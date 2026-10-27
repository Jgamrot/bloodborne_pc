from pathlib import Path
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'launcher'))
import bbport_launcher_win as core


class ExitCodeTests(unittest.TestCase):
    def test_windows_status_codes_keep_their_bits(self):
        self.assertEqual(core.exit_status(0xC000007B), -1073741701)
        self.assertEqual(core.exit_status(-1073741701), -1073741701)
        self.assertEqual(core.exit_status(3), 3)
        self.assertEqual(core.exit_status(0), 0)

    def test_status_codes_are_shown_in_hex_with_a_hint(self):
        self.assertEqual(core.exit_code_text(3), '3')
        self.assertTrue(core.exit_code_text(0xC000007B).startswith('0xC000007B, a DLL in bin is damaged'))
        self.assertTrue(core.exit_code_text(-1073741515).startswith('0xC0000135, a DLL is missing'))
        self.assertEqual(core.exit_code_text(0xC0000001), '0xC0000001')

    def test_sys_exit_takes_the_converted_code(self):
        # The raw status overflowed sys.exit's C int; the converted one ends the process with it.
        code = subprocess.run([sys.executable, '-c', f'import sys; sys.exit({core.exit_status(0xC000007B)})']).returncode
        self.assertEqual(code & 0xFFFFFFFF, 0xC000007B)


if __name__ == '__main__':
    unittest.main()
