"""The launcher's top-level pages must cover every existing settings section.

These are static mapping tests: they do not open a Qt window and run on any machine with the
launcher backend importable.
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'launcher'))
try:
    import bbport_launcher_backend as backend
except Exception as error:  # PySide6 or a Windows-only import is unavailable
    backend = None
    IMPORT_ERROR = error


@unittest.skipIf(backend is None, f'launcher backend unavailable: {IMPORT_ERROR if backend is None else ""}')
class LauncherPageTests(unittest.TestCase):
    def test_every_page_group_exists_in_the_settings_source(self):
        for page, groups in backend.LAUNCHER_PAGES.items():
            self.assertTrue(groups, page)
            for category, section in groups:
                self.assertIn(category, backend.SETTINGS_SECTIONS, page)
                self.assertIn(section, [name for name, _ in backend.SETTINGS_SECTIONS[category]], page)

    def test_every_settings_section_has_exactly_one_home(self):
        mapped = [(category, section) for groups in backend.LAUNCHER_PAGES.values()
                  for category, section in groups]
        self.assertEqual(len(mapped), len(set(mapped)), 'a section is shown on two pages')
        expected = {(category, section) for category, sections in backend.SETTINGS_SECTIONS.items()
                    for section, _ in sections}
        # Logs is its own top-level Diagnostics page, not a settings section.
        expected.discard(('System', 'Logs'))
        self.assertEqual(set(mapped), expected)

    def test_every_field_is_reachable(self):
        fields = {field['key'] for page in backend.FIELDS.values() for field in page}
        reachable = set()
        for category, section in [(c, s) for groups in backend.LAUNCHER_PAGES.values() for c, s in groups]:
            for name, keys in backend.SETTINGS_SECTIONS[category]:
                if name == section:
                    reachable.update(keys)
        self.assertEqual(fields - reachable, set())

    def test_hints_belong_to_visible_sections(self):
        visible = {(category, section) for groups in backend.LAUNCHER_PAGES.values()
                   for category, section in groups}
        self.assertTrue(set(backend.SECTION_HINTS).issubset(visible))

    def test_search_navigation_finds_the_page(self):
        self.assertEqual(backend.launcher_page_for('Visuals', 'Display & frame rate'), 'Display')
        self.assertEqual(backend.launcher_page_for('Visuals', 'Upscaling'), 'Graphics')
        self.assertEqual(backend.launcher_page_for('Online', "The Hunter's Dream"), 'Online')
        self.assertEqual(backend.launcher_page_for('System', 'Logs'), 'Logs')

    def test_page_sections_carry_titles_and_hints(self):
        groups = backend.launcher_page_sections('Graphics')
        self.assertEqual(groups[0]['category'], 'Visuals')
        self.assertEqual(groups[0]['section'], 'Upscaling')
        self.assertTrue(groups[0]['hint'])


if __name__ == '__main__':
    unittest.main()
