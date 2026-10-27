// SPDX-FileCopyrightText: Copyright 2024 shadPS4 Emulator Project
// SPDX-License-Identifier: GPL-2.0-or-later

#pragma once

#include "bbport_copy.h"

#include <atomic>
#include <chrono>
#include <deque>
#include <mutex>
#include <unordered_map>
#include <vector>
#include <boost/container/small_vector.hpp>

#include "common/interval_set.h"
#include "common/types.h"
#include "video_core/buffer_cache/buffer.h"
#include "video_core/buffer_cache/fault_manager.h"
#include "video_core/buffer_cache/range_set.h"
#include "video_core/renderer_vulkan/vk_semaphore.h"

namespace AmdGpu {
struct Liverpool;
}

namespace Core {
class MemoryManager;
}

namespace Vulkan {
class GraphicsPipeline;
struct SubmitInfo;
class Runtime;
class StagingBufferPool;
} // namespace Vulkan

namespace VideoCore {

class TextureCache;
class MemoryTracker;
class PageManager;

class BufferCache {
    static constexpr u64 ADDRESS_SPACE_BITS = 40;
    // bbport: arena pages are 4 GiB unless the driver's buffer size limit is lower (AMD's
    // Windows driver: 2 GiB); an arena spans up to two pages, so they shrink to half the limit.
    static constexpr u64 MAX_ARENA_PAGE_BITS = 32;
    static constexpr u64 MIN_ARENA_PAGE_BITS = 30;
    static constexpr u64 MAX_ARENA_PAGES = u64{1} << (ADDRESS_SPACE_BITS - MIN_ARENA_PAGE_BITS);
    static constexpr u64 MIN_BLOCK_SIZE = 16_KB;

public:
    /// Read-only bindings up to this size are copied into a stream buffer (bbport: public for
    /// the draw pipeline's constant ring).
    static constexpr u64 STREAM_THRESHOLD = 16_KB;

    explicit BufferCache(const Vulkan::Instance& instance, Vulkan::Scheduler& scheduler,
                         Vulkan::Runtime& runtime, AmdGpu::Liverpool* liverpool,
                         TextureCache& texture_cache, PageManager& tracker);
    ~BufferCache();

    /// Returns a pointer to GDS device local buffer.
    [[nodiscard]] const Buffer* GetGdsBuffer() const noexcept {
        return &gds_buffer;
    }

    [[nodiscard]] const Buffer* GetNullIndexBuffer() const noexcept {
        return null_index_buffer.get();
    }

    /// Retrieves the device local DBA page table buffer.
    [[nodiscard]] Buffer* GetBdaPageTableBuffer() noexcept {
        return bda_pagetable_buffer.get();
    }

    /// Retrieves the fault buffer.
    [[nodiscard]] Buffer* GetFaultBuffer() noexcept {
        return fault_manager->GetFaultBuffer();
    }

    /// Retrieves the stream buffer.
    StreamBuffer& GetStreamBuffer() noexcept {
        return stream_buffer;
    }

    /// Returns minimum granularity of a sparse memory bind.
    u32 GetSparsePageShift() const noexcept {
        return block_shift;
    }

    /// Invalidates any buffer in the logical page range.
    void InvalidateMemory(VAddr device_addr, u64 size, bool assume_locks = false);

    /// bbport: a guest write fault at `device_addr` was handled; unprotect its neighbourhood.
    void ExtendWriteFault(VAddr device_addr);

    /// Flushes any GPU modified buffer in the logical page range back to CPU memory.
    void ReadMemory(VAddr device_addr, u64 size, bool is_write = false, bool assume_locks = false);

    /// Finds a buffer for the specified region.
    [[nodiscard]] std::pair<const Buffer*, u64> ObtainBuffer(VAddr device_addr, u32 size,
                                                             bool is_written,
                                                             bool is_texel_buffer = false);

    /// Attempts to obtain a buffer without modifying the cache contents.
    [[nodiscard]] std::pair<const Buffer*, u64> ObtainBufferForImage(VAddr device_addr, u32 size);

    /// Return true when a region is modified from the CPU
    [[nodiscard]] bool IsRegionCpuModified(VAddr addr, size_t size);

    /// Return true when a region is modified from the GPU
    [[nodiscard]] bool IsRegionGpuModified(VAddr addr, size_t size);

    /// Processes the fault buffer.
    void ProcessFaultBuffer();

    /// Synchronizes all buffers needed for DMA.
    void SynchronizeDmaBuffers();

    /// Commits pending sparse buffer memory binds. Must be called before every scheduler submit.
    void SubmitPendingArenaBinds(Vulkan::SubmitInfo& info);

    /// bbport: gives back the VRAM of arena chunks no binding has used for a while, once the
    /// device's memory use (`used_memory`, from the driver) reaches `pressure_memory`.
    /// Call where no draw is being prepared (Rasterizer::OnSubmit).
    void RunGarbageCollector(u64 used_memory, u64 pressure_memory, u64 critical_memory);

private:
    struct ArenaBinds {
        const Buffer* arena;
        boost::container::small_vector<vk::SparseMemoryBind, 32> binds;
    };

    ArenaBinds* BindsForArena(const Buffer* arena) {
        auto it = std::ranges::find(pending_binds, arena, &ArenaBinds::arena);
        if (it != pending_binds.end()) {
            return std::addressof(*it);
        }
        return &pending_binds.emplace_back(arena);
    }

    const Buffer* GetArena(u64 first_block, u64 last_block);
    /// bbport: the arenas whose range includes arena page `page` (at most two).
    boost::container::small_vector<const Buffer*, 2> ArenasCovering(u64 page) const;
    /// bbport: binds the memory already resident in the range of a new arena.
    void BindResidentRanges(const Buffer* arena);

    void EnsureResident(const Buffer* arena, u64 first_block, u64 last_block);
    struct ChunkBacking;
    ChunkBacking AllocateArenaChunk(vk::MemoryAllocateInfo alloc_info);

    void DownloadMemory(const Buffer* arena, VAddr device_addr, u64 size);

    bool SynchronizeMemory(const Buffer* arena, VAddr device_addr, u32 size, bool is_written,
                           bool is_texel_buffer);

    /// bbport: batched small copies on the copy threads (BbCopy::QueueCopy).
    static void RunGuestCopy(const BbCopy::Item& item);
    void SmallGuestCopy(const BbCopy::Item& item);

    const Buffer* UploadCopies(const Buffer* arena, std::span<vk::BufferCopy> copies,
                               size_t total_size_bytes);

    bool SynchronizeMemoryFromImage(const Buffer* arena, VAddr device_addr, u32 size);

    const Vulkan::Instance& instance;
    Vulkan::Scheduler& scheduler;
    // bbport: texel buffer ranges known not to alias an image, per image registry generation.
    struct ImageMiss {
        VAddr address = 0;
        u32 size = 0;
        u64 generation = ~0ULL;
    };
    std::array<ImageMiss, 256> image_miss_cache{};
    Vulkan::Runtime& runtime;
    Vulkan::StagingBufferPool& staging_pool;
    AmdGpu::Liverpool* liverpool;
    Core::MemoryManager* memory;
    TextureCache& texture_cache;
    std::unique_ptr<MemoryTracker> memory_tracker;

    StreamBuffer stream_buffer;
    Buffer gds_buffer;
    std::unique_ptr<Buffer> null_index_buffer;
    RangeSet gpu_modified_ranges;

    std::unique_ptr<FaultManager> fault_manager;
    std::unique_ptr<Buffer> bda_pagetable_buffer;

    /// bbport: the arena starting at each arena page, two pages long (one at the top), so a
    /// request (at most two pages) always fits the arena of its first page and arenas never
    /// migrate; neighbouring arenas overlap by a page and memory there is bound in both.
    /// BB_ARENA_MIGRATE=1: as before, the arena covering each page, merged when a request spans
    /// two of them.
    std::array<const Buffer*, MAX_ARENA_PAGES> address_space{};
    bool migrate_arenas{};
    u64 arena_page_bits{MAX_ARENA_PAGE_BITS};
    u64 arena_page_size{u64{1} << MAX_ARENA_PAGE_BITS};
    u64 num_arena_pages{u64{1} << (ADDRESS_SPACE_BITS - MAX_ARENA_PAGE_BITS)};
    std::deque<Buffer> arenas;
    std::vector<ArenaBinds> pending_binds;
    Vulkan::Semaphore memory_semaphore;

    struct Backing : public Interval {
        vk::DeviceMemory memory;
        u64 offset;
        constexpr bool CanMergeWith(const Backing& other) const noexcept {
            return memory == other.memory && offset + (end - start) == other.offset;
        }
        constexpr Backing SubRange(u64 a, u64 b) const noexcept {
            return {{a, b}, memory, offset + (a - start)};
        }
    };
    IntervalList<Backing> resident_ranges;

    /// bbport: arena memory is made resident in aligned chunks of 2 MiB (or the sparse block
    /// size if larger), each its own allocation, so that RunGarbageCollector can free them.
    /// Before, residency was never released: every buffer the game had ever bound kept its VRAM,
    /// up to the size of the guest's GPU memory (3+ GB), and 4 GB cards ran out after an hour or
    /// two however many textures were evicted (Jgamrot/bloodborne_pc#3).
    static constexpr u32 CHUNK_BITS = 21;
    u32 chunk_shift{};
    u32 blocks_per_chunk_shift{};
    /// Second (RunGarbageCollector's clock) each chunk was last bound, by chunk index.
    std::vector<u32> chunk_last_use;
    struct ChunkBacking {
        vk::DeviceMemory memory;
        u64 offset;    ///< in `memory`: non-zero for a slot of the reserve
        bool counted;  ///< counts towards BB_ARENA_LIMIT_MB (VRAM of its own)
    };
    std::unordered_map<u64, ChunkBacking> chunk_memory;
    /// An arena migration binds the same allocation into the replacement buffer while the old
    /// sparse buffer remains alive. Unbind every buffer before freeing the allocation.
    std::unordered_map<u64, std::vector<const Buffer*>> chunk_arenas;
    std::atomic<u32> gc_second{0};
    u32 gc_run_second{};
    u64 gc_released{};
    std::chrono::steady_clock::time_point gc_report_time{};

    u32 arena_memory_type_index{};
    u32 arena_memory_type_bits{}; ///< bbport: the types the arena accepts (system memory fallback)
    /// bbport (Supermedo/bloodborne_pc 5f65e2d): VRAM kept at start for the arena when the GPU
    /// has no other room (discrete GPUs), handed out in chunk-sized slots.
    vk::DeviceMemory reserve_memory{};
    u64 reserve_size{};
    u64 reserve_next{};                ///< slots below this offset have been handed out once
    std::vector<u64> reserve_free;     ///< offsets of slots given back by the collector
    std::mutex reserve_mutex;          ///< reserve_free: slots come back from deferred operations
    u64 vram_allocated{};              ///< bytes of `counted` chunks (BB_ARENA_LIMIT_MB)
    u32 block_size{};
    u32 block_shift{};
    u32 blocks_per_arena_page{};
    u32 blocks_per_arena_page_shift{};
};

} // namespace VideoCore
