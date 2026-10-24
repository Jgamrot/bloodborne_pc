/* SPDX-License-Identifier: GPL-2.0-or-later
 * Guarded hooks into the loaded game image (engine_hooks.h). */
#include "engine_hooks.h"

#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
#include <windows.h>
#else
#include <sys/mman.h>
#endif

/* The arena's last page stays writable (bb_hook_skip's switches); the rest is code. */
enum { ARENA_SIZE = 0x10000, DATA_SIZE = 0x1000, CODE_SIZE = ARENA_SIZE - DATA_SIZE, REACH = 0x7ff00000 };

static unsigned char *g_image, *g_arena;
static size_t g_image_size, g_used, g_data_used;
static int g_sealed;
static const char *g_error = "";

static int refuse(const char *why) {
    g_error = why;
    return -1;
}

const char *bb_hooks_error(void) { return g_error; }

int bb_hooks_enabled(void) {
    const char *value = getenv("BB_ENGINE_HOOKS");
    return !(value && !strcmp(value, "0"));
}

void *bb_guest(uint64_t offset) { return g_image ? g_image + offset : NULL; }

static int reachable(const unsigned char *from, const unsigned char *to) {
    const int64_t distance = (int64_t)((uintptr_t)to - (uintptr_t)from);
    return distance > -(int64_t)REACH && distance < (int64_t)REACH;
}

/* A rel32 jump or call from anywhere in the image must reach the stubs, so they live in a
 * region reserved just past the image (or, failing that, just before it). */
static unsigned char *reserve_near(unsigned char *image, size_t size) {
    const uintptr_t granule = 0x10000;
    const uintptr_t end = ((uintptr_t)image + size + granule - 1) & ~(granule - 1);
    for (uintptr_t step = 0; step < 0x40000000u; step += granule) {
        uintptr_t candidates[2] = {end + step, (uintptr_t)image > step + ARENA_SIZE
                                                   ? (((uintptr_t)image - step - ARENA_SIZE) & ~(granule - 1)) : 0};
        for (int i = 0; i < 2; ++i) {
            if (!candidates[i]) continue;
            unsigned char *want = (unsigned char *)candidates[i];
            if (!reachable(image, want) || !reachable(want + ARENA_SIZE, image + size)) continue;
#ifdef _WIN32
            unsigned char *got = VirtualAlloc(want, ARENA_SIZE, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
            if (got) return got;
#else
            void *got = mmap(want, ARENA_SIZE, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
            if (got != MAP_FAILED) {
                if (got == want) return got;
                munmap(got, ARENA_SIZE);
            }
#endif
        }
    }
    return NULL;
}

int bb_hooks_init(unsigned char *image, size_t size) {
    if (g_arena) return refuse("hooks already initialised");
    g_arena = reserve_near(image, size);
    if (!g_arena) return refuse("no memory within rel32 reach of the image");
    memset(g_arena, 0xcc, ARENA_SIZE);
    g_image = image;
    g_image_size = size;
    g_used = g_data_used = 0;
    g_sealed = 0;
    return 0;
}

void bb_hooks_seal(void) {
    if (!g_arena || g_sealed) return;
#ifdef _WIN32
    DWORD old;
    VirtualProtect(g_arena, CODE_SIZE, PAGE_EXECUTE_READ, &old);
    FlushInstructionCache(GetCurrentProcess(), g_arena, CODE_SIZE);
#else
    mprotect(g_arena, CODE_SIZE, PROT_READ | PROT_EXEC);
#endif
    g_sealed = 1;
}

static unsigned char *stub(size_t size) {
    if (!g_arena || g_sealed || g_used + size > CODE_SIZE) return NULL;
    unsigned char *at = g_arena + g_used;
    g_used = (g_used + size + 15) & ~(size_t)15;
    return at;
}

static int in_image(uint64_t at, size_t n) { return g_image && at <= g_image_size && n <= g_image_size - at; }

static void put_rel32(unsigned char *field, const unsigned char *next, const unsigned char *to) {
    const int32_t rel = (int32_t)((intptr_t)to - (intptr_t)next);
    memcpy(field, &rel, 4);
}

static unsigned char *emit(unsigned char *p, const void *bytes, size_t n) {
    memcpy(p, bytes, n);
    return p + n;
}

static unsigned char *emit_movabs_r11(unsigned char *p, const void *target) {
    const uint64_t value = (uint64_t)(uintptr_t)target;
    *p++ = 0x49; *p++ = 0xbb;  /* movabs r11, imm64 */
    return emit(p, &value, 8);
}

int bb_hook_call(uint64_t at, uint64_t target, void *host) {
    if (!bb_hooks_enabled()) return refuse("engine hooks are off (BB_ENGINE_HOOKS=0)");
    if (!host || !in_image(at, 5) || !in_image(target, 1)) return refuse("address outside the image");
    unsigned char *site = g_image + at;
    if (site[0] != 0xe8 && site[0] != 0xe9) return refuse("not a call or jmp rel32");
    int32_t rel;
    memcpy(&rel, site + 1, 4);
    if (at + 5 + (int64_t)rel != target) return refuse("the call does not go to the expected function");
    unsigned char *s = stub(13);
    if (!s) return refuse("no stub space (not initialised, sealed or full)");
    unsigned char *p = emit_movabs_r11(s, host);
    *p++ = 0x41; *p++ = 0xff; *p++ = 0xe3;  /* jmp r11 */
    put_rel32(site + 1, site + 5, s);
    return 0;
}

int bb_read(uint64_t address, void *out, size_t n) {
    if (!address || !out) return 0;
#ifdef _WIN32
    SIZE_T got = 0;
    return ReadProcessMemory(GetCurrentProcess(), (const void *)(uintptr_t)address, out, n, &got) && got == n;
#else
    memcpy(out, (const void *)(uintptr_t)address, n);
    return 1;
#endif
}

/* The frame-time manager's update (SprjFlipper::Update), once a frame on the main thread; its
 * first 17 bytes, as bbhost's engine/frame_rate.cpp checks them. */
enum { FRAME_MANAGER = 0x2434770, MAX_TICKS = 8 };
static const BbCode frame_manager_prologue = {17, 0x522377a1cb8f9aceull};
static void (*g_ticks[MAX_TICKS])(void);
static int g_tick_count;

void bb_on_main_frame(void (*tick)(void)) {
    if (tick && g_tick_count < MAX_TICKS) g_ticks[g_tick_count++] = tick;
}

static BB_GUEST_ABI void main_frame(void) {
    for (int i = 0; i < g_tick_count; ++i) g_ticks[i]();
}

int bb_main_frame_install(void) {
    if (!g_tick_count) return 0;
    return !bb_hook_entry(BB_BN(FRAME_MANAGER), frame_manager_prologue, (void *)main_frame);
}

int bb_main_frame_available(void) {
    const uint64_t at = BB_BN(FRAME_MANAGER);
    return bb_hooks_enabled() && g_tick_count < MAX_TICKS && in_image(at, frame_manager_prologue.n) &&
           bb_code_is(g_image + at, frame_manager_prologue);
}

void *bb_hook_data(size_t n) {
    if (!g_arena || !n || n > 64 || g_data_used + n > DATA_SIZE) return refuse("no data space"), NULL;
    unsigned char *at = g_arena + CODE_SIZE + g_data_used;
    g_data_used += (n + 15) & ~(size_t)15;
    memset(at, 0, n);
    return at;
}

int bb_patch(uint64_t at, const void *expected, const void *replacement, size_t n) {
    if (!bb_hooks_enabled()) return refuse("engine hooks are off (BB_ENGINE_HOOKS=0)");
    if (!expected || !replacement || !n || !in_image(at, n)) return refuse("address outside the image");
    if (memcmp(g_image + at, expected, n)) return refuse("unexpected bytes at the patch site");
    memcpy(g_image + at, replacement, n);
    return 0;
}

int bb_hook_entry(uint64_t at, BbCode prologue, void *host) {
    const size_t n = prologue.n;
    if (!bb_hooks_enabled()) return refuse("engine hooks are off (BB_ENGINE_HOOKS=0)");
    if (!host || n < 5 || n > 32) return refuse("bad hook arguments");
    if (!in_image(at, n)) return refuse("address outside the image");
    unsigned char *site = g_image + at;
    if (!bb_code_is(site, prologue)) return refuse("unexpected bytes at the function entry");
    /* Save the argument registers (integer, rax for variadic callers, xmm0-7), call the host
     * function with them, restore them, run the displaced prologue and continue after it.
     * At entry rsp is 8 mod 16; seven pushes make it 0 and the 0x80-byte area keeps it. */
    static const unsigned char save[] = {
        0x57, 0x56, 0x52, 0x51, 0x41, 0x50, 0x41, 0x51, 0x50,  /* push rdi rsi rdx rcx r8 r9 rax */
        0x48, 0x81, 0xec, 0x80, 0x00, 0x00, 0x00,              /* sub rsp, 0x80 */
    };
    static const unsigned char restore[] = {
        0x48, 0x81, 0xc4, 0x80, 0x00, 0x00, 0x00,              /* add rsp, 0x80 */
        0x58, 0x41, 0x59, 0x41, 0x58, 0x59, 0x5a, 0x5e, 0x5f,  /* pop rax r9 r8 rcx rdx rsi rdi */
    };
    unsigned char *s = stub(sizeof(save) + 8 * 6 + 13 + 8 * 6 + sizeof(restore) + n + 5);
    if (!s) return refuse("no stub space (not initialised, sealed or full)");
    unsigned char *p = emit(s, save, sizeof(save));
    for (int i = 0; i < 8; ++i) {  /* movdqu [rsp+16*i], xmm_i */
        const unsigned char op[] = {0xf3, 0x0f, 0x7f, (unsigned char)(0x44 | i << 3), 0x24, (unsigned char)(16 * i)};
        p = emit(p, op, sizeof(op));
    }
    p = emit_movabs_r11(p, host);
    *p++ = 0x41; *p++ = 0xff; *p++ = 0xd3;  /* call r11 */
    for (int i = 0; i < 8; ++i) {  /* movdqu xmm_i, [rsp+16*i] */
        const unsigned char op[] = {0xf3, 0x0f, 0x6f, (unsigned char)(0x44 | i << 3), 0x24, (unsigned char)(16 * i)};
        p = emit(p, op, sizeof(op));
    }
    p = emit(p, restore, sizeof(restore));
    p = emit(p, site, n);  /* the displaced prologue, from the game itself */
    *p++ = 0xe9;
    put_rel32(p, p + 4, site + n);
    site[0] = 0xe9;
    put_rel32(site + 1, site + 5, s);
    memset(site + 5, 0xcc, n - 5);  /* never reached: the stub returns past them */
    return 0;
}

static unsigned char *mid_site(uint64_t at, BbCode original) {
    const size_t n = original.n;
    if (!bb_hooks_enabled()) return refuse("engine hooks are off (BB_ENGINE_HOOKS=0)"), NULL;
    if (n < 5 || n > 32) return refuse("bad hook arguments"), NULL;
    if (!in_image(at, n)) return refuse("address outside the image"), NULL;
    if (!bb_code_is(g_image + at, original)) return refuse("unexpected bytes at the hook site"), NULL;
    return g_image + at;
}

/* The site jumps to the stub; its other bytes are never run (the stub returns past them). */
static void divert(unsigned char *site, size_t n, const unsigned char *to) {
    site[0] = 0xe9;
    put_rel32(site + 1, site + 5, to);
    memset(site + 5, 0xcc, n - 5);
}

/* vmovdqu [rsp+32*i], ymm_i (store) or ymm_i, [rsp+32*i] (load). */
static unsigned char *emit_ymm(unsigned char *p, int i, int store) {
    const int32_t disp = 32 * i;
    *p++ = 0xc5;
    *p++ = i < 8 ? 0xfe : 0x7e;
    *p++ = store ? 0x7f : 0x6f;
    *p++ = (unsigned char)(0x84 | (i & 7) << 3);
    *p++ = 0x24;
    return emit(p, &disp, 4);
}

int bb_hook_mid(uint64_t at, BbCode original, void (BB_GUEST_ABI *host)(BbRegs *)) {
    const size_t n = original.n;
    unsigned char *site = mid_site(at, original);
    if (!site) return -1;
    if (!host) return refuse("bad hook arguments");
    /* Below the red zone, save the flags and the general registers (they form the BbRegs), align
     * the stack to 32 for ymm0-15, call the host with the BbRegs, restore everything, run the
     * displaced instructions and continue after them. rbx keeps the unaligned stack pointer
     * (the host preserves it, as the System V ABI has it). */
    static const unsigned char save[] = {
        0x48, 0x8d, 0x64, 0x24, 0x80,                          /* lea rsp, [rsp-0x80] */
        0x9c, 0x50, 0x51, 0x52, 0x53, 0x55, 0x56, 0x57,        /* pushfq; push rax rcx rdx rbx rbp rsi rdi */
        0x41, 0x50, 0x41, 0x51, 0x41, 0x52, 0x41, 0x53,        /* push r8 r9 r10 r11 */
        0x41, 0x54, 0x41, 0x55, 0x41, 0x56, 0x41, 0x57,        /* push r12 r13 r14 r15 */
        0x48, 0x89, 0xe7, 0x48, 0x89, 0xe3,                    /* mov rdi, rsp; mov rbx, rsp */
        0x48, 0x83, 0xe4, 0xe0,                                /* and rsp, -32 */
        0x48, 0x81, 0xec, 0x00, 0x02, 0x00, 0x00,              /* sub rsp, 0x200 */
    };
    static const unsigned char restore[] = {
        0x48, 0x89, 0xdc,                                      /* mov rsp, rbx */
        0x41, 0x5f, 0x41, 0x5e, 0x41, 0x5d, 0x41, 0x5c,        /* pop r15 r14 r13 r12 */
        0x41, 0x5b, 0x41, 0x5a, 0x41, 0x59, 0x41, 0x58,        /* pop r11 r10 r9 r8 */
        0x5f, 0x5e, 0x5d, 0x5b, 0x5a, 0x59, 0x58, 0x9d,        /* pop rdi rsi rbp rbx rdx rcx rax; popfq */
        0x48, 0x8d, 0xa4, 0x24, 0x80, 0x00, 0x00, 0x00,        /* lea rsp, [rsp+0x80] */
    };
    unsigned char *s = stub(sizeof(save) + 16 * 9 + 13 + 3 + 16 * 9 + sizeof(restore) + n + 5);
    if (!s) return refuse("no stub space (not initialised, sealed or full)");
    unsigned char *p = emit(s, save, sizeof(save));
    for (int i = 0; i < 16; ++i) p = emit_ymm(p, i, 1);
    p = emit_movabs_r11(p, (const void *)host);
    *p++ = 0x41; *p++ = 0xff; *p++ = 0xd3;  /* call r11 */
    for (int i = 0; i < 16; ++i) p = emit_ymm(p, i, 0);
    p = emit(p, restore, sizeof(restore));
    p = emit(p, site, n);  /* the displaced instructions, from the game itself */
    *p++ = 0xe9;
    put_rel32(p, p + 4, site + n);
    divert(site, n, s);
    return 0;
}

struct BbSkip {
    const unsigned char *volatile target;  /* where the stub's indirect jump goes: run or skip */
    const unsigned char *run, *skip;
};

BbSkip *bb_hook_skip(uint64_t at, BbCode original) {
    const size_t n = original.n;
    unsigned char *site = mid_site(at, original);
    if (!site) return NULL;
    if (g_data_used + sizeof(BbSkip) > DATA_SIZE) return refuse("no switch space"), NULL;
    unsigned char *s = stub(6 + n + 5 + 5);
    if (!s) return refuse("no stub space (not initialised, sealed or full)"), NULL;
    BbSkip *data = (BbSkip *)(g_arena + CODE_SIZE + g_data_used);
    g_data_used += (sizeof(BbSkip) + 15) & ~(size_t)15;
    /* jmp [data->target]; run: the instructions, then back; skip: straight back. */
    unsigned char *p = s;
    *p++ = 0xff; *p++ = 0x25;
    put_rel32(p, p + 4, (const unsigned char *)&data->target);
    p += 4;
    data->run = p;
    p = emit(p, site, n);  /* the instructions, from the game itself */
    *p++ = 0xe9;
    put_rel32(p, p + 4, site + n);
    p += 4;
    data->skip = p;
    *p++ = 0xe9;
    put_rel32(p, p + 4, site + n);
    data->target = data->run;
    divert(site, n, s);
    return data;
}

void bb_skip(BbSkip *site, int skip) {
    if (site) __atomic_store_n(&site->target, skip ? site->skip : site->run, __ATOMIC_RELEASE);
}
