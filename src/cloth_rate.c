/* SPDX-License-Identifier: GPL-2.0-or-later
 * Capes and coats by each frame's time. After Kyo's FPS++ cloth package and droogie's bbhost
 * (engine/frame_rate.cpp's uncapped mode, https://github.com/droogie/bbhost, GPL-3.0-or-later).
 *
 * scripts/patches.py gives the lists the cloth part of "90 FPS++ (rate base)": one solver
 * substep a frame (0xb6e67a) and six hcl constraint caves that multiply the stiffness by the
 * scalars at 0x4d3bd00, (60/fps)^2 at a fixed rate, 1 uncapped. Here the caves load a cell
 * instead, which the main thread sets once a frame (just after the frame-time manager's update)
 * to (60 x frame time)^2 over the game's step smoothed across about 10 frames, at most 1 (below
 * 60 the cloth keeps its 60 tuning): uncapped, and above 60 at a fixed preset unless
 * BB_FRAME_TIME_PRESETS=0 (a held rate gives patches.py's value). The damping exponent and the
 * integrator's dt*dt stay the game's, as at the fixed rates (patches.py CLOTH_LEFT_OUT).
 *
 * The CSClothThread workers only read the cell: it is written with one aligned 16-byte store of
 * four equal floats, so a solve reads the last frame's stiffness or this one's, which differ by
 * at most a tenth of the change in frame time. Without the tick nothing is redirected and the
 * caves keep patches.py's scalars.
 *
 * Addresses are Binary Ninja's (BB_BN). */
#include "cloth_rate.h"
#include "engine_hooks.h"
#include "frame_step.h"

#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <xmmintrin.h>

enum { STIFFNESS = 0x4d3bd00, SUBSTEPS = 0xb6e67a };
/* The caves' loads of the scalars (Kyo's, over dead hkMonitorStream timer blocks). */
static const uint64_t CAVE_LOADS[] = {0xb20e14, 0xb2b324, 0xb30b04, 0xb3873f, 0xb41f74, 0xb42114};
enum { CAVES = sizeof(CAVE_LOADS) / sizeof(*CAVE_LOADS) };

static float *g_stiffness;
static float g_smoothed = 1.0f / 60;
static float g_target, g_held;  /* a fixed preset's target and patches.py's stiffness for it */

static void tick(void) {
    const float step = bb_frame_step();
    if (!(step > 0.0f)) return;
    g_smoothed = bb_cloth_smoothed(g_smoothed, step);
    const float k = g_target && g_smoothed == g_target ? g_held : bb_cloth_stiffness(g_smoothed);
    _mm_store_ps(g_stiffness, _mm_set1_ps(k));
}

/* vmulps xmm0, xmm0, [rip+rel]: a cave's load. */
static void cave_load(int32_t rel, unsigned char out[8]) {
    const unsigned char op[4] = {0xc5, 0xf8, 0x59, 0x05};
    memcpy(out, op, 4);
    memcpy(out + 4, &rel, 4);
}

int bb_cloth_rate_install(void) {
    const int uncapped = bb_uncapped();
    const float target = uncapped ? 0.0f : bb_preset_target();
    if (!uncapped && !(target > 0.0f && target < 1.0f / 60)) return 0;  /* 30 and 60: the 60 tuning */
    if (!uncapped && !bb_frame_time_presets()) {
        puts("Cloth rate: the preset's stiffness, (60/fps)^2 (BB_FRAME_TIME_PRESETS=0)");
        return 0;
    }
    const unsigned char substeps[5] = {0xbb, 0x01, 0x00, 0x00, 0x00};  /* mov ebx, 1 */
    float slot[4];
    memcpy(slot, bb_guest(BB_BN(STIFFNESS)), sizeof(slot));
    const float want = uncapped ? 1.0f : bb_cloth_stiffness(target);
    unsigned char was[CAVES][8];
    int ok = !memcmp(bb_guest(BB_BN(SUBSTEPS)), substeps, 5) && fabsf(slot[0] - want) <= 1e-6f &&
             slot[1] == slot[0] && slot[2] == slot[0] && slot[3] == slot[0];
    for (int i = 0; ok && i < CAVES; ++i) {
        const int32_t rel = (int32_t)(BB_BN(STIFFNESS) - BB_BN(CAVE_LOADS[i] + 8));
        cave_load(rel, was[i]);
        ok = !memcmp(bb_guest(BB_BN(CAVE_LOADS[i])), was[i], 8);
    }
    if (!ok) {
        puts("Cloth rate: off (cloth_fix=0, cloth_uncapped=0, or the cloth package is not the one patches.py writes)");
        return 0;
    }
    if (!bb_main_frame_available()) {
        puts("Cloth rate: off - no frame tick (the frame-time manager's call is not the game's); the preset's stiffness");
        return 0;
    }
    if (!uncapped) {
        g_target = target;
        g_held = slot[0];
        g_smoothed = target;
    }
    float *cell = bb_hook_data(16);
    unsigned char to[CAVES][8];
    for (int i = 0; cell && i < CAVES; ++i) {
        int32_t rel;
        if (!bb_rel32_to(BB_BN(CAVE_LOADS[i] + 8), cell, &rel)) cell = NULL;
        else cave_load(rel, to[i]);
    }
    if (!cell) {
        puts("Cloth rate: off - no data cell within reach of the caves");
        return 0;
    }
    _mm_store_ps(cell, _mm_set1_ps(uncapped ? bb_cloth_stiffness(g_smoothed) : g_held));
    for (int i = 0; i < CAVES; ++i) {
        if (bb_patch(BB_BN(CAVE_LOADS[i]), was[i], to[i], 8)) {
            while (i--) bb_patch(BB_BN(CAVE_LOADS[i]), to[i], was[i], 8);
            printf("Cloth rate: off (%s)\n", bb_hooks_error());
            return 0;
        }
    }
    g_stiffness = cell;
    bb_on_main_frame(tick);
    printf("Cloth rate: %s, the cloth's stiffness follows the frame time ((60 x frame time)^2, at most 1)\n",
           uncapped ? "uncapped" : "at the preset");
    return 1;
}
