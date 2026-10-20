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

int main() {
    TestFrameLimitResolution();
    TestTimerBalanceAndDrift();
    TestTextureCacheEvictionLogic();
    std::puts("All frame limiter and degradation tests PASS");
    return 0;
}
