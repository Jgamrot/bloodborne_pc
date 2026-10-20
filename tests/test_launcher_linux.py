"""Headless unit tests for the GTK launcher in launcher/bbport_launcher.py."""
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER_DIR = ROOT / "launcher"
if str(LAUNCHER_DIR) not in sys.path:
    sys.path.insert(0, str(LAUNCHER_DIR))


def _install_gtk_stubs():
    """Provide the small part of GTK/Adw the launcher touches, for machines without them."""

    class StringList:
        def __init__(self, labels):
            self.labels = list(labels)

        @classmethod
        def new(cls, labels):
            return cls(labels)

        def get_string(self, index):
            return self.labels[index]

    class ComboRow:
        def __init__(self, title=None, model=None, **kwargs):
            self.title = title
            self.model = model
            self.subtitle = ""
            self.selected = 0

        def set_subtitle(self, text):
            self.subtitle = text

        def get_subtitle(self):
            return self.subtitle

        def set_selected(self, index):
            self.selected = index

        def get_selected(self):
            return self.selected

        def get_model(self):
            return self.model

    class Widget:
        def __init__(self, *args, **kwargs):
            pass

    class Align:
        CENTER = "center"

    class Orientation:
        VERTICAL = "vertical"

    class WrapMode:
        WORD_CHAR = "word-char"

    def fallback(_name):
        return Widget

    gtk = types.ModuleType("gi.repository.Gtk")
    gtk.__getattr__ = fallback
    gtk.StringList = StringList
    gtk.Align = Align
    gtk.Orientation = Orientation
    gtk.WrapMode = WrapMode

    adw = types.ModuleType("gi.repository.Adw")
    adw.__getattr__ = fallback
    adw.ApplicationWindow = type("ApplicationWindow", (Widget,), {})
    adw.Application = type("Application", (Widget,), {})
    adw.ComboRow = ComboRow

    gio = types.ModuleType("gi.repository.Gio")
    gio.__getattr__ = fallback
    glib = types.ModuleType("gi.repository.GLib")
    glib.__getattr__ = fallback

    for name in [name for name in sys.modules if name == "gi" or name.startswith("gi.")]:
        sys.modules.pop(name, None)

    gi = types.ModuleType("gi")
    gi.require_version = lambda *args, **kwargs: None
    repository = types.ModuleType("gi.repository")
    repository.Adw = adw
    repository.Gio = gio
    repository.GLib = glib
    repository.Gtk = gtk
    gi.repository = repository

    sys.modules["gi"] = gi
    sys.modules["gi.repository"] = repository
    sys.modules["gi.repository.Adw"] = adw
    sys.modules["gi.repository.Gio"] = gio
    sys.modules["gi.repository.GLib"] = glib
    sys.modules["gi.repository.Gtk"] = gtk


def _import_launcher():
    try:
        import bbport_launcher
        return bbport_launcher
    except (ImportError, ValueError):
        _install_gtk_stubs()
        sys.modules.pop("bbport_launcher", None)
        import bbport_launcher
        return bbport_launcher


launcher = _import_launcher()

try:
    import gi as _gi
    from gi.repository import Gio as _real_gio
    REAL_GI = getattr(_gi, "__file__", None) is not None and \
        hasattr(_real_gio, "SubprocessLauncher")
except ImportError:
    REAL_GI = False


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config_dir = Path(self.temp.name) / "config" / "bbport-launcher"
        self.config_file = self.config_dir / "settings.json"
        for name, value in (("CONFIG_DIR", self.config_dir), ("CONFIG_FILE", self.config_file)):
            patcher = patch.object(launcher, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_missing_file_returns_defaults_without_creating_it(self):
        settings = launcher.load_settings()
        self.assertEqual(settings, launcher.DEFAULTS)
        self.assertIsNot(settings, launcher.DEFAULTS)
        self.assertFalse(self.config_file.exists())

    def test_defaults_are_not_mutated_by_callers(self):
        settings = launcher.load_settings()
        settings["fullscreen"] = True
        self.assertFalse(launcher.DEFAULTS["fullscreen"])

    def test_saved_values_override_defaults(self):
        self.config_file.parent.mkdir(parents=True)
        self.config_file.write_text(
            json.dumps({"fullscreen": True, "language": "8"}), encoding="utf-8")
        settings = launcher.load_settings()
        self.assertTrue(settings["fullscreen"])
        self.assertEqual(settings["language"], "8")
        self.assertEqual(settings["present_mode"], launcher.DEFAULTS["present_mode"])

    def test_malformed_json_falls_back_to_defaults(self):
        self.config_file.parent.mkdir(parents=True)
        for content in ('{"fullscreen": tru', "not json at all", '"just a string"', "[]",
                        "null", "42", "true", "[1, 2]"):
            with self.subTest(content=content):
                self.config_file.write_text(content, encoding="utf-8")
                self.assertEqual(launcher.load_settings(), launcher.DEFAULTS)

    def test_wrong_typed_values_fall_back_but_unknown_keys_survive(self):
        self.config_file.parent.mkdir(parents=True)
        self.config_file.write_text(json.dumps({
            "fullscreen": "yes", "fps_limit": "90", "player_name": 5,
            "present_mode": None, "from_future_version": {"kept": True},
        }), encoding="utf-8")
        settings = launcher.load_settings()
        self.assertFalse(settings["fullscreen"])
        self.assertEqual(settings["fps_limit"], launcher.DEFAULTS["fps_limit"])
        self.assertEqual(settings["player_name"], "")
        self.assertEqual(settings["present_mode"], launcher.DEFAULTS["present_mode"])
        self.assertEqual(settings["from_future_version"], {"kept": True})

    def test_fps_limit_is_coerced_clamped_and_never_bool(self):
        self.config_file.parent.mkdir(parents=True)
        for raw, expected in ((90, 90), (90.7, 90), (-5, 0), (9999, 480), (True, 0),
                              ("90", 0), (1e999, 0)):
            with self.subTest(raw=raw):
                self.config_file.write_text(json.dumps({"fps_limit": raw}), encoding="utf-8")
                self.assertEqual(launcher.load_settings()["fps_limit"], expected)

    def test_non_utf8_settings_file_does_not_crash(self):
        self.config_file.parent.mkdir(parents=True)
        self.config_file.write_bytes(b'{"fullscreen": true, "note": "\xff"}')
        settings = launcher.load_settings()
        self.assertTrue(settings["fullscreen"])
        self.assertEqual(settings["note"], "\ufffd")

    def test_save_creates_directory_and_writes_readable_json(self):
        self.assertFalse(self.config_dir.exists())
        launcher.save_settings(dict(launcher.DEFAULTS))
        self.assertTrue(self.config_file.is_file())
        self.assertEqual(json.loads(self.config_file.read_text(encoding="utf-8")),
                         launcher.DEFAULTS)

    def test_extra_keys_survive_save_and_load(self):
        settings = dict(launcher.DEFAULTS)
        settings["custom_key"] = {"nested": [1, 2, 3]}
        settings["note"] = "Привет"
        settings["language"] = "8"
        launcher.save_settings(settings)
        raw = self.config_file.read_text(encoding="utf-8")
        self.assertIn("Привет", raw)
        on_disk = json.loads(raw)
        self.assertEqual(on_disk["custom_key"], {"nested": [1, 2, 3]})
        loaded = launcher.load_settings()
        self.assertEqual(loaded["custom_key"], {"nested": [1, 2, 3]})
        self.assertEqual(loaded["note"], "Привет")
        self.assertEqual(loaded["language"], "8")

    def test_unknown_keys_already_on_disk_survive_a_save(self):
        self.config_file.parent.mkdir(parents=True)
        self.config_file.write_text(
            json.dumps({"fullscreen": True, "from_future_version": 42}), encoding="utf-8")
        settings = launcher.load_settings()
        settings["language"] = "0"
        launcher.save_settings(settings)
        on_disk = json.loads(self.config_file.read_text(encoding="utf-8"))
        self.assertEqual(on_disk["from_future_version"], 42)
        self.assertTrue(on_disk["fullscreen"])
        self.assertEqual(on_disk["language"], "0")

    def test_save_overwrites_malformed_file(self):
        self.config_file.parent.mkdir(parents=True)
        self.config_file.write_text("{broken", encoding="utf-8")
        launcher.save_settings(dict(launcher.DEFAULTS))
        self.assertEqual(json.loads(self.config_file.read_text(encoding="utf-8")),
                         launcher.DEFAULTS)


class IniTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ini_file = Path(self.temp.name) / "bbport.ini"
        patcher = patch.object(launcher, "ini_path", lambda: self.ini_file)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, text):
        self.ini_file.write_text(text, encoding="utf-8")

    def read_lines(self):
        return self.ini_file.read_text(encoding="utf-8").splitlines()

    def test_missing_file_returns_defaults(self):
        values, lines = launcher.load_ini()
        self.assertEqual(values, launcher.INI_DEFAULTS)
        self.assertEqual(lines, [])
        self.assertFalse(self.ini_file.exists())

    def test_defaults_are_copied_not_shared(self):
        values, _ = launcher.load_ini()
        values["preset"] = "0"
        self.assertEqual(launcher.INI_DEFAULTS["preset"], "2")

    def test_values_comments_and_unknown_keys_are_loaded(self):
        text = ("# generated by the game\n"
                "upscaler = fsr3\n"
                "\n"
                "  # indented comment with = inside\n"
                "preset= 2 \n"
                "custom_key=custom value\n"
                "tricky=a=b\n")
        self.write(text)
        values, lines = launcher.load_ini()
        self.assertEqual(lines, text.splitlines())
        self.assertEqual(values["upscaler"], "fsr3")
        self.assertEqual(values["preset"], "2")
        self.assertEqual(values["custom_key"], "custom value")
        self.assertEqual(values["tricky"], "a=b")
        self.assertEqual(values["sharpen"], launcher.INI_DEFAULTS["sharpen"])
        self.assertNotIn("# indented comment with = inside", values)

    def test_save_updates_values_and_keeps_comments_and_extra_keys(self):
        text = ("# bbport.ini written by the game\n"
                "\n"
                "upscaler=dlss\n"
                "# preset comment\n"
                "preset = 4\n"
                "custom_key=keep me\n"
                "a line without equals\n")
        self.write(text)
        values, lines = launcher.load_ini()
        values["upscaler"] = "fsr411"
        values["preset"] = "1"
        values["custom_key"] = "changed"
        launcher.save_ini(values, lines)
        out = self.read_lines()
        self.assertEqual(out[0], "# bbport.ini written by the game")
        self.assertEqual(out[1], "")
        self.assertIn("upscaler=fsr411", out)
        self.assertIn("preset=1", out)
        self.assertIn("# preset comment", out)
        self.assertIn("custom_key=changed", out)
        self.assertIn("a line without equals", out)
        self.assertNotIn("upscaler=dlss", out)
        self.assertEqual(out.count("upscaler=fsr411"), 1)

    def test_unknown_lines_are_kept_even_when_not_in_values(self):
        lines = ["# comment", "custom_key=1", "upscaler=dlss", "  # note=value"]
        launcher.save_ini({"upscaler": "fsr3"}, lines)
        out = self.read_lines()
        self.assertIn("# comment", out)
        self.assertIn("custom_key=1", out)
        self.assertIn("upscaler=fsr3", out)
        self.assertIn("  # note=value", out)

    def test_missing_keys_are_appended_once(self):
        self.write("upscaler=fsr411\n")
        values, lines = launcher.load_ini()
        launcher.save_ini(values, lines)
        out = self.read_lines()
        self.assertEqual(out.count("upscaler=fsr411"), 1)
        for key, value in values.items():
            with self.subTest(key=key):
                self.assertIn(f"{key}={value}", out)

    def test_empty_file_gets_header_and_all_defaults(self):
        launcher.save_ini(dict(launcher.INI_DEFAULTS), [])
        text = self.ini_file.read_text(encoding="utf-8")
        out = text.splitlines()
        self.assertEqual(out[0], "# bbport settings (in-game menu: Insert / L3+R3)")
        self.assertEqual(len(out), len(launcher.INI_DEFAULTS) + 1)
        self.assertTrue(text.endswith("\n"))
        self.assertEqual(launcher.load_ini()[0], launcher.INI_DEFAULTS)

    def test_values_with_equals_and_empty_lines_round_trip(self):
        self.write("custom=old\n\npreset=4\n")
        values, lines = launcher.load_ini()
        values["custom"] = "name=value"
        values["preset"] = "2"
        launcher.save_ini(values, lines)
        out = self.read_lines()
        self.assertIn("custom=name=value", out)
        self.assertEqual(out[1], "")
        self.assertEqual(launcher.load_ini()[0]["custom"], "name=value")
        self.assertEqual(launcher.load_ini()[0]["preset"], "2")

    def test_saved_file_always_ends_with_newline(self):
        self.write("upscaler=fsr4")
        values, lines = launcher.load_ini()
        launcher.save_ini(values, lines)
        self.assertTrue(self.ini_file.read_text(encoding="utf-8").endswith("\n"))

    def test_malformed_numbers_fall_back_without_crashing(self):
        values = {"preset": "not a number", "sharpness": "", "hud_position": "x"}
        self.assertEqual(launcher.ini_int(values, "preset", 4), 4)
        self.assertEqual(launcher.ini_float(values, "sharpness", 0.5), 0.5)
        self.assertEqual(launcher.ini_int(values, "hud_position", 100), 100)
        self.assertEqual(launcher.ini_float({"sharpness": "nan"}, "sharpness", 0.5), 0.5)
        self.assertEqual(launcher.ini_int({"preset": 7}, "preset", 4), 7)

    def test_non_utf8_file_is_read_and_rewritten_gracefully(self):
        self.ini_file.write_bytes(b"upscaler=fsr3\nnote=\xff\n")
        values, lines = launcher.load_ini()
        self.assertEqual(values["upscaler"], "fsr3")
        self.assertEqual(values["note"], "\ufffd")
        launcher.save_ini(values, lines)
        self.assertIn("note=\ufffd", self.ini_file.read_text(encoding="utf-8"))


class AtomicWriteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_writes_text_and_creates_parent_directories(self):
        path = self.root / "nested" / "file.txt"
        launcher.atomic_write_text(path, "hello\n")
        self.assertEqual(path.read_text(encoding="utf-8"), "hello\n")

    def test_replaces_existing_content_and_leaves_no_temporary_files(self):
        path = self.root / "file.txt"
        path.write_text("old content that is longer", encoding="utf-8")
        launcher.atomic_write_text(path, "new")
        self.assertEqual(path.read_text(encoding="utf-8"), "new")
        self.assertEqual(sorted(entry.name for entry in self.root.iterdir()), ["file.txt"])

    def test_failed_replace_keeps_the_old_file_and_cleans_up(self):
        path = self.root / "file.txt"
        path.write_text("old", encoding="utf-8")
        with patch.object(launcher.os, "replace", side_effect=OSError("replace failed")):
            with self.assertRaises(OSError):
                launcher.atomic_write_text(path, "new")
        self.assertEqual(path.read_text(encoding="utf-8"), "old")
        self.assertEqual(sorted(entry.name for entry in self.root.iterdir()), ["file.txt"])

    def test_paths_with_spaces_and_unicode(self):
        path = self.root / "saves ü" / "settings file.json"
        launcher.atomic_write_text(path, '{"note": "Привет"}')
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"note": "Привет"})

    @unittest.skipUnless(hasattr(os, "O_DIRECTORY"), "directory fsync is POSIX-only")
    def test_syncs_the_file_and_its_directory(self):
        path = self.root / "file.txt"
        real_fsync = os.fsync
        synced = []

        def record(fd):
            synced.append(fd)
            real_fsync(fd)

        with patch.object(launcher.os, "fsync", side_effect=record):
            launcher.atomic_write_text(path, "data")
        self.assertGreaterEqual(len(synced), 2)

    def test_save_settings_uses_atomic_write(self):
        with patch.object(launcher, "atomic_write_text") as write:
            launcher.save_settings({"language": "8"})
        path, text = write.call_args.args
        self.assertEqual(path, launcher.CONFIG_FILE)
        self.assertEqual(json.loads(text), {"language": "8"})

    def test_save_ini_uses_atomic_write(self):
        ini_file = self.root / "bbport.ini"
        with patch.object(launcher, "ini_path", lambda: ini_file), \
                patch.object(launcher, "atomic_write_text") as write:
            launcher.save_ini({"upscaler": "dlss"}, [])
        path, text = write.call_args.args
        self.assertEqual(path, ini_file)
        self.assertIn("upscaler=dlss", text.splitlines())


class PathTests(unittest.TestCase):
    def test_empty_bb_config_falls_back_to_the_data_directory(self):
        with patch.dict(os.environ, {"BB_CONFIG": ""}):
            self.assertEqual(launcher.ini_path(), launcher.DATA_DIR / "bbport.ini")


class ComboRowTests(unittest.TestCase):
    def setUp(self):
        self.language = launcher.language()

    def tearDown(self):
        launcher.set_language(self.language)

    def combo(self, choices, current, subtitle=None):
        return launcher.combo_row("Title", subtitle, choices, current)

    def test_matching_current_value_selects_its_option(self):
        for index, (_, value) in enumerate(launcher.UPSCALERS):
            with self.subTest(value=value):
                row = self.combo(launcher.UPSCALERS, value)
                self.assertEqual(row.get_selected(), index)
                self.assertEqual(launcher.combo_value(row), value)

    def test_numeric_preset_values_select_their_option(self):
        for index, (_, value) in enumerate(launcher.PRESETS):
            with self.subTest(value=value):
                row = self.combo(launcher.PRESETS, value)
                self.assertEqual(row.get_selected(), index)
                self.assertEqual(launcher.combo_value(row), value)

    def test_unknown_current_value_is_appended_and_selected(self):
        for unknown in ("fsr2", "DLSS", "custom-value"):
            with self.subTest(current=unknown):
                row = self.combo(launcher.UPSCALERS, unknown)
                self.assertEqual(row.get_selected(), len(launcher.UPSCALERS))
                self.assertEqual(launcher.combo_value(row), unknown)
                self.assertEqual(row.get_model().get_string(len(launcher.UPSCALERS)), unknown)

    def test_hud_position_values_select_their_option(self):
        for index, (_, value) in enumerate(launcher.HUD_POSITIONS):
            with self.subTest(value=value):
                row = self.combo(launcher.HUD_POSITIONS, value)
                self.assertEqual(row.get_selected(), index)
                self.assertEqual(launcher.combo_value(row), value)

    def test_unknown_numeric_current_value_is_appended_and_selected(self):
        row = self.combo(launcher.PRESETS, 7)
        self.assertEqual(row.get_selected(), len(launcher.PRESETS))
        self.assertEqual(launcher.combo_value(row), 7)
        self.assertEqual(row.get_model().get_string(len(launcher.PRESETS)), "7")

    def test_dlss_default_matches_an_upscaler_option(self):
        self.assertEqual(launcher.INI_DEFAULTS["upscaler"], "dlss")
        values = [value for _, value in launcher.UPSCALERS]
        self.assertIn(launcher.INI_DEFAULTS["upscaler"], values)
        row = self.combo(launcher.UPSCALERS, launcher.INI_DEFAULTS["upscaler"])
        self.assertEqual(row.get_selected(), values.index("dlss"))
        self.assertEqual(launcher.combo_value(row), launcher.INI_DEFAULTS["upscaler"])

    def test_subtitle_is_set_only_when_given(self):
        row = self.combo(launcher.UPSCALERS, "fsr4", subtitle="Hint")
        self.assertEqual(row.get_subtitle(), "Hint")
        plain = self.combo(launcher.UPSCALERS, "fsr4")
        self.assertEqual(plain.get_subtitle(), "")

    def test_labels_are_taken_from_choices_and_translated(self):
        launcher.set_language("en")
        row = self.combo(launcher.UPSCALERS, "fsr3")
        model = row.get_model()
        self.assertEqual(model.get_string(2), "FSR 3.1 [Recommended]")
        self.assertEqual(model.get_string(3), "DLSS (NVIDIA GeForce RTX)")
        self.assertEqual(model.get_string(4), "TAA (native anti-aliasing)")
        self.assertEqual(model.get_string(5), "Off")

    def test_choices_are_not_modified_when_current_is_unknown(self):
        before = list(launcher.UPSCALERS)
        row = self.combo(launcher.UPSCALERS, "custom")
        self.assertEqual(launcher.UPSCALERS, before)
        self.assertEqual(launcher.combo_value(row), "custom")


class GameEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        data_patcher = patch.object(launcher, "DATA_DIR", self.data)
        data_patcher.start()
        self.addCleanup(data_patcher.stop)
        env_patcher = patch.dict(os.environ, {"HOST_ONLY": "kept"}, clear=True)
        env_patcher.start()
        self.addCleanup(env_patcher.stop)
        self.game = self.root / "CUSA03173"

    def settings(self, **overrides):
        settings = dict(launcher.DEFAULTS)
        settings["game_dir"] = str(self.game)
        settings.update(overrides)
        return settings

    def test_defaults_produce_the_base_environment(self):
        env = launcher.game_environment(self.settings())
        self.assertEqual(env["HOST_ONLY"], "kept")
        self.assertEqual(env["BB_GAME_DIR"], str(self.game))
        self.assertNotIn("BB_USER_DIR", env)
        self.assertEqual(env["BB_MODS_DIR"], str(self.data / "mods"))
        self.assertEqual(env["BB_MODS_CONFIG"], str(self.data / "mods.json"))
        self.assertEqual(env["BB_MODS_ENABLED"], "1")
        self.assertEqual(env["BB_PATCHES_DIR"], str(self.data / "patches"))
        self.assertEqual(env["BB_PATCHES_CONFIG"], str(self.data / "patches.json"))
        self.assertEqual(env["BB_LANGUAGE"], "1")
        self.assertEqual(env["BB_FULLSCREEN"], "0")
        self.assertEqual(env["BB_PRESENT_MODE"], "Mailbox")
        self.assertEqual(env["BB_FPS"], "uncap")
        for key in ("BB_HDR", "BB_FPS_LIMIT", "BB_DRAW_PIPE", "BB_READBACKS", "MANGOHUD",
                    "BB_FRAME_STATS", "BB_GPU_PROFILE", "BB_VK_VALIDATION", "BB_USER_NAME",
                    "BB_DLC_DIR"):
            with self.subTest(key=key):
                self.assertNotIn(key, env)

    def test_all_optional_settings_are_exported(self):
        user = self.root / "saves"
        dlc = self.root / "addcont"
        env = launcher.game_environment(self.settings(
            user_dir=str(user), dlc_dir=str(dlc), player_name="Lady Maria",
            fullscreen=True, hdr=True, fps_limit=90,
            draw_pipe="1", readbacks="2", mangohud=True, frame_stats=True,
            gpu_profile=True, vk_validation=True, language="8", present_mode="Fifo"))
        self.assertEqual(env["BB_USER_DIR"], str(user))
        self.assertEqual(env["BB_DLC_DIR"], str(dlc))
        self.assertEqual(env["BB_USER_NAME"], "Lady Maria")
        self.assertEqual(env["BB_FULLSCREEN"], "1")
        self.assertEqual(env["BB_HDR"], "1")
        self.assertEqual(env["BB_FPS_LIMIT"], "90")
        self.assertEqual(env["BB_DRAW_PIPE"], "1")
        self.assertEqual(env["BB_READBACKS"], "2")
        self.assertEqual(env["MANGOHUD"], "1")
        self.assertEqual(env["BB_FRAME_STATS"], "1")
        self.assertEqual(env["BB_GPU_PROFILE"], "1")
        self.assertEqual(env["BB_VK_VALIDATION"], "1")
        self.assertEqual(env["BB_LANGUAGE"], "8")
        self.assertEqual(env["BB_PRESENT_MODE"], "Fifo")

    def test_disabled_mods_and_zero_fps_limit(self):
        env = launcher.game_environment(self.settings(mods_enabled=False, fps_limit=0))
        self.assertEqual(env["BB_MODS_ENABLED"], "0")
        self.assertNotIn("BB_FPS_LIMIT", env)

    def test_fps_modes_and_limits_propagation(self):
        for mode in ("30", "60", "90", "uncap"):
            with self.subTest(mode=mode):
                env = launcher.game_environment(self.settings(fps_mode=mode, fps_limit=0))
                self.assertEqual(env["BB_FPS"], mode)
                self.assertNotIn("BB_FPS_LIMIT", env)
        env = launcher.game_environment(self.settings(fps_mode="uncap", fps_limit=144))
        self.assertEqual(env["BB_FPS"], "uncap")
        self.assertEqual(env["BB_FPS_LIMIT"], "144")


    def test_custom_directories_are_expanded(self):
        user = self.root / "saves"
        env = launcher.game_environment(self.settings(
            game_dir="~/CUSA03173", user_dir=str(user),
            mods_dir="~/mods", patches_dir="~/patches", dlc_dir="~/addcont"))
        self.assertEqual(env["BB_GAME_DIR"], str(Path("~/CUSA03173").expanduser()))
        self.assertEqual(env["BB_USER_DIR"], str(user))
        self.assertEqual(env["BB_MODS_DIR"], str(Path("~/mods").expanduser()))
        self.assertEqual(env["BB_PATCHES_DIR"], str(Path("~/patches").expanduser()))
        self.assertEqual(env["BB_DLC_DIR"], str(Path("~/addcont").expanduser()))

    def test_user_dir_is_expanded_like_the_other_folders(self):
        env = launcher.game_environment(self.settings(user_dir="~/saves"))
        self.assertEqual(env["BB_USER_DIR"], str(Path("~/saves").expanduser()))

    def test_player_name_is_trimmed_and_blank_names_are_skipped(self):
        env = launcher.game_environment(self.settings(player_name="  Micolash  "))
        self.assertEqual(env["BB_USER_NAME"], "Micolash")
        for name in ("", "   ", "\t\n"):
            with self.subTest(name=name):
                env = launcher.game_environment(self.settings(player_name=name))
                self.assertNotIn("BB_USER_NAME", env)

    def test_dlc_folder_is_expanded_and_blank_paths_are_skipped(self):
        env = launcher.game_environment(self.settings(dlc_dir="~/addcont"))
        self.assertEqual(env["BB_DLC_DIR"], str(Path("~/addcont").expanduser()))
        for path in ("", "   "):
            with self.subTest(path=path):
                env = launcher.game_environment(self.settings(dlc_dir=path))
                self.assertNotIn("BB_DLC_DIR", env)

    def test_extra_env_is_parsed_and_can_override_base_values(self):
        env = launcher.game_environment(self.settings(
            extra_env="FOO=1  BAR=two=parts BROKEN\tBB_LANGUAGE=8 HOST_ONLY=changed"))
        self.assertEqual(env["FOO"], "1")
        self.assertEqual(env["BAR"], "two=parts")
        self.assertNotIn("BROKEN", env)
        self.assertEqual(env["BB_LANGUAGE"], "8")
        self.assertEqual(env["HOST_ONLY"], "changed")


class FakeProcess:
    def __init__(self, identifier, exited=False, signaled=False):
        self.identifier = identifier
        self.exited = exited
        self.signaled = signaled
        self.forced = False

    def get_identifier(self):
        return self.identifier

    def force_exit(self):
        self.forced = True

    def get_if_exited(self):
        return self.exited

    def get_if_signaled(self):
        return self.signaled

    def get_exit_status(self):
        return 0

    def wait_finish(self, _result):
        pass


class ProcessLifecycleTests(unittest.TestCase):
    def window(self, process=None, stopping=None):
        window = types.SimpleNamespace()
        window.process = process
        window._stopping_pid = stopping
        window.toasts = types.SimpleNamespace(add_toast=lambda *_: None)
        window.append_log = lambda _text: None
        window.update_launch_button = lambda: None
        window.update_game_status = lambda: None
        window.process_active = lambda: launcher.LauncherWindow.process_active(window)
        window.kill_if_running = lambda pid: launcher.LauncherWindow.kill_if_running(window, pid)
        return window

    def stop(self, identifier):
        process = FakeProcess(identifier)
        window = self.window(process)
        with patch.object(launcher.GLib, "timeout_add_seconds", return_value=None) as timer, \
                patch.object(launcher.os, "killpg") as kill:
            launcher.LauncherWindow.stop_game(window)
        return process, timer, kill

    def test_pid_zero_and_one_are_never_signalled(self):
        for identifier in ("0", "1", "-1", "not-a-pid", None):
            with self.subTest(identifier=identifier):
                process, _timer, kill = self.stop(identifier)
                kill.assert_not_called()
                self.assertTrue(process.forced)

    def test_a_valid_pid_signals_its_process_group(self):
        _process, timer, kill = self.stop("4242")
        kill.assert_called_once_with(4242, signal.SIGTERM)
        timer.assert_called_once()
        self.assertEqual(timer.call_args.args[0], 3)
        self.assertEqual(timer.call_args.args[2], 4242)

    def test_the_timeout_escalates_to_sigkill_for_its_own_group(self):
        window = self.window(FakeProcess("4242"), stopping=4242)
        with patch.object(launcher.os, "killpg") as kill:
            self.assertFalse(launcher.LauncherWindow.kill_if_running(window, 4242))
        kill.assert_called_once_with(4242, signal.SIGKILL)

    def test_a_stale_timeout_leaves_a_new_process_alone(self):
        window = self.window(FakeProcess("9999"), stopping=9999)
        with patch.object(launcher.os, "killpg") as kill:
            self.assertFalse(launcher.LauncherWindow.kill_if_running(window, 4242))
        kill.assert_not_called()

    def test_an_exited_process_is_not_signalled_again(self):
        window = self.window(FakeProcess("4242", exited=True), stopping=4242)
        with patch.object(launcher.os, "killpg") as kill:
            launcher.LauncherWindow.kill_if_running(window, 4242)
        kill.assert_not_called()

    def test_an_old_exit_callback_does_not_clear_a_new_process(self):
        old, new = FakeProcess("100"), FakeProcess("200")
        window = self.window(new, stopping=200)
        launcher.LauncherWindow.on_exit(window, old, None)
        self.assertIs(window.process, new)
        self.assertEqual(window._stopping_pid, 200)

    def test_the_current_process_is_cleared_on_exit(self):
        process = FakeProcess("100")
        window = self.window(process, stopping=100)
        launcher.LauncherWindow.on_exit(window, process, None)
        self.assertIsNone(window.process)
        self.assertIsNone(window._stopping_pid)


class LogReaderTests(unittest.TestCase):
    class ConvertError(Exception):
        def __init__(self):
            super().__init__("Invalid byte sequence")
            self.message = "Invalid byte sequence"
            self.domain = "g_convert_error"

    class OtherError(Exception):
        def __init__(self):
            super().__init__("read failed")
            self.message = "read failed"
            self.domain = 0

    class Stream:
        def __init__(self, outcomes):
            self.outcomes = list(outcomes)

        def read_line_finish_utf8(self, _result):
            outcome = self.outcomes.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

    def window(self, active):
        window = types.SimpleNamespace()
        window.logs = []
        window.reads = 0
        window.append_log = window.logs.append
        window.process_active = lambda: active

        def read_line():
            window.reads += 1
        window.read_line = read_line
        return window

    def read(self, outcomes, active=True, error=ConvertError):
        window = self.window(active)
        stream = self.Stream(outcomes)
        with patch.object(launcher.GLib, "Error", error):
            for _ in outcomes:
                launcher.LauncherWindow.on_line(window, stream, None)
        return window

    def test_non_utf8_is_reported_and_the_next_line_is_still_read(self):
        window = self.read([self.ConvertError(), ("good", 4), (None, 0)], active=False)
        self.assertEqual(window.logs[1], "good\n")
        self.assertIn("Invalid byte sequence", window.logs[0])
        self.assertEqual(window.reads, 2)

    def test_other_read_errors_stop_with_the_process(self):
        window = self.read([self.OtherError()], active=False, error=self.OtherError)
        self.assertEqual(window.reads, 0)

    def test_eof_does_not_start_another_read(self):
        window = self.read([(None, 0)])
        self.assertEqual(window.reads, 0)

    @unittest.skipUnless(REAL_GI, "PyGObject is not installed")
    def test_a_real_stream_survives_non_utf8_output(self):
        process = launcher.Gio.SubprocessLauncher.new(
            launcher.Gio.SubprocessFlags.STDOUT_PIPE).spawnv(
                ["bash", "-c", "printf '\\xff bad\\n'; printf 'good line\\n'"])
        stream = launcher.Gio.DataInputStream.new(process.get_stdout_pipe())
        window = types.SimpleNamespace(process=process, stream=stream)
        window.logs = []
        window.append_log = window.logs.append
        loop = launcher.GLib.MainLoop()

        def on_line(source, result):
            launcher.LauncherWindow.on_line(window, source, result)
            if any("good line" in line for line in window.logs):
                loop.quit()

        window.process_active = lambda: launcher.LauncherWindow.process_active(window)
        window.read_line = lambda: stream.read_line_async(
            launcher.GLib.PRIORITY_DEFAULT, None, on_line)
        window.read_line()
        launcher.GLib.timeout_add(3000, loop.quit)
        loop.run()
        process.force_exit()
        self.assertTrue(any("good line" in line for line in window.logs))
        self.assertIn("Invalid byte sequence", "".join(window.logs))


class InstallDesktopTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "posix" and shutil.which("bash"), "needs bash")
    def test_paths_with_spaces_unicode_and_sed_metacharacters(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "check out ü&%" / "launcher"
            folder.mkdir(parents=True)
            for name in ("bb-launcher.sh", "bloodborne.png",
                         "io.github.bbport.Launcher.desktop.in", "install-desktop.sh"):
                shutil.copy2(LAUNCHER_DIR / name, folder / name)
            data = root / "data ü&%"
            env = dict(os.environ, XDG_DATA_HOME=str(data), HOME=str(root / "home"))
            result = subprocess.run(["bash", str(folder / "install-desktop.sh")], env=env,
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            desktop = (data / "applications/io.github.bbport.Launcher.desktop").read_text(
                encoding="utf-8")
            self.assertNotIn("@LAUNCHER@", desktop)
            self.assertIn("Icon=io.github.bbport.Launcher", desktop)
            exec_line = next(line for line in desktop.splitlines() if line.startswith("Exec="))
            self.assertTrue(exec_line.startswith('Exec="'))
            self.assertIn(str(folder / "bb-launcher.sh").replace("%", "%%"), exec_line)
            icon = data / "icons/hicolor/256x256/apps/io.github.bbport.Launcher.png"
            self.assertTrue(icon.is_file())


class DefinitionsTests(unittest.TestCase):
    def setUp(self):
        self.language = launcher.language()

    def tearDown(self):
        launcher.set_language(self.language)

    def test_upscaler_values_and_labels_are_unique(self):
        labels = [label for label, _ in launcher.UPSCALERS]
        values = [value for _, value in launcher.UPSCALERS]
        self.assertEqual(values, ["fsr4", "fsr411", "fsr3", "dlss", "taa", "off"])
        self.assertEqual(len(labels), len(set(labels)))
        self.assertEqual(len(values), len(set(values)))

    def test_upscaler_labels_are_translated(self):
        launcher.set_language("en")
        self.assertEqual([launcher.tr(label) for label, _ in launcher.UPSCALERS],
                         ["FSR 4 [Experimental ⚠️]", "FSR 4.1.1 [Experimental ⚠️]", "FSR 3.1 [Recommended]", "DLSS (NVIDIA GeForce RTX)",
                          "TAA (native anti-aliasing)", "Off"])
        launcher.set_language("ru")
        self.assertEqual([launcher.tr(label) for label, _ in launcher.UPSCALERS],
                         [label for label, _ in launcher.UPSCALERS])

    def test_ini_upscaler_default_is_a_known_option(self):
        self.assertEqual(launcher.INI_DEFAULTS["upscaler"], "dlss")
        values = [value for _, value in launcher.UPSCALERS]
        self.assertIn(launcher.INI_DEFAULTS["upscaler"], values)
        row = launcher.combo_row("Upscaler", None, launcher.UPSCALERS,
                                 launcher.INI_DEFAULTS["upscaler"])
        self.assertEqual(row.get_selected(), values.index("dlss"))
        self.assertEqual(launcher.combo_value(row), launcher.INI_DEFAULTS["upscaler"])

    def test_launcher_defaults_are_valid_menu_values(self):
        for key, choices in (
                ("ui_language", launcher.UI_LANGUAGES),
                ("control_scheme", launcher.CONTROL_SCHEMES),
                ("language", launcher.LANGUAGES),
                ("present_mode", launcher.PRESENT_MODES),
                ("fps_mode", launcher.FPS_MODES),
                ("draw_pipe", launcher.DRAW_PIPE),
                ("readbacks", launcher.READBACKS)):
            with self.subTest(key=key):
                self.assertIn(launcher.DEFAULTS[key], [value for _, value in choices])

    def test_ini_defaults_are_valid_menu_values(self):
        for key, choices in (
                ("upscaler", launcher.UPSCALERS),
                ("output_res", launcher.OUTPUT_RES),
                ("hud_position", launcher.HUD_POSITIONS),
                ("model_lod", launcher.MODEL_LOD),
                ("live_resolution", launcher.LIVE_RESOLUTION)):
            with self.subTest(key=key):
                self.assertIn(launcher.INI_DEFAULTS[key], [value for _, value in choices])
        self.assertIn(int(launcher.INI_DEFAULTS["preset"]),
                      [value for _, value in launcher.PRESETS])

    def test_output_resolutions_include_16_10_and_ultrawide(self):
        values = [value for _, value in launcher.OUTPUT_RES]
        for value in ("1280x720", "1920x1080", "2560x1440", "3840x2160",
                      "1280x800", "2560x1080", "3440x1440", "3840x1600", "5120x1440"):
            with self.subTest(value=value):
                self.assertIn(value, values)
        labels = [label for label, _ in launcher.OUTPUT_RES]
        self.assertEqual(len(labels), len(set(labels)))
        self.assertEqual(len(values), len(set(values)))

    def test_hud_positions_match_the_ini_default(self):
        values = [value for _, value in launcher.HUD_POSITIONS]
        self.assertEqual(values, ["100", "75", "50", "25", "0"])
        self.assertEqual(launcher.INI_DEFAULTS["hud_position"], values[0])
        labels = [label for label, _ in launcher.HUD_POSITIONS]
        self.assertEqual(len(labels), len(set(labels)))

    def test_effect_keys_and_ini_defaults_agree(self):
        for name, definitions in (("EFFECTS", launcher.EFFECTS),
                                  ("ENHANCEMENTS", launcher.ENHANCEMENTS),
                                  ("CHEATS_AND_TWEAKS", launcher.CHEATS_AND_TWEAKS)):
            keys = [key for key, _, _ in definitions]
            self.assertEqual(len(keys), len(set(keys)), name)
            for key, _, default in definitions:
                with self.subTest(list=name, key=key):
                    self.assertIn(key, launcher.INI_DEFAULTS)
                    self.assertEqual(launcher.INI_DEFAULTS[key], "1" if default else "0")

    def test_player_name_and_dlc_folder_defaults_are_empty(self):
        self.assertEqual(launcher.DEFAULTS["player_name"], "")
        self.assertEqual(launcher.DEFAULTS["dlc_dir"], "")

    def test_ini_defaults_are_strings(self):
        for key, value in launcher.INI_DEFAULTS.items():
            with self.subTest(key=key):
                self.assertIsInstance(value, str)

    def test_preset_definitions_are_ordered_and_unique(self):
        self.assertEqual([value for _, value in launcher.PRESETS], [0, 1, 2, 3, 4])
        labels = [label for label, _ in launcher.PRESETS]
        self.assertEqual(len(labels), len(set(labels)))

    def test_hud_labels_are_translated(self):
        launcher.set_language("en")
        self.assertEqual([launcher.tr(label) for label, _ in launcher.HUD_POSITIONS],
                         ["Screen edges (100%)", "75%", "Halfway (50%)", "25%",
                          "Centred (16:9)"])
        launcher.set_language("ru")
        self.assertEqual([launcher.tr(label) for label, _ in launcher.HUD_POSITIONS],
                         [label for label, _ in launcher.HUD_POSITIONS])


class TranslationTests(unittest.TestCase):
    def test_new_interface_strings_have_english_translations(self):
        from bbport_i18n import EN
        strings = [
            "Имя охотника", "Папка DLC", "Выбрать папку DLC", "Открыть папку DLC",
            "Вернуть папку DLC по умолчанию",
            "Позиция HUD", "Ультраширокие экраны: элементы у краёв или в центре 16:9",
            "У краёв экрана (100%)", "Посередине (50%)", "По центру (16:9)",
            "Улучшения (PC)",
            "Игровые файлы создаются при запуске; выключено — игра как в оригинале",
            *[title for _, title, _ in launcher.ENHANCEMENTS],
            "Читы и твики", "Патчи игры 1.09: сложность, физика и камера",
            "Ассеты FSR 4", "Скачать ассеты", "Проверить", "Не поддерживается",
            "Загрузка: {} из {}...", "Установлены: {} файлов в fsr4_shaders",
            "Отсутствует {} из {} файлов в fsr4_shaders",
            "Видеокарта не поддерживает FSR 4 (требуется INT8 dot product)",
            "Ошибка загрузки FSR 4: {}", "Нет ассетов (скачайте в строке ниже)",
            "Управление", "Схема управления", "Отображение кнопок и раскладка в игре",
            "ПК — клавиатура и мышь", "Геймпад Xbox", "Геймпад PlayStation",
            "Клавиатурные подсказки отсутствуют в дистрибутиве",
            "Подсказки Xbox отсутствуют в папке модов",
            *[title for _, title, _ in launcher.CHEATS_AND_TWEAKS],
        ]
        for text in strings:
            with self.subTest(text=text):
                self.assertIn(text, EN)
                self.assertTrue(EN[text])


class Fsr4LauncherTests(unittest.TestCase):
    def test_window_creates_fsr4_row_and_widgets(self):
        app = launcher.Adw.Application(application_id="io.github.bbport.TestFsr4")
        app.connect("activate", lambda a: None)
        win = launcher.LauncherWindow(app)
        self.assertTrue(hasattr(win, "fsr4_row"))
        self.assertTrue(hasattr(win, "fsr4_button"))
        self.assertTrue(hasattr(win, "fsr4_progress"))
        self.assertFalse(win.downloading_fsr4)
        subtitle = win.fsr4_row.get_subtitle()
        self.assertTrue(len(subtitle) > 0)


class ControlSchemeTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="bbport-ctrl-test-")
        self.root = Path(self.temp_dir)
        self.mods_dir = self.root / "mods"
        self.mods_dir.mkdir(parents=True)
        self.config_dir = self.root / "config"
        self.config_dir.mkdir(parents=True)
        self.data_dir = self.root / "data"
        self.data_dir.mkdir(parents=True)
        self.mods_json = self.data_dir / "mods.json"
        self.ini_file = self.data_dir / "bbport.ini"
        self.settings_json = self.config_dir / "settings.json"

        self.patch_data = patch.object(launcher, "DATA_DIR", self.data_dir)
        self.patch_cfg_file = patch.object(launcher, "CONFIG_FILE", self.settings_json)
        self.patch_cfg_dir = patch.object(launcher, "CONFIG_DIR", self.config_dir)
        self.patch_ini = patch("bbport_launcher.ini_path", return_value=self.ini_file)
        self.patch_data.start()
        self.patch_cfg_file.start()
        self.patch_cfg_dir.start()
        self.patch_ini.start()

    def tearDown(self):
        self.patch_ini.stop()
        self.patch_cfg_dir.stop()
        self.patch_cfg_file.stop()
        self.patch_data.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_default_control_scheme(self):
        self.assertEqual(launcher.DEFAULTS["control_scheme"], "xbox")
        scheme = launcher.detect_control_scheme(self.mods_dir, self.mods_json)
        self.assertIn(scheme, ("xbox", "playstation"))
        (self.mods_dir / "Xbox 360 Prompts (Elden Ring)").mkdir()
        scheme_xbox = launcher.detect_control_scheme(self.mods_dir, self.mods_json)
        self.assertEqual(scheme_xbox, "xbox")

    def test_loading_each_supported_scheme(self):
        for raw, expected in (
            ("pc", "pc"),
            ("keyboard", "pc"),
            ("PC — Keyboard & Mouse", "pc"),
            ("ПК — клавиатура и мышь", "pc"),
            ("xbox", "xbox"),
            ("Xbox Controller", "xbox"),
            ("Геймпад Xbox", "xbox"),
            ("playstation", "playstation"),
            ("PlayStation Controller", "playstation"),
            ("Геймпад PlayStation", "playstation"),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(launcher.canonical_control_scheme(raw), expected)

    def test_saving_each_scheme_and_reloading(self):
        (self.mods_dir / "Xbox 360 Prompts (Elden Ring)").mkdir()
        (self.mods_dir / launcher.KEYBOARD_PROMPTS / "menu").mkdir(parents=True)
        (self.mods_dir / launcher.KEYBOARD_PROMPTS / "menu" / "common.tpf.dcx").write_bytes(b"test")

        for scheme in ("pc", "xbox", "playstation"):
            with self.subTest(scheme=scheme):
                settings = dict(launcher.DEFAULTS)
                settings["control_scheme"] = scheme
                launcher.apply_control_scheme(scheme, self.mods_dir, self.mods_json)
                launcher.save_settings(settings)

                loaded = json.loads(self.settings_json.read_text(encoding="utf-8"))
                self.assertEqual(loaded["control_scheme"], scheme)

                detected = launcher.detect_control_scheme(self.mods_dir, self.mods_json)
                self.assertEqual(detected, scheme)

    def test_handling_unknown_or_malformed_values(self):
        for bad_val in (None, "", "   ", "nintendo_switch", "dance_pad", 12345, [], {}):
            with self.subTest(bad=bad_val):
                normalized = launcher.canonical_control_scheme(bad_val, default="xbox")
                self.assertEqual(normalized, "xbox")
                self.mods_json.write_text("invalid json {{{", encoding="utf-8")
                safe = launcher.detect_control_scheme(self.mods_dir, self.mods_json, fallback=bad_val)
                self.assertIn(safe, ("xbox", "playstation"))

    def test_preserving_unrelated_settings(self):
        settings = dict(launcher.DEFAULTS)
        settings["game_dir"] = "/custom/game/path"
        settings["player_name"] = "HunterTest"
        settings["fps_mode"] = "60"
        settings["mangohud"] = True
        settings["control_scheme"] = "pc"
        launcher.save_settings(settings)

        content_mod = "Custom Hunter Armor"
        profile = {"enabled": [content_mod], "disabled": ["Old Mod"], "order": [content_mod, "Old Mod"]}
        self.mods_json.write_text(json.dumps(profile), encoding="utf-8")

        self.ini_file.write_text("upscaler=fsr3\npreset=1\noutput_res=2560x1440\n", encoding="utf-8")

        launcher.apply_control_scheme("xbox", self.mods_dir, self.mods_json)
        settings["control_scheme"] = "xbox"
        launcher.save_settings(settings)

        reloaded_settings = json.loads(self.settings_json.read_text(encoding="utf-8"))
        self.assertEqual(reloaded_settings["game_dir"], "/custom/game/path")
        self.assertEqual(reloaded_settings["player_name"], "HunterTest")
        self.assertEqual(reloaded_settings["fps_mode"], "60")
        self.assertTrue(reloaded_settings["mangohud"])
        self.assertEqual(reloaded_settings["control_scheme"], "xbox")

        reloaded_mods = json.loads(self.mods_json.read_text(encoding="utf-8"))
        self.assertIn(content_mod, reloaded_mods["enabled"])
        self.assertIn("Old Mod", reloaded_mods["disabled"])

        ini_text = self.ini_file.read_text(encoding="utf-8")
        self.assertIn("upscaler=fsr3", ini_text)
        self.assertIn("preset=1", ini_text)
        self.assertIn("output_res=2560x1440", ini_text)

    def test_mapping_from_launcher_to_runtime_configuration(self):
        (self.mods_dir / "Xbox 360 Prompts (Elden Ring)").mkdir()
        (self.mods_dir / launcher.KEYBOARD_PROMPTS / "menu").mkdir(parents=True)
        (self.mods_dir / launcher.KEYBOARD_PROMPTS / "menu" / "common.tpf.dcx").write_bytes(b"test")

        launcher.apply_control_scheme("pc", self.mods_dir, self.mods_json)
        mods_data = json.loads(self.mods_json.read_text(encoding="utf-8"))
        self.assertIn(launcher.KEYBOARD_PROMPTS, mods_data["enabled"])
        self.assertIn("Xbox 360 Prompts (Elden Ring)", mods_data["disabled"])

        env_pc = launcher.game_environment({"game_dir": str(self.root), "user_dir": "", "mods_dir": str(self.mods_dir),
                                            "patches_dir": "", "language": "1", "fullscreen": False, "hdr": False,
                                            "present_mode": "Mailbox", "fps_mode": "uncap", "fps_limit": 0,
                                            "draw_pipe": "", "readbacks": "", "mangohud": False, "frame_stats": False,
                                            "gpu_profile": False, "vk_validation": False, "extra_env": "",
                                            "control_scheme": "pc"})
        self.assertEqual(env_pc["BB_BUTTON_PROMPTS"], "Keyboard")
        self.assertEqual(env_pc["BB_KEY_PROMPT_IMAGES"], "1")

        launcher.apply_control_scheme("xbox", self.mods_dir, self.mods_json)
        mods_data = json.loads(self.mods_json.read_text(encoding="utf-8"))
        self.assertIn("Xbox 360 Prompts (Elden Ring)", mods_data["enabled"])
        self.assertIn(launcher.KEYBOARD_PROMPTS, mods_data["disabled"])

        env_xbox = launcher.game_environment({"game_dir": str(self.root), "user_dir": "", "mods_dir": str(self.mods_dir),
                                              "patches_dir": "", "language": "1", "fullscreen": False, "hdr": False,
                                              "present_mode": "Mailbox", "fps_mode": "uncap", "fps_limit": 0,
                                              "draw_pipe": "", "readbacks": "", "mangohud": False, "frame_stats": False,
                                              "gpu_profile": False, "vk_validation": False, "extra_env": "",
                                              "control_scheme": "xbox"})
        self.assertEqual(env_xbox["BB_BUTTON_PROMPTS"], "")
        self.assertEqual(env_xbox["BB_KEY_PROMPT_IMAGES"], "0")

        launcher.apply_control_scheme("playstation", self.mods_dir, self.mods_json)
        mods_data = json.loads(self.mods_json.read_text(encoding="utf-8"))
        self.assertIn("Xbox 360 Prompts (Elden Ring)", mods_data["disabled"])
        self.assertIn(launcher.KEYBOARD_PROMPTS, mods_data["disabled"])
        self.assertNotIn(launcher.KEYBOARD_PROMPTS, mods_data["enabled"])
        self.assertNotIn("Xbox 360 Prompts (Elden Ring)", mods_data["enabled"])

        env_ps = launcher.game_environment({"game_dir": str(self.root), "user_dir": "", "mods_dir": str(self.mods_dir),
                                            "patches_dir": "", "language": "1", "fullscreen": False, "hdr": False,
                                            "present_mode": "Mailbox", "fps_mode": "uncap", "fps_limit": 0,
                                            "draw_pipe": "", "readbacks": "", "mangohud": False, "frame_stats": False,
                                            "gpu_profile": False, "vk_validation": False, "extra_env": "",
                                            "control_scheme": "playstation"})
        self.assertEqual(env_ps["BB_BUTTON_PROMPTS"], "")
        self.assertEqual(env_ps["BB_KEY_PROMPT_IMAGES"], "0")

    def test_runtime_prompt_selection_with_mods_py(self):
        xbox_mod = self.mods_dir / "Xbox 360 Prompts (Elden Ring)"
        (xbox_mod / "dvdroot_ps4" / "menu").mkdir(parents=True)
        (xbox_mod / "dvdroot_ps4" / "menu" / "common.tpf.dcx").write_bytes(b"xbox_prompts")

        kb_mod = self.mods_dir / launcher.KEYBOARD_PROMPTS
        (kb_mod / "dvdroot_ps4" / "menu").mkdir(parents=True)
        (kb_mod / "dvdroot_ps4" / "menu" / "common.tpf.dcx").write_bytes(b"kb_prompts")

        sys.path.insert(0, str(ROOT / "scripts"))
        import mods as mod_script

        launcher.apply_control_scheme("pc", self.mods_dir, self.mods_json)
        selected_pc = mod_script.selected(self.mods_dir, self.mods_json)
        self.assertIn(launcher.KEYBOARD_PROMPTS, selected_pc)
        self.assertNotIn("Xbox 360 Prompts (Elden Ring)", selected_pc)

        launcher.apply_control_scheme("xbox", self.mods_dir, self.mods_json)
        selected_xbox = mod_script.selected(self.mods_dir, self.mods_json)
        self.assertIn("Xbox 360 Prompts (Elden Ring)", selected_xbox)
        self.assertNotIn(launcher.KEYBOARD_PROMPTS, selected_xbox)

        launcher.apply_control_scheme("playstation", self.mods_dir, self.mods_json)
        selected_ps = mod_script.selected(self.mods_dir, self.mods_json)
        self.assertNotIn(launcher.KEYBOARD_PROMPTS, selected_ps)
        self.assertNotIn("Xbox 360 Prompts (Elden Ring)", selected_ps)

    def test_overlay_mods_json_sync(self):
        profile = {"disabled": ["Xbox 360 Prompts (Elden Ring)", launcher.KEYBOARD_PROMPTS], "enabled": []}
        self.mods_json.write_text(json.dumps(profile), encoding="utf-8")
        self.assertEqual(launcher.detect_control_scheme(self.mods_dir, self.mods_json), "playstation")

        profile = {"disabled": ["Xbox 360 Prompts (Elden Ring)"], "enabled": [launcher.KEYBOARD_PROMPTS]}
        self.mods_json.write_text(json.dumps(profile), encoding="utf-8")
        self.assertEqual(launcher.detect_control_scheme(self.mods_dir, self.mods_json), "pc")

        profile = {"disabled": [launcher.KEYBOARD_PROMPTS], "enabled": ["Xbox 360 Prompts (Elden Ring)"]}
        self.mods_json.write_text(json.dumps(profile), encoding="utf-8")
        self.assertEqual(launcher.detect_control_scheme(self.mods_dir, self.mods_json), "xbox")

    def test_window_creates_control_scheme_row(self):
        app = launcher.Adw.Application(application_id="io.github.bbport.TestControls")
        app.connect("activate", lambda a: None)
        win = launcher.LauncherWindow(app)
        self.assertTrue(hasattr(win, "control_scheme_row"))
        self.assertIn(win.current_control_scheme(), ("pc", "xbox", "playstation"))


class InternalResolutionTests(unittest.TestCase):
    def test_preset_scaling_calculations(self):
        # 1920x1080 calculations
        # Preset 0: 1.0x -> 1920x1080
        rw, rh, scale = launcher.compute_internal_resolution("1920x1080", 0)
        self.assertEqual((rw, rh, scale), (1920, 1080, 1.0))
        # Preset 1: 1.5x -> 1280x720
        rw, rh, scale = launcher.compute_internal_resolution("1920x1080", 1)
        self.assertEqual((rw, rh, scale), (1280, 720, 1.5))
        # Preset 2: 1.7x -> 1130x636 (aligned to even pixels)
        rw, rh, scale = launcher.compute_internal_resolution("1920x1080", 2)
        self.assertEqual(scale, 1.7)
        self.assertEqual(rw % 2, 0)
        self.assertEqual(rh % 2, 0)
        self.assertEqual((rw, rh), (1130, 636))
        # Preset 3: 2.0x -> 960x540
        rw, rh, scale = launcher.compute_internal_resolution("1920x1080", 3)
        self.assertEqual((rw, rh, scale), (960, 540, 2.0))
        # Preset 4: 3.0x -> 640x360
        rw, rh, scale = launcher.compute_internal_resolution("1920x1080", 4)
        self.assertEqual((rw, rh, scale), (640, 360, 3.0))

    def test_different_output_resolutions(self):
        # 4K (3840x2160) at Performance (2.0x) -> 1920x1080
        rw, rh, scale = launcher.compute_internal_resolution("3840x2160", 3)
        self.assertEqual((rw, rh, scale), (1920, 1080, 2.0))
        # 1440p (2560x1440) at Quality (1.5x) -> 1706x960
        rw, rh, scale = launcher.compute_internal_resolution("2560x1440", 1)
        self.assertEqual((rw, rh, scale), (1706, 960, 1.5))
        # Ultrawide (3440x1440) at Performance (2.0x) -> 1720x720
        rw, rh, scale = launcher.compute_internal_resolution("3440x1440", 3)
        self.assertEqual((rw, rh, scale), (1720, 720, 2.0))

    def test_custom_render_res_override(self):
        rw, rh, scale = launcher.compute_internal_resolution("1920x1080", 3, custom_render_res="1600x900")
        self.assertEqual((rw, rh, scale), (1600, 900, None))

    def test_invalid_strings_fallback(self):
        rw, rh, scale = launcher.compute_internal_resolution("invalid_output", "invalid_preset")
        self.assertEqual((rw, rh), (1130, 636))
        self.assertEqual(scale, 1.7)

    def test_window_preset_subtitle_updates(self):
        app = launcher.Adw.Application(application_id="io.github.bbport.TestRes")
        app.connect("activate", lambda a: None)
        win = launcher.LauncherWindow(app)

        # FSR 3 + 1920x1080 + Quality (1.5x)
        win.upscaler_row.set_selected(2)
        win.output_row.set_selected(1)
        win.preset_row.set_selected(1)
        win.update_upscaler_status()
        subtitle = win.preset_row.get_subtitle()
        self.assertIn("1280", subtitle)
        self.assertIn("720", subtitle)
        self.assertIn("1920", subtitle)
        self.assertIn("1080", subtitle)

        # TAA shows native resolution
        win.upscaler_row.set_selected(4)
        win.update_upscaler_status()
        taa_sub = win.preset_row.get_subtitle()
        self.assertIn("1920", taa_sub)
        self.assertIn("1080", taa_sub)
        self.assertNotIn("→", taa_sub)

    def test_preset_persistence_in_ini(self):
        with tempfile.TemporaryDirectory() as tmp:
            ini_file = Path(tmp) / "bbport.ini"
            with patch.object(launcher, "ini_path", lambda: ini_file):
                values, lines = launcher.load_ini()
                values["preset"] = "3"
                values["output_res"] = "2560x1440"
                values["upscaler"] = "fsr3"
                launcher.save_ini(values, lines)

                loaded_values, _ = launcher.load_ini()
                self.assertEqual(loaded_values["preset"], "3")
                self.assertEqual(loaded_values["output_res"], "2560x1440")
                self.assertEqual(loaded_values["upscaler"], "fsr3")


if __name__ == "__main__":
    unittest.main()


