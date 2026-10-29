from pathlib import Path
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'launcher'))
import bbport_launcher_win as core


class GraphicsPresetTests(unittest.TestCase):
    def defaults(self):
        return dict(core.INI_DEFAULTS), dict(core.APP_DEFAULTS)

    def test_presets_only_use_settings_that_exist(self):
        for name, values in core.GRAPHICS_PRESETS.items():
            with self.subTest(name=name):
                for key, value in values.items():
                    self.assertTrue(key in core.INI_DEFAULTS or key in core.APP_DEFAULTS, key)
                self.assertIn(name, core.GRAPHICS_PRESET_INFO)
                self.assertIn(values['preset'], [v for v, _ in core.PRESETS])
                self.assertIn(values['model_lod'], [v for v, _ in core.LODS])
                self.assertIn(values['fps_mode'], [v for v, _ in core.FPS_MODES])

    def test_shipped_defaults_are_balanced_and_overrides_are_custom(self):
        ini, app = self.defaults()
        self.assertEqual(core.graphics_preset_of(ini, app), 'balanced')
        core.apply_graphics_preset('ultra', ini, app)
        self.assertEqual(core.graphics_preset_of(ini, app), 'ultra')
        ini['effect_ssr'] = '0'
        self.assertEqual(core.graphics_preset_of(ini, app), 'custom')

    def test_preset_leaves_upscaler_output_and_look_alone(self):
        ini, app = self.defaults()
        ini.update(upscaler='fsr3', output_res='3840x2160', effect_dof='0', effect_motion_blur='0')
        core.apply_graphics_preset('low', ini, app)
        self.assertEqual((ini['upscaler'], ini['output_res'], ini['effect_dof'], ini['effect_motion_blur']),
                         ('fsr3', '3840x2160', '0', '0'))
        self.assertEqual(app['fps_mode'], '60')

    def test_new_installs_run_120_and_saved_settings_keep_their_frame_rate(self):
        self.assertEqual(core.app_settings({})['fps_mode'], '120')
        # Saved before 120 was the default, without a frame rate of their own: they ran unlocked.
        self.assertEqual(core.app_settings({'game_dir': 'x'})['fps_mode'], 'uncap')
        self.assertEqual(core.app_settings({'fps_mode': '60'})['fps_mode'], '60')
        modes = [v for v, _ in core.FPS_MODES]
        self.assertEqual(modes[0], '120')
        self.assertTrue({'120', '144', 'uncap', '90', '60', '30'} <= set(modes))
        self.assertIn('Amelia', dict(core.FPS_MODES)['uncap'][0])

    def test_window_options_reach_the_game(self):
        app = dict(core.APP_DEFAULTS)
        with patch.dict(os.environ, {}, clear=True):
            env = core.game_environment(app)
            self.assertEqual(env['BB_FULLSCREEN_MODE'], 'borderless')
            self.assertNotIn('BB_DISPLAY', env)
            self.assertEqual(env['BB_VOICE_LANGUAGE'], 'auto')
            self.assertNotIn('BB_AUDIO_CHANNELS', env)
            app.update(fullscreen_mode='exclusive', display='2', voice_language='ptb', audio_channels='2')
            env = core.game_environment(app)
            self.assertEqual((env['BB_FULLSCREEN_MODE'], env['BB_DISPLAY'], env['BB_VOICE_LANGUAGE'],
                              env['BB_AUDIO_CHANNELS']), ('exclusive', '2', 'ptb', '2'))
        for key, options in (('fullscreen_mode', core.FULLSCREEN_MODES), ('display', core.DISPLAYS),
                             ('voice_language', core.VOICE_LANGUAGES), ('audio_channels', core.AUDIO_CHANNELS)):
            self.assertIn(core.APP_DEFAULTS[key], [v for v, _ in options])

    def test_recommendation_from_gpu_status(self):
        cases = {
            'NVIDIA GeForce RTX 4060 Laptop GPU, discrete, 7956 MiB': 'high',
            'NVIDIA GeForce RTX 4090, discrete, 24564 MiB': 'ultra',
            'NVIDIA GeForce GTX 1060 6GB, discrete, 6144 MiB': 'balanced',
            'AMD Radeon RX 560, discrete, 2048 MiB': 'low',
            'AMD Custom GPU 0405 (RADV VANGOGH), integrated or other, 1024 MiB': 'low',
            'Graphics card check unavailable': None,
            '': None,
        }
        for status, expected in cases.items():
            with self.subTest(status=status):
                self.assertEqual(core.recommended_graphics_preset(status), expected)

    def test_video_memory_target_is_passed_to_the_game(self):
        app = dict(core.APP_DEFAULTS)
        with patch.dict(os.environ, {}, clear=True):
            self.assertNotIn('BB_GC_BUDGET_MB', core.game_environment(app))
            app['vram_budget_mb'] = '3072'
            self.assertEqual(core.game_environment(app)['BB_GC_BUDGET_MB'], '3072')
            app['vram_budget_mb'] = '999999'
            self.assertNotIn('BB_GC_BUDGET_MB', core.game_environment(app))


if __name__ == '__main__':
    unittest.main()
