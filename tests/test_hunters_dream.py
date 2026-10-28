from paths import ROOT
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


run = load('bb_run', 'run.py')
sys.path.insert(0, str(ROOT / 'launcher'))
launcher = load('bb_launcher', 'launcher/bbport_launcher_win.py')
import bbport_coop as coop


class HuntersDreamTests(unittest.TestCase):
    """The Hunter's Dream pool: the engine's own backend (BB_NET_BACKEND=thd), from Supermedo's
    port; and seamless co-op, which must never use it."""

    def setUp(self):
        patcher = mock.patch.object(launcher, 'HUNTERS_DREAM_POOL', True)
        patcher.start()
        self.addCleanup(patcher.stop)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.refusal = Path(temp.name) / 'thd-refusal.json'
        for name, value in {'CONFIG_DIR': Path(temp.name), 'THD_REFUSAL': self.refusal}.items():
            patcher = mock.patch.object(launcher, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.settings = {**launcher.APP_DEFAULTS, 'game_dir': 'x', 'online': True,
                         'online_pool': 'huntersdream', 'thd_online_id': 'Hunter1', 'thd_token': 'tok',
                         'online_npid': 'shadnet_name', 'online_password': 'secret'}

    def test_run_sets_the_backend_and_http_overrides(self):
        with tempfile.TemporaryDirectory() as temp:
            env = {'BB_THD_TOKEN': 't', 'BB_THD_ONLINE_ID': 'Hunter1', 'BB_SHADNET_SERVER': 'x:1'}
            run.hunters_dream(env, Path(temp))
            overrides = json.loads((Path(temp) / 'host_overrides.json').read_text(encoding='utf-8'))
        self.assertEqual(overrides['*.scej-network.jp'], 'https://thehuntersdream.com')
        self.assertEqual(overrides['bb-playlog-prod.s3.amazonaws.com'], 'https://thehuntersdream.com:18671')
        self.assertEqual(env['BB_THD_SERVER'], 'https://thehuntersdream.com:18671')
        self.assertNotIn('BB_SHADNET_SERVER', env)

    def test_run_refuses_the_pool_without_a_sign_in(self):
        with tempfile.TemporaryDirectory() as temp, self.assertRaises(SystemExit):
            run.hunters_dream({}, Path(temp))

    def test_shadnet_pool_sends_game_functions_over_http_only(self):
        with tempfile.TemporaryDirectory() as temp:
            env = {'BB_SHADNET_WEBAPI': 'http://srv.shadps4.net:31315'}
            run.online_overrides(env, Path(temp))
            overrides = json.loads((Path(temp) / 'host_overrides.json').read_text(encoding='utf-8'))
        self.assertFalse(any('31315' in v for v in overrides.values()))
        self.assertEqual(overrides['https://bb-playlog-prod.s3.amazonaws.com:443'],
                         'https://thehuntersdream.com:18671')

    def test_launcher_environment(self):
        env = launcher.game_environment(self.settings)
        self.assertEqual((env['BB_NET_BACKEND'], env['BB_THD_ONLINE_ID'], env['BB_THD_TOKEN']),
                         ('thd', 'Hunter1', 'tok'))
        self.assertNotIn('BB_SHADNET_NPID', env)
        # The shadNet-server pool is gone: an old setting with it starts offline now.
        env = launcher.game_environment({**self.settings, 'online_pool': 'shadnet'})
        self.assertNotIn('BB_NET_BACKEND', env)
        self.assertNotIn('BB_SHADNET_NPID', env)
        self.assertNotEqual(env.get('BB_ONLINE'), '1')
        # The play mode decides: offline and co-op modes never start the normal online path.
        for mode in ('offline', 'coop'):
            env = launcher.game_environment({**self.settings, 'play_mode': mode})
            self.assertNotIn('BB_NET_BACKEND', env)
            self.assertNotEqual(env.get('BB_ONLINE'), '1')
        self.assertEqual(launcher.game_environment({**self.settings, 'play_mode': 'huntersdream'})['BB_NET_BACKEND'], 'thd')
        with mock.patch.object(launcher, 'HUNTERS_DREAM_POOL', False):
            self.assertNotIn('BB_NET_BACKEND', launcher.game_environment(self.settings))
        self.assertNotIn('BB_NET_BACKEND', launcher.game_environment({**self.settings, 'online': False}))

    def test_client_version_names_this_fork(self):
        env = launcher.game_environment(self.settings)
        self.assertEqual(env['BB_CLIENT_VERSION'], f'yharnam-pc {launcher.VERSION}')
        self.assertNotIn('shadPS4', env['BB_CLIENT_VERSION'])

    def test_sign_in_opens_the_link_page_with_its_code(self):
        # As bbhost does: /link?code=..., so the website asks to approve this code after the
        # Discord sign-in (its "code from the game" box is for the other direction).
        replies = [{'ResKind': 0, 'DeviceCode': 'dev', 'UserCode': 'ABCD-EFGH', 'Interval': 1,
                    'ExpiresIn': 60, 'VerificationUri': 'https://thehuntersdream.com/link'},
                   {'ResKind': 0, 'Status': 'approved', 'OnlineId': 'Hunter1', 'Token': 'tok'}]
        pages = []
        with mock.patch.object(launcher, 'thd_call', side_effect=lambda url, body: replies.pop(0)), \
                mock.patch.object(launcher.time, 'sleep'):
            result = launcher.thd_sign_in('thehuntersdream.com', lambda page, code: pages.append((page, code)))
        self.assertEqual(result, ('Hunter1', 'tok'))
        self.assertEqual(pages, [('https://thehuntersdream.com/link?code=ABCD-EFGH', 'ABCD-EFGH')])

    def test_connection_test_asks_the_server_about_the_sign_in(self):
        # Issue #69: a saved token showed "Signed in" while the game got HTTP 401.
        import io
        import urllib.error
        refused = urllib.error.HTTPError('https://thehuntersdream.com:18671/np/events/poll', 401,
                                         'Unauthorized', {}, io.BytesIO(json.dumps(
                                             {'Message': 'This client is not supported'}).encode()))
        with mock.patch.object(launcher.urllib.request, 'urlopen', side_effect=refused) as urlopen:
            line = launcher.thd_account_check('https://thehuntersdream.com', 'Hunter1', 'tok')
        request = urlopen.call_args[0][0]
        self.assertEqual(request.get_header('X-bb-token'), 'tok')
        self.assertEqual(request.get_header('User-agent'), f'yharnam-pc/{launcher.VERSION}')
        self.assertIn('refused by the server (This client is not supported)', line)
        self.assertIn('signing in again does not help', line)
        self.assertTrue(launcher.thd_refused())  # remembered: no more checks from this version
        self.refusal.unlink()
        # Any other refusal is the account's: signing in again is the way out.
        expired = urllib.error.HTTPError('https://thehuntersdream.com:18671/np/events/poll', 401,
                                         'Unauthorized', {}, io.BytesIO(json.dumps(
                                             {'Message': 'Token was issued to another client'}).encode()))
        with mock.patch.object(launcher.urllib.request, 'urlopen', side_effect=expired):
            line = launcher.thd_account_check('https://thehuntersdream.com', 'Hunter1', 'tok')
        self.assertIn('refused by the server', line)
        self.assertNotIn('does not help', line)
        self.assertFalse(launcher.thd_refused())
        # A broken reply is reported, not left to end the check's thread.
        import http.client
        with mock.patch.object(launcher.urllib.request, 'urlopen',
                               side_effect=http.client.IncompleteRead(b'')):
            self.assertIn('not checked', launcher.thd_account_check('https://thehuntersdream.com', 'Hunter1', 'tok'))
        # Another refusal that says "not supported" is not about this build.
        ruleset = urllib.error.HTTPError('https://thehuntersdream.com:18671/np/events/poll', 401,
                                         'Unauthorized', {}, io.BytesIO(json.dumps(
                                             {'Message': 'Ruleset hard is not supported'}).encode()))
        with mock.patch.object(launcher.urllib.request, 'urlopen', side_effect=ruleset):
            self.assertNotIn('does not help', launcher.thd_account_check('https://thehuntersdream.com',
                                                                         'Hunter1', 'tok'))

        def answer(body):
            response = mock.MagicMock()
            response.__enter__.return_value.read.return_value = body
            return response
        # Accepted only with the poll's own JSON reply; the game's 16-character online ID is sent.
        with mock.patch.object(launcher.urllib.request, 'urlopen',
                               return_value=answer(b'{"HasEvent": 0, "NextCursor": 0}')) as urlopen:
            self.assertIn('accepted', launcher.thd_account_check('https://thehuntersdream.com',
                                                                 'A' * 20, 'tok'))
        self.assertEqual(json.loads(urlopen.call_args[0][0].data)['OnlineId'], 'A' * 16)
        with mock.patch.object(launcher.urllib.request, 'urlopen',
                               return_value=answer(b'<html>Sign in to the Wi-Fi</html>')):
            self.assertIn('not from The Hunter', launcher.thd_account_check('https://thehuntersdream.com',
                                                                            'Hunter1', 'tok'))
        self.assertIn('Not signed in', launcher.thd_account_check('https://thehuntersdream.com', '', ''))

    def test_refused_build_stays_off_the_hunters_dream(self):
        # The game's line when the server refuses this build ("client is not supported").
        source = (ROOT / 'gpu/bbnet/thd/thd_session.cpp').read_text(encoding='utf-8')
        self.assertIn('Log("' + launcher.THD_REFUSED_LINE.removeprefix('THD: '), source)
        line = (f"THD: the server refused this client (yharnam-pc/{launcher.VERSION}) for Hunter1 "
                "(This client is not supported on The Hunter's Dream): all traffic to The Hunter's Dream "
                "is stopped for this session; offline play and seamless co-op still work\n")
        self.assertFalse(launcher.note_game_output('THD: np: event #3 guest_invite\n'))
        self.assertFalse(launcher.thd_refused())
        self.assertTrue(launcher.note_game_output(line))
        self.assertTrue(launcher.thd_refused())
        self.assertEqual(json.loads(self.refusal.read_text(encoding='utf-8'))['client'], launcher.CLIENT_VERSION)
        # PLAY in The Hunter's Dream mode starts offline: no backend, no account, no online switch.
        for settings in (self.settings, {**self.settings, 'play_mode': 'huntersdream'}):
            env = launcher.game_environment(settings)
            for key in run.THD_ENV + ('BB_ONLINE', 'BB_SHADNET_SERVER', 'BB_COMMUNITY_SERVER'):
                self.assertNotIn(key, env)
        # No sign-in and no account check: nothing is sent to the server.
        with mock.patch.object(launcher, 'thd_call') as call, \
                mock.patch.object(launcher.urllib.request, 'urlopen') as urlopen:
            with self.assertRaises(ValueError) as refused:
                launcher.thd_sign_in('thehuntersdream.com', lambda page, code: None)
            self.assertIn("doesn't accept this build", str(refused.exception))
            note = launcher.thd_account_check('https://thehuntersdream.com', 'Hunter1', 'tok')
        call.assert_not_called()
        urlopen.assert_not_called()
        self.assertIn('offline play and seamless co-op still work', note)
        # Seamless co-op is untouched by it.
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(os.environ, {'LOCALAPPDATA': temp}):
            env = coop.co_op_environment(launcher.game_environment({**self.settings, 'play_mode': 'coop'}),
                                         '100.65.141.9', 'hunter', 'secret',
                                         Path(temp) / 'bbport-windows' / 'bin' / 'bb-probe.exe')
        self.assertEqual((env['BB_COOP'], env['BB_ONLINE'], env['BB_SHADNET_SERVER']),
                         ('1', '1', '100.65.141.9:31313'))
        # A new launcher version tries The Hunter's Dream again.
        with mock.patch.object(launcher, 'CLIENT_VERSION', 'yharnam-pc 9.9'):
            self.assertFalse(launcher.thd_refused())
            self.assertEqual(launcher.game_environment(self.settings)['BB_NET_BACKEND'], 'thd')
        self.assertTrue(launcher.thd_refused())

    def test_https_trusts_the_shipped_roots_and_explains_certificate_errors(self):
        # Issue #13: CERTIFICATE_VERIFY_FAILED on a PC whose Windows store lacks the roots.
        import certifi
        with open(certifi.where(), encoding='ascii') as bundle:
            shipped = bundle.read().count('BEGIN CERTIFICATE')
        context = launcher.https_context()
        self.assertGreaterEqual(context.cert_store_stats()['x509_ca'], shipped)
        text = launcher.connection_error_text(OSError('[SSL: CERTIFICATE_VERIFY_FAILED] certificate has expired'))
        self.assertIn('date and time', text)
        self.assertEqual(launcher.connection_error_text(OSError('timed out')), 'timed out')

    def test_pool_is_off_unless_switched_on(self):
        # The server refuses this port's client (#10).
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('BB_HUNTERS_DREAM', None)
            hidden = load('bb_launcher_hidden', 'launcher/bbport_launcher_win.py')
        with mock.patch.dict(os.environ, {'BB_HUNTERS_DREAM': '1'}):
            shown = load('bb_launcher_shown', 'launcher/bbport_launcher_win.py')
        self.assertFalse(hidden.HUNTERS_DREAM_POOL)
        self.assertTrue(shown.HUNTERS_DREAM_POOL)

    def test_a_saved_hunters_dream_mode_plays_offline_while_it_is_off(self):
        saved = {**self.settings, 'play_mode': 'huntersdream'}
        with mock.patch.object(launcher, 'HUNTERS_DREAM_POOL', False):
            self.assertEqual(launcher.play_mode(saved), 'offline')
            env = launcher.game_environment(saved)
            self.assertNotIn('BB_NET_BACKEND', env)
            self.assertNotEqual(env.get('BB_ONLINE'), '1')
            self.assertEqual(launcher.play_mode({**self.settings, 'play_mode': 'coop'}), 'coop')
        self.assertEqual(launcher.play_mode(saved), 'huntersdream')

    def test_co_op_never_uses_the_hunters_dream(self):
        base = launcher.game_environment(self.settings)
        with tempfile.TemporaryDirectory() as temp:
            with mock.patch.dict(os.environ, {'LOCALAPPDATA': temp}):
                env = coop.co_op_environment(base, '100.65.141.9', 'hunter', 'secret',
                                             Path(temp) / 'bbport-windows' / 'bin' / 'bb-probe.exe')
        for key in run.THD_ENV:
            self.assertNotIn(key, env)
        self.assertEqual(env['BB_SHADNET_SERVER'], '100.65.141.9:31313')
        self.assertEqual(base['BB_NET_BACKEND'], 'thd')  # the normal environment is untouched


if __name__ == '__main__':
    unittest.main()
