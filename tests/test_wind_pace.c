/* SPDX-License-Identifier: GPL-2.0-or-later
 * wind_pace.h and frame_step.h: the wind time a game second and a push's 0.75 s fade under
 * Uncap FPS++'s uneven frames match the game's at 30 (1/60 of wind each 1/30 s frame), and the
 * step follows the cave's clamp. After bbhost's tests/wind_pace_test.cpp. */
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include "frame_step.h"
#include "wind_pace.h"

static uint32_t g_rng = 0x2713870u;
static float uniform(float lo, float hi) {
    g_rng = g_rng * 1664525u + 1013904223u;
    return lo + (hi - lo) * (float)((g_rng >> 8) / (double)(1u << 24));
}

/* Wind seconds a game second, and the game seconds a 0.75 s life lasts. */
static void run(int frames, float fixed, double *pace, double *fade) {
    double wind = 0, game = 0, life = 0.75;
    *fade = 0;
    for (int i = 0; i < frames; ++i) {
        const float step = bb_uncapped_step(fixed ? fixed : uniform(1.0f / 400, 1.0f / 25), 1.0f / 240);
        const float w = fixed == 1.0f / 30 ? 1.0f / 60 : bb_wind_step(step);
        wind += w;
        game += step;
        life -= w;
        if (!*fade && life <= 0) *fade = game;
    }
    *pace = wind / game;
}

int main(void) {
    assert(bb_uncapped_step(1.0f / 500, 1.0f / 240) == 1.0f / 240);
    assert(bb_uncapped_step(1.0f / 500, 0.0f) == 1.0f / 240);
    assert(bb_uncapped_step(1.0f / 10, 1.0f / 240) == 1.0f / 30);
    assert(bb_uncapped_step(1.0f / 100, 1.0f / 240) == 1.0f / 100);
    assert(bb_uncapped_step(NAN, 1.0f / 240) == 0.0f && bb_uncapped_step(0.0f, 1.0f / 240) == 0.0f);
    double pace30, fade30, pace, fade;
    run(600, 1.0f / 30, &pace30, &fade30);  /* the game at 30 */
    assert(fabs(pace30 - 0.5) < 1e-6 && fabs(fade30 - 1.5) < 1.0 / 30 + 1e-6);
    const float rates[] = {60, 90, 120, 144, 240};
    for (int i = 0; i < 5; ++i) {
        run((int)(20 * rates[i]), 1.0f / rates[i], &pace, &fade);
        assert(fabs(pace - pace30) < 1e-4 && fabs(fade - fade30) < 1.0 / rates[i] + 1e-4);
    }
    run(5000, 0, &pace, &fade);  /* uneven frames */
    assert(fabs(pace - pace30) < 1e-4 && fabs(fade - fade30) < 1.0 / 25);
    printf("wind pace: ok (%.4f s of wind a game second, a push fades in %.3f s)\n", pace, fade);
    return 0;
}
