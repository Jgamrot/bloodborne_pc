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
launcher = load('bb_launcher', 'launcher/bbport_net.py')
import bbport_coop as coop


class HuntersDreamTests(unittest.TestCase):
    """The Hunter's Dream pool: the engine's own backend (BB_NET_BACKEND=thd), from Supermedo's
    port; and seamless co-op, which must never use it."""

    def setUp(self):
        patcher = mock.patch.object(launcher, 'HUNTERS_DREAM_POOL', True)
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
        self.assertEqual(env['BB_CLIENT_VERSION'], f'bbport-jgamrot {launcher.VERSION}')
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

    def test_https_trusts_the_shipped_roots_and_explains_certificate_errors(self):
        # Issue #13: CERTIFICATE_VERIFY_FAILED on a PC whose Windows store lacks the roots.
        import certifi
        with open(certifi.where(), encoding='utf-8') as bundle:
            shipped = bundle.read().count('BEGIN CERTIFICATE')
        context = launcher.https_context()
        self.assertGreaterEqual(context.cert_store_stats()['x509_ca'], shipped)
        text = launcher.connection_error_text(OSError('[SSL: CERTIFICATE_VERIFY_FAILED] certificate has expired'))
        self.assertIn('date and time', text)
        self.assertEqual(launcher.connection_error_text(OSError('timed out')), 'timed out')

    def test_certifi_bundle_binary_text_boundary(self):
        import certifi
        # Verify bundle contains certificates and can be decoded as UTF-8 / read as bytes
        raw_bytes = Path(certifi.where()).read_bytes()
        self.assertIn(b'BEGIN CERTIFICATE', raw_bytes)
        text = raw_bytes.decode('utf-8')
        self.assertIn('BEGIN CERTIFICATE', text)
        # Ensure https_context loads without throwing encoding/SSL errors
        context = launcher.https_context()
        self.assertGreater(context.cert_store_stats()['x509_ca'], 0)

    def test_pool_is_shown_unless_switched_off(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('BB_HUNTERS_DREAM', None)
            shown = load('bb_launcher_shown', 'launcher/bbport_net.py')
        with mock.patch.dict(os.environ, {'BB_HUNTERS_DREAM': '0'}):
            hidden = load('bb_launcher_hidden', 'launcher/bbport_net.py')
        self.assertTrue(shown.HUNTERS_DREAM_POOL)
        self.assertFalse(hidden.HUNTERS_DREAM_POOL)

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
