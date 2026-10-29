/* SPDX-License-Identifier: GPL-2.0-or-later
 * Ending trace (ending_trace.c): how far an ending got, in last_run.log (GitHub issue #236).
 * On unless BB_ENDING_TRACE=0. */
#ifndef BB_ENDING_TRACE_H
#define BB_ENDING_TRACE_H

/* Registers the main-thread tick; returns 1 when it will run. */
int bb_ending_trace_install(void);

#endif
