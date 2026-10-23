/* SPDX-License-Identifier: GPL-2.0-or-later
 * Effects above 30 FPS in whole 1/30 s steps, the frames between holding what the effects count
 * per update (effect_step_gate.c), and the smooth steps that move the converted effects by each
 * frame's own time (effect_smooth_steps.c). On by default; BB_EFFECT_SMOOTH=0 keeps the whole
 * steps for every effect, BB_EFFECT_STEP_GATE=0 turns both off. */
#ifndef BB_EFFECT_STEP_GATE_H
#define BB_EFFECT_STEP_GATE_H

/* Checks every site and hooks them, unless the effects already step 1/30 s a frame (30 FPS);
 * returns hooks added (0 when refused or not needed). */
int bb_effect_step_gate_install(void);

/* The game's own effect step at 30 FPS. */
#define BB_EFFECT_WHOLE_STEP (1.0f / 30.0f)

/* What the schedule makes of a frame the game gives `step`. */
typedef struct {
    float step;  /* the manager's: 1/30 s, 0 between whole steps, or the game's own */
    float frame; /* the frame's own time when split, else 0 */
    float from;  /* the carry before the frame, at least +0: how far past its last whole step it begins */
    float into;  /* the carry after it, at least +0 */
    int between; /* no whole step this frame */
    int split;   /* the schedule took the frame (a step above 0 and under 1/30 s) */
} BbEffectFrame;

/* A step shorter than 1/30 s goes into `carry` and the manager takes it back in whole 1/30 s, 0 on
 * the frames between. A step of 1/30 s or more, 0 or NaN is the game's own. */
static inline BbEffectFrame bb_effect_frame(double *carry, float step) {
    BbEffectFrame f = {step, 0.0f, 0.0f, 0.0f, 0, 0};
    if (!(step > 0.0f) || step >= BB_EFFECT_WHOLE_STEP) return f;
    f.split = 1;
    f.frame = step;
    f.from = *carry > 0.0 ? (float)*carry : 0.0f;
    *carry += step;
    /* The 1e-6 keeps a carry a rounding short of a step from waiting a frame. */
    if (*carry * 30.0 + 1e-6 < 1.0) {
        f.between = 1;
        f.step = 0.0f;
    } else {
        *carry -= 1.0 / 30.0;
        f.step = BB_EFFECT_WHOLE_STEP;
    }
    /* What the 1e-6 took early leaves the carry up to that much below 0: none past the step. */
    f.into = *carry > 0.0 ? (float)*carry : 0.0f;
    return f;
}

static inline float bb_effect_step(double *carry, float step, int *between) {
    const BbEffectFrame f = bb_effect_frame(carry, step);
    *between = f.between;
    return f.step;
}

#endif
