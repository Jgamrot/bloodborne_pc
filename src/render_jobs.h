/* SPDX-License-Identifier: GPL-2.0-or-later
 * Render jobs above 30 FPS (render_jobs.c): failed jobs give their pool slot back, and the render
 * resource cache gets 512 MiB of the port's own memory (#149, Laurence's cinematic). On with the
 * engine hooks; BB_JOB_SLOT_FIX=0 and BB_RENDER_RESOURCE_CACHE_MB=160 turn each part off. */
#ifndef BB_RENDER_JOBS_H
#define BB_RENDER_JOBS_H

/* Hooks the job runner's exits and the cache's allocation; returns hooks added. */
int bb_render_jobs_install(void);

#endif
