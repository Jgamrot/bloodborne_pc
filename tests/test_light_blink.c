/* SPDX-License-Identifier: GPL-2.0-or-later
 * light_blink.c: the refusal of an image that is not the game's and, with the player's game
 * (game_code.h), the install on the game's own code and the hooked blink against the game's own
 * update (sub_12a25f0, run from the fixture): the game's bit for bit on whole steps, held between
 * them, and lights over 600 game seconds whose cycles begin on whole steps at 30's pace. The
 * effect step gate is a stand-in here; its schedule is the gate's own (bb_effect_frame). */
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
#include "light_blink.h"

/* Binary Ninja addresses, as light_blink.c has them. */
enum {
    BLINK_UPDATE = 0x12a25f0, POINT_UPDATE = 0x2649490, POINT_SLOT = 0x57b7688, POINT_CALL = 0x26494a0,
    SPOT_UPDATE = 0x2649d90, SPOT_SLOT = 0x57b76e8, SPOT_CALL = 0x2649da0, OTHER_UPDATE = 0x2648ee0,
    OTHER_SLOT = 0x57b7628, OTHER_CALL = 0x2648ef7, BLINK_CONSTANTS = 0x4ca887c,
};
static const size_t IMAGE = 0x5700000;
static const struct {
    uint64_t at;
    size_t n;
} GAME_CODE[] = {
    {BLINK_UPDATE, 0x11a}, {POINT_UPDATE, 0x15}, {SPOT_UPDATE, 0x15}, {OTHER_UPDATE, 0x1c},
    {BLINK_CONSTANTS, 0x34}, /* what the update's RIP-relative loads read */
};
static const uint64_t SLOTS[][2] = {{POINT_SLOT, POINT_UPDATE}, {SPOT_SLOT, SPOT_UPDATE}, {OTHER_SLOT, OTHER_UPDATE}};
static const uint64_t CALLS[] = {POINT_CALL, SPOT_CALL, OTHER_CALL};

/* The step gate, as far as the blink reads it. */
static BbGateState g_gate_state = BB_GATE_ON;
static int g_held;
BbGateState bb_effect_step_gate_state(void) { return g_gate_state; }
int bb_effect_held(void) { return g_held; }

typedef void (BB_GUEST_ABI *BlinkFn)(uint64_t, float);

static unsigned char *g_image;
static uint64_t at(uint64_t bn) { return (uint64_t)(uintptr_t)(g_image + BB_BN(bn)); }
static void put64(uint64_t address, uint64_t v) { memcpy((void *)(uintptr_t)address, &v, 8); }
static uint64_t get64(uint64_t address) {
    uint64_t v;
    memcpy(&v, (const void *)(uintptr_t)address, 8);
    return v;
}
static uint32_t bits(float f) {
    uint32_t b;
    memcpy(&b, &f, 4);
    return b;
}
static float from_bits(uint32_t b) {
    float f;
    memcpy(&f, &b, 4);
    return f;
}

static int branches_to(uint64_t site, uint64_t target) {
    int32_t rel;
    memcpy(&rel, g_image + BB_BN(site) + 1, 4);
    return BB_BN(site) + 5 + (int64_t)rel == BB_BN(target);
}

/* The host a hooked call or jmp now reaches: its stub is movabs r11, host; jmp r11. */
static uint64_t host_of(uint64_t site) {
    int32_t rel;
    memcpy(&rel, g_image + BB_BN(site) + 1, 4);
    return get64(at(site) + 5 + (int64_t)rel + 2);
}

static void build_fixture(void) {
    memset(g_image, 0, IMAGE);
    for (size_t i = 0; i < sizeof(GAME_CODE) / sizeof(*GAME_CODE); ++i)
        bb_test_place_game_code(g_image, BB_BN(GAME_CODE[i].at), GAME_CODE[i].n);
    for (size_t i = 0; i < sizeof(SLOTS) / sizeof(*SLOTS); ++i) put64(at(SLOTS[i][0]), at(SLOTS[i][1]));
}

/* An install that writes nothing: 0 hooks and the image as it was. */
static void refused(void) {
    unsigned char *before = malloc(IMAGE);
    assert(before);
    memcpy(before, g_image, IMAGE);
    assert(bb_light_blink_install() == 0);
    assert(!memcmp(before, g_image, IMAGE));
    free(before);
}

static uint32_t g_seed = 0x12a25f0u;
static uint32_t rnd(void) {
    g_seed ^= g_seed << 13;
    g_seed ^= g_seed >> 17;
    g_seed ^= g_seed << 5;
    return g_seed;
}
static float odd_float(void) {
    static const uint32_t odd[] = {0, 0x80000000u, 1, 0x007fffffu, 0x7f800000u, 0xff800000u, 0x7fc00000u,
                                   0xffc00001u, 0x3f800000u, 0x3d088889u, 0x3c888889u};
    switch (rnd() % 4) {
    case 0: return from_bits(odd[rnd() % (sizeof(odd) / sizeof(*odd))]);
    case 1: return from_bits(rnd());
    default: return (float)(rnd() % 4000) / 4000.0f * 0.4f;
    }
}
static void random_blink(unsigned char *b) {
    for (int i = 0; i < 0x30; i += 4) {
        const uint32_t v = rnd();
        memcpy(b + i, &v, 4);
    }
    const int none = rnd() % 8 == 0;
    for (int o = 0x14; o <= 0x28; o += 4) {
        const float f = none && o <= 0x18 ? 0.0f : odd_float();
        memcpy(b + o, &f, 4);
    }
}

static float field(const unsigned char *b, int o) {
    float f;
    memcpy(&f, b + o, 4);
    return f;
}

/* Fuzzed blinks: on whole steps the hook is the game's bit for bit; between them it is the game's
 * unless the time is past the length, where the light holds its next cycle's first factor, its
 * generator and length untouched, its time moved on. */
static void check_against_game(void) {
    const BlinkFn game = (BlinkFn)(uintptr_t)at(BLINK_UPDATE);
    unsigned held = 0;
    for (int i = 0; i < 400000; ++i) {
        for (size_t c = 0; c < sizeof(CALLS) / sizeof(*CALLS); ++c) {
            const BlinkFn ours = (BlinkFn)(uintptr_t)host_of(CALLS[c]);
            _Alignas(16) unsigned char a[0x30], b[0x30], next[0x30], was[0x30];
            random_blink(a);
            memcpy(b, a, sizeof(a));
            memcpy(next, a, sizeof(a));
            memcpy(was, a, sizeof(a));
            const float step = rnd() % 16 ? 1.0f / (30 + rnd() % 211) : odd_float();
            g_held = i & 1;
            ours((uint64_t)(uintptr_t)a, step);
            game((uint64_t)(uintptr_t)b, step);
            const float time = field(was, 0x28), length = field(was, 0x24);
            const int none = field(was, 0x14) == 0.0f && field(was, 0x18) == 0.0f;
            if (!g_held || none || !(time > length)) {
                assert(!memcmp(a, b, sizeof(a)));
                continue;
            }
            ++held;
            game((uint64_t)(uintptr_t)next, 0.0f);
            assert(bits(field(a, 0x2c)) == bits(field(next, 0x2c)));
            assert(bits(field(a, 0x28)) == bits(time + step));
            /* The generator, the bounds and the length are the blink's as it was. */
            assert(!memcmp(a, was, 0x28));
        }
    }
    printf("  %u fuzzed blinks held between whole steps, the rest the game's bit for bit\n", held);
    assert(held > 1000);
}

/* What one light does over `seconds` of game time at `fps`: the frame's held flag as the game
 * reads it (the gate's schedule of the frame before), its cycles, their lengths in frames. */
typedef struct {
    unsigned cycles, frames, off_whole, uneven;
    double game_s;
} Run;
static Run run_light(float shortest, float longest, float fps, double seconds, int hold) {
    const BlinkFn ours = (BlinkFn)(uintptr_t)host_of(POINT_CALL);
    _Alignas(16) unsigned char b[0x30] = {0};
    const uint32_t seed[4] = {0x2545f491u, 0x9e3779b9u, 0x6a09e667u, 0xbb67ae85u};
    memcpy(b + 4, seed, sizeof(seed));
    memcpy(b + 0x14, &shortest, 4);
    memcpy(b + 0x18, &longest, 4);
    const float low = 0.4f, high = 1.0f, step = 1.0f / fps;
    memcpy(b + 0x1c, &low, 4);
    memcpy(b + 0x20, &high, 4);
    Run r = {0};
    double carry = 0;
    int held = 0;
    const int ratio = (int)lroundf(fps / 30.0f);
    const int integral = fabsf(fps / 30.0f - (float)ratio) < 1e-6f;
    unsigned since = 0;
    const unsigned frames = (unsigned)(seconds * fps);
    for (unsigned i = 0; i < frames; ++i) {
        g_held = hold && held;
        uint32_t generator[4];
        memcpy(generator, b + 4, sizeof(generator));
        ours((uint64_t)(uintptr_t)b, step);
        ++since;
        /* A cycle begins with a draw from the light's generator. */
        if (memcmp(generator, b + 4, sizeof(generator))) {
            ++r.cycles;
            r.off_whole += g_held;
            if (r.cycles > 1 && integral && since % (unsigned)ratio) ++r.uneven;
            since = 0;
        }
        held = bb_effect_frame(&carry, step).between;
        ++r.frames;
    }
    r.game_s = frames * (double)step;
    return r;
}

static void check_pace(void) {
    static const float lights[][2] = {{0.12f, 0.28f}, {0.05f, 0.11f}, {0.21f, 0.21f}, {0.3f, 0.9f}, {0.002f, 0.006f}};
    static const float rates[] = {60, 90, 120, 144, 240};
    for (size_t l = 0; l < sizeof(lights) / sizeof(*lights); ++l) {
        const Run thirty = run_light(lights[l][0], lights[l][1], 30, 600, 1);
        const double base = thirty.cycles / thirty.game_s;
        assert(!thirty.off_whole && thirty.cycles > 0);
        for (size_t f = 0; f < sizeof(rates) / sizeof(*rates); ++f) {
            const Run r = run_light(lights[l][0], lights[l][1], rates[f], 600, 1);
            const Run game = run_light(lights[l][0], lights[l][1], rates[f], 600, 0);
            const double pace = r.cycles / r.game_s, game_pace = game.cycles / game.game_s;
            printf("  light %.3f-%.3f s at %3.0f FPS: %.3f cycles a game second (30: %.3f, the game's own: %.3f)\n",
                   lights[l][0], lights[l][1], rates[f], pace, base, game_pace);
            /* Cycles begin only on whole steps, a whole number of 1/30 s long. */
            assert(!r.off_whole && !r.uneven);
            assert(fabs(pace / base - 1.0) < (lights[l][1] < 0.01f ? 0.002 : 0.01));
            /* The game's own update begins them faster above 30. */
            assert(game_pace / base > 1.01);
        }
    }
}

static void check_game(void) {
    /* Not installed without the gate, at 30 or with the switch. */
    build_fixture();
    assert(bb_hooks_init(g_image, IMAGE) == 0);
    g_gate_state = BB_GATE_AT_THIRTY;
    refused();
    g_gate_state = BB_GATE_OFF;
    refused();
    g_gate_state = BB_GATE_ON;
    _putenv("BB_BLINK_HOLD=0");
    refused();
    _putenv("BB_BLINK_HOLD=");

    /* Each site that is not the game's refuses the whole install. */
    static const uint64_t changed[] = {BLINK_UPDATE + 0x40, POINT_UPDATE + 3, SPOT_UPDATE + 0xa, OTHER_UPDATE + 2};
    for (size_t i = 0; i < sizeof(changed) / sizeof(*changed); ++i) {
        build_fixture();
        g_image[BB_BN(changed[i])] ^= 1;
        refused();
    }
    for (size_t i = 0; i < sizeof(SLOTS) / sizeof(*SLOTS); ++i) {
        build_fixture();
        put64(at(SLOTS[i][0]), at(SLOTS[i][1]) + 16);
        refused();
    }

    /* The loader's TCB loads: none in the checked code, which installs as the executable has it. */
    build_fixture();
    static const unsigned char fs[] = {0x64, 0x48, 0x8b, 0x04, 0x25};
    for (size_t i = 0; i + sizeof(fs) <= IMAGE; ++i) assert(g_image[i] != 0x64 || memcmp(g_image + i, fs, sizeof(fs)));
    assert(bb_light_blink_install() == 3);

    build_fixture();
    assert(bb_light_blink_install() == 3);
    for (size_t i = 0; i < sizeof(CALLS) / sizeof(*CALLS); ++i) assert(!branches_to(CALLS[i], BLINK_UPDATE));
    assert(host_of(POINT_CALL) == host_of(SPOT_CALL) && host_of(SPOT_CALL) == host_of(OTHER_CALL));
    bb_hooks_seal();
    DWORD old;
    assert(VirtualProtect(g_image, IMAGE, PAGE_EXECUTE_READWRITE, &old));
    FlushInstructionCache(GetCurrentProcess(), g_image, IMAGE);
    check_against_game();
    check_pace();
}

int main(void) {
    setvbuf(stdout, NULL, _IONBF, 0);
    g_image = VirtualAlloc(NULL, IMAGE, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
    assert(g_image);
    const char *game = getenv("BB_TEST_EBOOT_ELF");
    if (game && *game) {
        check_game();
        puts("light blink: ok (with the game's code)");
        return 0;
    }
    /* Another image is refused with nothing written. */
    assert(bb_hooks_init(g_image, IMAGE) == 0);
    refused();
    puts("light blink: ok (BB_TEST_EBOOT_ELF unset: the game's code not checked)");
    return 0;
}
