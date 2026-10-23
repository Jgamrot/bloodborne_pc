/* SPDX-License-Identifier: GPL-2.0-or-later
 * The blur-kernel sample count (deadinside28/bloodborne_pc #207: "guest raised debug exception
 * 0xa0020007", exit code 23, at +0xbbc429).
 *
 * Yebis's GPUTexUtil_GetRecursiveSampleParameters (sub_bbc3e0) asserts that its first argument,
 * the base sample count, is at least 3 ("nBaseSamples >= 3"). Post-effect parameters now and
 * then give it 2, and the assertion stops the game. The count is raised to 3 on entry.
 * BB_KERNEL_CLAMP=0 leaves the function as it is.
 *
 * Addresses are image offsets (eboot virtual address; Binary Ninja's minus 0x400000). */
#include "blur_kernel.h"
#include "engine_hooks.h"

#include <stdio.h>
#include <stdlib.h>

enum { SAMPLE_PARAMETERS = 0xbbc3e0, MIN_BASE_SAMPLES = 3 };
/* push rbp; mov rbp, rsp; push r15 */
static const BbCode prologue = {6, 0x82d75a35aabe38aaull};

static BB_GUEST_ABI void on_entry(BbRegs *regs) {
    if ((int32_t)regs->rdi < MIN_BASE_SAMPLES) regs->rdi = MIN_BASE_SAMPLES;
}

int bb_blur_kernel_install(void) {
    const char *env = getenv("BB_KERNEL_CLAMP");
    if (env && *env == '0') {
        puts("Blur-kernel sample count clamp: off (BB_KERNEL_CLAMP=0)");
        return 0;
    }
    if (bb_hook_mid(SAMPLE_PARAMETERS, prologue, on_entry)) {
        printf("Blur-kernel sample count clamp: not installed (%s)\n", bb_hooks_error());
        return 0;
    }
    return 1;
}
