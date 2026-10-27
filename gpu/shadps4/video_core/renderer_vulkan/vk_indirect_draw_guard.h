// SPDX-License-Identifier: GPL-2.0-or-later
// bbport: indirect draws run from checked vertex and instance counts.
//
// Like indirect dispatches (vk_indirect_guard.h), the game's indirect draws take their counts
// from memory a shader may have written; garbage ones kept an NVIDIA GPU past the driver's
// timeout (Xid 109, ayozetr/bloodborne_linux#19). Before each indirect draw a compute shader
// (indirect_draw_guard.comp) copies its arguments to a slot of our own, the vertex (or index) and
// instance counts zero if their product passes BB_INDIRECT_DRAW_GUARD_MAX (default 16M), and the
// draw reads that slot. An open render pass is paused for the check and continued without
// clearing its attachments again. Skipped draws are counted and reported.
// BB_INDIRECT_DRAW_GUARD=0: the game's arguments as they are.
#pragma once

#include <atomic>
#include <memory>
#include <optional>
#include <utility>

#include "common/types.h"
#include "video_core/renderer_vulkan/vk_common.h"

namespace VideoCore {
struct Buffer;
}

namespace Vulkan {

class Instance;
class Scheduler;

class IndirectDrawGuard {
public:
    IndirectDrawGuard(const Instance& instance, Scheduler& scheduler);
    ~IndirectDrawGuard();

    static bool Enabled();

    /// Records the check of `draws` draws of `stride` bytes at `offset` in `args` (outside a
    /// render pass); returns the buffer and offset to draw from, or nothing when the call is too
    /// big for the slots (then drawn from the game's arguments).
    std::optional<std::pair<vk::Buffer, u64>> CheckArgs(const VideoCore::Buffer& args, u64 offset,
                                                        u32 draws, u32 stride, bool is_indexed);

private:
    static constexpr u32 SlotBytes = 1u << 20;

    void Report();

    const Instance& instance;
    Scheduler& scheduler;
    std::unique_ptr<VideoCore::Buffer> checked; ///< SlotBytes of draw arguments, used in turn
    std::unique_ptr<VideoCore::Buffer> skipped; ///< count and the last skipped counts (host)
    vk::UniqueDescriptorSetLayout set_layout;
    vk::UniquePipelineLayout pipeline_layout;
    vk::UniquePipeline pipeline;
    u32 max_total = 0;
    std::atomic<u32> next_byte{0};
    std::atomic<u32> reported{0};
    std::atomic<bool> told_too_big{false};
    std::atomic<s64> last_report_ns{0};
};

} // namespace Vulkan
