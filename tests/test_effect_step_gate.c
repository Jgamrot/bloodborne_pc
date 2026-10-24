/* SPDX-License-Identifier: GPL-2.0-or-later
 * effect_step_gate.c and effect_smooth_steps.c: the whole 1/30 s steps the effect manager takes at
 * each frame rate and the frame's own time and carry beside them, the refusal of an image that is
 * not the game's, and, with the player's game (game_code.h), the install on the game's own code and
 * each hold and smooth step against stand-ins for the functions it calls. */
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>
#include "effect_step_gate.h"
#include "engine_hooks.h"
#include "game_code.h"

/* Binary Ninja addresses, as effect_step_gate.c and effect_smooth_steps.c have them. */
enum {
    SFX = 0x5940370, EFFECTS_CALL = 0x2377d34, EFFECTS_CALL_END = 0x2377d52, STEP_LOAD = 0x2377d48,
    STEP_CONSTANT = 0x4d29170, MANAGER_SLOT = 0x57b90c0, MANAGER_UPDATE = 0x26ff340,
    MANAGER_WIND = 0x26ff3bf, WIND_CALL = 0x26ff3ee, RECEIVERS_CALL = 0x26ff41a, RECEIVERS_UPDATE = 0x27174e0,
    INSTANCE_UPDATE = 0x2c4ff30, CONTROLLER_CALL = 0x2c4fffb, CONTROLLER_UPDATE = 0x2c820f0,
    NODE_CALL = 0x2c5007b, NODE_UPDATE = 0x2c4df80, CONTAINER_UPDATE = 0x2c4c8c0,
    CONTAINER_FIRST = 0x2c4e143, CONTAINER_LAST = 0x2c4e540,
    LIGHT_SLOT = 0x56ebbb8, LIGHT_UPDATE = 0x131e660, PREROLL_CONTEXT = 0x56dbd80,
    RECORD_CALL_A = 0x2cbaaf7, RECORD_CALL_B = 0x2cbab1d, RECORD_UPDATE = 0x2cbcf50,
    TYPE_2713 = 0x56eb0d0, TYPE_2713_UPDATE = 0x12e81b0,
    WOBBLE_A_SLOT = 0x570e6d0, WOBBLE_A = 0x2e89d10, WOBBLE_A_BASE = 0x2e866f0, WOBBLE_A_CALL = 0x2e89a80,
    FOLLOW_SLOT = 0x570e690, FOLLOW = 0x2e896f0, WOBBLE_B_SLOT = 0x570e8d0, WOBBLE_B = 0x2e8e430,
    WOBBLE_B_BASE = 0x2e8bfd0, WOBBLE_B_CALL = 0x2e8e19f, FOLLOW_B = 0x2e8de10,
    WIND_SOURCES = 0x1314660, SOURCE = 0x56ec140, SOURCE_STEP = 0x2d552d0, SOURCE_NONE = 0x56ebf70,
    SOURCE_NONE_STEP = 0x2d521c0, FADES_CALL = 0x27019fc, FADES_CALL_CODE = 0x27019ed, LIGHT_FADES = 0x12e5500,
    COMPOSITE = 0x570e750, COMPOSITE_UPDATE = 0x2e8ae30, GX_BINDER = 0x56e3100, RIBBON = 0x56e3620,
    STANDARD = 0x56eb1d0, SPARK_SIMULATION = 0x12fef10, STANDARD_SIMULATION = 0x13040b0,
    EULER = 0x570e650, LIGHT_CLASS = 0x56ebba0,
};
static const size_t IMAGE = 0x5700000;
static const struct {
    uint64_t at;
    size_t n;
} GAME_CODE[] = {
    {EFFECTS_CALL, 16}, {EFFECTS_CALL_END, 14}, {STEP_LOAD, 10}, {MANAGER_UPDATE, 28}, {MANAGER_WIND, 0x82},
    {RECEIVERS_UPDATE, 0x601}, {INSTANCE_UPDATE, 0x1ae}, {NODE_UPDATE, 0x66c}, {CONTAINER_UPDATE, 20},
    {LIGHT_UPDATE, 0x8d2}, {RECORD_UPDATE, 0x1d5}, {TYPE_2713_UPDATE, 0x274}, {CONTROLLER_CALL, 5},
    {NODE_CALL, 5}, {RECORD_CALL_A, 5}, {RECORD_CALL_B, 5}, {WOBBLE_A, 0x593}, {WOBBLE_A_BASE, 0x868},
    {FOLLOW, 0x3b3}, {WOBBLE_B, 0x593}, {WOBBLE_B_BASE, 0x5a6}, {FOLLOW_B, 0x3b2},
    {COMPOSITE_UPDATE, 0x3d}, {WIND_SOURCES, 0x52}, {SOURCE_STEP, 0x36}, {SOURCE_NONE_STEP, 1},
    {FADES_CALL_CODE, 0x14}, {LIGHT_FADES, 0x22d}, {STANDARD_SIMULATION, 0xd26}, {SPARK_SIMULATION, 0xb44},
};
/* The converted classes: vtable, slot, update, its length (effect_smooth_steps.c's CLASSES). */
static const struct {
    uint64_t vtable;
    unsigned slot;
    uint64_t update;
    size_t n;
} CLASSES[] = {
    {0x570e650, 0, 0x2e88510, 0x4fe}, {0x570e610, 0, 0x2e87a10, 0x6a3}, {0x570e5d0, 0, 0x2e866f0, 0x868},
    {0x570e6d0, 0, 0x2e89d10, 0x593}, {0x570e690, 0, 0x2e896f0, 0x3b3}, {0x570e850, 0, 0x2e8d740, 0x256},
    {0x570e810, 0, 0x2e8cc60, 0x3f5}, {0x570e7d0, 0, 0x2e8bfd0, 0x5a6}, {0x570e8d0, 0, 0x2e8e430, 0x593},
    {0x570e890, 0, 0x2e8de10, 0x3b2}, {0x570e790, 0, 0x2e8b100, 0x95b}, {0x570e710, 0, 0x2e8a3d0, 0x7cc},
    {0x570e910, 0, 0x2e8ec00, 0x6e}, {0x56eb2e0, 0x18, 0x12fccf0, 0x403}, {0x5756e50, 0x10, 0x23749d0, 0x1f8},
    {0x56ebba0, 0x18, 0x131e660, 0x8d2}, {0x56ebc40, 0x18, 0x1320260, 0xa85}, {0x56e3090, 0x10, 0x2cba4b0, 0xe4},
    {0x56e3100, 0x10, 0x2cbaa40, 0xc8}, {0x56eb1d0, 0x10, 0x12f18f0, 0x306}, {0x56eb120, 0x10, 0x12ed0b0, 0x306},
    {0x56eb220, 0x10, 0x12f7ee0, 0x37f}, {0x56ea9b0, 0x10, 0x12e09d0, 0x498}, {0x56eaa90, 0x10, 0x12e17d0, 0x50c},
    {0x56eb290, 0x10, 0x12fc690, 0x76}, {0x56eb0d0, 0x10, 0x12e81b0, 0x274}, {0x56e35d0, 0x10, 0x2ec0a60, 0x171},
    {0x56e3530, 0x10, 0x2eb6550, 0x2d5}, {0x56e3580, 0x10, 0x2ebc280, 0x28c}, {0x56ebe20, 0x10, 0x1325cd0, 0xe0},
    {0x56eadf0, 0x10, 0x12e3c30, 0x821}, {0x56eac40, 0x10, 0x12e27b0, 0x773}, {0x56e3620, 0x10, 0x2ec1e00, 0x174e},
};
static const uint64_t SLOTS[][2] = {
    {MANAGER_SLOT, MANAGER_UPDATE}, {LIGHT_SLOT, LIGHT_UPDATE}, {TYPE_2713 + 0x10, TYPE_2713_UPDATE},
    {WOBBLE_A_SLOT, WOBBLE_A}, {FOLLOW_SLOT, FOLLOW}, {WOBBLE_B_SLOT, WOBBLE_B}, {COMPOSITE, COMPOSITE_UPDATE},
    {SOURCE + 0x58, SOURCE_STEP}, {SOURCE_NONE + 0x58, SOURCE_NONE_STEP},
};

typedef uint64_t (BB_GUEST_ABI *ManagerFn)(uint64_t, float);
typedef uint64_t (BB_GUEST_ABI *ControllerFn)(uint64_t, uint64_t, float);
typedef uint8_t (BB_GUEST_ABI *NodeFn)(uint64_t, float *, uint64_t, uint64_t);
typedef void (BB_GUEST_ABI *ContainerFn)(uint64_t, float *, uint64_t, uint64_t);
typedef void (BB_GUEST_ABI *LightFn)(uint64_t, uint64_t, uint64_t);
typedef void (BB_GUEST_ABI *RecordFn)(uint64_t, uint64_t);
typedef void (BB_GUEST_ABI *MotionFn)(uint64_t, uint64_t, const float *, uint64_t);
typedef void (BB_GUEST_ABI *StepFn)(uint64_t, float);

static uint32_t bits(float f) {
    uint32_t b;
    memcpy(&b, &f, 4);
    return b;
}

/* A rate's frames: whole steps every fps/30 frames, never two in a row, the long run's count
 * the time that passed, the carry under a step. */
static void check_rate(float fps, unsigned frames) {
    double carry = 0;
    const float step = 1.0f / fps;
    unsigned whole = 0, run = 0, longest_between = 0;
    int last = 0;
    float into = 0.0f;
    double time = 0.0;
    for (unsigned i = 0; i < frames; ++i) {
        const BbEffectFrame f = bb_effect_frame(&carry, step);
        assert(f.split && bits(f.frame) == bits(step));
        assert(f.between ? f.step == 0.0f : bits(f.step) == bits(BB_EFFECT_WHOLE_STEP));
        assert(!(last && !f.between) || fps < 60.0f);
        /* The frame begins where the last one ended, and its carry after it is under a step. */
        assert(bits(f.from) == bits(into) && f.into >= 0.0f && f.into < BB_EFFECT_WHOLE_STEP);
        assert(fabs((double)f.from + f.frame - (f.between ? 0.0 : 1.0 / 30.0) - f.into) < 1e-6);
        into = f.into;
        time += f.frame;
        if (!f.between) ++whole, run = 0;
        else if (++run > longest_between) longest_between = run;
        last = !f.between;
        assert(carry > -1e-7 && carry < 1.0 / 30.0);
    }
    const double expected = frames * 30.0 / fps;
    assert(fabs(whole - expected) <= 1.0);
    assert(fabs(whole / 30.0 + carry - time) < 1e-6);
    assert(longest_between == (unsigned)ceil(fps / 30.0) - 1);
}

static void check_schedule(void) {
    /* 30 FPS: the game's own step every frame, bit for bit, and no carry: nothing split. */
    double carry = 0;
    int between;
    for (int i = 0; i < 10000; ++i) {
        const BbEffectFrame f = bb_effect_frame(&carry, BB_EFFECT_WHOLE_STEP);
        assert(bits(f.step) == bits(BB_EFFECT_WHOLE_STEP) && !f.between && !f.split && carry == 0);
        assert(f.frame == 0.0f && bits(f.from) == 0 && bits(f.into) == 0);
    }
    /* 60: whole, between, whole... from the second frame on. */
    carry = 0;
    for (int i = 0; i < 1000; ++i) {
        bb_effect_step(&carry, 1.0f / 60, &between);
        assert(between == !(i & 1));
    }
    /* 90: two frames between each whole step. */
    carry = 0;
    for (int i = 0; i < 900; ++i) {
        bb_effect_step(&carry, 1.0f / 90, &between);
        assert(between == (i % 3 != 2));
    }
    /* 120: the carry a quarter of a step further each frame, back under it at the whole step. */
    carry = 0;
    for (int i = 0; i < 8; ++i) {
        const BbEffectFrame f = bb_effect_frame(&carry, 1.0f / 120);
        assert(f.between == (i % 4 != 3));
        assert(fabs(f.from - (i % 4) / 120.0) < 1e-7 && fabs(f.into - ((i + 1) % 4) / 120.0) < 1e-7);
    }
    const float rates[] = {45, 60, 90, 120, 144, 165, 240, 1000};
    for (size_t i = 0; i < sizeof(rates) / sizeof(*rates); ++i) check_rate(rates[i], 100000);
    /* A second at the rates a player picks: 30 whole steps, the frames adding up to the second. */
    const int picked[] = {60, 90, 120, 144};
    for (size_t i = 0; i < sizeof(picked) / sizeof(*picked); ++i) {
        carry = 0;
        double frames = 0;
        int whole = 0;
        for (int k = 0; k < picked[i]; ++k) {
            const BbEffectFrame f = bb_effect_frame(&carry, 1.0f / picked[i]);
            whole += !f.between;
            frames += f.frame;
        }
        assert(whole == 30 && fabs(frames - 1.0) < 1e-5);
    }
    /* The game's still frame (0), a NaN and a slow frame stay the game's, the carry untouched. */
    carry = 0.01;
    const float odd[] = {0.0f, NAN, 0.05f, -1.0f};
    for (size_t i = 0; i < sizeof(odd) / sizeof(*odd); ++i) {
        const BbEffectFrame f = bb_effect_frame(&carry, odd[i]);
        assert(bits(f.step) == bits(odd[i]) && !f.between && !f.split && carry == 0.01 && f.frame == 0.0f);
    }
    /* Uncapped: frames from 1/240 to 1/20 s; the whole steps and the carry hold the time of the
     * frames under 1/30 s, each split frame beginning where the last split one ended. */
    carry = 0;
    double under = 0;
    unsigned whole = 0;
    uint32_t seed = 12345;
    float into = 0.0f;
    for (int i = 0; i < 1000000; ++i) {
        seed = seed * 1664525u + 1013904223u;
        const float dt = 1.0f / 240 + (1.0f / 20 - 1.0f / 240) * (float)(seed >> 8) / (float)(1u << 24);
        const BbEffectFrame f = bb_effect_frame(&carry, dt);
        if (dt < BB_EFFECT_WHOLE_STEP) {
            under += dt;
            whole += !f.between;
            assert(f.split && bits(f.frame) == bits(dt) && bits(f.from) == bits(into));
            assert(f.between ? f.step == 0.0f : f.step == BB_EFFECT_WHOLE_STEP);
            assert(f.into >= 0.0f && f.into < BB_EFFECT_WHOLE_STEP);
            into = f.into;
        } else {
            assert(f.step == dt && !f.between && !f.split);
        }
    }
    /* Each whole step may come up to 1e-6/30 s early. */
    assert(fabs(whole / 30.0 + carry - under) <= whole * 1e-6 / 30 + 1e-9);
}

static unsigned char *g_image;
static uint64_t at(uint64_t bn) { return (uint64_t)(uintptr_t)(g_image + BB_BN(bn)); }
static void put64(uint64_t address, uint64_t v) { memcpy((void *)(uintptr_t)address, &v, 8); }
static void put32(uint64_t address, uint32_t v) { memcpy((void *)(uintptr_t)address, &v, 4); }
static void put_float(uint64_t address, float v) { memcpy((void *)(uintptr_t)address, &v, 4); }
static uint64_t get64(uint64_t address) {
    uint64_t v;
    memcpy(&v, (const void *)(uintptr_t)address, 8);
    return v;
}
static uint32_t get32(uint64_t address) {
    uint32_t v;
    memcpy(&v, (const void *)(uintptr_t)address, 4);
    return v;
}
static float get_float(uint64_t address) {
    float v;
    memcpy(&v, (const void *)(uintptr_t)address, 4);
    return v;
}
static uint64_t addr(const void *p) { return (uint64_t)(uintptr_t)p; }

static int calls_to(uint64_t call, uint64_t target) {
    int32_t rel;
    memcpy(&rel, g_image + BB_BN(call) + 1, 4);
    return g_image[BB_BN(call)] == 0xe8 && BB_BN(call) + 5 + (int64_t)rel == BB_BN(target);
}

/* The host a hooked call site now reaches: its stub is movabs r11, host; jmp r11. */
static uint64_t host_of(uint64_t call) {
    int32_t rel;
    memcpy(&rel, g_image + BB_BN(call) + 1, 4);
    return get64(at(call) + 5 + (int64_t)rel + 2);
}

/* A stand-in for a game function: movabs rax, fn; jmp rax. */
static void stand_in(uint64_t bn, const void *fn) {
    unsigned char code[12] = {0x48, 0xb8};
    const uint64_t target = addr(fn);
    memcpy(code + 2, &target, 8);
    code[10] = 0xff;
    code[11] = 0xe0;
    memcpy(g_image + BB_BN(bn), code, sizeof(code));
}

static void build_fixture(float step_constant) {
    memset(g_image, 0, IMAGE);
    for (size_t i = 0; i < sizeof(GAME_CODE) / sizeof(*GAME_CODE); ++i)
        bb_test_place_game_code(g_image, BB_BN(GAME_CODE[i].at), GAME_CODE[i].n);
    for (size_t i = 0; i < sizeof(CLASSES) / sizeof(*CLASSES); ++i) {
        bb_test_place_game_code(g_image, BB_BN(CLASSES[i].update), CLASSES[i].n);
        put64(at(CLASSES[i].vtable) + CLASSES[i].slot, at(CLASSES[i].update));
    }
    for (size_t i = 0; i < sizeof(SLOTS) / sizeof(*SLOTS); ++i) put64(at(SLOTS[i][0]), at(SLOTS[i][1]));
    memcpy(g_image + BB_BN(STEP_CONSTANT), &step_constant, 4);
}

/* What the stand-ins saw. */
enum { SEEN = 8 };
static struct {
    int calls;
    float step[SEEN], time[SEEN], definition_time[SEEN];
    uint64_t context[SEEN];
} g_container;
static float g_node_step;
static int g_node_calls, g_controller_calls;
static uint64_t g_light_module, g_follow_motion;
static struct {
    int calls;
    float time[SEEN], rate[SEEN];
    uint32_t mode[SEEN], colour_mode[SEEN];
} g_light;
static int g_wobble_a, g_wobble_a_base, g_wobble_b, g_wobble_b_base, g_follow;
static uint32_t g_follow_period;
static float g_wind_step, g_fades_step;
static uint64_t g_registry, g_receivers;
static struct {
    int calls;
    float step[SEEN], interval[SEEN], smoothing[SEEN], row[SEEN];
} g_record;
static float g_motion_step;

static BB_GUEST_ABI uint64_t fake_manager(uint64_t manager, float step) {
    const float scaled = step * get_float(manager + 0x5d8);
    ((StepFn)(uintptr_t)host_of(WIND_CALL))(g_registry, scaled);
    ((StepFn)(uintptr_t)host_of(RECEIVERS_CALL))(g_receivers, scaled);
    ((StepFn)(uintptr_t)host_of(FADES_CALL))(manager + 0x118, *(uint8_t *)(uintptr_t)(manager + 0x5ce) ? 0.0f : scaled);
    return bits(step);
}
static BB_GUEST_ABI uint64_t fake_controller(uint64_t controller, uint64_t instance, float step) {
    (void)controller, (void)instance, (void)step;
    return ++g_controller_calls;
}
/* The game's node update as far as the smooth steps see it: its two container calls, each with a
 * copy of the step, and its time adds. */
static BB_GUEST_ABI uint8_t fake_node(uint64_t node, float *step, uint64_t definition, uint64_t context) {
    ++g_node_calls;
    g_node_step = *step;
    float copy = *step;
    if (!(get32(node + 0x78) & 8)) {
        ((ContainerFn)(uintptr_t)host_of(CONTAINER_FIRST))(node + 0x80, &copy, definition, context);
        put_float(node + 0xe0, get_float(node + 0xe0) + *step);
    }
    copy = *step;
    ((ContainerFn)(uintptr_t)host_of(CONTAINER_LAST))(node + 0x80, &copy, definition, context);
    put_float(node + 0x7c, get_float(node + 0x7c) + *step);
    return 7;
}
static BB_GUEST_ABI void fake_container(uint64_t container, float *step, uint64_t definition, uint64_t context) {
    (void)definition;
    const uint64_t node = container - 0x80;
    const int i = g_container.calls++ % SEEN;
    g_container.step[i] = *step;
    g_container.time[i] = get_float(node + 0x7c);
    g_container.definition_time[i] = get_float(node + 0xe0);
    g_container.context[i] = context;
    if (g_light_module) ((LightFn)(uintptr_t)get64(at(LIGHT_SLOT)))(g_light_module, 0, context);
    if (g_follow_motion) ((MotionFn)(uintptr_t)get64(at(FOLLOW_SLOT)))(g_follow_motion, node, step, 0);
}
static BB_GUEST_ABI void fake_light(uint64_t module, uint64_t params, uint64_t context) {
    (void)params, (void)context;
    const int i = g_light.calls++ % SEEN;
    g_light.time[i] = get_float(get64(module + 8) + 0x7c);
    g_light.rate[i] = get_float(module + 0x80);
    g_light.mode[i] = get32(module + 0x38);
    g_light.colour_mode[i] = get32(module + 0x3c);
    put32(module + 0x30, 0x12345678);
}
static BB_GUEST_ABI void fake_wobble_a(uint64_t m, uint64_t n, const float *s, uint64_t l) {
    (void)m, (void)n, (void)l;
    g_motion_step = *s;
    ++g_wobble_a;
}
static BB_GUEST_ABI void fake_wobble_a_base(uint64_t m, uint64_t n, const float *s, uint64_t l) {
    (void)m, (void)n, (void)l;
    g_motion_step = *s;
    ++g_wobble_a_base;
}
static BB_GUEST_ABI void fake_wobble_b(uint64_t m, uint64_t n, const float *s, uint64_t l) {
    (void)m, (void)n, (void)s, (void)l;
    ++g_wobble_b;
}
static BB_GUEST_ABI void fake_wobble_b_base(uint64_t m, uint64_t n, const float *s, uint64_t l) {
    (void)m, (void)n, (void)s, (void)l;
    ++g_wobble_b_base;
}
/* The following wobble: its count, then the wobble's own update through its hooked call. */
static BB_GUEST_ABI void fake_follow(uint64_t motion, uint64_t node, const float *step, uint64_t local) {
    ++g_follow;
    g_follow_period = get32(motion + 0x68);
    put32(motion + 0x6c, get32(motion + 0x6c) + 1);
    ((MotionFn)(uintptr_t)host_of(WOBBLE_A_CALL))(motion, node, step, local);
}
static BB_GUEST_ABI void fake_receivers(uint64_t system, float step) {
    (void)step;
    *(uint8_t *)(uintptr_t)(system + 0x4c) = 0;
    put32(system + 0x50, get32(system + 0x50) - 1);
    if (!get32(system + 0x50)) *(uint8_t *)(uintptr_t)(system + 0x4d) = 0;
}
static BB_GUEST_ABI void fake_wind_sources(uint64_t registry, float step) {
    (void)registry;
    g_wind_step = step;
}
static BB_GUEST_ABI void fake_fades(uint64_t list, float step) {
    (void)list;
    g_fades_step = step;
}

/* An emitter's update as StandardParticle's simulation counts it: the timer by the step, an event an
 * interval up to the update's cap (past it the timer dropped), the total times the share truncated. */
static int32_t test_cap(uint64_t sim) {
    const int32_t high = (int32_t)get32(sim + 0x25e4);
    const uint32_t sum = get32(sim + 0x29c4) + get32(sim + 0x25dc) + (uint32_t)(high >= 0 ? high : 0);
    const float a = get_float(sim + 0x29a8), b = get_float(sim + 0x29ac), f = a > b ? a : b;
    const double factor = 1.0f > f ? 1.0 : (double)(f > 50.0f ? 50.0f : f);
    const double x = 2.0 * (double)(int32_t)sum * factor;
    const int32_t r = x >= 2147483647.0 ? INT32_MIN : (int32_t)x;
    if (r < 4) return 20;
    const int32_t limit = (int32_t)get32(sim + 0x2890);
    return (r > limit ? limit : r) + 16;
}
static void fake_simulation(uint64_t sim, float step) {
    put_float(sim + 0x387c, get_float(sim + 0x387c) + step);
    put_float(sim + 0x3880, get_float(sim + 0x3880) + step);
    if (!*(uint8_t *)(uintptr_t)(sim + 0x3872)) {
        put32(sim + 0x3878, 0);
        return;
    }
    const int32_t cap = test_cap(sim);
    const float interval = get_float(sim + 0x3888);
    int32_t n = 0;
    while (get_float(sim + 0x3880) >= interval && n < cap) {
        ++n;
        put_float(sim + 0x3880, get_float(sim + 0x3880) - interval);
        put32(sim + 0x3884, get32(sim + 0x3884) + 1);
    }
    if (n >= cap) put_float(sim + 0x3880, 0.0f);
    int32_t e = (int32_t)((float)n * get_float(sim + 0x3940));
    put32(sim + 0x3878, (uint32_t)(e < 0 ? 0 : e > cap ? cap : e));
}
/* The record update: the item's rows, previous = time, time += the item's step, the type's update. */
static BB_GUEST_ABI void fake_record(uint64_t record, uint64_t item) {
    const uint64_t type = get64(record + 8);
    const int i = g_record.calls++ % SEEN;
    g_record.step[i] = get_float(item + 0x60);
    g_record.row[i] = get_float(item);
    if (get64(type) == at(RIBBON)) {
        g_record.interval[i] = get_float(get64(type + 8) + 0x88);
        g_record.smoothing[i] = get_float(get64(type + 8) + 0x98);
    }
    memcpy((void *)(uintptr_t)(record + 0x50), (const void *)(uintptr_t)item, 48);
    put32(record + 0x24, get32(record + 0x28));
    put_float(record + 0x28, get_float(record + 0x28) + get_float(item + 0x60));
    if (get64(type) == at(STANDARD)) fake_simulation(type + 0x6b0, get_float(record + 0x28) - get_float(record + 0x24));
    if (get64(type) == at(TYPE_2713)) put32(type + 0x1c, 0xdeadbeef);
}

static void place_stand_ins(void) {
    stand_in(MANAGER_UPDATE, (const void *)fake_manager);
    stand_in(CONTROLLER_UPDATE, (const void *)fake_controller);
    stand_in(NODE_UPDATE, (const void *)fake_node);
    stand_in(CONTAINER_UPDATE, (const void *)fake_container);
    stand_in(LIGHT_UPDATE, (const void *)fake_light);
    stand_in(RECORD_UPDATE, (const void *)fake_record);
    stand_in(WOBBLE_A, (const void *)fake_wobble_a);
    stand_in(WOBBLE_A_BASE, (const void *)fake_wobble_a_base);
    stand_in(WOBBLE_B, (const void *)fake_wobble_b);
    stand_in(WOBBLE_B_BASE, (const void *)fake_wobble_b_base);
    stand_in(FOLLOW, (const void *)fake_follow);
    stand_in(RECEIVERS_UPDATE, (const void *)fake_receivers);
    stand_in(WIND_SOURCES, (const void *)fake_wind_sources);
    stand_in(LIGHT_FADES, (const void *)fake_fades);
    FlushInstructionCache(GetCurrentProcess(), g_image, IMAGE);
}

/* The game's objects the tests make: SprjSfx and its manager, an instance with one node. */
static _Alignas(16) unsigned char sfx[0x100], manager[0x600], instance[0x100], node[0x100], motion[0x100];
static _Alignas(16) unsigned char module[0x200], context[8], preroll[8], registry[8], receivers[0x60];
static _Alignas(16) unsigned char record[0x80], item[0x70], type[0x4000], other_type[0x80], definition[0x130];
static _Alignas(16) unsigned char pending[0x30], target[0x20], holder[0x10], part[2][0x20];

static ManagerFn g_effects;
static NodeFn g_node_hold;
static RecordFn g_record_hold;
static double g_carry;  /* the gate's, followed frame by frame */

/* A frame of SprjSfx's manager: what the gate makes of it, as the schedule says. */
static BbEffectFrame frame(float dt) {
    BbEffectFrame f = bb_effect_frame(&g_carry, dt);
    assert(g_effects(addr(manager), dt) == bits(f.step));
    return f;
}
static BbEffectFrame frame_where(float dt, int between, float into_above) {
    for (int i = 0; i < 1000; ++i) {
        const BbEffectFrame f = frame(dt);
        if (f.between == between && f.into > into_above) return f;
    }
    assert(!"no such frame");
    return frame(dt);
}

/* A frame between whole steps after one: an instance's classes looked at again. */
static BbEffectFrame between_after_whole(float dt, float into_above) {
    frame_where(dt, 0, -1.0f);
    return frame_where(dt, 1, into_above);
}

static uint8_t update_node(float step) {
    g_container.calls = g_node_calls = 0;
    float s = step;
    return g_node_hold(addr(node), &s, 0x1234, addr(context));
}

static void reset_node(uint32_t flags, float time, float definition_time) {
    put32(addr(node) + 0x78, flags);
    put_float(addr(node) + 0x7c, time);
    put_float(addr(node) + 0xe0, definition_time);
}

static void check_holds(void) {
    const uint64_t n = addr(node), m = addr(module), ctx = addr(context), pre = addr(preroll);
    put64(pre, at(PREROLL_CONTEXT));
    /* A node of no converted class: the gate's holds. */
    put64(addr(motion), at(EULER) + 8);
    const BbEffectFrame between = frame_where(1.0f / 60, 1, -1.0f);
    assert(between.split && bb_effect_held());
    reset_node(1, 1.5f, 0.25f);
    assert(update_node(0.0f) == 1 && g_node_calls == 0 && g_container.calls == 2);
    assert(g_container.step[0] == 0.0f && g_container.step[1] == 0.0f && g_container.context[1] == ctx);
    assert(get_float(n + 0x7c) == 1.5f && get_float(n + 0xe0) == 0.25f);
    reset_node(1 | 8, 1.5f, 0.25f);  /* staged: its one container update */
    assert(update_node(0.0f) == 1 && g_container.calls == 1);
    reset_node(1 | 4, 1.5f, 0.25f);  /* dead: kept for the next whole step */
    assert(update_node(0.0f) == 1 && g_container.calls == 0);
    reset_node(0, 1.5f, 0.25f);
    assert(update_node(0.0f) == 1 && g_container.calls == 0);
    g_controller_calls = 0;
    assert(((ControllerFn)(uintptr_t)host_of(CONTROLLER_CALL))(1, addr(instance), 0.0f) == 0 && g_controller_calls == 0);

    const LightFn light = (LightFn)(uintptr_t)get64(at(LIGHT_SLOT));
    put64(m + 8, n);
    put_float(m + 0x80, 2.0f);
    put32(m + 0x38, 2);
    put32(m + 0x30, bits(-0.0f));
    g_light.calls = 0;
    light(m, 0, ctx);
    assert(g_light.calls == 1 && g_light.rate[0] == 0.0f && g_light.mode[0] == 1);
    assert(get_float(m + 0x80) == 2.0f && get32(m + 0x38) == 2 && get32(m + 0x30) == bits(-0.0f));
    light(m, 0, pre);  /* a pre-roll's call is the game's */
    assert(g_light.rate[1] == 2.0f && get32(m + 0x30) == 0x12345678);

    /* GPU type 0x2713: a step of 0 keeps the last whole step's elapsed time and values. */
    const uint64_t r = addr(record), it = addr(item), t = addr(other_type);
    put64(t, at(TYPE_2713));
    put64(r + 0x08, t);
    put32(r + 0x24, bits(1.0f));
    put32(r + 0x28, bits(1.0f + 1.0f / 30));
    put32(t + 0x1c, 111);
    put_float(it + 0x60, 0.0f);
    g_record_hold(r, it);
    assert(get32(r + 0x24) == bits(1.0f) && get32(t + 0x1c) == 111);

    /* The wobbles: only their base motion between whole steps, the follow without its lerp. */
    const MotionFn wobble_a = (MotionFn)(uintptr_t)get64(at(WOBBLE_A_SLOT));
    const MotionFn wobble_b = (MotionFn)(uintptr_t)get64(at(WOBBLE_B_SLOT));
    const MotionFn follow = (MotionFn)(uintptr_t)get64(at(FOLLOW_SLOT));
    const float zero = 0.0f;
    wobble_a(addr(motion), n, &zero, 0);
    ((MotionFn)(uintptr_t)host_of(WOBBLE_A_CALL))(addr(motion), n, &zero, 0);
    wobble_b(addr(motion), n, &zero, 0);
    ((MotionFn)(uintptr_t)host_of(WOBBLE_B_CALL))(addr(motion), n, &zero, 0);
    follow(addr(motion), n, &zero, 0);
    assert(g_wobble_a == 0 && g_wobble_a_base == 3 && g_wobble_b == 0 && g_wobble_b_base == 2 && g_follow == 0);

    /* The wind system's warm-up count waits for the whole step. */
    frame_where(1.0f / 60, 0, -1.0f);
    put32(addr(receivers) + 0x50, 60);
    receivers[0x4d] = receivers[0x4c] = 1;
    assert(frame(1.0f / 60).between);
    assert(get32(addr(receivers) + 0x50) == 60 && receivers[0x4d] == 1 && receivers[0x4c] == 0);

    /* A whole step: the game's everywhere. */
    assert(!frame(1.0f / 60).between && !bb_effect_held());
    assert(get32(addr(receivers) + 0x50) == 59);
    reset_node(1, 1.5f, 0.25f);
    assert(update_node(BB_EFFECT_WHOLE_STEP) == 7 && g_node_calls == 1);
    assert(((ControllerFn)(uintptr_t)host_of(CONTROLLER_CALL))(1, addr(instance), 0.0f) == 1);
    put32(m + 0x30, 0);
    light(m, 0, ctx);
    assert(get32(m + 0x30) == 0x12345678 && g_light.rate[2] == 2.0f);
    put_float(it + 0x60, BB_EFFECT_WHOLE_STEP);
    put32(r + 0x24, bits(1.0f));
    g_record_hold(r, it);
    assert(get32(r + 0x24) == bits(1.0f + 1.0f / 30) && get32(t + 0x1c) == 0xdeadbeef);
    wobble_a(addr(motion), n, &zero, 0);
    wobble_b(addr(motion), n, &zero, 0);
    follow(addr(motion), n, &zero, 0);
    assert(g_wobble_a == 2 && g_wobble_b == 1 && g_follow == 1);

    /* The game's still frame, another manager and a step of 1/30 s keep the game's step. */
    put32(addr(sfx) + 0x8c, 1);
    assert(g_effects(addr(manager), 1.0f / 60) == bits(1.0f / 60));
    put32(addr(sfx) + 0x8c, 0);
    assert(g_effects(addr(manager) + 8, 1.0f / 60) == bits(1.0f / 60));
    assert(g_effects(addr(manager), 1.0f / 30) == bits(1.0f / 30));
    assert(update_node(BB_EFFECT_WHOLE_STEP) == 7);
}

static void check_smooth(void) {
    const uint64_t n = addr(node), ctx = addr(context), r = addr(record), it = addr(item), ty = addr(type);
    put64(addr(motion), at(EULER));
    /* Between whole steps: the container calls by the frame's time, the node's times shifted for them. */
    BbEffectFrame f = between_after_whole(1.0f / 120, 1e-4f);
    reset_node(1, 1.5f, 0.25f);
    assert(update_node(0.0f) == 1 && g_node_calls == 0 && g_container.calls == 2);
    for (int i = 0; i < 2; ++i) {
        assert(bits(g_container.step[i]) == bits(f.frame * 0.5f));
        assert(g_container.time[i] == 1.5f + f.from * 0.5f);
    }
    assert(g_container.definition_time[0] == 0.25f + f.from * 0.5f && g_container.definition_time[1] == 0.25f + f.into * 0.5f);
    assert(get_float(n + 0x7c) == 1.5f && get_float(n + 0xe0) == 0.25f);
    assert(g_container.context[0] == ctx && g_container.context[1] == ctx);
    reset_node(1 | 8, 1.5f, 0.25f);
    assert(update_node(0.0f) == 1 && g_container.calls == 1 && g_container.definition_time[0] == 0.25f);
    reset_node(1 | 4, 1.5f, 0.25f);  /* dead: still the next whole step's to free */
    assert(update_node(0.0f) == 1 && g_container.calls == 0);
    g_controller_calls = 0;
    assert(((ControllerFn)(uintptr_t)host_of(CONTROLLER_CALL))(1, addr(instance), 0.0f) == 0 && g_controller_calls == 0);

    /* The FFX light between whole steps: at the frame's time, its rate 0 and blends kept. */
    const uint64_t m = addr(module);
    put64(m + 8, n);
    put_float(m + 0x80, 2.0f);
    put32(m + 0x38, 2);
    put32(m + 0x3c, 2);
    put32(m + 0x30, 77);
    g_light_module = m;
    g_light.calls = 0;
    reset_node(1 | 8, 1.5f, 0.25f);
    update_node(0.0f);
    assert(g_light.calls == 1 && g_light.rate[0] == 0.0f && g_light.mode[0] == 1 && g_light.colour_mode[0] == 1);
    assert(g_light.time[0] == 1.5f + f.from * 0.5f && get32(m + 0x30) == 77 && get32(m + 0x38) == 2 && get32(m + 0x3c) == 2);

    /* The following wobble in a smooth node's call: its update with the period held, its count back. */
    g_follow_motion = addr(motion);
    put32(addr(motion) + 0x68, 5);
    put32(addr(motion) + 0x6c, 3);
    g_follow = g_wobble_a = g_wobble_a_base = 0;
    update_node(0.0f);
    assert(g_follow == 1 && g_follow_period == 0xffffffffu && g_wobble_a == 0 && g_wobble_a_base == 1);
    assert(bits(g_motion_step) == bits(f.frame * 0.5f));
    assert(get32(addr(motion) + 0x68) == 5 && get32(addr(motion) + 0x6c) == 3);
    g_follow_motion = 0;

    /* A whole step: the game's node update with the whole step, its container calls by the frame's. */
    f = frame_where(1.0f / 120, 0, -1.0f);
    reset_node(1, 1.5f, 0.25f);
    g_light.calls = 0;
    assert(update_node(BB_EFFECT_WHOLE_STEP * 0.5f) == 7 && g_node_calls == 1 && g_container.calls == 2);
    assert(bits(g_node_step) == bits(BB_EFFECT_WHOLE_STEP * 0.5f));
    assert(bits(g_container.step[0]) == bits(f.frame * 0.5f) && bits(g_container.step[1]) == bits(f.frame * 0.5f));
    assert(g_container.time[0] == 1.5f + f.from * 0.5f && g_container.time[1] == 1.5f + f.from * 0.5f);
    assert(g_container.definition_time[0] == 0.25f + f.from * 0.5f);
    const float counted = 0.25f + BB_EFFECT_WHOLE_STEP * 0.5f;
    assert(g_container.definition_time[1] == (f.into > 0.0f ? counted + f.into * 0.5f : counted));
    assert(get_float(n + 0x7c) == 1.5f + BB_EFFECT_WHOLE_STEP * 0.5f && get_float(n + 0xe0) == counted);
    /* The light counted at the whole step's time, then at the frame's. */
    assert(g_light.calls == 4 && g_light.rate[0] == 2.0f && g_light.time[0] == 1.5f && g_light.rate[1] == 0.0f);
    assert(g_light.time[1] == 1.5f + f.from * 0.5f && get32(m + 0x30) == 0x12345678);
    g_light_module = 0;

    /* A node with a class off the list: the gate's holds. */
    put64(addr(motion), at(EULER) + 8);
    between_after_whole(1.0f / 120, -1.0f);
    reset_node(1, 1.5f, 0.25f);
    update_node(0.0f);
    assert(g_container.calls == 2 && g_container.step[0] == 0.0f && g_container.time[0] == 1.5f);
    /* A composite of converted parts is converted; with a part off the list it is not. */
    put64(addr(motion), at(COMPOSITE));
    put64(addr(motion) + 8, addr(part[0]));
    put64(addr(motion) + 0x10, addr(part[1]));
    put64(addr(part[0]), at(EULER));
    put64(addr(part[1]), at(WOBBLE_A_SLOT));
    between_after_whole(1.0f / 120, 1e-4f);
    update_node(0.0f);
    assert(g_container.step[0] > 0.0f);
    put64(addr(part[1]), at(EULER) + 8);
    between_after_whole(1.0f / 120, 1e-4f);
    update_node(0.0f);
    assert(g_container.step[0] == 0.0f);
    put64(addr(motion), at(EULER));

    /* A GPU record binder in the node's pending list, its type a ribbon: marked for the record update. */
    put64(addr(node) + 0x80 + 0x30, addr(pending));
    put64(addr(pending) + 0x20, addr(target));
    put64(addr(target), at(GX_BINDER));
    put64(addr(target) + 0x10, addr(holder));
    put64(addr(holder) + 8, ty);
    put64(ty, at(RIBBON));
    put64(ty + 8, addr(definition));
    put_float(addr(definition) + 0x88, 0.05f);
    put_float(addr(definition) + 0x98, 0.5f);
    put64(r + 0x08, ty);
    put64(r + 0x10, n);
    f = between_after_whole(1.0f / 120, 1e-4f);
    reset_node(1 | 8, 1.5f, 0.25f);
    update_node(0.0f);
    assert(g_container.step[0] > 0.0f);
    put_float(r + 0x28, 2.0f);
    put_float(it + 0x60, f.frame * 0.5f);
    g_record.calls = 0;
    g_record_hold(r, it);
    assert(g_record.calls == 1 && isinf(g_record.interval[0]) && g_record.smoothing[0] == 0.0f);
    assert(get64(ty + 8) == addr(definition) && get_float(addr(definition) + 0x88) == 0.05f);
    assert(get_float(r + 0x28) == 2.0f + f.frame * 0.5f);
    /* A whole step past which the frame ends: the inserts at the whole step's time and place, then on. */
    f = frame_where(1.0f / 40, 0, 1e-3f);
    update_node(BB_EFFECT_WHOLE_STEP * 0.5f);
    const float step = f.frame * 0.5f, into = f.into * 0.5f;
    put_float(r + 0x24, 1.9f);
    put_float(r + 0x28, 2.0f);
    for (int i = 0; i < 12; ++i) put_float(r + 0x50 + 4 * (uint64_t)i, 0.0f), put_float(it + 4 * (uint64_t)i, 1.0f);
    put_float(it + 0x60, step);
    g_record.calls = 0;
    g_record_hold(r, it);
    assert(g_record.calls == 2 && g_record.step[0] == step - into && g_record.interval[0] == 0.05f);
    assert(fabsf(g_record.row[0] - (step - into) / step) < 1e-6f);
    assert(g_record.step[1] == into && isinf(g_record.interval[1]) && g_record.row[1] == 1.0f);
    assert(get_float(r + 0x24) == 2.0f && get_float(r + 0x28) == 2.0f + step && get_float(it + 0x60) == step);
    assert(get_float(it) == 1.0f);

    /* Type 0x2713: its update at the whole step's elapsed time, the record's times by the frame's. */
    put64(ty, at(TYPE_2713));
    f = frame_where(1.0f / 120, 1, 1e-4f);
    update_node(0.0f);
    put_float(r + 0x28, 2.0f);
    put_float(it + 0x60, f.frame * 0.5f);
    g_record.calls = 0;
    g_record_hold(r, it);
    assert(g_record.calls == 1 && g_record.step[0] == BB_EFFECT_WHOLE_STEP * 0.5f);
    assert(get_float(r + 0x28) == 2.0f + f.frame * 0.5f);
    assert(get_float(r + 0x28) - get_float(r + 0x24) == (2.0f + BB_EFFECT_WHOLE_STEP * 0.5f) - 2.0f);
    assert(get_float(it + 0x60) == f.frame * 0.5f);

    /* The wind sources and the light fades by the frame's own time on the manager's scale. */
    f = frame(1.0f / 120);
    assert(bits(g_wind_step) == bits(f.frame * 0.5f) && bits(g_fades_step) == bits(f.frame * 0.5f));
    manager[0x5ce] = 1;
    f = frame(1.0f / 120);
    assert(bits(g_wind_step) == bits(f.frame * 0.5f) && g_fades_step == 0.0f);
    manager[0x5ce] = 0;
    assert(g_effects(addr(manager), 1.0f / 30) == bits(1.0f / 30));
    assert(bits(g_wind_step) == bits(1.0f / 30 * 0.5f) && bits(g_fades_step) == bits(1.0f / 30 * 0.5f));
}

/* StandardParticle emitting over a whole step's frames what one update would at 30. */
static int32_t window_emission(int frames_per_step, float interval, float share) {
    const uint64_t r = addr(record), it = addr(item), ty = addr(type), sim = ty + 0x6b0;
    memset(type, 0, sizeof(type));
    put64(ty, at(STANDARD));
    put64(addr(holder) + 8, ty);
    put64(r + 0x08, ty);
    *(uint8_t *)(uintptr_t)(sim + 0x3872) = 1;
    put_float(sim + 0x3888, interval);
    put_float(sim + 0x3940, share);
    put_float(sim + 0x2540, 1e9f);
    put32(sim + 0x2890, 100);
    put32(sim + 0x253c, 1);
    int32_t emitted = 0;
    const float dt = 1.0f / (30.0f * (float)frames_per_step);
    /* Up to the first whole step, so the emitter's windows begin with the effects'. */
    frame_where(dt, 0, -1.0f);
    for (int k = 0; k < frames_per_step; ++k) {
        const BbEffectFrame f = frame(dt);
        assert(f.between == (k != frames_per_step - 1));
        update_node(f.between ? 0.0f : BB_EFFECT_WHOLE_STEP * 0.5f);
        put_float(it + 0x60, f.frame * 0.5f);
        g_record_hold(r, it);
        emitted += (int32_t)get32(sim + 0x3878);
    }
    return emitted;
}

static void check_emission(void) {
    /* What one update of a whole step emits (the stand-in's simulation at 30's step). */
    const uint64_t sim = addr(type) + 0x6b0;
    const float intervals[] = {0.0029f, 0.0005f, 0.0029f}, shares[] = {1.0f, 1.0f, 0.5f};
    for (int c = 0; c < 3; ++c) {
        memset(type, 0, sizeof(type));
        *(uint8_t *)(uintptr_t)(sim + 0x3872) = 1;
        put_float(sim + 0x3888, intervals[c]);
        put_float(sim + 0x3940, shares[c]);
        put32(sim + 0x2890, 100);
        fake_simulation(sim, BB_EFFECT_WHOLE_STEP * 0.5f);
        const int32_t whole = (int32_t)get32(sim + 0x3878);
        assert(whole == (c == 1 ? 20 : c == 0 ? 5 : 2));
        assert(window_emission(4, intervals[c], shares[c]) == whole);
        assert(window_emission(2, intervals[c], shares[c]) == whole);
    }
}

/* The image as the loader leaves it: each TCB load a gs: load with a displacement (probe.c
 * patch_tcb_loads). */
static void tcb_as_loaded(void) {
    static const unsigned char fs[] = {0x64, 0x48, 0x8b, 0x04, 0x25, 0, 0, 0, 0};
    size_t loads = 0;
    for (size_t i = 0; i + sizeof(fs) <= IMAGE; ++i)
        if (g_image[i] == 0x64 && !memcmp(g_image + i, fs, sizeof(fs))) {
            g_image[i] = 0x65;
            g_image[i + 6] = 0x14;
            ++loads;
        }
    assert(loads);
}

static void check_game(void) {
    /* The effects stepping 1/30 s a frame: nothing hooked. */
    build_fixture(1.0f / 30);
    assert(bb_hooks_init(g_image, IMAGE) == 0);
    assert(bb_effect_step_gate_install() == 0 && bb_effect_step_gate_state() == BB_GATE_AT_THIRTY);
    assert(get64(at(MANAGER_SLOT)) == at(MANAGER_UPDATE) && get64(at(LIGHT_SLOT)) == at(LIGHT_UPDATE));
    assert(calls_to(NODE_CALL, NODE_UPDATE) && calls_to(CONTAINER_LAST, CONTAINER_UPDATE));

    /* Uncap FPS++ sends the load to its frame-time cave (jmp at STEP_LOAD): hooked. */
    build_fixture(1.0f / 30);
    const unsigned char uncapped[] = {0xeb, 0xa2};
    memcpy(g_image + BB_BN(STEP_LOAD), uncapped, sizeof(uncapped));
    assert(bb_effect_step_gate_install() == 16 && bb_effect_step_gate_state() == BB_GATE_ON);

    /* BB_EFFECT_SMOOTH=0: the gate's sites only. */
    build_fixture(1.0f / 60);
    _putenv("BB_EFFECT_SMOOTH=0");
    assert(bb_effect_step_gate_install() == 12);
    assert(calls_to(WIND_CALL, WIND_SOURCES) && calls_to(CONTAINER_FIRST, CONTAINER_UPDATE));
    _putenv("BB_EFFECT_SMOOTH=");

    /* A class's update that is not the game's: the gate without the smooth steps. */
    build_fixture(1.0f / 60);
    g_image[BB_BN(0x2e8ec00) + 0x10] ^= 1;
    assert(bb_effect_step_gate_install() == 12);

    /* The loader's TCB loads inside checked functions (the wind warm-up has six). */
    build_fixture(1.0f / 60);
    tcb_as_loaded();
    assert(bb_effect_step_gate_install() == 16);

    /* A 60 FPS list's step: every site hooked. */
    build_fixture(1.0f / 60);
    assert(bb_effect_step_gate_install() == 16);
    bb_hooks_seal();
    DWORD old;
    assert(VirtualProtect(g_image, IMAGE, PAGE_EXECUTE_READWRITE, &old));
    g_effects = (ManagerFn)(uintptr_t)get64(at(MANAGER_SLOT));
    g_node_hold = (NodeFn)(uintptr_t)host_of(NODE_CALL);
    g_record_hold = (RecordFn)(uintptr_t)host_of(RECORD_CALL_A);
    assert(host_of(RECORD_CALL_B) == host_of(RECORD_CALL_A));
    place_stand_ins();

    put64(at(SFX), addr(sfx));
    put64(addr(sfx) + 0x70, addr(manager));
    put_float(addr(manager) + 0x5d8, 1.0f);
    put_float(addr(instance) + 8, 1.0f);
    put64(addr(instance) + 0x38, 0x1234);
    put64(addr(instance) + 0x78, addr(node));
    put64(addr(node) + 0x58, addr(instance));
    put64(addr(node) + 0x90, addr(motion));
    g_registry = addr(registry);
    g_receivers = addr(receivers);
    check_holds();
    /* The smooth steps with the manager's time scale and the instance's at a half each. */
    put_float(addr(manager) + 0x5d8, 0.5f);
    check_smooth();
    put_float(addr(manager) + 0x5d8, 1.0f);
    put_float(addr(instance) + 8, 0.5f);
    check_emission();
}

int main(void) {
    setvbuf(stdout, NULL, _IONBF, 0);
    check_schedule();
    g_image = VirtualAlloc(NULL, IMAGE, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
    assert(g_image);
    const char *game = getenv("BB_TEST_EBOOT_ELF");
    if (game && *game) {
        check_game();
        puts("effect step gate: ok (with the game's code)");
        return 0;
    }
    /* Another image is refused with nothing written; the switch turns it off. */
    assert(bb_hooks_init(g_image, IMAGE) == 0);
    assert(bb_effect_step_gate_install() == 0 && bb_effect_step_gate_state() == BB_GATE_OFF);
    for (size_t i = 0; i < IMAGE; ++i) assert(!g_image[i]);
    _putenv("BB_EFFECT_STEP_GATE=0");
    assert(bb_effect_step_gate_install() == 0 && bb_effect_step_gate_state() == BB_GATE_OFF);
    puts("effect step gate: ok (BB_TEST_EBOOT_ELF unset: the game's code not checked)");
    return 0;
}
