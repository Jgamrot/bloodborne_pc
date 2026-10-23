/* SPDX-License-Identifier: GPL-2.0-or-later
 * Effects above 30 FPS in whole 1/30 s steps, the frames between holding what the effects count
 * per update (effect_step_gate.c). On by default; BB_EFFECT_STEP_GATE=0 turns it off. */
#ifndef BB_EFFECT_STEP_GATE_H
#define BB_EFFECT_STEP_GATE_H

/* Checks every site and hooks them, unless the effects already step 1/30 s a frame (30 FPS);
 * returns hooks added (0 when refused or not needed). */
int bb_effect_step_gate_install(void);

/* The game's own effect step at 30 FPS. */
#define BB_EFFECT_WHOLE_STEP (1.0f / 30.0f)

/* The step the effect manager takes for a frame the game gives `step`: a step shorter than
 * 1/30 s goes into `carry` and the manager takes it back in whole 1/30 s, 0 on the frames
 * between (`*between` set). A step of 1/30 s or more, 0 or NaN is the game's own. */
static inline float bb_effect_step(double *carry, float step, int *between) {
    *between = 0;
    if (!(step > 0.0f) || step >= BB_EFFECT_WHOLE_STEP) return step;
    *carry += step;
    /* The 1e-6 keeps a carry a rounding short of a step from waiting a frame. */
    if (*carry * 30.0 + 1e-6 < 1.0) {
        *between = 1;
        return 0.0f;
    }
    *carry -= 1.0 / 30.0;
    return BB_EFFECT_WHOLE_STEP;
}

#endif
