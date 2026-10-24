/* SPDX-License-Identifier: GPL-2.0-or-later
 * The grass and tree wind at 30's pace by each frame's time (wind_pace.c): uncapped, and at the
 * fixed rates over scripts/patches.py's 1/(2 fps). On with wind_fix. */
#ifndef BB_WIND_PACE_H
#define BB_WIND_PACE_H

/* The wind's step for a frame of game step `step`: 1/60 s of wind each 1/30 s, as at 30. */
static inline float bb_wind_step(float step) { return step * 0.5f; }

/* Points the wind's step load at a cell set each frame; returns hooks added. */
int bb_wind_pace_install(void);

#endif
