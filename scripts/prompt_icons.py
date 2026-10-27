# SPDX-License-Identifier: GPL-2.0-or-later
"""Button prompt images written into the player's own menu/common.tpf.dcx.

The images (launcher/assets/prompts/<pack>.json, made by tools/prompts/make_prompt_icons.py from
Kenney's CC0 Input Prompts) replace the game's KG_* glyph textures and the three HUD glyphs of
MENU_Common_00091 block for block, so every texture keeps its size and only those bytes change.
PS4 textures store their 4x4 blocks in 8x8-block tiles, Morton order inside each tile.
"""
import base64
import json
import struct

from fromsoft import FormatError, dcx_compress, dcx_decompress

BC7 = 98  # DXGI_FORMAT_BC7_UNORM
BLOCK = 16


def textures(tpf):
    """{name: (offset, width, height)} of a PS4 TPF's BC7 textures with one mip level."""
    if tpf[:4] != b'TPF\0':
        raise FormatError('not a TPF texture file')
    count, platform, _, encoding = struct.unpack_from('<IBBB', tpf, 8)
    if platform != 4 or encoding != 1:
        raise FormatError('not the PS4 texture file of Bloodborne')
    found, at = {}, 0x10
    for _ in range(count):
        offset, size, _, _, mips, _, width, height, _, _, name_at, floats, dxgi = \
            struct.unpack_from('<IiBBBBhhiiIii', tpf, at)
        at += 0x24
        if floats:
            at += 8 + struct.unpack_from('<i', tpf, at + 4)[0]
        end = name_at
        while end < len(tpf) and tpf[end:end + 2] != b'\0\0':
            end += 2
        name = tpf[name_at:end].decode('utf-16-le')
        if dxgi == BC7 and mips == 1 and size == width * height:
            found[name] = (offset, width, height)
    return found


def _tiled(bx, by, blocks_wide):
    tile = (by // 8) * ((blocks_wide + 7) // 8) + bx // 8
    x, y, morton = bx % 8, by % 8, 0
    for bit in range(3):
        morton |= ((x >> bit) & 1) << (2 * bit) | ((y >> bit) & 1) << (2 * bit + 1)
    return (tile * 64 + morton) * BLOCK


def _write(tpf, offset, width, blocks, x, y, w, h):
    if len(blocks) != w * h * BLOCK:
        raise FormatError('prompt image data has the wrong size')
    for row in range(h):
        for col in range(w):
            at = offset + _tiled(x + col, y + row, width // 4)
            tpf[at:at + BLOCK] = blocks[(row * w + col) * BLOCK:(row * w + col + 1) * BLOCK]


def apply(packed, pack):
    """The player's common.tpf.dcx (bytes) with `pack`'s images (a loaded <pack>.json)."""
    tpf = bytearray(dcx_decompress(packed))
    found = textures(tpf)
    atlas = pack['atlas']
    wanted = {**{name: (32, 32) for name in pack['textures']}, atlas['name']: (1024, 512)}
    for name, size in wanted.items():
        if name not in found or found[name][1:] != size:
            raise FormatError(f'menu/common.tpf.dcx has no {size[0]}x{size[1]} {name}: '
                              'not the game 1.09 file, or already a prompt mod')
    for name, data in pack['textures'].items():
        offset, width, height = found[name]
        _write(tpf, offset, width, base64.b64decode(data), 0, 0, width // 4, height // 4)
    offset, width, _ = found[atlas['name']]
    _write(tpf, offset, width, base64.b64decode(atlas['blocks']), atlas['x'], atlas['y'], atlas['w'], atlas['h'])
    return dcx_compress(bytes(tpf), template=packed)


def load(path):
    with open(path, encoding='utf-8') as file:
        return json.load(file)
