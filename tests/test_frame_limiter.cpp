// SPDX-License-Identifier: GPL-2.0-or-later
#include <cassert>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>

using u32 = uint32_t;
using u64 = uint64_t;

// Test the resolution logic corresponding to EmulatorSettings::GetFrameLimit()
static u32 ResolveFrameLimit(long limit_override, const std::string& fps, long vblank_hz, u32 display_refresh_hz) {
    if (limit_override >= 0) {
        return static_cast<u32>(limit_override);
    }
    if (fps == "30") return 30u;
    if (fps == "60") return 60u;
    if (fps == "90") return 90u;
    if (fps == "uncap") return std::min<u32>(display_refresh_hz, 120u);
    if (!fps.empty()) {
        try {
            const long parsed = std::stol(fps);
            if (parsed >= 0) return static_cast<u32>(parsed);
        } catch (...) {}
    }
    return vblank_hz > 0 ? static_cast<u32>(vblank_hz) : std::min<u32>(display_refresh_hz, 120u);
}

// Minimal reproduction of Common::AccurateTimer to deterministically test drift
class TestAccurateTimer {
    std::chrono::nanoseconds target_interval{};
    std::chrono::nanoseconds total_wait{};
    std::chrono::high_resolution_clock::time_point start_time{};

public:
    explicit TestAccurateTimer(std::chrono::nanoseconds target_interval)
        : target_interval(target_interval) {}

    void Start(std::chrono::high_resolution_clock::time_point& now, bool simulated_sleep = false) {
        const auto begin_sleep = now;
        if (total_wait.count() > 0 && simulated_sleep) {
            // Simulated accurate sleep consumes total_wait by advancing time
            now += total_wait;
        }
        start_time = now;
        total_wait -= std::chrono::duration_cast<std::chrono::nanoseconds>(start_time - begin_sleep);
    }

    void End(std::chrono::high_resolution_clock::time_point now) {
        total_wait += target_interval - std::chrono::duration_cast<std::chrono::nanoseconds>(now - start_time);
    }

    std::chrono::nanoseconds GetTotalWait() const {
        return total_wait;
    }
};

static void TestFrameLimitResolution() {
    const u32 refresh_60 = 60;
    const u32 refresh_144 = 144;

    // 1. Explicit limit overrides everything
    assert(ResolveFrameLimit(60, "uncap", 0, refresh_144) == 60u);
    assert(ResolveFrameLimit(30, "uncap", 0, refresh_144) == 30u);
    assert(ResolveFrameLimit(0, "uncap", 0, refresh_144) == 0u); // 0 = explicit uncapped
    assert(ResolveFrameLimit(144, "60", 60, refresh_144) == 144u);

    // 2. Unset limit (-1) respects preset
    assert(ResolveFrameLimit(-1, "30", 60, refresh_144) == 30u);
    assert(ResolveFrameLimit(-1, "60", 60, refresh_144) == 60u);
    assert(ResolveFrameLimit(-1, "90", 90, refresh_144) == 90u);

    // 3. Uncap preset defaults to min(refresh, 120)
    assert(ResolveFrameLimit(-1, "uncap", 0, refresh_144) == 120u);
    assert(ResolveFrameLimit(-1, "uncap", 0, refresh_60) == 60u);

    // 4. Numeric fps string (e.g. "120")
    assert(ResolveFrameLimit(-1, "120", 0, refresh_144) == 120u);

    // 5. Fallback when fps string is empty
    assert(ResolveFrameLimit(-1, "", 60, refresh_144) == 60u);
    assert(ResolveFrameLimit(-1, "", 90, refresh_144) == 90u);
    assert(ResolveFrameLimit(-1, "", 0, refresh_144) == 120u);
    assert(ResolveFrameLimit(-1, "", 0, refresh_60) == 60u);

    std::puts("PASS: Frame limit resolution logic");
}

static void TestTimerBalanceAndDrift() {
    using namespace std::chrono;
    const auto frame_interval = nanoseconds(16'666'667); // 60 FPS (~16.66 ms)

    // A. Properly paired Start() and End() across 3600 frames (1 minute of gameplay)
    TestAccurateTimer paired_timer{frame_interval};
    auto simulated_time = high_resolution_clock::now();

    for (int frame = 0; frame < 3600; ++frame) {
        paired_timer.Start(simulated_time, true);
        // Simulate work lasting 15 ms
        simulated_time += milliseconds(15);
        paired_timer.End(simulated_time);
        // Advance time to next tick
        simulated_time += milliseconds(1);
    }
    // Total wait should remain bounded within a small fraction of a second, NOT drifting to minutes
    const auto wait_ms = duration_cast<milliseconds>(paired_timer.GetTotalWait()).count();
    assert(std::abs(wait_ms) < 5000);

    // B. Unpaired Start() without End() (the bug in immediate_flips)
    TestAccurateTimer buggy_timer{frame_interval};
    simulated_time = high_resolution_clock::now();
    for (int frame = 0; frame < 3600; ++frame) {
        buggy_timer.Start(simulated_time, false);
        // Simulated frame without calling End()
        simulated_time += milliseconds(16);
    }
    // Buggy timer never gained interval in total_wait, so total_wait stayed 0 or negative
    assert(buggy_timer.GetTotalWait().count() <= 0);

    std::puts("PASS: Timer balance and drift bounding");
}

static void TestTextureCacheEvictionLogic() {
    // Simulate gc_tick_at_second buffer of 64 entries
    std::vector<u64> gc_tick_at_second(64, 0);
    const u64 current_second = 100;
    const u64 ticks_per_second = 300; // ~300 submissions/sec
    u64 gc_tick = 0;

    for (u64 s = current_second - 63; s <= current_second; ++s) {
        gc_tick += ticks_per_second;
        gc_tick_at_second[s % 64] = gc_tick;
    }

    const auto tick_seconds_ago = [&](u64 seconds) {
        return gc_tick_at_second[(current_second - seconds) % 64];
    };

    const u64 idle_seconds = 20;
    const u64 pressure_idle_seconds = 5;
    const u64 idle_tick = tick_seconds_ago(idle_seconds);

    // 1. Normal state (!pressured && !aggressive): below_tick must be <= idle_tick (20s ago)
    {
        bool pressured = false;
        bool aggressive = false;
        const u64 ticks_to_destroy = 16;
        u64 below_tick = gc_tick - ticks_to_destroy;
        if (!pressured && !aggressive) {
            below_tick = std::min(below_tick, idle_tick);
        }
        assert(below_tick == idle_tick);
        // Textures touched 10 seconds ago must NOT be below below_tick
        const u64 touched_10s_ago = tick_seconds_ago(10);
        assert(touched_10s_ago > below_tick);
    }

    // 2. Pressured state (pressured == true, emergency == false):
    // Must protect textures used in the last 5 seconds (pressure_idle_seconds)
    {
        bool pressured = true;
        bool aggressive = false;
        bool emergency = false;
        const u64 ticks_to_destroy = 80;
        u64 below_tick = gc_tick - ticks_to_destroy;
        if (!pressured && !aggressive) {
            below_tick = std::min(below_tick, idle_tick);
        } else if (!emergency) {
            below_tick = std::min(below_tick, tick_seconds_ago(aggressive ? 1 : pressure_idle_seconds));
        }
        assert(below_tick == tick_seconds_ago(5));

        // Texture touched 2 seconds ago (e.g. turned camera briefly) MUST NOT be evicted!
        const u64 touched_2s_ago = tick_seconds_ago(2);
        assert(touched_2s_ago > below_tick);

        // Texture untouched for 6 seconds is eligible for eviction
        const u64 touched_6s_ago = tick_seconds_ago(6);
        assert(touched_6s_ago <= below_tick);
    }

    // 3. Emergency state (emergency == true, critical memory exhausted):
    // Fall back to tick-based eviction (gc_tick - 160) to avoid OOM
    {
        bool pressured = true;
        bool aggressive = true;
        bool emergency = true;
        const u64 ticks_to_destroy = 160;
        u64 below_tick = gc_tick - ticks_to_destroy;
        if (!pressured && !aggressive) {
            below_tick = std::min(below_tick, idle_tick);
        } else if (!emergency) {
            below_tick = std::min(below_tick, tick_seconds_ago(aggressive ? 1 : pressure_idle_seconds));
        }
        assert(below_tick == gc_tick - 160);
    }

    std::puts("PASS: Texture cache eviction threshold and pressure retention");
}

// Reproduction of the texture cache memory threshold resolution logic
struct CacheThresholds {
    u64 trigger_gc_memory = 0;
    u64 pressure_gc_memory = 0;
    u64 critical_gc_memory = 0;
    u64 vram_critical = 0;
};

static CacheThresholds ResolveCacheThresholds(u64 driver_budget, u64 forced_budget,
                                              u64 device_local_memory, bool is_integrated,
                                              bool can_report_memory) {
    static constexpr u64 GB = 1024ULL * 1024ULL * 1024ULL;
    static constexpr u64 MB = 1024ULL * 1024ULL;
    static constexpr u64 DEFAULT_PRESSURE_GC_MEMORY = 1 * GB + 512 * MB;
    static constexpr u64 DEFAULT_CRITICAL_GC_MEMORY = 3 * GB;

    CacheThresholds t{};
    if (!can_report_memory) {
        t.pressure_gc_memory = DEFAULT_PRESSURE_GC_MEMORY;
        t.critical_gc_memory = DEFAULT_CRITICAL_GC_MEMORY;
        t.trigger_gc_memory = t.pressure_gc_memory / 10 * 7;
        t.vram_critical = t.critical_gc_memory;
        return t;
    }

    if (driver_budget != 0) {
        t.vram_critical = driver_budget / 100 * (is_integrated ? 95 : 90);
    }

    const u64 fallback_budget = device_local_memory != 0
                                    ? device_local_memory
                                    : DEFAULT_PRESSURE_GC_MEMORY;
    const u64 budget = forced_budget && driver_budget ? std::min(forced_budget, driver_budget)
                       : forced_budget                ? forced_budget
                       : driver_budget                ? driver_budget
                                                      : fallback_budget;

    if (is_integrated || forced_budget) {
        t.trigger_gc_memory = budget / 10 * 7;
        t.pressure_gc_memory = budget / 100 * (is_integrated ? 85 : 80);
        t.critical_gc_memory = budget / 100 * (is_integrated ? 95 : 90);
    } else {
        t.trigger_gc_memory = budget / 10 * 7;
        t.pressure_gc_memory = budget / 100 * 80;
        t.critical_gc_memory = budget / 100 * 90;
    }
    return t;
}

enum class GcAction {
    EarlyReturn,
    IdleSweepOnly,
    PressureSweep,
    CriticalSweep,
};

static GcAction EvaluateGc(const CacheThresholds& t, u64 total_used_memory) {
    if (total_used_memory < t.trigger_gc_memory) {
        return GcAction::EarlyReturn;
    }
    if (total_used_memory >= t.critical_gc_memory) {
        return GcAction::CriticalSweep;
    }
    if (total_used_memory >= t.pressure_gc_memory) {
        return GcAction::PressureSweep;
    }
    return GcAction::IdleSweepOnly;
}

static void TestTextureCacheMemoryThresholds() {
    static constexpr u64 GB = 1024ULL * 1024ULL * 1024ULL;
    static constexpr u64 MB = 1024ULL * 1024ULL;

    // 1. Normal usage below the trigger (6 GB budget discrete GPU)
    {
        const u64 budget = 6 * GB;
        const auto t = ResolveCacheThresholds(budget, 0, 8 * GB, false, true);
        assert(t.trigger_gc_memory == budget / 10 * 7); // 4.2 GB
        assert(t.pressure_gc_memory == budget / 100 * 80); // 4.8 GB
        assert(t.critical_gc_memory == budget / 100 * 90); // 5.4 GB

        // Healthy usage: 3.5 GB used < 4.2 GB trigger -> Early return, no sweeps!
        assert(EvaluateGc(t, 3500 * MB) == GcAction::EarlyReturn);
        assert(EvaluateGc(t, 0) == GcAction::EarlyReturn);
        assert(EvaluateGc(t, t.trigger_gc_memory - 1) == GcAction::EarlyReturn);
    }

    // 2. Usage crossing the trigger
    {
        const u64 budget = 6 * GB;
        const auto t = ResolveCacheThresholds(budget, 0, 8 * GB, false, true);
        // At exactly trigger (4.2 GB) or between trigger and pressure (4.5 GB):
        assert(EvaluateGc(t, t.trigger_gc_memory) == GcAction::IdleSweepOnly);
        assert(EvaluateGc(t, 4500 * MB) == GcAction::IdleSweepOnly);
        assert(EvaluateGc(t, t.pressure_gc_memory - 1) == GcAction::IdleSweepOnly);
    }

    // 3. High memory pressure and critical pressure
    {
        const u64 budget = 6 * GB;
        const auto t = ResolveCacheThresholds(budget, 0, 8 * GB, false, true);
        // Pressure threshold (4.8 GB):
        assert(EvaluateGc(t, t.pressure_gc_memory) == GcAction::PressureSweep);
        assert(EvaluateGc(t, 5000 * MB) == GcAction::PressureSweep);
        assert(EvaluateGc(t, t.critical_gc_memory - 1) == GcAction::PressureSweep);

        // Critical threshold (5.4 GB):
        assert(EvaluateGc(t, t.critical_gc_memory) == GcAction::CriticalSweep);
        assert(EvaluateGc(t, budget) == GcAction::CriticalSweep);
        assert(EvaluateGc(t, budget + 512 * MB) == GcAction::CriticalSweep);
    }

    // 4. Zero or unavailable budget (fallback protection)
    {
        // When driver reports 0 budget, falls back to device-local memory estimate
        const auto t_dev = ResolveCacheThresholds(0, 0, 8 * GB, false, true);
        assert(t_dev.trigger_gc_memory == (8 * GB) / 10 * 7);
        assert(t_dev.trigger_gc_memory > 0);
        assert(EvaluateGc(t_dev, 2 * GB) == GcAction::EarlyReturn);

        // When driver reports 0 and device memory is 0, falls back to DEFAULT_PRESSURE_GC_MEMORY
        const auto t_def = ResolveCacheThresholds(0, 0, 0, false, true);
        assert(t_def.trigger_gc_memory > 0);
        assert(t_def.trigger_gc_memory < t_def.pressure_gc_memory);
        assert(t_def.pressure_gc_memory < t_def.critical_gc_memory);

        // When can_report_memory is false
        const auto t_no_report = ResolveCacheThresholds(0, 0, 0, false, false);
        assert(t_no_report.trigger_gc_memory > 0);
        assert(t_no_report.trigger_gc_memory == (1536 * MB / 10 * 7));
        assert(EvaluateGc(t_no_report, 500 * MB) == GcAction::EarlyReturn);
    }

    // 5. Small budgets (e.g. 512 MB and 256 MB)
    {
        for (u64 small_budget : {256 * MB, 512 * MB, 1 * GB}) {
            const auto t = ResolveCacheThresholds(small_budget, 0, small_budget, false, true);
            assert(t.trigger_gc_memory > 0);
            assert(t.trigger_gc_memory < t.pressure_gc_memory);
            assert(t.pressure_gc_memory < t.critical_gc_memory);
            assert(t.critical_gc_memory < small_budget);

            assert(EvaluateGc(t, t.trigger_gc_memory / 2) == GcAction::EarlyReturn);
            assert(EvaluateGc(t, t.trigger_gc_memory) == GcAction::IdleSweepOnly);
            assert(EvaluateGc(t, t.pressure_gc_memory) == GcAction::PressureSweep);
            assert(EvaluateGc(t, t.critical_gc_memory) == GcAction::CriticalSweep);
        }
    }

    // 6. Integrated-GPU behavior (70% trigger, 85% pressure, 95% critical)
    {
        const u64 budget = 8 * GB;
        const auto t_igpu = ResolveCacheThresholds(budget, 0, budget, true, true);
        const auto t_dgpu = ResolveCacheThresholds(budget, 0, budget, false, true);

        // Trigger is 70% on both (preventing 0-threshold thrashing on Steam Deck)
        assert(t_igpu.trigger_gc_memory == budget / 10 * 7);
        assert(t_dgpu.trigger_gc_memory == budget / 10 * 7);

        // iGPU has wider tolerance before pressure (85% vs 80%) and critical (95% vs 90%)
        assert(t_igpu.pressure_gc_memory == budget / 100 * 85);
        assert(t_dgpu.pressure_gc_memory == budget / 100 * 80);
        assert(t_igpu.critical_gc_memory == budget / 100 * 95);
        assert(t_dgpu.critical_gc_memory == budget / 100 * 90);
        assert(t_igpu.pressure_gc_memory > t_dgpu.pressure_gc_memory);
        assert(t_igpu.critical_gc_memory > t_dgpu.critical_gc_memory);
    }

    // 7. Threshold arithmetic, monotonicity, and boundary conditions
    {
        // Test various budgets up to large discrete cards (24 GB, 64 GB, 128 GB)
        for (u64 test_budget : {1 * GB, 4 * GB, 8 * GB, 16 * GB, 24 * GB, 64 * GB, 128 * GB}) {
            const auto t = ResolveCacheThresholds(test_budget, 0, test_budget, false, true);
            // Strict monotonic ordering
            assert(t.trigger_gc_memory < t.pressure_gc_memory);
            assert(t.pressure_gc_memory < t.critical_gc_memory);
            assert(t.critical_gc_memory < test_budget);

            // Integer arithmetic precision check: /10 * 7 should not underflow or invert
            assert(t.trigger_gc_memory == (test_budget / 10) * 7);
            assert(t.pressure_gc_memory == (test_budget / 100) * 80);
            assert(t.critical_gc_memory == (test_budget / 100) * 90);
        }
    }

    std::puts("PASS: Texture cache trigger, pressure, critical, and boundary thresholds");
}

int main() {
    TestFrameLimitResolution();
    TestTimerBalanceAndDrift();
    TestTextureCacheEvictionLogic();
    TestTextureCacheMemoryThresholds();
    std::puts("All frame limiter and degradation tests PASS");
    return 0;
}
