/* SPDX-License-Identifier: GPL-2.0-or-later
 * Guarded hooks into the loaded CUSA03173 1.09 image, for the PC features (in-game menu,
 * enhancements, keyboard and mouse). Approach and addresses after droogie's bbhost
 * (https://github.com/droogie/bbhost, GPL-3.0-or-later).
 *
 * Addresses are image offsets: Binary Ninja / PS4 virtual address minus 0x400000 (patches.py).
 * Every hook first checks the original code (its length and hash, code_check.h; the port keeps
 * no game bytes) and refuses, leaving the image unchanged, when it differs - another layout,
 * another game version or a patch already there.
 *
 * Host functions run on the game's own threads with the game's calling convention, so they
 * are declared BB_GUEST_ABI (System V). */
#ifndef BB_ENGINE_HOOKS_H
#define BB_ENGINE_HOOKS_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define BB_GUEST_ABI __attribute__((sysv_abi))

/* Image offset of a Binary Ninja address (eboot at its preferred 0x400000 base). */
#define BB_BN(address) ((uint64_t)(address) - 0x400000u)

#include "code_check.h"

/* Reserves the stub area within reach of rel32 jumps from the image. The image must still be
 * writable. Returns 0 on success. */
int bb_hooks_init(unsigned char *image, size_t size);
/* Makes the stubs executable and read-only; no hooks can be added after it. */
void bb_hooks_seal(void);
/* Guest pointer of an image offset (to call a game function from a hook). */
void *bb_guest(uint64_t offset);

/* `at` holds `call rel32` (E8) or `jmp rel32` (E9) to `target`: sends it to `host` instead.
 * `host` has the callee's signature; it may call the original through bb_guest(target).
 * Returns 0, or -1 (nothing changed) when the instruction is not that. */
int bb_hook_call(uint64_t at, uint64_t target, void *host);

/* Runs `host` with the function's arguments (integer and vector registers preserved) each time
 * the function at `at` is entered, then the function itself. `prologue` describes the first
 * (>= 5) bytes expected there; they must not be RIP-relative, since they run from the stub. */
int bb_hook_entry(uint64_t at, BbCode prologue, void *host);

/* Writes `n` bytes at `at` when they are exactly `expected` (data or code). Returns 0, or -1
 * with nothing changed. */
int bb_patch(uint64_t at, const void *expected, const void *replacement, size_t n);

/* The game's general registers at a bb_hook_mid site, as the host sees (and may change) them. */
typedef struct {
    uint64_t r15, r14, r13, r12, r11, r10, r9, r8, rdi, rsi, rbp, rbx, rdx, rcx, rax, flags;
} BbRegs;

/* Runs `host` in the middle of a function, just before the (>= 5) bytes at `at`, which must
 * be the code `original` describes: whole instructions that are not RIP-relative, not branches, and that
 * no branch lands inside after the first. Every register, the flags and the vector registers
 * (ymm0-15) are kept; the red zone below the game's stack pointer is left alone. */
int bb_hook_mid(uint64_t at, BbCode original, void (BB_GUEST_ABI *host)(BbRegs *));

/* Makes the (>= 5) bytes at `at` (the code `original` describes, under the same rules) skippable while
 * the game runs: bb_skip(handle, 1) jumps over them, bb_skip(handle, 0) runs them again. The
 * switch is one pointer-sized store, so it is safe from any thread. NULL when refused. */
typedef struct BbSkip BbSkip;
BbSkip *bb_hook_skip(uint64_t at, BbCode original);
void bb_skip(BbSkip *site, int skip);

/* Copies `n` bytes of the game's memory at a guest address without faulting on an unmapped one
 * (game objects a feature reads may not exist yet). Returns 1 when all were read. */
int bb_read(uint64_t address, void *out, size_t n);

/* Registers a function run once a frame on the game's main thread, just after its frame-time
 * manager's update (sub_2434770): the measured frame time is the one the task step reads next.
 * Call from an install function. */
void bb_on_main_frame(void (*tick)(void));
/* Installs that hook when something registered; returns 1 when it went in. */
int bb_main_frame_install(void);
/* Whether a tick registered now will run: the task step's call of the frame-time manager is the
 * game's and there is room for one more. */
int bb_main_frame_available(void);

/* `at` holds `mov dword [mem], imm32` (`n` bytes, C7 /0, the memory operand neither rip- nor
 * rsp-based) whose bytes before the immediate are `prefix`: it stores the 32-bit value at `cell`
 * instead, read each time it runs. Flags and every register are kept. Returns 0, or -1 with
 * nothing changed. */
int bb_hook_store(uint64_t at, size_t n, BbCode prefix, const void *cell);

/* `n` (at most 64) zeroed, 16-byte aligned bytes in the stubs' writable page, within rel32 reach
 * of the image: a value the game's code can load rip-relative. NULL when there is no room. */
void *bb_hook_data(size_t n);

/* Why the last hook was refused (static text). */
const char *bb_hooks_error(void);

/* BB_ENGINE_HOOKS=0 turns every engine hook off. */
int bb_hooks_enabled(void);

#ifdef __cplusplus
}
#endif

#endif
