/* SPDX-License-Identifier: GPL-2.0-or-later
 * The FPS presets' fixed per-frame values follow the frame's time. After droogie's bbhost
 * (engine/frame_rate.cpp's redirected loads and frame-time sites, https://github.com/droogie/bbhost,
 * GPL-3.0-or-later).
 *
 * Every FPS++ list's cave (0x2418e3d) gives the game's task step the measured frame time clamped
 * to [target, 1/30], but what the lists and scripts/patches.py set for the preset's rate stays a
 * fixed amount a frame: the steps frame_steps makes 1/fps (Havok's physics and AI worlds and the
 * other step-infos built for a call, the durations made from frame counts, the effects' step),
 * the lists' turn step, the replay ghosts' fade and, with camera_fix, the follow camera's two
 * eases. A 90 preset running at 58 FPS stepped its physics 1/90 s a 1/58 s frame. Here each reads a
 * cell the main thread writes once a frame, just after the frame-time manager's update, from that
 * same clamped step: value x step / target, a weight 1 - (1 - w)^(step / target). A held rate
 * reads the preset's own values. A store into a stack local runs through a stub that stores the
 * cell (bb_hook_store); a .rodata constant's loads get the cell's displacement.
 *
 * A site is taken with its code as src/frame_time_sites.inc has it (tools/frame_time_sites.py)
 * and its value the preset's: value / target within the table's range, a weight camera_fix's.
 * Others stay as the list has them (frame_step_fix=0's 1/60 at 90, the uncapped list's 1/60 steps,
 * the durations the rate base leaves at 1/30). The cells are aligned 4-byte stores: a reader on
 * another thread sees the last frame's value or this one's.
 *
 * Addresses are Binary Ninja's (BB_BN). */
#include "frame_time.h"
#include "engine_hooks.h"
#include "frame_step.h"

#include <stdint.h>
#include <stdio.h>
#include <string.h>

enum { BB_FT_STORE, BB_FT_LOAD, BB_FT_WEIGHT };
typedef struct {
    uint32_t at;        /* the instruction */
    uint8_t n, kind;    /* its length, BB_FT_* */
    uint32_t constant;  /* what a load reads; 0 for a store */
    float lo, hi;       /* the value over the target it must have; a weight: the game's at 30 */
    BbCode code;        /* a store: its bytes before the immediate; a load: the instruction */
} Site;
static const Site SITES[] = {
#include "frame_time_sites.inc"
};
enum { SITE_COUNT = sizeof(SITES) / sizeof(*SITES), MAX_CELLS = 16 };

typedef struct {
    volatile float *at;
    float value;  /* at the target */
    int weight;
} Cell;
static Cell g_cells[MAX_CELLS];
static int g_cell_count;
static float g_target;

static void tick(void) {
    const float step = bb_frame_step();
    if (!(step > 0.0f)) return;
    for (int i = 0; i < g_cell_count; ++i) {
        const Cell *c = &g_cells[i];
        *c->at = c->weight ? bb_ft_weight(c->value, step, g_target) : bb_ft_step(c->value, step, g_target);
    }
}

static float *cell_for(float value, int weight) {
    for (int i = 0; i < g_cell_count; ++i)
        if (g_cells[i].value == value && g_cells[i].weight == weight) return (float *)g_cells[i].at;
    float *at = g_cell_count < MAX_CELLS ? bb_hook_data(sizeof(float)) : NULL;
    if (!at) return NULL;
    *at = value;
    g_cells[g_cell_count++] = (Cell){at, value, weight};
    return at;
}

/* The site's value in this image when its code is the table's; 0 otherwise. */
static float site_value(const Site *s) {
    const unsigned char *at = bb_guest(BB_BN(s->at));
    float value = 0;
    if (!bb_code_is(at, s->code)) return 0.0f;
    memcpy(&value, s->kind == BB_FT_STORE ? at + s->n - 4 : (const unsigned char *)bb_guest(BB_BN(s->constant)), 4);
    return value;
}

static int follows(const Site *s, float value) {
    if (s->kind == BB_FT_WEIGHT) return value > 0.0f && fabsf(value - bb_ft_weight_at(s->lo, g_target)) <= 1e-6f;
    const float k = value / g_target;
    return value != 0.0f && k >= s->lo && k <= s->hi;
}

static int redirect(const Site *s, const float *cell) {
    if (s->kind == BB_FT_STORE) return !bb_hook_store(BB_BN(s->at), s->n, s->code, cell);
    int32_t was, rel;
    memcpy(&was, (const unsigned char *)bb_guest(BB_BN(s->at)) + 4, 4);
    return bb_rel32_to(BB_BN(s->at) + 8, cell, &rel) && !bb_patch(BB_BN(s->at) + 4, &was, &rel, 4);
}

int bb_frame_time_install(void) {
    g_target = bb_preset_target();
    if (!g_target) return 0;  /* the game's 30 */
    if (!bb_frame_time_presets()) {
        puts("Frame-time presets: off (BB_FRAME_TIME_PRESETS=0): the preset's steps stay those of its rate");
        return 0;
    }
    if (!bb_main_frame_available()) {
        puts("Frame-time presets: off - no frame tick; the preset's steps stay those of its rate");
        return 0;
    }
    int followed = 0, left = 0;
    for (int i = 0; i < SITE_COUNT; ++i) {
        const Site *s = &SITES[i];
        const float value = site_value(s);
        float *cell = follows(s, value) ? cell_for(value, s->kind == BB_FT_WEIGHT) : NULL;
        if (cell && redirect(s, cell)) ++followed;
        else ++left;
    }
    if (!followed) {
        printf("Frame-time presets: off - none of the %d sites holds the preset's values\n", SITE_COUNT);
        return 0;
    }
    bb_on_main_frame(tick);
    char rate[16] = "uncapped";
    if (!bb_uncapped()) snprintf(rate, sizeof(rate), "%d FPS", (int)(1.0f / g_target + 0.5f));
    printf("Frame-time presets: %d steps follow the frame time at %s (%d left as the list has them)\n",
           followed, rate, left);
    return followed;
}
