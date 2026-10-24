"""bbport.ini keeps each key once across saves; a file with repeated keys collapses to the last value."""
from collections import Counter
from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'launcher'))
import bbport_launcher_win as core


class IniDuplicateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / 'bbport.ini'
        self.env = patch.dict(os.environ, {'BB_CONFIG': str(self.path)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temporary.cleanup()

    def save(self):
        """As the launcher does: every launcher key from the file as read, then read back."""
        values, lines = core.load_ini()
        core.save_ini({key: values[key] for key in core.INI_DEFAULTS}, lines)
        return core.load_ini()[0]

    def counts(self):
        lines = self.path.read_text(encoding='utf-8').splitlines()
        return Counter(line.split('=', 1)[0] for line in lines if '=' in line and not line.startswith('#'))

    def test_repeated_keys_collapse_to_the_last_value(self):
        # What the in-game menu left before its fix: one more frame_gen block per save.
        self.path.write_text('# bbport settings (in-game menu: Insert / L3+R3)\n'
                             'frame_gen=off\nframe_gen_multiplier=3\nframe_gen_fit_display=0\n'
                             'other_tool=1\n'
                             'frame_gen=dlss\nframe_gen_multiplier=2\nframe_gen_fit_display=1\n'
                             'other_tool=2\n', encoding='utf-8')
        for _ in range(2):
            values = self.save()
            self.assertEqual(max(self.counts().values()), 1, self.counts())
        self.assertEqual((values['frame_gen'], values['frame_gen_multiplier'],
                          values['frame_gen_fit_display'], values['other_tool']), ('dlss', '2', '1', '2'))

    def test_saving_twice_adds_nothing(self):
        self.save()
        first = self.path.read_text(encoding='utf-8')
        self.save()
        self.assertEqual(self.path.read_text(encoding='utf-8'), first)
        self.assertEqual(set(self.counts().values()), {1})
        self.assertEqual(set(self.counts()), set(core.INI_DEFAULTS))


if __name__ == '__main__':
    unittest.main()
