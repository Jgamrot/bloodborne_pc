// SPDX-License-Identifier: GPL-2.0-or-later
#include "video_core/renderer_vulkan/vk_indirect_draw_guard.h"

#include <array>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>

#include "video_core/buffer_cache/buffer.h"
#include "video_core/host_shaders/indirect_draw_guard_comp.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/renderer_vulkan/vk_shader_util.h"

namespace Vulkan {

namespace {
struct Push {
    u32 first;
    u32 stride;
    u32 words;
    u32 draws;
    u32 max_total;
    u32 slot;
};

struct Skipped {
    u32 count;
    u32 pad;
    u32 last[2];
};

s64 NowNs() {
    return std::chrono::steady_clock::now().time_since_epoch().count();
}

// BB_INDIRECT_DRAW_GUARD_MAX: the most vertices (or indices) times instances one indirect draw may
// run. A value that is not a positive number keeps the default: 0 would skip every indirect draw.
u32 MaxTotal() {
    constexpr u32 Default = 1u << 24;
    const char* text = std::getenv("BB_INDIRECT_DRAW_GUARD_MAX");
    if (!text || !*text) {
        return Default;
    }
    char* end = nullptr;
    const unsigned long long value = std::strtoull(text, &end, 0);
    if (*end != '\0' || value == 0 || value > 0xFFFFFFFFull) {
        std::printf("Indirect draws: BB_INDIRECT_DRAW_GUARD_MAX=\"%s\" is not a number from 1 to "
                    "4294967295, keeping the default %u\n",
                    text, Default);
        return Default;
    }
    return static_cast<u32>(value);
}
} // namespace

bool IndirectDrawGuard::Enabled() {
    static const bool enabled = [] {
        const char* v = std::getenv("BB_INDIRECT_DRAW_GUARD");
        return !(v && v[0] == '0');
    }();
    return enabled;
}

IndirectDrawGuard::IndirectDrawGuard(const Instance& instance_, Scheduler& scheduler_)
    : instance{instance_}, scheduler{scheduler_} {
    const auto device = instance.GetDevice();
    checked = std::make_unique<VideoCore::Buffer>(instance, 0, SlotBytes,
                                                  VideoCore::MemoryType::DeviceLocal,
                                                  "Indirect draw arguments");
    skipped = std::make_unique<VideoCore::Buffer>(instance, 0, sizeof(Skipped),
                                                  VideoCore::MemoryType::HostCached,
                                                  "Indirect draws skipped");
    std::memset(skipped->mapped_data.data(), 0, sizeof(Skipped));
    skipped->Flush(0, sizeof(Skipped));
    max_total = MaxTotal();

    std::array<vk::DescriptorSetLayoutBinding, 3> bindings{};
    for (u32 i = 0; i < bindings.size(); ++i) {
        bindings[i] = {.binding = i,
                       .descriptorType = vk::DescriptorType::eStorageBuffer,
                       .descriptorCount = 1,
                       .stageFlags = vk::ShaderStageFlagBits::eCompute};
    }
    set_layout = Check(device.createDescriptorSetLayoutUnique({
        .flags = vk::DescriptorSetLayoutCreateFlagBits::ePushDescriptorKHR,
        .bindingCount = static_cast<u32>(bindings.size()),
        .pBindings = bindings.data(),
    }));
    const vk::PushConstantRange range{.stageFlags = vk::ShaderStageFlagBits::eCompute,
                                      .offset = 0,
                                      .size = sizeof(Push)};
    pipeline_layout = Check(device.createPipelineLayoutUnique({
        .setLayoutCount = 1,
        .pSetLayouts = &*set_layout,
        .pushConstantRangeCount = 1,
        .pPushConstantRanges = &range,
    }));
    const auto module = CompileSPV(INDIRECT_DRAW_GUARD_COMP, device);
    pipeline = Check(device.createComputePipelineUnique(
        {}, vk::ComputePipelineCreateInfo{
                .stage = {.stage = vk::ShaderStageFlagBits::eCompute,
                          .module = module,
                          .pName = "main"},
                .layout = *pipeline_layout,
            }));
    device.destroyShaderModule(module);
    last_report_ns = NowNs();
}

IndirectDrawGuard::~IndirectDrawGuard() = default;

std::optional<std::pair<vk::Buffer, u64>> IndirectDrawGuard::CheckArgs(
    const VideoCore::Buffer& args, u64 offset, u32 draws, u32 stride, bool is_indexed) {
    // The slots are used in turn, a call's draws together; one call may take a quarter of them at
    // most, so a slot is reused only long after the draw that read it.
    const u32 bytes = (draws * stride + 15) & ~15u;
    if (draws == 0 || bytes > SlotBytes / 4) {
        if (draws != 0 && !told_too_big.exchange(true, std::memory_order_relaxed)) {
            std::printf("Indirect draws: a call of %u draws is not checked (too many; "
                        "BB_INDIRECT_DRAW_GUARD)\n",
                        draws);
        }
        return std::nullopt;
    }
    u32 slot_byte = next_byte.fetch_add(bytes, std::memory_order_relaxed) % SlotBytes;
    if (slot_byte + bytes > SlotBytes) {
        slot_byte = 0; // the call does not fit before the end: from the start
    }
    // A storage binding starts at a multiple of the device's alignment: the arguments are
    // `first` dwords into it.
    const u64 alignment = instance.StorageMinAlignment();
    const u64 bind_offset = offset / alignment * alignment;
    const u32 first = static_cast<u32>((offset - bind_offset) / sizeof(u32));
    const u64 bind_size = (offset - bind_offset) + u64(draws) * stride;
    const Push push{first,        stride / 4u, is_indexed ? 5u : 4u, draws, max_total,
                    slot_byte / 4};
    scheduler.Record([this, source = args.Handle(), bind_offset, bind_size,
                      push](vk::CommandBuffer cmdbuf) {
        const vk::MemoryBarrier2 before{
            .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
            .srcAccessMask = vk::AccessFlagBits2::eMemoryWrite,
            .dstStageMask = vk::PipelineStageFlagBits2::eComputeShader,
            .dstAccessMask = vk::AccessFlagBits2::eShaderStorageRead |
                             vk::AccessFlagBits2::eShaderStorageWrite,
        };
        cmdbuf.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &before});
        const std::array<vk::DescriptorBufferInfo, 3> infos{{
            {source, bind_offset, bind_size},
            {checked->Handle(), 0, SlotBytes},
            {skipped->Handle(), 0, sizeof(Skipped)},
        }};
        std::array<vk::WriteDescriptorSet, 3> writes{};
        for (u32 i = 0; i < writes.size(); ++i) {
            writes[i] = {.dstBinding = i,
                         .descriptorCount = 1,
                         .descriptorType = vk::DescriptorType::eStorageBuffer,
                         .pBufferInfo = &infos[i]};
        }
        cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, *pipeline);
        cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, *pipeline_layout, 0, writes);
        cmdbuf.pushConstants(*pipeline_layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push),
                             &push);
        cmdbuf.dispatch((push.draws + 63) / 64, 1, 1);
        const vk::MemoryBarrier2 after{
            .srcStageMask = vk::PipelineStageFlagBits2::eComputeShader,
            .srcAccessMask = vk::AccessFlagBits2::eShaderStorageWrite,
            .dstStageMask = vk::PipelineStageFlagBits2::eDrawIndirect,
            .dstAccessMask = vk::AccessFlagBits2::eIndirectCommandRead,
        };
        cmdbuf.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &after});
    });
    Report();
    return std::pair{checked->Handle(), u64(slot_byte)};
}

void IndirectDrawGuard::Report() {
    const s64 now = NowNs();
    s64 last = last_report_ns.load(std::memory_order_relaxed);
    if (now - last < 5'000'000'000 ||
        !last_report_ns.compare_exchange_strong(last, now, std::memory_order_relaxed)) {
        return;
    }
    skipped->Invalidate(0, sizeof(Skipped));
    const auto* s = reinterpret_cast<const volatile Skipped*>(skipped->mapped_data.data());
    const u32 count = s->count;
    const u32 before = reported.exchange(count, std::memory_order_relaxed);
    if (count != before) {
        std::printf("Indirect draws: %u skipped in all (garbage counts, the last %u x %u "
                    "instances; BB_INDIRECT_DRAW_GUARD)\n",
                    count, s->last[0], s->last[1]);
    }
}

} // namespace Vulkan
