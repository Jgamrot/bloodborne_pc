"""Wine/Windows Qt Quick backend selection.

Wine's D3D11 RHI does not present QML page changes until a native resize; the launcher
selects OpenGL there. Native Windows keeps D3D11.
"""
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('windows_launcher', ROOT / 'launcher/bbport_launcher_win.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class RendererTests(unittest.TestCase):
    def test_wine_selects_opengl(self):
        environment = {}
        self.assertEqual(launcher.configure_renderer(environment, wine=True), 'opengl')
        self.assertEqual(environment['QSG_RHI_BACKEND'], 'opengl')

    def test_native_windows_keeps_the_default(self):
        environment = {}
        self.assertIsNone(launcher.configure_renderer(environment, wine=False))
        self.assertNotIn('QSG_RHI_BACKEND', environment)

    def test_an_explicit_backend_is_never_overridden(self):
        environment = {'QSG_RHI_BACKEND': 'd3d11'}
        launcher.configure_renderer(environment, wine=True)
        self.assertEqual(environment['QSG_RHI_BACKEND'], 'd3d11')
        environment = {'QT_QUICK_BACKEND': 'software'}
        launcher.configure_renderer(environment, wine=True)
        self.assertNotIn('QSG_RHI_BACKEND', environment)

    def test_detection_is_safe(self):
        if sys.platform != 'win32':
            self.assertFalse(launcher.running_under_wine())
        else:
            self.assertIsInstance(launcher.running_under_wine(), bool)


if __name__ == '__main__':
    unittest.main()
