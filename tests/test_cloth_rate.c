/* SPDX-License-Identifier: GPL-2.0-or-later
 * cloth_rate.h and frame_step.h: under Uncap FPS++ the cloth's stiffness settles on patches.py's
 * (60/fps)^2 for a held rate, keeps the 60 tuning (1) below 60, and a one-frame hitch moves the
 * frame time it follows a tenth of the way. */
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include "cloth_rate.h"
#include "frame_step.h"

/* The stiffness after `frames` frames of `seconds` each, from the 60 tuning. */
static float settle(float seconds, int frames, float *smoothed) {
    for (int i = 0; i < frames; ++i) *smoothed = bb_cloth_smoothed(*smoothed, bb_uncapped_step(seconds, 1.0f / 240));
    return bb_cloth_stiffness(*smoothed);
}

int main(void) {
    const float rates[] = {60, 90, 120, 144, 165, 240};
    for (int i = 0; i < 6; ++i) {
        float smoothed = 1.0f / 60;
        const float k = settle(1.0f / rates[i], 300, &smoothed), fixed = (60 / rates[i]) * (60 / rates[i]);
        assert(fabsf(k - fixed) < 1e-4f * fixed);
    }
    float smoothed = 1.0f / 60;
    assert(settle(1.0f / 40, 300, &smoothed) == 1.0f);
    assert(settle(1.0f / 500, 300, &smoothed) <= 0.0626f);  /* 1/240 at least: (60/240)^2 */
    smoothed = 1.0f / 60;
    const float held = settle(1.0f / 144, 300, &smoothed), before = smoothed;
    const float hitch = settle(1.0f / 30, 1, &smoothed);
    assert(fabsf((smoothed - before) - 0.1f * (1.0f / 30 - before)) < 1e-6f);
    assert(hitch > held && hitch < bb_cloth_stiffness(1.0f / 30));
    assert(fabsf(settle(1.0f / 144, 300, &smoothed) - held) < 1e-4f);
    printf("cloth rate: ok (144 FPS: %.4f, a 1/30 s hitch: %.4f)\n", held, hitch);
    return 0;
}
