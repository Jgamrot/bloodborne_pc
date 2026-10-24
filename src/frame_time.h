/* SPDX-License-Identifier: GPL-2.0-or-later
 * The FPS presets' fixed per-frame values follow the frame's time (frame_time.c): a game below its
 * target steps as the lower rate would. Off with BB_FRAME_TIME_PRESETS=0. */
#ifndef BB_FRAME_TIME_H
#define BB_FRAME_TIME_H

#include <math.h>

/* What a value tuned for frames of `target` s is for a frame of `step` s: a step or an amount a
 * frame scales with it, a weight a frame w becomes 1 - (1 - w)^(step / target). Exact when held. */
static inline float bb_ft_step(float value, float step, float target) {
    return step == target ? value : (float)((double)value * step / target);
}
static inline float bb_ft_weight(float value, float step, float target) {
    if (step == target || !(value > 0.0f) || !(value < 1.0f)) return value;
    return (float)(1.0 - pow(1.0 - (double)value, (double)step / target));
}

/* A weight the game has for a 30 fps frame (w30), as patches.py's camera_fix writes it for `target`. */
static inline float bb_ft_weight_at(double w30, float target) { return (float)(1.0 - pow(1.0 - w30, 30.0 * target)); }

/* Points the preset's fixed steps at cells set each frame; returns hooks added. */
int bb_frame_time_install(void);

#endif
