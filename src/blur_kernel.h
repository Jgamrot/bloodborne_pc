/* SPDX-License-Identifier: GPL-2.0-or-later
 * The game's blur-kernel sample count kept at its minimum of 3 (blur_kernel.c), so its own
 * assertion does not stop the game (0xa0020007). On with the engine hooks, BB_KERNEL_CLAMP=0 off. */
#ifndef BB_BLUR_KERNEL_H
#define BB_BLUR_KERNEL_H

/* Hooks the sample parameters' entry; returns hooks added. */
int bb_blur_kernel_install(void);

#endif
