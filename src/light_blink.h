/* SPDX-License-Identifier: GPL-2.0-or-later
 * The GX lights' blink (the flicker of torches, braziers and candles) at 30's pace above 30 FPS
 * (light_blink.c). On with the effect step gate; BB_BLINK_HOLD=0 turns it off. */
#ifndef BB_LIGHT_BLINK_H
#define BB_LIGHT_BLINK_H

/* Checks every site and hooks the blink's three calls, when the effect step gate is on; returns
 * hooks added (0 when refused or not needed). */
int bb_light_blink_install(void);

#endif
