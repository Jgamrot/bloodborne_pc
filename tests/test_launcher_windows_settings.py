"""Configuration, asset and process-reader regressions for the Windows launcher.

Runs on any platform: the helpers under test do not open a window and the Windows-only
process job is exercised by the launcher itself.
"""
import importlib.util
import json
import os
from pathlib import Path
import queue
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('windows_launcher', ROOT / 'launcher/bbport_launcher_win.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)
run_spec = importlib.util.spec_from_file_location('bbport_run', ROOT / 'run.py')
run = importlib.util.module_from_spec(run_spec)
run_spec.loader.exec_module(run)

SPIRV_HEADER = b'\x03\x02\x23\x07' + bytes(16)
FSR411_PASSES = ['spd', 'prepass', 'pass0_post', 'postpass', 'rcas'] + [
    part for i in range(1, 13) for part in (f'pass{i}', f'pass{i}_post')]


class Variable:
    def __init__(self, value):
        self.value = value
        self.callbacks = []

    def get(self):
        return self.value

    def set(self, value):
        self.value = value
        for callback in self.callbacks:
            callback()

    def trace_add(self, _mode, callback):
        self.callbacks.append(callback)


class Combobox:
    def __init__(self, _parent, **options):
        self.values = options['values']
        self.text = ''

    def current(self, index=None):
        if index is not None:
            self.text = self.values[index]
        return self.values.index(self.text) if self.text in self.values else -1

    def set(self, text):
        self.text = text

    def get(self):
        return self.text

    def bind(self, _event, _callback):
        pass


class FakeTk:
    class Var(Variable):
        def __init__(self, value=None):
            super().__init__(value)

    BooleanVar = StringVar = DoubleVar = Var


class BadLog:
    def __init__(self):
        self.closed = False

    def write(self, _text):
        raise OSError('disk full')

    def close(self):
        self.closed = True


class Stdout:
    def __init__(self):
        self.lines = iter([b'one\n', b'\xff two\n', b'three\n'])

    def readline(self):
        return next(self.lines, b'')


class Process:
    def __init__(self):
        self.stdout = Stdout()

    def wait(self):
        return 3


class SettingsTests(unittest.TestCase):
    def test_non_object_settings_json_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / 'settings.json'
            config.write_text('[1, 2]', encoding='utf-8')
            with mock.patch.object(launcher, 'CONFIG_FILE', config):
                self.assertEqual(launcher.load_app_settings(), launcher.APP_DEFAULTS)

    def test_malformed_json_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / 'settings.json'
            config.write_text('{', encoding='utf-8')
            self.assertEqual(launcher.load_json(config, {}), {})

    def test_invalid_types_fall_back_and_unknown_keys_survive(self):
        settings = launcher.validated_settings({
            'mods_enabled': 'yes', 'language': 8, 'game_dir': None,
            'future_setting': {'kept': True}})
        self.assertEqual(settings['mods_enabled'], launcher.APP_DEFAULTS['mods_enabled'])
        self.assertEqual(settings['language'], '8')
        self.assertEqual(settings['game_dir'], launcher.APP_DEFAULTS['game_dir'])
        self.assertEqual(settings['future_setting'], {'kept': True})

    def test_unknown_settings_survive_a_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / 'settings.json'
            config.write_text(json.dumps({'future_setting': 42, 'fullscreen': 'yes'}), encoding='utf-8')
            with mock.patch.object(launcher, 'CONFIG_FILE', config):
                settings = launcher.load_app_settings()
                launcher.atomic_write_text(config, json.dumps(settings))
            saved = json.loads(config.read_text(encoding='utf-8'))
            self.assertEqual(saved['future_setting'], 42)
            self.assertEqual(saved['fullscreen'], launcher.APP_DEFAULTS['fullscreen'])

    def test_ini_path_with_empty_bb_config_falls_back_to_the_data_directory(self):
        with mock.patch.dict(os.environ, {'BB_CONFIG': ''}):
            self.assertEqual(launcher.ini_path(), launcher.DATA_DIR / 'bbport.ini')

    def test_non_utf8_ini_is_read_without_crashing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'bbport.ini'
            path.write_bytes(b'# caf\xe9\nupscaler=fsr4\n')
            with mock.patch.object(launcher, 'ini_path', lambda: path):
                values, lines = launcher.load_ini()
            self.assertEqual(values['upscaler'], 'fsr4')
            self.assertTrue(any('caf' in line for line in lines))

    def test_save_ini_keeps_comments_unknown_keys_and_final_newline(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'bbport.ini'
            path.write_text('# keep this\nupscaler=fsr3\ncustom_tool=value\n', encoding='utf-8')
            lines = path.read_text(encoding='utf-8').splitlines()
            with mock.patch.object(launcher, 'ini_path', lambda: path):
                launcher.save_ini({'upscaler': 'fsr4'}, lines)
            text = path.read_text(encoding='utf-8')
            self.assertIn('# keep this', text)
            self.assertIn('custom_tool=value', text)
            self.assertIn('upscaler=fsr4', text)
            self.assertTrue(text.endswith('\n'))

    def test_malformed_sharpness_falls_back_without_crashing(self):
        window = launcher.Launcher.__new__(launcher.Launcher)
        window.tk = FakeTk
        window.vars = {}
        window.ini = {'sharpness': 'not a number'}
        window.ini_lines = []
        self.assertEqual(window.var('sharpness', 'ini').get(), 0.5)

    def test_unknown_choice_value_stays_selected(self):
        window = launcher.Launcher.__new__(launcher.Launcher)
        variable = Variable('future-upscaler')
        window.var = lambda *_: variable
        window.ttk = SimpleNamespace(Combobox=Combobox)
        box = window.choice(None, 'upscaler', 'ini', launcher.UPSCALERS)
        self.assertEqual(variable.get(), 'future-upscaler')
        self.assertIn('future-upscaler', box.values)

    def test_paths_with_spaces_and_unicode_are_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'saves ü' / 'settings.json'
            launcher.atomic_write_text(path, '{"ok": true}')
            self.assertEqual(path.read_text(encoding='utf-8'), '{"ok": true}')

    def test_failed_atomic_write_keeps_the_old_file_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'settings.json'
            path.write_text('old', encoding='utf-8')
            with mock.patch.object(launcher.os, 'replace', side_effect=OSError('locked')):
                with self.assertRaises(OSError):
                    launcher.atomic_write_text(path, 'new')
            self.assertEqual(path.read_text(encoding='utf-8'), 'old')
            self.assertEqual(list(Path(tmp).glob('.*.tmp')), [])

    def test_environment_expands_variables_and_user_home(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {'BBPORT_TEST_DIR': tmp}):
            self.assertEqual(launcher.expanded_path('$BBPORT_TEST_DIR/saves'),
                             str(Path(tmp) / 'saves'))
            self.assertEqual(launcher.expanded_path('~'), str(Path.home()))

    def test_game_environment_carries_settings_to_run_py(self):
        settings = launcher.validated_settings({
            'game_dir': 'C:/Games/Blood borne ü', 'user_dir': 'C:/Users/Test/Saves',
            'dlc_dir': 'C:/Games/DLC', 'mods_enabled': True, 'fps_mode': '60',
            'frame_cap': '90', 'fullscreen': True, 'hdr': True,
            'present_mode': 'FifoRelaxed', 'extra_env': 'BB_CUSTOM=1'})
        env = launcher.game_environment(settings)
        self.assertEqual(env['BB_GAME_DIR'], str(Path('C:/Games/Blood borne ü')))
        self.assertEqual(env['BB_USER_DIR'], str(Path('C:/Users/Test/Saves')))
        self.assertEqual(env['BB_DLC_DIR'], str(Path('C:/Games/DLC')))
        self.assertEqual(env['BB_FPS'], '60')
        self.assertEqual(env['BB_FPS_LIMIT'], '90')
        self.assertEqual(env['BB_FULLSCREEN'], '1')
        self.assertEqual(env['BB_HDR'], '1')
        self.assertEqual(env['BB_PRESENT_MODE'], 'FifoRelaxed')
        self.assertEqual(env['BB_CUSTOM'], '1')


class AssetTests(unittest.TestCase):
    def test_spirv_header_and_sizes_are_validated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            good = root / 'good.spv'
            good.write_bytes(SPIRV_HEADER)
            bad = root / 'bad.spv'
            bad.write_bytes(bytes(20))
            self.assertTrue(launcher.validate_fsr4_file(good))
            self.assertFalse(launcher.validate_fsr4_file(bad))
            initializers = root / 'fsr4_model_v07_i8_quality_initializers.bin'
            initializers.write_bytes(bytes(89216))
            self.assertTrue(launcher.validate_fsr4_file(initializers))
            initializers.write_bytes(bytes(100))
            self.assertFalse(launcher.validate_fsr4_file(initializers))

    def test_partial_fsr411_model_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / 't1080_m0'
            folder.mkdir()
            for name in FSR411_PASSES:
                (folder / f'{name}.spv').write_bytes(SPIRV_HEADER)
            (folder / 'initializer.bin').write_bytes(bytes(131072))
            self.assertIsNone(launcher.fsr411_problem(root, '1920x1080', 1))
            (folder / 'pass5.spv').unlink()
            self.assertEqual(launcher.fsr411_problem(root, '1920x1080', 1), 't1080_m0/pass5.spv')

    def test_fsr411_tier_follows_the_output_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(launcher.fsr411_problem(root, '3840x2160', 3), 't2160_m0/spd.spv')
            self.assertEqual(launcher.fsr411_problem(root, '1280x720', 4), 't1080_m1/spd.spv')

    @unittest.skipIf(os.name == 'nt', 'the fake checker is a POSIX shell script')
    def test_gpu_capability_probe_reads_the_checker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'out').mkdir()
            exe = root / 'out' / 'bb-gpu-capabilities.exe'
            exe.write_text('#!/bin/sh\necho 1\n', encoding='utf-8')
            exe.chmod(0o755)
            with mock.patch.object(launcher, 'PORT_DIR', root):
                self.assertTrue(launcher.fsr4_gpu_supported())


class ProcessReaderTests(unittest.TestCase):
    def test_stale_exit_does_not_clear_a_newer_process(self):
        window = launcher.Launcher.__new__(launcher.Launcher)
        window.ui_calls = queue.Queue()
        window.output = queue.Queue()
        window.process = current = object()
        window.job = None
        window.stop_button = SimpleNamespace(configure=lambda **_kwargs: None)
        window.refresh_status = lambda: None
        window.append = lambda _text: None
        window.root = SimpleNamespace(after=lambda *_args: None)
        window.output.put((1, object()))
        window.drain_output()
        self.assertIs(window.process, current)
        window.output.put((0, current))
        window.drain_output()
        self.assertIsNone(window.process)

    def test_a_failing_log_does_not_stop_the_reader(self):
        window = launcher.Launcher.__new__(launcher.Launcher)
        window.app = {}
        window.output = queue.Queue()
        window.ui_calls = queue.Queue()
        window.messagebox = SimpleNamespace(showwarning=lambda *_args: None)
        log = BadLog()
        process = Process()
        with mock.patch.object(launcher, 'open_run_log', lambda _folder: log):
            window.read_output(process)
        items = list(window.output.queue)
        self.assertEqual(items[0], 'one\n')
        self.assertIn('\ufffd', items[1])
        self.assertEqual(items[2], 'three\n')
        self.assertEqual(items[3], (3, process))
        self.assertTrue(log.closed)


class EntryPointTests(unittest.TestCase):
    def test_entry_points_are_absolute_and_independent_of_the_working_directory(self):
        self.assertTrue(launcher.PORT_DIR.is_absolute())
        self.assertTrue(run.PORT.is_absolute())
        self.assertTrue((launcher.PORT_DIR / 'scripts' / 'patches.py').is_file())
        self.assertTrue((run.PORT / 'scripts' / 'patches.py').is_file())
        command = launcher.run_command()
        self.assertTrue(Path(command[0]).is_absolute())
        if not launcher.FROZEN:
            self.assertTrue(Path(command[-1]).is_absolute())

    def test_malformed_ini_values_are_ignored_by_run_helpers(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / 'bbport.ini'
            config.write_text('output_res=wide\nhud_position=near\n', encoding='utf-8')
            self.assertIsNone(run.ini_value(config, 'missing'))
            self.assertEqual(run.ini_value(config, 'output_res'), 'wide')
            self.assertFalse(run.auto_live_blurs_dof('1920x1080', config))


if __name__ == '__main__':
    unittest.main()
