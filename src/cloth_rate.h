/* SPDX-License-Identifier: GPL-2.0-or-later
 * Capes and coats (cloth_rate.c): the cloth's stiffness follows the frame time, uncapped (with
 * cloth_uncapped) and above 60 at a fixed preset (with cloth_fix). scripts/patches.py writes the
 * cloth package it needs. */
#ifndef BB_CLOTH_RATE_H
#define BB_CLOTH_RATE_H

/* The frame time the stiffness follows: the game's step smoothed over about 10 frames. */
static inline float bb_cloth_smoothed(float smoothed, float step) { return smoothed + (step - smoothed) * 0.1f; }

/* The stiffness scalar for one solver substep a frame of `smoothed` s: (60 x frame time)^2, as
 * patches.py's (60/fps)^2 at a fixed rate, at most 1 (below 60 the cloth keeps its 60 tuning). */
static inline float bb_cloth_stiffness(float smoothed) {
    const float s = 60.0f * smoothed;
    return s < 1.0f ? s * s : 1.0f;
}

/* Points the cloth's six constraint caves at a stiffness set each frame; returns hooks added. */
int bb_cloth_rate_install(void);

#endif
