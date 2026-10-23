from paths import ROOT
from contextlib import redirect_stderr, redirect_stdout
import io
import os
import struct
import tempfile
import unittest
from unittest import mock
import xml.etree.ElementTree as ET
from pathlib import Path

from patches import (EBOOT_BASE, FIXES, FPS_PRESETS, OUTPUT_SIZE, RESOLUTION_TEMPLATE, SCENE_HEIGHT,
                     SCENE_WIDTH, UI_HEIGHT, UI_WIDTH, compile_patches,
                     render_size, resolution_writes, scaled_sizes, output_size, effect_patches,
                     validate_patch_requirements, external_patches, external_selection,
                     compile_external, frame_rate_fixes, sprint_fix_enabled, eboot_bytes,
                     eboot_matches_patches, patch_fingerprint, patch_sites, game_app_version,
                     eboot_is_109, SCALED_BASE, SCALED_FPS, SCALED_VALUES, fps_preset, rate_scaled,
                     eboot_segments, rate_corrections, camera_value, EFFECT_RATE_SITES,
                     CLOTH_STIFFNESS, CLOTH_LEFT_OUT, WIND_STEP, WIND_LOADS, CAMERA_FIELDS, frame_steps, preset_writes, with_external,
                     HEAP_PATCH, HEAP_GUARD, pc_heaps_enabled, site_matches,
                     HASH_GUARDS, guarded_patches)

XML = ROOT / 'patches/Bloodborne.xml'
SEGMENTS = [(0, 0x6000000)]


def immediate(writes, address):
    # The XML splits a 9-byte MOV imm32 + NOP into 4+4+1 byte writes.
    data = bytearray(9)
    for offset, value in writes:
        if address <= offset < address + 9:
            data[offset-address:offset-address+len(value)] = value
    assert data[5:] == b'\x0f\x1f\x40\x00'
    return data[0], struct.unpack_from('<I', data, 1)[0]


class NativeUiTests(unittest.TestCase):
    def test_presets_keep_ui_native(self):
        for preset, expected in [(1, (1280, 720)), (2, (1130, 636)),
                                 (3, (960, 540)), (4, (640, 360))]:
            with self.subTest(preset=preset):
                size = render_size({'upscaler': 'fsr3', 'preset': str(preset)})
                self.assertEqual(size, expected)
                writes = resolution_writes(XML, size, '01.09', SEGMENTS)
                self.assertEqual(immediate(writes, SCENE_WIDTH), (0xB8, size[0]))
                self.assertEqual(immediate(writes, SCENE_HEIGHT), (0xB8, size[1]))
                self.assertEqual(immediate(writes, UI_WIDTH), (0xB8, OUTPUT_SIZE[0]))
                self.assertEqual(immediate(writes, UI_HEIGHT), (0xB9, OUTPUT_SIZE[1]))

    def test_explicit_scene_resolution_keeps_native_ui(self):
        writes = resolution_writes(XML, (800, 450), '01.09', SEGMENTS)
        self.assertEqual(immediate(writes, SCENE_WIDTH)[1], 800)
        self.assertEqual(immediate(writes, UI_WIDTH)[1], 1920)
        self.assertEqual(immediate(writes, UI_HEIGHT)[1], 1080)

    def test_coordinate_and_aspect_fixes_are_preserved(self):
        original = compile_patches(XML, [RESOLUTION_TEMPLATE], '01.09', SEGMENTS)
        modified = resolution_writes(XML, (960, 540), '01.09', SEGMENTS)
        self.assertEqual(len(original), len(modified))
        changed = {SCENE_WIDTH, SCENE_HEIGHT, UI_WIDTH, UI_HEIGHT}
        self.assertEqual([w for w in original if w[0] not in changed],
                         [w for w in modified if w[0] not in changed])

    def test_unexpected_or_missing_ui_instruction_is_rejected(self):
        for remove in (False, True):
            tree = ET.parse(XML)
            for meta in tree.getroot().iter('Metadata'):
                if meta.get('Name') == RESOLUTION_TEMPLATE and meta.get('AppVer') == '01.09':
                    patch_list = meta.find('PatchList')
                    for line in list(patch_list):
                        if int(line.get('Address'), 0) == UI_WIDTH + EBOOT_BASE:
                            if remove:
                                patch_list.remove(line)
                            else:
                                line.set('Value', '0x000500B9')
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'patch.xml'
                tree.write(path)
                with self.assertRaises(ValueError):
                    resolution_writes(path, (960, 540), '01.09', SEGMENTS)

    def test_native_and_disabled_upscaler_need_no_resolution_patch(self):
        self.assertIsNone(render_size({'preset': '0'}))
        self.assertIsNone(render_size({'upscaler': 'off', 'preset': '3'}))

    def test_output_other_than_1080p_scales_the_scene(self):
        self.assertIsNone(scaled_sizes({'output_res': '1920x1080', 'preset': '2'}))
        # Steam Deck: below 1080p the scene is still the preset's fraction of the output.
        for preset, expected in [(0, (1280, 720)), (2, (752, 424)), (4, (426, 240))]:
            with self.subTest(preset=preset):
                self.assertEqual(scaled_sizes({'output_res': '1280x720', 'preset': str(preset)}),
                                 (expected, (1280, 720)))
        self.assertEqual(scaled_sizes({'output_res': '3840x2160', 'preset': '3'}),
                         ((1916, 1078), (3840, 2160)))
        # TAA is native-only and uses the live host targets.
        self.assertIsNone(scaled_sizes({'output_res': '1280x720', 'upscaler': 'taa', 'preset': '3'}))


    def test_arbitrary_aspect_and_native_movie_viewport(self):
        for out in ((2560,1080), (5120,2160), (1280,800), (1920,1200), (1080,1920), (5000,2000)):
            settings={'output_res': f'{out[0]}x{out[1]}', 'upscaler':'dlss', 'preset':'1'}
            scene, actual=scaled_sizes(settings)
            self.assertEqual(actual, out)
            writes=resolution_writes(XML,scene,'01.09',SEGMENTS,ui=out)
            self.assertEqual(immediate(writes, UI_WIDTH)[1],out[0])
            self.assertEqual(immediate(writes, UI_HEIGHT)[1],out[1])
            # The stage-coordinate constants still describe 1920x1080.
            self.assertEqual(immediate(writes,0x019E83AF-EBOOT_BASE)[1],1920)
        self.assertEqual(scaled_sizes({'output_res':'1280x800','upscaler':'taa'}),
                         ((1280,800),(1280,800)))

    def test_invalid_custom_resolutions_fall_back(self):
        for text in ('0x0','999999x1080','1921x1080','1920x143','bad','-10x1080'):
            self.assertEqual(output_size({'output_res':text}),OUTPUT_SIZE)


class FpsPatchTests(unittest.TestCase):
    def test_fps_physics_write_preserves_unrelated_instruction(self):
        # 60 FPS++ keeps the game's own 1/30 step: the file has no write for it there.
        for preset, value in [('90 FPS++', '610B363C'), ('Uncap FPS++', '8988083C')]:
            with self.subTest(preset=preset):
                writes = compile_patches(XML, [preset], '01.09', SEGMENTS)
                self.assertIn((0x00f383ca - EBOOT_BASE, bytes.fromhex(value)), writes)
                self.assertNotIn(0x011383ca - EBOOT_BASE, [at for at, data in writes])

    def test_fps_presets_set_the_physics_step_per_frame_rate(self):
        # shadPS4's maintained patch values (upstream be1cde3): 1/30 at 60 FPS (the game's own),
        # 1/90 at 90 FPS, 1/120 uncapped. The old values were 1/15, 1/30 and 1/240.
        for preset, step in [('90 FPS++', 90), ('Uncap FPS++', 120)]:
            with self.subTest(preset=preset):
                writes = dict(compile_patches(XML, [preset], '01.09', SEGMENTS))
                value = struct.unpack('<f', writes[0x00f383ca - EBOOT_BASE])[0]
                self.assertAlmostEqual(1 / value, step, places=2)
        # 60 FPS++ leaves the game's 1/30 in place (patches/Bloodborne.xml keeps no game bytes).
        self.assertNotIn(0x00f383ca - EBOOT_BASE, dict(compile_patches(XML, ['60 FPS++'], '01.09', SEGMENTS)))

    def test_other_versions_keep_their_xml_addresses(self):
        tree = ET.parse(XML)
        for meta in tree.getroot().iter('Metadata'):
            if meta.get('Name') == '90 FPS++' and meta.get('AppVer') == '01.09':
                meta.set('AppVer', '01.08')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'patch.xml'
            tree.write(path)
            writes = compile_patches(path, ['90 FPS++'], '01.08', SEGMENTS)
            self.assertIn(0x011383ca - EBOOT_BASE, [at for at, data in writes])
            self.assertNotIn(0x00f383ca - EBOOT_BASE, [at for at, data in writes])


# A prepared 1.09 eboot.elf (prepare.py's out/eboot.elf, or BB_TEST_EBOOT_ELF): the tests that
# check sites against the game's own code skip without one.
GAME_ELF = Path(os.environ.get('BB_TEST_EBOOT_ELF') or ROOT / 'out/eboot.elf')


class ScaledFpsTests(unittest.TestCase):
    """120 and 144: 90 FPS++ (rate base) with its frame-rate values for the rate."""
    def base(self):
        return compile_patches(XML, [SCALED_BASE], '01.09', SEGMENTS)

    def test_presets_use_the_base(self):
        self.assertEqual(SCALED_FPS, {'120': 120, '144': 144})
        names = [m.get('Name') for m in ET.parse(XML).getroot().iter('Metadata')]
        self.assertEqual(names.count(SCALED_BASE), 1)

    def test_90_is_the_list_as_it_is(self):
        self.assertEqual(rate_scaled(self.base(), 90), self.base())

    def test_120_and_144_values(self):
        base = dict(self.base())
        for fps in (120, 144):
            with self.subTest(fps=fps):
                writes = rate_scaled(self.base(), fps)
                self.assertEqual(len(writes), len(base))
                scaled = dict(writes)
                f = lambda address, at=0: struct.unpack_from('<f', scaled[address - EBOOT_BASE], at)[0]
                self.assertAlmostEqual(f(0x0F383CA), 1 / fps, places=7)          # physics step
                self.assertAlmostEqual(f(0x1CBDB42, 6), 1.125 / fps, places=7)   # stamina
                self.assertAlmostEqual(f(0x4D29170), 1 / fps, places=7)
                self.assertEqual([f(0x4CF6420, i) for i in (0, 4, 8, 12)], [f(0x4CF6420)] * 4)
                self.assertAlmostEqual(f(0x4CF6420), 3 / fps, places=7)
                self.assertAlmostEqual(f(0x4D27FD4), -3 / fps, places=7)
                limiter = scaled[0x2C012CC - EBOOT_BASE]
                self.assertEqual(struct.unpack_from('<I', limiter, 2)[0], {120: 8000, 144: 6500}[fps])
                self.assertEqual(struct.unpack_from('<I', limiter, 9)[0], {120: 8000, 144: 6500}[fps])
                self.assertEqual(struct.unpack('<i', scaled[0x1929676 - EBOOT_BASE])[0], fps // 6)
                self.assertEqual(struct.unpack('<i', scaled[0x192C405 - EBOOT_BASE])[0], fps // 3)
                self.assertEqual(struct.unpack_from('<I', scaled[0x25629F0 - EBOOT_BASE], 1)[0], 990000 // fps)
                # Everything else is the 90 FPS++ list's own bytes.
                changed = {a for a in base if base[a] != scaled[a]}
                self.assertLessEqual({a + EBOOT_BASE for a in changed}, set(SCALED_VALUES))
                for a in changed:  # only the value fields, never the instructions around them
                    fields = SCALED_VALUES[a + EBOOT_BASE]
                    for i, (old, new) in enumerate(zip(base[a], scaled[a])):
                        if old != new:
                            self.assertTrue(any(at <= i < at + struct.calcsize(fmt) for at, fmt, _ in fields))

    def test_another_list_under_the_name_is_refused(self):
        for change in ('value', 'missing'):
            with self.subTest(change=change):
                writes = self.base()
                at = [i for i, (o, _) in enumerate(writes) if o == 0x0F383CA - EBOOT_BASE][0]
                if change == 'value':
                    writes[at] = (writes[at][0], struct.pack('<f', 1 / 60))
                else:
                    del writes[at]
                with self.assertRaises(ValueError):
                    rate_scaled(writes, 120)

    def test_other_code_gets_no_scaled_preset(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(fps_preset('120', fake_elf(0x400000, bytes(64)), XML, '01.09'), [])
        self.assertEqual(fps_preset('90', b'', XML, '01.09'), ['90 FPS++'])

    @unittest.skipUnless(GAME_ELF.is_file(), 'needs a prepared 1.09 eboot.elf (BB_TEST_EBOOT_ELF)')
    def test_game_matches_and_the_base_keeps_no_game_bytes(self):
        elf = GAME_ELF.read_bytes()
        self.assertEqual(fps_preset('144', elf, XML, '01.09'), [SCALED_BASE])
        for offset, data in compile_patches(XML, [SCALED_BASE], '01.09', eboot_segments(elf)):
            self.assertNotEqual(eboot_bytes(elf, offset, offset + len(data)), data, hex(offset + EBOOT_BASE))


class RateCorrectionTests(unittest.TestCase):
    """High-FPS corrections (Awakenchan/BloodBorneButPc): effect rate, cloth, camera."""
    def corrected(self, fps, settings=None, env=None):
        writes = rate_scaled(compile_patches(XML, [SCALED_BASE], '01.09', SEGMENTS), fps)
        with mock.patch.dict('os.environ', env or {}, clear=True), redirect_stdout(io.StringIO()):
            return writes, rate_corrections(writes, fps, None, settings or {})

    def test_effects_keep_the_games_rate(self):
        writes, out = self.corrected(120)
        sites = {a - EBOOT_BASE for a in EFFECT_RATE_SITES}
        self.assertTrue(sites <= dict(writes).keys())
        self.assertFalse(sites & dict(out).keys())
        _, out = self.corrected(120, env={'BB_EFFECT_RATE_FIX': '0'})
        self.assertTrue(sites <= dict(out).keys())
        _, out = self.corrected(120, settings={'effect_rate_fix': '0'})
        self.assertTrue(sites <= dict(out).keys())

    def test_cloth_stiffness_and_the_1_0_sites_above_60(self):
        for fps in (120, 144):
            with self.subTest(fps=fps):
                writes, out = self.corrected(fps)
                out = dict(out)
                self.assertEqual(struct.unpack('<4f', out[CLOTH_STIFFNESS - EBOOT_BASE]),
                                 (struct.unpack('<f', struct.pack('<f', (60 / fps) ** 2))[0],) * 4)
                left = [o for o, _ in writes if any(lo <= o + EBOOT_BASE < hi for lo, hi in CLOTH_LEFT_OUT)]
                self.assertTrue(left)
                self.assertFalse(set(left) & out.keys())
        writes, out = self.corrected(144, env={'BB_CLOTH_FIX': '0'})
        self.assertEqual(dict(out)[CLOTH_STIFFNESS - EBOOT_BASE], dict(writes)[CLOTH_STIFFNESS - EBOOT_BASE])

    def test_wind_step_follows_the_rate(self):
        at = WIND_STEP - EBOOT_BASE
        elf = fake_elf(at, struct.pack('<f', 1 / 60))

        def corrected(writes, fps, env=None, image=elf):
            with mock.patch.dict('os.environ', env or {}, clear=True), redirect_stdout(io.StringIO()):
                return dict(rate_corrections(writes, fps, image, {}))
        self.assertEqual(corrected([], 90)[at], struct.pack('<f', 1 / 90))
        # The base's loads read a real-dt cell instead (120/144).
        self.assertNotIn(at, corrected([(WIND_LOADS - EBOOT_BASE, bytes(4))], 120))
        self.assertNotIn(at, corrected([], None))
        self.assertNotIn(at, corrected([], 90, {'BB_WIND_FIX': '0'}))
        self.assertNotIn(at, corrected([], 90, image=fake_elf(at, bytes(4))))

    def test_camera_only_when_asked(self):
        writes, out = self.corrected(144)
        cams = {a - EBOOT_BASE for a in CAMERA_FIELDS}
        self.assertEqual({o: d for o, d in out if o in cams}, {o: d for o, d in writes if o in cams})
        _, on = self.corrected(144, env={'BB_CAMERA_FIX': '1'})
        on, base = dict(on), dict(writes)
        changed = [o for o in cams if on[o] != base[o]]
        self.assertTrue(changed)
        for o in changed:
            w = struct.unpack('<f', base[o])[0]
            expected = camera_value(CAMERA_FIELDS[o + EBOOT_BASE], w, 60 / 144)
            self.assertAlmostEqual(struct.unpack('<f', on[o])[0], expected, places=6)
        self.assertAlmostEqual(camera_value(0x19c, 0.05, 1), 0.05)
        self.assertAlmostEqual(camera_value(0x19c, 0.5, 0.5), 1 - 0.5 ** 0.5)
        self.assertAlmostEqual(camera_value(0x1a8, 0.5, 0.5), 0.5 ** 0.5)
        self.assertEqual(camera_value(0x238, 0.5, 0.5), 0.5)

    def test_existing_presets_are_unchanged_by_default(self):
        for preset, fps in (('60 FPS++', 60), ('90 FPS++', 90), ('Uncap FPS++', None)):
            with self.subTest(preset=preset):
                writes = compile_patches(XML, [preset], '01.09', SEGMENTS)
                with mock.patch.dict('os.environ', {}, clear=True), redirect_stdout(io.StringIO()):
                    self.assertEqual(rate_corrections(writes, fps, None, {}), writes)


class FrameStepTests(unittest.TestCase):
    """The lists' fixed 1/60 steps follow the rate above 60 FPS (BB_FRAME_STEP_FIX)."""
    def setUp(self):
        code = bytearray(0x40)
        struct.pack_into('<f', code, 0x10, 1 / 30)   # a game step
        struct.pack_into('<f', code, 0x20, 0.25)     # something else
        self.elf = fake_elf(0, bytes(code))
        self.writes = [(0x10, struct.pack('<f', 1 / 60)), (0x20, struct.pack('<f', 1 / 60)),
                       (0x30, b'\x90' * 4)]

    def steps(self, fps, env=None, settings=None):
        with mock.patch.dict('os.environ', env or {}, clear=True), redirect_stdout(io.StringIO()):
            return frame_steps(self.writes, fps, self.elf, settings or {})

    def test_only_steps_the_game_has_at_1_30(self):
        for fps in (90, 120, 144):
            with self.subTest(fps=fps):
                out = self.steps(fps)
                self.assertEqual(out[0], (0x10, struct.pack('<f', 1 / fps)))
                self.assertEqual(out[1:], self.writes[1:])

    def test_60_uncapped_and_off_keep_the_list(self):
        self.assertEqual(self.steps(60), self.writes)
        self.assertEqual(self.steps(None), self.writes)
        self.assertEqual(self.steps(120, env={'BB_FRAME_STEP_FIX': '0'}), self.writes)
        self.assertEqual(self.steps(120, settings={'frame_step_fix': '0'}), self.writes)

    @unittest.skipUnless(GAME_ELF.is_file(), 'needs a prepared 1.09 eboot.elf (BB_TEST_EBOOT_ELF)')
    def test_sites_in_the_game(self):
        elf = GAME_ELF.read_bytes()
        segments = eboot_segments(elf)
        for preset, fps, count in (('90 FPS++', '90', 95), (SCALED_BASE, '120', 78)):
            with self.subTest(preset=preset), mock.patch.dict('os.environ', {}, clear=True), \
                    redirect_stdout(io.StringIO()):
                before = rate_scaled(compile_patches(XML, [preset], '01.09', segments), int(fps)) \
                    if preset == SCALED_BASE else compile_patches(XML, [preset], '01.09', segments)
                after = preset_writes(XML, [preset], fps, '01.09', segments, elf, {})
                stepped = [o for (o, d) in after if d == struct.pack('<f', 1 / int(fps))
                           and eboot_bytes(elf, o, o + 4) == struct.pack('<f', 1 / 30)
                           and dict(before)[o] == struct.pack('<f', 1 / 60)]
                self.assertEqual(len(stepped), count)


class ExternalFpsPatchTests(unittest.TestCase):
    EXTERNAL = """<?xml version="1.0"?>
<Patch><TitleID><ID>CUSA03173</ID></TitleID>
<Metadata Title="Bloodborne" Name="{name}" AppVer="01.09" AppElf="eboot.bin" isEnabled="true"><PatchList>
<Line Type="bytes" Address="{address}" Value="8988883C"/>
</PatchList></Metadata></Patch>"""

    def folder(self, files):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        for name, text in files.items():
            (Path(directory.name) / name).write_text(text)
        return Path(directory.name)

    def test_copies_of_the_built_in_file_are_ignored(self):
        folder = self.folder({'bloodborne.XML': XML.read_text(encoding='utf-8'),
                              'other.xml': self.EXTERNAL.format(name='Mine', address='0x00500000')})
        with mock.patch.dict('os.environ', {}, clear=True), redirect_stderr(io.StringIO()) as log:
            self.assertEqual([key for key, _, _ in external_patches(folder)], ['other.xml/Mine'])
        self.assertIn('ignored', log.getvalue())
        with mock.patch.dict('os.environ', {'BB_EXTERNAL_BLOODBORNE_XML': '1'}, clear=True):
            self.assertIn('bloodborne.XML/Uncap FPS++', [key for key, _, _ in external_patches(folder)])
        ini = folder / 'bbport.ini'
        ini.write_text('external_bloodborne_xml=1\n')
        with mock.patch.dict('os.environ', {'BB_CONFIG': str(ini)}, clear=True):
            self.assertIn('bloodborne.XML/Uncap FPS++', [key for key, _, _ in external_patches(folder)])

    def test_an_external_fps_patch_replaces_the_preset(self):
        preset = compile_patches(XML, ['60 FPS++'], '01.09', SEGMENTS)
        others = [(0x500000, b'\x01')]
        # A site the preset writes (its physics step stays the game's own 1/30 at 60 FPS, so that
        # line is not in the list since the redistribution review).
        written = f'0x{preset[0][0] + EBOOT_BASE:08X}'
        for address, replaces in ((written, True), ('0x00500010', False)):
            with self.subTest(address=address):
                folder = self.folder({'fps.xml': self.EXTERNAL.format(name='60FPS (no deltatime)', address=address)})
                with mock.patch.dict('os.environ', {}, clear=True), redirect_stdout(io.StringIO()):
                    selected = external_selection(external_patches(folder), None)
                    writes, replaced = with_external(preset + others, len(preset), selected, SEGMENTS)
                external = [(int(address, 16) - EBOOT_BASE, bytes.fromhex('8988883C'))]
                if replaces:
                    self.assertEqual(replaced, 'fps.xml/60FPS (no deltatime)')
                    self.assertEqual(writes, others + external)
                else:
                    self.assertIsNone(replaced)
                    self.assertEqual(writes, preset + others + external)


class PcHeapTests(unittest.TestCase):
    def test_switch(self):
        with mock.patch.dict('os.environ', {}, clear=True):
            self.assertTrue(pc_heaps_enabled({}))
            self.assertFalse(pc_heaps_enabled({'pc_heaps': '0'}))
        with mock.patch.dict('os.environ', {'BB_PC_HEAPS': '0'}):
            self.assertFalse(pc_heaps_enabled({'pc_heaps': '1'}))

    def test_guard_covers_both_writes(self):
        offset, length, _ = HEAP_GUARD
        writes = compile_patches(XML, [HEAP_PATCH], '01.09', SEGMENTS)
        self.assertEqual(len(writes), 2)
        for at, data in writes:
            self.assertTrue(offset <= at and at + len(data) <= offset + length)
        self.assertFalse(site_matches(fake_elf(offset, bytes(length)), HEAP_GUARD))

    @unittest.skipUnless(GAME_ELF.is_file(), 'needs a prepared 1.09 eboot.elf (BB_TEST_EBOOT_ELF)')
    def test_guard_matches_the_game(self):
        self.assertTrue(site_matches(GAME_ELF.read_bytes(), HEAP_GUARD))


class CircleConfirmTests(unittest.TestCase):
    NAME = 'Circle Confirm (Japanese/Asian button layout)'

    def test_switch_and_guard(self):
        self.assertIn(self.NAME, effect_patches({'tweak_circle_confirm': '1'}))
        self.assertNotIn(self.NAME, effect_patches({'tweak_circle_confirm': '0'}))
        offset, length, _ = HASH_GUARDS[self.NAME]
        (at, data), = compile_patches(XML, [self.NAME], '01.09', SEGMENTS)
        self.assertEqual((at, len(data)), (offset, length))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(guarded_patches([self.NAME], fake_elf(0, bytes(0x2000000))), [])

    @unittest.skipUnless(GAME_ELF.is_file(), 'needs a prepared 1.09 eboot.elf (BB_TEST_EBOOT_ELF)')
    def test_guard_matches_the_game(self):
        self.assertEqual(guarded_patches([self.NAME], GAME_ELF.read_bytes()), [self.NAME])


def fake_elf(vaddr, code):
    # One PT_LOAD segment holding `code` at `vaddr` (file offset 0x1000).
    header = bytearray(0x1000)
    struct.pack_into('<Q', header, 0x20, 0x40)
    struct.pack_into('<HH', header, 0x36, 56, 1)
    struct.pack_into('<IIQQQQQQ', header, 0x40, 1, 5, 0x1000, vaddr, vaddr, len(code), len(code), 0x1000)
    return bytes(header) + code


class SprintFixTests(unittest.TestCase):
    def test_blocked_movement_check_divides_by_frame_time(self):
        # The fix knows the game's vmulss only by length and hash (no game bytes here): stand-in
        # bytes with a matching check exercise the same path.
        import patches
        from cpu_compat import site_check
        stand_in = bytes(range(8))
        fixes = [(vaddr, (8, site_check(stand_in)), new) for vaddr, _, new in patches.FRAME_RATE_FIXES]
        with mock.patch.object(patches, 'FRAME_RATE_FIXES', fixes):
            elf = fake_elf(0x1514c24, stand_in)
            self.assertEqual(frame_rate_fixes(elf), [(0x1514c24, bytes.fromhex('c5fa5e458c0f1f00'))])

    def test_unexpected_code_is_left_alone(self):
        elf = fake_elf(0x1514c24, bytes.fromhex('9090909090909090'))
        self.assertEqual(frame_rate_fixes(elf), [])

    def test_switch(self):
        from unittest import mock
        with mock.patch.dict('os.environ', {}, clear=True):
            self.assertTrue(sprint_fix_enabled({}))
            self.assertFalse(sprint_fix_enabled({'sprint_fix': '0'}))
        with mock.patch.dict('os.environ', {'BB_SPRINT_FIX': '0'}):
            self.assertFalse(sprint_fix_enabled({'sprint_fix': '1'}))


class DebugPatchTests(unittest.TestCase):
    def test_camera_patch_is_optional_and_compatible_with_fps_and_debug_menu(self):
        self.assertEqual(effect_patches({'debug_camera': '0', 'debug_menu': '0'}), [])
        camera = effect_patches({'debug_camera': '1'})
        writes = compile_patches(XML, camera, '01.09', SEGMENTS)
        self.assertGreater(len(writes), 0)
        camera_bytes = {offset+i: byte for offset, data in writes for i, byte in enumerate(data)}
        for patch in ('Uncap FPS++', '60 FPS++', '90 FPS++', 'Restore Debug Menu (READ NOTES)'):
            for offset, data in compile_patches(XML, [patch], '01.09', SEGMENTS):
                for i, byte in enumerate(data):
                    if offset+i in camera_bytes:
                        self.assertEqual(camera_bytes[offset+i], byte, patch)

    def test_debug_menu_needs_both_fonts_but_camera_does_not(self):
        names = effect_patches({'debug_menu': '1'})
        menu = 'Restore Debug Menu (READ NOTES)'
        with tempfile.TemporaryDirectory() as directory:
            game = Path(directory)
            self.assertEqual(validate_patch_requirements(['Restore Debug Camera'], game),
                             ['Restore Debug Camera'])
            # Without the fonts the patch is left out; the game still starts.
            self.assertNotIn(menu, validate_patch_requirements(names, game))
            font = game / 'dvdroot_ps4/font'
            font.mkdir(parents=True)
            (font / 'DbgFont14h.ccm').write_bytes(b'test')
            (font / 'DbgFont14h.tpf').touch()  # an empty file is not enough
            self.assertNotIn(menu, validate_patch_requirements(names, game))
            (font / 'DbgFont14h.tpf').write_bytes(b'test')
            self.assertIn(menu, validate_patch_requirements(names, game))

    def test_debug_menu_fonts_in_adhoc_font_with_a_mods_own_case(self):
        names = effect_patches({'debug_menu': '1'})
        with tempfile.TemporaryDirectory() as directory:
            game = Path(directory)
            font = game / 'dvdroot_ps4/Adhoc/Font'
            font.mkdir(parents=True)
            (font / 'dbgfont14h.ccm').write_bytes(b'test')
            (font / 'dbgfont14h.tpf').write_bytes(b'test')
            self.assertIn('Restore Debug Menu (READ NOTES)', validate_patch_requirements(names, game))

    def test_fixes_raise_the_frame_heaps_without_touching_other_patches(self):
        writes = compile_patches(XML, FIXES, '01.09', SEGMENTS)
        self.assertEqual(writes, [(0x2195c0a, b'\x00\x00\x10\x00'), (0x2195c47, b'\x00\x00\x10\x00')])
        others = [n for names in FPS_PRESETS.values() for n in names] + [RESOLUTION_TEMPLATE]
        for offset, data in compile_patches(XML, others, '01.09', SEGMENTS):
            for fix, value in writes:
                self.assertFalse(offset < fix + len(value) and fix < offset + len(data), hex(offset))

    def test_conflicting_enemy_control_patch_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'conflicts with Enemy Control'):
            validate_patch_requirements(['Enemy Control', 'Restore Debug Camera'], Path('.'))


EXTERNAL = """<?xml version="1.0"?>
<Patch>
  <TitleID><ID>CUSA03173</ID><ID>CUSA00207</ID></TitleID>
  <Metadata Title="Bloodborne" Name="On" Author="x" PatchVer="1.0" AppVer="01.09" AppElf="eboot.bin" isEnabled="true">
    <PatchList><Line Type="bytes" Address="0x00401000" Value="9090"/></PatchList>
  </Metadata>
  <Metadata Title="Bloodborne" Name="Off" Author="x" PatchVer="1.0" AppVer="01.09" AppElf="eboot.bin">
    <PatchList><Line Type="bytes32" Address="0x00402000" Value="0x12345678"/></PatchList>
  </Metadata>
  <Metadata Title="Bloodborne" Name="Mask" Author="x" PatchVer="1.0" AppVer="01.09" AppElf="eboot.bin" isEnabled="true">
    <PatchList><Line Type="mask" Value="90 ?? 90" Offset="0"/></PatchList>
  </Metadata>
  <Metadata Title="Bloodborne" Name="Old" Author="x" PatchVer="1.0" AppVer="01.00" AppElf="eboot.bin" isEnabled="true">
    <PatchList><Line Type="bytes" Address="0x00403000" Value="90"/></PatchList>
  </Metadata>
</Patch>"""


class ExternalPatchTests(unittest.TestCase):
    def test_selection_and_unsupported_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / 'extra.xml').write_text(EXTERNAL)
            (folder / 'other.xml').write_text(EXTERNAL.replace('CUSA03173', 'CUSA99999')
                                              .replace('CUSA00207', 'CUSA99998'))
            (folder / 'broken.xml').write_text('<Patch>')
            found = external_patches(folder)
            self.assertEqual([key for key, _, _ in found],
                             ['extra.xml/On', 'extra.xml/Off', 'extra.xml/Mask'])
            # The file's isEnabled; the mask patch is skipped as a whole.
            writes = compile_external(external_selection(found, None), SEGMENTS)
            self.assertEqual(writes, [(0x1000, bytes.fromhex('9090'))])
            config = folder / 'patches.json'
            config.write_text('{"enabled": ["extra.xml/Off"], "disabled": ["extra.xml/On"]}')
            writes = compile_external(external_selection(found, config), SEGMENTS)
            self.assertEqual(writes, [(0x2000, (0x12345678).to_bytes(4, 'little'))])

    def test_built_in_file_is_not_external(self):
        self.assertEqual(external_patches(XML.parent), [])


FINGERPRINTED = """<?xml version="1.0"?>
<Patch>
  <Metadata Name="60 FPS++" AppVer="01.09" AppElf="eboot.bin">
    <PatchList>
      <Line Type="bytes" Address="0x00400100" Value="909090"/>
      <Line Type="bytes" Address="0x00400102" Value="9090"/>
      <Line Type="bytes32" Address="0x00402ffe" Value="0x12345678"/>
    </PatchList>
  </Metadata>
  <Metadata Name="Skip Intro" AppVer="01.09" AppElf="eboot.bin">
    <PatchList><Line Type="bytes" Address="0x00400800" Value="90"/></PatchList>
  </Metadata>
</Patch>"""


def elf_image(code):
    """ELF64 with one PT_LOAD: `code` at vaddr 0 (file offset 0x1000), memory size 0x4000."""
    header = bytearray(0x1000)
    struct.pack_into('<Q', header, 0x20, 0x40)
    struct.pack_into('<HH', header, 0x36, 56, 1)
    struct.pack_into('<IIQQQQQQ', header, 0x40, 1, 5, 0x1000, 0, 0, len(code), 0x4000, 0x1000)
    return bytes(header) + bytes(code)


class FingerprintTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.xml = Path(directory.name) / 'patches.xml'
        self.xml.write_text(FINGERPRINTED)
        self.code = bytearray(range(256)) * 48  # 0x3000 bytes; the image is zero after that

    def fingerprint(self, code):
        return patch_fingerprint(elf_image(code), self.xml, '01.09')

    def test_sites_merge_and_ignore_other_patches(self):
        self.assertEqual(patch_sites(self.xml, '01.09'), [(0x100, 0x104), (0x2ffe, 0x3002)])

    def test_image_bytes_past_the_file_are_zero(self):
        self.assertEqual(eboot_bytes(elf_image(self.code), 0x2ffe, 0x3002),
                         bytes(self.code[0x2ffe:]) + b'\0\0')

    def test_only_patched_bytes_count(self):
        expected = self.fingerprint(self.code)
        other = bytearray(self.code)
        other[0x800] ^= 0xff  # written only by a patch outside the fingerprint
        other[0x50] ^= 0xff
        self.assertEqual(self.fingerprint(other), expected)
        other[0x103] ^= 0xff
        self.assertNotEqual(self.fingerprint(other), expected)

    @unittest.skipUnless((ROOT / 'out/eboot.elf').is_file(), 'needs a run of the game (out/eboot.elf)')
    def test_stored_fingerprint_matches_the_prepared_game(self):
        # Fails after the FPS or resolution patches change: update PATCH_FINGERPRINTS.
        self.assertTrue(eboot_matches_patches(ROOT / 'out/eboot.elf'))


def param_sfo(app_ver):
    """param.sfo with the single string entry APP_VER."""
    key, value = b'APP_VER\0', app_ver.encode() + b'\0'
    keys, values = 20 + 16, 20 + 16 + len(key)
    return (struct.pack('<4sIIII', b'\0PSF', 0x101, keys, values, 1)
            + struct.pack('<HHIII', 0, 0x204, len(value), len(value), 0) + key + value)


class GameVersionTests(unittest.TestCase):
    def game(self, app_ver, eboot=True):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        game = Path(directory.name)
        (game / 'sce_sys').mkdir()
        (game / 'sce_sys/param.sfo').write_bytes(param_sfo(app_ver))
        if eboot:
            (game / 'eboot.bin').write_bytes(b'eboot')
        return game

    def test_goty_dump_with_the_109_code_is_109(self):
        # Game of the Year discs say APP_VER 01.00 over the 1.09 executable.
        with mock.patch('patches.eboot_is_109', return_value=True):
            self.assertEqual(game_app_version(self.game('01.00')), '01.09')

    def test_other_code_keeps_the_app_ver(self):
        with mock.patch('patches.eboot_is_109', return_value=False):
            self.assertEqual(game_app_version(self.game('01.00')), '01.00')

    def test_missing_eboot_keeps_the_app_ver(self):
        with mock.patch('patches.eboot_is_109') as check:
            self.assertEqual(game_app_version(self.game('01.00', eboot=False)), '01.00')
        check.assert_not_called()

    def test_109_app_ver_skips_the_fingerprint(self):
        with mock.patch('patches.eboot_is_109') as check:
            self.assertEqual(game_app_version(self.game('01.09')), '01.09')
        check.assert_not_called()

    def test_unreadable_eboot_is_not_109(self):
        game = self.game('01.00')
        self.assertFalse(eboot_is_109(str(game / 'eboot.bin')))


if __name__ == '__main__':
    unittest.main()
