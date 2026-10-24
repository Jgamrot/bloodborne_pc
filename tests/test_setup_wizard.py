import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'launcher'))
import bbport_launcher_win as core
import bbport_startup
from bbport_launcher_backend import LauncherBackend


class FirstRunWizardTests(unittest.TestCase):
    def setUp(self):
        parent = Path(__file__).resolve().parents[1] / 'out'
        parent.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=parent)
        self.root = Path(self.temporary.name)
        self.patches = [patch.object(core, 'CONFIG_DIR', self.root),
                        patch.object(core, 'CONFIG_FILE', self.root / 'settings.json'),
                        patch.object(core, 'DATA_DIR', self.root),
                        patch.dict(os.environ, {'BB_CONFIG': str(self.root / 'bbport.ini')}),
                        patch.dict(core.APP_DEFAULTS, {'check_updates': False,
                                                       'game_dir': str(self.root / 'missing')}),
                        patch.object(LauncherBackend, '_detect_gpu', lambda self: None)]
        for active in self.patches:
            active.start()

    def tearDown(self):
        for active in reversed(self.patches):
            active.stop()
        self.temporary.cleanup()

    def settings(self):
        return {**core.APP_DEFAULTS, **json.loads((self.root / 'settings.json').read_text(encoding='utf-8'))}

    def route(self, args=()):
        return bbport_startup.route(self.settings(), list(args), self.root, False)

    def test_wizard_survives_partial_setup_and_stops_after_finish(self):
        first = LauncherBackend()
        first.setValue('game_dir', str(self.root / 'game'))
        self.assertEqual(self.route()['page'], 'Setup')
        first.completeSetup()
        saved = self.settings()
        self.assertTrue(saved['setupCompleted'])
        self.assertEqual(saved['setupVersion'], bbport_startup.SETUP_VERSION)
        self.assertNotEqual(self.route()['page'], 'Setup')

    def test_finished_setup_with_game_launches_directly(self):
        game = self.root / 'CUSA03173'
        game.mkdir()
        (game / 'eboot.bin').write_bytes(b'\0')
        backend = LauncherBackend()
        backend.setValue('game_dir', str(game))
        backend.completeSetup()
        self.assertEqual(self.route()['mode'], 'direct')
        self.assertEqual(self.route(['--launcher'])['page'], 'Home')
        self.assertEqual(self.route(['--setup'])['page'], 'Setup')
        backend.setValue('launchDirectly', False)
        self.assertEqual(self.route()['mode'], 'launcher')

    def test_skip_opens_game_page_with_fix_banner(self):
        backend = LauncherBackend()
        backend.skipSetup()
        self.assertTrue(self.settings()['setupSkipped'])
        self.assertEqual(backend.startupProblem, 'Game files not found')
        route = self.route()
        self.assertEqual((route['page'], route['problem'], route['step']), ('Game', 'game', 1))
        backend.dismissProblem()
        self.assertEqual(backend.startupProblem, '')

    def test_fix_banner_clears_once_game_folder_is_valid(self):
        backend = LauncherBackend({'mode': 'launcher', 'page': 'Game', 'step': 1, 'problem': 'game'})
        self.assertEqual(backend.startPage, 'Game')
        self.assertEqual(backend.fixStep, 1)
        self.assertEqual(backend.startupProblem, 'Game files not found')
        game = self.root / 'game'
        game.mkdir()
        (game / 'eboot.bin').write_bytes(b'\0')
        backend.setValue('game_dir', str(game))
        self.assertEqual(backend.startupProblem, '')

    def game_with_menu(self):
        """A game folder whose menu/common.tpf.dcx has the slots the prompt images replace."""
        from test_prompt_icons import common_tpf
        import fromsoft
        game = self.root / 'CUSA03173'
        (game / 'dvdroot_ps4' / 'menu').mkdir(parents=True)
        (game / 'dvdroot_ps4' / 'menu' / 'common.tpf.dcx').write_bytes(fromsoft.dcx_compress(common_tpf()))
        return game

    def test_prompt_images_are_made_from_the_players_game(self):
        backend = LauncherBackend()
        self.assertEqual(backend.promptChoice, 'PlayStation')  # the port ships no game textures
        # No game folder yet: nothing changes and the notice says why.
        backend.setPrompt('Keyboard')
        self.assertEqual(backend.promptChoice, 'PlayStation')
        self.assertIn('game folder', backend.notice)
        self.assertFalse((self.root / 'mods' / core.KEYBOARD_PROMPTS).exists())
        game = self.game_with_menu()
        backend.setValue('game_dir', str(game))
        backend.setPrompt('Keyboard')
        self.assertEqual(backend.promptChoice, 'Keyboard')
        installed = self.root / 'mods' / core.KEYBOARD_PROMPTS
        texture = (installed / 'menu' / 'common.tpf.dcx').read_bytes()
        self.assertNotEqual(texture, (game / 'dvdroot_ps4' / 'menu' / 'common.tpf.dcx').read_bytes())
        self.assertIn('Kenney', (installed / 'SOURCE.txt').read_text(encoding='utf-8'))
        ini = (self.root / 'bbport.ini').read_text(encoding='utf-8')
        self.assertIn('key_roll=Left Shift', ini)
        self.assertIn('key_lock_on=Mouse3', ini)
        self.assertNotIn(core.KEYBOARD_PROMPTS, [m['name'] for m in backend.contentMods])
        backend.setPrompt('Xbox')
        self.assertEqual(backend.promptChoice, 'Xbox')
        self.assertTrue((self.root / 'mods' / core.XBOX_PROMPTS / 'menu' / 'common.tpf.dcx').is_file())
        # What run.py reads at every start (BB_BUTTON_PROMPTS): the Xbox images, not the keys.
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
        import mods
        in_use = mods.selected(self.root / 'mods', self.root / 'mods.json')
        self.assertIn(core.XBOX_PROMPTS, in_use)
        self.assertNotIn(core.KEYBOARD_PROMPTS, in_use)
        # Both added: switching writes nothing new.
        with patch.object(core, 'install_prompt_pack', lambda *args: self.fail('rebuilt')):
            backend.setPrompt('Keyboard')
            self.assertEqual(backend.promptChoice, 'Keyboard')
            # A choice made in the game's overlay (mods.json only) shows in the launcher too.
            profile = json.loads((self.root / 'mods.json').read_text())
            profile['disabled'] = sorted(set(profile['disabled']) - {core.XBOX_PROMPTS} | {core.KEYBOARD_PROMPTS})
            (self.root / 'mods.json').write_text(json.dumps(profile))
            backend.refresh_addons()
            self.assertEqual(backend.promptChoice, 'Xbox')
            backend.setPrompt('PlayStation')
            self.assertEqual(backend.promptChoice, 'PlayStation')

    def test_earlier_nexus_prompt_mods_are_switched_off(self):
        legacy = self.root / 'mods' / core.LEGACY_KEYBOARD_PROMPTS / 'menu'
        legacy.mkdir(parents=True)
        (legacy / 'common.tpf.dcx').write_bytes(b'DCX\0keys')
        backend = LauncherBackend()
        self.assertEqual(backend.promptChoice, 'Keyboard')
        self.assertNotIn(core.LEGACY_KEYBOARD_PROMPTS, [m['name'] for m in backend.contentMods])
        backend.setValue('game_dir', str(self.game_with_menu()))
        backend.setPrompt('Xbox')
        self.assertEqual(backend.promptChoice, 'Xbox')
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
        import mods
        self.assertNotIn(core.LEGACY_KEYBOARD_PROMPTS, mods.selected(self.root / 'mods', self.root / 'mods.json'))

    def test_a_menu_file_that_is_already_a_prompt_mod_is_refused(self):
        from test_prompt_icons import common_tpf
        import fromsoft
        game = self.game_with_menu()
        (game / 'dvdroot_ps4' / 'menu' / 'common.tpf.dcx').write_bytes(
            fromsoft.dcx_compress(common_tpf(atlas=(2048, 1024))))
        backend = LauncherBackend()
        backend.setValue('game_dir', str(game))
        backend.setPrompt('Keyboard')
        self.assertEqual(backend.promptChoice, 'PlayStation')
        self.assertIn('MENU_Common_00091', backend.notice)
        self.assertFalse((self.root / 'mods' / core.KEYBOARD_PROMPTS).exists())

    def test_launch_options_moved_out_of_advanced(self):
        backend = LauncherBackend()
        keys = {field['key'] for page in ('Advanced', 'Diagnostics') for field in backend.fields(page)}
        self.assertFalse(keys & {'close_on_play', 'launchDirectly', 'check_updates'})
        self.assertEqual([f['key'] for f in backend.fields('Diagnostics')],
                         ['frame_stats', 'gpu_profile', 'vk_validation'])
        pages = ('Graphics', 'Display', 'Game', 'Controller', 'Cheats', 'Online', 'Mods', 'Advanced', 'Diagnostics')
        every = [field['key'] for page in pages for field in backend.fields(page)]
        self.assertEqual(len(every), len(set(every)), 'a setting appears on two pages')


if __name__ == '__main__':
    unittest.main()
