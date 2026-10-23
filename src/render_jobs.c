/* SPDX-License-Identifier: GPL-2.0-or-later
 * Laurence's cinematic above 30 FPS (#149: "SRT walker read an unmapped resource table", then a
 * device lost).
 *
 * Render jobs run with a slot from a pool of six (sub_1056920 takes one, sleeping until one is
 * free; sub_1056990 gives it back). The job runner's step (sub_1067f60) takes a slot into
 * [runner+0x120], checks the job's resource, runs it and gives the slot back, but its two error
 * exits leave through the shared epilogue (0x1068092) still holding it, and the runner's destroy
 * and reset (0x106798a, 0x1067a5c) clear the pointer without giving it back. Each failed job
 * loses a slot for good; once all six are gone every thread that needs one sleeps for ever.
 * Here the held slot goes back to the pool at those three places.
 *
 * The runs fail (error 9 from sub_2169c30) when the graphics manager's render resource cache
 * (made in sub_216b0f0), a range heap over one 160 MiB block, fills up at high frame rates:
 * requests of 20-40 KiB fail and leave resource tables unwritten. Right after the block is
 * allocated (0x216b21d) the cache gets 512 MiB of the port's own direct memory instead
 * (runtime_memory_port_map). The game's 160 MiB stays allocated and unused, so the game's heaps
 * keep their layout: taking the larger block from the game's allocator starved the memory areas
 * load into (map pieces missing after travelling to the Hunter's Dream and back).
 *
 * BB_JOB_SLOT_FIX=0: slots as the game has them. BB_RENDER_RESOURCE_CACHE_MB: the cache's size,
 * 160 (the game's, nothing changed) to 512 (the default).
 *
 * After deadinside28/bloodborne_pc 0.6 (8185b88). Addresses are image offsets (eboot virtual
 * address; Binary Ninja's minus 0x400000). */
#include "render_jobs.h"
#include "engine_hooks.h"
#include "runtime.h"

#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum {
    SLOT_GIVE_BACK = 0x1056990, /* (pool, slot) */
    SLOT_POOL = 0x1057350,      /* () -> the pool */
    STEP_RELEASE = 0x1068075,   /* the step's success path giving the slot back, then */
    STEP_EXIT = 0x1068092,      /* its shared epilogue: r14 the runner, r12 the pool, r15d the result */
    RUNNER_DESTROY = 0x106798a, /* mov qword [rbx+0x120], 0, rbx the runner */
    RUNNER_RESET = 0x1067a5c,
    CACHE_ALLOCATE = 0x216b20e, /* allocator->Allocate([r14+0x54], 16), r14 the cache's parameters */
    CACHE_BACKING = 0x216b21d,  /* just after it, the block in rax */
};
enum { RUNNER_SLOT = 0x120, PARAMS_CACHE_SIZE = 0x54, STEP_FAILED = 1, RUNNER_CONTEXT = 11 };
enum { GAME_CACHE_MB = 160, CACHE_MB = 512, CACHE_ALIGNMENT = 64 << 10 };

static const BbCode give_back_entry = {13, 0xcd926b5dd12be449ull};
static const BbCode pool_getter = {8, 0x18617228569ca3bdull};
static const BbCode step_release = {29, 0xe68aa040c9907512ull};
static const BbCode step_exit = {7, 0x55404848d9076ba9ull};
static const BbCode runner_clear = {11, 0x6b18ed14b8cfb06eull};
/* The clear with the instructions around it: [rbx+0x110] cleared before, the job read after. */
static const BbCode runner_context = {29, 0x36452d18eaf1b48cull};
static const BbCode cache_allocate = {15, 0x7a2f91d52cd6cb16ull};
static const BbCode cache_backing = {7, 0x89105bf8804bfc27ull};

typedef void (BB_GUEST_ABI *GiveBackFn)(uint64_t pool, uint64_t slot);
typedef uint64_t (BB_GUEST_ABI *PoolFn)(void);

static atomic_uint g_given_back;
static uint32_t g_cache_bytes;

/* Read through bb_read, so a smaller image of another version is refused rather than faulting. */
static int code_at(uint64_t at, BbCode code) {
    unsigned char bytes[32];
    return code.n <= sizeof(bytes) && bb_read((uint64_t)(uintptr_t)bb_guest(at), bytes, code.n) &&
           bb_code_is(bytes, code);
}

static void give_back(uint64_t pool, uint64_t runner, const char *holder) {
    uint64_t *held = (uint64_t *)(uintptr_t)(runner + RUNNER_SLOT);
    const uint64_t slot = *held;
    if (!pool || !slot) return;
    ((GiveBackFn)bb_guest(SLOT_GIVE_BACK))(pool, slot);
    *held = 0;
    const unsigned n = atomic_fetch_add(&g_given_back, 1) + 1;
    if (n <= 5 || !(n & (n - 1))) {
        printf("Render jobs: the slot of %s went back to the pool (%u so far)\n", holder, n);
        fflush(stdout);
    }
}

static BB_GUEST_ABI void on_step_exit(BbRegs *r) {
    if ((uint32_t)r->r15 == STEP_FAILED) give_back(r->r12, r->r14, "a failed job");
}

static BB_GUEST_ABI void on_runner_clear(BbRegs *r) {
    give_back(((PoolFn)bb_guest(SLOT_POOL))(), r->rbx, "a runner destroyed or reset");
}

static BB_GUEST_ABI void on_cache_backing(BbRegs *r) {
    uint32_t size = 0;
    if (!r->rax || !bb_read(r->r14 + PARAMS_CACHE_SIZE, &size, sizeof(size)) ||
        size != (uint32_t)GAME_CACHE_MB << 20)
        return;
    void *block = NULL;
    const int error = runtime_memory_port_map(g_cache_bytes, CACHE_ALIGNMENT, &block);
    if (error || !block) {
        printf("Render resource cache: no port memory for %u MiB (error 0x%x), the game's %d MiB\n",
               g_cache_bytes >> 20, (unsigned)error, GAME_CACHE_MB);
        fflush(stdout);
        return;
    }
    /* The range heap is set up over the block with the parameters' size a few instructions on. */
    memcpy((void *)(uintptr_t)(r->r14 + PARAMS_CACHE_SIZE), &g_cache_bytes, sizeof(g_cache_bytes));
    r->rax = (uint64_t)(uintptr_t)block;
    printf("Render resource cache: %u MiB of the port's memory at %p (the game's %d MiB stays "
           "allocated, unused)\n", g_cache_bytes >> 20, block, GAME_CACHE_MB);
    fflush(stdout);
}

static int slots_install(const char **state) {
    const char *env = getenv("BB_JOB_SLOT_FIX");
    if (env && !strcmp(env, "0")) {
        *state = "slots as the game has them (BB_JOB_SLOT_FIX=0)";
        return 0;
    }
    if (!code_at(SLOT_GIVE_BACK, give_back_entry) || !code_at(SLOT_POOL, pool_getter) ||
        !code_at(STEP_RELEASE, step_release) || !code_at(STEP_EXIT, step_exit) ||
        !code_at(RUNNER_DESTROY - RUNNER_CONTEXT, runner_context) ||
        !code_at(RUNNER_RESET - RUNNER_CONTEXT, runner_context)) {
        *state = "slots as the game has them (unexpected code)";
        return 0;
    }
    int hooks = !bb_hook_mid(STEP_EXIT, step_exit, on_step_exit);
    hooks += !bb_hook_mid(RUNNER_DESTROY, runner_clear, on_runner_clear);
    hooks += !bb_hook_mid(RUNNER_RESET, runner_clear, on_runner_clear);
    *state = hooks == 3 ? "slots given back by failed jobs" : "slots given back at some exits only";
    return hooks;
}

static int cache_install(char *state, size_t n) {
    const char *env = getenv("BB_RENDER_RESOURCE_CACHE_MB");
    long mb = env && *env ? strtol(env, NULL, 10) : CACHE_MB;
    if (mb > CACHE_MB) mb = CACHE_MB;
    const char *why = NULL;
    if (mb <= GAME_CACHE_MB) why = "BB_RENDER_RESOURCE_CACHE_MB";
    else if (!code_at(CACHE_ALLOCATE, cache_allocate) || !code_at(CACHE_BACKING, cache_backing))
        why = "unexpected code";
    else if (runtime_memory_port_reserve((uint64_t)mb << 20))
        why = "guest memory already set up";
    else if (bb_hook_mid(CACHE_BACKING, cache_backing, on_cache_backing)) {
        runtime_memory_port_reserve(0);
        why = bb_hooks_error();
    }
    if (why) {
        snprintf(state, n, "resource cache at the game's %d MiB (%s)", GAME_CACHE_MB, why);
        return 0;
    }
    g_cache_bytes = (uint32_t)mb << 20;
    snprintf(state, n, "resource cache %ld MiB of the port's memory", mb);
    return 1;
}

int bb_render_jobs_install(void) {
    const char *slots = "";
    char cache[128];
    const int hooks = slots_install(&slots) + cache_install(cache, sizeof(cache));
    printf("Render jobs: %s; %s\n", slots, cache);
    return hooks;
}
