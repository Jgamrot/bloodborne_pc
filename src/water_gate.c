/* SPDX-License-Identifier: GPL-2.0-or-later
 * The water interaction's wave steps on the effects' whole 1/30 s steps above 30 FPS
 * (water_gate.h). Ported from droogie's bbhost (https://github.com/droogie/bbhost,
 * GPL-3.0-or-later, branch render/next-12: 57d2b9f, f6b975d and 44cf952;
 * src/decomp/gx/water_gate.cpp).
 *
 * The water interaction's manager (vtable 0x5760c60, the scene renderer's +0x1cd0) keeps grids
 * of heights, each with three maps: +0x10 the one a step writes and the water surfaces read,
 * +0xd0 the last step's, +0xd8 the one before. Each frame its update (sub_2677780, from the
 * scene renderer's prepare) turns each grid's maps round (sub_12bbda0) and hands each water
 * surface the impulses queued for it (+0xa0 into +0x98), and its render task (sub_2677e50, the
 * vtable's slot 0) splats them and runs one wave step, whose shader integrates a fixed time. So
 * the wakes spread at the frame rate: twice as fast at 60, four times at 120.
 *
 * Here the update steps when the effects took a whole step since its last frame (the step
 * gate's count, so the water steps on the effects' whole steps). On a frame between, the game's
 * update runs, the grids it turned round are turned back, and the task returns at once: the
 * surfaces show the last step's water, as between frames at 30. The next update gives the held
 * frame's impulses up when a newer frame's wait in the queue (a wake queues one each time it is
 * drawn), else puts them back in the queue, so a step takes the latest frame's. In screen-space
 * mode (+0x79) the grid follows the camera in whole units: a frame between on which the
 * camera's truncated x or z moved since the last step steps too, and the next whole step is
 * given up for it. At 30 FPS nothing is hooked.
 *
 * Addresses are Binary Ninja's (BB_BN gives the image offset). */
#include "water_gate.h"
#include "effect_step_gate.h"
#include "engine_hooks.h"

#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum {
    PREPARE_CALL = 0x26c55c7,   /* sub_26c53e0: lea rdi,[rbx+0x1cd0]; call WATER_UPDATE */
    WATER_UPDATE = 0x2677780,   /* (manager) */
    STEP_LOAD_A = 0x267784b,    /* vmovss xmm0,[1/30 s] before each call of TURN */
    STEP_LOAD_B = 0x2677892,
    TURN = 0x12bbda0,           /* (grid, float step): +0x10 <- +0xd8, +0xd0 <- +0x10, +0xd8 <- +0xd0 */
    TASK_SLOT = 0x5760c60,      /* the manager's vtable +0 */
    WATER_TASK = 0x2677e50,     /* (self, context, param): param +0 the manager */
    STEP_CONSTANT = 0x4d29b80,  /* what the loads read in the eboot */
    FRAME_TIME_SLOT = 0x575a908, /* and with 90 FPS++ (rate base), the 120 and 144 FPS presets */
};

/* The update is checked around the two loads' displacements, which the presets move. */
static const struct {
    uint64_t at;
    BbCode code;
} CODE[] = {
    {PREPARE_CALL - 7, {0xc, 0xbaff6d511a9ba0dcull}},
    {WATER_UPDATE, {0xcf, 0xf761276370191912ull}},
    {STEP_LOAD_A + 8, {0x43, 0x68ed3f32b494b21eull}},
    {STEP_LOAD_B + 8, {0x5b6, 0x301bb3e5ab972ba5ull}},
    {WATER_TASK, {0x8a0, 0x078bb0dd3f2a1c61ull}},
    {TURN, {0xdd, 0xd1b92a86bef51442ull}},
};

enum { MANAGER_HOLDERS = 0x18, MANAGER_SURFACES = 0x40, MANAGER_SCREEN_HOLDER = 0x60, MANAGER_NO_HOLDER = 0x68,
       MANAGER_ON = 0x78, MANAGER_SCREEN_SPACE = 0x79 };
enum { HOLDER_IN_USE = 0x18, GRID_MAP = 0x10, GRID_KIND = 0x30, GRID_LAST = 0xd0, GRID_BEFORE = 0xd8, GRID_WAVES = 3 };
enum { SURFACE_TAKEN = 0x98, SURFACE_QUEUED = 0xa0, VECTOR_FIRST = 8, VECTOR_END = 0x10, VECTOR_ROOM = 0x18,
       VECTOR_HEAP = 0x20 };
enum { CONTEXT_CAMERA = 0x3f8, CAMERA_X = 0x30, CAMERA_Z = 0x38 };

typedef uint64_t (BB_GUEST_ABI *UpdateFn)(uint64_t);
typedef uint64_t (BB_GUEST_ABI *TaskFn)(uint64_t, uint64_t, uint64_t);

/* A manager's gate; the scene renderer runs its update, then its task. */
enum { MANAGERS = 4, GRIDS = 32 };
typedef struct {
    _Atomic uint64_t manager;
    atomic_int decided; /* its update ran since its task did */
    int step;           /* that update's frame steps */
    int started, owed, waiting, have_camera;
    uint64_t whole;     /* the effects' whole steps at its last update */
    float camera_x, camera_z;
    int turned;
    uint64_t grids[GRIDS];
} Water;
static Water g_water[MANAGERS];

static uint64_t guest(uint64_t bn) { return (uint64_t)(uintptr_t)bb_guest(BB_BN(bn)); }
static uint64_t read64(uint64_t at) {
    uint64_t v;
    memcpy(&v, (const void *)(uintptr_t)at, 8);
    return v;
}
static uint8_t read8(uint64_t at) { return *(const uint8_t *)(uintptr_t)at; }
static float read_float(uint64_t at) {
    float v;
    memcpy(&v, (const void *)(uintptr_t)at, 4);
    return v;
}
static void write64(uint64_t at, uint64_t v) { memcpy((void *)(uintptr_t)at, &v, 8); }

static Water *water_of(uint64_t manager, int claim) {
    for (int i = 0; i < MANAGERS; ++i) {
        uint64_t have = atomic_load(&g_water[i].manager);
        if (have == manager) return &g_water[i];
        if (!have && claim && (atomic_compare_exchange_strong(&g_water[i].manager, &have, manager) || have == manager))
            return &g_water[i];
    }
    return NULL;
}

static void turn_round(uint64_t grid) {
    const uint64_t map = read64(grid + GRID_MAP), last = read64(grid + GRID_LAST), before = read64(grid + GRID_BEFORE);
    write64(grid + GRID_MAP, before);
    write64(grid + GRID_LAST, map);
    write64(grid + GRID_BEFORE, last);
}

static void turn_back(uint64_t grid) {
    const uint64_t map = read64(grid + GRID_MAP), last = read64(grid + GRID_LAST), before = read64(grid + GRID_BEFORE);
    write64(grid + GRID_MAP, last);
    write64(grid + GRID_LAST, before);
    write64(grid + GRID_BEFORE, map);
}

static int update_runs(uint64_t manager) { return read8(manager + MANAGER_ON) && read64(manager + MANAGER_NO_HOLDER); }

static int add_grid(Water *w, uint64_t grid) {
    if (!grid || !read64(grid + GRID_MAP) || read8(grid + GRID_KIND) != GRID_WAVES) return 1;
    if (w->turned == GRIDS) return 0;
    w->grids[w->turned++] = grid;
    return 1;
}

/* The grids the game's update turns round, in its order (TURN's own test); 0 past GRIDS. */
static int grids_to_turn(uint64_t manager, Water *w) {
    w->turned = 0;
    if (!update_runs(manager)) return 1;
    const uint64_t none = read64(manager + MANAGER_NO_HOLDER);
    const uint64_t end = read64(manager + MANAGER_HOLDERS + 8);
    for (uint64_t at = read64(manager + MANAGER_HOLDERS); at < end; at += 8) {
        const uint64_t holder = read64(at);
        if (holder && read8(holder + HOLDER_IN_USE) && holder != none && !add_grid(w, read64(holder))) return 0;
    }
    const uint64_t screen = read64(manager + MANAGER_SCREEN_HOLDER);
    return !screen || add_grid(w, read64(screen));
}

/* A held frame's impulses, still where the task reads them: given up for a newer frame's, else
 * put back in the queue (in its room, or by the vectors' swap the update makes itself), for the
 * game's update to hand on again. */
static void requeue(uint64_t manager) {
    const uint64_t end = read64(manager + MANAGER_SURFACES + 8);
    for (uint64_t at = read64(manager + MANAGER_SURFACES); at < end; at += 8) {
        const uint64_t surface = read64(at);
        if (!surface) continue;
        const uint64_t taken = read64(surface + SURFACE_TAKEN), queued = read64(surface + SURFACE_QUEUED);
        if (!taken || !queued || taken == queued) continue;
        const uint64_t t_first = read64(taken + VECTOR_FIRST), t_end = read64(taken + VECTOR_END);
        const uint64_t q_first = read64(queued + VECTOR_FIRST), q_end = read64(queued + VECTOR_END);
        const uint64_t q_room = read64(queued + VECTOR_ROOM);
        if (t_end <= t_first || q_end != q_first) continue;
        const uint64_t bytes = t_end - t_first;
        if (q_room >= q_first && q_room - q_first >= bytes) {
            memmove((void *)(uintptr_t)q_first, (const void *)(uintptr_t)t_first, bytes);
            write64(queued + VECTOR_END, q_first + bytes);
            write64(taken + VECTOR_END, t_first);
        } else if (read64(taken + VECTOR_HEAP) == read64(queued + VECTOR_HEAP)) {
            for (uint64_t f = VECTOR_FIRST; f <= VECTOR_ROOM; f += 8) {
                const uint64_t v = read64(taken + f);
                write64(taken + f, read64(queued + f));
                write64(queued + f, v);
            }
        }
    }
}

static BB_GUEST_ABI uint64_t on_update(uint64_t manager) {
    const UpdateFn game = (UpdateFn)bb_guest(BB_BN(WATER_UPDATE));
    Water *w = manager ? water_of(manager, 1) : NULL;
    if (!w) return game(manager);
    if (w->waiting) requeue(manager);
    w->waiting = 0;
    const uint64_t whole = bb_effect_whole_steps();
    int step = 1;
    if (!w->started) {
        w->started = 1;
        w->owed = w->have_camera = 0;
    } else if (whole == w->whole) {
        step = 0;
    } else if (w->owed) {
        w->owed = 0;
        step = 0;
    }
    w->whole = whole;
    if (!step && !grids_to_turn(manager, w)) step = 1;
    if (step) w->turned = 0;
    w->step = step;
    w->waiting = !step && update_runs(manager);
    const uint64_t result = game(manager);
    for (int i = w->turned - 1; i >= 0; --i) turn_back(w->grids[i]);
    atomic_store(&w->decided, 1);
    return result;
}

static BB_GUEST_ABI uint64_t on_task(uint64_t self, uint64_t context, uint64_t param) {
    const TaskFn game = (TaskFn)bb_guest(BB_BN(WATER_TASK));
    const uint64_t manager = param ? read64(param) : 0;
    Water *w = manager ? water_of(manager, 0) : NULL;
    if (!w || !atomic_exchange(&w->decided, 0)) return game(self, context, param);
    const uint64_t camera = context ? read64(context + CONTEXT_CAMERA) : 0;
    const int scroll = read8(manager + MANAGER_SCREEN_SPACE) && camera;
    /* The game's vroundps toward zero. */
    const float x = scroll ? __builtin_truncf(read_float(camera + CAMERA_X)) : 0.0f;
    const float z = scroll ? __builtin_truncf(read_float(camera + CAMERA_Z)) : 0.0f;
    if (!w->step) {
        if (!scroll || (w->have_camera && x == w->camera_x && z == w->camera_z)) return 0;
        for (int i = 0; i < w->turned; ++i) turn_round(w->grids[i]);
        w->owed = 1;
        w->waiting = 0;
    }
    if (scroll) {
        w->have_camera = 1;
        w->camera_x = x;
        w->camera_z = z;
    }
    return game(self, context, param);
}

/* The two loads before TURN's calls read the eboot's 1/30 s or the presets' frame time. */
static int loads_step(uint64_t load) {
    static const unsigned char vmovss_xmm0[] = {0xc5, 0xfa, 0x10, 0x05};
    const unsigned char *site = bb_guest(BB_BN(load));
    int32_t rel;
    memcpy(&rel, site + 4, 4);
    const uint64_t target = BB_BN(load) + 8 + (int64_t)rel;
    return !memcmp(site, vmovss_xmm0, 4) && (target == BB_BN(STEP_CONSTANT) || target == BB_BN(FRAME_TIME_SLOT));
}

static int calls_to(uint64_t at, uint64_t target) {
    const unsigned char *site = bb_guest(BB_BN(at));
    int32_t rel;
    memcpy(&rel, site + 1, 4);
    return site[0] == 0xe8 && BB_BN(at) + 5 + (int64_t)rel == BB_BN(target);
}

/* The first site that is not as expected (its Binary Ninja address), or 0. */
static uint64_t unexpected(void) {
    for (size_t i = 0; i < sizeof(CODE) / sizeof(*CODE); ++i)
        if (!bb_code_is(bb_guest(BB_BN(CODE[i].at)), CODE[i].code)) return CODE[i].at;
    if (!loads_step(STEP_LOAD_A)) return STEP_LOAD_A;
    if (!loads_step(STEP_LOAD_B)) return STEP_LOAD_B;
    if (read64(guest(TASK_SLOT)) != guest(WATER_TASK)) return TASK_SLOT;
    if (!calls_to(PREPARE_CALL, WATER_UPDATE)) return PREPARE_CALL;
    return 0;
}

int bb_water_gate_install(void) {
    const char *env = getenv("BB_WATER_GATE");
    if (env && !strcmp(env, "0")) {
        puts("Water wave steps: off (BB_WATER_GATE=0)");
        return 0;
    }
    const BbGateState gate = bb_effect_step_gate_state();
    if (gate != BB_GATE_ON) {
        puts(gate == BB_GATE_AT_THIRTY ? "Water wave steps: not needed, the effects step 1/30 s a frame (30 FPS)"
                                       : "Water wave steps: off (the effect step gate is off)");
        return 0;
    }
    const uint64_t site = unexpected();
    if (site) {
        printf("Water wave steps: off (unexpected code at %#llx)\n", (unsigned long long)site);
        return 0;
    }
    /* The task first: an update that holds frames needs the task that skips them. */
    const uint64_t task = guest(WATER_TASK), ours = (uint64_t)(uintptr_t)(void *)on_task;
    if (bb_patch(BB_BN(TASK_SLOT), &task, &ours, 8)) {
        printf("Water wave steps: off (%s)\n", bb_hooks_error());
        return 0;
    }
    if (bb_hook_call(BB_BN(PREPARE_CALL), BB_BN(WATER_UPDATE), (void *)on_update)) {
        bb_patch(BB_BN(TASK_SLOT), &ours, &task, 8);
        printf("Water wave steps: off (%s)\n", bb_hooks_error());
        return 0;
    }
    puts("Water wave steps: on; above 30 FPS the wakes in water step on the effects' whole 1/30 s steps "
         "(BB_WATER_GATE=0 turns it off)");
    return 2;
}
