/* SPDX-License-Identifier: GPL-2.0-or-later
 * The grass and tree wind at 30's pace under Uncap FPS++. After droogie's bbhost
 * (engine/wind_pace.h, https://github.com/droogie/bbhost, GPL-3.0-or-later).
 *
 * The wind query (sub_2713870) steps the gusts' and pushes' times and lives by its load at
 * 0x2713d8d, the game's 1/60 a frame: 1/60 s of wind each 1/30 s at 30, fps/30 times that
 * uncapped. scripts/patches.py points it at 1/(2 fps) for the fixed rates and weighs the force by
 * the game's 1/60 (0x27149ea) at every rate; uncapped the load reads a cell here instead, set at
 * the start of each frame (the frame-time manager's update, main thread) to half the game's last
 * step. One aligned 4-byte store: the wind query, on whatever thread draws, reads the last
 * frame's step or this one's. Off with wind_fix=0 (patches.py then leaves the force load alone).
 *
 * Addresses are Binary Ninja's (BB_BN). */
#include "wind_pace.h"
#include "engine_hooks.h"
#include "frame_step.h"

#include <stdint.h>
#include <stdio.h>
#include <string.h>

enum {
    STEP_LOAD = 0x2713d8d,   /* vmovss xmm4, [rip+disp32] (the game's 1/60) */
    FORCE_LOAD = 0x27149ea,  /* patches.py's vmovss xmm14, [rip+disp32] (the game's 1/60) */
    GAME_STEP = 0x4d29e70,
};
static const BbCode step_load = {8, 0xaadb3e83d86419c5ull};

static volatile float *g_step;

static void tick(void) {
    const float step = bb_uncapped_frame_step();
    if (step > 0.0f) *g_step = bb_wind_step(step);
}

/* patches.py's force load: vmovss xmm14, [rip -> GAME_STEP]. */
static int force_weighed(void) {
    const unsigned char op[4] = {0xc5, 0x7a, 0x10, 0x35};
    const int32_t rel = (int32_t)(BB_BN(GAME_STEP) - BB_BN(FORCE_LOAD + 8));
    const unsigned char *at = bb_guest(BB_BN(FORCE_LOAD));
    return !memcmp(at, op, 4) && !memcmp(at + 4, &rel, 4);
}

int bb_wind_pace_install(void) {
    if (!bb_uncapped()) return 0;  /* the fixed rates: patches.py */
    float game = 0;
    memcpy(&game, bb_guest(BB_BN(GAME_STEP)), 4);
    if (!force_weighed() || game != 1.0f / 60) {
        puts("Wind pace: off (wind_fix=0, or other code at the wind's loads): fps/30 times 30's pace");
        return 0;
    }
    unsigned char *load = bb_guest(BB_BN(STEP_LOAD));
    if (!bb_code_is(load, step_load)) {
        puts("Wind pace: off - unexpected code at the wind's step load");
        return 0;
    }
    if (!bb_main_frame_available()) {
        puts("Wind pace: off - no frame tick (the frame-time manager is hooked elsewhere)");
        return 0;
    }
    float *cell = bb_hook_data(sizeof(float));
    unsigned char now[8];
    int32_t rel;
    if (!cell || !bb_rel32_to(BB_BN(STEP_LOAD + 8), cell, &rel)) {
        printf("Wind pace: off (%s)\n", cell ? "the cell is out of reach" : bb_hooks_error());
        return 0;
    }
    *cell = bb_wind_step(1.0f / 60);
    memcpy(now, load, 8);
    unsigned char to[8];
    memcpy(to, load, 4);
    memcpy(to + 4, &rel, 4);
    if (bb_patch(BB_BN(STEP_LOAD), now, to, 8)) {
        printf("Wind pace: off (%s)\n", bb_hooks_error());
        return 0;
    }
    g_step = cell;
    bb_on_main_frame(tick);
    puts("Wind pace: uncapped, the wind steps half the game's step a frame (30's pace)");
    return 1;
}
