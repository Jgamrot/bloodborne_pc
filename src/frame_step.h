/* SPDX-License-Identifier: GPL-2.0-or-later
 * The game's step a frame under Uncap FPS++, for the features that follow it each frame
 * (bb_on_main_frame). Addresses are Binary Ninja's (BB_BN). */
#ifndef BB_FRAME_STEP_H
#define BB_FRAME_STEP_H

#include <stdint.h>
#include <string.h>

#include "engine_hooks.h"

enum {
    BB_FLIPPER = 0x59404f8,          /* the SprjFlipper singleton (frame-time manager) */
    BB_FLIPPER_TARGET = 0x18,        /* its target frame time, s */
    BB_FLIPPER_MEASURED = 0x264,     /* its measured frame time, s */
    BB_UNCAPPED_TARGET = 0x2434845,  /* Uncap FPS++: mov dword [r12+0x18], 1/240 */
};

/* The step Uncap FPS++'s cave (0x2418e3d) gives the game: the measured frame time clamped to
 * [target, 1/30], at least 1/240; 0 when there is none. */
static inline float bb_uncapped_step(float measured, float target) {
    const float floor = target > 1.0f / 240 ? target : 1.0f / 240;
    if (!(measured > 0.0f)) return 0.0f;  /* also NaN */
    return measured < floor ? floor : measured < 1.0f / 30 ? measured : 1.0f / 30;
}

/* Whether the image runs Uncap FPS++ (its 1/240 target). */
static inline int bb_uncapped(void) {
    float target = 0;
    memcpy(&target, bb_guest(BB_BN(BB_UNCAPPED_TARGET)), 4);
    return target == 1.0f / 240;
}

/* The last frame's step, from the start of the frame-time manager's update; 0 before it exists. */
static inline float bb_uncapped_frame_step(void) {
    uint64_t flipper = 0;
    float target = 0, measured = 0;
    if (!bb_read((uint64_t)(uintptr_t)bb_guest(BB_BN(BB_FLIPPER)), &flipper, 8) || !flipper ||
        !bb_read(flipper + BB_FLIPPER_TARGET, &target, 4) || !bb_read(flipper + BB_FLIPPER_MEASURED, &measured, 4))
        return 0.0f;
    return bb_uncapped_step(measured, target);
}

/* The rel32 that points an instruction ending at image offset `end` at `to`; 0 when out of reach. */
static inline int bb_rel32_to(uint64_t end, const void *to, int32_t *rel) {
    const int64_t d = (int64_t)((uintptr_t)to - (uintptr_t)bb_guest(end));
    if (d < INT32_MIN || d > INT32_MAX) return 0;
    *rel = (int32_t)d;
    return 1;
}

#endif
