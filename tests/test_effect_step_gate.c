/* SPDX-License-Identifier: GPL-2.0-or-later
 * effect_step_gate.c: the whole 1/30 s steps the effect manager takes at each frame rate, the
 * refusal of an image that is not the game's, and, with the player's game (game_code.h), the
 * install on the game's own code and each hold against stand-ins for the functions it calls. */
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

/* Binary Ninja addresses, as effect_step_gate.c has them. */
enum {
    SFX = 0x5940370, EFFECTS_CALL = 0x2377d34, EFFECTS_CALL_END = 0x2377d52, STEP_LOAD = 0x2377d48,
    STEP_CONSTANT = 0x4d29170, MANAGER_SLOT = 0x57b90c0, MANAGER_UPDATE = 0x26ff340,
    INSTANCE_UPDATE = 0x2c4ff30, CONTROLLER_CALL = 0x2c4fffb, CONTROLLER_UPDATE = 0x2c820f0,
    NODE_CALL = 0x2c5007b, NODE_UPDATE = 0x2c4df80, CONTAINER_UPDATE = 0x2c4c8c0,
    LIGHT_SLOT = 0x56ebbb8, LIGHT_UPDATE = 0x131e660, PREROLL_CONTEXT = 0x56dbd80,
    RECORD_CALL_A = 0x2cbaaf7, RECORD_CALL_B = 0x2cbab1d, RECORD_UPDATE = 0x2cbcf50,
    TYPE_2713 = 0x56eb0d0, TYPE_2713_UPDATE = 0x12e81b0,
};
static const size_t IMAGE = 0x5600000;
static const struct {
    uint64_t at;
    size_t n;
} GAME_CODE[] = {
    {EFFECTS_CALL, 16}, {EFFECTS_CALL_END, 14}, {STEP_LOAD, 10}, {MANAGER_UPDATE, 28},
    {INSTANCE_UPDATE, 0x1ae}, {NODE_UPDATE, 0x66c}, {CONTAINER_UPDATE, 20}, {LIGHT_UPDATE, 0x8d2},
    {RECORD_UPDATE, 0x1d5}, {TYPE_2713_UPDATE, 0x274}, {CONTROLLER_CALL, 5}, {NODE_CALL, 5},
    {RECORD_CALL_A, 5}, {RECORD_CALL_B, 5},
};

typedef uint64_t (BB_GUEST_ABI *ManagerFn)(uint64_t, float);
typedef uint64_t (BB_GUEST_ABI *ControllerFn)(uint64_t, uint64_t, float);
typedef uint8_t (BB_GUEST_ABI *NodeFn)(uint64_t, float *, uint64_t, uint64_t);
typedef void (BB_GUEST_ABI *LightFn)(uint64_t, uint64_t, uint64_t);
typedef void (BB_GUEST_ABI *RecordFn)(uint64_t, uint64_t);

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
    for (unsigned i = 0; i < frames; ++i) {
        int between;
        const float taken = bb_effect_step(&carry, step, &between);
        assert(between ? taken == 0.0f : bits(taken) == bits(BB_EFFECT_WHOLE_STEP));
        assert(!(last && !between) || fps < 60.0f);
        if (!between) ++whole, run = 0;
        else if (++run > longest_between) longest_between = run;
        last = !between;
        assert(carry > -1e-7 && carry < 1.0 / 30.0);
    }
    const double expected = frames * 30.0 / fps;
    assert(fabs(whole - expected) <= 1.0);
    assert(longest_between == (unsigned)ceil(fps / 30.0) - 1);
}

static void check_schedule(void) {
    /* 30 FPS: the game's own step every frame, bit for bit, and no carry. */
    double carry = 0;
    int between;
    for (int i = 0; i < 10000; ++i) {
        assert(bits(bb_effect_step(&carry, BB_EFFECT_WHOLE_STEP, &between)) == bits(BB_EFFECT_WHOLE_STEP));
        assert(!between && carry == 0);
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
    const float rates[] = {45, 60, 90, 120, 144, 165, 240, 1000};
    for (size_t i = 0; i < sizeof(rates) / sizeof(*rates); ++i) check_rate(rates[i], 100000);
    /* The game's still frame (0), a NaN and a slow frame stay the game's, the carry untouched. */
    carry = 0.01;
    assert(bb_effect_step(&carry, 0.0f, &between) == 0.0f && !between && carry == 0.01);
    assert(isnan(bb_effect_step(&carry, NAN, &between)) && !between && carry == 0.01);
    assert(bb_effect_step(&carry, 0.05f, &between) == 0.05f && !between && carry == 0.01);
    /* Uncapped: frames from 1/240 to 1/20 s; the whole steps and the carry hold the time of the
     * frames under 1/30 s. */
    carry = 0;
    double under = 0;
    unsigned whole = 0;
    uint32_t seed = 12345;
    for (int i = 0; i < 1000000; ++i) {
        seed = seed * 1664525u + 1013904223u;
        const float dt = 1.0f / 240 + (1.0f / 20 - 1.0f / 240) * (float)(seed >> 8) / (float)(1u << 24);
        const float taken = bb_effect_step(&carry, dt, &between);
        if (dt < BB_EFFECT_WHOLE_STEP) {
            under += dt;
            whole += !between;
            assert(between ? taken == 0.0f : taken == BB_EFFECT_WHOLE_STEP);
        } else {
            assert(taken == dt && !between);
        }
    }
    /* Each whole step may come up to 1e-6/30 s early. */
    assert(fabs(whole / 30.0 + carry - under) <= whole * 1e-6 / 30 + 1e-9);
}

static unsigned char *g_image;
static uint64_t at(uint64_t bn) { return (uint64_t)(uintptr_t)(g_image + BB_BN(bn)); }
static void put64(uint64_t address, uint64_t v) { memcpy((void *)(uintptr_t)address, &v, 8); }
static void put32(uint64_t address, uint32_t v) { memcpy((void *)(uintptr_t)address, &v, 4); }
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

/* The host a hooked call site now reaches: its stub is movabs r11, host; jmp r11. */
static uint64_t host_of(uint64_t call) {
    int32_t rel;
    memcpy(&rel, g_image + BB_BN(call) + 1, 4);
    return get64(at(call) + 5 + (int64_t)rel + 2);
}

static void place(uint64_t bn, const unsigned char *code, size_t n) { memcpy(g_image + BB_BN(bn), code, n); }

/* Stand-ins for the game's functions the holds call, written over its code once installed. */
static const unsigned char manager_code[] = {0x66, 0x0f, 0x7e, 0xc0, 0xc3};  /* movd eax, xmm0 */
static const unsigned char controller_code[] = {0xff, 0x07, 0xc3};             /* inc dword [rdi] */
/* inc dword [rdi+0xe8]; mov al, 7 */
static const unsigned char node_code[] = {0xff, 0x87, 0xe8, 0x00, 0x00, 0x00, 0xb0, 0x07, 0xc3};
/* inc dword [rdi+0x70]; mov eax, [rsi]; mov [rdi+0x74], eax; mov [rdi+0x78], rcx */
static const unsigned char container_code[] = {0xff, 0x47, 0x70, 0x8b, 0x06, 0x89, 0x47, 0x74,
                                               0x48, 0x89, 0x4f, 0x78, 0xc3};
/* The rate and mode it sees at +0x90 and +0x94, the phase set to 0x12345678. */
static const unsigned char light_code[] = {0x8b, 0x87, 0x80, 0x00, 0x00, 0x00, 0x89, 0x87, 0x90, 0x00, 0x00, 0x00,
                                           0x8b, 0x47, 0x38, 0x89, 0x87, 0x94, 0x00, 0x00, 0x00,
                                           0xc7, 0x47, 0x30, 0x78, 0x56, 0x34, 0x12, 0xc3};
/* previous = time; the type's first size and first colour word set to 0xdeadbeef. */
static const unsigned char record_code[] = {0x8b, 0x47, 0x28, 0x89, 0x47, 0x24, 0x48, 0x8b, 0x47, 0x08,
                                            0xc7, 0x40, 0x1c, 0xef, 0xbe, 0xad, 0xde,
                                            0xc7, 0x40, 0x50, 0xef, 0xbe, 0xad, 0xde, 0xc3};

static void build_fixture(float step_constant) {
    memset(g_image, 0, IMAGE);
    for (size_t i = 0; i < sizeof(GAME_CODE) / sizeof(*GAME_CODE); ++i)
        bb_test_place_game_code(g_image, BB_BN(GAME_CODE[i].at), GAME_CODE[i].n);
    put64(at(MANAGER_SLOT), at(MANAGER_UPDATE));
    put64(at(LIGHT_SLOT), at(LIGHT_UPDATE));
    put64(at(TYPE_2713) + 0x10, at(TYPE_2713_UPDATE));
    memcpy(g_image + BB_BN(STEP_CONSTANT), &step_constant, 4);
}

static void check_game(void) {
    /* The effects stepping 1/30 s a frame: nothing hooked. */
    build_fixture(1.0f / 30);
    assert(bb_hooks_init(g_image, IMAGE) == 0);
    assert(bb_effect_step_gate_install() == 0);
    assert(get64(at(MANAGER_SLOT)) == at(MANAGER_UPDATE) && get64(at(LIGHT_SLOT)) == at(LIGHT_UPDATE));
    int32_t rel;
    memcpy(&rel, g_image + BB_BN(NODE_CALL) + 1, 4);
    assert(g_image[BB_BN(NODE_CALL)] == 0xe8 && BB_BN(NODE_CALL) + 5 + (int64_t)rel == BB_BN(NODE_UPDATE));

    /* Uncap FPS++ sends the load to its frame-time cave (jmp at STEP_LOAD): hooked. */
    build_fixture(1.0f / 30);
    const unsigned char uncapped[] = {0xeb, 0xa2};
    place(STEP_LOAD, uncapped, sizeof(uncapped));
    assert(bb_effect_step_gate_install() == 6);

    /* A 60 FPS list's step: every site hooked. */
    build_fixture(1.0f / 60);
    assert(bb_effect_step_gate_install() == 6);
    bb_hooks_seal();
    DWORD old;
    assert(VirtualProtect(g_image, IMAGE, PAGE_EXECUTE_READWRITE, &old));
    const ManagerFn effects = (ManagerFn)(uintptr_t)get64(at(MANAGER_SLOT));
    const LightFn light = (LightFn)(uintptr_t)get64(at(LIGHT_SLOT));
    const NodeFn node_hold = (NodeFn)(uintptr_t)host_of(NODE_CALL);
    const ControllerFn controller_hold = (ControllerFn)(uintptr_t)host_of(CONTROLLER_CALL);
    const RecordFn record_hold = (RecordFn)(uintptr_t)host_of(RECORD_CALL_A);
    assert(host_of(RECORD_CALL_B) == host_of(RECORD_CALL_A));
    place(MANAGER_UPDATE, manager_code, sizeof(manager_code));
    place(CONTROLLER_UPDATE, controller_code, sizeof(controller_code));
    place(NODE_UPDATE, node_code, sizeof(node_code));
    place(CONTAINER_UPDATE, container_code, sizeof(container_code));
    place(LIGHT_UPDATE, light_code, sizeof(light_code));
    place(RECORD_UPDATE, record_code, sizeof(record_code));
    FlushInstructionCache(GetCurrentProcess(), g_image, IMAGE);

    static unsigned char sfx[0x100], manager[0x10], node[0x100], controller[4], module[0x100];
    static unsigned char record[0x30], item[0x70], type[0x80], other_type[0x80], context[8], preroll[8];
    put64(at(SFX), (uint64_t)(uintptr_t)sfx);
    put64((uint64_t)(uintptr_t)sfx + 0x70, (uint64_t)(uintptr_t)manager);
    const uint64_t m = (uint64_t)(uintptr_t)manager;
    const uint64_t n = (uint64_t)(uintptr_t)node, c = (uint64_t)(uintptr_t)controller;
    const uint64_t ctx = (uint64_t)(uintptr_t)context, pre = (uint64_t)(uintptr_t)preroll;
    put64(pre, at(PREROLL_CONTEXT));

    /* A frame between whole steps (the first at 60): the manager gets 0 and the holds act. */
    assert(effects(m, 1.0f / 60) == 0);
    float zero = 0.0f;
    put32(n + 0x78, 1);
    put32(n + 0x7c, bits(1.5f));
    put32(n + 0xe0, bits(0.25f));
    assert(node_hold(n, &zero, 0x1234, ctx) == 1);
    assert(get32(n + 0xf0) == 2 && get64(n + 0xf8) == ctx && get32(n + 0xf4) == 0 && get32(n + 0xe8) == 0);
    assert(get_float(n + 0x7c) == 1.5f && get_float(n + 0xe0) == 0.25f);
    put32(n + 0x78, 1 | 8);  /* staged: its one container update */
    assert(node_hold(n, &zero, 0x1234, ctx) == 1 && get32(n + 0xf0) == 3);
    put32(n + 0x78, 1 | 4);  /* dead: kept for the next whole step */
    assert(node_hold(n, &zero, 0x1234, ctx) == 1 && get32(n + 0xf0) == 3);
    put32(n + 0x78, 0);
    assert(node_hold(n, &zero, 0x1234, ctx) == 1 && get32(n + 0xf0) == 3 && get32(n + 0xe8) == 0);
    assert(controller_hold(c, 0, 0.0f) == 0 && get32(c) == 0);

    put32((uint64_t)(uintptr_t)module + 0x80, bits(2.0f));
    put32((uint64_t)(uintptr_t)module + 0x38, 2);
    put32((uint64_t)(uintptr_t)module + 0x30, bits(-0.0f));
    light((uint64_t)(uintptr_t)module, 0, ctx);
    assert(get32((uint64_t)(uintptr_t)module + 0x90) == 0 && get32((uint64_t)(uintptr_t)module + 0x94) == 1);
    assert(get32((uint64_t)(uintptr_t)module + 0x80) == bits(2.0f) && get32((uint64_t)(uintptr_t)module + 0x38) == 2);
    assert(get32((uint64_t)(uintptr_t)module + 0x30) == bits(-0.0f));
    light((uint64_t)(uintptr_t)module, 0, pre);  /* a pre-roll's call is the game's */
    assert(get32((uint64_t)(uintptr_t)module + 0x90) == bits(2.0f) && get32((uint64_t)(uintptr_t)module + 0x30) == 0x12345678);

    const uint64_t r = (uint64_t)(uintptr_t)record, it = (uint64_t)(uintptr_t)item, t = (uint64_t)(uintptr_t)type;
    put64(t, at(TYPE_2713));
    put64(r + 0x08, t);
    put32(r + 0x24, bits(1.0f));
    put32(r + 0x28, bits(1.0f + 1.0f / 30));
    put32(t + 0x1c, 111);
    put32(t + 0x50, 222);
    record_hold(r, it);  /* a step of 0: the last whole step's elapsed time and values kept */
    assert(get32(r + 0x24) == bits(1.0f) && get32(t + 0x1c) == 111 && get32(t + 0x50) == 222);
    put32(it + 0x60, bits(1.0f / 30));
    record_hold(r, it);
    assert(get32(r + 0x24) == bits(1.0f + 1.0f / 30) && get32(t + 0x1c) == 0xdeadbeef);
    put64((uint64_t)(uintptr_t)other_type, at(TYPE_2713) + 8);
    put64(r + 0x08, (uint64_t)(uintptr_t)other_type);
    put32(r + 0x24, bits(1.0f));
    put32(it + 0x60, 0);
    record_hold(r, it);
    assert(get32(r + 0x24) == bits(1.0f + 1.0f / 30));

    /* The whole step: 1/30 s to the manager, every hold the game's. */
    assert(effects(m, 1.0f / 60) == bits(BB_EFFECT_WHOLE_STEP));
    put32(n + 0x78, 1);
    assert(node_hold(n, &zero, 0x1234, ctx) == 7 && get32(n + 0xe8) == 1 && get32(n + 0xf0) == 3);
    controller_hold(c, 0, 0.0f);
    assert(get32(c) == 1);
    put32((uint64_t)(uintptr_t)module + 0x30, 0);
    light((uint64_t)(uintptr_t)module, 0, ctx);
    assert(get32((uint64_t)(uintptr_t)module + 0x30) == 0x12345678);
    put64(r + 0x08, t);
    put32(r + 0x24, bits(1.0f));
    record_hold(r, it);
    assert(get32(r + 0x24) == bits(1.0f + 1.0f / 30));

    /* The game's still frame, another manager and a step of 1/30 s keep the game's step. */
    put32((uint64_t)(uintptr_t)sfx + 0x8c, 1);
    assert(effects(m, 1.0f / 60) == bits(1.0f / 60));
    assert(node_hold(n, &zero, 0x1234, ctx) == 7);
    put32((uint64_t)(uintptr_t)sfx + 0x8c, 0);
    assert(effects(m + 8, 1.0f / 60) == bits(1.0f / 60));
    assert(effects(m, 1.0f / 30) == bits(1.0f / 30));
    assert(node_hold(n, &zero, 0x1234, ctx) == 7);
}

int main(void) {
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
    assert(bb_effect_step_gate_install() == 0);
    for (size_t i = 0; i < IMAGE; ++i) assert(!g_image[i]);
    _putenv("BB_EFFECT_STEP_GATE=0");
    assert(bb_effect_step_gate_install() == 0);
    puts("effect step gate: ok (BB_TEST_EBOOT_ELF unset: the game's code not checked)");
    return 0;
}
