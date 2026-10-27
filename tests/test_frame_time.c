/* SPDX-License-Identifier: GPL-2.0-or-later
 * frame_time.h with frame_step.h, wind_pace.h and cloth_rate.h: the 90 preset held to 60 FPS by
 * the frame limiter, with uneven and dropped frames, advances its fixed steps, the turn step, the
 * replay ghosts' fade, the camera's eases, the wind and the cloth by as much a second as the 60
 * preset given the same frames; held at 90 every value is the preset's own.
 *
 * With BB_TEST_EBOOT_ELF (game_code.h) the same on the game's code: a fixture with every site of
 * src/frame_time_sites.inc, the wind's and the cloth's loads as patches.py leaves them at 90 and
 * Hunter's Atlas's jump at the frame-time manager's entry; the frames run through the task step's
 * hooked call, every redirected load and every stub store reads the frame's value, and
 * BB_FRAME_TIME_PRESETS=0 changes nothing. */
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>
#include "cloth_rate.h"
#include "engine_hooks.h"
#include "frame_step.h"
#include "frame_time.h"
#include "game_code.h"
#include "wind_pace.h"

static uint32_t g_rng = 0x2418e3du;
static float uniform(float lo, float hi) {
    g_rng = g_rng * 1664525u + 1013904223u;
    return lo + (hi - lo) * (float)((g_rng >> 8) / (double)(1u << 24));
}

/* One preset's values as patches.py writes them for its target (90 FPS++ and 60 FPS++). */
typedef struct {
    float target, step, turn, fade, ease, chase, wind, cloth;
} Preset;
static Preset preset(float fps) {
    const float t = 1.0f / fps;
    Preset p = {t, t, fps == 60 ? 1.0f / 54 : 0.0125f, -3.0f * t, bb_ft_weight_at(0.1, t), bb_ft_weight_at(1.0 / 30, t),
                bb_wind_step(t), bb_cloth_stiffness(t)};
    return p;
}

/* Totals over a run: game seconds, the steps' advance, turn, fade, eased share, wind seconds, a push's
 * fade time (0.75 s of wind), and the cloth's stiffness weighed by each frame's step. */
typedef struct {
    double game, step, turn, fade, eased, chased, wind, push, cloth;
} Run;
static Run run(const Preset *p, const float *measured, int frames, int follow) {
    Run r = {0};
    double life = 0.75, kept = 1.0, chase_kept = 1.0;
    float smoothed = p->target;
    for (int i = 0; i < frames; ++i) {
        const float step = bb_uncapped_step(measured[i], p->target), real = follow ? step : p->target;
        const float wind = follow ? bb_wind_step(step) : p->wind;
        smoothed = bb_cloth_smoothed(smoothed, step);
        const float cloth = p->target >= 1.0f / 60 ? 1.0f : follow ? bb_cloth_stiffness(smoothed) : p->cloth;
        r.game += step;
        r.step += bb_ft_step(p->step, real, p->target);
        r.turn += bb_ft_step(p->turn, real, p->target);
        r.fade += bb_ft_step(p->fade, real, p->target);
        kept *= 1.0 - bb_ft_weight(p->ease, real, p->target);
        chase_kept *= 1.0 - bb_ft_weight(p->chase, real, p->target);
        r.wind += wind;
        life -= wind;
        if (!r.push && life <= 0) r.push = r.game;
        r.cloth += cloth * step;
    }
    r.eased = 1.0 - kept;
    r.chased = 1.0 - chase_kept;
    return r;
}

static int within(double a, double b, double tolerance) { return fabs(a - b) <= tolerance * fmax(1.0, fabs(b)); }

/* The game's code. */
enum { BB_FT_STORE, BB_FT_LOAD, BB_FT_WEIGHT };
typedef struct {
    uint32_t at;
    uint8_t n, kind;
    uint32_t constant;
    float lo, hi;
    BbCode code;
} Site;
static const Site SITES[] = {
#include "frame_time_sites.inc"
};
enum {
    SITE_COUNT = sizeof(SITES) / sizeof(*SITES), MAX_PIECES = 512,
    TURN = 0x1cbdb42, CALL = 0x2418e22, MANAGER = 0x2434770, TARGET = 0x243487e, FLIPPER = 0x59404f8,
    WIND_LOAD = 0x2713d8d, WIND_PACE_LOAD = 0x2715d71, WIND_FORCE = 0x27149ea, WIND_GAME = 0x4d29e70,
    WIND_PACE = 0x4d29e74, CLOTH = 0x4d3bd00, SUBSTEPS = 0xb6e67a,
    PHYSICS = 0x1bf9b71,  /* the Havok physics world's step-info: mov dword [rbp-0x48], step */
};
static const size_t IMAGE = 0x5600000;
static const uint64_t CAVES[] = {0xb20e14, 0xb2b324, 0xb30b04, 0xb3873f, 0xb41f74, 0xb42114};
static unsigned char *g_image, g_flipper[0x300];
static uint64_t g_pieces[MAX_PIECES][2];
static int g_piece_count, g_atlas;
typedef uint32_t (BB_GUEST_ABI *ReadBack)(void);
typedef void (BB_GUEST_ABI *Frame)(void);
static ReadBack g_read[SITE_COUNT];

/* Writes fixture bytes at a Binary Ninja address; 0 when they would cover another piece. */
static int piece(uint64_t at, const void *bytes, size_t n) {
    for (int i = 0; i < g_piece_count; ++i)
        if (g_pieces[i][0] < at + n && at < g_pieces[i][1]) return 0;
    assert(g_piece_count < MAX_PIECES);
    g_pieces[g_piece_count][0] = at;
    g_pieces[g_piece_count++][1] = at + n;
    if (bytes) memcpy(g_image + BB_BN(at), bytes, n);
    return 1;
}
static void game(uint64_t at, size_t n) {
    assert(piece(at, NULL, n));
    bb_test_place_game_code(g_image, BB_BN(at), n);
}
static void put(uint64_t at, float v) { memcpy(g_image + BB_BN(at), &v, 4); }
static void rel(uint64_t field, uint64_t end, uint64_t to) {
    const int32_t r = (int32_t)(BB_BN(to) - BB_BN(end));
    memcpy(g_image + BB_BN(field), &r, 4);
}
/* The cell an 8-byte rip-relative load reads. */
static float loaded(uint64_t at) {
    int32_t r;
    float v;
    memcpy(&r, g_image + BB_BN(at) + 4, 4);
    memcpy(&v, g_image + BB_BN(at) + 8 + r, 4);
    return v;
}
static float bits(uint32_t u) {
    float v;
    memcpy(&v, &u, 4);
    return v;
}

/* Stands in for Atlas's frame bridge (its tick, then the update) over the manager's entry. */
static BB_GUEST_ABI int64_t atlas_bridge(void *flipper) {
    (void)flipper;
    ++g_atlas;
    return 0;
}

/* The 90 preset as patches.py leaves the image (90 FPS++, frame_steps, cloth_writes, wind_pace,
 * camera_fix=1), each store site inside push rbp; mov rbp,rsp ... mov eax,[its local]; pop rbp; ret. */
static void build_fixture(float t) {
    memset(g_image, 0, IMAGE);
    g_piece_count = 0;
    static const unsigned char turn[6] = {0xc7, 0x85, 0x7c, 0xff, 0xff, 0xff};  /* 90 FPS++'s line */
    for (int i = 0; i < SITE_COUNT; ++i) {
        const Site *s = &SITES[i];
        if (s->at == TURN) {
            assert(piece(TURN, turn, sizeof(turn)) && piece(TURN + 6, NULL, 4));
            put(TURN + 6, 0.0125f);
        } else {
            game(s->at, s->n);
        }
        if (s->kind == BB_FT_STORE) {
            if (s->at != TURN) put(s->at + s->n - 4, t);
        } else if (piece(s->constant, NULL, 4)) {
            put(s->constant, s->kind == BB_FT_WEIGHT ? bb_ft_weight_at(s->lo, t) : s->lo < -2 ? -3 * t : s->lo > 2 ? 3 * t : t);
        }
    }
    for (int i = 0; i < SITE_COUNT; ++i) {
        const Site *s = &SITES[i];
        g_read[i] = NULL;
        if (s->kind != BB_FT_STORE) continue;
        static const unsigned char entry[4] = {0x55, 0x48, 0x89, 0xe5};
        unsigned char back[16];
        const size_t m = s->n - 4u;
        memcpy(back, g_image + BB_BN(s->at), m);
        back[0] = 0x8b;  /* mov eax, [the local] for mov dword [the local], imm32 (no REX here) */
        back[m] = 0x5d;
        back[m + 1] = 0xc3;
        if (piece(s->at - 4, entry, 4) && piece(s->at + s->n, back, m + 2))
            g_read[i] = (ReadBack)(void *)(g_image + BB_BN(s->at - 4));
    }
    game(TARGET, 9);
    put(TARGET + 5, t);
    /* sub rsp, 8; the task step's call; add rsp, 8; ret: the call as the game makes it, aligned. */
    static const unsigned char before[8] = {0x48, 0x83, 0xec, 0x08, 0x90, 0x90, 0x90, 0x90}, after[5] = {0x48, 0x83, 0xc4, 0x08, 0xc3};
    game(CALL, 5);
    assert(piece(CALL - 8, before, 8) && piece(CALL + 5, after, 5));
    unsigned char jump[17] = {0xff, 0x25, 0, 0, 0, 0};  /* runtime_atlas_state.c's jump */
    const uint64_t bridge = (uint64_t)(uintptr_t)atlas_bridge;
    memcpy(jump + 6, &bridge, 8);
    memset(jump + 14, 0x90, 3);
    assert(piece(MANAGER, jump, sizeof(jump)));
    const uint64_t flipper = (uint64_t)(uintptr_t)g_flipper;
    assert(piece(FLIPPER, &flipper, 8));
    memcpy(g_flipper + BB_FLIPPER_TARGET, &t, 4);
    /* The wind as patches.py's wind_pace leaves it at a fixed rate. */
    game(WIND_LOAD, 8);
    game(WIND_PACE_LOAD, 8);
    rel(WIND_LOAD + 4, WIND_LOAD + 8, WIND_PACE);
    static const unsigned char force[4] = {0xc5, 0x7a, 0x10, 0x35};
    assert(piece(WIND_FORCE, force, 4) && piece(WIND_FORCE + 4, NULL, 4));
    rel(WIND_FORCE + 4, WIND_FORCE + 8, WIND_GAME);
    assert(piece(WIND_GAME, NULL, 8));
    put(WIND_GAME, 1.0f / 60);
    put(WIND_PACE, bb_wind_step(t));
    /* The cloth package as cloth_writes gives it. */
    static const unsigned char one[5] = {0xbb, 0x01, 0x00, 0x00, 0x00}, cave[4] = {0xc5, 0xf8, 0x59, 0x05};
    assert(piece(SUBSTEPS, one, 5));
    for (size_t i = 0; i < sizeof(CAVES) / sizeof(*CAVES); ++i) {
        assert(piece(CAVES[i], cave, 4) && piece(CAVES[i] + 4, NULL, 4));
        rel(CAVES[i] + 4, CAVES[i] + 8, CLOTH);
    }
    assert(piece(CLOTH, NULL, 16));
    for (int i = 0; i < 4; ++i) put(CLOTH + 4u * i, (float)((60.0 / 90) * (60.0 / 90)));
}

static void check_game(void) {
    const float t = 1.0f / 90;
    g_image = VirtualAlloc(NULL, IMAGE, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
    assert(g_image);
    build_fixture(t);
    assert(bb_hooks_init(g_image, IMAGE) == 0);
    assert(bb_preset_target() == t && !bb_uncapped());
    /* Atlas's jump at the entry does not take the tick away: it hooks the call. */
    assert(bb_main_frame_available());

    /* BB_FRAME_TIME_PRESETS=0: nothing written. */
    unsigned char *copy = malloc(IMAGE);
    assert(copy);
    memcpy(copy, g_image, IMAGE);
    _putenv("BB_FRAME_TIME_PRESETS=0");
    assert(bb_frame_time_install() == 0 && bb_wind_pace_install() == 0 && bb_cloth_rate_install() == 0);
    assert(!memcmp(copy, g_image, IMAGE));
    free(copy);
    _putenv("BB_FRAME_TIME_PRESETS=");

    float base[SITE_COUNT];
    for (int i = 0; i < SITE_COUNT; ++i) {
        const Site *s = &SITES[i];
        memcpy(&base[i], g_image + BB_BN(s->kind == BB_FT_STORE ? s->at + s->n - 4u : s->constant), 4);
    }
    assert(bb_frame_time_install() == SITE_COUNT);
    assert(bb_wind_pace_install() == 1 && bb_cloth_rate_install() == 1);
    assert(bb_main_frame_install() == 1);
    bb_hooks_seal();
    DWORD old;
    assert(VirtualProtect(g_image, IMAGE, PAGE_EXECUTE_READWRITE, &old));
    FlushInstructionCache(GetCurrentProcess(), g_image, IMAGE);
    const Frame frame = (Frame)(void *)(g_image + BB_BN(CALL - 8));

    /* Before the first frame: the preset's values. */
    int stores = 0, physics_site = -1;
    for (int i = 0; i < SITE_COUNT; ++i) {
        if (SITES[i].kind != BB_FT_STORE) assert(loaded(SITES[i].at) == base[i]);
        else if (g_read[i]) assert(bits(g_read[i]()) == base[i]), ++stores;
        if (SITES[i].at == PHYSICS) physics_site = i;
    }
    assert(physics_site >= 0 && g_read[physics_site]);

    /* The limiter at 60, uneven, a dropped frame in 30; then held at 90. */
    enum { FRAMES = 3000 };
    double game_time = 0, physics = 0;
    float smoothed = t;
    for (int f = 0; f < FRAMES + 300; ++f) {
        const float measured = f >= FRAMES ? t : f % 30 == 29 ? 1.0f / 15 : uniform(1.0f / 60, 1.0f / 40);
        memcpy(g_flipper + BB_FLIPPER_MEASURED, &measured, 4);
        frame();
        const float step = bb_uncapped_step(measured, t);
        smoothed = bb_cloth_smoothed(smoothed, step);
        for (int i = 0; i < SITE_COUNT; ++i) {
            const Site *s = &SITES[i];
            const float want = s->kind == BB_FT_WEIGHT ? bb_ft_weight(base[i], step, t) : bb_ft_step(base[i], step, t);
            if (s->kind != BB_FT_STORE) assert(loaded(s->at) == want);
            else if (g_read[i]) assert(bits(g_read[i]()) == want);
        }
        if (f < FRAMES) {
            game_time += step;
            physics += bits(g_read[physics_site]());
        }
        assert(bb_ft_step(t, step, t) == step);  /* the 60 preset's 1/60 x step / (1/60) */
        assert(loaded(WIND_LOAD) == bb_wind_step(step) && loaded(WIND_PACE_LOAD) == bb_wind_step(step));
        const float cloth = loaded(CAVES[0]);
        assert(fabsf(cloth - bb_cloth_stiffness(smoothed)) <= 1e-6f && loaded(CAVES[5]) == cloth);
        if (f == FRAMES + 299) assert(fabsf(cloth - (float)((60.0 / 90) * (60.0 / 90))) <= 1e-6f);
    }
    assert(g_atlas == FRAMES + 300);
    assert(within(physics, game_time, 1e-6));
    printf("frame time: ok with the game's code (%d sites, %d stores run, Atlas's bridge %d times)\n", SITE_COUNT,
           stores, g_atlas);
}

int main(void) {
    /* Held: each value is the preset's own, bit for bit. */
    const Preset p90 = preset(90), p60 = preset(60);
    assert(bb_ft_step(p90.step, p90.target, p90.target) == p90.step);
    assert(bb_ft_weight(p90.ease, p90.target, p90.target) == p90.ease);
    assert(bb_ft_step(p90.step, 1.0f / 60, p90.target) == 1.0f / 60);
    assert(fabsf(bb_ft_weight(p90.ease, 1.0f / 60, p90.target) - p60.ease) < 1e-6f);
    assert(fabsf(bb_ft_weight(p90.chase, 1.0f / 60, p90.target) - p60.chase) < 1e-6f);
    assert(bb_ft_weight(0.0f, 1.0f / 60, p90.target) == 0.0f && bb_ft_weight(1.0f, 1.0f / 60, p90.target) == 1.0f);

    /* The frame limiter at 60 (frames of 1/60 s or longer), uneven, with a dropped frame in 30. */
    enum { FRAMES = 6000 };
    static float measured[FRAMES];
    for (int i = 0; i < FRAMES; ++i) measured[i] = i % 30 == 29 ? 1.0f / 15 : uniform(1.0f / 60, 1.0f / 40);
    const Run a = run(&p90, measured, FRAMES, 1), b = run(&p60, measured, FRAMES, 1);
    assert(a.game == b.game);
    assert(within(a.step / a.game, 1.0, 1e-5) && within(a.step, b.step, 1e-6));  /* a second a second */
    assert(within(a.fade, b.fade, 1e-6) && within(a.fade / a.game, -3.0, 1e-5));
    assert(within(a.eased, b.eased, 1e-6) && within(a.chased, b.chased, 1e-6));
    assert(within(a.wind / a.game, 0.5, 1e-5) && within(a.wind, b.wind, 1e-6) && fabs(a.push - b.push) < 1e-9);
    /* The cloth settles on its 60 tuning within a few frames (it starts from 90's (2/3)^2). */
    assert(a.cloth / a.game > 0.999 && b.cloth / b.game == 1.0);
    /* The turn step: 1.125 a second from 90 FPS++, 1.111 from 60 FPS++ (Kyo's values). */
    assert(within(a.turn / a.game, 1.125, 1e-5) && within(b.turn / b.game, 1.0 / 0.9, 1e-5));

    /* Without following (BB_FRAME_TIME_PRESETS=0) the 90 preset at 60 FPS ran 2/3 slow. */
    const Run fixed = run(&p90, measured, FRAMES, 0);
    assert(fixed.step / fixed.game < 0.6 && fixed.wind / fixed.game < 0.31);

    /* Held at 90 (the limiter at 90, its frames 1/90 s or longer): nothing changes on time. */
    for (int i = 0; i < FRAMES; ++i) measured[i] = 1.0f / 90;
    const Run held = run(&p90, measured, FRAMES, 1), today = run(&p90, measured, FRAMES, 0);
    assert(held.step == today.step && held.turn == today.turn && held.wind == today.wind &&
           held.cloth == today.cloth && held.eased == today.eased);
    printf("frame time: ok (90 preset at 60 FPS: %.4f s of steps, %.4f of wind a game second; held at 90: as today)\n",
           a.step / a.game, a.wind / a.game);
    const char *game = getenv("BB_TEST_EBOOT_ELF");
    if (game && *game) check_game();
    else puts("SKIP frame time with the game's code: set BB_TEST_EBOOT_ELF to a prepared eboot.elf (scripts/prepare.py)");
    return 0;
}
