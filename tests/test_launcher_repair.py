import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'launcher'))
import bbport_launcher_win as core
import run

ROOT = Path(__file__).resolve().parents[1]


def release(tag, name, assets=('bbport-windows.zip',), draft=False):
    return {'tag_name': tag, 'name': name, 'draft': draft, 'html_url': f'https://example.invalid/{tag}',
            'assets': [{'name': asset, 'browser_download_url': f'https://example.invalid/{tag}/{asset}'}
                       for asset in assets]}


RELEASES = [
    release('qml-launcher-preview-23', 'Bloodborne Windows Launcher 2.1 (upstream fixes, language)'),
    release('qml-launcher-preview-22', 'Bloodborne Windows Launcher 2.0 (community PRs, 120/144 FPS)'),
    release('qml-launcher-preview-21', 'Bloodborne Windows Launcher 1.9.7 (map, frame generation)'),
    release('qml-launcher-preview-13', 'Bloodborne Windows Launcher 1.9 experimental (co-op test)'),
    release('windows-v1.6.4', 'Bloodborne for Windows v1.6.4', assets=('bb-probe.exe', 'Bloodborne-Windows-v1.6.4-Jgamrot.zip')),
]


def write_port(folder, scripts=run.START_SCRIPTS, text='new'):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'run.py').write_text(text, encoding='utf-8')
    (folder / 'scripts').mkdir(exist_ok=True)
    for name in scripts:
        (folder / 'scripts' / name).write_text(text, encoding='utf-8')


class Response(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.headers = {'Content-Length': str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class MissingFilesTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.port = Path(self.directory.name)

    def test_repository_is_complete(self):
        self.assertEqual(core.missing_port_files(ROOT), [])

    def test_uses_run_py_list(self):
        write_port(self.port)
        self.assertEqual(core.missing_port_files(self.port), [])
        (self.port / 'scripts' / 'language_files.py').unlink()
        (self.port / 'scripts' / 'quiet_output.py').unlink()
        self.assertEqual(core.missing_port_files(self.port),
                         ['scripts\\language_files.py', 'scripts\\quiet_output.py'])

    def test_missing_run_py_comes_first(self):
        write_port(self.port, scripts=run.START_SCRIPTS[1:])
        (self.port / 'run.py').unlink()
        self.assertEqual(core.missing_port_files(self.port), ['run.py', f'scripts\\{run.START_SCRIPTS[0]}'])


class OwnReleaseTests(unittest.TestCase):
    def test_tag_of_this_launcher(self):
        self.assertEqual(core.own_release(RELEASES, '2.1', 'qml-launcher-preview-23'),
                         ('https://example.invalid/qml-launcher-preview-23/bbport-windows.zip',
                          'https://example.invalid/qml-launcher-preview-23'))

    def test_version_in_the_name_when_the_tag_is_unknown(self):
        found = core.own_release(RELEASES, '1.9', 'qml-launcher-preview-99')
        self.assertEqual(found[1], 'https://example.invalid/qml-launcher-preview-13')
        self.assertEqual(core.own_release(RELEASES, '1.9.7', 'none')[1], 'https://example.invalid/qml-launcher-preview-21')

    def test_defaults_to_the_launcher_constants(self):
        with patch.object(core, 'VERSION', '2.0'), patch.object(core, 'CURRENT_RELEASE_TAG', 'qml-launcher-preview-22'):
            self.assertEqual(core.own_release(RELEASES)[1], 'https://example.invalid/qml-launcher-preview-22')

    def test_drafts_and_releases_without_a_zip_are_skipped(self):
        releases = [release('qml-launcher-preview-24', 'Bloodborne Windows Launcher 2.2', draft=True),
                    release('qml-launcher-preview-25', 'Bloodborne Windows Launcher 2.2', assets=('notes.txt',))]
        self.assertIsNone(core.own_release(releases, '2.2', 'qml-launcher-preview-24'))
        self.assertIsNone(core.own_release(RELEASES, '3.0', 'qml-launcher-preview-30'))
        self.assertIsNone(core.own_release([], '2.1', 'qml-launcher-preview-23'))

    def test_package_zip_preferred(self):
        releases = [release('t', 'x', assets=('Xbox-Prompts.zip', 'bbport-windows.zip'))]
        self.assertEqual(core.own_release(releases, '2.1', 't')[0], 'https://example.invalid/t/bbport-windows.zip')


class RepairTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.port = self.root / 'port'
        for name, value in {'FROZEN': True, 'COOP_TEST': False, 'UPDATE_DIR': self.root / 'update',
                            'VERSION': '2.1', 'CURRENT_RELEASE_TAG': 'qml-launcher-preview-23'}.items():
            patcher = patch.object(core, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        # A 1.9.7 folder under the 2.1 launcher (#171): old scripts, two of them missing.
        write_port(self.port, scripts=[n for n in run.START_SCRIPTS
                                       if n not in ('language_files.py', 'quiet_output.py')], text='old')
        (self.port / 'Bloodborne.exe').write_text('running launcher', encoding='utf-8')
        (self.port / '_internal').mkdir()
        (self.port / '_internal' / 'python312.dll').write_text('running launcher', encoding='utf-8')
        (self.port / 'user' / 'savedata').mkdir(parents=True)
        (self.port / 'user' / 'savedata' / 'SAVEDATA00').write_text('save', encoding='utf-8')
        (self.port / 'bbport.ini').write_text('preset=4', encoding='utf-8')
        (self.port / 'mods.json').write_text('{"mine": true}', encoding='utf-8')

    def release_folder(self):
        source = self.root / 'release' / 'bbport-windows'
        write_port(source)
        (source / 'bin').mkdir()
        (source / 'bin' / 'bb-probe.exe').write_text('new', encoding='utf-8')
        (source / 'Bloodborne.exe').write_text('new launcher', encoding='utf-8')
        (source / '_internal').mkdir()
        (source / '_internal' / 'python312.dll').write_text('new launcher', encoding='utf-8')
        (source / 'user').mkdir()
        (source / 'user' / 'SAVEDATA00').write_text('packaged', encoding='utf-8')
        (source / 'bbport.ini').write_text('preset=2', encoding='utf-8')
        return source

    def assert_user_files_kept(self):
        self.assertEqual((self.port / 'user' / 'savedata' / 'SAVEDATA00').read_text(encoding='utf-8'), 'save')
        self.assertFalse((self.port / 'user' / 'SAVEDATA00').exists())
        self.assertEqual((self.port / 'bbport.ini').read_text(encoding='utf-8'), 'preset=4')
        self.assertEqual((self.port / 'mods.json').read_text(encoding='utf-8'), '{"mine": true}')
        self.assertEqual((self.port / 'Bloodborne.exe').read_text(encoding='utf-8'), 'running launcher')
        self.assertEqual((self.port / '_internal' / 'python312.dll').read_text(encoding='utf-8'), 'running launcher')

    def test_copy_fills_missing_and_replaces_old_files_only(self):
        self.assertEqual(core.missing_port_files(self.port), ['scripts\\language_files.py', 'scripts\\quiet_output.py'])
        self.assertEqual(core.repair_copy(self.release_folder(), self.port), [])
        self.assertEqual(core.missing_port_files(self.port), [])
        self.assertEqual((self.port / 'scripts' / 'game_check.py').read_text(encoding='utf-8'), 'new')
        self.assertEqual((self.port / 'bin' / 'bb-probe.exe').read_text(encoding='utf-8'), 'new')
        self.assert_user_files_kept()

    def serve(self, releases=None, archive=None):
        def urlopen(request, timeout=None):
            if request.full_url == core.RELEASES_LIST_API:
                return Response(json.dumps(RELEASES if releases is None else releases).encode())
            if request.full_url == 'https://example.invalid/qml-launcher-preview-23/bbport-windows.zip':
                return Response(archive)
            raise OSError(f'unexpected {request.full_url}')
        return patch.object(core.urllib.request, 'urlopen', side_effect=urlopen)

    def zipped_release(self):
        source = self.release_folder()
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as package:
            for path in sorted(source.rglob('*')):
                if path.is_file():
                    package.write(path, str(path.relative_to(source.parent)).replace('/', '\\'))
        return buffer.getvalue()

    def test_repair_downloads_this_version(self):
        shown = []
        with self.serve(archive=self.zipped_release()) as urlopen:
            self.assertEqual(core.repair_port(shown.append, self.port), ([], []))
        self.assertEqual(urlopen.call_args_list[1].args[0].get_header('User-agent'), 'bbport-launcher')
        self.assertEqual(shown[-1], 100)
        self.assertEqual((self.port / 'scripts' / 'quiet_output.py').read_text(encoding='utf-8'), 'new')
        self.assert_user_files_kept()
        self.assertFalse(core.UPDATE_DIR.exists())

    def test_falls_back_when_nothing_is_found(self):
        with patch.object(core, 'FROZEN', False), self.assertRaises(OSError):
            core.repair_port(target=self.port)
        with patch.object(core.urllib.request, 'urlopen', side_effect=OSError('offline')), self.assertRaises(OSError):
            core.repair_port(target=self.port)
        with self.serve(releases={'message': 'API rate limit exceeded'}), self.assertRaisesRegex(OSError, 'not found'):
            core.repair_port(target=self.port)
        with self.serve(archive=b'not a zip'), self.assertRaisesRegex(OSError, 'damaged'):
            core.repair_port(target=self.port)
        self.assertFalse(core.UPDATE_DIR.exists())
        self.assertEqual(core.missing_port_files(self.port), ['scripts\\language_files.py', 'scripts\\quiet_output.py'])
        self.assert_user_files_kept()


if __name__ == '__main__':
    unittest.main()
