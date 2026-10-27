/* SPDX-License-Identifier: GPL-2.0-or-later
 * render_jobs.c on an image holding the game's code at its sites (game_code.h): every site is
 * recognised in the 1.09 eboot; a failed job's exit and a runner's destroy give the held slot back
 * through the game's pool getter; a successful exit gives nothing; the cache gets the port's block
 * and its size; the switches and a changed byte leave the image as it was. Re-runs itself for the
 * cases that need another environment. */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>
#include "engine_hooks.h"
#include "game_code.h"
#include "render_jobs.h"
#include "runtime.h"

enum {
    GIVE_BACK = 0x1056990, POOL_GETTER = 0x1057350, POOL_GLOBAL = 0x54b8788,
    DESTROY = 0x106798a, RESET = 0x1067a5c, STEP_EXIT = 0x1068092, CACHE = 0x216b21d,
    IMAGE_SIZE = 0x54c0000,
};
static const uint64_t FAKE_POOL = 0x1234560000ull, FAKE_SLOT = 0x2345670000ull;
static void *const PORT_BLOCK = (void *)(uintptr_t)0x3456780000ull;

/* runtime_memory.c's side, as render_jobs.c calls it. */
static uint64_t reserved;
static unsigned port_maps;
int runtime_memory_port_reserve(uint64_t size) {
    reserved = size;
    return 0;
}
int runtime_memory_port_map(uint64_t size, uint64_t alignment, void **out) {
    assert(size == reserved && alignment == 64 << 10);
    ++port_maps;
    *out = PORT_BLOCK;
    return 0;
}

static uint64_t given_pool, given_slot;
static unsigned gives;
static BB_GUEST_ABI void fake_give_back(uint64_t pool, uint64_t slot) {
    given_pool = pool;
    given_slot = slot;
    ++gives;
}

static unsigned char *image;
static void place(void) {
    static const struct { uint64_t at, n; } code[] = {
        {0x1056990, 0x10}, {0x1057350, 8}, {0x1067970, 0x30}, {0x1067a40, 0x30},
        {0x1068060, 0x40}, {0x216b200, 0x30},
    };
    for (size_t i = 0; i < sizeof(code) / sizeof(*code); ++i) bb_test_place_game_code(image, code[i].at, code[i].n);
}
static void put(uint64_t at, const void *bytes, size_t n) { memcpy(image + at, bytes, n); }
static int hooked(uint64_t at) { return image[at] == 0xe9; }

/* sysv thunks that enter a hooked site with the game's registers; the code after it is a ret. */
static unsigned char *thunks;
typedef void (BB_GUEST_ABI *ExitFn)(uint64_t runner, uint64_t pool, uint64_t result, void *frame);
typedef void (BB_GUEST_ABI *ClearFn)(uint64_t runner);
typedef uint64_t (BB_GUEST_ABI *CacheFn)(void *cache, void *params, uint64_t block);
static unsigned char *thunk(size_t offset, const unsigned char *head, size_t n, uint64_t site,
                            const unsigned char *tail, size_t m) {
    unsigned char *p = thunks + offset, *start = p;
    memcpy(p, head, n), p += n;
    const uint64_t target = (uint64_t)(uintptr_t)(image + site);
    *p++ = 0x49, *p++ = 0xbb, memcpy(p, &target, 8), p += 8;  /* movabs r11, site */
    *p++ = 0x41, *p++ = 0xff, *p++ = 0xd3;                    /* call r11 */
    memcpy(p, tail, m);
    return start;
}

static void behaviour(void) {
    bb_hooks_seal();
    const unsigned char ret = 0xc3;
    put(STEP_EXIT + 7, &ret, 1);
    put(DESTROY + 11, &ret, 1);
    put(CACHE + 7, &ret, 1);
    unsigned char jump[12] = {0x48, 0xb8};  /* movabs rax, fake_give_back; jmp rax */
    const uint64_t fake = (uint64_t)(uintptr_t)fake_give_back;
    memcpy(jump + 2, &fake, 8), jump[10] = 0xff, jump[11] = 0xe0;
    put(GIVE_BACK, jump, sizeof(jump));
    memcpy(image + POOL_GLOBAL, &FAKE_POOL, 8);
    thunks = VirtualAlloc(NULL, 4096, MEM_RESERVE | MEM_COMMIT, PAGE_EXECUTE_READWRITE);
    assert(thunks);
    /* push rbp rbx r12 r14 r15; r14 rdi, r12 rsi, r15 rdx, rbx rcx, rbp rcx+0x30 */
    static const unsigned char exit_head[] = {0x55, 0x53, 0x41, 0x54, 0x41, 0x56, 0x41, 0x57, 0x49, 0x89, 0xfe,
                                              0x49, 0x89, 0xf4, 0x49, 0x89, 0xd7, 0x48, 0x89, 0xcb, 0x48, 0x8d, 0x69, 0x30};
    static const unsigned char exit_tail[] = {0x41, 0x5f, 0x41, 0x5e, 0x41, 0x5c, 0x5b, 0x5d, 0xc3};
    static const unsigned char clear_head[] = {0x53, 0x48, 0x89, 0xfb};  /* push rbx; mov rbx, rdi */
    static const unsigned char clear_tail[] = {0x5b, 0xc3};
    /* push rbx r14 r15; rbx rdi, r14 rsi, rax rdx */
    static const unsigned char cache_head[] = {0x53, 0x41, 0x56, 0x41, 0x57, 0x48, 0x89, 0xfb, 0x49, 0x89, 0xf6, 0x48, 0x89, 0xd0};
    static const unsigned char cache_tail[] = {0x41, 0x5f, 0x41, 0x5e, 0x5b, 0xc3};
    ExitFn step_exit = (ExitFn)(uintptr_t)thunk(0, exit_head, sizeof(exit_head), STEP_EXIT, exit_tail, sizeof(exit_tail));
    ClearFn destroy = (ClearFn)(uintptr_t)thunk(256, clear_head, sizeof(clear_head), DESTROY, clear_tail, sizeof(clear_tail));
    CacheFn cache = (CacheFn)(uintptr_t)thunk(512, cache_head, sizeof(cache_head), CACHE, cache_tail, sizeof(cache_tail));
    FlushInstructionCache(GetCurrentProcess(), NULL, 0);

    uint64_t runner[0x30] = {0}, frame[8] = {0};
    runner[0x120 / 8] = FAKE_SLOT;
    step_exit((uint64_t)(uintptr_t)runner, FAKE_POOL, 0, frame);  /* success: the game gave it back */
    assert(!gives && runner[0x120 / 8] == FAKE_SLOT);
    step_exit((uint64_t)(uintptr_t)runner, FAKE_POOL, 1, frame);
    assert(gives == 1 && given_pool == FAKE_POOL && given_slot == FAKE_SLOT && !runner[0x120 / 8]);
    step_exit((uint64_t)(uintptr_t)runner, FAKE_POOL, 1, frame);  /* nothing held */
    assert(gives == 1);
    runner[0x120 / 8] = FAKE_SLOT + 1;
    destroy((uint64_t)(uintptr_t)runner);
    assert(gives == 2 && given_pool == FAKE_POOL && given_slot == FAKE_SLOT + 1 && !runner[0x120 / 8]);

    uint64_t object[4] = {0};
    uint32_t params[0x20] = {0};
    params[0x54 / 4] = 160u << 20;
    const uint64_t game_block = 0x4567890000ull;
    assert(cache(object, params, game_block) == (uint64_t)(uintptr_t)PORT_BLOCK);
    assert(object[2] == (uint64_t)(uintptr_t)PORT_BLOCK && params[0x54 / 4] == 512u << 20 && port_maps == 1);
    params[0x54 / 4] = 64u << 20;  /* another cache: left alone */
    assert(cache(object, params, game_block) == game_block && object[2] == game_block && port_maps == 1);
    puts("PASS: failed jobs and cleared runners give the slot back; the cache gets the port's 512 MiB");
}

static int install(int expected) {
    image = VirtualAlloc(NULL, IMAGE_SIZE, MEM_RESERVE | MEM_COMMIT, PAGE_EXECUTE_READWRITE);
    assert(image);
    place();
    return bb_hooks_init(image, IMAGE_SIZE) == 0 && bb_render_jobs_install() == expected;
}

static int run_self(const char *self, const char *mode, const char *env) {
    char command[1100];
    snprintf(command, sizeof(command), "cmd /c \"%s\"%s\" %s\"", env, self, mode);
    return system(command);
}

int main(int argc, char **argv) {
    setvbuf(stdout, NULL, _IONBF, 0);
    bb_test_require_game("render jobs");
    const char *mode = argc > 1 ? argv[1] : "";
    if (!strcmp(mode, "--on")) {
        assert(install(4));
        assert(hooked(STEP_EXIT) && hooked(DESTROY) && hooked(RESET) && hooked(CACHE) && reserved == 512u << 20);
        behaviour();
        return 0;
    }
    if (!strcmp(mode, "--off")) {
        assert(install(0));
        assert(!hooked(STEP_EXIT) && !hooked(DESTROY) && !hooked(RESET) && !hooked(CACHE) && !reserved);
        puts("PASS: BB_JOB_SLOT_FIX=0 and BB_RENDER_RESOURCE_CACHE_MB=160 leave the image as it is");
        return 0;
    }
    if (!strcmp(mode, "--changed")) {
        image = VirtualAlloc(NULL, IMAGE_SIZE, MEM_RESERVE | MEM_COMMIT, PAGE_EXECUTE_READWRITE);
        assert(image);
        place();
        image[0x216b20e] ^= 1;  /* the cache's allocation call */
        image[0x1068075] ^= 1;  /* the step's own give-back, before its exit */
        assert(bb_hooks_init(image, IMAGE_SIZE) == 0 && bb_render_jobs_install() == 0);
        assert(!hooked(STEP_EXIT) && !hooked(DESTROY) && !hooked(RESET) && !hooked(CACHE) && !reserved);
        puts("PASS: other code at the sites leaves the image as it is");
        return 0;
    }
    int failed = 0;
    failed |= run_self(argv[0], "--on", "") != 0;
    failed |= run_self(argv[0], "--off", "set BB_JOB_SLOT_FIX=0&& set BB_RENDER_RESOURCE_CACHE_MB=160&& ") != 0;
    failed |= run_self(argv[0], "--changed", "") != 0;
    puts(failed ? "FAIL" : "PASS: render jobs");
    return failed;
}
