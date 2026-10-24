from paths import ROOT
import base64
import os
from pathlib import Path
import struct
import unittest

import fromsoft
import prompt_icons

PACKS = ROOT / 'launcher' / 'assets' / 'prompts'
# BB_TEST_GAME_DIR=<CUSA03173>: also check the real 1.09 menu/common.tpf.dcx.
GAME = Path(os.environ['BB_TEST_GAME_DIR']) if os.environ.get('BB_TEST_GAME_DIR') else None
GLYPHS = ('Cancel', 'OK', 'R_L', 'R_U', 'L1', 'L2', 'L3', 'R1', 'R2', 'R3', 'LS', 'RS',
          'L_U', 'L_D', 'L_LR', 'L_UD', 'L_UDLR', 'Start', 'TP_L', 'TP_R')


def tpf(textures):
    """A PS4 TPF of BC7 textures with one mip: [(name, width, height)], data filled with each
    texture's index so a test can tell them apart."""
    entries_at, count = 0x10, len(textures)
    names_at = entries_at + 0x24 * count
    names = b''.join(n.encode('utf-16-le') + b'\0\0' for n, _, _ in textures)
    data_at = names_at + len(names)
    data_at += -data_at % 0x80
    header, entries, body, name_at = b'', b'', b'', names_at
    for i, (name, width, height) in enumerate(textures):
        size = width * height
        entries += struct.pack('<IiBBBBhhiiIii', data_at + len(body), size, 102, 0, 1, 0, width, height,
                               1, 0xd, name_at, 0, prompt_icons.BC7)
        name_at += len(name.encode('utf-16-le')) + 2
        body += bytes([i + 1]) * size
    header = b'TPF\0' + struct.pack('<IIBBBB', len(body), count, 4, 3, 1, 0)
    return header + entries + names + b'\0' * (data_at - names_at - len(names)) + body


def common_tpf(atlas=(1024, 512)):
    return tpf([(f'KG_{g}', 32, 32) for g in GLYPHS] + [('KG_TM_Registered', 16, 16),
                                                     ('MENU_Common_00091', *atlas)])


class PromptIconTests(unittest.TestCase):
    def test_tiled_block_order(self):
        # 8x8-block tiles in row order, Morton order inside a tile: x bits even, y bits odd.
        self.assertEqual(prompt_icons._tiled(0, 0, 256), 0)
        self.assertEqual(prompt_icons._tiled(1, 0, 256), 16)
        self.assertEqual(prompt_icons._tiled(0, 1, 256), 32)
        self.assertEqual(prompt_icons._tiled(2, 0, 256), 64)
        self.assertEqual(prompt_icons._tiled(7, 7, 256), 63 * 16)
        self.assertEqual(prompt_icons._tiled(8, 0, 256), 64 * 16)
        self.assertEqual(prompt_icons._tiled(0, 8, 256), 32 * 64 * 16)

    def test_packs_cover_every_glyph(self):
        for name in ('xbox.json', 'keyboard.json'):
            pack = prompt_icons.load(PACKS / name)
            self.assertEqual(set(pack['textures']), {f'KG_{g}' for g in GLYPHS})
            for data in pack['textures'].values():
                self.assertEqual(len(base64.b64decode(data)), 64 * 16)
            atlas = pack['atlas']
            self.assertEqual(len(base64.b64decode(atlas['blocks'])), atlas['w'] * atlas['h'] * 16)

    def test_only_the_glyph_textures_change(self):
        original = common_tpf()
        packed = fromsoft.dcx_compress(original)
        pack = prompt_icons.load(PACKS / 'xbox.json')
        result = fromsoft.dcx_decompress(prompt_icons.apply(packed, pack))
        self.assertEqual(len(result), len(original))
        found = prompt_icons.textures(original)
        self.assertNotIn('KG_TM_Registered', pack['textures'])
        for name, data in pack['textures'].items():
            offset, width, _ = found[name]
            blocks = base64.b64decode(data)
            for i in range(64):
                at = offset + prompt_icons._tiled(i % 8, i // 8, width // 4)
                self.assertEqual(result[at:at + 16], blocks[i * 16:(i + 1) * 16])
        offset, width, height = found['MENU_Common_00091']
        atlas = pack['atlas']
        inside = {(offset + prompt_icons._tiled(atlas['x'] + c, atlas['y'] + r, width // 4)) // 16
                  for r in range(atlas['h']) for c in range(atlas['w'])}
        for block in range(offset // 16, (offset + width * height) // 16):
            if block not in inside:
                self.assertEqual(result[block * 16:block * 16 + 16], original[block * 16:block * 16 + 16])
        others = [found[n] for n in found if n not in pack['textures'] and n != 'MENU_Common_00091']
        for offset, width, height in others:
            self.assertEqual(result[offset:offset + width * height], original[offset:offset + width * height])
        self.assertEqual(result[:found['KG_Cancel'][0]], original[:found['KG_Cancel'][0]])

    def test_refuses_a_prompt_mod_or_another_file(self):
        pack = prompt_icons.load(PACKS / 'keyboard.json')
        with self.assertRaisesRegex(fromsoft.FormatError, 'MENU_Common_00091'):
            prompt_icons.apply(fromsoft.dcx_compress(common_tpf(atlas=(2048, 1024))), pack)
        with self.assertRaises(fromsoft.FormatError):
            prompt_icons.apply(fromsoft.dcx_compress(b'BND4' + b'\0' * 60), pack)

    @unittest.skipUnless(GAME, 'BB_TEST_GAME_DIR not set')
    def test_real_menu_file(self):
        packed = (GAME / 'dvdroot_ps4' / 'menu' / 'common.tpf.dcx').read_bytes()
        original = fromsoft.dcx_decompress(packed)
        found = prompt_icons.textures(original)
        for name in ('xbox.json', 'keyboard.json'):
            pack = prompt_icons.load(PACKS / name)
            result = fromsoft.dcx_decompress(prompt_icons.apply(packed, pack))
            allowed = [found[n] for n in [*pack['textures'], 'MENU_Common_00091']]
            changed = [i for i, (a, b) in enumerate(zip(original, result)) if a != b]
            self.assertTrue(changed)
            self.assertTrue(all(any(o <= i < o + w * h for o, w, h in allowed) for i in changed))


if __name__ == '__main__':
    unittest.main()
