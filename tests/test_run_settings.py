"""Exercise run.sh across a re-exec with lightweight preparation/probe stand-ins."""
from paths import ROOT
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest


class RestartResolutionTests(unittest.TestCase):
    def run_restarts(self, explicit=False, live=False, ini_extra='', caps=None, bare_path=False,
                     output_res='1280x720', force_patches=False, fps_env=None):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            # Preparation is unrelated to this test; allow the real patch compiler to
            # validate writes against a single ELF load segment spanning the game image.
            out = data / 'out'
            out.mkdir()
            elf = bytearray(120)
            struct.pack_into('<Q', elf, 0x20, 64)
            struct.pack_into('<HH', elf, 0x36, 56, 1)
            struct.pack_into('<IIQQQQQQ', elf, 64, 1, 0, 0, 0, 0, 0, 0x6000000, 0)
            (out / 'eboot.elf').write_bytes(elf)
            (data / 'eboot.bin').touch()
            config = data / 'bbport.ini'
            config.write_text(f'upscaler=fsr3\npreset=1\noutput_res={output_res}\n' + ini_extra)
            if caps is not None:  # the GPU check next to the probe (live_resolution=auto)
                tool = data / 'bb-gpu-capabilities'
                tool.write_text(f'#!/bin/sh\necho {caps}\n')
                tool.chmod(0o755)
            python = data / 'python'
            python.write_text(f'#!{sys.executable}\n' +
                'import subprocess, sys\n'
                'if sys.argv[1] in ("scripts/patches.py", "scripts/mods.py", "scripts/hud_layout.py"):\n'
                '    sys.exit(subprocess.call([sys.executable, *sys.argv[1:]]))\n')
            python.chmod(0o755)
            probe = data / 'probe'
            probe.write_text(f'#!{sys.executable}\n' +
                'import json, os\n'
                'from pathlib import Path\n'
                'config=Path(os.environ["BB_CONFIG"])\n'
                'stage=int(os.environ.get("BB_TEST_STAGE", "0"))\n'
                'with (config.parent/"environments").open("a") as f:\n'
                '    row={key:os.environ.get(key) for key in '
                '("BB_RENDER_RES", "BB_OUTPUT_RES", "BB_AUTO_RENDER_RES", "BB_UI_RES", '
                '"BB_FPS", "BB_FPS_LIMIT", "BB_VBLANK_HZ")}\n'
                '    row["hud_layer"]=(config.parent/"out/hud_layout/dvdroot_ps4").is_dir()\n'
                '    f.write(json.dumps(row)+"\\n")\n'
                'if stage<2:\n'
                '    config.write_text("upscaler=fsr3\\npreset=4\\noutput_res="+'
                '("1280x720" if stage==0 else "1920x1080")+"\\n")\n'
                '    os.environ["BB_TEST_STAGE"]=str(stage+1)\n'
                '    os.execlp("bash", "bash", "run.sh")\n')
            probe.chmod(0o755)
            env = dict(os.environ, BB_PREBUILT='1', BB_PROBE=str(probe), PYTHON=str(python),
                       BB_DATA_DIR=str(data), BB_CONFIG=str(config), BB_GAME_DIR=str(data))
            for key in ('BB_RENDER_RES', 'BB_OUTPUT_RES', 'BB_AUTO_RENDER_RES', 'BB_TEST_STAGE',
                        'BB_FPS', 'BB_FPS_LIMIT', 'BB_VBLANK_HZ'):
                env.pop(key, None)
            if fps_env:
                env.update(fps_env)
            env.pop('BB_LIVE_RES', None)
            env.pop('BB_FORCE_PATCHES', None)
            if force_patches:
                env['BB_FORCE_PATCHES'] = '1'
            if explicit:
                env['BB_RENDER_RES'] = '800x450'
            if live:
                env['BB_LIVE_RES'] = '1'
            if bare_path:  # the AppImage's PATH: coreutils and bash, no sed/grep
                tools = data / 'bin'
                tools.mkdir()
                for name in ('bash', 'dirname', 'mkdir', 'realpath'):
                    (tools / name).symlink_to(shutil.which(name))
                env['PATH'] = str(tools)
            subprocess.run([shutil.which('bash'), 'run.sh'], cwd=ROOT, env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=30)
            return [json.loads(line) for line in (data / 'environments').read_text().splitlines()]

    def test_outputs_other_than_1080p_patch_the_render_size_and_restarts_recompute_it(self):
        rows = self.run_restarts()
        # 720p Quality, 720p Ultra Performance after a restart, then 1080p (live host targets).
        self.assertEqual([row['BB_RENDER_RES'] for row in rows], ['854x480', '426x240', None])
        self.assertEqual([row['BB_OUTPUT_RES'] for row in rows], ['1280x720', '1280x720', None])
        self.assertEqual([row['BB_AUTO_RENDER_RES'] for row in rows], ['1', '1', None])

    def test_live_resolution_keeps_guest_sizes_native(self):
        rows = self.run_restarts(live=True)
        self.assertTrue(all(row['BB_RENDER_RES'] is None for row in rows))
        self.assertTrue(all(row['BB_OUTPUT_RES'] is None for row in rows))
        self.assertTrue(all(row['BB_AUTO_RENDER_RES'] is None for row in rows))

    def test_live_resolution_setting_and_gpu_check(self):
        # Only the first launch matters here: the probe rewrites bbport.ini for the restarts.
        self.assertIsNone(self.run_restarts(ini_extra='live_resolution=1\n')[0]['BB_RENDER_RES'])
        self.assertEqual(self.run_restarts(ini_extra='live_resolution=0\n', caps=1)[0]['BB_RENDER_RES'],
                         '854x480')
        # Unset: off (the startup patch), whatever the GPU; auto asks the GPU check.
        self.assertEqual(self.run_restarts(caps=1)[0]['BB_RENDER_RES'], '854x480')
        self.assertIsNone(self.run_restarts(ini_extra='live_resolution=auto\n', caps=1)[0]['BB_RENDER_RES'])
        self.assertEqual(self.run_restarts(ini_extra='live_resolution=auto\n', caps=0)[0]['BB_RENDER_RES'],
                         '854x480')

    def test_live_resolution_without_sed_or_grep(self):
        # A missing sed ended run.sh (exit 127) before the game in the AppImage on NixOS.
        self.assertEqual(self.run_restarts(ini_extra='live_resolution=0\n', caps=1,
                                           bare_path=True)[0]['BB_RENDER_RES'], '854x480')
        self.assertIsNone(self.run_restarts(ini_extra='live_resolution=auto\n', caps=1,
                                            bare_path=True)[0]['BB_RENDER_RES'])

    def test_explicit_render_override_survives_restart(self):
        rows = self.run_restarts(explicit=True)
        self.assertEqual([row['BB_RENDER_RES'] for row in rows], ['800x450'] * 3)
        self.assertTrue(all(row['BB_AUTO_RENDER_RES'] is None for row in rows))

    def test_explicit_render_size_does_not_invent_a_movie_viewport(self):
        rows = self.run_restarts(explicit=True, output_res='1280x800')
        self.assertTrue(all(row['BB_UI_RES'] is None for row in rows))

    def test_16_9_outputs_do_not_set_the_movie_viewport(self):
        rows = self.run_restarts()
        self.assertTrue(all(row['BB_UI_RES'] is None for row in rows))

    def test_16_10_exports_the_output_as_the_movie_viewport(self):
        rows = self.run_restarts(output_res='1280x800')
        self.assertEqual(rows[0]['BB_UI_RES'], '1280x800')
        # The probe switches to 16:9 sizes; a stale viewport must not survive the restart.
        self.assertEqual([row['BB_UI_RES'] for row in rows[1:]], [None, None])
        self.assertFalse(any(row['hud_layer'] for row in rows))

    def test_ultrawide_builds_the_hud_layer_and_exports_the_canvas(self):
        rows = self.run_restarts(output_res='3440x1440', force_patches=True)
        self.assertEqual(rows[0]['BB_UI_RES'], '2580x1080')
        self.assertTrue(rows[0]['hud_layer'])

    def test_fps_mode_60_from_ini_sets_env_and_vblank(self):
        rows = self.run_restarts(ini_extra='fps_mode=60\nfps_limit=0\n')
        self.assertEqual(rows[0]['BB_FPS'], '60')
        self.assertIsNone(rows[0]['BB_FPS_LIMIT'])
        self.assertEqual(rows[0]['BB_VBLANK_HZ'], '60')

    def test_fps_mode_uncap_from_ini_sets_vblank_0(self):
        rows = self.run_restarts(ini_extra='fps_mode=uncap\nfps_limit=0\n')
        self.assertEqual(rows[0]['BB_FPS'], 'uncap')
        self.assertIsNone(rows[0]['BB_FPS_LIMIT'])
        self.assertEqual(rows[0]['BB_VBLANK_HZ'], '0')

    def test_fps_limit_positive_from_ini_is_exported(self):
        rows = self.run_restarts(ini_extra='fps_mode=uncap\nfps_limit=90\n')
        self.assertEqual(rows[0]['BB_FPS'], 'uncap')
        self.assertEqual(rows[0]['BB_FPS_LIMIT'], '90')
        self.assertEqual(rows[0]['BB_VBLANK_HZ'], '0')

    def test_explicit_cli_fps_limit_zero_is_preserved(self):
        # Explicit BB_FPS_LIMIT=0 from CLI/scripts for benchmarks must not be overwritten by ini.
        rows = self.run_restarts(ini_extra='fps_mode=60\nfps_limit=60\n', fps_env={'BB_FPS_LIMIT': '0'})
        self.assertEqual(rows[0]['BB_FPS_LIMIT'], '0')


class SupervisorRestartTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name)
        out = self.data / 'out'
        out.mkdir()
        elf = bytearray(120)
        struct.pack_into('<Q', elf, 0x20, 64)
        struct.pack_into('<HH', elf, 0x36, 56, 1)
        struct.pack_into('<IIQQQQQQ', elf, 64, 1, 0, 0, 0, 0, 0, 0x6000000, 0)
        (out / 'eboot.elf').write_bytes(elf)
        (self.data / 'eboot.bin').touch()
        self.config = self.data / 'bbport.ini'
        self.config.write_text('upscaler=fsr3\npreset=1\noutput_res=1920x1080\n')

        self.python = self.data / 'python'
        self.python.write_text(
            f'#!{sys.executable}\n'
            'import subprocess, sys\n'
            'if sys.argv[1] in ("scripts/patches.py", "scripts/mods.py", "scripts/hud_layout.py"):\n'
            '    sys.exit(subprocess.call([sys.executable, *sys.argv[1:]]))\n'
        )
        self.python.chmod(0o755)

    def run_supervisor(self, probe_script, extra_args=None):
        probe = self.data / 'probe'
        probe.write_text(probe_script)
        probe.chmod(0o755)
        env = dict(
            os.environ,
            BB_PREBUILT='1',
            BB_PROBE=str(probe),
            PYTHON=str(self.python),
            BB_DATA_DIR=str(self.data),
            BB_CONFIG=str(self.config),
            BB_GAME_DIR=str(self.data),
        )
        cmd = [shutil.which('bash'), 'run.sh']
        if extra_args:
            cmd.extend(extra_args)
        proc = subprocess.run(
            cmd,
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )
        return proc

    def test_supervisor_restarts_on_code_85_and_preserves_arguments(self):
        probe_script = (
            f'#!{sys.executable}\n'
            'import sys, os\n'
            'from pathlib import Path\n'
            'data = Path(os.environ["BB_DATA_DIR"])\n'
            'log_file = data / "probe_calls.log"\n'
            'count = 0\n'
            'if log_file.is_file():\n'
            '    count = len(log_file.read_text().splitlines())\n'
            'with log_file.open("a") as f:\n'
            '    f.write(f"call {count}: {sys.argv[1:]}\\n")\n'
            'if count == 0:\n'
            '    sys.exit(85)\n'
            'sys.exit(0)\n'
        )
        proc = self.run_supervisor(probe_script, extra_args=['--custom-arg', 'value42'])
        self.assertEqual(proc.returncode, 0)
        calls = (self.data / "probe_calls.log").read_text().splitlines()
        self.assertEqual(len(calls), 2)
        self.assertIn("--custom-arg", calls[0])
        self.assertIn("value42", calls[0])
        self.assertIn("--custom-arg", calls[1])
        self.assertIn("value42", calls[1])

    def test_supervisor_does_not_restart_on_normal_exit(self):
        probe_script = (
            f'#!{sys.executable}\n'
            'import sys, os\n'
            'from pathlib import Path\n'
            'data = Path(os.environ["BB_DATA_DIR"])\n'
            'log_file = data / "probe_calls.log"\n'
            'with log_file.open("a") as f:\n'
            '    f.write("call\\n")\n'
            'sys.exit(0)\n'
        )
        proc = self.run_supervisor(probe_script)
        self.assertEqual(proc.returncode, 0)
        calls = (self.data / "probe_calls.log").read_text().splitlines()
        self.assertEqual(len(calls), 1)

    def test_supervisor_does_not_restart_on_runtime_failure(self):
        probe_script = (
            f'#!{sys.executable}\n'
            'import sys, os\n'
            'from pathlib import Path\n'
            'data = Path(os.environ["BB_DATA_DIR"])\n'
            'log_file = data / "probe_calls.log"\n'
            'with log_file.open("a") as f:\n'
            '    f.write("call\\n")\n'
            'sys.exit(2)\n'
        )
        proc = self.run_supervisor(probe_script)
        self.assertEqual(proc.returncode, 2)
        calls = (self.data / "probe_calls.log").read_text().splitlines()
        self.assertEqual(len(calls), 1)

    def test_supervisor_bounds_restarts_to_single_attempt(self):
        probe_script = (
            f'#!{sys.executable}\n'
            'import sys, os\n'
            'from pathlib import Path\n'
            'data = Path(os.environ["BB_DATA_DIR"])\n'
            'log_file = data / "probe_calls.log"\n'
            'with log_file.open("a") as f:\n'
            '    f.write("call\\n")\n'
            'sys.exit(85)\n'
        )
        proc = self.run_supervisor(probe_script)
        self.assertEqual(proc.returncode, 85)
        self.assertIn(b"refusing endless loop", proc.stderr)
        calls = (self.data / "probe_calls.log").read_text().splitlines()
        self.assertEqual(len(calls), 2)

    def test_supervisor_allows_subsequent_restart_after_successful_session(self):
        # A restart requested during a second, stable session must succeed and not be blocked.
        probe_script = (
            f'#!{sys.executable}\n'
            'import sys, os\n'
            'from pathlib import Path\n'
            'data = Path(os.environ["BB_DATA_DIR"])\n'
            'log_file = data / "probe_calls.log"\n'
            'count = 0\n'
            'if log_file.is_file():\n'
            '    count = len(log_file.read_text().splitlines())\n'
            'with log_file.open("a") as f:\n'
            '    f.write(f"call {count}\\n")\n'
            'if count == 0:\n'
            '    # First user restart request\n'
            '    sys.exit(85)\n'
            'elif count == 1:\n'
            '    # Second session: runs successfully and reaches steady state\n'
            '    (data / "session_steady").touch()\n'
            '    # User requests another restart later in gameplay\n'
            '    sys.exit(85)\n'
            'else:\n'
            '    # Third session: runs and exits normally\n'
            '    sys.exit(0)\n'
        )
        proc = self.run_supervisor(probe_script)
        self.assertEqual(proc.returncode, 0)
        calls = (self.data / "probe_calls.log").read_text().splitlines()
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls, ["call 0", "call 1", "call 2"])



