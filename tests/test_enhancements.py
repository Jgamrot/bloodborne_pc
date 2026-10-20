from paths import ROOT
import hashlib
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(ROOT / 'scripts'))
import enhancements  # noqa: E402
from fromsoft import dcx_compress, dcx_decompress  # noqa: E402

# BB_TEST_GAME_DIR=<CUSA03173>: also rewrite the real 1.09 files.
GAME = Path(os.environ['BB_TEST_GAME_DIR']) if os.environ.get('BB_TEST_GAME_DIR') else None


def emevd(events):
    """A minimal 64-bit EMEVD: events [(id, [(bank, id, argument bytes)])]."""
    header = 0x90
    event_table = header
    ins_table = event_table + 0x30 * len(events)
    instructions, args, rows = b'', b'', b''
    for event_id, items in events:
        rows += struct.pack('<qqq', event_id, len(items), len(instructions)) + b'\0' * 0x18
        for bank, ins_id, data in items:
            instructions += struct.pack('<iiqq', bank, ins_id, len(data), len(args)) + b'\0' * 8
            args += data
    args_at = ins_table + len(instructions)
    head = bytearray(header)
    struct.pack_into('<qq', head, 0x10, len(events), event_table)
    struct.pack_into('<q', head, 0x28, ins_table)
    struct.pack_into('<q', head, 0x78, args_at)
    return bytes(head) + rows + instructions + args


class SettingsTests(unittest.TestCase):
    def test_off_unless_switched_on_and_environment_wins(self):
        menu_off = {'pc_menu': '0'}
        self.assertEqual(enhancements.enabled(menu_off, {}), [])
        self.assertEqual(enhancements.enabled({**menu_off, 'pc_two_invaders': '1'}, {}), ['pc_two_invaders'])
        self.assertEqual(enhancements.enabled({**menu_off, 'pc_two_invaders': '1'}, {'BB_PC_TWO_INVADERS': '0'}), [])
        self.assertEqual(enhancements.enabled(menu_off, {'BB_PC_MIRROR': '1'}), ['pc_mirror_appearance'])

    def test_the_menu_is_on_unless_switched_off(self):
        self.assertEqual(enhancements.enabled({}, {}), ['pc_menu'])
        self.assertEqual(enhancements.enabled({}, {'BB_PC_MENU': '0'}), [])

    def test_overlay_and_launcher_offer_the_same_keys(self):
        header = (ROOT / 'gpu/shim/bbport_settings.h').read_text(encoding='utf-8')
        launcher = (ROOT / 'launcher/bbport_launcher.py').read_text(encoding='utf-8')
        for key in set(enhancements.FEATURES) - enhancements.DEFAULT_ON - enhancements.EXPERIMENTAL:
            self.assertIn(f'{{"{key}", ', header)
            self.assertIn(f'("{key}", ', launcher)
        for key in enhancements.EXPERIMENTAL:  # launcher only, labelled experimental; not the overlay
            self.assertNotIn(f'{{"{key}", ', header)
            self.assertIn(f'("{key}", ', launcher)


class RewriteTests(unittest.TestCase):
    def test_event_instructions_reads_arguments(self):
        data = emevd([(0, [(2000, 0, struct.pack('<ii', 5, 13404710) + b'\0' * 8)]),
                      (13404710, [(3, 29, bytes([1, 1, 0, 0])), (1, 1, b'')])])
        found = enhancements.event_instructions(data, 13404710)
        self.assertEqual([(bank, ins) for bank, ins, _at, _n in found], [(3, 29)])
        _bank, _ins, at, length = found[0]
        self.assertEqual(data[at:at + length], bytes([1, 1, 0, 0]))

    def test_talk_script_bytecode(self):
        import esd
        self.assertEqual(esd.lit(3), b'\x43')
        self.assertEqual(esd.lit(-1), b'\x3f')
        self.assertEqual(esd.lit(72500390), b'\x82' + struct.pack('<i', 72500390))
        self.assertEqual(esd.call(15, [4330]), b'\x4f\x82' + struct.pack('<i', 4330) + b'\x85\xa6')
        self.assertEqual(esd.done(b'\x41'), b'\x41\xa1')
        with self.assertRaises(esd.EsdError):
            esd.parse(b'fsSL' + b'\0' * 0x10)

    def test_unknown_files_are_left_alone(self):
        with tempfile.TemporaryDirectory() as folder:
            game = Path(folder) / 'game'
            (game / 'dvdroot_ps4/event').mkdir(parents=True)
            (game / 'dvdroot_ps4/map/MapStudio').mkdir(parents=True)
            for name in ('m26_00_00_00', 'm33_00_00_00'):
                (game / f'dvdroot_ps4/event/{name}.emevd.dcx').write_bytes(dcx_compress(emevd([])))
            (game / 'dvdroot_ps4/map/MapStudio/m21_00_00_00.msb.dcx').write_bytes(dcx_compress(b'MSB not 1.09'))
            made = enhancements.make(game, Path(folder) / 'out', list(enhancements.FEATURES))
            self.assertEqual(made, [])
            self.assertFalse((Path(folder) / 'out/two-invaders').exists())


@unittest.skipUnless(GAME, 'BB_TEST_GAME_DIR not set')
class RealGameTests(unittest.TestCase):
    def test_every_talk_script_round_trips_and_the_altar_matches_bbhost(self):
        import esd
        from fromsoft import Bnd4
        scripts = 0
        for archive in sorted((GAME / 'dvdroot_ps4/script/talk').glob('*.talkesdbnd.dcx')):
            bnd = Bnd4(dcx_decompress(archive.read_bytes()))
            for name, data in zip(bnd.names, bnd.files):
                if name.lower().endswith('.esd'):
                    self.assertEqual(esd.serialize(esd.parse(data)), data, name)
                    scripts += 1
        self.assertEqual(scripts, 271)
        files = enhancements.rebirth(GAME / 'dvdroot_ps4')
        archive = Bnd4(dcx_decompress(next(iter(files.values()))))
        altar = archive.files[archive.index('t242307.esd')]
        self.assertEqual(hashlib.sha256(altar).hexdigest(), enhancements.REBIRTH_OUT)

    def test_rewrites_match_bbhost_and_are_reused(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            made = enhancements.make(GAME, out, ['pc_two_invaders', 'pc_mirror_appearance'])
            self.assertEqual(sorted(m.name for m in made), ['dream-mirror', 'two-invaders'])
            for name, _sha_in, sha_out, *_ in enhancements.MAIDEN_MAPS:
                packed = (out / f'two-invaders/dvdroot_ps4/event/{name}.emevd.dcx').read_bytes()
                self.assertEqual(hashlib.sha256(dcx_decompress(packed)).hexdigest(), sha_out)
                original = (GAME / f'dvdroot_ps4/event/{name}.emevd.dcx').read_bytes()
                self.assertEqual(packed[:0x1c], original[:0x1c])  # the game's own DCX header
            msb = dcx_decompress((out / 'dream-mirror/dvdroot_ps4/map/MapStudio/m21_00_00_00.msb.dcx').read_bytes())
            self.assertEqual(hashlib.sha256(msb).hexdigest(), enhancements.MIRROR_OUT)
            stamp = out / 'dream-mirror/stamp.txt'
            before = stamp.stat().st_mtime_ns
            again = enhancements.make(GAME, out, ['pc_mirror_appearance'])
            self.assertEqual([m.name for m in again], ['dream-mirror'])
            self.assertEqual(stamp.stat().st_mtime_ns, before)  # up to date: not made again

    def test_experimental_rematch_keeps_the_lamps_and_rebirth(self):
        from fromsoft import Bnd4
        import esd
        import enhanced_lamps
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            keys = enhancements.enabled({'pc_rebirth': '1', 'pc_enhanced_lamps': '1'}, {'BB_PC_REMATCHES': '1'})
            self.assertEqual(keys[-3:], ['pc_enhanced_lamps', 'pc_boss_rematches', 'pc_menu'])
            made = {m.name: m for m in enhancements.make(GAME, out, keys)}
            root = made['boss-rematches'] / 'dvdroot_ps4'
            self.assertTrue((root / 'event/m24_01_00_00.emevd.dcx').is_file())
            # The altar archive keeps Rebirth; Central Yharnam's lamp has the menu and the rematch.
            altar = Bnd4(dcx_decompress((root / 'script/talk/m24_02_00_00.talkesdbnd.dcx').read_bytes()))
            self.assertEqual(hashlib.sha256(altar.files[altar.index('t242307.esd')]).hexdigest(),
                             enhancements.REBIRTH_OUT)
            yharnam = Bnd4(dcx_decompress((root / 'script/talk/m24_01_00_00.talkesdbnd.dcx').read_bytes()))
            for name, states in (('t241000.esd', 11), ('t241002.esd', 14), ('t241003.esd', 14)):
                lamp = esd.parse(yharnam.files[yharnam.index(name)])
                self.assertEqual(len(lamp.group(enhanced_lamps.LAMP_MENU_GROUP).states), states, name)
            # Ebrietas's lamp shares the altar's archive: its rematch and Rebirth are both there.
            ebrietas = esd.parse(altar.files[altar.index('t242001.esd')])
            self.assertEqual(len(ebrietas.group(enhanced_lamps.LAMP_MENU_GROUP).states), 14)
        # Off unless switched on (the launcher's toggle is labelled experimental).
        self.assertNotIn('pc_boss_rematches', enhancements.enabled({'pc_boss_rematches': '0'}, {}))

    def test_rematches_keep_the_two_invaders(self):
        from emevd import Emevd
        import boss_rematches
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            keys = enhancements.enabled({'pc_two_invaders': '1', 'pc_boss_rematches': '1'}, {})
            self.assertLess(keys.index('pc_two_invaders'), keys.index('pc_boss_rematches'))  # rematches win
            made = {m.name: m for m in enhancements.make(GAME, out, keys)}
            for rule in enhancements.MAIDEN_MAPS:
                relative = f'dvdroot_ps4/event/{rule[0]}.emevd.dcx'
                invaders = Emevd(dcx_decompress((made['two-invaders'] / relative).read_bytes()))
                both = Emevd(dcx_decompress((made['boss-rematches'] / relative).read_bytes()))
                for event in (rule[3], rule[4]):  # the maidens' ring and stop events
                    self.assertEqual(both.event_instructions(event), invaders.event_instructions(event))
                for boss in boss_rematches.BOSSES:
                    if boss.map == rule[0]:
                        self.assertTrue(both.event_instructions(boss.ids[4]), boss.name)

    def test_lamps_and_rebirth_share_the_altar_archive(self):
        from fromsoft import Bnd4
        import enhanced_lamps
        shared = 'script/talk/m24_02_00_00.talkesdbnd.dcx'
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            keys = enhancements.enabled({'pc_rebirth': '1', 'pc_enhanced_lamps': '1'}, {})
            self.assertLess(keys.index('pc_rebirth'), keys.index('pc_enhanced_lamps'))  # lamps win
            made = enhancements.make(GAME, out, keys)
            self.assertIn('enhanced-lamps', [m.name for m in made])
            archive = Bnd4(dcx_decompress((out / 'enhanced-lamps/dvdroot_ps4' / shared).read_bytes()))
            altar = archive.files[archive.index('t242307.esd')]
            self.assertEqual(hashlib.sha256(altar).hexdigest(), enhancements.REBIRTH_OUT)
            lamp = archive.files[archive.index('t242000.esd')]
            self.assertIsNotNone(__import__('esd').parse(lamp).group(enhanced_lamps.LAMP_MENU_GROUP))
            # Rebirth switched off: the lamp layer is made again, without the altar edit.
            stamp = (out / 'enhanced-lamps/stamp.txt').read_text(encoding='utf-8')
            self.assertIn('+pc_rebirth', stamp.splitlines()[0])
            enhancements.make(GAME, out, ['pc_enhanced_lamps'])
            archive = Bnd4(dcx_decompress((out / 'enhanced-lamps/dvdroot_ps4' / shared).read_bytes()))
            original = Bnd4(dcx_decompress((GAME / 'dvdroot_ps4' / shared).read_bytes()))
            self.assertEqual(archive.files[archive.index('t242307.esd')],
                             original.files[original.index('t242307.esd')])


if __name__ == '__main__':
    unittest.main()
