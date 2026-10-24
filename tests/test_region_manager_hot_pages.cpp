// SPDX-License-Identifier: GPL-2.0-or-later
// Standalone CPU check of the measured hot page rule (BB_HOT_PAGES=2, RegionManager): which
// pages become hot, the 8 MiB cap, the 2 s window, and that a use never reads stale data.
#include <array>
#include <bitset>
#include <cassert>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <map>
#include <memory>
#include <thread>
#include <vector>
#include "video_core/buffer_cache/region_manager.h"

extern "C" {
std::uint64_t runtime_disabled_optimizations = 0;
#ifdef _WIN32
__thread sigjmp_buf* runtime_fault_recover = nullptr;
int bb_setjmp(sigjmp_buf) {
    return 0;
}
#else
thread_local sigjmp_buf* runtime_fault_recover = nullptr;
#endif
}

using namespace VideoCore;

namespace {

constexpr u64 Page = TRACKER_BYTES_PER_PAGE;
constexpr u64 Pages = NUM_PAGES_PER_REGION;
std::map<VAddr, std::bitset<Pages>> write_protected;

} // namespace

// The page tracker's protection, recorded instead of applied.
template <bool track, bool is_read>
void PageManager::UpdatePageWatchersForRegion(VAddr base_addr, RegionBits& mask) const {
    if constexpr (!is_read) {
        for (u64 page = 0; page < Pages; ++page) {
            if (mask.Get(page)) {
                write_protected[base_addr][page] = track;
            }
        }
    }
}

namespace {

PageManager* Tracker() {
    alignas(PageManager) static unsigned char storage[sizeof(PageManager)];
    return reinterpret_cast<PageManager*>(storage);
}

// Guest memory and the GPU's copy of it, as versions per page.
struct Region {
    explicit Region(VAddr base) : manager{std::make_unique<RegionManager>(Tracker(), base)} {}
    void Write(u64 page) {
        ++memory[page];
        if (write_protected[manager->GetCpuAddr()][page]) {
            const u64 faults = BbStats::tracker_faults.load();
            manager->ChangeRegionState<Type::CPU, true>(manager->GetCpuAddr() + page * Page,
                                                        Page);
            assert(BbStats::tracker_faults.load() == faults + 1);
        }
    }
    // A binding of `count` pages: what is CPU modified is uploaded, then the GPU reads it.
    void Use(u64 page, u64 count = 1) {
        const VAddr base = manager->GetCpuAddr();
        manager->ForEachModifiedRange<Type::CPU, true>(
            base + page * Page, s64(count * Page), [&](VAddr addr, u64 size) {
                for (u64 p = (addr - base) / Page; p < (addr - base + size) / Page; ++p) {
                    uploaded[p] = memory[p];
                }
            });
        for (u64 p = page; p < page + count; ++p) {
            assert(uploaded[p] == memory[p]);
        }
    }
    bool Hot(u64 page) {
        // Hot: writable, and still CPU modified right after an upload.
        Use(page);
        return !write_protected[manager->GetCpuAddr()][page] &&
               manager->IsRegionModified<Type::CPU>(page * Page, Page);
    }
    std::unique_ptr<RegionManager> manager;
    std::array<u32, Pages> memory{};
    std::array<u32, Pages> uploaded{};
};

void PageWrittenBeforeEveryUse() {
    const s64 hot_before = BbStats::hot_pages.load();
    Region region{0x10000000};
    region.Use(0, Pages); // first upload: everything protected
    for (int i = 0; i < 15; ++i) {
        region.Write(3);
        region.Use(3);
    }
    assert(BbStats::hot_pages.load() == hot_before);
    assert(write_protected[0x10000000][3]);
    region.Write(3); // the 16th fault in the window
    region.Use(3);
    assert(BbStats::hot_pages.load() == hot_before + 1);
    assert(region.Hot(3));
    // Hot: writes cost no fault and every use uploads them.
    const u64 faults = BbStats::tracker_faults.load();
    for (int i = 0; i < 100; ++i) {
        region.Write(3);
        region.Use(3);
        region.Use(2, 3);
    }
    assert(BbStats::tracker_faults.load() == faults);
    assert(region.Hot(3));
    assert(!region.Hot(2) && !region.Hot(4));
}

void PageReadManyTimesPerWrite() {
    const s64 hot_before = BbStats::hot_pages.load();
    Region region{0x20000000};
    region.Use(0, Pages);
    for (int i = 0; i < 64; ++i) {
        region.Write(7);
        for (int use = 0; use < 9; ++use) {
            region.Use(7);
        }
    }
    assert(BbStats::hot_pages.load() == hot_before);
    assert(!region.Hot(7));
    assert(write_protected[0x20000000][7]);
    // Eight uses per write is still hot.
    for (int i = 0; i < 16; ++i) {
        region.Write(8);
        for (int use = 0; use < 8; ++use) {
            region.Use(8);
        }
    }
    assert(BbStats::hot_pages.load() == hot_before + 1);
    assert(region.Hot(8));
}

void HotPagesCapped() {
    std::vector<std::unique_ptr<Region>> regions;
    for (VAddr base = 0x30000000; regions.size() < 3; base += TRACKER_HIGHER_PAGE_SIZE) {
        regions.push_back(std::make_unique<Region>(base));
        regions.back()->Use(0, Pages);
    }
    for (int i = 0; i < 20; ++i) {
        for (auto& region : regions) {
            for (u64 page = 0; page < Pages; ++page) {
                region->Write(page);
            }
            region->Use(0, Pages);
        }
    }
    assert(BbStats::hot_pages.load() == 2048);
    for (auto& region : regions) {
        for (u64 page = 0; page < Pages; ++page) {
            region->Write(page);
        }
        region->Use(0, Pages);
    }
}

void FaultsOutsideTheWindow() {
    Region region{0x40000000};
    region.Use(0, Pages);
    const s64 hot_before = BbStats::hot_pages.load();
    for (int i = 0; i < 15; ++i) {
        region.Write(9);
        region.Use(9);
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(2100));
    for (int i = 0; i < 15; ++i) {
        region.Write(9);
        region.Use(9);
    }
    assert(BbStats::hot_pages.load() == hot_before);
    region.Write(9);
    region.Use(9);
    assert(BbStats::hot_pages.load() == hot_before + 1);
    assert(region.Hot(9));
}

} // namespace

int main() {
#ifdef _WIN32
    _putenv_s("BB_HOT_PAGES", "");
#else
    unsetenv("BB_HOT_PAGES");
#endif
    PageWrittenBeforeEveryUse();
    PageReadManyTimesPerWrite();
    FaultsOutsideTheWindow();
    HotPagesCapped(); // last: the cap is global
    std::puts("hot pages check: ok");
}
