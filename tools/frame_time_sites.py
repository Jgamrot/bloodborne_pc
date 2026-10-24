"""Writes src/frame_time_sites.inc (src/frame_time.c's sites) from the 1.09 eboot.elf and patches/Bloodborne.xml.

The fixed frame steps are the 4-byte values "90 FPS++" turns from the game's 1/30 into 1/60 (patches.py
frame_steps; the cave's own 0x4d29170 too), less the frame-time manager's targets, the task step the
cave computes and the wind's pace (wind_pace.c). A step in an instruction is followed where the
instruction stores it into a stack local (a step-info built for each call); a store into an object
(an initialisation) keeps its value. A step in .rodata is followed by its rip-relative scalar loads
the list leaves as they are.
Only lengths and hashes of the game's code go into the table (code_check.h).

python tools/frame_time_sites.py ELF [--xml patches/Bloodborne.xml] [--out src/frame_time_sites.inc]
(needs numpy and capstone)
"""
import argparse
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import patches as P  # noqa: E402

EB = P.EBOOT_BASE
THIRTIETH = struct.pack('<f', 1 / 30)
SIXTIETH = struct.pack('<f', 1 / 60)
# The frame-time manager's targets (sub_2434520's and sub_2434770's [r12/r13+0x18]), the task step
# the FPS++ cave replaces (0x2418e36), the wind's pace (wind_pace.c).
OWN = {0x243460c, 0x243485f, 0x2434883, 0x24348b8, 0x2418e39, 0x4d29e74}
SFX_STEP = 0x4d29170  # SprjSfx::Update's step: 1/fps in the lists themselves
CODE_END = 0x3000000  # the game's functions end before it (the last at 0x2fbe370); .rodata follows
# Not steps a list writes as 1/60, followed with their own rule: the turn and stamina step the lists
# fix (0x1cbdb42, 1.111/fps at 60, 1.125/fps above), the replay ghosts' fade (-+3/fps a frame), and
# with camera_fix the follow camera's two eases (1 - (1 - w)^(30/fps), w the game's at 30).
TURN = (0x1cbdb42, '90 FPS++', 1.11, 1.126)
SCALED = {0x4d27fd4: (-3.0001, -2.9999), 0x4d27fe0: (2.9999, 3.0001)}
WEIGHTS = {0x4d25e68: 0.1, 0x4d25e94: 1 / 30}
STORE, LOAD, WEIGHT = 'BB_FT_STORE', 'BB_FT_LOAD', 'BB_FT_WEIGHT'


def code_hash(data):
    """code_check.h's bb_code_hash (no TCB loads in these sites)."""
    h = 0xcbf29ce484222325
    for b in data:
        h = ((h ^ b) * 0x100000001b3) & 0xffffffffffffffff
    return h


class Code:
    def __init__(self, elf):
        import capstone
        import numpy as np
        self.cs, self.np = capstone, np
        self.elf = elf
        self.md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
        self.md.detail = True
        phoff, = struct.unpack_from('<Q', elf, 0x20)
        phentsize, phnum = struct.unpack_from('<HH', elf, 0x36)
        for i in range(phnum):
            kind, flags, off, vaddr, _, filesz, _, _ = struct.unpack_from('<IIQQQQQQ', elf, phoff + i * phentsize)
            if kind == 1 and flags & 1:
                self.text_va, self.text = vaddr, elf[off:off + filesz]
        self.ends = []  # (byte offset in the dword view, rip target of a disp32 there + 4)
        for k in range(4):
            m = (len(self.text) - k) // 4
            d = np.frombuffer(self.text, dtype='<i4', count=m, offset=k).astype(np.int64)
            self.ends.append((k, d + (np.arange(m, dtype=np.int64) * 4 + k + self.text_va + 4)))

    def insn(self, at):
        found = list(self.md.disasm(P.eboot_bytes(self.elf, at, at + 16), at, 1))
        return found[0] if found else None

    def store(self, site):
        """The mov dword [mem], imm32 whose immediate is at `site` (an image offset): the instruction
        when it stores into [rbp+disp], False for another memory operand, None when there is none."""
        x86 = self.cs.x86
        for start in range(site - 8, site - 2):
            i = self.insn(start)
            if (i and i.address + i.size == site + 4 and i.mnemonic == 'mov' and len(i.operands) == 2
                    and i.operands[0].type == x86.X86_OP_MEM and i.operands[0].size == 4
                    and i.operands[1].type == x86.X86_OP_IMM):
                m = i.operands[0].mem
                return i if m.base == x86.X86_REG_RBP and m.index == x86.X86_REG_INVALID else False
        return None

    def loads(self, constant):
        """The 8-byte VEX scalar instructions reading the dword at `constant` rip-relative."""
        out = []
        for k, ends in self.ends:
            for j in self.np.nonzero(ends == constant)[0]:
                disp_at = int(j) * 4 + k + self.text_va
                i = self.insn(disp_at - 4)
                if (i and i.size == 8 and i.bytes[0] == 0xc5 and i.address + 8 == disp_at + 4
                        and any(op.type == self.cs.x86.X86_OP_MEM and op.size == 4
                                and op.mem.base == self.cs.x86.X86_REG_RIP for op in i.operands)):
                    out.append(i)
        return sorted(out, key=lambda i: i.address)


def list_writes(xml, name, elf):
    segments = P.eboot_segments(elf)
    return P.compile_patches(xml, [name], '01.09', segments)


def frame_steps(xml, elf):
    """The image offsets of the values 90 FPS++ turns from 1/30 into 1/60, and SFX_STEP."""
    sites = {offset for offset, data in list_writes(xml, '90 FPS++', elf)
             if data == SIXTIETH and P.eboot_bytes(elf, offset, offset + 4) == THIRTIETH}
    return sorted(sites - {a - EB for a in OWN} | {SFX_STEP - EB})


def entry(i, kind, constant, lo, hi, code):
    text = f'    {{{i.address + EB:#010x}, {i.size}, {kind}, {constant:#010x}, {float(lo)!r}f, {float(hi)!r}f, ' \
           f'{{{len(code)}, {code_hash(code):#018x}ull}}}},'
    # What it does, not its bytes: the constant it reads, or the local it stores the value into.
    operand = i.op_str.split(', ')
    if kind == STORE:
        what = f'{i.mnemonic} {operand[0]}, value'
    else:
        what = f'{i.mnemonic} {", ".join(operand[:-1])}, [{constant:#x}]'
    return f'{text}  /* {what.replace("dword ptr ", "")} */'


def generate(elf, xml):
    code = Code(elf)
    lines, left = [], []
    # A load the list rewrites (0x21bc308: its jump to the cave that multiplies by the frame time).
    written = [(o, o + len(d)) for o, d in list_writes(xml, '90 FPS++', elf)]
    rewritten = lambda i: any(lo < i.address + i.size and i.address < hi for lo, hi in written)
    for site in frame_steps(xml, elf):
        if site < CODE_END - EB and (s := code.store(site)) is not None:
            if s is False:
                left.append(f'{site + EB:#x}')
                continue
            lines.append(entry(s, STORE, 0, 0.9999, 1.0001, bytes(s.bytes[:-4])))
            continue
        for i in code.loads(site):
            if not rewritten(i): lines.append(entry(i, LOAD, site + EB, 0.9999, 1.0001, bytes(i.bytes)))
    at, name, lo, hi = TURN
    data = dict(list_writes(xml, name, elf))[at - EB]
    turn = next(code.md.disasm(data, at - EB, 1))
    lines.append(entry(turn, STORE, 0, lo, hi, data[:turn.size - 4]))
    for constant, (lo, hi) in SCALED.items():
        lines += [entry(i, LOAD, constant, lo, hi, bytes(i.bytes)) for i in code.loads(constant - EB)]
    for constant, w in WEIGHTS.items():
        lines += [entry(i, WEIGHT, constant, w, 0, bytes(i.bytes)) for i in code.loads(constant - EB)]
    head = ['/* Generated by tools/frame_time_sites.py from the 1.09 eboot and patches/Bloodborne.xml: src/frame_time.c\'s',
            ' * sites. {instruction (Binary Ninja), length, kind, constant read, the value over the preset\'s',
            ' * frame time (a weight: the game\'s at 30), the bytes checked (a store: those before its immediate)}.',
            f' * Stores into objects, kept: {", ".join(left)}. */']
    return '\n'.join(head + lines) + '\n'


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('elf', type=Path)
    p.add_argument('--xml', type=Path, default=ROOT / 'patches/Bloodborne.xml')
    p.add_argument('--out', type=Path, default=ROOT / 'src/frame_time_sites.inc')
    a = p.parse_args()
    a.out.write_text(generate(a.elf.read_bytes(), a.xml), encoding='utf-8', newline='\n')


if __name__ == '__main__':
    main()
