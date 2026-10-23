// SPDX-FileCopyrightText: Copyright 2024 shadPS4 Emulator Project
// SPDX-License-Identifier: GPL-2.0-or-later

#include <chrono>
#include <array>
#include <map>
#include <optional>
#include <unordered_map>
#include <algorithm>
#include <bit>
#include <cstdio>
#include <cstdlib>
#include <tuple>
#include <magic_enum/magic_enum.hpp>
#include "bbport_copy.h"
#include "bbport_toggles.h"
#include "common/alignment.h"
#include "core/memory.h"
#include "video_core/amdgpu/liverpool.h"
#include "video_core/buffer_cache/buffer.h"
#include "video_core/buffer_cache/buffer_cache.h"
#include "video_core/buffer_cache/memory_tracker.h"
#include "video_core/renderer_vulkan/vk_graphics_pipeline.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_runtime.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/texture_cache/texture_cache.h"

#include <vk_mem_alloc.h>

namespace VideoCore {

static constexpr size_t GDS_BUFFER_SIZE = 64_KB;
static constexpr size_t NULL_INDEX_BUFFER_SIZE = 16;
static constexpr size_t STREAM_BUFFER_SIZE = 128_MB;

static constexpr auto ARENA_USAGE =
    vk::BufferUsageFlagBits::eTransferSrc | vk::BufferUsageFlagBits::eTransferDst |
    vk::BufferUsageFlagBits::eUniformBuffer | vk::BufferUsageFlagBits::eStorageBuffer |
    vk::BufferUsageFlagBits::eIndexBuffer | vk::BufferUsageFlagBits::eVertexBuffer |
    vk::BufferUsageFlagBits::eIndirectBuffer | vk::BufferUsageFlagBits::eShaderDeviceAddress;

std::optional<u32> FindMemoryType(const vk::PhysicalDeviceMemoryProperties& properties,
                                  vk::MemoryPropertyFlags wanted, u32 memory_type_bits) {
    for (u32 i = 0; i < properties.memoryTypeCount; ++i) {
        if (((memory_type_bits >> i) & 1) == 0) {
            continue;
        }
        const auto flags = properties.memoryTypes[i].propertyFlags;
        if ((flags & wanted) == wanted) {
            return i;
        }
    }
    return std::nullopt;
}

BufferCache::BufferCache(const Vulkan::Instance& instance_, Vulkan::Scheduler& scheduler_,
                         Vulkan::Runtime& runtime_, AmdGpu::Liverpool* liverpool_,
                         TextureCache& texture_cache_, PageManager& tracker)
    : instance{instance_}, scheduler{scheduler_}, runtime{runtime_},
      staging_pool{runtime_.GetStagingPool()}, liverpool{liverpool_},
      memory{Core::Memory::Instance()}, texture_cache{texture_cache_},
      memory_tracker{std::make_unique<MemoryTracker>(tracker)},
      stream_buffer{instance, scheduler, MemoryType::Stream, STREAM_BUFFER_SIZE},
      gds_buffer{instance, 0, GDS_BUFFER_SIZE, MemoryType::Stream, "GDS Buffer"},
      memory_semaphore{instance} {
    while (arena_page_bits > MIN_ARENA_PAGE_BITS &&
           (u64{2} << arena_page_bits) > instance.GetMaxBufferSize()) {
        --arena_page_bits;
    }
    arena_page_size = u64{1} << arena_page_bits;
    num_arena_pages = u64{1} << (ADDRESS_SPACE_BITS - arena_page_bits);
    const char* migrate_env = std::getenv("BB_ARENA_MIGRATE");
    migrate_arenas = migrate_env && migrate_env[0] == '1';
    if (arena_page_bits != MAX_ARENA_PAGE_BITS) {
        LOG_INFO(Render_Vulkan, "Buffer arenas of {} MiB (driver buffer limit {} MiB)",
                 arena_page_size >> 20, instance.GetMaxBufferSize() >> 20);
    }
    const vk::BufferCreateInfo probe_ci = {
        .flags =
            vk::BufferCreateFlagBits::eSparseBinding | vk::BufferCreateFlagBits::eSparseResidency,
        .size = arena_page_size,
        .usage = ARENA_USAGE,
        .sharingMode = vk::SharingMode::eExclusive,
    };
    const vk::DeviceBufferMemoryRequirements req_info = {
        .pCreateInfo = &probe_ci,
    };
    const auto device = instance.GetDevice();
    const auto reqs = device.getBufferMemoryRequirements(req_info).memoryRequirements;
    block_size = Common::AlignUp(std::max<u64>(reqs.alignment, MIN_BLOCK_SIZE), reqs.alignment);
    ASSERT_MSG(std::popcount(block_size) == 1, "Sparse block size {} is not a power of 2",
               block_size);
    block_shift = std::bit_width(block_size) - 1;
    blocks_per_arena_page = arena_page_size / block_size;
    blocks_per_arena_page_shift = arena_page_bits - block_shift;
    chunk_shift = std::max<u32>(CHUNK_BITS, block_shift);
    blocks_per_chunk_shift = chunk_shift - block_shift;
    chunk_last_use.resize(u64{1} << (ADDRESS_SPACE_BITS - chunk_shift));
    arena_memory_type_index =
        FindMemoryType(instance.GetMemoryProperties(), vk::MemoryPropertyFlagBits::eDeviceLocal,
                       reqs.memoryTypeBits)
            .value();
    arena_memory_type_bits = reqs.memoryTypeBits;
    // bbport (Supermedo/bloodborne_pc 5f65e2d): discrete GPUs keep a reserve of VRAM for the
    // guest memory backing (AllocateArenaChunk), used only once VRAM is otherwise full. The
    // backing grows as areas load and, on NVIDIA, cannot be outside VRAM (sparse buffers accept
    // VRAM types only): on 4 GB cards textures filled VRAM and the next area stopped the game
    // with ErrorOutOfDeviceMemory (Jgamrot/bloodborne_pc#31). BB_ARENA_RESERVE=0: no reserve.
    const char* reserve_env = std::getenv("BB_ARENA_RESERVE");
    if (!instance.IsIntegrated() && !(reserve_env && reserve_env[0] == '0')) {
        const auto& props = instance.GetMemoryProperties();
        const u64 heap =
            props.memoryHeaps[props.memoryTypes[arena_memory_type_index].heapIndex].size;
        const u64 size = Common::AlignDown(std::min<u64>(512_MB, heap / 8), u64{1} << chunk_shift);
        if (size) {
            const auto [result, memory] = device.allocateMemory({
                .allocationSize = size,
                .memoryTypeIndex = arena_memory_type_index,
            });
            if (result == vk::Result::eSuccess) {
                reserve_memory = memory;
                reserve_size = size;
                LOG_INFO(Render_Vulkan, "Guest memory backing: {} MiB of VRAM kept in reserve",
                         size >> 20);
            }
        }
    }

    const u64 bda_pagetable_size =
        (blocks_per_arena_page * num_arena_pages) * sizeof(vk::DeviceAddress);
    fault_manager = std::make_unique<FaultManager>(instance, scheduler, *this, block_shift,
                                                   blocks_per_arena_page * num_arena_pages);
    bda_pagetable_buffer = std::make_unique<Buffer>(
        instance, 0, bda_pagetable_size, MemoryType::DeviceLocal, "BDA Page Table Buffer");
    runtime.FillBuffer(bda_pagetable_buffer.get(), 0u, bda_pagetable_size, 0u);
    if (!instance.IsMaintenance6Supported()) {
        null_index_buffer = std::make_unique<Buffer>(instance, 0, NULL_INDEX_BUFFER_SIZE,
                                                     MemoryType::DeviceLocal, "Null Index Buffer");
        runtime.FillBuffer(null_index_buffer.get(), 0u, NULL_INDEX_BUFFER_SIZE, 0u);
    }
}

BufferCache::~BufferCache() = default;

void BufferCache::InvalidateMemory(VAddr device_addr, u64 size, bool assume_locks) {
    memory_tracker->InvalidateRegion(device_addr, size, [this, device_addr, size, assume_locks] {
        ReadMemory(device_addr, size, true, assume_locks);
    });
}

// bbport: the game fills its per-frame buffers (constants, skinning output) sequentially and
// every 4 KiB page cost a protection fault (~110k/s in Hunter's Nightmare, a fifth of each
// render worker's time in the kernel). A fault unprotects the aligned window around it instead;
// pages marked CPU-modified without being written only cost an upload when bound.
// Item: context = BufferCache, source = guest address, destination = host pointer, size,
// extra = the Buffer whose mapping holds the destination (flushed after the copy).
void BufferCache::RunGuestCopy(const BbCopy::Item& item) {
    auto* cache = static_cast<BufferCache*>(item.context);
    auto* dst = reinterpret_cast<u8*>(item.destination);
    cache->memory->CopySparseMemory(item.source, dst, item.size);
    auto* buffer = reinterpret_cast<Buffer*>(item.extra);
    buffer->Flush(dst - buffer->mapped_data.data(), item.size);
}

// Small guest copies run on the recording thread (it spins for work: no wakeup, and it is
// idle most of the time); PoolSmallCopies (toggle 524288) batches them for the copy threads.
void BufferCache::SmallGuestCopy(const BbCopy::Item& item) {
    if (scheduler.IsRecordingDeferred() && !BbToggle::Disabled(BbToggle::PoolSmallCopies)) {
        scheduler.RecordHostCopy([item] { item.run(item); });
        return;
    }
    BbCopy::QueueCopy(item);
}

void BufferCache::ExtendWriteFault(VAddr device_addr) {
    static const u64 window = [] {
        const char* env = std::getenv("BB_FAULT_WINDOW");
        const u64 kib = env ? std::strtoull(env, nullptr, 10) : 256;
        return std::bit_ceil(std::clamp<u64>(kib, 4, 1024)) * 1024;
    }();
    if (window <= TRACKER_BYTES_PER_PAGE || BbToggle::Disabled(BbToggle::FaultWindow)) {
        return;
    }
    memory_tracker->ExtendWriteFault(Common::AlignDown(device_addr, window), window);
}

void BufferCache::ReadMemory(VAddr device_addr, u64 size, bool is_write, bool assume_locks) {
    const auto flush_request = [this, device_addr, size, is_write] {
        const u32 first_block = device_addr >> block_shift;
        const u32 last_block = (device_addr + size - 1) >> block_shift;
        const auto* arena = GetArena(first_block, last_block);

        // GPU-modified ranges come as many small scattered islands,
        // so the download is widened to a window around the request
        constexpr u64 WindowSize = 512_KB;
        const VAddr arena_end = arena->cpu_addr + arena->size_bytes;
        const VAddr window_start =
            std::max<VAddr>(Common::AlignDown(device_addr, WindowSize), arena->cpu_addr);
        const VAddr window_end = std::min<VAddr>(
            std::max<VAddr>(window_start + WindowSize, device_addr + size), arena_end);
        DownloadMemory(arena, window_start, window_end - window_start);
        if (is_write) {
            memory_tracker->MarkRegionAsCpuModified(device_addr, size);
        }
    };
    if (assume_locks) {
        flush_request();
    } else {
        liverpool->SendCommand<true>(std::move(flush_request));
    }
}

void BufferCache::DownloadMemory(const Buffer* arena, VAddr device_addr, u64 size) {
    boost::container::small_vector<vk::BufferCopy, 1> copies;
    u64 total_size_bytes = 0;
    const VAddr arena_base = arena->cpu_addr;
    memory_tracker->ForEachDownloadRange<false>(device_addr, size, [&](u64 address, u64 size) {
        const auto add_download = [&](VAddr start, VAddr end) {
            const u64 new_offset = start - arena_base;
            const u64 new_size = end - start;
            copies.push_back(vk::BufferCopy{
                .srcOffset = new_offset,
                .dstOffset = total_size_bytes,
                .size = new_size,
            });
            // Align up to avoid cache conflicts
            constexpr u64 align = 64ULL;
            constexpr u64 mask = ~(align - 1ULL);
            total_size_bytes += (new_size + align - 1) & mask;
        };
        gpu_modified_ranges.ForEachInRange(address, size, add_download);
        gpu_modified_ranges.Subtract(address, size);
    });
    if (total_size_bytes == 0) {
        return;
    }
    const auto download = staging_pool.Request(total_size_bytes, VideoCore::MemoryType::HostCached);
    for (auto& copy : copies) {
        copy.dstOffset += download.offset;
    }
    runtime.CopyBuffer(arena, download.buffer, copies);
    scheduler.Finish();

    download.buffer->Invalidate(download.offset, download.size);
    for (const auto& copy : copies) {
        auto* dst_addr = std::bit_cast<u8*>(arena_base + copy.srcOffset);
        memory->TryWriteBacking(dst_addr, download.mapped + (copy.dstOffset - download.offset),
                                copy.size);
    }
    memory_tracker->UnmarkRegionAsGpuModified(device_addr, size);
}

namespace {
// bbport: BB_BUFFER_STATS=1 — how buffer bindings reach the GPU, by guest region (256 MiB),
// printed every 5 s: small read-only copies into the stream buffer, arena bindings, and the
// bytes those re-upload after CPU writes. Input for engine-level short paths.
struct BufferStats {
    struct Region {
        u64 stream_count{}, stream_bytes{}, arena_count{}, arena_bytes{}, upload_bytes{};
    };
    std::map<u64, Region> regions;
    /// Hot window: frame of the last binding per 64 KiB block, and the distribution of the
    /// frames between uses (1, 2, 3, 4, 5-8, 9-16, 17+): the ring's reuse distance.
    std::unordered_map<u64, u64> last_use;
    std::array<u64, 7> reuse{};
    std::chrono::steady_clock::time_point window = std::chrono::steady_clock::now();
    u64 calls = 0;
};
/// 256 MiB regions; 1 MiB inside the hot 0x104xxxxxxx window (the engine's frame data).
BufferStats& Stats();
void NoteHotUse(VAddr address, u32 size) {
    if ((address >> 28) != 0x104) {
        return;
    }
    auto& st = Stats();
    const u64 frame = BbStats::gpu_frames.load(std::memory_order_relaxed);
    for (u64 block = address >> 16; block <= (address + size - 1) >> 16; ++block) {
        auto [it, inserted] = st.last_use.try_emplace(block, frame);
        if (!inserted && it->second != frame) {
            const u64 d = frame - it->second;
            ++st.reuse[d <= 4 ? d - 1 : d <= 8 ? 4 : d <= 16 ? 5 : 6];
            it->second = frame;
        }
    }
}
u64 RegionKey(VAddr address) {
    return (address >> 28) == 0x104 ? (address >> 20) | (1ull << 40) : address >> 28;
}
bool BufferStatsEnabled() {
    static const bool enabled = [] {
        const char* value = std::getenv("BB_BUFFER_STATS");
        return value && value[0] == '1';
    }();
    return enabled;
}
BufferStats& Stats() {
    static BufferStats stats;
    return stats;
}
void PrintBufferStats() {
    auto& st = Stats();
    if ((++st.calls & 4095) != 0) {
        return;
    }
    const auto now = std::chrono::steady_clock::now();
    const double seconds = std::chrono::duration<double>(now - st.window).count();
    if (seconds < 5.0) {
        return;
    }
    std::printf("Buffer stats (%.1f s, per second): region, stream copies/bytes, arena bindings, "
                "re-uploaded bytes\n", seconds);
    std::printf("  hot window reuse distance in frames (1,2,3,4,5-8,9-16,17+): %llu %llu %llu %llu "
                "%llu %llu %llu\n",
                (unsigned long long)st.reuse[0], (unsigned long long)st.reuse[1],
                (unsigned long long)st.reuse[2], (unsigned long long)st.reuse[3],
                (unsigned long long)st.reuse[4], (unsigned long long)st.reuse[5],
                (unsigned long long)st.reuse[6]);
    st.reuse = {};
    for (const auto& [region, r] : st.regions) {
        const u64 base = (region >> 40) ? (region & ((1ull << 40) - 1)) << 20 : region << 28;
        if ((region >> 40) && r.stream_bytes + r.upload_bytes < 1e6 * seconds) {
            continue; // quiet MiB of the hot window
        }
        std::printf("  %#012llx: %8.0f copies %8.2f MB, %8.0f arena %8.2f MB bound, %8.2f MB uploads\n",
                    static_cast<unsigned long long>(base), r.stream_count / seconds,
                    r.stream_bytes / seconds / 1e6, r.arena_count / seconds,
                    r.arena_bytes / seconds / 1e6,
                    r.upload_bytes / seconds / 1e6);
    }
    st.regions.clear();
    st.window = now;
}
} // namespace

std::pair<const Buffer*, u64> BufferCache::ObtainBuffer(VAddr device_addr, u32 size,
                                                        bool is_written, bool is_texel_buffer) {
    const bool stats = BufferStatsEnabled();
    if (stats) {
        PrintBufferStats();
        NoteHotUse(device_addr, size);
    }
    // For read-only buffers use device local stream buffer to reduce renderpass breaks.
    if (!is_written && size <= STREAM_THRESHOLD && !IsRegionGpuModified(device_addr, size)) {
        if (stats) {
            auto& region = Stats().regions[RegionKey(device_addr)];
            ++region.stream_count;
            region.stream_bytes += size;
        }
        // bbport: the guest data is copied on a copy thread, started now; submission and
        // guest-visible fences wait for it (Scheduler::WaitHostCopies).
        if (!stream_buffer.mapped_data.empty() &&
            !BbToggle::Disabled(BbToggle::DeferredStreamCopies)) {
            if (const auto offset = stream_buffer.Reserve(size, instance.UniformMinAlignment())) {
                SmallGuestCopy({
                    .run = &RunGuestCopy,
                    .context = this,
                    .source = device_addr,
                    .destination = reinterpret_cast<u64>(stream_buffer.mapped_data.data() + *offset),
                    .size = size,
                    .extra = reinterpret_cast<u64>(static_cast<Buffer*>(&stream_buffer)),
                });
                return {&stream_buffer, *offset};
            }
        }
        const auto [data, offset] = stream_buffer.Map(size, instance.UniformMinAlignment());
        memory->CopySparseMemory(device_addr, data, size);
        stream_buffer.Commit();
        return {&stream_buffer, offset};
    }
    const u64 first_block = device_addr >> block_shift;
    const u64 last_block = (device_addr + size - 1) >> block_shift;
    const auto* arena = GetArena(first_block, last_block);
    EnsureResident(arena, first_block, last_block);
    const u64 uploaded_before = BbStats::buffer_upload_bytes.load(std::memory_order_relaxed);
    SynchronizeMemory(arena, device_addr, size, is_written, is_texel_buffer);
    if (stats) {
        auto& region = Stats().regions[RegionKey(device_addr)];
        ++region.arena_count;
        region.arena_bytes += size;
        region.upload_bytes +=
            BbStats::buffer_upload_bytes.load(std::memory_order_relaxed) - uploaded_before;
    }
    if (is_written) {
        gpu_modified_ranges.Add(device_addr, size);
    }
    return {arena, arena->Offset(device_addr)};
}

std::pair<const Buffer*, u64> BufferCache::ObtainBufferForImage(VAddr device_addr, u32 size) {
    if (IsRegionGpuModified(device_addr, size)) {
        return ObtainBuffer(device_addr, size, false);
    }
    const auto staging = staging_pool.Request(size, VideoCore::MemoryType::HostUncached,
                                              instance.StorageMinAlignment());
    if (!BbToggle::Disabled(BbToggle::DeferredUploads)) {
        // bbport: texture data is copied on the copy threads (streaming: 100+ MB per frame);
        // the upload reads the staging only after submission, which waits for the copies.
        constexpr u64 Chunk = 1_MB;
        for (u64 offset = 0; offset < staging.size; offset += Chunk) {
            const BbCopy::Item item{
                .run = &RunGuestCopy,
                .context = this,
                .source = device_addr + offset,
                .destination = reinterpret_cast<u64>(staging.mapped + offset),
                .size = std::min(Chunk, staging.size - offset),
                .extra = reinterpret_cast<u64>(staging.buffer),
            };
            if (staging.size < Chunk) {
                SmallGuestCopy(item);
            } else {
                BbCopy::Async([item] { item.run(item); });
            }
        }
        return {staging.buffer, staging.offset};
    }
    memory->CopySparseMemory(device_addr, staging.mapped, staging.size);
    staging.Flush();
    return {staging.buffer, staging.offset};
}

bool BufferCache::IsRegionCpuModified(VAddr addr, size_t size) {
    return memory_tracker->IsRegionCpuModified(addr, size);
}

bool BufferCache::IsRegionGpuModified(VAddr addr, size_t size) {
    return memory_tracker->IsRegionGpuModified(addr, size);
}

void BufferCache::ProcessFaultBuffer() {
    fault_manager->ProcessFaultBuffer();
}

void BufferCache::SynchronizeDmaBuffers() {
    // bbport: resident ranges merge across arena pages (and sizes are u32 below), so each is
    // synchronized a page (and at most 1 GiB) at a time, in an arena that includes it.
    const u64 max_blocks = u64{1} << (30 - block_shift);
    for (const auto& range : resident_ranges) {
        for (u64 start = range.start; start < range.end;) {
            const u64 page = start >> blocks_per_arena_page_shift;
            const u64 end = std::min({range.end, (page + 1) << blocks_per_arena_page_shift,
                                      start + max_blocks});
            if (const auto arenas = ArenasCovering(page); !arenas.empty()) {
                SynchronizeMemory(arenas.front(), start << block_shift,
                                  u32((end - start) << block_shift), false, false);
            }
            start = end;
        }
    }
}

boost::container::small_vector<const Buffer*, 2> BufferCache::ArenasCovering(u64 page) const {
    boost::container::small_vector<const Buffer*, 2> result;
    if (address_space[page]) {
        result.push_back(address_space[page]);
    }
    if (!migrate_arenas && page > 0) {
        const Buffer* previous = address_space[page - 1];
        if (previous && previous->cpu_addr + previous->size_bytes > (page << arena_page_bits)) {
            result.push_back(previous);
        }
    }
    return result;
}

void BufferCache::BindResidentRanges(const Buffer* arena) {
    const u64 base_block = arena->cpu_addr >> block_shift;
    const u64 end_block = (arena->cpu_addr + arena->size_bytes) >> block_shift;
    auto* bind = BindsForArena(arena);
    resident_ranges.ForEachInRange(base_block, end_block, [&](const Backing& backing) {
        const u64 start = std::max(base_block, backing.start);
        const u64 end = std::min(end_block, backing.end);
        bind->binds.push_back(vk::SparseMemoryBind{
            .resourceOffset = (start - base_block) << block_shift,
            .size = (end - start) << block_shift,
            .memory = backing.memory,
            .memoryOffset = backing.offset + ((start - backing.start) << block_shift),
        });
        for (u64 chunk = start >> blocks_per_chunk_shift;
             chunk < (end >> blocks_per_chunk_shift); ++chunk) {
            chunk_arenas[chunk].push_back(arena);
        }
    });
}

const Buffer* BufferCache::GetArena(u64 first_block, u64 last_block) {
    const u64 first_page = first_block >> blocks_per_arena_page_shift;
    const u64 last_page = last_block >> blocks_per_arena_page_shift;
    ASSERT_MSG(last_page - first_page <= 1,
               "Buffer request cannot span more than two VA arena pages");

    // bbport: "Migrating arena" in the logs of Jgamrot/bloodborne_pc#31, #37 and #47 (missing
    // objects and textures, crashes). A merged arena was bound only to the memory resident when
    // it was made; memory made resident later went into the new arena alone, while work still
    // using the old one read zeros there (Awakenchan/BloodBorneButPc 0.9.32 beta 2). Merges of
    // arenas that already spanned two pages also grew past the driver's buffer size limit once
    // the game's memory spanned more pages. Each page now has its own arena of two pages.
    if (!migrate_arenas) {
        if (const auto* arena = address_space[first_page]) {
            return arena;
        }
        const u64 num_pages = std::min<u64>(2, num_arena_pages - first_page);
        const auto* new_arena =
            &arenas.emplace_back(instance, first_page << arena_page_bits,
                                 num_pages << arena_page_bits, MemoryType::Sparse);
        address_space[first_page] = new_arena;
        BindResidentRanges(new_arena);
        return new_arena;
    }

    const auto* first_arena = address_space[first_page];
    const auto* last_arena = address_space[last_page];
    if (first_arena == last_arena) {
        if (!first_arena) {
            const u64 base_block = Common::AlignDownPow2<u64>(first_block, blocks_per_arena_page);
            const u64 num_pages = last_page - first_page + 1;
            const auto* new_arena =
                &arenas.emplace_back(instance, base_block << block_shift,
                                     num_pages << arena_page_bits, MemoryType::Sparse);
            address_space[first_page] = new_arena;
            address_space[last_page] = new_arena;
        }
        return address_space[first_page];
    }

    LOG_WARNING(Render, "Migrating arena");

    const u64 first_addr = first_arena ? first_arena->cpu_addr : (first_page << arena_page_bits);
    const u64 first_size = first_arena ? first_arena->size_bytes : arena_page_size;
    const u64 last_size = last_arena ? last_arena->size_bytes : arena_page_size;

    const u64 total_size = first_size + last_size;
    auto* new_arena = &arenas.emplace_back(instance, first_addr, total_size, MemoryType::Sparse);
    BindResidentRanges(new_arena);

    u64 base_page = first_addr >> arena_page_bits;
    for (u32 page = 0; page < (first_size >> arena_page_bits); ++page) {
        address_space[base_page + page] = new_arena;
    }
    base_page = last_page;
    for (u32 page = 0; page < (last_size >> arena_page_bits); ++page) {
        address_space[base_page + page] = new_arena;
    }
    return new_arena;
}

BufferCache::ChunkBacking BufferCache::AllocateArenaChunk(vk::MemoryAllocateInfo alloc_info) {
    // BB_ARENA_LIMIT_MB=N: VRAM counts as full once N MiB are backed by allocations of their own
    // (tests the reserve and the system memory fallback).
    static const u64 arena_limit = [] {
        const char* env = std::getenv("BB_ARENA_LIMIT_MB");
        return env ? std::strtoull(env, nullptr, 10) << 20 : 0;
    }();
    vk::Result result = vk::Result::eErrorOutOfDeviceMemory;
    vk::DeviceMemory memory{};
    if (!arena_limit || vram_allocated + alloc_info.allocationSize <= arena_limit) {
        std::tie(result, memory) = instance.GetDevice().allocateMemory(alloc_info);
    }
    if (result == vk::Result::eSuccess) {
        vram_allocated += alloc_info.allocationSize;
        return {memory, 0, true};
    }
    if (result == vk::Result::eErrorOutOfDeviceMemory && reserve_memory) {
        // The reserve kept at start (VRAM; on NVIDIA no other memory type takes sparse buffers).
        std::optional<u64> slot;
        {
            std::scoped_lock lk{reserve_mutex};
            if (!reserve_free.empty()) {
                slot = reserve_free.back();
                reserve_free.pop_back();
            }
        }
        if (!slot && reserve_size - reserve_next >= alloc_info.allocationSize) {
            slot = reserve_next;
            const u64 quarter_before = reserve_next * 4 / reserve_size;
            reserve_next += alloc_info.allocationSize;
            if (*slot == 0 || reserve_next * 4 / reserve_size != quarter_before) {
                std::printf("GPU: video memory full: game memory from its reserve (%llu of %llu "
                            "MiB handed out)\n",
                            static_cast<unsigned long long>(reserve_next >> 20),
                            static_cast<unsigned long long>(reserve_size >> 20));
                std::fflush(stdout);
            }
        }
        if (slot) {
            return {reserve_memory, *slot, false};
        }
    }
    if (result == vk::Result::eErrorOutOfDeviceMemory) {
        // bbport (Supermedo/bloodborne_pc 96502c8): VRAM full. The guest memory the GPU uses is
        // backed here and only grows as areas load; on 4-8 GB cards it ran out
        // ("ErrorOutOfDeviceMemory" stopped the game). Another memory type the arena accepts,
        // outside VRAM (system memory the GPU reaches), is slower but keeps the game going.
        const auto& props = instance.GetMemoryProperties();
        const u32 vram_heap = props.memoryTypes[arena_memory_type_index].heapIndex;
        for (u32 i = 0; i < props.memoryTypeCount && result != vk::Result::eSuccess; ++i) {
            if (((arena_memory_type_bits >> i) & 1) == 0 ||
                props.memoryTypes[i].heapIndex == vram_heap) {
                continue;
            }
            alloc_info.memoryTypeIndex = i;
            std::tie(result, memory) = instance.GetDevice().allocateMemory(alloc_info);
        }
        if (result == vk::Result::eSuccess) {
            Vulkan::NoteOverBudget("buffer");
        } else {
            std::printf("Buffer cache: no memory left for the guest memory backing (%llu MiB "
                        "more); VRAM and the system-memory types the arena accepts are full\n",
                        (unsigned long long)(alloc_info.allocationSize >> 20));
        }
    }
    return {Vulkan::Check(vk::ResultValue<vk::DeviceMemory>{result, memory}), 0, false};
}

void BufferCache::EnsureResident(const Buffer* arena, u64 first_block, u64 last_block) {
    // bbport: whole chunks, each its own allocation (see chunk_memory), and their last use.
    const u64 first_chunk = first_block >> blocks_per_chunk_shift;
    const u64 last_chunk = last_block >> blocks_per_chunk_shift;
    const u32 now = gc_second.load(std::memory_order_relaxed);
    for (u64 chunk = first_chunk; chunk <= last_chunk; ++chunk) {
        chunk_last_use[chunk] = now;
    }
    first_block = first_chunk << blocks_per_chunk_shift;
    last_block = ((last_chunk + 1) << blocks_per_chunk_shift) - 1;

    u32 resident_blocks{};
    IntervalList bind_ranges;
    resident_ranges.ForEachGap(first_block, last_block + 1, [&](u64 start, u64 end) {
        resident_blocks += end - start;
        bind_ranges.Add({start, end});
    });

    if (bind_ranges.Empty()) {
        return;
    }
    BbStats::Timer timer{BbStats::t_resident};

    const vk::MemoryAllocateInfo alloc_info = {
        .allocationSize = u64{1} << chunk_shift,
        .memoryTypeIndex = arena_memory_type_index,
    };

    boost::container::small_vector<vk::BufferCopy, 8> copies;
    const auto staging =
        staging_pool.Request(resident_blocks * sizeof(vk::DeviceAddress), MemoryType::HostUncached);

    auto* bda_addrs = reinterpret_cast<vk::DeviceAddress*>(staging.mapped);
    u64 offset = staging.offset;
    for (const auto& range : bind_ranges) {
        // Residency only ever changes by whole chunks, so the gaps are whole chunks.
        for (u64 start = range.start; start < range.end; start += u64{1} << blocks_per_chunk_shift) {
            const u64 chunk = start >> blocks_per_chunk_shift;
            const ChunkBacking chunk_backing = AllocateArenaChunk(alloc_info);
            chunk_memory[chunk] = chunk_backing;

            Backing backing;
            backing.start = start;
            backing.end = start + (u64{1} << blocks_per_chunk_shift);
            backing.memory = chunk_backing.memory;
            backing.offset = chunk_backing.offset;
            resident_ranges.Add(backing);

            LOG_INFO(Render, "Making range start={}, end={} resident", backing.start,
                     backing.end);

            // bbport: bound in every arena that includes the chunk (two where arenas overlap,
            // see address_space), so that work using either reads the same memory.
            boost::container::small_vector<const Buffer*, 2> targets{arena};
            if (!migrate_arenas) {
                targets = ArenasCovering(start >> blocks_per_arena_page_shift);
            }
            for (const Buffer* target : targets) {
                chunk_arenas[chunk].push_back(target);
                const u64 resource_offset = (start << block_shift) - target->cpu_addr;
                // A release of this chunk that has not been submitted yet: this bind replaces it.
                auto& pending = BindsForArena(target)->binds;
                pending.erase(std::remove_if(pending.begin(), pending.end(),
                                             [&](const vk::SparseMemoryBind& bind) {
                                                 return !bind.memory &&
                                                        bind.resourceOffset == resource_offset;
                                             }),
                              pending.end());
                pending.push_back(vk::SparseMemoryBind{
                    .resourceOffset = resource_offset,
                    .size = alloc_info.allocationSize,
                    .memory = backing.memory,
                    .memoryOffset = backing.offset,
                });
            }

            const u64 resource_offset = (start << block_shift) - arena->cpu_addr;
            for (u64 block = 0; block < alloc_info.allocationSize; block += block_size) {
                *(bda_addrs++) = arena->BufferDeviceAddress() + resource_offset + block;
            }
            const u64 copy_size = (backing.end - backing.start) * sizeof(vk::DeviceAddress);
            copies.emplace_back(offset, backing.start * sizeof(vk::DeviceAddress), copy_size);
            offset += copy_size;
        }
    }

    staging.Flush();
    runtime.CopyBuffer(staging.buffer, bda_pagetable_buffer.get(), copies);
}

bool BufferCache::SynchronizeMemory(const Buffer* arena, VAddr device_addr, u32 size,
                                    bool is_written, bool is_texel_buffer) {
    boost::container::small_vector<vk::BufferCopy, 4> copies;
    size_t total_size_bytes{};
    const Buffer* src_buffer{};
    memory_tracker->ForEachUploadRange(
        device_addr, size, is_written,
        [&](u64 addr, u64 size) {
            copies.emplace_back(total_size_bytes, addr, size);
            total_size_bytes += size;
        },
        [&] { src_buffer = UploadCopies(arena, copies, total_size_bytes); });

    if (src_buffer) {
        runtime.CopyBuffer(src_buffer, arena, copies);
    }
    if (is_texel_buffer && !is_written) {
        return SynchronizeMemoryFromImage(arena, device_addr, size);
    }
    return false;
}

const Buffer* BufferCache::UploadCopies(const Buffer* arena, std::span<vk::BufferCopy> copies,
                                        size_t total_size_bytes) {
    if (copies.empty()) {
        return nullptr;
    }
    BbStats::buffer_upload_bytes.fetch_add(total_size_bytes, std::memory_order_relaxed);
    const auto staging = staging_pool.Request(total_size_bytes, MemoryType::HostUncached);
    // bbport: the guest memory is copied into staging on the copy threads, started now in
    // groups of about 1 MiB; submission and guest-visible fences wait for them
    // (Scheduler::WaitHostCopies).
    if (!BbToggle::Disabled(BbToggle::DeferredUploads) && total_size_bytes < 1_MB) {
        // Small uploads join the calling thread's batch.
        for (auto& copy : copies) {
            SmallGuestCopy({
                .run = &RunGuestCopy,
                .context = this,
                .source = copy.dstOffset,
                .destination = reinterpret_cast<u64>(staging.mapped + copy.srcOffset),
                .size = copy.size,
                .extra = reinterpret_cast<u64>(staging.buffer),
            });
            copy.srcOffset += staging.offset;
            copy.dstOffset -= arena->cpu_addr;
        }
        return staging.buffer;
    }
    if (!BbToggle::Disabled(BbToggle::DeferredUploads)) {
        struct HostCopy {
            VAddr source;
            u8* destination;
            u64 size;
        };
        using Group = boost::container::small_vector<HostCopy, 8>;
        auto group = std::make_shared<Group>();
        u64 group_bytes = 0;
        const auto launch = [&] {
            BbCopy::Async([group, memory = memory, staging] {
                for (const auto& copy : *group) {
                    memory->CopySparseMemory(copy.source, copy.destination, copy.size);
                }
                staging.Flush();
            });
        };
        for (auto& copy : copies) {
            group->push_back({copy.dstOffset, staging.mapped + copy.srcOffset, copy.size});
            group_bytes += copy.size;
            copy.srcOffset += staging.offset;
            copy.dstOffset -= arena->cpu_addr;
            if (group_bytes >= 1_MB) {
                launch();
                group = std::make_shared<Group>();
                group_bytes = 0;
            }
        }
        if (!group->empty()) {
            launch();
        }
        return staging.buffer;
    }
    const auto copy = [&](std::size_t i) {
        memory->CopySparseMemory(copies[i].dstOffset, staging.mapped + copies[i].srcOffset,
                                 copies[i].size);
    };
    if (total_size_bytes >= 2_MB && copies.size() > 1) {
        BbCopy::ParallelFor(copies.size(), copy);
    } else {
        for (std::size_t i = 0; i < copies.size(); ++i) {
            copy(i);
        }
    }
    for (auto& copy : copies) {
        copy.srcOffset += staging.offset;
        copy.dstOffset -= arena->cpu_addr;
    }
    staging.Flush();
    return staging.buffer;
}

bool BufferCache::SynchronizeMemoryFromImage(const Buffer* arena, VAddr device_addr, u32 size) {
    if (auto type = texture_cache.IsMeta(device_addr)) {
        if (*type == TextureCache::MetaType::HTile) {
            static constexpr u32 ZmaskUncompressed = 0xf;
            runtime.FillBuffer(arena, arena->Offset(device_addr), size, ZmaskUncompressed);
            return true;
        } else {
            LOG_WARNING(Render_Vulkan, "Unhandled metadata type {}", magic_enum::enum_name(*type));
        }
    }
    // bbport: most texel buffers alias no image; remember misses until images change.
    const u64 generation = texture_cache.RegistryGeneration();
    auto& miss = image_miss_cache[((device_addr >> 6) ^ size * 0x9E3779B1u) % image_miss_cache.size()];
    if (miss.address == device_addr && miss.size == size && miss.generation == generation &&
        !BbToggle::Disabled(BbToggle::TextureBindingMemo)) {
        return false;
    }
    const ImageId image_id = texture_cache.FindImageFromRange(device_addr, size);
    if (!image_id) {
        miss = {device_addr, size, generation};
        return false;
    }
    // bbport: the lookups above only read what the texture binding helper leaves alone; the
    // copy below changes image state, so the helper finishes first.
    runtime.BeforeImageAccess();
    Image& image = texture_cache.GetImage(image_id);
    ASSERT_MSG(device_addr == image.info.guest_address,
               "Texel buffer aliases image subresources {:x} : {:x}", device_addr,
               image.info.guest_address);
    const u64 arena_offset = arena->Offset(device_addr);
    boost::container::small_vector<vk::BufferImageCopy, 8> buffer_copies;
    for (u32 mip = 0; mip < image.info.resources.levels; mip++) {
        const auto& mip_info = image.info.mips_layout[mip];
        const u32 width = std::max(image.info.size.width >> mip, 1u);
        const u32 height = std::max(image.info.size.height >> mip, 1u);
        const u32 depth = std::max(image.info.size.depth >> mip, 1u);
        if (arena_offset + mip_info.offset + mip_info.size > arena->size_bytes) {
            break;
        }
        buffer_copies.push_back(vk::BufferImageCopy{
            .bufferOffset = mip_info.offset,
            .bufferRowLength = mip_info.pitch,
            .bufferImageHeight = mip_info.height,
            .imageSubresource{
                .aspectMask = image.aspect_mask & ~vk::ImageAspectFlagBits::eStencil,
                .mipLevel = mip,
                .baseArrayLayer = 0,
                .layerCount = image.info.resources.layers,
            },
            .imageOffset = {0, 0, 0},
            .imageExtent = {width, height, depth},
        });
    }
    if (buffer_copies.empty()) {
        return false;
    }
    auto& tile_manager = texture_cache.GetTileManager();
    tile_manager.TileImage(image, buffer_copies, arena, arena_offset);
    return true;
}

void BufferCache::SubmitPendingArenaBinds(Vulkan::SubmitInfo& info) {
    if (pending_binds.empty()) {
        return;
    }

    std::vector<vk::SparseBufferMemoryBindInfo> buffer_binds;
    buffer_binds.reserve(pending_binds.size());

    for (const auto& binds : pending_binds) {
        buffer_binds.emplace_back(vk::SparseBufferMemoryBindInfo{
            .buffer = binds.arena->Handle(),
            .bindCount = static_cast<u32>(binds.binds.size()),
            .pBinds = binds.binds.data(),
        });
    }

    const u64 signal_tick = memory_semaphore.NextTick();
    const auto signal_sema = memory_semaphore.Handle();

    const vk::TimelineSemaphoreSubmitInfo timeline_si = {
        .signalSemaphoreValueCount = 1u,
        .pSignalSemaphoreValues = &signal_tick,
    };

    const vk::BindSparseInfo sparse_info = {
        .pNext = &timeline_si,
        .bufferBindCount = static_cast<u32>(buffer_binds.size()),
        .pBufferBinds = buffer_binds.data(),
        .signalSemaphoreCount = 1u,
        .pSignalSemaphores = &signal_sema,
    };

    info.AddWait(signal_sema, signal_tick);
    auto submit_result = instance.GetGraphicsQueue().bindSparse(sparse_info);
    if (submit_result == vk::Result::eErrorDeviceLost) {
        instance.DeviceLost("sparse bind");
    }

    pending_binds.clear();
}

void BufferCache::RunGarbageCollector(u64 used_memory, u64 pressure_memory, u64 critical_memory) {
    // BB_BUFFER_GC=0: keep every chunk resident, as before.
    static const bool enabled = [] {
        const char* env = std::getenv("BB_BUFFER_GC");
        return !env || env[0] != '0';
    }();
    static const u32 idle_seconds = [] {
        const char* env = std::getenv("BB_BUFFER_GC_IDLE_SECONDS");
        return u32(std::clamp<u64>(env ? std::strtoull(env, nullptr, 10) : 10, 1, 3600));
    }();
    const u32 second = u32(std::chrono::duration_cast<std::chrono::seconds>(
                               std::chrono::steady_clock::now().time_since_epoch())
                               .count());
    gc_second.store(second, std::memory_order_relaxed);
    // Once a second at most: the driver's usage drops only once the GPU is done with a chunk.
    if (!enabled || second == gc_run_second || !instance.CanReportMemoryUsage() ||
        used_memory < pressure_memory) {
        return;
    }
    gc_run_second = second;
    const bool critical = used_memory >= critical_memory;
    const u32 min_idle = critical ? std::min<u32>(idle_seconds, 3) : idle_seconds;
    const size_t max_chunks = critical ? 128 : 32;

    std::vector<std::pair<u32, u64>> idle; // last use, chunk
    for (const auto& [chunk, memory] : chunk_memory) {
        const u32 last_use = chunk_last_use[chunk];
        if (second - last_use >= min_idle) {
            idle.emplace_back(last_use, chunk);
        }
    }
    if (idle.empty()) {
        return;
    }
    if (idle.size() > max_chunks) {
        std::ranges::nth_element(idle, idle.begin() + max_chunks);
        idle.resize(max_chunks);
    }

    const u64 chunk_size = u64{1} << chunk_shift;
    // Contents the GPU wrote exist only in the arena: written back to guest memory first (each a
    // wait for the GPU), before any release is queued.
    for (const auto& [last_use, chunk] : idle) {
        const VAddr address = chunk << chunk_shift;
        if (memory_tracker->IsRegionGpuModified(address, chunk_size)) {
            DownloadMemory(ArenasCovering(address >> arena_page_bits).front(), address, chunk_size);
        }
    }
    const auto device = instance.GetDevice();
    for (const auto& [last_use, chunk] : idle) {
        const VAddr address = chunk << chunk_shift;
        const u64 first_block = chunk << blocks_per_chunk_shift;
        const u64 end_block = (chunk + 1) << blocks_per_chunk_shift;
        resident_ranges.Subtract(first_block, end_block);
        // Unbound before the next submission; the next use binds new memory and uploads again.
        for (const Buffer* bound_arena : chunk_arenas.at(chunk)) {
            auto& binds = BindsForArena(bound_arena)->binds;
            const u64 resource_offset = address - bound_arena->cpu_addr;
            // A migration can still have a pending bind for this chunk. Replace it instead of
            // submitting overlapping bind and unbind ranges in the same sparse batch.
            binds.erase(std::remove_if(binds.begin(), binds.end(), [&](const auto& bind) {
                            return bind.resourceOffset == resource_offset;
                        }), binds.end());
            binds.push_back(vk::SparseMemoryBind{
                .resourceOffset = resource_offset,
                .size = chunk_size,
                .memory = VK_NULL_HANDLE,
                .memoryOffset = 0,
            });
        }
        // Shaders reading guest memory by address fault on it again instead.
        runtime.FillBuffer(bda_pagetable_buffer.get(), first_block * sizeof(vk::DeviceAddress),
                           (end_block - first_block) * sizeof(vk::DeviceAddress), 0u);
        memory_tracker->MarkRegionAsCpuModified(address, chunk_size);
        // Freed (or its reserve slot given back) once the GPU has finished the commands
        // submitted with the release.
        const ChunkBacking backing = chunk_memory[chunk];
        if (backing.counted) {
            vram_allocated -= chunk_size;
        }
        if (backing.memory == reserve_memory) {
            scheduler.DeferOperation([this, offset = backing.offset] {
                std::scoped_lock lk{reserve_mutex};
                reserve_free.push_back(offset);
            });
        } else {
            scheduler.DeferOperation([device, memory = backing.memory] {
                device.freeMemory(memory);
            });
        }
        chunk_memory.erase(chunk);
        chunk_arenas.erase(chunk);
    }
    gc_released += idle.size();

    const auto now = std::chrono::steady_clock::now();
    if (now - gc_report_time >= std::chrono::seconds(5)) {
        std::printf("Buffer cache: memory pressure, %llu MiB in use: %llu MiB of buffers unused "
                    "for %u s released since the last report, %llu MiB resident\n",
                    (unsigned long long)(used_memory >> 20),
                    (unsigned long long)((gc_released << chunk_shift) >> 20), min_idle,
                    (unsigned long long)((chunk_memory.size() << chunk_shift) >> 20));
        gc_report_time = now;
        gc_released = 0;
    }
}

} // namespace VideoCore
