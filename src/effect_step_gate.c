/* SPDX-License-Identifier: GPL-2.0-or-later
 * Effects above 30 FPS step in whole 1/30 s, and the frames between hold what they count per
 * update (effect_step_gate.h). Ported from droogie's bbhost (https://github.com/droogie/bbhost,
 * GPL-3.0-or-later, branch render/next-10: a5930f2, ae1e44c, c558312, 9c13c5a and 9b1ac6b;
 * src/decomp/sfx/step_gate.cpp and src/engine/sfx_schedule.h).
 *
 * SprjSfx::Update (sub_2377bd0) hands the effect manager's update (vtable +0x40, sub_26ff340)
 * one step a frame: 1/30 s at 30 FPS, the frame's time with the FPS presets. The effects count
 * part of their lives in updates, not time: a node's state edges (sub_2c4df80's switch), its
 * emissions in state 1 (one an update, sub_2c4e6b0), the definitions its conditions pick, its
 * instance's controllers, and an FFX light's flicker phase (+0x30 adds the age times a rate each
 * call). Above 30 FPS they move on too often: at 90 the rock emitter of Ebrietas' effect 1251721
 * never stops and the effect never ends, where at 30 it ends by itself after 4.27 s.
 *
 * Here the manager takes whole 1/30 s steps, the rest of each frame's step carried. A frame that
 * takes none still runs the update with a step of 0, so effects follow what they ride on and are
 * drawn every frame, but on it:
 *   - the instance update (sub_2c4ff30) leaves its controllers to the next whole step, and each
 *     node only makes its container updates and its time adds (of 0), where sub_2c4df80 makes
 *     them; a dead node stays for the next whole step to free, as at 30;
 *   - the FFX light module's update (sub_131e660) runs with its phase rate (+0x80) as 0 and its
 *     blend mode (+0x38) as keep, both put back with the phase, except in a creation's pre-roll
 *     (sub_2c500e0, its stand-in render context);
 *   - a record of GPU particle type 0x2713 (sub_2cbcf50) keeps its previous time and its type's
 *     two sizes and three colours, which its curves would otherwise give for an elapsed time of 0.
 * The game's own still frame (SprjSfx+0x8c) and a step of 1/30 s or more stay the game's; with
 * the effects stepping 1/30 s a frame (30 FPS) nothing is hooked.
 *
 * Addresses are Binary Ninja's (BB_BN gives the image offset). */
#include "effect_step_gate.h"
#include "engine_hooks.h"

#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum {
    SFX = 0x5940370,               /* SprjSfx*: the effect manager at +0x70, the still frame at +0x8c */
    EFFECTS_CALL = 0x2377d34,      /* SprjSfx::Update: mov rax,[rdi]; mov rax,[rax+0x40]; cmp [r12+0x8c],0 */
    EFFECTS_CALL_END = 0x2377d52,  /* call rax; mov dword [r12+0x8c],0 */
    STEP_LOAD = 0x2377d48,         /* jne; vmovss xmm0,[STEP_CONSTANT], as the eboot has them */
    STEP_CONSTANT = 0x4d29170,
    MANAGER_SLOT = 0x57b90c0,      /* the effect manager's vtable +0x40 */
    MANAGER_UPDATE = 0x26ff340,    /* (manager, float step) */
    INSTANCE_UPDATE = 0x2c4ff30,   /* (instance, context, float step) */
    CONTROLLER_CALL = 0x2c4fffb,
    CONTROLLER_UPDATE = 0x2c820f0, /* (controller, instance, float step) */
    NODE_CALL = 0x2c5007b,
    NODE_UPDATE = 0x2c4df80,       /* (node, &step, definition, context) -> 0 frees the node */
    CONTAINER_UPDATE = 0x2c4c8c0,  /* (node + 0x80, &step, definition, context) */
    LIGHT_SLOT = 0x56ebbb8,        /* the FFX light module's vtable +0x18 */
    LIGHT_UPDATE = 0x131e660,      /* (module, params, context) */
    PREROLL_CONTEXT = 0x56dbd80,   /* the vtable of sub_2c500e0's stand-in render context */
    RECORD_UPDATE = 0x2cbcf50,     /* (record, item), from the GPU particle binder */
    TYPE_2713 = 0x56eb0d0,         /* GPU particle type 0x2713's vtable; +0x10 its update */
    TYPE_2713_UPDATE = 0x12e81b0,
};
static const uint64_t RECORD_CALLS[] = {0x2cbaaf7, 0x2cbab1d};

static const struct {
    uint64_t at;
    BbCode code;
} CODE[] = {
    {EFFECTS_CALL, {16, 0xdc7c08a7f7410b3cull}},
    {EFFECTS_CALL_END, {14, 0xdba237f1151f10beull}},
    {MANAGER_UPDATE, {28, 0x949a70763ce4838bull}},
    {INSTANCE_UPDATE, {0x1ae, 0x9cb8ac1277527517ull}},
    {NODE_UPDATE, {0x66c, 0x58f4c3523aa6739aull}},
    {CONTAINER_UPDATE, {20, 0x62b802cca4bec90bull}},
    {LIGHT_UPDATE, {0x8d2, 0xae216ee949720e67ull}},
    {RECORD_UPDATE, {0x1d5, 0x96921dc827d1648cull}},
    {TYPE_2713_UPDATE, {0x274, 0xd21a5454f05422dbull}},
};
static const BbCode step_load_code = {10, 0x757d71478a6d19d3ull};

enum { NODE_FLAGS = 0x78, NODE_TIME = 0x7c, NODE_CONTAINER = 0x80, NODE_DEFINITION_TIME = 0xe0 };
enum { NODE_ACTIVE = 1, NODE_DEAD = 4, NODE_STAGED = 8 };
enum { LIGHT_PHASE = 0x30, LIGHT_MODE = 0x38, LIGHT_RATE = 0x80, LIGHT_KEEP = 1 };
enum { RECORD_TYPE = 0x08, RECORD_PREVIOUS = 0x24, RECORD_TIME = 0x28, ITEM_STEP = 0x60,
       TYPE_SIZES = 0x1c, TYPE_COLOURS = 0x50, COLOURS_SIZE = 0x30 };

typedef uint64_t (BB_GUEST_ABI *ManagerFn)(uint64_t, float);
typedef uint64_t (BB_GUEST_ABI *ControllerFn)(uint64_t, uint64_t, float);
typedef uint8_t (BB_GUEST_ABI *NodeFn)(uint64_t, float *, uint64_t, uint64_t);
typedef void (BB_GUEST_ABI *ContainerFn)(uint64_t, float *, uint64_t, uint64_t);
typedef void (BB_GUEST_ABI *LightFn)(uint64_t, uint64_t, uint64_t);
typedef void (BB_GUEST_ABI *RecordFn)(uint64_t, uint64_t);

/* Set by the manager's update for its frame; the effects' updates read it on their threads. */
static atomic_int g_between;
static double g_carry;

static uint64_t guest(uint64_t bn) { return (uint64_t)(uintptr_t)bb_guest(BB_BN(bn)); }
static uint64_t read64(uint64_t at) {
    uint64_t v;
    memcpy(&v, (const void *)(uintptr_t)at, 8);
    return v;
}
static uint32_t read32(uint64_t at) {
    uint32_t v;
    memcpy(&v, (const void *)(uintptr_t)at, 4);
    return v;
}
static float read_float(uint64_t at) {
    float v;
    memcpy(&v, (const void *)(uintptr_t)at, 4);
    return v;
}
static void write32(uint64_t at, uint32_t v) { memcpy((void *)(uintptr_t)at, &v, 4); }
static void write_float(uint64_t at, float v) { memcpy((void *)(uintptr_t)at, &v, 4); }

static int held(void) { return atomic_load_explicit(&g_between, memory_order_relaxed); }

static BB_GUEST_ABI uint64_t on_effects(uint64_t manager, float step) {
    const uint64_t sfx = read64(guest(SFX));
    /* Another manager, or the game's own still frame, keeps the game's step. */
    const int sprj = sfx && read64(sfx + 0x70) == manager && !read32(sfx + 0x8c);
    int between = 0;
    const float taken = sprj ? bb_effect_step(&g_carry, step, &between) : step;
    atomic_store_explicit(&g_between, between, memory_order_relaxed);
    return ((ManagerFn)bb_guest(BB_BN(MANAGER_UPDATE)))(manager, taken);
}

static BB_GUEST_ABI uint64_t on_controller(uint64_t controller, uint64_t instance, float step) {
    if (held()) return 0;
    return ((ControllerFn)bb_guest(BB_BN(CONTROLLER_UPDATE)))(controller, instance, step);
}

/* What sub_2c4df80 does with a step of 0 that does not count: its container updates (the world
 * matrix that follows the parent, the modules' render items) and its time adds. */
static BB_GUEST_ABI uint8_t on_node(uint64_t node, float *step, uint64_t definition, uint64_t context) {
    if (!held()) return ((NodeFn)bb_guest(BB_BN(NODE_UPDATE)))(node, step, definition, context);
    const uint32_t flags = read32(node + NODE_FLAGS);
    /* At 30 the next update frees a dead node, 1/30 s later: freed now, it ended early. */
    if ((flags & NODE_DEAD) || !(flags & NODE_ACTIVE)) return 1;
    const ContainerFn container = (ContainerFn)bb_guest(BB_BN(CONTAINER_UPDATE));
    if (!(flags & NODE_STAGED)) {
        float s = *step;
        container(node + NODE_CONTAINER, &s, definition, context);
        write_float(node + NODE_DEFINITION_TIME, read_float(node + NODE_DEFINITION_TIME) + *step);
    }
    float s = *step;
    container(node + NODE_CONTAINER, &s, definition, context);
    write_float(node + NODE_TIME, read_float(node + NODE_TIME) + *step);
    return 1;
}

static BB_GUEST_ABI void on_light(uint64_t module, uint64_t params, uint64_t context) {
    const LightFn game = (LightFn)bb_guest(BB_BN(LIGHT_UPDATE));
    if (!held() || (context && read64(context) == guest(PREROLL_CONTEXT))) {
        game(module, params, context);
        return;
    }
    const uint32_t rate = read32(module + LIGHT_RATE), mode = read32(module + LIGHT_MODE);
    const uint32_t phase = read32(module + LIGHT_PHASE);
    write_float(module + LIGHT_RATE, 0.0f);
    write32(module + LIGHT_MODE, LIGHT_KEEP);
    game(module, params, context);
    write32(module + LIGHT_RATE, rate);
    write32(module + LIGHT_MODE, mode);
    /* The add of the age times 0 still turns a -0 phase into +0, or a NaN age into NaN. */
    write32(module + LIGHT_PHASE, phase);
}

static BB_GUEST_ABI void on_record(uint64_t record, uint64_t item) {
    const RecordFn game = (RecordFn)bb_guest(BB_BN(RECORD_UPDATE));
    const uint64_t type = read64(record + RECORD_TYPE);
    if (!held() || !type || read64(type) != guest(TYPE_2713) || read_float(item + ITEM_STEP) != 0.0f ||
        read32(record + RECORD_PREVIOUS) == read32(record + RECORD_TIME)) {
        game(record, item);
        return;
    }
    const uint32_t previous = read32(record + RECORD_PREVIOUS);
    unsigned char sizes[8], colours[COLOURS_SIZE];
    memcpy(sizes, (const void *)(uintptr_t)(type + TYPE_SIZES), sizeof(sizes));
    memcpy(colours, (const void *)(uintptr_t)(type + TYPE_COLOURS), sizeof(colours));
    game(record, item);
    write32(record + RECORD_PREVIOUS, previous);
    memcpy((void *)(uintptr_t)(type + TYPE_SIZES), sizes, sizeof(sizes));
    memcpy((void *)(uintptr_t)(type + TYPE_COLOURS), colours, sizeof(colours));
}

static int calls_to(uint64_t at, uint64_t target) {
    const unsigned char *site = bb_guest(BB_BN(at));
    int32_t rel;
    memcpy(&rel, site + 1, 4);
    return site[0] == 0xe8 && BB_BN(at) + 5 + (int64_t)rel == BB_BN(target);
}

/* The eboot's own load of 1/30 s: the effects already step as at 30. */
static int steps_at_thirty(void) {
    float step;
    memcpy(&step, bb_guest(BB_BN(STEP_CONSTANT)), 4);
    return bb_code_is(bb_guest(BB_BN(STEP_LOAD)), step_load_code) && step == BB_EFFECT_WHOLE_STEP;
}

/* The first site that is not as expected (its Binary Ninja address), or 0. */
static uint64_t unexpected(void) {
    for (size_t i = 0; i < sizeof(CODE) / sizeof(*CODE); ++i)
        if (!bb_code_is(bb_guest(BB_BN(CODE[i].at)), CODE[i].code)) return CODE[i].at;
    if (read64(guest(MANAGER_SLOT)) != guest(MANAGER_UPDATE)) return MANAGER_SLOT;
    if (read64(guest(LIGHT_SLOT)) != guest(LIGHT_UPDATE)) return LIGHT_SLOT;
    if (read64(guest(TYPE_2713) + 0x10) != guest(TYPE_2713_UPDATE)) return TYPE_2713;
    if (!calls_to(CONTROLLER_CALL, CONTROLLER_UPDATE)) return CONTROLLER_CALL;
    if (!calls_to(NODE_CALL, NODE_UPDATE)) return NODE_CALL;
    for (size_t i = 0; i < sizeof(RECORD_CALLS) / sizeof(*RECORD_CALLS); ++i)
        if (!calls_to(RECORD_CALLS[i], RECORD_UPDATE)) return RECORD_CALLS[i];
    return 0;
}

int bb_effect_step_gate_install(void) {
    const char *env = getenv("BB_EFFECT_STEP_GATE");
    if (env && !strcmp(env, "0")) {
        puts("Effect step gate: off (BB_EFFECT_STEP_GATE=0)");
        return 0;
    }
    if (steps_at_thirty()) {
        puts("Effect step gate: not needed, the effects step 1/30 s a frame (30 FPS)");
        return 0;
    }
    const uint64_t site = unexpected();
    if (site) {
        printf("Effect step gate: off (unexpected code at %#llx)\n", (unsigned long long)site);
        return 0;
    }
    /* The holds first: without them the manager's whole steps would leave the frames between
     * counting, so its slot goes last and only once every hold is in. */
    const uint64_t light = guest(LIGHT_UPDATE), our_light = (uint64_t)(uintptr_t)on_light;
    const uint64_t manager = guest(MANAGER_UPDATE), our_effects = (uint64_t)(uintptr_t)on_effects;
    int hooks = 0;
    hooks += !bb_hook_call(BB_BN(CONTROLLER_CALL), BB_BN(CONTROLLER_UPDATE), (void *)on_controller);
    hooks += !bb_hook_call(BB_BN(NODE_CALL), BB_BN(NODE_UPDATE), (void *)on_node);
    for (size_t i = 0; i < sizeof(RECORD_CALLS) / sizeof(*RECORD_CALLS); ++i)
        hooks += !bb_hook_call(BB_BN(RECORD_CALLS[i]), BB_BN(RECORD_UPDATE), (void *)on_record);
    hooks += !bb_patch(BB_BN(LIGHT_SLOT), &light, &our_light, 8);
    if (hooks != 5 || bb_patch(BB_BN(MANAGER_SLOT), &manager, &our_effects, 8)) {
        printf("Effect step gate: off (%s)\n", bb_hooks_error());
        return hooks;
    }
    puts("Effect step gate: on; above 30 FPS the effects take whole 1/30 s steps and the frames "
         "between hold what they count per update (BB_EFFECT_STEP_GATE=0 turns it off)");
    return hooks + 1;
}
