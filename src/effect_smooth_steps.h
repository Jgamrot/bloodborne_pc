/* SPDX-License-Identifier: GPL-2.0-or-later
 * The smooth steps' side of the effect step gate (effect_smooth_steps.c), called from the gate's
 * hooks (effect_step_gate.c). */
#ifndef BB_EFFECT_SMOOTH_STEPS_H
#define BB_EFFECT_SMOOTH_STEPS_H

#include "effect_step_gate.h"

#include <stdint.h>

/* A frame between whole steps that the gate holds (effect_step_gate.c). */
int bb_effect_held(void);

/* Whether the smooth steps go in: BB_EFFECT_SMOOTH is not 0 and every site they read is as
 * expected (one log line when not). Called before the gate writes anything. */
int bb_smooth_wanted(void);
/* Hooks the smooth steps' own sites; hooks added, or -1 when one is refused. */
int bb_smooth_install(void);

/* Around each update of SprjSfx's effect manager that is not its still frame: the frame the
 * schedule made of it. */
void bb_smooth_begin(uint64_t manager, const BbEffectFrame *frame);
void bb_smooth_end(void);

/* The gate's hooks ask these first; 1 when the smooth steps took the call. */
int bb_smooth_node(uint64_t node, float *step, uint64_t definition, uint64_t context, uint8_t *keep);
int bb_smooth_light(uint64_t module, uint64_t params, uint64_t context);
int bb_smooth_follow(uint64_t motion, uint64_t node, const float *step, uint64_t local);
int bb_smooth_record(uint64_t record, uint64_t item);

#endif
