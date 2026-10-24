"""src/frame_time_sites.inc against the 1.09 eboot and patches.py's preset writes: the table
regenerates from them, and under src/frame_time.c's rule (a site follows when its code is the
table's and its value over the preset's target is in the table's range) the 90 preset held to
60 FPS by the frame limiter advances every followed value by as much a second as the 60 preset;
held at 90 each value is the one patches.py writes today."""
import os
import re
import struct
import sys
import unittest
from pathlib import Path
from unittest import mock

from paths import ROOT

import patches as P

sys.path.insert(0, str(ROOT / 'tools'))
import frame_time_sites as T  # noqa: E402

GAME_ELF = Path(os.environ.get('BB_TEST_EBOOT_ELF') or ROOT / 'out/eboot.elf')
XML = ROOT / 'patches/Bloodborne.xml'
INC = ROOT / 'src/frame_time_sites.inc'
EB = P.EBOOT_BASE
ENTRY = re.compile(r'\{(0x[0-9a-f]+), (\d+), (BB_FT_\w+), (0x[0-9a-f]+), ([-0-9.e]+)f, ([-0-9.e]+)f, '
                   r'\{(\d+), (0x[0-9a-f]+)ull\}\}')
SWITCHES = ('BB_FRAME_STEP_FIX', 'BB_CLOTH_FIX', 'BB_CLOTH_UNCAPPED', 'BB_WIND_FIX', 'BB_CAMERA_FIX',
            'BB_EFFECT_RATE_FIX')
f32 = lambda v: struct.unpack('<f', struct.pack('<f', v))[0]


def table():
    out = []
    for m in ENTRY.finditer(INC.read_text(encoding='utf-8')):
        at, n, kind, constant, lo, hi, cn, ch = m.groups()
        out.append((int(at, 16), int(n), kind, int(constant, 16), float(lo), float(hi), int(cn), int(ch, 16)))
    return out


@unittest.skipUnless(GAME_ELF.is_file(), 'needs a prepared 1.09 eboot.elf (BB_TEST_EBOOT_ELF)')
class FrameTimePresets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.elf = GAME_ELF.read_bytes()
        cls.segments = P.eboot_segments(cls.elf)
        cls.sites = table()

    def image(self, fps, **settings):
        with mock.patch.dict(os.environ, {}), mock.patch('builtins.print'):
            for key in SWITCHES: os.environ.pop(key, None)
            names = P.fps_preset(fps, self.elf, XML, '01.09')
            writes = P.preset_writes(XML, names, fps, '01.09', self.segments, self.elf, settings)
        memory = {}
        for offset, data in writes:
            for i, b in enumerate(data): memory[offset + i] = b
        return lambda at, n: bytes(memory.get(o, P.eboot_bytes(self.elf, o, o + 1)[0]) for o in range(at - EB, at - EB + n))

    @staticmethod
    def target(read):
        if read(0x243487e, 5) != bytes.fromhex('41c7442418'): return 0.0  # frame_step.h bb_preset_target
        t, = struct.unpack('<f', read(0x2434883, 4))
        return t if f32(1 / 240) <= t < f32(1 / 30) else 0.0

    def followed(self, read):
        """{site: (kind, value)} for the sites src/frame_time.c takes in this image."""
        t = self.target(read)
        out = {}
        for at, n, kind, constant, lo, hi, cn, ch in self.sites:
            if T.code_hash(read(at, cn)) != ch: continue
            value, = struct.unpack('<f', read(at + n - 4, 4) if kind == 'BB_FT_STORE' else read(constant, 4))
            if kind == 'BB_FT_WEIGHT':
                ok = value > 0 and abs(value - f32(1 - (1 - f32(lo)) ** (30 * t))) <= 1e-6
            else:
                ok = value != 0 and lo <= f32(value / t) <= hi
            if ok: out[at] = (kind, value)
        return t, out

    @unittest.skipUnless(all(__import__('importlib').util.find_spec(m) for m in ('capstone', 'numpy')),
                         'needs capstone and numpy')
    def test_the_table_regenerates_from_the_eboot(self):
        self.assertEqual(T.generate(self.elf, XML), INC.read_text(encoding='utf-8'))

    def test_every_fixed_step_follows_at_60_and_90(self):
        steps = {at for at, n, kind, c, lo, hi, *_ in self.sites if kind != 'BB_FT_WEIGHT' and lo == 0.9999}
        for fps in ('60', '90'):
            t, got = self.followed(self.image(fps))
            self.assertEqual(t, f32(1 / int(fps)))
            self.assertEqual(steps - set(got), set(), fps)
            self.assertIn(0x1cbdb42, got)  # the turn step
            self.assertFalse([a for a, (k, _) in got.items() if k == 'BB_FT_WEIGHT'], fps)  # camera_fix off

    def test_the_90_preset_at_60_fps_steps_as_the_60_preset(self):
        t60, at60 = self.followed(self.image('60', camera_fix='1'))
        t90, at90 = self.followed(self.image('90', camera_fix='1'))
        self.assertEqual(set(at60), set(at90))
        step = f32(1 / 60)  # the frame limiter at 60: the cave's step at both presets
        for at, (kind, v90) in at90.items():
            v60 = at60[at][1]
            if kind == 'BB_FT_WEIGHT':
                self.assertAlmostEqual(1 - (1 - v90) ** (step / t90), 1 - (1 - v60) ** (step / t60), places=6)
            elif at == 0x1cbdb42:  # Kyo's turn step: 1.125 a second from 90 FPS++, 1.111 from 60 FPS++
                self.assertAlmostEqual(v90 * step / t90 / v60, 1.125 / (1 / 0.9), places=4)
            else:
                self.assertAlmostEqual(v90 * step / t90, v60, delta=abs(v60) * 1e-6)

    def test_120_and_144_follow_what_the_rate_base_gives_their_rate(self):
        for fps in ('120', '144'):
            read = self.image(fps)
            t, got = self.followed(read)
            self.assertEqual(t, f32(1 / int(fps)))
            for at, (kind, value) in got.items():
                if at != 0x1cbdb42 and kind == 'BB_FT_STORE': self.assertEqual(value, t)
            self.assertIn(0x1bf9b71, got)  # the physics world's step
            self.assertNotIn(0x131e607, got)  # a duration the rate base leaves at the game's 1/30

    def test_frame_step_fix_0_keeps_the_steps_fixed(self):
        t, got = self.followed(self.image('90', frame_step_fix='0'))
        self.assertFalse([a for a, (k, v) in got.items() if v == f32(1 / 60)])
        self.assertNotIn(0x1bf9b71, got)

    def test_uncapped_follows_its_1_240_steps_only(self):
        t, got = self.followed(self.image('uncap'))
        self.assertEqual(t, f32(1 / 240))
        self.assertTrue(got and all(v == t for k, v in got.values()))
        self.assertNotIn(0x2377d4a, got)  # the effects' step: 1/60 in the uncapped list

    def test_the_wind_and_the_cloth_hold_what_the_c_side_checks(self):
        load = P.WIND_STEP_LOAD
        for fps in ('90', '120', '144'):
            read = self.image(fps)
            t = self.target(read)
            rel, = struct.unpack('<i', read(load + 4, 4))
            self.assertEqual(load + 8 + rel, P.WIND_PACE)  # wind_pace.c paced()
            self.assertEqual(struct.unpack('<f', read(P.WIND_PACE, 4))[0], t * 0.5)
            slot = struct.unpack('<4f', read(P.CLOTH_STIFFNESS, 16))
            self.assertEqual(len(set(slot)), 1)
            self.assertLessEqual(abs(slot[0] - f32((60 * t) ** 2)), 1e-6)  # cloth_rate.c's want
        read = self.image('90', cloth_fix='0')
        self.assertNotEqual(read(P.CLOTH_SUBSTEPS + 0, 5), bytes.fromhex('bb01000000'))
        read = self.image('120', cloth_fix='0')
        slot, = struct.unpack('<f', read(P.CLOTH_STIFFNESS, 4))
        self.assertGreater(abs(slot - (60 / 120) ** 2), 1e-3)  # the 1.0 package: cloth_rate.c refuses


if __name__ == '__main__':
    unittest.main()
