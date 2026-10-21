#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""The GCN code of every shader program in the player's own game files, by program hash.

Programs live in dvdroot_ps4/shader/*.shaderbnd.dcx (.vpo/.ppo/... files) and in the game
executable. Each ends in an OrbShdr footer whose shader_hash is the hash the renderer keys its
cache on; the code starts at the container's 'Shdr' header + 16 + the 32-bit offset at 'Shdr' +
24, and is the footer's length long - exactly the bytes the game maps (checked against the
renderer's own dumps). Nothing is copied anywhere but the folder asked for.

  shader_code.py <game folder> <prepared eboot.elf> <output folder>
"""
from pathlib import Path
import shutil
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fromsoft import Bnd4, FormatError, dcx_decompress  # noqa: E402

FOOTER = b'OrbShdr'


COPY_SHADER = 6  # the footer's type: a geometry shader's copy shader, under the same hash


def programs(data):
    """(hash, type, code) of each program in a blob. A container's first program follows its
    'Shdr' header; a second one in the same container (a geometry shader's copy shader) has no
    header of its own and follows the previous program's footer."""
    previous_end = 0
    i = data.find(FOOTER)
    while i >= 0:
        shader_hash = struct.unpack_from('<Q', data, i + 16)[0]
        bits = struct.unpack_from('<I', data, i + 8)[0]
        length, kind = (bits >> 8) & 0xffffff, (bits >> 2) & 0xf
        header = data.rfind(b'Shdr', max(previous_end, i - 0x10000), i)
        while header >= 3 and data[header - 3:header] == b'Orb':  # inside a footer, not a header
            header = data.rfind(b'Shdr', max(previous_end, i - 0x10000), header)
        start = header + 16 + struct.unpack_from('<I', data, header + 24)[0] if header >= 0 else previous_end
        if previous_end <= start and start + length <= i and length % 4 == 0:
            yield shader_hash, kind, data[start:start + length]
        previous_end = i + 28
        i = data.find(FOOTER, i + 1)


def collect(game, eboot):
    found = {}
    for archive in sorted((Path(game) / 'dvdroot_ps4' / 'shader').glob('*.shaderbnd*.dcx')):
        # A damaged archive only leaves its shaders to be translated in game, as without this.
        try:
            files = Bnd4(dcx_decompress(archive.read_bytes())).files
        except (OSError, FormatError, IndexError, struct.error) as error:
            print(f'shader code: skipped {archive.name}: {error}', file=sys.stderr)
            continue
        for data in files:
            for shader_hash, kind, code in programs(data):
                found.setdefault((shader_hash, kind == COPY_SHADER), code)
    if eboot:
        for shader_hash, kind, code in programs(Path(eboot).read_bytes()):
            found.setdefault((shader_hash, kind == COPY_SHADER), code)
    return found


def extract(game, eboot, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    found = collect(game, eboot)
    for (shader_hash, copy), code in found.items():
        (out / f'{shader_hash:016x}{".copy" if copy else ""}.bin').write_bytes(code)
    print(f'shader code: {len(found)} programs')


def prebuild(game, eboot, out):
    """Extract once, again only when the game files or this extractor changed.
    Returns 0 on success; a damaged/missing eboot removes the partial output."""
    out = Path(out)
    sources = sorted((Path(game) / 'dvdroot_ps4' / 'shader').glob('*.shaderbnd*.dcx'))
    sources += [Path(eboot), Path(__file__)]
    stamp = '\n'.join(f'{p.name} {p.stat().st_size} {int(p.stat().st_mtime)}'
                      for p in sources if p.is_file())
    try:
        current = (out / 'stamp.txt').read_text(encoding='utf-8') == stamp
    except OSError:
        current = False
    if current:
        return 0
    shutil.rmtree(out, ignore_errors=True)
    try:
        found = collect(game, eboot)
    except (OSError, FormatError, IndexError, struct.error) as error:
        print(f'shader code: {error}', file=sys.stderr)
        shutil.rmtree(out, ignore_errors=True)
        return 1
    out.mkdir(parents=True, exist_ok=True)
    for (shader_hash, copy), code in found.items():
        (out / f'{shader_hash:016x}{".copy" if copy else ""}.bin').write_bytes(code)
    (out / 'stamp.txt').write_text(stamp, encoding='utf-8')
    print(f'shader code: {len(found)} programs')
    return 0


def main(argv):
    # --prebuild <game> <eboot.elf> <out>: the launcher's shader pre-build, re-run only when
    # its inputs changed (the output folder's stamp).
    if argv and argv[0] == '--prebuild':
        return prebuild(argv[1], argv[2], argv[3])
    extract(argv[0], argv[1], argv[2])
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
