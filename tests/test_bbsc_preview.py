"""Check that an experimental BBSC launch cannot leave the regular server redirected."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))
import bbsc_preview


class BBSCPreviewTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        root = Path(self.temp.name)
        self.package, self.port, self.game = root / "BBSC", root / "port", root / "CUSA03173"
        for file in (self.package / "tools" / "play-bbport.ps1",
                     self.package / "bbsc" / "bbsc-launch.exe",
                     self.package / "bbsc" / "bbsc.dll",
                     self.port / "Bloodborne.exe", self.port / "bin" / "bb-probe.exe",
                     self.game / "eboot.bin"):
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(b"test")
        (self.package / "bbsc" / "mod.json").write_text(
            json.dumps({"id": "bbsc", "games": ["CUSA03173"]}), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_restores_existing_files_and_backs_up_saves(self):
        override = self.port / "user" / "host_overrides.custom.json"
        override.parent.mkdir(parents=True)
        override.write_bytes(b"original server")
        saves = self.port / "user" / "savedata" / "account"
        saves.mkdir(parents=True)
        (saves / "save.bin").write_bytes(b"character")
        paths = self.package / "tools" / "bbport-paths.json"
        paths.write_bytes(b"original paths")

        def runner(_command, **_kwargs):
            override.write_bytes(b"BBSC server")
            paths.write_bytes(b"BBSC paths")
            return type("Result", (), {"returncode": 0})()

        code, backup = bbsc_preview.run_preview(self.package, self.port, self.game, runner=runner)
        self.assertEqual(code, 0)
        self.assertEqual(override.read_bytes(), b"original server")
        self.assertEqual(paths.read_bytes(), b"original paths")
        self.assertEqual((backup / "account" / "save.bin").read_bytes(), b"character")

    def test_restores_when_launch_fails(self):
        override = self.port / "user" / "host_overrides.custom.json"
        paths = self.package / "tools" / "bbport-paths.json"

        def runner(_command, **_kwargs):
            override.write_bytes(b"BBSC server")
            raise OSError("failed to launch")

        with self.assertRaises(OSError):
            bbsc_preview.run_preview(self.package, self.port, self.game, runner=runner)
        self.assertFalse(override.exists())
        self.assertFalse(paths.exists())


if __name__ == "__main__":
    unittest.main()
