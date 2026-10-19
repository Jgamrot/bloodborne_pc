import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'launcher'))
import bbport_coop as coop


class CoopTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        patcher = mock.patch.dict(os.environ, {'LOCALAPPDATA': self.folder.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.folder.cleanup)

    def test_invite_round_trip_and_damage(self):
        code = coop.make_invite('100.65.141.9', 'abc123')
        self.assertTrue(code.startswith(coop.INVITE_PREFIX))
        self.assertEqual(coop.read_invite('  ' + code + '\n'), ('100.65.141.9', 'abc123'))
        # Wrapped by a chat app over two lines.
        self.assertEqual(coop.read_invite(code[:20] + '\r\n ' + code[20:]), ('100.65.141.9', 'abc123'))
        with self.assertRaises(coop.CoopError):
            coop.read_invite('hello')
        with self.assertRaises(coop.CoopError):
            coop.read_invite(coop.INVITE_PREFIX + '!!!')

    def test_registration_key_is_made_once(self):
        cfg = coop.package_dir('server') / 'server' / 'shadnet.cfg'
        cfg.parent.mkdir(parents=True)
        cfg.write_text('[General]\nHost=0.0.0.0\nRegistrationSecretKey=\n', encoding='utf-8')
        with mock.patch.object(coop, 'bundled_server', return_value=None):  # BBSC's own server
            key = coop.registration_key()
            self.assertEqual(len(key), 40)
            self.assertEqual(coop.registration_key(), key)
        self.assertIn(f'RegistrationSecretKey={key}', cfg.read_text(encoding='utf-8'))

    def test_the_bundled_server_runs_from_its_own_folder_with_the_hosts_key(self):
        # This port's shadnet.exe (STUN fix) keeps its config and database beside itself: it is
        # copied under bbport-coop and takes BBSC's configuration, key included, the first time.
        bbsc = coop.package_dir('server') / 'server'
        bbsc.mkdir(parents=True)
        (bbsc / 'shadnet.cfg').write_text('[General]\nRegistrationSecretKey=hostkey\n', encoding='utf-8')
        bundled = Path(self.folder.name) / 'port' / 'bin' / 'coop-server'
        (bundled / 'sqldrivers').mkdir(parents=True)
        (bundled / 'shadnet.exe').write_bytes(b'new server')
        (bundled / 'sqldrivers' / 'qsqlite.dll').write_bytes(b'plugin')
        with mock.patch.object(coop, 'bundled_server', return_value=bundled):
            self.assertEqual(coop.registration_key(), 'hostkey')
            folder = coop.shadnet_dir()
            self.assertEqual(folder, coop.coop_dir() / 'shadnet-bbport')
            self.assertEqual((folder / 'shadnet.exe').read_bytes(), b'new server')
            self.assertTrue((folder / 'sqldrivers' / 'qsqlite.dll').is_file())
            # Its own config from then on; an update of the programs keeps it.
            (folder / 'shadnet.cfg').write_text('[General]\nRegistrationSecretKey=kept\n', encoding='utf-8')
            (bundled / 'shadnet.exe').write_bytes(b'newer server!')
            coop.shadnet_dir(sync=True)
            self.assertEqual((folder / 'shadnet.exe').read_bytes(), b'newer server!')
            self.assertEqual(coop.registration_key(), 'kept')

    def test_environment_points_this_launch_at_the_host(self):
        base = {'BB_ONLINE': '0', 'BB_SHADNET_NPID': 'normal', 'BB_GAME_DIR': 'game'}
        port = Path(self.folder.name) / 'bbport-windows'
        env = coop.co_op_environment(base, '100.65.141.9', 'hunter', 'secret', port / 'bin' / 'bb-probe.exe')
        self.assertEqual(env['BBSC_RELAY'], '100.65.141.9:20444')
        self.assertEqual(env['BB_COOP'], '1')
        # BBSC reads the redirects itself from <port>\user\host_overrides.json (the game starts there).
        self.assertEqual((port / 'user' / 'host_overrides.json').read_text(encoding='utf-8'),
                         Path(env['BB_HOST_OVERRIDES']).read_text(encoding='utf-8'))
        self.assertEqual(base['BB_SHADNET_NPID'], 'normal')  # the normal environment is untouched
        self.assertEqual(env['BB_SHADNET_SERVER'], '100.65.141.9:31313')
        self.assertEqual(env['BB_SHADNET_WEBAPI'], 'http://100.65.141.9:31315')
        self.assertEqual(env['BB_SHADNET_NPID'], 'hunter')
        self.assertTrue(env['BB_PROBE'].endswith('bbsc-launch.exe'))
        self.assertEqual(env['BB_GAME_DIR'], 'game')
        overrides = json.loads(Path(env['BB_HOST_OVERRIDES']).read_text(encoding='utf-8'))
        self.assertEqual(overrides['https://ss4.scej-network.jp:20443'], 'http://100.65.141.9:20443')
        self.assertEqual(overrides['https://thehuntersdream.com:18671/summon_messenger'],
                         'http://100.65.141.9:31315')
        self.assertNotIn('BBSC_SAVE_DIR', env)  # no saves yet: BBSC finds none either way

    def test_bbsc_is_told_where_the_saves_are(self):
        # BBSC gives its co-op kit (Hunt Bell, Kin Bell) only after backing up the save it finds.
        user = Path(self.folder.name) / 'saves'
        older = user / 'savedata' / '2' / 'CUSA00207' / 'SPRJ0005'
        newer = user / 'savedata' / '1' / 'CUSA00207' / 'SPRJ0005'
        for folder, when in ((older, 1000), (newer, 2000)):
            folder.mkdir(parents=True)
            (folder / 'userdata0000').write_bytes(b'save')
            os.utime(folder / 'userdata0000', (when, when))
        port = Path(self.folder.name) / 'bbport-windows'
        env = coop.co_op_environment({'BB_USER_DIR': str(user)}, '100.65.141.9', 'hunter', 'secret',
                                     port / 'bin' / 'bb-probe.exe')
        self.assertEqual(Path(env['BBSC_SAVE_DIR']), newer)
        # With the copy made before the session, BBSC backs that up instead: copying the save the
        # running game has open failed, and the kit was never given.
        copy = coop.backup_saves(user)
        env = coop.co_op_environment({'BB_USER_DIR': str(user)}, '100.65.141.9', 'hunter', 'secret',
                                     port / 'bin' / 'bb-probe.exe', save_copy=copy)
        self.assertEqual(Path(env['BBSC_SAVE_DIR']),
                         copy / 'savedata' / '1' / 'CUSA00207' / 'SPRJ0005')
        self.assertTrue((Path(env['BBSC_SAVE_DIR']) / 'userdata0000').is_file())

    def test_unsafe_package_paths_are_refused(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as archive:
            archive.writestr('../outside.txt', 'x')
        with zipfile.ZipFile(data) as archive, self.assertRaises(coop.CoopError):
            coop._safe_extract(archive, Path(self.folder.name) / 'unpack')

    def test_firewall_rules_stay_on_tailscale_and_the_home_network(self):
        script = coop._firewall_script(r'C:\Games\bbport\bin\bb-probe.exe')
        self.assertIn("@('100.64.0.0/10','LocalSubnet')", script)
        self.assertNotIn('Any', script)
        self.assertEqual(script.count('New-NetFirewallRule'), len(coop.FIREWALL_PORTS) + 1)

    def test_tailscale_addresses(self):
        self.assertTrue(coop.is_tailscale('100.65.141.9'))
        self.assertFalse(coop.is_tailscale('100.128.0.1'))
        self.assertFalse(coop.is_tailscale('192.168.1.5'))

    def test_tailscale_is_found_on_path_outside_program_files(self):
        exe = r'E:\Installs\Tailscale\tailscale.exe'
        ran = mock.Mock(stdout='100.64.233.56\n')
        with mock.patch.object(coop.shutil, 'which', return_value=exe), \
                mock.patch.object(coop.subprocess, 'run', return_value=ran) as run:
            self.assertEqual(coop.tailscale_ip(), '100.64.233.56')
        self.assertEqual(run.call_args[0][0][0], str(Path(exe)))

    def test_tailscale_address_from_the_route_when_the_cli_is_missing(self):
        probe = mock.MagicMock()
        probe.__enter__.return_value.getsockname.return_value = ('100.64.233.56', 50000)
        with mock.patch.object(coop, 'tailscale_exe', return_value=None), \
                mock.patch.object(coop.socket, 'socket', return_value=probe):
            self.assertEqual(coop.tailscale_ip(), '100.64.233.56')
        probe.__enter__.return_value.getsockname.return_value = ('192.168.1.5', 50000)
        with mock.patch.object(coop, 'tailscale_exe', return_value=None), \
                mock.patch.object(coop.socket, 'socket', return_value=probe):
            self.assertIsNone(coop.tailscale_ip())

    def test_account_names_are_checked_before_asking_the_server(self):
        with self.assertRaises(coop.CoopError):
            coop.create_account('100.65.141.9', '', 'x', 'secret')
        with self.assertRaises(coop.CoopError):
            coop.create_account('100.65.141.9', '', 'hunter', 'abc')

    @unittest.skipUnless(os.name == 'nt', 'Windows process trees')
    def test_stopping_a_server_ends_its_child_too(self):
        # Like BBSC-GameServer.exe: a parent that starts a second copy of itself and waits.
        import subprocess
        import time
        pid_file = Path(self.folder.name) / 'child.pid'
        child = 'import time; time.sleep(60)'
        parent = (f"import subprocess, sys, pathlib; c = subprocess.Popen([sys.executable, '-c', {child!r}]); "
                  f"pathlib.Path({str(pid_file)!r}).write_text(str(c.pid)); c.wait()")
        process = subprocess.Popen([sys.executable, '-c', parent])
        for _ in range(100):
            if pid_file.exists() and pid_file.read_text():
                break
            time.sleep(0.05)
        child_pid = int(pid_file.read_text())
        coop.end_tree(process)
        self.assertIsNotNone(process.poll())
        alive = subprocess.run(['tasklist', '/FI', f'PID eq {child_pid}', '/NH'], capture_output=True,
                               text=True).stdout
        self.assertNotIn(str(child_pid), alive)


if __name__ == '__main__':
    unittest.main()
