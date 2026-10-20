/* SPDX-License-Identifier: GPL-2.0-or-later
 * engine_hooks.c on a small executable "image": an entry hook sees the arguments and leaves the
 * function's integer and vector arguments intact, a call-site hook replaces the callee and can
 * call the original, a mid-function hook sees and changes the registers while the flags, the
 * vector registers and the red zone survive it, a skippable site switches both ways, and all
 * refuse unexpected bytes without changing anything. */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#ifdef _WIN32
#include <windows.h>
#else
#include <sys/mman.h>
#endif
#include "engine_hooks.h"

typedef int64_t (BB_GUEST_ABI *IntFn)(int64_t, int64_t);
typedef double (BB_GUEST_ABI *VecFn)(double, double);

enum { SUM = 0x100, ADD = 0x200, CALLER = 0x300, MID = 0x400, MID_SITE = MID + 16, STEP = 0x500,
       IMAGE = 0x2000 };
/* sum(a, b) = a + 2b: push rbp; mov rbp,rsp; lea rax,[rdi+rsi*2]; pop rbp; ret */
static const unsigned char sum_code[] = {0x55, 0x48, 0x89, 0xe5, 0x48, 0x8d, 0x04, 0x77, 0x5d, 0xc3};
/* add(x, y) = x + y: addsd xmm0,xmm1; ret (the whole function is the displaced prologue) */
static const unsigned char add_code[] = {0xf2, 0x0f, 0x58, 0xc1, 0xc3};

static int64_t seen_a, seen_b;
static int entries;
static volatile double sink;

static BB_GUEST_ABI void on_sum(int64_t a, int64_t b) {
    seen_a = a;
    seen_b = b;
    ++entries;
}
/* Uses the vector registers itself, so a missing save would change add()'s arguments. */
static BB_GUEST_ABI void on_add(double x, double y) {
    sink = x * 3.0 + y * 7.0 + 0.25;
    ++entries;
}
/* mid(a, b) = (a + b) + (a < b ? 1 << 32 : 0) + a + b, from r13, the flags of cmp a, b,
 * xmm9 and the red zone [rsp-8] across the hooked lea rax, [r13+rsi] at MID_SITE. */
static const unsigned char mid_code[] = {
    0x49, 0x89, 0xfd,                    /* mov r13, rdi */
    0x66, 0x4c, 0x0f, 0x6e, 0xcf,        /* movq xmm9, rdi */
    0x48, 0x89, 0x74, 0x24, 0xf8,        /* mov [rsp-8], rsi */
    0x48, 0x39, 0xf7,                    /* cmp rdi, rsi */
    0x49, 0x8d, 0x44, 0x35, 0x00,        /* lea rax, [r13+rsi] (the hooked site) */
    0x0f, 0x92, 0xc1,                    /* setb cl */
    0x48, 0x0f, 0xb6, 0xc9,              /* movzx rcx, cl */
    0x48, 0xc1, 0xe1, 0x20,              /* shl rcx, 32 */
    0x48, 0x01, 0xc8,                    /* add rax, rcx */
    0x66, 0x4c, 0x0f, 0x7e, 0xca,        /* movq rdx, xmm9 */
    0x48, 0x01, 0xd0,                    /* add rax, rdx */
    0x48, 0x03, 0x44, 0x24, 0xf8,        /* add rax, [rsp-8] */
    0xc3,
};
/* step() = 1, or 17 with the add: mov eax, 1; add eax, 0x10; ret */
static const unsigned char step_code[] = {0xb8, 0x01, 0x00, 0x00, 0x00, 0x05, 0x10, 0x00, 0x00, 0x00, 0xc3};
typedef int32_t (BB_GUEST_ABI *StepFn)(void);

static uint64_t seen_r13;
/* Changes the flags and the vector registers itself, and moves r13 on by 1000. */
static BB_GUEST_ABI void on_mid(BbRegs *regs) {
    seen_r13 = regs->r13;
    regs->r13 += 1000;
    __asm__ volatile("vpxor %%ymm9, %%ymm9, %%ymm9\n\tcmp %%rsp, %%rsp" ::: "xmm9", "cc");
    ++entries;
}
static BB_GUEST_ABI int64_t replace_sum(int64_t a, int64_t b) {
    return ((IntFn)bb_guest(SUM))(a, b) * 10;
}

int main(void) {
#ifdef _WIN32
    unsigned char *image = VirtualAlloc(NULL, IMAGE, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
#else
    unsigned char *image = mmap(NULL, IMAGE, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    assert(image != MAP_FAILED);
#endif
    assert(image);
    memset(image, 0xcc, IMAGE);
    memcpy(image + SUM, sum_code, sizeof(sum_code));
    memcpy(image + ADD, add_code, sizeof(add_code));
    /* caller(a, b): call sum; ret */
    image[CALLER] = 0xe8;
    int32_t rel = SUM - (CALLER + 5);
    memcpy(image + CALLER + 1, &rel, 4);
    image[CALLER + 5] = 0xc3;
    memcpy(image + MID, mid_code, sizeof(mid_code));
    memcpy(image + STEP, step_code, sizeof(step_code));

    assert(bb_hooks_init(image, IMAGE) == 0);
    unsigned char before[IMAGE];
    memcpy(before, image, IMAGE);
    const unsigned char wrong[] = {0x55, 0x48, 0x89, 0xe5, 0x90};
    assert(bb_hook_entry(SUM, wrong, sizeof(wrong), (void *)on_sum) == -1);
    assert(bb_hook_call(CALLER, ADD, (void *)replace_sum) == -1);
    assert(bb_hook_call(SUM, SUM, (void *)replace_sum) == -1);
    assert(bb_hook_mid(MID_SITE, step_code, 5, on_mid) == -1);
    assert(bb_hook_skip(STEP, step_code + 5, 5) == NULL);
    assert(!memcmp(before, image, IMAGE));  /* refusals change nothing */

    /* A guarded data write: only over the expected bytes, nothing changed otherwise. */
    const unsigned char pad[4] = {0xcc, 0xcc, 0xcc, 0xcc}, data[4] = {1, 2, 3, 4}, other[4] = {9, 9, 9, 9};
    assert(bb_patch(0x1800, other, data, 4) == -1 && !memcmp(before, image, IMAGE));
    assert(bb_patch(IMAGE - 2, pad, data, 4) == -1);
    assert(bb_patch(0x1800, pad, data, 4) == 0 && !memcmp(image + 0x1800, data, 4));
    assert(bb_patch(0x1800, pad, data, 4) == -1);  /* already written */

    assert(bb_hook_entry(SUM, sum_code, 8, (void *)on_sum) == 0);
    assert(bb_hook_entry(ADD, add_code, sizeof(add_code), (void *)on_add) == 0);
    assert(bb_hook_call(CALLER, SUM, (void *)replace_sum) == 0);
    assert(bb_hook_entry(SUM, sum_code, 8, (void *)on_sum) == -1);  /* already hooked */
    assert(bb_hook_mid(MID_SITE, mid_code + 16, 5, on_mid) == 0);
    BbSkip *add16 = bb_hook_skip(STEP + 5, step_code + 5, 5);
    assert(add16);
    bb_hooks_seal();
#ifdef _WIN32
    DWORD old;
    assert(VirtualProtect(image, IMAGE, PAGE_EXECUTE_READ, &old));
    FlushInstructionCache(GetCurrentProcess(), image, IMAGE);
#else
    assert(mprotect(image, IMAGE, PROT_READ | PROT_EXEC) == 0);
    __builtin___clear_cache((char *)image, (char *)image + IMAGE);
#endif

    assert(((IntFn)(image + SUM))(5, 7) == 19);
    assert(seen_a == 5 && seen_b == 7 && entries == 1);
    assert(((VecFn)(image + ADD))(1.5, 2.25) == 3.75);
    assert(entries == 2);
    assert(((IntFn)(image + CALLER))(1, 2) == 50);  /* replaced, and the original still ran */
    assert(seen_a == 1 && seen_b == 2 && entries == 3);
    /* r13 seen as 3, then 1003; 3 < 5 kept in the flags; xmm9 and [rsp-8] intact. */
    assert(((IntFn)(image + MID))(3, 5) == 1003 + 5 + (1ll << 32) + 3 + 5);
    assert(seen_r13 == 3 && entries == 4);
    assert(((IntFn)(image + MID))(9, 5) == 1009 + 5 + 9 + 5);
    assert(((StepFn)(image + STEP))() == 17);
    bb_skip(add16, 1);
    assert(((StepFn)(image + STEP))() == 1);
    bb_skip(add16, 0);
    assert(((StepFn)(image + STEP))() == 17);
    puts("engine hooks: ok");
    return 0;
}
