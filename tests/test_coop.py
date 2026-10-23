import io
import json
import os
from pathlib import Path
import shutil
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

    def test_release_selection_pairs_assets_and_allows_prereleases_and_unusual_tags(self):
        release = {'tag_name': 'release_candidate-2', 'prerelease': True,
                   'body': 'This release supports BBport players.', 'assets': [
            {'name': 'BBSC-0.0.2-BBport.zip', 'digest': 'sha256:' + 'a' * 64, 'browser_download_url': 'client'},
            {'name': 'BBSC-0.0.2-Server.zip', 'digest': 'sha256:' + 'b' * 64, 'browser_download_url': 'server'},
            {'name': 'BBSC-9.0.0-Server-Linux.zip', 'digest': 'sha256:' + 'c' * 64},
        ]}
        with mock.patch.object(coop.json, 'load', return_value=[release]), \
                mock.patch.object(coop.urllib.request, 'urlopen'):
            selected, assets = coop.discover_release()
        self.assertEqual(selected['tag_name'], 'release_candidate-2')
        self.assertEqual(assets['client']['version'], '0.0.2')
        self.assertEqual(assets['server']['url'], 'server')

    def test_release_with_missing_or_mismatched_server_is_rejected(self):
        release = {'tag_name': 'v0.0.3', 'body': 'BBport compatible.', 'assets': [
            {'name': 'BBSC-0.0.3-BBport.zip', 'digest': 'sha256:' + 'a' * 64,
             'browser_download_url': 'client'},
            {'name': 'BBSC-0.0.2-Server.zip', 'digest': 'sha256:' + 'b' * 64,
             'browser_download_url': 'server'},
        ]}
        with mock.patch.object(coop.json, 'load', return_value=[release]), \
                mock.patch.object(coop.urllib.request, 'urlopen'), \
                self.assertRaises(coop.CoopError):
            coop.discover_release()

    def test_release_without_explicit_bbport_compatibility_is_not_selected(self):
        release = {'tag_name': 'v0.0.3', 'body': 'General release', 'assets': [
            {'name': 'BBSC-0.0.3-BBport.zip', 'digest': 'sha256:' + 'a' * 64,
             'browser_download_url': 'client'},
            {'name': 'BBSC-0.0.3-Server.zip', 'digest': 'sha256:' + 'b' * 64,
             'browser_download_url': 'server'},
        ]}
        with mock.patch.object(coop.json, 'load', return_value=[release]), \
                mock.patch.object(coop.urllib.request, 'urlopen'), \
                self.assertRaisesRegex(coop.CoopError, 'No compatible release'):
            coop.discover_release()

    def test_offline_fallback_requires_a_consistent_verified_pair(self):
        for kind in ('client', 'server'):
            root = coop.package_dir(kind)
            if kind == 'client':
                files = ('bbsc/bbsc-launch.exe', 'bbsc/bbsc.dll', 'account/shadnet-sample.exe')
            else:
                files = ('server/shadnet.exe', 'server/BBSC-GameServer.exe', 'server/shadnet.cfg')
            for relative in files:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'installed')
            (root / '.bbsc-release.json').write_text(json.dumps({'tag': 'v0.0.2'}), encoding='utf-8')
        marker = coop.coop_dir() / 'installed-release.json'
        marker.write_text(json.dumps({'tag': 'v0.0.2'}), encoding='utf-8')
        with mock.patch.object(coop, 'discover_release', side_effect=coop.CoopError('offline')):
            coop.ensure_packages()  # a complete verified pair remains usable
            (coop.package_dir('server') / '.bbsc-release.json').write_text(
                json.dumps({'tag': 'v0.0.1'}), encoding='utf-8')
            with self.assertRaisesRegex(coop.CoopError, 'offline'):
                coop.ensure_packages()  # mixed/incomplete pair must not launch offline

    def _package_asset(self, kind, root, version='0.0.2'):
        name = f'BBSC-{version}-{"BBport" if kind == "client" else "Server"}.zip'
        asset = {'name': name, 'url': name, 'digest': 'unused', 'version': version, 'tag': 'v0.0.2'}
        folder = Path(root) / Path(name).stem
        if kind == 'client':
            files = ('bbsc/bbsc-launch.exe', 'bbsc/bbsc.dll', 'account/shadnet-sample.exe')
        else:
            files = ('server/shadnet.exe', 'server/BBSC-GameServer.exe', 'server/shadnet.cfg')
        for name_part in files:
            path = folder / name_part
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'new')
        archive_path = Path(root) / name
        with zipfile.ZipFile(archive_path, 'w') as archive:
            for path in folder.rglob('*'):
                if path.is_file():
                    archive.write(path, path.relative_to(root))
        return asset, archive_path

    def test_upgrade_migrates_configuration_database_accounts_and_settings(self):
        old = coop.coop_dir() / 'BBSC-0.0.1-Server' / 'server'
        for relative, content in (('shadnet.cfg', b'RegistrationSecretKey=key'),
                                  ('db/accounts.db', b'accounts'), ('accounts/players.json', b'players'),
                                  ('settings/custom.json', b'settings')):
            path = old / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        self.assertTrue(coop._legacy_package_dir('server'))
        unpacked = Path(self.folder.name) / 'release'
        unpacked.mkdir()
        assets, archives = {}, {}
        for kind in ('client', 'server'):
            assets[kind], archives[kind] = self._package_asset(kind, unpacked)
        release = {'tag_name': 'v0.0.2'}
        with mock.patch.object(coop, 'discover_release', return_value=(release, assets)), \
                mock.patch.object(coop, '_download_asset', side_effect=lambda asset, destination, progress=None:
                                  archives['client' if asset is assets['client'] else 'server']):
            coop.install_release()
        new = coop.package_dir('server') / 'server'
        self.assertTrue(coop.installed('client'))
        self.assertTrue(coop.installed('server'))
        for relative, content in (('shadnet.cfg', b'RegistrationSecretKey=key'),
                                  ('db/accounts.db', b'accounts'), ('accounts/players.json', b'players'),
                                  ('settings/custom.json', b'settings')):
            self.assertEqual((new / relative).read_bytes(), content)

    def test_corrupted_archive_fails_without_touching_installed_packages(self):
        for kind in ('client', 'server'):
            target = coop.package_dir(kind)
            target.mkdir(parents=True)
            (target / 'sentinel').write_bytes(b'old')
        release = {'tag_name': 'v0.0.2'}
        assets = {kind: {'name': f'BBSC-0.0.2-{suffix}.zip', 'url': 'x', 'digest': 'unused',
                         'version': '0.0.2'} for kind, suffix in (('client', 'BBport'), ('server', 'Server'))}
        corrupt = Path(self.folder.name) / 'corrupt.zip'
        corrupt.write_bytes(b'not a zip archive')
        with mock.patch.object(coop, 'discover_release', return_value=(release, assets)), \
                mock.patch.object(coop, '_download_asset', return_value=corrupt), \
                self.assertRaisesRegex(coop.CoopError, 'not a valid package'):
            coop.install_release()
        for kind in ('client', 'server'):
            self.assertEqual((coop.package_dir(kind) / 'sentinel').read_bytes(), b'old')

    def test_failed_download_is_reported_without_installing(self):
        with mock.patch.object(coop.urllib.request, 'urlopen', side_effect=OSError('offline')):
            with self.assertRaisesRegex(coop.CoopError, 'Could not download'):
                coop._download_asset({'name': 'client.zip', 'url': 'https://example.invalid',
                                      'digest': '0' * 64}, Path(self.folder.name))

    def test_second_swap_failure_rolls_back_first_package(self):
        for kind in ('client', 'server'):
            target = coop.package_dir(kind)
            target.mkdir(parents=True)
            (target / 'sentinel').write_bytes(b'old-' + kind.encode())
        release = {'tag_name': 'v0.0.2'}
        assets = {}
        archives = {}
        unpacked = Path(self.folder.name) / 'unpacked'
        unpacked.mkdir()
        for kind in ('client', 'server'):
            assets[kind], archives[kind] = self._package_asset(kind, unpacked)
        def extract(zip_path, asset, staging):
            folder = staging / Path(asset['name']).stem
            folder.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(unpacked / folder.name, folder)
            return folder
        real_replace = coop.os.replace
        calls = 0
        def replace(src, dst):
            nonlocal calls
            calls += 1
            if calls == 4:
                raise OSError('simulated install failure')
            return real_replace(src, dst)
        with mock.patch.object(coop, 'discover_release', return_value=(release, assets)), \
                mock.patch.object(coop, '_download_asset', side_effect=lambda a, d, p=None: archives[
                    'client' if a is assets['client'] else 'server']), \
                mock.patch.object(coop, '_extract_package', side_effect=extract), \
                mock.patch.object(coop.os, 'replace', side_effect=replace), \
                self.assertRaisesRegex(coop.CoopError, 'previous packages were restored'):
            coop.install_release()
        for kind in ('client', 'server'):
            self.assertEqual((coop.package_dir(kind) / 'sentinel').read_bytes(), b'old-' + kind.encode())

    def test_firewall_rules_stay_on_tailscale_and_the_home_network(self):
        script = coop._firewall_script(r'C:\Games\bbport\bin\bb-probe.exe')
        self.assertIn("@('100.64.0.0/10','LocalSubnet')", script)
        self.assertNotIn('Any', script)
        self.assertEqual(script.count('New-NetFirewallRule'), len(coop.FIREWALL_PORTS) + 1)

    def test_firewall_script_quotes_an_apostrophe_in_the_path(self):
        script = coop._firewall_script(r"C:\Users\O'Neil\bbport\bin\bb-probe.exe")
        self.assertIn(r"-Program 'C:\Users\O''Neil\bbport\bin\bb-probe.exe'", script)

    def test_tailscale_addresses(self):
        self.assertTrue(coop.is_tailscale('100.65.141.9'))
        self.assertFalse(coop.is_tailscale('100.128.0.1'))
        self.assertFalse(coop.is_tailscale('192.168.1.5'))

    def test_tailscale_is_found_on_path_outside_program_files(self):
        # Ask which() for the full 'tailscale.exe', not bare 'tailscale': the bare
        # name is only ever resolved by appending a PATHEXT entry, so what comes back
        # is 'tailscale' + whatever extension matched; the full name makes the result
        # unambiguously the file handed to subprocess.run. Also check that exact file
        # is the one run.
        exe = r'D:\Apps\Tailscale\tailscale.exe'
        ran = mock.Mock(stdout='100.65.141.9\n')
        with mock.patch.object(coop.shutil, 'which', return_value=exe) as which, \
                mock.patch.object(coop.subprocess, 'run', return_value=ran) as run:
            self.assertEqual(coop.tailscale_ip(), '100.65.141.9')
        which.assert_called_once_with('tailscale.exe')
        self.assertEqual(run.call_args[0][0][0], str(Path(exe)))

    def test_tailscale_found_in_program_files_when_not_on_path(self):
        # Not on PATH, so which() misses; it must fall back to the install folder,
        # ProgramW6432 before ProgramFiles, and only when the file is there. Both
        # env vars point at our own temp dirs so the real C:\Program Files on the
        # test machine is never consulted. A distinct exe in each proves the order.
        with tempfile.TemporaryDirectory() as w6432, tempfile.TemporaryDirectory() as pf:
            exe_w6432 = Path(w6432) / 'Tailscale' / 'tailscale.exe'
            exe_pf = Path(pf) / 'Tailscale' / 'tailscale.exe'
            exe_w6432.parent.mkdir()
            exe_pf.parent.mkdir()
            exe_w6432.write_bytes(b'')
            exe_pf.write_bytes(b'')
            env = {'ProgramW6432': w6432, 'ProgramFiles': pf}
            with mock.patch.object(coop.shutil, 'which', return_value=None), \
                    mock.patch.dict(coop.os.environ, env, clear=False):
                # ProgramW6432 wins over ProgramFiles when both hold the exe.
                self.assertEqual(coop.tailscale_exe(), exe_w6432)
            # ProgramW6432 empty, ProgramFiles has it: fall through to ProgramFiles.
            exe_w6432.unlink()
            with mock.patch.object(coop.shutil, 'which', return_value=None), \
                    mock.patch.dict(coop.os.environ, env, clear=False):
                self.assertEqual(coop.tailscale_exe(), exe_pf)
            # Neither folder has it: no exe is reported.
            exe_pf.unlink()
            with mock.patch.object(coop.shutil, 'which', return_value=None), \
                    mock.patch.dict(coop.os.environ, env, clear=False):
                self.assertIsNone(coop.tailscale_exe())

    def test_tailscale_address_from_the_route_when_the_cli_is_missing(self):
        probe = mock.MagicMock()
        probe.__enter__.return_value.getsockname.return_value = ('100.65.141.9', 50000)
        with mock.patch.object(coop, 'tailscale_exe', return_value=None), \
                mock.patch.object(coop.socket, 'socket', return_value=probe):
            self.assertEqual(coop.tailscale_ip(), '100.65.141.9')
        probe.__enter__.return_value.getsockname.return_value = ('192.168.1.5', 50000)
        with mock.patch.object(coop, 'tailscale_exe', return_value=None), \
                mock.patch.object(coop.socket, 'socket', return_value=probe):
            self.assertIsNone(coop.tailscale_ip())

    def test_account_names_are_checked_before_asking_the_server(self):
        with self.assertRaises(coop.CoopError):
            coop.create_account('100.65.141.9', '', 'x', 'secret')
        with self.assertRaises(coop.CoopError):
            coop.create_account('100.65.141.9', '', 'hunter', 'abc')

    def account_server(self, *replies):
        """create_account against canned account tool outputs, in order."""
        tool = mock.patch.object(coop, '_account_tool', side_effect=list(replies))
        sleep = mock.patch.object(coop.time, 'sleep')
        self.addCleanup(tool.stop)
        self.addCleanup(sleep.stop)
        sleep.start()
        return tool.start()

    def test_account_created_after_the_server_finished_starting(self):
        refused = '[connect] 100.65.141.9:31313 ...\n[connect] FAILED: connection refused\n'
        tool = self.account_server(refused, '[connect] OK\n[login] FAILED: LoginInvalidPassword\n',
                                   '[connect] OK\n[create] Account created successfully.\n',
                                   '[connect] OK\n[login] OK userId=2\n')
        self.assertEqual(coop.create_account('100.65.141.9', 'key', 'hunter', 'secret'), 'created')
        self.assertEqual(tool.call_count, 4)

    def test_account_failures_say_why(self):
        failed_login = '[connect] OK\n[login] FAILED: LoginInvalidPassword\n'
        for reply, reason in (('[create] FAILED: Unauthorized', 'invite code does not match'),
                              ('[create] FAILED: CreationExistingUsername', 'already taken'),
                              ('[create] FAILED: InvalidInput', 'does not accept the name')):
            self.account_server(failed_login, f'[connect] OK\n{reply}\n')
            with self.assertRaisesRegex(coop.CoopError, reason):
                coop.create_account('100.65.141.9', 'key', 'hunter', 'secret')
        self.account_server('[connect] OK\n[login] FAILED: LoginAlreadyLoggedIn\n')
        with self.assertRaisesRegex(coop.CoopError, 'signed in on the host'):
            coop.create_account('100.65.141.9', 'key', 'hunter', 'secret')

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
