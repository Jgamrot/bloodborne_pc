/* SPDX-License-Identifier: GPL-2.0-or-later
 * water_gate.c: the refusal of an image that is not the game's and, with the player's game
 * (game_code.h), the install on the game's own code (the eboot's and the 120/144 presets' loads),
 * then the hooked update and task over stand-ins that turn the maps, hand the impulses on and
 * step as the game's do: a step on each frame the effects take a whole step and on no other,
 * every step reading the two steps before it in order, the frames between showing the last
 * step's, each step taking the latest frame's impulses and none twice, and in screen-space mode
 * the grid never parting from the camera's whole units. The effect step gate is a stand-in; its
 * schedule is the gate's own (bb_effect_frame). */
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>
#include "effect_step_gate.h"
#include "engine_hooks.h"
#include "game_code.h"
#include "water_gate.h"

/* Binary Ninja addresses, as water_gate.c has them. */
enum {
    PREPARE_CALL = 0x26c55c7, WATER_UPDATE = 0x2677780, STEP_LOAD_A = 0x267784b, STEP_LOAD_B = 0x2677892,
    TURN = 0x12bbda0, TASK_SLOT = 0x5760c60, WATER_TASK = 0x2677e50,
};
static const size_t IMAGE = 0x5800000;
static const struct {
    uint64_t at;
    size_t n;
} GAME_CODE[] = {{PREPARE_CALL - 7, 12}, {WATER_UPDATE, 0x6d0}, {WATER_TASK, 0x8a0}, {TURN, 0xdd}};

/* The step gate, as far as the water reads it. */
static BbGateState g_gate_state = BB_GATE_ON;
static uint64_t g_whole;
BbGateState bb_effect_step_gate_state(void) { return g_gate_state; }
uint64_t bb_effect_whole_steps(void) { return g_whole; }

typedef uint64_t (BB_GUEST_ABI *UpdateFn)(uint64_t);
typedef uint64_t (BB_GUEST_ABI *TaskFn)(uint64_t, uint64_t, uint64_t);

static unsigned char *g_image;
static uint64_t at(uint64_t bn) { return (uint64_t)(uintptr_t)(g_image + BB_BN(bn)); }
static uint64_t addr(const void *p) { return (uint64_t)(uintptr_t)p; }
static void put64(uint64_t address, uint64_t v) { memcpy((void *)(uintptr_t)address, &v, 8); }
static uint64_t get64(uint64_t address) {
    uint64_t v;
    memcpy(&v, (const void *)(uintptr_t)address, 8);
    return v;
}
static void put_float(uint64_t address, float v) { memcpy((void *)(uintptr_t)address, &v, 4); }
static float get_float(uint64_t address) {
    float v;
    memcpy(&v, (const void *)(uintptr_t)address, 4);
    return v;
}
static uint8_t get8(uint64_t address) { return *(const uint8_t *)(uintptr_t)address; }

static int calls_to(uint64_t site, uint64_t target) {
    int32_t rel;
    memcpy(&rel, g_image + BB_BN(site) + 1, 4);
    return g_image[BB_BN(site)] == 0xe8 && BB_BN(site) + 5 + (int64_t)rel == BB_BN(target);
}
static uint64_t host_of(uint64_t site) {
    int32_t rel;
    memcpy(&rel, g_image + BB_BN(site) + 1, 4);
    return get64(at(site) + 5 + (int64_t)rel + 2);
}
static void stand_in(uint64_t bn, const void *fn) {
    unsigned char code[12] = {0x48, 0xb8};
    const uint64_t target = addr(fn);
    memcpy(code + 2, &target, 8);
    code[10] = 0xff;
    code[11] = 0xe0;
    memcpy(g_image + BB_BN(bn), code, sizeof(code));
}

static void build_fixture(void) {
    memset(g_image, 0, IMAGE);
    for (size_t i = 0; i < sizeof(GAME_CODE) / sizeof(*GAME_CODE); ++i)
        bb_test_place_game_code(g_image, BB_BN(GAME_CODE[i].at), GAME_CODE[i].n);
    put64(at(TASK_SLOT), at(WATER_TASK));
}

static void refused(void) {
    unsigned char *before = malloc(IMAGE);
    assert(before);
    memcpy(before, g_image, IMAGE);
    assert(bb_water_gate_install() == 0);
    assert(!memcmp(before, g_image, IMAGE));
    free(before);
}

/* --- The stand-ins: a manager with a grid a water surface's holder keeps, screen-space mode's
 * grid, and two water surfaces; maps stamped with the step that wrote them. --- */
enum { IMPULSE = 0x20, ROOM = 64 };
typedef struct {
    int written; /* the step that wrote it; -1 a resize's new map */
} Map;
static Map g_maps[4096];
static int g_map_count;
static Map *new_map(int written) {
    assert(g_map_count < (int)(sizeof(g_maps) / sizeof(*g_maps)));
    g_maps[g_map_count].written = written;
    return &g_maps[g_map_count++];
}

static _Alignas(16) unsigned char manager[0x100], holder[2][0x20], screen_holder[0x20], grid[2][0x140];
static _Alignas(16) unsigned char surface[2][0xb0], vector[2][2][0x28], context[0x400], camera[0x40],
    last_camera[0x40];
static uint64_t holders[2], surfaces[2], param[2];
static _Alignas(16) unsigned char buffers[4096][ROOM * IMPULSE];
static int g_buffer_count;
static uint64_t heaps[2] = {0x1000, 0x2000};

/* What the stand-ins saw. */
static int g_steps, g_order_errors, g_scroll_errors;
static int g_splats[100000], g_step_ids[64], g_step_id_count;
static float g_grid_x, g_grid_z;

static Map *map_at(uint64_t grid_at, int field) { return (Map *)(uintptr_t)get64(grid_at + field); }

static void fake_turn(uint64_t g) {
    if (!get64(g + 0x10) || get8(g + 0x30) != 3) return;
    const uint64_t map = get64(g + 0x10), last = get64(g + 0xd0), before = get64(g + 0xd8);
    put64(g + 0xd8, last);
    put64(g + 0xd0, map);
    put64(g + 0x10, before);
}

/* sub_2677780 as far as the gate sees it: the turns, a resize's new maps, the impulses handed on. */
static BB_GUEST_ABI uint64_t fake_update(uint64_t m) {
    if (!get8(m + 0x78) || !get64(m + 0x68)) return 0;
    for (uint64_t h = get64(m + 0x18); h < get64(m + 0x20); h += 8) {
        const uint64_t hd = get64(h);
        if (get8(hd + 0x18) && hd != get64(m + 0x68) && get64(hd)) fake_turn(get64(hd));
    }
    if (get64(m + 0x60) && get64(get64(m + 0x60))) fake_turn(get64(get64(m + 0x60)));
    for (int i = 0; i < 2; ++i)
        if (grid[i][0x100]) {
            grid[i][0x100] = 0;
            put64(addr(grid[i]) + 0x10, addr(new_map(-1)));
            put64(addr(grid[i]) + 0xd0, addr(new_map(-1)));
            put64(addr(grid[i]) + 0xd8, addr(new_map(-1)));
        }
    for (uint64_t s = get64(m + 0x40); s < get64(m + 0x48); s += 8) {
        const uint64_t taken = get64(get64(s) + 0x98), queued = get64(get64(s) + 0xa0);
        put64(taken + 0x10, get64(taken + 8));
        if (taken != queued && get64(taken + 0x20) == get64(queued + 0x20)) {
            for (int f = 8; f <= 0x18; f += 8) {
                const uint64_t v = get64(taken + f);
                put64(taken + f, get64(queued + f));
                put64(queued + f, v);
            }
        } else if (taken != queued) {
            /* Two heaps: the queue's impulses copied, each vector keeping its own room. */
            const uint64_t bytes = get64(queued + 0x10) - get64(queued + 8);
            assert(get64(taken + 8) + bytes <= get64(taken + 0x18));
            memcpy((void *)(uintptr_t)get64(taken + 8), (const void *)(uintptr_t)get64(queued + 8), bytes);
            put64(taken + 0x10, get64(taken + 8) + bytes);
        }
        put64(queued + 0x10, get64(queued + 8));
    }
    return 0;
}

static void wave_step(uint64_t g) {
    const Map *last = map_at(g, 0xd0), *before = map_at(g, 0xd8);
    if ((last->written != -1 && last->written != g_steps - 1) ||
        (before->written != -1 && before->written != g_steps - 2 && !(g_steps == 1 && before->written == 0)))
        ++g_order_errors;
    map_at(g, 0x10)->written = g_steps;
}

/* sub_2677e50: the splats of what each surface was handed, a step of each grid, the scroll. */
static BB_GUEST_ABI uint64_t fake_task(uint64_t self, uint64_t ctx, uint64_t prm) {
    (void)self;
    const uint64_t m = get64(prm);
    if (!get64(m + 0x68)) return 0;
    ++g_steps;
    g_step_id_count = 0;
    for (uint64_t s = get64(m + 0x40); s < get64(m + 0x48); s += 8) {
        const uint64_t taken = get64(get64(s) + 0x98);
        for (uint64_t i = get64(taken + 8); i < get64(taken + 0x10); i += IMPULSE) {
            const uint32_t id = (uint32_t)get64(i);
            /* While the manager is off its update hands nothing on, and the game's task splats the
             * last impulses again: those are the game's own. */
            if (get8(m + 0x78)) ++g_splats[id];
            if (g_step_id_count < 64) g_step_ids[g_step_id_count++] = (int)id;
        }
    }
    wave_step(addr(grid[0]));
    if (get8(m + 0x79) && get64(m + 0x60)) {
        const uint64_t now = get64(ctx + 0x3f8), before = get64(prm + 8);
        g_grid_x += truncf(get_float(now + 0x30)) - truncf(get_float(before + 0x30));
        g_grid_z += truncf(get_float(now + 0x38)) - truncf(get_float(before + 0x38));
        if (g_grid_x != truncf(get_float(now + 0x30)) || g_grid_z != truncf(get_float(now + 0x38))) ++g_scroll_errors;
        wave_step(addr(grid[1]));
    }
    return 0;
}

static void vector_init(unsigned char *v, uint64_t heap, int room) {
    memset(v, 0, 0x28);
    put64(addr(v) + 0x20, heap);
    if (room) {
        assert(g_buffer_count < (int)(sizeof(buffers) / sizeof(*buffers)));
        const uint64_t b = addr(buffers[g_buffer_count++]);
        put64(addr(v) + 8, b);
        put64(addr(v) + 0x10, b);
        put64(addr(v) + 0x18, b + ROOM * IMPULSE);
    }
}

/* sub_2677170: a wake's impulse queued for a surface, the queue grown as a vector grows. */
static void queue_impulse(int s, uint32_t id) {
    const uint64_t q = get64(addr(surface[s]) + 0xa0);
    if (get64(q + 0x10) + IMPULSE > get64(q + 0x18)) {
        const uint64_t first = get64(q + 8), bytes = get64(q + 0x10) - first;
        assert(g_buffer_count < (int)(sizeof(buffers) / sizeof(*buffers)));
        const uint64_t b = addr(buffers[g_buffer_count++]);
        if (bytes) memcpy((void *)(uintptr_t)b, (const void *)(uintptr_t)first, bytes);
        put64(q + 8, b);
        put64(q + 0x10, b + bytes);
        put64(q + 0x18, b + ROOM * IMPULSE);
    }
    unsigned char impulse[IMPULSE] = {0};
    memcpy(impulse, &id, 4);
    memcpy((void *)(uintptr_t)get64(q + 0x10), impulse, IMPULSE);
    put64(q + 0x10, get64(q + 0x10) + IMPULSE);
}

static void reset_world(int screen_space, int split_heaps) {
    memset(manager, 0, sizeof(manager));
    memset(holder, 0, sizeof(holder));
    memset(screen_holder, 0, sizeof(screen_holder));
    memset(grid, 0, sizeof(grid));
    memset(surface, 0, sizeof(surface));
    memset(g_splats, 0, sizeof(g_splats));
    g_map_count = g_buffer_count = 0;
    g_steps = g_order_errors = g_scroll_errors = 0;
    for (int i = 0; i < 2; ++i) {
        grid[i][0x30] = 3;
        put64(addr(grid[i]) + 0x10, addr(new_map(0)));
        put64(addr(grid[i]) + 0xd0, addr(new_map(0)));
        put64(addr(grid[i]) + 0xd8, addr(new_map(0)));
    }
    put64(addr(holder[0]), addr(grid[0]));
    holder[0][0x18] = 1;
    holder[1][0x18] = 1; /* the holder for none */
    holders[0] = addr(holder[0]);
    holders[1] = addr(holder[1]);
    put64(addr(manager) + 0x18, addr(&holders[0]));
    put64(addr(manager) + 0x20, addr(&holders[2]));
    put64(addr(manager) + 0x68, addr(holder[1]));
    manager[0x78] = 1;
    manager[0x79] = (unsigned char)screen_space;
    put64(addr(screen_holder), addr(grid[1]));
    if (screen_space) put64(addr(manager) + 0x60, addr(screen_holder));
    for (int s = 0; s < 2; ++s) {
        /* One surface's queue starts with no room: its held impulses go back by the vectors' swap. */
        vector_init(vector[s][0], heaps[0], 1);
        vector_init(vector[s][1], heaps[split_heaps && s ? 1 : 0], s == 0);
        put64(addr(surface[s]) + 0x98, addr(vector[s][0]));
        put64(addr(surface[s]) + 0xa0, addr(vector[s][1]));
        surfaces[s] = addr(surface[s]);
    }
    put64(addr(manager) + 0x40, addr(&surfaces[0]));
    put64(addr(manager) + 0x48, addr(&surfaces[2]));
    put64(addr(context) + 0x3f8, addr(camera));
    param[0] = addr(manager);
    param[1] = addr(last_camera);
}

typedef struct {
    int frames, steps, wrong, camera_steps, latest_errors, splat_twice, lost;
    double seconds;
} Run;

/* Frames at `fps` (0: uneven, 1/240 to 1/30 s), the camera moving at `speed` m/s along x and a
 * third of it along z, impulses queued on the frames `queue` picks. */
static Run run(float fps, float speed, int screen_space, int (*queue)(int frame, int stepped_before)) {
    reset_world(screen_space, 0);
    const UpdateFn update = (UpdateFn)(uintptr_t)host_of(PREPARE_CALL);
    const TaskFn task = (TaskFn)(uintptr_t)get64(at(TASK_SLOT));
    Run r = {0};
    double carry = 0, t = 0;
    uint32_t seed = 0x2677e50u, id = 1, latest = 0;
    int stepped_before = 1, frames = fps ? (int)(fps * 20) : 12000, waiting_ids = 0;
    float x = -40.3f, z = 25.6f;
    put_float(addr(camera) + 0x30, x);
    put_float(addr(camera) + 0x38, z);
    memcpy(last_camera, camera, sizeof(camera));
    g_grid_x = truncf(x);
    g_grid_z = truncf(z);
    /* Two whole steps for what the last run left (a step the camera took ahead), then a fresh count. */
    for (int i = 0; i < 2; ++i) {
        ++g_whole;
        update(addr(manager));
        task(addr(manager), addr(context), addr(&param[0]));
    }
    for (int i = 0; i < g_map_count; ++i) g_maps[i].written = 0;
    g_steps = g_order_errors = g_scroll_errors = 0;
    for (int i = 0; i < frames; ++i) {
        seed = seed * 1664525u + 1013904223u;
        const float dt = fps ? 1.0f / fps : 1.0f / 240 + (1.0f / 30 - 1.0f / 240) * (float)(seed >> 8) / (float)(1u << 24);
        const BbEffectFrame f = bb_effect_frame(&carry, dt);
        g_whole += !f.between;
        t += dt;
        memcpy(last_camera, camera, sizeof(camera));
        x += speed * dt;
        z -= speed * dt / 3;
        put_float(addr(camera) + 0x30, x);
        put_float(addr(camera) + 0x38, z);
        if (queue(i, stepped_before)) {
            queue_impulse(0, id);
            queue_impulse(1, id);
            latest = id++;
            ++waiting_ids;
        }
        const int steps = g_steps;
        update(addr(manager));
        task(addr(manager), addr(context), addr(&param[0]));
        const int stepped = g_steps != steps;
        r.steps += stepped;
        if (stepped) {
            /* The latest frame's impulses (both surfaces'), when one came since the last step. */
            if (waiting_ids && !(g_step_id_count == 2 && g_step_ids[0] == (int)latest && g_step_ids[1] == (int)latest))
                ++r.latest_errors;
            if (!waiting_ids && g_step_id_count) ++r.latest_errors;
            waiting_ids = 0;
        }
        /* Without the camera's steps a frame steps on the effects' whole steps, and on no other. */
        if (!screen_space && stepped != !f.between) ++r.wrong;
        if (screen_space && stepped && f.between) ++r.camera_steps;
        /* Between steps the surfaces read the last step's maps. */
        if (map_at(addr(grid[0]), 0x10)->written != g_steps) ++g_order_errors;
        stepped_before = stepped;
        ++r.frames;
    }
    for (uint32_t k = 1; k < id; ++k) {
        if (g_splats[k] > 2) ++r.splat_twice;
        if (!g_splats[k]) ++r.lost;
    }
    r.seconds = t;
    return r;
}

static int every_frame(int frame, int stepped_before) { return (void)frame, (void)stepped_before, 1; }
static int after_steps(int frame, int stepped_before) { return (void)frame, stepped_before; }
static int every_seventh(int frame, int stepped_before) { return (void)stepped_before, frame % 7 == 0; }

static void check_runs(void) {
    static const float rates[] = {30, 60, 90, 120, 144, 0};
    for (size_t i = 0; i < sizeof(rates) / sizeof(*rates); ++i) {
        char name[32];
        snprintf(name, sizeof(name), rates[i] ? "%.0f FPS" : "uneven frames", rates[i]);
        const Run r = run(rates[i], 0.0f, 0, every_frame);
        printf("  %s: %d steps over %d frames, %.3f s: %.2f a second\n", name, r.steps, r.frames, r.seconds,
               r.steps / r.seconds);
        assert(!r.wrong && !g_order_errors && !r.latest_errors && !r.splat_twice);
        assert(fabs(r.steps - 30.0 * r.seconds) <= 1.5);
        if (rates[i] == 30) assert(r.steps == r.frames);
        /* Impulses queued only on some frames still reach the next step, once. */
        const Run some = run(rates[i], 0.0f, 0, after_steps);
        assert(!some.wrong && !g_order_errors && !some.latest_errors && !some.splat_twice && !some.lost);
        const Run seventh = run(rates[i], 0.0f, 0, every_seventh);
        assert(!seventh.wrong && !g_order_errors && !seventh.latest_errors && !seventh.splat_twice && !seventh.lost);
        /* Screen-space mode, running through x = 0: the grid keeps to the camera's whole units, at 30 a second. */
        const Run s = run(rates[i], 6.0f, 1, every_frame);
        printf("  %s, screen-space at 6 m/s: %d steps (%d as the camera crossed) over %.3f s: %.2f a second\n",
               name, s.steps, s.camera_steps, s.seconds, s.steps / s.seconds);
        assert(!g_order_errors && !g_scroll_errors && !s.latest_errors && !s.splat_twice);
        assert(fabs(s.steps - 30.0 * s.seconds) <= 2.0 + 0.02 * s.seconds * 30.0);
        if (rates[i] > 30) assert(s.camera_steps > 0);
    }
}

/* A frame between steps whose update hands on what the queue held: with the manager off for a
 * while, nothing is taken twice; a surface whose vectors come from two heaps keeps its own. */
static void check_odd_managers(void) {
    reset_world(0, 1);
    const UpdateFn update = (UpdateFn)(uintptr_t)host_of(PREPARE_CALL);
    const TaskFn task = (TaskFn)(uintptr_t)get64(at(TASK_SLOT));
    const uint64_t own_taken = get64(addr(surface[1]) + 0x98), own_queued = get64(addr(surface[1]) + 0xa0);
    double carry = 0;
    uint32_t id = 50000;
    for (int i = 0; i < 400; ++i) {
        g_whole += !bb_effect_frame(&carry, 1.0f / 120).between;
        manager[0x78] = (unsigned char)(i % 50 >= 20);
        /* sub_2677170 queues nothing while the manager is off. */
        if (manager[0x78]) {
            queue_impulse(0, id);
            queue_impulse(1, id);
            ++id;
        }
        update(addr(manager));
        task(addr(manager), addr(context), addr(&param[0]));
        assert(get64(addr(surface[1]) + 0x98) == own_taken && get64(addr(surface[1]) + 0xa0) == own_queued);
    }
    for (uint32_t k = 50000; k < id; ++k) assert(g_splats[k] <= 2);
}

static void check_game(void) {
    build_fixture();
    assert(bb_hooks_init(g_image, IMAGE) == 0);
    g_gate_state = BB_GATE_AT_THIRTY;
    refused();
    g_gate_state = BB_GATE_OFF;
    refused();
    g_gate_state = BB_GATE_ON;
    _putenv("BB_WATER_GATE=0");
    refused();
    _putenv("BB_WATER_GATE=");

    /* Each site that is not the game's refuses the whole install. */
    static const uint64_t changed[] = {PREPARE_CALL - 7, PREPARE_CALL + 1, WATER_UPDATE + 0x30, STEP_LOAD_A + 2,
                                       STEP_LOAD_A + 8, STEP_LOAD_B + 5, WATER_UPDATE + 0x400, WATER_TASK + 0x100,
                                       TURN + 0x20};
    for (size_t i = 0; i < sizeof(changed) / sizeof(*changed); ++i) {
        build_fixture();
        g_image[BB_BN(changed[i])] ^= 1;
        refused();
    }
    build_fixture();
    put64(at(TASK_SLOT), at(WATER_TASK) + 16);
    refused();

    /* 90 FPS++ (rate base), the 120 and 144 presets: the loads read the frame-time slot. */
    build_fixture();
    static const unsigned char rate_a[] = {0xb5, 0x30, 0x0e, 0x03}, rate_b[] = {0x6e, 0x30, 0x0e, 0x03};
    memcpy(g_image + BB_BN(STEP_LOAD_A + 4), rate_a, 4);
    memcpy(g_image + BB_BN(STEP_LOAD_B + 4), rate_b, 4);
    assert(bb_water_gate_install() == 2);

    /* The loader's TCB loads: none in the checked code, which installs as the executable has it. */
    build_fixture();
    static const unsigned char fs[] = {0x64, 0x48, 0x8b, 0x04, 0x25};
    for (size_t i = 0; i + sizeof(fs) <= IMAGE; ++i) assert(g_image[i] != 0x64 || memcmp(g_image + i, fs, sizeof(fs)));
    assert(bb_water_gate_install() == 2);

    build_fixture();
    assert(bb_water_gate_install() == 2);
    assert(!calls_to(PREPARE_CALL, WATER_UPDATE) && get64(at(TASK_SLOT)) != at(WATER_TASK));
    bb_hooks_seal();
    DWORD old;
    assert(VirtualProtect(g_image, IMAGE, PAGE_EXECUTE_READWRITE, &old));
    stand_in(WATER_UPDATE, (const void *)fake_update);
    stand_in(WATER_TASK, (const void *)fake_task);
    FlushInstructionCache(GetCurrentProcess(), g_image, IMAGE);
    check_runs();
    check_odd_managers();
}

int main(void) {
    setvbuf(stdout, NULL, _IONBF, 0);
    g_image = VirtualAlloc(NULL, IMAGE, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
    assert(g_image);
    const char *game = getenv("BB_TEST_EBOOT_ELF");
    if (game && *game) {
        check_game();
        puts("water gate: ok (with the game's code)");
        return 0;
    }
    assert(bb_hooks_init(g_image, IMAGE) == 0);
    refused();
    puts("water gate: ok (BB_TEST_EBOOT_ELF unset: the game's code not checked)");
    return 0;
}
