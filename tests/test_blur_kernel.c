/* SPDX-License-Identifier: GPL-2.0-or-later
 * blur_kernel.c on a small image with a stand-in for the sample parameters function (the
 * game's prologue, then it returns its first argument): counts below 3 reach it as 3, others
 * as they are, BB_KERNEL_CLAMP=0 installs nothing, and other code at the address is refused. */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>
#include "blur_kernel.h"
#include "engine_hooks.h"

typedef int32_t (BB_GUEST_ABI *SamplesFn)(int32_t);

enum { AT = 0xbbc3e0, IMAGE = 0xbbd000 };
/* push rbp; mov rbp, rsp; push r15; mov eax, edi; pop r15; pop rbp; ret */
static const unsigned char samples_code[] = {0x55, 0x48, 0x89, 0xe5, 0x41, 0x57, 0x89, 0xf8,
                                             0x41, 0x5f, 0x5d, 0xc3};

int main(void) {
    unsigned char *image = VirtualAlloc(NULL, IMAGE, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
    assert(image);
    memset(image + AT - 16, 0xcc, 64);
    assert(bb_hooks_init(image, IMAGE) == 0);

    image[AT] = 0x90;
    assert(bb_blur_kernel_install() == 0);
    memcpy(image + AT, samples_code, sizeof(samples_code));
    _putenv("BB_KERNEL_CLAMP=0");
    assert(bb_blur_kernel_install() == 0);
    assert(!memcmp(image + AT, samples_code, sizeof(samples_code)));
    _putenv("BB_KERNEL_CLAMP=");
    assert(bb_blur_kernel_install() == 1);
    bb_hooks_seal();
    DWORD old;
    assert(VirtualProtect(image, IMAGE, PAGE_EXECUTE_READ, &old));
    FlushInstructionCache(GetCurrentProcess(), image, IMAGE);

    const SamplesFn samples = (SamplesFn)(image + AT);
    assert(samples(2) == 3);
    assert(samples(0) == 3);
    assert(samples(-1) == 3);
    assert(samples(3) == 3);
    assert(samples(7) == 7);
    puts("blur kernel: ok");
    return 0;
}
