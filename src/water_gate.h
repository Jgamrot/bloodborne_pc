/* SPDX-License-Identifier: GPL-2.0-or-later
 * The wakes characters leave in water (GX's water interaction) in 30 wave steps a game second
 * above 30 FPS (water_gate.c). On with the effect step gate; BB_WATER_GATE=0 turns it off. */
#ifndef BB_WATER_GATE_H
#define BB_WATER_GATE_H

/* Checks every site and hooks the water interaction's update and render task, when the effect
 * step gate is on; returns hooks added (0 when refused or not needed). */
int bb_water_gate_install(void);

#endif
