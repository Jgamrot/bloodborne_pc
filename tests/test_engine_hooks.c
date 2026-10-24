/* SPDX-License-Identifier: GPL-2.0-or-later
 * engine_hooks.c on a small executable "image": an entry hook sees the arguments and leaves the
 * function's integer and vector arguments intact, a call-site hook replaces the callee and can
 * call the original, a mid-function hook sees and changes the registers while the flags, the
 * vector registers and the red zone survive it, a skippable site switches both ways, a data cell
 * the image loads rip-relative follows writes after the seal, a store of an immediate stores a
 * cell's value instead (flags and registers kept), and all refuse unexpected bytes without
 * changing anything. */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <windows.h>
#include "engine_hooks.h"

typedef int64_t (BB_GUEST_ABI *IntFn)(int64_t, int64_t);
typedef double (BB_GUEST_ABI *VecFn)(double, double);

enum { SUM = 0x100, ADD = 0x200, CALLER = 0x300, MID = 0x400, MID_SITE = MID + 18, STEP = 0x500,
       LOAD = 0x600, STORE = 0x700, STORE_RAX = 0x780, STORE_R12 = 0x800, STORE_BAD = 0x880, IMAGE = 0x2000 };
/* store() = 7 + 0x100 (the flags of cmp 7, 9 kept) + what mov dword [rbp-0x48], imm32 stored. */
static const unsigned char store_code[] = {
    0x55, 0x48, 0x89, 0xe5,                    /* push rbp; mov rbp, rsp */
    0xb8, 0x07, 0x00, 0x00, 0x00,              /* mov eax, 7 */
    0x83, 0xf8, 0x09,                          /* cmp eax, 9 */
    0xc7, 0x45, 0xb8, 0x11, 0x11, 0x11, 0x11,  /* mov dword [rbp-0x48], 0x11111111 (hooked) */
    0x0f, 0x92, 0xc1, 0x0f, 0xb6, 0xc9,        /* setb cl; movzx ecx, cl */
    0xc1, 0xe1, 0x08, 0x01, 0xc8,              /* shl ecx, 8; add eax, ecx */
    0x03, 0x45, 0xb8, 0x5d, 0xc3,              /* add eax, [rbp-0x48]; pop rbp; ret */
};
/* store_rax(p) = what mov dword [rax+0x10], imm32 stored, read back through rax. */
static const unsigned char store_rax_code[] = {
    0x48, 0x89, 0xf8, 0xc7, 0x40, 0x10, 0x22, 0x22, 0x22, 0x22, 0x8b, 0x40, 0x10, 0xc3,
};
/* store_r12(p): the same through [r12+0x18] (REX.B, SIB). */
static const unsigned char store_r12_code[] = {
    0x41, 0x54, 0x49, 0x89, 0xfc, 0x41, 0xc7, 0x44, 0x24, 0x18, 0x33, 0x33, 0x33, 0x33,
    0x41, 0x8b, 0x44, 0x24, 0x18, 0x41, 0x5c, 0xc3,
};
/* Refused: mov dword [rsp+8], imm32; mov dword [rip+0], imm32. */
static const unsigned char store_bad_code[] = {
    0xc7, 0x44, 0x24, 0x08, 0x44, 0x44, 0x44, 0x44, 0xc7, 0x05, 0, 0, 0, 0, 0x55, 0x55, 0x55, 0x55,
};
typedef uint32_t (BB_GUEST_ABI *StoreFn)(void *);
typedef float (BB_GUEST_ABI *LoadFn)(void);
/* sum(a, b) = a + 2b: push rbp; mov rbp,rsp; lea rax,[rdi+rsi*2]; pop rbp; ret */
/* The hook API checks sites by length and hash (code_check.h). */
static BbCode code_of(const unsigned char *code, size_t n) {
    BbCode c = {n, bb_code_hash(code, n)};
    return c;
}
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
    0x41, 0x55,                          /* push r13 (callee-saved) */
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
    0x41, 0x5d,                          /* pop r13 */
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
    unsigned char *image = VirtualAlloc(NULL, IMAGE, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
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
    memcpy(image + STORE, store_code, sizeof(store_code));
    memcpy(image + STORE_RAX, store_rax_code, sizeof(store_rax_code));
    memcpy(image + STORE_R12, store_r12_code, sizeof(store_r12_code));
    memcpy(image + STORE_BAD, store_bad_code, sizeof(store_bad_code));

    assert(bb_hooks_init(image, IMAGE) == 0);
    unsigned char before[IMAGE];
    memcpy(before, image, IMAGE);
    const unsigned char wrong[] = {0x55, 0x48, 0x89, 0xe5, 0x90};
    assert(bb_hook_entry(SUM, code_of(wrong, sizeof(wrong)), (void *)on_sum) == -1);
    assert(bb_hook_call(CALLER, ADD, (void *)replace_sum) == -1);
    assert(bb_hook_call(SUM, SUM, (void *)replace_sum) == -1);
    assert(bb_hook_mid(MID_SITE, code_of(step_code, 5), on_mid) == -1);
    assert(bb_hook_skip(STEP, code_of(step_code + 5, 5)) == NULL);
    static uint32_t far_cell;
    assert(bb_hook_store(STORE + 12, 7, code_of(store_code + 13, 3), &far_cell) == -1);  /* other bytes */
    assert(bb_hook_store(STORE_BAD, 8, code_of(store_bad_code, 4), &far_cell) == -1);    /* rsp-based */
    assert(bb_hook_store(STORE_BAD + 8, 10, code_of(store_bad_code + 8, 6), &far_cell) == -1);  /* rip */
    assert(bb_hook_store(STORE + 4, 5, code_of(store_code + 4, 1), &far_cell) == -1);  /* mov eax, imm32 */
    assert(!memcmp(before, image, IMAGE));  /* refusals change nothing */

    /* A guarded data write: only over the expected bytes, nothing changed otherwise. */
    const unsigned char pad[4] = {0xcc, 0xcc, 0xcc, 0xcc}, data[4] = {1, 2, 3, 4}, other[4] = {9, 9, 9, 9};
    assert(bb_patch(0x1800, other, data, 4) == -1 && !memcmp(before, image, IMAGE));
    assert(bb_patch(IMAGE - 2, pad, data, 4) == -1);
    assert(bb_patch(0x1800, pad, data, 4) == 0 && !memcmp(image + 0x1800, data, 4));
    assert(bb_patch(0x1800, pad, data, 4) == -1);  /* already written */

    assert(bb_hook_entry(SUM, code_of(sum_code, 8), (void *)on_sum) == 0);
    assert(bb_hook_entry(ADD, code_of(add_code, sizeof(add_code)), (void *)on_add) == 0);
    assert(bb_hook_call(CALLER, SUM, (void *)replace_sum) == 0);
    assert(bb_hook_entry(SUM, code_of(sum_code, 8), (void *)on_sum) == -1);  /* already hooked */
    assert(bb_hook_mid(MID_SITE, code_of(mid_code + 18, 5), on_mid) == 0);
    BbSkip *add16 = bb_hook_skip(STEP + 5, code_of(step_code + 5, 5));
    assert(add16);
    /* A cell the image loads rip-relative (movss xmm0, [rip+rel32]; ret), written after the seal. */
    float *cell = bb_hook_data(sizeof(float)), *second = bb_hook_data(16);
    assert(cell && second && !((uintptr_t)second & 15) && (unsigned char *)second >= (unsigned char *)(cell + 1));
    assert(*cell == 0.0f && !bb_hook_data(65));
    const int64_t to_cell = (int64_t)((uintptr_t)cell - (uintptr_t)(image + LOAD + 8));
    assert(to_cell >= INT32_MIN && to_cell <= INT32_MAX);
    const unsigned char load_code[] = {0xf3, 0x0f, 0x10, 0x05};
    memcpy(image + LOAD, load_code, 4);
    const int32_t rel32 = (int32_t)to_cell;
    memcpy(image + LOAD + 4, &rel32, 4);
    image[LOAD + 8] = 0xc3;
    /* Stores of a cell's value in place of an immediate: rbp-, rax- (another scratch) and r12-based. */
    uint32_t *stored = bb_hook_data(4), *stored_rax = bb_hook_data(4), *stored_r12 = bb_hook_data(4);
    assert(stored && stored_rax && stored_r12);
    assert(bb_hook_store(STORE + 12, 7, code_of(store_code + 12, 3), stored) == 0);
    assert(bb_hook_store(STORE_RAX + 3, 7, code_of(store_rax_code + 3, 3), stored_rax) == 0);
    assert(bb_hook_store(STORE_R12 + 5, 9, code_of(store_r12_code + 5, 5), stored_r12) == 0);
    assert(bb_hook_store(STORE + 12, 7, code_of(store_code + 12, 3), stored) == -1);  /* already hooked */
    assert(!bb_main_frame_available());  /* no frame-time manager in this image */
    bb_hooks_seal();
    DWORD old;
    assert(VirtualProtect(image, IMAGE, PAGE_EXECUTE_READ, &old));
    FlushInstructionCache(GetCurrentProcess(), image, IMAGE);

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
    *cell = 0.25f;
    assert(((LoadFn)(image + LOAD))() == 0.25f);
    *(volatile float *)cell = -2.0f;
    assert(((LoadFn)(image + LOAD))() == -2.0f);
    uint32_t box[8] = {0};
    *(volatile uint32_t *)stored = 0x2000;
    assert(((StoreFn)(image + STORE))(NULL) == 7 + 0x100 + 0x2000);
    *(volatile uint32_t *)stored = 0x3c360b61;
    assert(((StoreFn)(image + STORE))(NULL) == 7 + 0x100 + 0x3c360b61);
    *(volatile uint32_t *)stored_rax = 0xabcdef01;
    assert(((StoreFn)(image + STORE_RAX))(box) == 0xabcdef01 && box[4] == 0xabcdef01);
    *(volatile uint32_t *)stored_r12 = 0x12345678;
    assert(((StoreFn)(image + STORE_R12))(box) == 0x12345678 && box[6] == 0x12345678);
    puts("engine hooks: ok");
    return 0;
}
