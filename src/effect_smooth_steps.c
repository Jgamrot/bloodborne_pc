/* SPDX-License-Identifier: GPL-2.0-or-later
 * The smooth effect steps (effect_step_gate.h). Ported from droogie's bbhost
 * (https://github.com/droogie/bbhost, GPL-3.0-or-later, branch render/next-13: 8e5ac13, 57f4b21,
 * 83d00bd, 9906f8d, ac386f8, 3d841f1, 6617fef, 15ece99, 579bbd2, 5e0d009, 8a5a46a, 4dd433e, f66bc99,
 * 77a33d6, 5e3974e, 1293ed4, 5986a4b, fd80740 and f0be5e4; src/decomp/sfx/step_gate.cpp and
 * node_update.cpp).
 *
 * The step gate (effect_step_gate.c) keeps what the effects count on whole 1/30 s steps, and so
 * moves everything they move in whole steps too. Here an instance whose every class is on the
 * converted list (CLASSES: each one's update read in Binary Ninja and checked here by its code)
 * moves by each frame's own time instead:
 *   - its nodes' container calls (the motions, modules and binders) get the frame's step on the
 *     manager's time scale and the instance's, and the node's time (+0x7c), and a plain node's
 *     definition time (+0xe0), put as far past the last whole step as the frame begins (a plain
 *     node's second call: ends) for the call. On a whole step that is the game's node update with
 *     its two container calls (0x2c4e143, 0x2c4e540) taken; between whole steps only the container
 *     calls run, as the gate's hold has them;
 *   - an FFX light counts its flicker once a whole step at the whole step's time, and between and
 *     after that runs at the frame's time with its rate and blends held;
 *   - a following wobble (0x570e690) follows its parent every frame, its count held;
 *   - a ribbon (FFX-format GX type 0x28) inserts its points once a whole step at the whole step's
 *     time and place, its head drawn to the emitter every frame;
 *   - GPU particle type 0x2713 reads its curves at the whole step's elapsed time;
 *   - StandardParticle and Spark emit what a whole step's update would, over its frames;
 *   - the fading lights of ended FFX lights (sub_12e5500) and the wind sources' gusts
 *     (sub_1314660) move by the frame's time.
 * An instance with a class off the list keeps the gate's whole steps. Nothing here acts on the
 * game's own still frame or a step of 1/30 s or more.
 *
 * Addresses are Binary Ninja's (BB_BN gives the image offset). */
#include "effect_smooth_steps.h"
#include "engine_hooks.h"

#include <emmintrin.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum {
    SFX = 0x5940370,
    NO_TIME = 0x5ac82e8,           /* the effects' "no time" float */
    NODE_UPDATE = 0x2c4df80,       /* (node, &step, definition, context) */
    CONTAINER_UPDATE = 0x2c4c8c0,  /* (node + 0x80, &step, definition, context) */
    CONTAINER_FIRST = 0x2c4e143,   /* a plain node's call, before its +0xe0 add */
    CONTAINER_LAST = 0x2c4e540,    /* every node's, before its +0x7c add */
    LIGHT_UPDATE = 0x131e660,
    FOLLOW = 0x2e896f0,            /* motion 0x570e690's update */
    RECORD_UPDATE = 0x2cbcf50,
    WIND_CALL = 0x26ff3ee,         /* the manager's update: (registry, step x time scale) */
    WIND_SOURCES = 0x1314660,      /* each source's vtable +0x58 */
    SOURCE = 0x56ec140,            /* the wind sources' class */
    SOURCE_STEP = 0x2d552d0,       /* its last step, age and gust phase */
    SOURCE_NONE = 0x56ebf70,       /* an entry's default object */
    SOURCE_NONE_STEP = 0x2d521c0,  /* ret */
    FADES_CALL = 0x27019fc,        /* the manager's update: (manager + 0x118, its step) */
    FADES_CALL_CODE = 0x27019ed,
    LIGHT_FADES = 0x12e5500,
    COMPOSITE = 0x570e750,         /* a motion running its parts at +8 and +0x10 */
    GX_BINDER = 0x56e3100,         /* a GPU particle system's record binder; its type at *(+0x10) + 8 */
    RIBBON = 0x56e3620,            /* FFX-format GX type 0x28 */
    TYPE_2713 = 0x56eb0d0,
    STANDARD = 0x56eb1d0,          /* GPU particle types 0x2710 and 0x2718 */
    SPARK = 0x56eb120,
    STANDARD_SIMULATION = 0x13040b0,
    SPARK_SIMULATION = 0x12fef10,
};

/* The converted classes: each one's vtable, the slot of its update and that update's code. */
static const struct {
    uint64_t vtable;
    unsigned slot;
    uint64_t update;
    BbCode code;
} CLASSES[] = {
    /* motions: velocity by the step times a speed curve, position by the step, facing the move */
    {0x570e650, 0, 0x2e88510, {0x4fe, 0x505b83963c9f60feull}},
    {0x570e610, 0, 0x2e87a10, {0x6a3, 0xda667193eb158a8cull}},  /* with gravity */
    {0x570e5d0, 0, 0x2e866f0, {0x868, 0xd060474d0c43aa4dull}},  /* with the wind world */
    {0x570e6d0, 0, 0x2e89d10, {0x593, 0xa13804c81f5d972eull}},  /* wobble: its count held by the gate */
    {0x570e690, 0, 0x2e896f0, {0x3b3, 0x5185cb44fda14875ull}},  /* following wobble */
    {0x570e850, 0, 0x2e8d740, {0x256, 0x23451f0f76105ccbull}},  /* direction motions */
    {0x570e810, 0, 0x2e8cc60, {0x3f5, 0x8acb01f20f41b501ull}},
    {0x570e7d0, 0, 0x2e8bfd0, {0x5a6, 0xd879c97cba1ae465ull}},
    {0x570e8d0, 0, 0x2e8e430, {0x593, 0x1a095bfd6d2f90b6ull}},  /* direction wobble */
    {0x570e890, 0, 0x2e8de10, {0x3b2, 0x1efb8a887d9b8eaeull}},  /* following direction wobble */
    {0x570e790, 0, 0x2e8b100, {0x95b, 0xd2dfbe24e26634d6ull}},  /* turned by the step times its rates */
    {0x570e710, 0, 0x2e8a3d0, {0x7cc, 0x57d8543b04e0d201ull}},  /* a transform; no step */
    {0x570e910, 0, 0x2e8ec00, {0x6e, 0xeff5b3f576e3be24ull}},   /* a curve at the node's time */
    /* modules */
    {0x56eb2e0, 0x18, 0x12fccf0, {0x403, 0x6624c0a5845434eaull}}, /* the children follow */
    {0x5756e50, 0x10, 0x23749d0, {0x1f8, 0x10fdd1c017f6e4ccull}}, /* a model advanced by the step */
    {0x56ebba0, 0x18, 0x131e660, {0x8d2, 0xae216ee949720e67ull}}, /* FFX light (bb_smooth_light) */
    {0x56ebc40, 0x18, 0x1320260, {0xa85, 0x2957faa9c5ee54d9ull}}, /* FFX spot light: curves at the age */
    /* binders */
    {0x56e3090, 0x10, 0x2cba4b0, {0xe4, 0x46a3e68d6a8d6591ull}},  /* CPU particles */
    {0x56e3100, 0x10, 0x2cbaa40, {0xc8, 0x7344b05fa476671dull}},  /* a GPU particle record */
    /* GPU particle types */
    {0x56eb1d0, 0x10, 0x12f18f0, {0x306, 0x1887e57a11874ba5ull}}, /* StandardParticle (emission_window) */
    {0x56eb120, 0x10, 0x12ed0b0, {0x306, 0xa3589bece5bf043eull}}, /* Spark (emission_window) */
    {0x56eb220, 0x10, 0x12f7ee0, {0x37f, 0xf004bd22692e465cull}}, /* WanderingVision */
    {0x56ea9b0, 0x10, 0x12e09d0, {0x498, 0x33c1e1715935e9d9ull}}, /* 0x283e: no time */
    {0x56eaa90, 0x10, 0x12e17d0, {0x50c, 0x65101da8aa61c99aull}}, /* 0x27d8: no time */
    {0x56eb290, 0x10, 0x12fc690, {0x76, 0xb47cdab7c6d90a54ull}},  /* 0x2968: constant bounds */
    {0x56eb0d0, 0x10, 0x12e81b0, {0x274, 0xd21a5454f05422dbull}}, /* 0x2713 (smooth_2713) */
    /* FFX-format GX types */
    {0x56e35d0, 0x10, 0x2ec0a60, {0x171, 0x6b77ba0be272796eull}}, /* 0x6b: bounds only */
    {0x56e3530, 0x10, 0x2eb6550, {0x2d5, 0x7d07755f2d409dd4ull}}, /* 0x14 / 0x3b: the elapsed time x rates */
    {0x56e3580, 0x10, 0x2ebc280, {0x28c, 0x911f11cd552002aaull}}, /* 0x2b */
    {0x56ebe20, 0x10, 0x1325cd0, {0xe0, 0x3c5dcb418a00a89dull}},  /* 3 / 0x3d */
    {0x56eadf0, 0x10, 0x12e3c30, {0x821, 0x64c60dd150dc1567ull}}, /* 0x283c: a wind source */
    {0x56eac40, 0x10, 0x12e27b0, {0x773, 0x3e577ec3b120cd18ull}}, /* 0x283d: a wind source */
    {0x56e3620, 0x10, 0x2ec1e00, {0x174e, 0x41cdd51d6ce93283ull}}, /* ribbon (smooth_ribbon) */
};

static const struct {
    uint64_t at;
    BbCode code;
} CODE[] = {
    {0x2e8ae30, {0x3d, 0xd874d47b346b36d5ull}}, /* the composite's update */
    {WIND_SOURCES, {0x52, 0xa34e2f34a6ee1876ull}},
    {SOURCE_STEP, {0x36, 0x5dd7aa27f6eeaedcull}},
    {SOURCE_NONE_STEP, {1, 0xaf647e4c8602ffd2ull}},
    {FADES_CALL_CODE, {0x14, 0x4b2d08600fa99c25ull}},
    {LIGHT_FADES, {0x22d, 0x6f3fd8d1f57ef61aull}},
    {STANDARD_SIMULATION, {0xd26, 0x92b05bfb926af18full}},
    {SPARK_SIMULATION, {0xb44, 0x9d79610e7a2e0545ull}},
};
static const struct {
    uint64_t slot, target;
} SLOTS[] = {{COMPOSITE, 0x2e8ae30}, {SOURCE + 0x58, SOURCE_STEP}, {SOURCE_NONE + 0x58, SOURCE_NONE_STEP}};

enum { MANAGER_STILL = 0x5ce, MANAGER_TIME_SCALE = 0x5d8, MANAGER_FADES = 0x118 };
enum { INSTANCE_SCALE = 0x08, INSTANCE_DEFINITION = 0x38, INSTANCE_ROOT = 0x78 };
enum { NODE_INSTANCE = 0x58, NODE_PARENT = 0x60, NODE_SIBLING = 0x68, NODE_CHILD = 0x70, NODE_FLAGS = 0x78,
       NODE_TIME = 0x7c, NODE_CONTAINER = 0x80, NODE_MOTION = 0x90, NODE_DEFINITION_TIME = 0xe0,
       CONTAINER_PENDING = 0x30, PENDING_NEXT = 0x18, PENDING_TARGET = 0x20 };
enum { NODE_ACTIVE = 1, NODE_DEAD = 4, NODE_STAGED = 8 };
enum { LIGHT_PHASE = 0x30, LIGHT_MODE = 0x38, LIGHT_COLOUR_MODE = 0x3c, LIGHT_RATE = 0x80, LIGHT_KEEP = 1,
       LIGHT_BLEND = 2 };
enum { FOLLOW_PERIOD = 0x68, FOLLOW_COUNT = 0x6c };
enum { RECORD_TYPE = 0x08, RECORD_NODE = 0x10, RECORD_PREVIOUS = 0x24, RECORD_TIME = 0x28, RECORD_ROWS = 0x50,
       ITEM_STEP = 0x60, TYPE_DEFINITION = 0x08, RIBBON_DEFINITION = 0x12c, RIBBON_INTERVAL = 0x88,
       RIBBON_SMOOTHING = 0x98 };

typedef uint8_t (BB_GUEST_ABI *NodeFn)(uint64_t, float *, uint64_t, uint64_t);
typedef void (BB_GUEST_ABI *ContainerFn)(uint64_t, float *, uint64_t, uint64_t);
typedef void (BB_GUEST_ABI *LightFn)(uint64_t, uint64_t, uint64_t);
typedef void (BB_GUEST_ABI *MotionFn)(uint64_t, uint64_t, const float *, uint64_t);
typedef void (BB_GUEST_ABI *RecordFn)(uint64_t, uint64_t);
typedef void (BB_GUEST_ABI *StepFn)(uint64_t, float);

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
static int32_t read_s32(uint64_t at) { return (int32_t)read32(at); }
static uint8_t read8(uint64_t at) { return *(const volatile uint8_t *)(uintptr_t)at; }
static float read_float(uint64_t at) {
    float v;
    memcpy(&v, (const void *)(uintptr_t)at, 4);
    return v;
}
static void write64(uint64_t at, uint64_t v) { memcpy((void *)(uintptr_t)at, &v, 8); }
static void write32(uint64_t at, uint32_t v) { memcpy((void *)(uintptr_t)at, &v, 4); }
static void write8(uint64_t at, uint8_t v) { *(volatile uint8_t *)(uintptr_t)at = v; }
static void write_float(uint64_t at, float v) { memcpy((void *)(uintptr_t)at, &v, 4); }
static uint32_t bits(float f) {
    uint32_t b;
    memcpy(&b, &f, 4);
    return b;
}
static float from_bits(uint32_t b) {
    float f;
    memcpy(&f, &b, 4);
    return f;
}

/* The game's addss and subss, its first operand first, so a NaN keeps the game's payload. */
static float add_ss(float x, float y) {
    __asm__("addss %1, %0" : "+x"(x) : "x"(y));
    return x;
}
static float sub_ss(float x, float y) {
    __asm__("subss %1, %0" : "+x"(x) : "x"(y));
    return x;
}

/* The frame, set before SprjSfx's manager update and read by the effects' updates on their threads:
 * whether the smooth steps run it, its own time, the carry before and after it, the manager. */
static atomic_int g_on, g_split;
static atomic_uint g_frame, g_from, g_into, g_serial = 1, g_whole_serial = 1;
static _Atomic uint64_t g_manager;
/* In that update on its own thread (the wind sources and the light fades). */
static _Thread_local int t_update;

static float frame_float(atomic_uint *v) { return from_bits(atomic_load_explicit(v, memory_order_relaxed)); }
static uint64_t manager(void) { return atomic_load_explicit(&g_manager, memory_order_relaxed); }

/* The converted classes' vtables as the image has them, in an open table built at install. */
enum { CONVERTED_SLOTS = 128 };
static uint64_t g_converted[CONVERTED_SLOTS];
static size_t converted_slot(uint64_t vt) { return (size_t)(((vt >> 3) * 0x9E3779B97F4A7C15ull) >> 57) & (CONVERTED_SLOTS - 1); }
static int converted_vt(uint64_t vt) {
    if (!vt) return 0;
    for (size_t h = converted_slot(vt);; h = (h + 1) & (CONVERTED_SLOTS - 1)) {
        if (g_converted[h] == vt) return 1;
        if (!g_converted[h]) return 0;
    }
}
static int converted_class(uint64_t object) { return !object || converted_vt(read64(object)); }

/* The ribbons and 0x2713 types of the instances run smooth this frame, for the record update: the
 * frame's serial << 48 | the type, a slot of another frame free to take. */
enum { MARK_SLOTS = 1024, MARK_PROBES = 16 };
static const uint64_t MARK_TYPE = 0xffffffffffffull;
static _Atomic uint64_t g_marks[MARK_SLOTS];
static size_t mark_slot(uint64_t type) { return (size_t)(((type >> 3) * 0x9E3779B97F4A7C15ull) >> 54) & (MARK_SLOTS - 1); }
static uint64_t mark_frame(void) { return (uint64_t)(atomic_load_explicit(&g_serial, memory_order_relaxed) & 0xffffu) << 48; }
static int mark(uint64_t type) {
    const uint64_t now = mark_frame(), want = now | (type & MARK_TYPE);
    size_t h = mark_slot(type);
    for (int k = 0; k < MARK_PROBES; ++k, h = (h + 1) & (MARK_SLOTS - 1)) {
        uint64_t w = atomic_load_explicit(&g_marks[h], memory_order_relaxed);
        while ((w & ~MARK_TYPE) != now)
            if (atomic_compare_exchange_weak_explicit(&g_marks[h], &w, want, memory_order_release, memory_order_relaxed))
                return 1;
        if (w == want) return 1;
    }
    return 0;
}
static int marked(uint64_t type) {
    const uint64_t now = mark_frame(), want = now | (type & MARK_TYPE);
    size_t h = mark_slot(type);
    for (int k = 0; k < MARK_PROBES; ++k, h = (h + 1) & (MARK_SLOTS - 1)) {
        const uint64_t w = atomic_load_explicit(&g_marks[h], memory_order_acquire);
        if (w == want) return 1;
        if ((w & ~MARK_TYPE) != now) return 0;
    }
    return 0;
}

/* sub_2c4f0e0's walk: the first child, else the next sibling of the node or its nearest parent. */
static uint64_t node_next(uint64_t node) {
    const uint64_t child = read64(node + NODE_CHILD);
    if (child) return child;
    for (; node; node = read64(node + NODE_PARENT)) {
        const uint64_t sibling = read64(node + NODE_SIBLING);
        if (sibling) return sibling;
    }
    return 0;
}

static int motion_converted(uint64_t motion, int depth, uint64_t *kept) {
    if (!motion) return 1;
    const uint64_t vt = read64(motion);
    if (vt == guest(COMPOSITE)) {
        if (depth < 4)
            return motion_converted(read64(motion + 8), depth + 1, kept) &&
                   motion_converted(read64(motion + 0x10), depth + 1, kept);
    } else if (converted_vt(vt)) {
        return 1;
    }
    *kept = vt;
    return 0;
}

/* The first class of the instance's off the list (its vtable), or 0: each node's motion, its three
 * modules and its pending binders' targets, a GPU record binder's type among them. The ribbons and
 * 0x2713 types go in `marks` (past MARKS, `*count` is MARKS + 1); `*unbound` for a binder whose type
 * the GX side has yet to make. */
enum { MARKS = 16 };
static uint64_t first_unconverted(uint64_t instance, uint64_t *marks, int *count, int *unbound) {
    const uint64_t binder = guest(GX_BINDER), ribbon = guest(RIBBON), t2713 = guest(TYPE_2713);
    for (uint64_t node = read64(instance + INSTANCE_ROOT); node; node = node_next(node)) {
        uint64_t kept = 0;
        if (!motion_converted(read64(node + NODE_MOTION), 0, &kept)) return kept;
        for (uint64_t slot = 0x98; slot <= 0xa8; slot += 8) {
            const uint64_t module = read64(node + slot);
            if (!converted_class(module)) return read64(module);
        }
        for (uint64_t item = read64(node + NODE_CONTAINER + CONTAINER_PENDING); item; item = read64(item + PENDING_NEXT)) {
            const uint64_t target = read64(item + PENDING_TARGET);
            if (!converted_class(target)) return read64(target);
            if (!target || read64(target) != binder) continue;
            const uint64_t holder = read64(target + 0x10);
            const uint64_t type = holder ? read64(holder + 8) : 0;
            if (!type) *unbound = 1;
            if (!converted_class(type)) return read64(type);
            if (type && (read64(type) == ribbon || read64(type) == t2713)) {
                if (*count < MARKS) marks[*count] = type;
                if (*count <= MARKS) ++*count;
            }
        }
    }
    return 0;
}

static int mark_all(uint64_t instance) {
    const uint64_t binder = guest(GX_BINDER), ribbon = guest(RIBBON), t2713 = guest(TYPE_2713);
    for (uint64_t node = read64(instance + INSTANCE_ROOT); node; node = node_next(node))
        for (uint64_t item = read64(node + NODE_CONTAINER + CONTAINER_PENDING); item; item = read64(item + PENDING_NEXT)) {
            const uint64_t target = read64(item + PENDING_TARGET);
            if (!target || read64(target) != binder) continue;
            const uint64_t holder = read64(target + 0x10);
            const uint64_t type = holder ? read64(holder + 8) : 0;
            if (type && (read64(type) == ribbon || read64(type) == t2713) && !mark(type)) return 0;
        }
    return 1;
}

/* An instance's classification stands between whole steps while it keeps its definition, its root
 * node and that node's first child, and every GPU record binder it met had its type: its tree and
 * classes change on whole steps, the GX side's types when they bind. One slot an instance, by
 * address, behind a sequence word (odd while written). */
enum { CLASS_SLOTS = 2048, SLOT_MARKS = 2 };
typedef struct {
    _Alignas(64) atomic_uint seq;
    atomic_uint serial;
    _Atomic uint64_t instance, definition, root, child, kept, marks[SLOT_MARKS];
} ClassSlot;
static ClassSlot g_classes[CLASS_SLOTS];
static ClassSlot *class_slot(uint64_t instance) {
    return &g_classes[(size_t)(((instance >> 4) * 0x9E3779B97F4A7C15ull) >> 53) & (CLASS_SLOTS - 1)];
}

static uint64_t classify(uint64_t instance, uint64_t *marks, int *count) {
    const uint64_t definition = read64(instance + INSTANCE_DEFINITION), root = read64(instance + INSTANCE_ROOT);
    const uint64_t child = root ? read64(root + NODE_CHILD) : 0;
    const unsigned serial = atomic_load_explicit(&g_whole_serial, memory_order_relaxed);
    ClassSlot *slot = class_slot(instance);
    *count = 0;
    if (bb_effect_held()) {
        const unsigned s1 = atomic_load_explicit(&slot->seq, memory_order_acquire);
        if (!(s1 & 1) && atomic_load_explicit(&slot->instance, memory_order_relaxed) == instance &&
            atomic_load_explicit(&slot->serial, memory_order_relaxed) == serial &&
            atomic_load_explicit(&slot->definition, memory_order_relaxed) == definition &&
            atomic_load_explicit(&slot->root, memory_order_relaxed) == root &&
            atomic_load_explicit(&slot->child, memory_order_relaxed) == child) {
            const uint64_t kept = atomic_load_explicit(&slot->kept, memory_order_relaxed);
            uint64_t kept_marks[SLOT_MARKS];
            for (int i = 0; i < SLOT_MARKS; ++i) kept_marks[i] = atomic_load_explicit(&slot->marks[i], memory_order_relaxed);
            atomic_thread_fence(memory_order_acquire);
            if (atomic_load_explicit(&slot->seq, memory_order_relaxed) == s1) {
                for (int i = 0; i < SLOT_MARKS && kept_marks[i]; ++i) marks[(*count)++] = kept_marks[i];
                return kept;
            }
        }
    }
    int unbound = 0;
    const uint64_t kept = first_unconverted(instance, marks, count, &unbound);
    if (unbound || *count > SLOT_MARKS) return kept;
    unsigned s = atomic_load_explicit(&slot->seq, memory_order_relaxed);
    if ((s & 1) || !atomic_compare_exchange_strong_explicit(&slot->seq, &s, s + 1, memory_order_relaxed, memory_order_relaxed))
        return kept;
    atomic_thread_fence(memory_order_release);
    atomic_store_explicit(&slot->instance, instance, memory_order_relaxed);
    atomic_store_explicit(&slot->serial, serial, memory_order_relaxed);
    atomic_store_explicit(&slot->definition, definition, memory_order_relaxed);
    atomic_store_explicit(&slot->root, root, memory_order_relaxed);
    atomic_store_explicit(&slot->child, child, memory_order_relaxed);
    atomic_store_explicit(&slot->kept, kept, memory_order_relaxed);
    for (int i = 0; i < SLOT_MARKS; ++i)
        atomic_store_explicit(&slot->marks[i], !kept && i < *count ? marks[i] : 0, memory_order_relaxed);
    atomic_store_explicit(&slot->seq, s + 2, memory_order_release);
    return kept;
}

/* The instance whose nodes this thread is updating: smooth or not this frame, and its steps for the
 * container calls (the frame's, the carry before and after it, on the manager's and its scales). */
typedef struct {
    uint64_t instance;
    unsigned serial;
    int smooth;
    float frame, from, into;
} Instance;
static _Thread_local Instance t_instance;

static const Instance *smooth_instance(uint64_t instance) {
    const unsigned serial = atomic_load_explicit(&g_serial, memory_order_relaxed);
    Instance *in = &t_instance;
    if (in->instance == instance && in->serial == serial) return in->smooth ? in : NULL;
    in->instance = instance;
    in->serial = serial;
    in->smooth = 0;
    uint64_t marks[MARKS];
    int count = 0;
    if (classify(instance, marks, &count)) return NULL;
    for (int i = 0; i < count && i < MARKS; ++i)
        if (!mark(marks[i])) return NULL;
    if (count > MARKS && !mark_all(instance)) return NULL;
    const uint64_t m = manager();
    const float time_scale = read_float(m + MANAGER_TIME_SCALE), scale = read_float(instance + INSTANCE_SCALE);
    const int still = read8(m + MANAGER_STILL) != 0;
    in->frame = (still ? 0.0f : frame_float(&g_frame) * time_scale) * scale;
    in->from = still ? 0.0f : frame_float(&g_from) * time_scale * scale;
    in->into = still ? 0.0f : frame_float(&g_into) * time_scale * scale;
    in->smooth = 1;
    return in;
}

/* The container call being made for a smooth node (its modules read it): the node, its time at the
 * last whole step and whether the frame has one. */
typedef struct {
    uint64_t node;
    uint32_t time;
    int tick;
} Call;
static _Thread_local Call t_call;

/* The game's node update of a smooth node on a whole step, for its two container calls. */
typedef struct {
    uint64_t node;
    int plain;
    float frame, from, into;
} Node;
static _Thread_local Node t_node;

/* A container call by the frame's step, the node's time (and a plain node's definition time) put
 * `node_offset` (`definition_offset`) past it for the call and back after, unless the call moved
 * them; a time that is the "no time" value stays. */
static void container_call(uint64_t node, float step, uint64_t definition, uint64_t context, float node_offset,
                           float definition_offset, int tick) {
    const uint32_t none = read32(guest(NO_TIME));
    const uint32_t t = read32(node + NODE_TIME), e = read32(node + NODE_DEFINITION_TIME);
    const Call outer = t_call;
    t_call = (Call){node, t, tick};
    const int shift_t = node_offset != 0.0f && t != none, shift_e = definition_offset != 0.0f && e != none;
    uint32_t t_shifted = t, e_shifted = e;
    if (shift_t) {
        write_float(node + NODE_TIME, add_ss(from_bits(t), node_offset));
        t_shifted = read32(node + NODE_TIME);
    }
    if (shift_e) {
        write_float(node + NODE_DEFINITION_TIME, add_ss(from_bits(e), definition_offset));
        e_shifted = read32(node + NODE_DEFINITION_TIME);
    }
    float s = step;
    ((ContainerFn)bb_guest(BB_BN(CONTAINER_UPDATE)))(node + NODE_CONTAINER, &s, definition, context);
    t_call = outer;
    if (shift_t && read32(node + NODE_TIME) == t_shifted) write32(node + NODE_TIME, t);
    if (shift_e && read32(node + NODE_DEFINITION_TIME) == e_shifted) write32(node + NODE_DEFINITION_TIME, e);
}

int bb_smooth_node(uint64_t node, float *step, uint64_t definition, uint64_t context, uint8_t *keep) {
    if (!atomic_load_explicit(&g_split, memory_order_relaxed)) return 0;
    const Instance *in = smooth_instance(read64(node + NODE_INSTANCE));
    if (!in) return 0;
    const float frame = in->frame, from = in->from, into = in->into;
    const uint32_t flags = read32(node + NODE_FLAGS);
    const int plain = !(flags & NODE_STAGED);
    if (!bb_effect_held()) {
        const Node outer = t_node;
        t_node = (Node){node, plain, frame, from, into};
        *keep = ((NodeFn)bb_guest(BB_BN(NODE_UPDATE)))(node, step, definition, context);
        t_node = outer;
        return 1;
    }
    /* Between whole steps: the container calls only; a dead node waits for the whole step. */
    *keep = 1;
    if ((flags & NODE_DEAD) || !(flags & NODE_ACTIVE)) return 1;
    if (plain) container_call(node, frame, definition, context, from, from, 0);
    container_call(node, frame, definition, context, from, plain ? into : 0.0f, 0);
    return 1;
}

static BB_GUEST_ABI void on_container_first(uint64_t container, float *step, uint64_t definition, uint64_t context) {
    const Node n = t_node;
    if (n.node != container - NODE_CONTAINER)
        ((ContainerFn)bb_guest(BB_BN(CONTAINER_UPDATE)))(container, step, definition, context);
    else
        container_call(n.node, n.frame, definition, context, n.from, n.from, 1);
}

static BB_GUEST_ABI void on_container_last(uint64_t container, float *step, uint64_t definition, uint64_t context) {
    const Node n = t_node;
    if (n.node != container - NODE_CONTAINER)
        ((ContainerFn)bb_guest(BB_BN(CONTAINER_UPDATE)))(container, step, definition, context);
    else
        container_call(n.node, n.frame, definition, context, n.from, n.plain ? n.into : 0.0f, 1);
}

/* sub_131e660 counts once a call: its flicker phase (+0x30 adds the age times +0x80) and the blends
 * of modes +0x38 and +0x3c. On a whole step the game's call at the whole step's time counts them;
 * then every frame the call at the frame's time, the rate 0 and a blend as keep, all put back. */
int bb_smooth_light(uint64_t module, uint64_t params, uint64_t context) {
    const Call call = t_call;
    const uint64_t node = read64(module + 8);
    if (!node || call.node != node) return 0;
    const LightFn game = (LightFn)bb_guest(BB_BN(LIGHT_UPDATE));
    if (call.tick) {
        const uint32_t shifted = read32(node + NODE_TIME);
        write32(node + NODE_TIME, call.time);
        game(module, params, context);
        if (read32(node + NODE_TIME) == call.time) write32(node + NODE_TIME, shifted);
    }
    const uint32_t rate = read32(module + LIGHT_RATE), phase = read32(module + LIGHT_PHASE);
    const uint32_t mode = read32(module + LIGHT_MODE), colour_mode = read32(module + LIGHT_COLOUR_MODE);
    write_float(module + LIGHT_RATE, 0.0f);
    if (mode == LIGHT_BLEND) write32(module + LIGHT_MODE, LIGHT_KEEP);
    if (colour_mode == LIGHT_BLEND) write32(module + LIGHT_COLOUR_MODE, LIGHT_KEEP);
    game(module, params, context);
    write32(module + LIGHT_RATE, rate);
    write32(module + LIGHT_MODE, mode);
    write32(module + LIGHT_COLOUR_MODE, colour_mode);
    write32(module + LIGHT_PHASE, phase);
    return 1;
}

/* A smooth node's following wobble between whole steps: the game's update, which follows a share of
 * the parent's move, its period at its largest and its count put back (its end, the wobble's own
 * update, is the gate's hold too). */
int bb_smooth_follow(uint64_t motion, uint64_t node, const float *step, uint64_t local) {
    if (!node || t_call.node != node) return 0;
    const uint32_t count = read32(motion + FOLLOW_COUNT), period = read32(motion + FOLLOW_PERIOD);
    write32(motion + FOLLOW_PERIOD, 0xffffffffu);
    ((MotionFn)bb_guest(BB_BN(FOLLOW)))(motion, node, step, local);
    write32(motion + FOLLOW_PERIOD, period);
    write32(motion + FOLLOW_COUNT, count);
    return 1;
}

/* A record's item of a smooth instance on a frame with a whole step: its step is the frame's on the
 * manager's and the instance's scales (a held instance's is the whole step's). */
static int smooth_item(uint64_t record, float step, float *time_scale, float *scale) {
    const uint64_t node = read64(record + RECORD_NODE), m = manager();
    const uint64_t instance = node ? read64(node + NODE_INSTANCE) : 0;
    if (!instance || !m || read8(m + MANAGER_STILL)) return 0;
    *time_scale = read_float(m + MANAGER_TIME_SCALE);
    *scale = read_float(instance + INSTANCE_SCALE);
    return bits(frame_float(&g_frame) * *time_scale * *scale) == bits(step);
}

/* sub_2ec1e00 at its record's time alone: it lets go of old points, draws the points from the last
 * kept one to the emitter again, and once its interval (+0x88) has passed inserts them, shifts its
 * places and draws the FX RNG; with smoothing (+0x98) every point moves toward the next. With a
 * copy of its definition whose interval is infinite and smoothing 0: only the drawn points. */
static void ribbon_drawn(RecordFn game, uint64_t record, uint64_t item, uint64_t type) {
    const uint64_t definition = read64(type + TYPE_DEFINITION);
    _Alignas(16) unsigned char copy[0x130];
    memcpy(copy, (const void *)(uintptr_t)definition, RIBBON_DEFINITION);
    const uint64_t at = (uint64_t)(uintptr_t)copy;
    write32(at + RIBBON_INTERVAL, 0x7f800000u);
    write32(at + RIBBON_SMOOTHING, 0);
    write64(type + TYPE_DEFINITION, at);
    game(record, item);
    if (read64(type + TYPE_DEFINITION) == at) write64(type + TYPE_DEFINITION, definition);
}

/* Between whole steps the drawn points to the emitter at the frame's time; on a frame with one the
 * game's call at the whole step's time and place (the step less the carry past it, the emitter's
 * rows that far between the record's last and the item's), then on to the frame's as between. */
static int smooth_ribbon(RecordFn game, uint64_t record, uint64_t item, uint64_t type) {
    const float step = read_float(item + ITEM_STEP);
    if (!marked(type) || !(step > 0.0f)) return 0;
    if (bb_effect_held()) {
        ribbon_drawn(game, record, item, type);
        return 1;
    }
    float time_scale, scale;
    if (!smooth_item(record, step, &time_scale, &scale)) return 0;
    const float into = frame_float(&g_into) * time_scale * scale;
    if (!(into > 0.0f) || !(into < step)) {
        game(record, item);
        return 1;
    }
    const uint32_t before = read32(record + RECORD_TIME);
    const float share = (step - into) / step;
    float rows[12];
    memcpy(rows, (const void *)(uintptr_t)item, sizeof(rows));
    for (int i = 0; i < 12; ++i) {
        const float last = read_float(record + RECORD_ROWS + 4 * (uint64_t)i);
        write_float(item + 4 * (uint64_t)i, last + (rows[i] - last) * share);
    }
    write_float(item + ITEM_STEP, step - into);
    game(record, item);
    memcpy((void *)(uintptr_t)item, rows, sizeof(rows));
    write_float(item + ITEM_STEP, into);
    ribbon_drawn(game, record, item, type);
    write32(record + RECORD_PREVIOUS, before);
    write_float(record + RECORD_TIME, add_ss(from_bits(before), step));
    write_float(item + ITEM_STEP, step);
    return 1;
}

/* The next float up or down from a finite x, by its bits. */
static float ulp_toward(float x, int up) {
    uint32_t b = bits(x);
    if (!(b & 0x7fffffffu)) return from_bits(up ? 1u : 0x80000001u);
    const int positive = !(b & 0x80000000u);
    b = positive == up ? b + 1 : b - 1;
    return from_bits(b);
}

/* Type 0x2713 reads its five curves at the record's elapsed time, and its draw again: the game's call
 * with the whole step on the instance's scales, then the record's times as the frame's step leaves
 * them, the previous one where the draw reads the same elapsed time. */
static int smooth_2713(RecordFn game, uint64_t record, uint64_t item, uint64_t type) {
    const uint64_t node = read64(record + RECORD_NODE), m = manager();
    const uint64_t instance = node ? read64(node + NODE_INSTANCE) : 0;
    const float step = read_float(item + ITEM_STEP);
    if (!marked(type) || !m || !instance || !(step > 0.0f)) return 0;
    const float whole = BB_EFFECT_WHOLE_STEP * read_float(m + MANAGER_TIME_SCALE) * read_float(instance + INSTANCE_SCALE);
    const float before = read_float(record + RECORD_TIME);
    write_float(item + ITEM_STEP, whole);
    game(record, item);
    write_float(item + ITEM_STEP, step);
    const float elapsed = sub_ss(read_float(record + RECORD_TIME), before), now = add_ss(before, step);
    float previous = sub_ss(now, elapsed);
    for (int k = 0; k < 8 && sub_ss(now, previous) != elapsed; ++k) previous = ulp_toward(previous, sub_ss(now, previous) > elapsed);
    write_float(record + RECORD_PREVIOUS, previous);
    write_float(record + RECORD_TIME, now);
    return 1;
}

/* StandardParticle's and Spark's simulations (sub_13040b0, sub_12fef10, on the type +0x6b0) count
 * their emission in updates: events for each interval (+0x3888) the timer (+0x3880) holds, an
 * update's cap past which the timer is dropped, the total times the wind's share (+0x3940) truncated
 * once (+0x3878), the end time (+0x2540) and the events' limit (+0x2620) checked at an update's start.
 * A smooth instance's update counts toward a window, the whole step its emitter's own time falls in:
 * each frame emits what the window's total would in one update, less what the window emitted. */
enum { SIMULATION = 0x6b0, SIM_EVENTS_LIMIT = 0x2620, SIM_LIMIT_MODE = 0x261c, SIM_UNLIMITED = 0x253c,
       SIM_END = 0x2540, SIM_COUNT_HIGH = 0x25e4, SIM_COUNT_ADD = 0x25dc, SIM_CAP_LIMIT = 0x2890,
       SIM_SHARE_LOW = 0x29a8, SIM_SHARE_HIGH = 0x29ac, SIM_CAP_ADD = 0x29c4, SIM_LIMIT_COPY = 0x3811,
       SIM_LIMIT_COPIED = 0x3860, SIM_LIMIT_COPY_1 = 0x2cb0, SIM_LIMIT_COPY_2 = 0x3340, SIM_ON = 0x3872,
       SIM_EMIT = 0x3878, SIM_TIME = 0x387c, SIM_TIMER = 0x3880, SIM_EVENTS = 0x3884, SIM_INTERVAL = 0x3888,
       SIM_SHARE = 0x3940 };

typedef struct {
    _Alignas(64) _Atomic uint64_t simulation;
    atomic_uint touched; /* g_serial when last taken */
    atomic_uint busy;
    double time;         /* the emitter's smooth steps since its slot began */
    float total;         /* its own time after its last update */
    int64_t window;
    int32_t counts, emitted, cap;
    int32_t events;      /* its events as its window began */
    uint32_t interval;   /* the window's interval */
    uint32_t rolled;     /* the interval its last update with events drew */
    uint8_t open, capped, counted, ended, drew;
} EmitSlot;
enum { EMIT_SLOTS = 4096, EMIT_PROBES = 8, EMIT_STALE = 32 };
static EmitSlot g_emit[EMIT_SLOTS];

/* The emitter's slot for this call: its own, a free one or one 32 frames untouched; NULL past eight. */
static EmitSlot *emit_slot(uint64_t simulation) {
    const unsigned now = atomic_load_explicit(&g_serial, memory_order_relaxed);
    size_t h = (size_t)(((simulation >> 4) * 0x9E3779B97F4A7C15ull) >> 52) & (EMIT_SLOTS - 1);
    for (int k = 0; k < EMIT_PROBES; ++k, h = (h + 1) & (EMIT_SLOTS - 1)) {
        EmitSlot *s = &g_emit[h];
        const uint64_t owner = atomic_load_explicit(&s->simulation, memory_order_relaxed);
        if (owner != simulation && owner && now - atomic_load_explicit(&s->touched, memory_order_relaxed) < EMIT_STALE)
            continue;
        if (atomic_exchange_explicit(&s->busy, 1, memory_order_acquire)) continue;
        const uint64_t o = atomic_load_explicit(&s->simulation, memory_order_relaxed);
        if (o != simulation) {
            if (o && now - atomic_load_explicit(&s->touched, memory_order_relaxed) < EMIT_STALE) {
                atomic_store_explicit(&s->busy, 0, memory_order_release);
                continue;
            }
            atomic_store_explicit(&s->simulation, simulation, memory_order_relaxed);
            s->open = 0;
            s->window = -1;
        }
        atomic_store_explicit(&s->touched, now, memory_order_relaxed);
        return s;
    }
    return NULL;
}

/* An update's cap from its emitter's fields (0x1304a19..0x1304acb), the game's comparisons. */
static int32_t emission_cap(uint64_t sim) {
    const int32_t high = read_s32(sim + SIM_COUNT_HIGH);
    const uint32_t sum = (uint32_t)read_s32(sim + SIM_CAP_ADD) + (uint32_t)read_s32(sim + SIM_COUNT_ADD) +
                         (uint32_t)(high >= 0 ? high : 0);
    const float a = read_float(sim + SIM_SHARE_LOW), b = read_float(sim + SIM_SHARE_HIGH);
    const float f = a > b ? a : b;
    const double factor = 1.0f > f ? 1.0 : (double)(f > 50.0f ? 50.0f : f);
    double x = (double)(int32_t)sum;
    x = x + x;
    const int32_t r = _mm_cvttsd_si32(_mm_set_sd(x * factor));
    if (r < 4) return 20;
    const int32_t limit = read_s32(sim + SIM_CAP_LIMIT);
    return (r > limit ? limit : r) + 16;
}

/* What one update emits of a total (0x1304d8c..0x1304daf). */
static int32_t emission_of(int32_t total, float share, int32_t cap) {
    const int32_t e = _mm_cvttss_si32(_mm_set_ss((float)total * share));
    return e < 0 ? 0 : (e > cap ? cap : e);
}

static void emit_release(EmitSlot *slot, uint64_t sim) {
    slot->total = read_float(sim + SIM_TIME);
    atomic_store_explicit(&slot->busy, 0, memory_order_release);
}

static int emission_window(RecordFn game, uint64_t record, uint64_t item, uint64_t type) {
    const float step = read_float(item + ITEM_STEP);
    float time_scale, scale;
    if (!(step > 0.0f) || !smooth_item(record, step, &time_scale, &scale)) return 0;
    const float whole = BB_EFFECT_WHOLE_STEP * time_scale * scale;
    if (!(whole > 0.0f)) return 0;
    const uint64_t sim = type + SIMULATION;
    EmitSlot *slot = emit_slot(sim);
    if (!slot) return 0;
    /* The window: the whole step this update's end falls in, of the emitter's smooth steps since it
     * began; a time that went back (another emitter at the address) begins them again. */
    const float own_time = read_float(sim + SIM_TIME);
    const int begun = !slot->open || own_time < slot->total;
    if (begun) slot->time = 0;
    const double time_end = slot->time + (double)step;
    const double at = time_end / (double)whole - 1e-4;
    const int64_t window = at > 0.0 ? (int64_t)at : 0;
    const double to_end = (double)(window + 1) * (double)whole - slot->time;
    slot->time = time_end;
    if (begun || slot->window != window) {
        /* 30's update re-rolls the interval after its step's events: the next window takes that. */
        if (!begun && slot->drew) write32(sim + SIM_INTERVAL, slot->rolled);
        slot->open = 1;
        slot->window = window;
        slot->counts = slot->emitted = slot->cap = 0;
        slot->capped = slot->counted = slot->ended = slot->drew = 0;
        slot->events = read_s32(sim + SIM_EVENTS);
        slot->interval = read32(sim + SIM_INTERVAL);
    }
    if (slot->capped || slot->ended) {
        /* Nothing more this window, the timer as the cap left it. */
        const uint8_t on = read8(sim + SIM_ON);
        write8(sim + SIM_ON, 0);
        game(record, item);
        const int ended = slot->ended || (read32(sim + SIM_UNLIMITED) == 0 && !(read_float(sim + SIM_TIME) < read_float(sim + SIM_END)));
        write8(sim + SIM_ON, ended ? 0 : on);
        if (slot->capped) write_float(sim + SIM_TIMER, 0.0f);
        emit_release(slot, sim);
        return 1;
    }
    const float share = read_float(sim + SIM_SHARE);
    const int32_t limit = read_s32(sim + SIM_CAP_LIMIT), addend = read_s32(sim + SIM_CAP_ADD);
    const int later = slot->counted != 0;
    int32_t left = 0;
    /* The window's later frames: the cap it has left (16 + min(int(2 x (2^23 + ...) x f), left - 16),
     * the formula's own way to it) and, when its first update began with events to go, no stop at the
     * events' limit (nor the definition's copy of it). */
    uint64_t limit_at[2] = {SIM_EVENTS_LIMIT, SIM_EVENTS_LIMIT};
    int32_t limit_was[2] = {0, 0};
    const uint8_t mode = read8(sim + SIM_LIMIT_COPIED) ? read8(sim + SIM_LIMIT_COPY) : 0;
    if (mode == 1) limit_at[1] = SIM_LIMIT_COPY_1;
    if (mode == 2) limit_at[1] = SIM_LIMIT_COPY_2;
    write_float(sim + SIM_SHARE, 1.0f);
    if (slot->drew) write32(sim + SIM_INTERVAL, slot->interval);
    if (later) {
        left = slot->cap - slot->counts;
        write32(sim + SIM_CAP_ADD, 0x800000);
        write32(sim + SIM_CAP_LIMIT, (uint32_t)(left - 16));
        if (slot->counted == 2)
            for (int i = 0; i < 2; ++i) {
                limit_was[i] = read_s32(sim + limit_at[i]);
                write32(sim + limit_at[i], 0x7fffffff);
            }
    }
    const uint32_t timer = read32(sim + SIM_TIMER), events = read32(sim + SIM_EVENTS), interval = read32(sim + SIM_INTERVAL);
    game(record, item);
    const int32_t n = read_s32(sim + SIM_EMIT);
    write_float(sim + SIM_SHARE, share);
    if (read32(sim + SIM_EVENTS) != events) {
        slot->drew = 1;
        slot->rolled = read32(sim + SIM_INTERVAL);
    }
    if (later) {
        write32(sim + SIM_CAP_ADD, (uint32_t)addend);
        write32(sim + SIM_CAP_LIMIT, (uint32_t)limit);
        if (slot->counted == 2)
            for (int i = 1; i >= 0; --i) write32(sim + limit_at[i], (uint32_t)limit_was[i]);
    } else {
        /* The window's first update: the whole step's limits as the fields hold them. An end time the
         * whole step reaches stops the emitter at its update, nothing emitted. */
        left = slot->cap = emission_cap(sim);
        const int limits = read32(sim + SIM_UNLIMITED) == 0;
        const float end = (float)((double)own_time + to_end);
        if (limits && !(end < read_float(sim + SIM_END))) {
            write32(sim + SIM_TIMER, bits(add_ss(from_bits(timer), step)));
            write32(sim + SIM_EVENTS, events);
            write32(sim + SIM_INTERVAL, interval);
            write32(sim + SIM_EMIT, 0);
            write8(sim + SIM_ON, 0);
            slot->ended = 1;
            slot->drew = 0;
            emit_release(slot, sim);
            return 1;
        }
        slot->counted = limits && read32(sim + SIM_LIMIT_MODE) == 1 && read_s32(sim + SIM_EVENTS_LIMIT) > slot->events ? 2 : 1;
    }
    const int32_t total = slot->counts + n;
    const int32_t want = emission_of(total, share, slot->cap);
    const int32_t emit = want > slot->emitted ? want - slot->emitted : 0;
    write32(sim + SIM_EMIT, (uint32_t)emit);
    slot->counts = total;
    slot->emitted += emit;
    if (n > 0 && n >= left) slot->capped = 1;
    emit_release(slot, sim);
    return 1;
}

int bb_smooth_record(uint64_t record, uint64_t item) {
    if (!atomic_load_explicit(&g_split, memory_order_relaxed)) return 0;
    const uint64_t type = read64(record + RECORD_TYPE);
    if (!type) return 0;
    const RecordFn game = (RecordFn)bb_guest(BB_BN(RECORD_UPDATE));
    const uint64_t vt = read64(type);
    if (vt == guest(RIBBON)) return smooth_ribbon(game, record, item, type);
    if (vt == guest(TYPE_2713)) return smooth_2713(game, record, item, type);
    if (vt == guest(STANDARD) || vt == guest(SPARK)) return emission_window(game, record, item, type);
    return 0;
}

/* sub_1314660 steps every wind source (sub_2d552d0: its last step, age and gust phase; nothing
 * counted) with the manager's step on its time scale: the frame's own instead. */
static BB_GUEST_ABI void on_wind_sources(uint64_t registry, float step) {
    if (t_update) step = frame_float(&g_frame) * read_float(manager() + MANAGER_TIME_SCALE);
    ((StepFn)bb_guest(BB_BN(WIND_SOURCES)))(registry, step);
}

/* sub_12e5500 fades the GX lights of ended FFX lights by the step on the manager's scale, 0 when it
 * is still: the frame's own instead. */
static BB_GUEST_ABI void on_light_fades(uint64_t list, float step) {
    if (t_update) {
        const uint64_t m = list - MANAGER_FADES;
        step = read8(m + MANAGER_STILL) ? 0.0f : frame_float(&g_frame) * read_float(m + MANAGER_TIME_SCALE);
    }
    ((StepFn)bb_guest(BB_BN(LIGHT_FADES)))(list, step);
}

void bb_smooth_begin(uint64_t m, const BbEffectFrame *frame) {
    /* The marks' serial wraps at 16 bits: the table wiped, 0 skipped. */
    unsigned serial = atomic_load_explicit(&g_serial, memory_order_relaxed) + 1;
    if (!(serial & 0xffffu)) {
        for (size_t i = 0; i < MARK_SLOTS; ++i) atomic_store_explicit(&g_marks[i], 0, memory_order_relaxed);
        ++serial;
    }
    atomic_store_explicit(&g_serial, serial, memory_order_relaxed);
    if (!frame->between) atomic_fetch_add_explicit(&g_whole_serial, 1, memory_order_relaxed);
    atomic_store_explicit(&g_manager, m, memory_order_relaxed);
    atomic_store_explicit(&g_frame, bits(frame->frame), memory_order_relaxed);
    atomic_store_explicit(&g_from, bits(frame->from), memory_order_relaxed);
    atomic_store_explicit(&g_into, bits(frame->into), memory_order_relaxed);
    const int split = atomic_load_explicit(&g_on, memory_order_relaxed) && frame->split;
    atomic_store_explicit(&g_split, split, memory_order_relaxed);
    t_update = split;
}

void bb_smooth_end(void) { t_update = 0; }

static int calls_to(uint64_t at, uint64_t target) {
    const unsigned char *site = bb_guest(BB_BN(at));
    int32_t rel;
    memcpy(&rel, site + 1, 4);
    return site[0] == 0xe8 && BB_BN(at) + 5 + (int64_t)rel == BB_BN(target);
}

static uint64_t unexpected(void) {
    for (size_t i = 0; i < sizeof(CLASSES) / sizeof(*CLASSES); ++i) {
        if (read64(guest(CLASSES[i].vtable) + CLASSES[i].slot) != guest(CLASSES[i].update)) return CLASSES[i].vtable;
        if (!bb_code_is(bb_guest(BB_BN(CLASSES[i].update)), CLASSES[i].code)) return CLASSES[i].update;
    }
    for (size_t i = 0; i < sizeof(CODE) / sizeof(*CODE); ++i)
        if (!bb_code_is(bb_guest(BB_BN(CODE[i].at)), CODE[i].code)) return CODE[i].at;
    for (size_t i = 0; i < sizeof(SLOTS) / sizeof(*SLOTS); ++i)
        if (read64(guest(SLOTS[i].slot)) != guest(SLOTS[i].target)) return SLOTS[i].slot;
    if (!calls_to(CONTAINER_FIRST, CONTAINER_UPDATE)) return CONTAINER_FIRST;
    if (!calls_to(CONTAINER_LAST, CONTAINER_UPDATE)) return CONTAINER_LAST;
    if (!calls_to(WIND_CALL, WIND_SOURCES)) return WIND_CALL;
    if (!calls_to(FADES_CALL, LIGHT_FADES)) return FADES_CALL;
    return 0;
}

int bb_smooth_wanted(void) {
    const char *env = getenv("BB_EFFECT_SMOOTH");
    if (env && !strcmp(env, "0")) {
        puts("Effect smooth steps: off, every effect in whole steps (BB_EFFECT_SMOOTH=0)");
        return 0;
    }
    const uint64_t site = unexpected();
    if (site) {
        printf("Effect smooth steps: off, every effect in whole steps (unexpected code at %#llx)\n",
               (unsigned long long)site);
        return 0;
    }
    return 1;
}

int bb_smooth_install(void) {
    memset(g_converted, 0, sizeof(g_converted));
    for (size_t i = 0; i < sizeof(CLASSES) / sizeof(*CLASSES); ++i) {
        const uint64_t vt = guest(CLASSES[i].vtable);
        size_t h = converted_slot(vt);
        while (g_converted[h] && g_converted[h] != vt) h = (h + 1) & (CONVERTED_SLOTS - 1);
        g_converted[h] = vt;
    }
    int hooks = 0;
    hooks += !bb_hook_call(BB_BN(CONTAINER_FIRST), BB_BN(CONTAINER_UPDATE), (void *)on_container_first);
    hooks += !bb_hook_call(BB_BN(CONTAINER_LAST), BB_BN(CONTAINER_UPDATE), (void *)on_container_last);
    hooks += !bb_hook_call(BB_BN(WIND_CALL), BB_BN(WIND_SOURCES), (void *)on_wind_sources);
    hooks += !bb_hook_call(BB_BN(FADES_CALL), BB_BN(LIGHT_FADES), (void *)on_light_fades);
    if (hooks != 4) return -1;
    atomic_store(&g_on, 1);
    return hooks;
}
