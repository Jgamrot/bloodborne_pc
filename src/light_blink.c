/* SPDX-License-Identifier: GPL-2.0-or-later
 * The GX lights' blink at 30's pace above 30 FPS (light_blink.h). Ported from droogie's bbhost
 * (https://github.com/droogie/bbhost, GPL-3.0-or-later, branch render/next-12: f24d18f;
 * src/decomp/gx/blink.cpp).
 *
 * A GX light (point lights at +0x130, spot lights at +0x1ac, the lights of vtable 0x57b7610 at
 * +0x150: the map's lights and the effects' light modules alike) keeps a blink that
 * sub_12a25f0 steps once a frame, from the light's update in the GX world's update:
 *   +0x04..+0x10  the light's own xorshift128 state, which nothing else draws from
 *   +0x14, +0x18  the shortest and longest cycle (both 0: no blink, the factor 1)
 *   +0x24, +0x28  the cycle's length and the time in it; +0x2c the factor the colour is scaled by
 * Once the time is past the length a cycle begins: a length drawn from the generator, the time 0,
 * the factor a triangle over the cycle. The time past the length is dropped, half a frame on
 * average, so above 30 the cycles are shorter (4.95 a game second at 30 in the Grand Cathedral,
 * 5.24 at 60, 5.31 at 120).
 *
 * Here a cycle begins only on a frame after one on which the effects took a whole step (the step
 * gate's schedule: the GX world's update runs just before SprjSfx::Update in sub_219b340, so it
 * reads the frame before's). On the frames between, a light past its cycle's length takes the
 * factor its next cycle begins with, from the game's update run on a copy of the blink, and its
 * time moves on; its generator is left for the next whole step to draw from. A cycle then lasts a
 * whole number of 1/30 s and draws once, as at 30. Everywhere else the update is the game's.
 *
 * Addresses are Binary Ninja's (BB_BN gives the image offset). */
#include "light_blink.h"
#include "effect_step_gate.h"
#include "engine_hooks.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum {
    BLINK_UPDATE = 0x12a25f0, /* (blink, float step) */
    POINT_UPDATE = 0x2649490, /* vtable 0x57b7670 +0x18: call at +0x10 with the blink at +0x130 */
    POINT_SLOT = 0x57b7688,
    POINT_CALL = 0x26494a0,
    SPOT_UPDATE = 0x2649d90,  /* vtable 0x57b76d0 +0x18: call at +0x10 with the blink at +0x1ac */
    SPOT_SLOT = 0x57b76e8,
    SPOT_CALL = 0x2649da0,
    OTHER_UPDATE = 0x2648ee0, /* vtable 0x57b7610 +0x18: jmp at +0x17 with the blink at +0x150 */
    OTHER_SLOT = 0x57b7628,
    OTHER_CALL = 0x2648ef7,
};

static const struct {
    uint64_t at;
    BbCode code;
} CODE[] = {
    {BLINK_UPDATE, {0x11a, 0x02f20a0002bf1951ull}},
    {POINT_UPDATE, {0x15, 0xf7c6bc1ec482f06dull}},
    {SPOT_UPDATE, {0x15, 0x18b5bd0ddda12942ull}},
    {OTHER_UPDATE, {0x1c, 0xfed98ed62f6b89b4ull}},
};
static const struct {
    uint64_t slot, update, call;
} LIGHTS[] = {
    {POINT_SLOT, POINT_UPDATE, POINT_CALL},
    {SPOT_SLOT, SPOT_UPDATE, SPOT_CALL},
    {OTHER_SLOT, OTHER_UPDATE, OTHER_CALL},
};

enum { SHORTEST = 0x14, LONGEST = 0x18, LENGTH = 0x24, TIME = 0x28, FACTOR = 0x2c, BLINK_SIZE = 0x30 };

typedef void (BB_GUEST_ABI *BlinkFn)(uint64_t, float);

static uint64_t guest(uint64_t bn) { return (uint64_t)(uintptr_t)bb_guest(BB_BN(bn)); }
static uint64_t read64(uint64_t at) {
    uint64_t v;
    memcpy(&v, (const void *)(uintptr_t)at, 8);
    return v;
}
static float read_float(uint64_t at) {
    float v;
    memcpy(&v, (const void *)(uintptr_t)at, 4);
    return v;
}
static void write_float(uint64_t at, float v) { memcpy((void *)(uintptr_t)at, &v, 4); }

static BB_GUEST_ABI void on_blink(uint64_t blink, float step) {
    const BlinkFn game = (BlinkFn)bb_guest(BB_BN(BLINK_UPDATE));
    const float time = read_float(blink + TIME);
    /* The game's own tests: both bounds 0 is no blink, and a NaN time or length is not past. */
    if (!bb_effect_held() || (read_float(blink + SHORTEST) == 0.0f && read_float(blink + LONGEST) == 0.0f) ||
        !(time > read_float(blink + LENGTH))) {
        game(blink, step);
        return;
    }
    _Alignas(16) unsigned char next[BLINK_SIZE];
    memcpy(next, (const void *)(uintptr_t)blink, sizeof(next));
    game((uint64_t)(uintptr_t)next, 0.0f);
    memcpy((void *)(uintptr_t)(blink + FACTOR), next + FACTOR, 4);
    write_float(blink + TIME, time + step);
}

static int branches_to(uint64_t at, uint64_t target) {
    const unsigned char *site = bb_guest(BB_BN(at));
    int32_t rel;
    memcpy(&rel, site + 1, 4);
    return (site[0] == 0xe8 || site[0] == 0xe9) && BB_BN(at) + 5 + (int64_t)rel == BB_BN(target);
}

/* The first site that is not as expected (its Binary Ninja address), or 0. */
static uint64_t unexpected(void) {
    for (size_t i = 0; i < sizeof(CODE) / sizeof(*CODE); ++i)
        if (!bb_code_is(bb_guest(BB_BN(CODE[i].at)), CODE[i].code)) return CODE[i].at;
    for (size_t i = 0; i < sizeof(LIGHTS) / sizeof(*LIGHTS); ++i) {
        if (read64(guest(LIGHTS[i].slot)) != guest(LIGHTS[i].update)) return LIGHTS[i].slot;
        if (!branches_to(LIGHTS[i].call, BLINK_UPDATE)) return LIGHTS[i].call;
    }
    return 0;
}

int bb_light_blink_install(void) {
    const char *env = getenv("BB_BLINK_HOLD");
    if (env && !strcmp(env, "0")) {
        puts("Light blink hold: off (BB_BLINK_HOLD=0)");
        return 0;
    }
    const BbGateState gate = bb_effect_step_gate_state();
    if (gate != BB_GATE_ON) {
        puts(gate == BB_GATE_AT_THIRTY ? "Light blink hold: not needed, the effects step 1/30 s a frame (30 FPS)"
                                       : "Light blink hold: off (the effect step gate is off)");
        return 0;
    }
    const uint64_t site = unexpected();
    if (site) {
        printf("Light blink hold: off (unexpected code at %#llx)\n", (unsigned long long)site);
        return 0;
    }
    int hooks = 0;
    for (size_t i = 0; i < sizeof(LIGHTS) / sizeof(*LIGHTS); ++i)
        hooks += !bb_hook_call(BB_BN(LIGHTS[i].call), BB_BN(BLINK_UPDATE), (void *)on_blink);
    if (hooks != 3) {
        printf("Light blink hold: off (%s)\n", bb_hooks_error());
        return hooks;
    }
    puts("Light blink hold: on; above 30 FPS the GX lights begin their blink cycles on the effects' whole "
         "steps (BB_BLINK_HOLD=0 turns it off)");
    return hooks;
}
