/* SPDX-License-Identifier: GPL-2.0-or-later
 * Ending trace (GitHub issue #236: "Submit your life" gave the Yharnam Sunrise trophy, but no
 * cutscene played and Gehrman went on as before). Logs, in last_run.log, how far an ending got:
 *
 * - every cutscene (remo) the game starts and how many frames it ran, anywhere;
 * - in the Hunter's Dream, the event flags the three endings' events step through
 *   (m21_00_00_00.emevd 12100180, 12100000, 12100002): Gehrman's answer (72100130 submit,
 *   72100131 refuse), 9180 (on around their cutscenes), 6600/6601/6602 (Yharnam Sunrise,
 *   Honoring Wishes, Childhood's Beginning) and 6603/6604 (on in all three, after the trophy);
 * - the playthrough count (GameDataMan +0x68, which the Yharnam Sunrise event raises before its
 *   cutscene).
 *
 * Read only: the flags through the game's own query, everything else with bb_read. Only changes
 * are logged, so a session without an ending adds a few cutscene lines at most. */
#include "ending_trace.h"
#include "engine_hooks.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum {
    GAME_DATA_MAN = 0x593b130,  /* GameDataMan*; +0x68 the playthrough, 0 on the first */
    WORLD_CHR_MAN = 0x593e878,  /* WorldChrMan*; the main player ChrIns at +0x60 */
    EVENT_FLAG_MAN = 0x593b100, /* SprjEventFlagMan* */
    IS_EVENT_FLAG = 0x17cfc00,  /* (man, id, int* exists) -> on */
    /* SprjRemo*; its manager at +8: bit 0 of +0x168 while a cutscene runs, +0xf8 the cutscenes
     * queued (bbhost src/engine/loading.cpp). */
    SPRJ_REMO = 0x5940058,
};
enum { DREAM_AREA = 21 };
static const BbCode is_flag_prologue = {16, 0x7a984991b845c048ull};

static const struct {
    uint32_t id;
    const char *what;
} FLAGS[] = {
    {72100130, "Gehrman: Submit your life"}, {72100131, "Gehrman: refused"},
    {9180, "the ending's cutscene flag"},    {6600, "Yharnam Sunrise"},
    {6601, "Honoring Wishes"},               {6602, "Childhood's Beginning"},
    {6603, "an ending reached"},             {6604, "an ending's trophy given"},
};
enum { FLAG_COUNT = sizeof(FLAGS) / sizeof(FLAGS[0]) };

typedef int64_t (BB_GUEST_ABI *GuestFn)(uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t);

static uint64_t slot_value(uint64_t bn) {
    uint64_t v = 0;
    return bb_read((uint64_t)(uintptr_t)bb_guest(BB_BN(bn)), &v, 8) ? v : 0;
}

static int flag(uint32_t id) {
    const uint64_t man = slot_value(EVENT_FLAG_MAN);
    int32_t exists = 0;
    return man && (((GuestFn)bb_guest(BB_BN(IS_EVENT_FLAG)))(man, id, (uint64_t)(uintptr_t)&exists, 0, 0, 0) & 0xff) != 0;
}

/* The player's map block, or 0 when no world is loaded. */
static uint32_t player_block(void) {
    const uint64_t man = slot_value(WORLD_CHR_MAN);
    uint64_t chr = 0;
    uint32_t block = 0;
    if (!man || !bb_read(man + 0x60, &chr, 8) || !chr || !bb_read(chr + 0x3f8, &block, 4) || block == 0xffffffffu)
        return 0;
    return block;
}

static int playthrough(void) {
    const uint64_t man = slot_value(GAME_DATA_MAN);
    int32_t v = -1;
    return man && bb_read(man + 0x68, &v, 4) ? v : -1;
}

/* 1 while a cutscene runs or is queued, 0 when none, -1 when there is no cutscene manager. */
static int cutscene(uint64_t *queued) {
    const uint64_t remo = slot_value(SPRJ_REMO);
    uint64_t man = 0;
    uint32_t state = 0;
    *queued = 0;
    if (!remo || !bb_read(remo + 8, &man, 8) || !man || !bb_read(man + 0x168, &state, 4) ||
        !bb_read(man + 0xf8, queued, 8))
        return -1;
    return (state & 1) || *queued ? 1 : 0;
}

static int g_world, g_in_dream, g_cycle = -1, g_cut = -1;
static unsigned char g_flags[FLAG_COUNT];
static uint64_t g_frame, g_cut_since;

static void dream_flags(int announce) {
    char on[256];
    size_t used = 0;
    on[0] = 0;
    for (int i = 0; i < FLAG_COUNT; ++i) {
        const unsigned char now = (unsigned char)flag(FLAGS[i].id);
        if (announce) {
            if (now && used < sizeof(on))
                used += (size_t)snprintf(on + used, sizeof(on) - used, " %u", FLAGS[i].id);
        } else if (now != g_flags[i]) {
            printf("Ending trace: frame %llu: flag %u (%s) %s\n", (unsigned long long)g_frame, FLAGS[i].id,
                   FLAGS[i].what, now ? "on" : "off");
        }
        g_flags[i] = now;
    }
    if (announce) printf("Ending trace: in the Hunter's Dream, playthrough %d, ending flags on:%s\n", playthrough(),
                         on[0] ? on : " none");
}

static void tick(void) {
    ++g_frame;
    uint64_t queued = 0;
    const int cut = cutscene(&queued);
    if (cut != g_cut) {
        if (cut == 1) {
            printf("Ending trace: frame %llu: cutscene starts (%llu queued)\n", (unsigned long long)g_frame,
                   (unsigned long long)queued);
            g_cut_since = g_frame;
        } else if (g_cut == 1) {
            printf("Ending trace: frame %llu: cutscene over after %llu frames\n", (unsigned long long)g_frame,
                   (unsigned long long)(g_frame - g_cut_since));
        }
        g_cut = cut;
    }
    const uint32_t block = player_block();
    if (!block) {  /* loading: the next world is read afresh */
        g_world = g_in_dream = 0;
        return;
    }
    if (!g_world) {  /* a frame for the world to settle, as rebirth.c */
        g_world = 1;
        return;
    }
    const int cycle = playthrough();
    if (g_cycle >= 0 && cycle != g_cycle)
        printf("Ending trace: frame %llu: playthrough %d -> %d\n", (unsigned long long)g_frame, g_cycle, cycle);
    g_cycle = cycle;
    const int dream = (block >> 24) == DREAM_AREA;
    if (dream) dream_flags(!g_in_dream);
    g_in_dream = dream;
}

int bb_ending_trace_install(void) {
    const char *env = getenv("BB_ENDING_TRACE");
    if (env && !strcmp(env, "0")) return 0;
    if (!bb_code_is(bb_guest(BB_BN(IS_EVENT_FLAG)), is_flag_prologue)) {
        puts("Ending trace: off - the event flag query is not the 1.09 code");
        return 0;
    }
    if (!bb_main_frame_available()) {
        puts("Ending trace: off - no main-thread tick");
        return 0;
    }
    bb_on_main_frame(tick);
    return 1;
}
