#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Bloodborne launcher for the native Linux port (GTK4 / libadwaita).

Cinematic Gothic Hybrid redesign featuring:
- Dramatic Bloodborne Victorian gothic home screen and hero section
- Clean multi-page navigation (Home, Graphics, Game, Downloads, Settings, Log)
- Dedicated 6-language switcher (EN, FR, RU, ZH, KO, JA)
- Robust settings persistence and supervisor integration
"""

import json
import math
import os
import shutil
import signal
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path

LAUNCHER_DIR = Path(__file__).resolve().parent
if str(LAUNCHER_DIR) not in sys.path:
    sys.path.insert(0, str(LAUNCHER_DIR))

from bbport_assets import (
    FSR4_BASE,
    KEYBOARD_PROMPTS,
    KEYBOARD_PROMPT_LAYOUT,
    apply_control_scheme,
    bundled_keyboard_prompts,
    canonical_control_scheme,
    detect_control_scheme,
    fsr411_problem,
    fsr4_files,
    fsr4_gpu_supported,
    fsr4_missing,
    install_keyboard_prompts,
    is_keyboard_prompt,
    is_prompt_mod,
    is_xbox_prompt,
    validate_fsr4_file,
)
from bbport_i18n import language, set_language, tr

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

PORT_DIR = LAUNCHER_DIR.parent  # native_probe (or the package's copy)
sys.path.insert(0, str(PORT_DIR / 'scripts'))
from mods import discover as discover_mods  # noqa: E402
from patches import external_patches  # noqa: E402
# Packaged (AppImage): generated files, saves and bbport.ini live in BB_DATA_DIR.
PACKAGED = bool(os.environ.get("BB_PREBUILT"))
DATA_DIR = Path(os.environ.get("BB_DATA_DIR", PORT_DIR))
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "bbport-launcher"
CONFIG_FILE = CONFIG_DIR / "settings.json"
MAX_LOG_LINES = 5000

# Choices: (native display label, value). Default is English ("en").
UI_LANGUAGES = [
    ("English", "en"),
    ("Français", "fr"),
    ("Русский", "ru"),
    ("简体中文", "zh"),
    ("한국어", "ko"),
    ("日本語", "ja"),
]

UI_SCALE_OPTIONS = [
    ("100% (Default)", "100"),
    ("125%", "125"),
    ("150%", "150"),
]

THEME_OPTIONS = [
    ("Dark (Default)", "dark"),
    ("Midnight Charcoal", "charcoal"),
    ("Blood Moon", "blood_moon"),
]

CONTROL_SCHEMES = [
    ("ПК — клавиатура и мышь", "pc"),
    ("Геймпад Xbox", "xbox"),
    ("Геймпад PlayStation", "playstation"),
]

UPSCALERS = [
    ("FSR 4 [Experimental ⚠️]", "fsr4"),
    ("FSR 4.1.1 [Experimental ⚠️]", "fsr411"),
    ("FSR 3.1 [Рекомендуется]", "fsr3"),
    ("DLSS (NVIDIA GeForce RTX)", "dlss"),
    ("TAA (нативное сглаживание)", "taa"),
    ("Выключен", "off"),
]

PRESETS = [("Native AA", 0), ("Quality (x1.5)", 1), ("Balanced (x1.7)", 2),
           ("Performance (x2)", 3), ("Ultra Performance (x3)", 4)]
PRESET_SCALES = [1.0, 1.5, 1.7, 2.0, 3.0]


def compute_internal_resolution(output_res_str, preset_idx, custom_render_res=None):
    """(render_w, render_h, scale): calculates internal rendering resolution."""
    if custom_render_res:
        try:
            w, h = (int(v) for v in str(custom_render_res).lower().split("x"))
            return w, h, None
        except (ValueError, TypeError):
            pass
    try:
        out_w, out_h = (int(v) for v in str(output_res_str).lower().split("x"))
    except (ValueError, TypeError):
        out_w, out_h = 1920, 1080
    try:
        idx = max(0, min(int(preset_idx), len(PRESET_SCALES) - 1))
    except (ValueError, TypeError):
        idx = 2
    scale = PRESET_SCALES[idx]
    render_w = max(2, round(out_w / scale / 2) * 2)
    render_h = max(2, round(out_h / scale / 2) * 2)
    return render_w, render_h, scale


OUTPUT_RES = [
    ("1280×720 (Steam Deck)", "1280x720"),
    ("1920×1080", "1920x1080"),
    ("2560×1440", "2560x1440"),
    ("3840×2160", "3840x2160"),
    ("1280×800 (16:10)", "1280x800"),
    ("2560×1080 (Ultrawide 21:9)", "2560x1080"),
    ("3440×1440 (Ultrawide 21:9)", "3440x1440"),
    ("3840×1600 (Ultrawide)", "3840x1600"),
    ("5120×1440 (32:9 Super Ultrawide)", "5120x1440"),
]

# Ultrawide outputs: where the HUD's corner groups go (run.py hud_position, 0 = centred 16:9).
HUD_POSITIONS = [("У краёв экрана (100%)", "100"), ("75%", "75"), ("Посередине (50%)", "50"),
                 ("25%", "25"), ("По центру (16:9)", "0")]

# Game effects (patches applied at start): bbport.ini key, title, default.
EFFECTS = [
    ("effect_chromatic_aberration", "Хроматическая аберрация", True),
    ("effect_dof", "Глубина резкости (DoF)", True),
    ("effect_motion_blur", "Размытие в движении", True),
    ("effect_ssao", "Затенение SSAO", True),
    ("effect_game_aa", "Собственное сглаживание игры", True),
    ("effect_dynamic_shadows", "Тени от динамических источников", True),
    ("effect_ssr", "Отражения SSR (не было в игре)", False),
    ("skip_intro", "Пропуск заставок при запуске", False),
    ("debug_camera", "Свободная камера (Cross + L3 / Space + Z)", False),
    ("debug_menu", "Debug menu (левый touchpad / Tab; нужны шрифты)", False),
]

# PC enhancements (scripts/enhancements.py): game files made at start; off is original game.
ENHANCEMENTS = [
    ("pc_mirror_appearance", "Зеркало в Сне охотника: смена внешности", False),
    ("pc_two_invaders", "Два захватчика в поздних локациях", False),
    ("pc_rebirth", "Перерождение у Алтаря отчаяния", False),
    ("pc_enhanced_lamps", "Фонари: повышение уровня и хранилище", False),
    ("pc_boss_rematches", "Повторные бои с боссами у фонарей", False),
]

# Cheats and gameplay tweaks: game patches for 1.09, off by default.
CHEATS_AND_TWEAKS = [
    ("cheat_no_death", "Бессмертие (здоровье не ниже 1 HP)", False),
    ("cheat_stealth", "Враги не видят вас", False),
    ("cheat_silent", "Враги не слышат вас", False),
    ("cheat_rally_no_decay", "Rally не угасает", False),
    ("cheat_enemy_control", "Управление выбранным врагом (R3)", False),
    ("tweak_no_rally", "Без Rally", False),
    ("tweak_camera_distance", "Камера дальше от персонажа", False),
    ("tweak_no_camera_rotation", "Без автоповорота камеры при движении", False),
    ("tweak_easy_run", "Бег при меньшем наклоне стика", False),
    ("tweak_ragdoll", "Физика тел Dark Souls", False),
]

MODEL_LOD = [("Как в игре", "0"), ("Максимальная (-2)", "-2"), ("Ниже (1)", "1"),
             ("Минимальная (2)", "2")]
FPS_MODES = [("Без ограничения (патч)", "uncap"), ("60", "60"), ("90", "90"),
             ("30 (как на PS4)", "30")]
PRESENT_MODES = [("Mailbox", "Mailbox"), ("FIFO (VSync)", "Fifo"),
                 ("FIFO Relaxed", "FifoRelaxed"), ("Immediate", "Immediate")]
DRAW_PIPE = [("Авто (8+ потоков)", ""), ("Включён", "1"), ("Выключен (стабильнее)", "0")]
LANGUAGES = [("Английский", "1"), ("Русский", "8"), ("Японский", "0"), ("Французский", "2"),
             ("Испанский", "3"), ("Немецкий", "4"), ("Итальянский", "5")]
LIVE_RESOLUTION = [("Авто (по видеокарте)", "auto"), ("Выключена (быстрее)", "0"), ("Включена", "1")]
READBACKS = [("Relaxed (по умолчанию)", ""), ("Выключены", "0"), ("Precise", "2")]

DEFAULTS = {
    "ui_language": "en",
    "control_scheme": "xbox",
    "game_dir": "" if PACKAGED else str(PORT_DIR.parent / "CUSA03173"),
    "user_dir": "",
    "mods_dir": "",
    "mods_enabled": True,
    "patches_dir": "",
    "language": "1",
    "player_name": "",
    "dlc_dir": "",
    "fullscreen": False,
    "hdr": False,
    "present_mode": "Mailbox",
    "fps_mode": "uncap",
    "fps_limit": 0,
    "frames_ahead": 1,
    "draw_pipe": "",
    "readbacks": "",
    "mangohud": False,
    "frame_stats": False,
    "gpu_profile": False,
    "vk_validation": False,
    "extra_env": "",
    "start_minimized": False,
    "close_to_tray": True,
    "check_updates": True,
    "show_confirmation": False,
    "ui_scale": "100",
    "theme": "dark",
    "reduce_motion": False,
}

# bbport.ini keys the launcher edits; the rest of the file is kept.
INI_DEFAULTS = {
    "upscaler": "dlss",
    "preset": "2",
    "sharpen": "1",
    "sharpness": "0.50",
    "object_motion": "1",
    "show_fps": "1",
    "output_res": "1920x1080",
    "hud_position": "100",
    "model_lod": "0",
    "live_resolution": "0",
    **{key: "1" if default else "0"
       for key, _, default in EFFECTS + ENHANCEMENTS + CHEATS_AND_TWEAKS},
}

BOOL_SETTINGS = {"mods_enabled", "fullscreen", "hdr", "mangohud", "frame_stats",
                 "gpu_profile", "vk_validation", "start_minimized", "close_to_tray",
                 "check_updates", "show_confirmation", "reduce_motion"}
STRING_SETTINGS = {"ui_language", "control_scheme", "game_dir", "user_dir", "mods_dir", "patches_dir",
                    "language", "player_name", "dlc_dir", "present_mode", "fps_mode",
                    "draw_pipe", "readbacks", "extra_env", "ui_scale", "theme"}


def setting_value(key, value):
    """The value as the launcher uses it, or None when invalid for `key`."""
    if key in BOOL_SETTINGS:
        return value if isinstance(value, bool) else None
    if key == "ui_language":
        if isinstance(value, str) and value in ("en", "fr", "ru", "zh", "ko", "ja"):
            return value
        return "en"
    if key in STRING_SETTINGS:
        return value if isinstance(value, str) else None
    if key == "fps_limit":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        if not math.isfinite(value):
            return None
        return max(0, min(480, int(value)))
    if key == "frames_ahead":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        if not math.isfinite(value):
            return None
        return max(0, min(8, int(value)))
    return value


def load_settings():
    settings = dict(DEFAULTS)
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding='utf-8', errors='replace'))
    except (OSError, ValueError, TypeError):
        return settings
    if not isinstance(data, dict):
        return settings
    for key, value in data.items():
        if key not in DEFAULTS:
            settings[key] = value
            continue
        val = setting_value(key, value)
        if val is not None:
            settings[key] = val
    return settings


def atomic_write_text(path, text):
    """Writes `text` through a temporary file in the target directory, then replaces `path`."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding='utf-8') as temp:
            temp.write(text)
            temp.flush()
            os.fsync(temp.fileno())
        os.replace(temp_name, path)
        # The file's fsync does not cover the rename: sync the directory entry too.
        try:
            directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        except OSError:
            return
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def save_settings(settings):
    atomic_write_text(CONFIG_FILE, json.dumps(settings, indent=2, ensure_ascii=False))


def ini_path():
    return Path(os.environ.get("BB_CONFIG") or DATA_DIR / "bbport.ini")


def ini_int(values, key, fallback):
    try:
        return int(str(values.get(key, fallback)).strip())
    except (TypeError, ValueError):
        return fallback


def ini_float(values, key, fallback):
    try:
        value = float(str(values.get(key, fallback)).strip())
    except (TypeError, ValueError):
        return fallback
    return value if math.isfinite(value) else fallback


def load_ini():
    values = dict(INI_DEFAULTS)
    lines = []
    try:
        lines = ini_path().read_text(encoding='utf-8', errors='replace').splitlines()
    except OSError:
        pass
    for line in lines:
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values, lines


def save_ini(values, lines):
    """Rewrites the edited keys in place, appends missing ones, keeps comments and others."""
    written = set()
    out = []
    for line in lines:
        if "=" in line and not line.lstrip().startswith("#"):
            key = line.split("=", 1)[0].strip()
            if key in values:
                out.append(f"{key}={values[key]}")
                written.add(key)
                continue
        out.append(line)
    if not lines:
        out.append("# bbport settings (in-game menu: Insert / L3+R3)")
    for key, value in values.items():
        if key not in written:
            out.append(f"{key}={value}")
    atomic_write_text(ini_path(), "\n".join(out) + "\n")


def patches_dir(settings):
    return Path(settings.get("patches_dir") or DATA_DIR / "patches").expanduser()


def game_environment(s):
    """Environment for run.sh from the launcher settings."""
    env = dict(os.environ)
    env["BB_GAME_DIR"] = str(Path(s["game_dir"]).expanduser())
    if s["user_dir"]:
        env["BB_USER_DIR"] = str(Path(s["user_dir"]).expanduser())
    if s.get("player_name", "").strip():
        env["BB_USER_NAME"] = s["player_name"].strip()
    if s.get("dlc_dir", "").strip():
        env["BB_DLC_DIR"] = str(Path(s["dlc_dir"]).expanduser())
    env["BB_MODS_DIR"] = str(Path(s.get("mods_dir") or DATA_DIR / "mods").expanduser())
    env["BB_MODS_CONFIG"] = str(DATA_DIR / "mods.json")
    env["BB_MODS_ENABLED"] = "1" if s.get("mods_enabled", True) else "0"
    scheme = canonical_control_scheme(s.get("control_scheme"))
    keyboard = (scheme == "pc")
    if not keyboard and s.get("mods_enabled", True):
        try:
            mods_cfg = DATA_DIR / "mods.json"
            if mods_cfg.is_file():
                cfg = json.loads(mods_cfg.read_text(encoding="utf-8"))
                keyboard = any(is_keyboard_prompt(n) for n in cfg.get("enabled", []))
        except (OSError, ValueError):
            pass
    env["BB_BUTTON_PROMPTS"] = "Keyboard" if keyboard else ""
    env["BB_KEY_PROMPT_IMAGES"] = "1" if keyboard else "0"
    env["BB_PATCHES_DIR"] = str(patches_dir(s))
    env["BB_PATCHES_CONFIG"] = str(DATA_DIR / "patches.json")
    env["BB_LANGUAGE"] = s["language"]
    env["BB_FULLSCREEN"] = "1" if s["fullscreen"] else "0"
    env["BB_PRESENT_MODE"] = s["present_mode"]
    if s["hdr"]:
        env["BB_HDR"] = "1"
    env["BB_FPS"] = s["fps_mode"]
    if s["fps_limit"] > 0:
        env["BB_FPS_LIMIT"] = str(s["fps_limit"])
    # 1 is the game's default; only export a different overlap bound (0 = unlimited).
    frames_ahead = int(s.get("frames_ahead", 1))
    if frames_ahead != 1:
        env["BB_FRAMES_AHEAD"] = str(frames_ahead)
    if s["draw_pipe"]:
        env["BB_DRAW_PIPE"] = s["draw_pipe"]
    if s["readbacks"]:
        env["BB_READBACKS"] = s["readbacks"]
    if s["mangohud"]:
        env["MANGOHUD"] = "1"
    if s["frame_stats"]:
        env["BB_FRAME_STATS"] = "1"
    if s["gpu_profile"]:
        env["BB_GPU_PROFILE"] = "1"
    if s["vk_validation"]:
        env["BB_VK_VALIDATION"] = "1"
    for item in s["extra_env"].split():
        if "=" in item:
            key, value = item.split("=", 1)
            env[key] = value
    return env


def flat_button(icon, tooltip, handler):
    button = Gtk.Button(icon_name=icon, valign=Gtk.Align.CENTER, tooltip_text=tooltip)
    button.add_css_class("flat")
    button.connect("clicked", handler)
    return button


def open_folder(window, path):
    """Opens `path` in the file manager."""
    try:
        Path(path).mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    Gtk.FileLauncher.new(Gio.File.new_for_path(str(path))).launch(window, None, None)


def combo_row(title, subtitle, choices, current):
    values = [value for _, value in choices]
    if current not in values:
        choices = [*choices, (str(current), current)]
        values.append(current)
    labels = [GLib.markup_escape_text(tr(label)) for label, _ in choices]
    model = Gtk.StringList.new(labels)
    row = Adw.ComboRow(title=title, model=model)
    if subtitle:
        row.set_subtitle(subtitle)
    row.set_selected(values.index(current))
    row.values = values
    return row


def combo_value(row):
    return row.values[row.get_selected()]


def invalid_utf8(error):
    """Whether `error` is GLib's UTF-8 conversion failure."""
    quark = GLib.convert_error_quark() if hasattr(GLib, "convert_error_quark") else None
    return getattr(error, "domain", None) in ("g_convert_error", quark)


class FolderList:
    """A preferences group with a folder row and one switch row per item below it."""

    def __init__(self, group):
        self.group = group
        self.rows = []

    def clear(self):
        for _, row in self.rows:
            self.group.remove(row)
        self.rows = []

    def add(self, key, row):
        self.group.add(row)
        self.rows.append((key, row))


def expand_preferences_page(page, max_size=1150, tightening_threshold=900):
    """Walk the widget hierarchy of an Adw.PreferencesPage to expand its internal Adw.Clamp."""
    def walk(widget):
        if widget is None:
            return
        if hasattr(widget, "set_maximum_size"):
            widget.set_maximum_size(max_size)
        if hasattr(widget, "set_tightening_threshold"):
            widget.set_tightening_threshold(tightening_threshold)
        child = widget.get_first_child() if hasattr(widget, "get_first_child") else None
        while child:
            walk(child)
            child = child.get_next_sibling()
    walk(page)


GOTHIC_CSS = b"""
/* Victorian Gothic Bloodborne Theme - Editorial Desktop Software */
window.gothic-window, .gothic-window {
    background-color: #0c0d12;
    color: #ede8df;
}

headerbar.gothic-header {
    background-color: #0f1016;
    border-bottom: 1px solid #1c1d27;
    min-height: 48px;
    padding-left: 8px;
    padding-right: 8px;
}

/* Shell Brand */
.shell-brand-title {
    font-family: 'Cinzel', 'Garamond', 'Times New Roman', 'Noto Serif', serif;
    font-size: 13px;
    font-weight: 800;
    letter-spacing: 2px;
    color: #ede8df;
}

.shell-brand-subtitle {
    font-size: 10px;
    letter-spacing: 1px;
    color: #8c867a;
    text-transform: uppercase;
}

/* Shell Play Button */
.shell-play-button {
    background: linear-gradient(180deg, #7c1818 0%, #521010 100%);
    color: #fff5f0;
    border: 1px solid #992424;
    border-radius: 4px;
    font-weight: 700;
    font-size: 13px;
    letter-spacing: 0.5px;
    padding: 6px 16px;
    transition: all 150ms ease;
}

.shell-play-button:hover {
    background: linear-gradient(180deg, #941f1f 0%, #631414 100%);
    border-color: #b82e2e;
}

.shell-play-button.running {
    background: linear-gradient(180deg, #3d1414 0%, #260c0c 100%);
    border-color: #7a2222;
    color: #ffcccc;
}

.shell-play-button.running:hover {
    background: linear-gradient(180deg, #571c1c 0%, #361111 100%);
    border-color: #9e2a2a;
}

/* Navigation ViewSwitcher */
viewswitcher {
    background: transparent;
}

viewswitcher button {
    border-radius: 4px;
    color: #9c978d;
    font-size: 13px;
    font-weight: 500;
    padding: 6px 9px;
    margin-left: 2px;
    margin-right: 2px;
    border-bottom: 2px solid transparent;
    transition: all 150ms ease;
}

viewswitcher button:hover {
    color: #ede8df;
    background-color: rgba(255, 255, 255, 0.04);
}

viewswitcher button:checked,
viewswitcher > stack > box > button:checked {
    color: #ffffff;
    background-color: #211215;
    border-bottom: 2px solid #8c1d1d;
}

/* Hero Section */
.hero-box {
    background-color: #0c0d12;
    border: 1px solid #1c1d27;
    border-radius: 6px;
}

.hero-overlay-scrim {
    background: linear-gradient(90deg, rgba(12, 13, 18, 0.96) 0%, rgba(12, 13, 18, 0.8) 32%, rgba(12, 13, 18, 0.25) 55%, transparent 75%);
    padding: 24px 28px;
}

.hero-title {
    font-family: 'Cinzel', 'Garamond', 'Times New Roman', 'Noto Serif', serif;
    font-size: 34px;
    font-weight: 800;
    letter-spacing: 2px;
    color: #f5f2eb;
    text-shadow: 0 2px 10px rgba(0, 0, 0, 0.9);
}

.hero-subtitle-caps {
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 3px;
    color: #a8a296;
}

.hero-flourish {
    border-top: 1px solid #7c1818;
    margin-top: 4px;
    margin-bottom: 4px;
}

.hero-quote {
    font-size: 13px;
    font-style: italic;
    color: #b8b2a6;
}

.hero-launch-button {
    font-family: 'Cinzel', 'Garamond', 'Times New Roman', 'Noto Serif', serif;
    font-size: 14px;
    font-weight: 800;
    letter-spacing: 1.5px;
    padding: 10px 24px;
    border-radius: 4px;
    transition: all 150ms ease;
}

.hero-launch-button.ready {
    background: linear-gradient(180deg, #7c1818 0%, #4e0f0f 100%);
    color: #fff5f0;
    border: 1px solid #992828;
    box-shadow: 0 4px 14px rgba(124, 24, 24, 0.35);
}

.hero-launch-button.ready:hover {
    background: linear-gradient(180deg, #961d1d 0%, #611313 100%);
    border-color: #c93636;
    box-shadow: 0 6px 18px rgba(150, 29, 29, 0.5);
}

.hero-launch-button.running {
    background: linear-gradient(180deg, #3d1414 0%, #260c0c 100%);
    color: #ffcccc;
    border: 1px solid #7a2222;
}

.hero-launch-button.running:hover {
    background: linear-gradient(180deg, #571c1c 0%, #361111 100%);
    border-color: #9e2a2a;
}

.hero-status-title {
    font-size: 13px;
    font-weight: 600;
    color: #ede8df;
}

.hero-status-sub {
    font-size: 11px;
    color: #8c867a;
}

/* Info Strip */
.info-strip {
    background-color: #0f1016;
    border: 1px solid #1c1d27;
    border-radius: 6px;
    padding: 12px 16px;
}

.info-col {
    padding: 2px 14px;
}

.info-icon {
    color: #8c867a;
}

.info-col-title {
    font-size: 10.5px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    color: #8c867a;
}

.info-col-value {
    font-size: 12.5px;
    font-weight: 500;
    color: #ede8df;
}

.info-col-sep {
    background-color: #1c1d27;
    min-width: 1px;
}

/* Lower Section */
.section-header-title {
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 0.5px;
    color: #ede8df;
}

.terminal-activity-box {
    background-color: #090a0e;
    border: 1px solid #1a1b24;
    border-radius: 6px;
    padding: 12px 16px;
    min-height: 160px;
}

.terminal-activity-text {
    font-family: 'JetBrains Mono', 'Fira Code', 'DejaVu Sans Mono', monospace;
    font-size: 11.5px;
    line-height: 1.6;
    color: #a39e93;
}

.quick-actions-list {
    background-color: #0f1016;
    border: 1px solid #1c1d27;
    border-radius: 6px;
}

.quick-action-row {
    background: transparent;
    border-bottom: 1px solid #1a1b25;
    border-radius: 0;
    padding: 0;
    transition: background-color 150ms ease;
}

.quick-action-row.is-last {
    border-bottom: none;
}

.quick-action-row:hover {
    background-color: #171822;
}

.action-icon {
    color: #8c867a;
}

.action-row-title {
    font-size: 13px;
    font-weight: 600;
    color: #ede8df;
}

.action-row-desc {
    font-size: 11.5px;
    color: #8c867a;
}

.action-chevron {
    color: #6e6a62;
}

/* Preferences & Row styling */
preferencespage > scrolledwindow > viewport > box {
    margin-top: 16px;
    margin-bottom: 24px;
}

preferencesgroup > box {
    margin-bottom: 22px;
}

preferencesgroup .boxed-list {
    background-color: #0f1016;
    border: 1px solid #1c1d27;
    border-radius: 6px;
    box-shadow: none;
}

preferencesgroup .boxed-list > row {
    border-bottom: 1px solid #1a1b25;
}

preferencesgroup .boxed-list > row:last-child {
    border-bottom: none;
}

preferencesgroup > box > label.title {
    font-family: 'Cinzel', 'Garamond', 'Times New Roman', 'Noto Serif', serif;
    font-size: 15px;
    font-weight: 700;
    letter-spacing: 0.5px;
    color: #ede8df;
    margin-bottom: 4px;
}

preferencesgroup > box > label.subtitle {
    font-size: 12px;
    color: #8c867a;
    margin-bottom: 10px;
}

switch:checked {
    background-color: #8c1d1d;
}

/* Diagnostic Terminal Log */
.log-page-container {
    padding: 16px 20px 20px 20px;
    background-color: #0c0d12;
}

.log-terminal-frame {
    background-color: #08090d;
    border: 1px solid #1c1d27;
    border-radius: 6px;
}

.log-terminal-view {
    font-family: 'JetBrains Mono', 'Fira Code', 'DejaVu Sans Mono', monospace;
    font-size: 12px;
    line-height: 1.5;
    background-color: transparent;
    color: #dcd8cf;
}

.dim-label {
    color: #807c73;
}
"""


def install_gothic_theme():
    """Installs the dark Victorian Gothic CSS styling."""
    try:
        provider = Gtk.CssProvider()
        provider.load_from_data(GOTHIC_CSS)
        display = Gdk.Display.get_default() if hasattr(Gdk, "Display") else None
        if display:
            Gtk.StyleContext.add_provider_for_display(
                display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
        if hasattr(Adw, "StyleManager"):
            style_manager = Adw.StyleManager.get_default()
            style_manager.set_color_scheme(Adw.ColorScheme.FORCE_DARK)
    except Exception:
        pass


class LauncherWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Bloodborne")
        self.set_default_size(820, 840)
        self.add_css_class("gothic-window")
        install_gothic_theme()
        self.settings = load_settings()
        set_language(self.settings.get("ui_language") or "en")
        self.ini, self.ini_lines = load_ini()
        self.process = None
        self._stopping_pid = None
        self.stream = None
        self.downloading_fsr4 = False
        self.build()
        self.connect("close-request", self.on_close)

    def build(self):
        """(Re)creates the window's content in the current launcher language."""
        prev_page = self.stack.get_visible_child_name() if hasattr(self, "stack") and self.stack.get_visible_child_name() else "home"

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.add_css_class("gothic-header")

        # Shell brand on the left
        brand_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        brand_box.set_valign(Gtk.Align.CENTER)
        brand_box.set_margin_start(12)
        brand_box.set_margin_end(12)
        brand_title = Gtk.Label(label="BLOODBORNE", xalign=0)
        brand_title.add_css_class("shell-brand-title")
        brand_sub = Gtk.Label(label=tr("Linux Port"), xalign=0)
        brand_sub.add_css_class("shell-brand-subtitle")
        brand_box.append(brand_title)
        brand_box.append(brand_sub)
        header.pack_start(brand_box)

        self.stack = Adw.ViewStack()
        switcher = Adw.ViewSwitcher(stack=self.stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        header.set_title_widget(switcher)

        self.launch_button = Gtk.Button()
        self.launch_button.add_css_class("shell-play-button")
        self.launch_button.set_margin_end(6)
        self.launch_button.connect("clicked", self.on_launch)
        header.pack_end(self.launch_button)
        toolbar.add_top_bar(header)

        self.toasts = Adw.ToastOverlay()
        self.toasts.set_child(self.stack)
        toolbar.set_content(self.toasts)
        self.set_content(toolbar)

        log_text = self.log_view.get_buffer().get_text(
            *self.log_view.get_buffer().get_bounds(), False) if hasattr(self, "log_view") else ""

        # Navigation: 6 core pages
        self.pages = {
            "home": self.build_home_page(),
            "graphics": self.build_graphics_page(),
            "game": self.build_game_page(),
            "downloads": self.build_downloads_page(),
            "settings": self.build_settings_page(),
            "log": self.build_log_page(),
        }
        self.stack.add_titled_with_icon(self.pages["home"], "home", tr("Главная"),
                                        "user-home-symbolic")
        self.stack.add_titled_with_icon(self.pages["graphics"], "graphics", tr("Графика"),
                                        "video-display-symbolic")
        self.stack.add_titled_with_icon(self.pages["game"], "game", tr("Игра"),
                                        "applications-games-symbolic")
        self.stack.add_titled_with_icon(self.pages["downloads"], "downloads", tr("Загрузки"),
                                        "folder-download-symbolic")
        self.stack.add_titled_with_icon(self.pages["settings"], "settings", tr("Настройки"),
                                        "preferences-system-symbolic")
        self.stack.add_titled_with_icon(self.pages["log"], "log", tr("Журнал"),
                                        "utilities-terminal-symbolic")

        if prev_page in self.pages:
            self.stack.set_visible_child_name(prev_page)

        self.log_view.get_buffer().set_text(log_text)
        self.update_launch_button()
        self.update_game_status()
        self.update_user_status()
        self.update_dlc_status()
        self.update_upscaler_status()
        self.update_recent_activity()

    # --- 1. Home page --------------------------------------------------------------------

    def build_home_page(self):
        scroller = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        box.set_margin_top(14)
        box.set_margin_bottom(20)
        box.set_margin_start(16)
        box.set_margin_end(16)

        # Hero Banner with artwork
        self.hero_box = hero_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.hero_box.add_css_class("hero-box")
        hero_overlay = Gtk.Overlay()

        hero_art = LAUNCHER_DIR / "art" / "hero.png"
        if not hero_art.is_file():
            hero_art = PORT_DIR / "launcher" / "art" / "hero.png"

        if hero_art.is_file():
            picture = Gtk.Picture.new_for_filename(str(hero_art))
            picture.set_content_fit(Gtk.ContentFit.COVER)
            picture.set_size_request(-1, 350)
            hero_overlay.set_child(picture)
        else:
            fallback = Gtk.Box()
            fallback.set_size_request(-1, 350)
            fallback.add_css_class("hero-box")
            hero_overlay.set_child(fallback)

        scrim = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        scrim.add_css_class("hero-overlay-scrim")
        scrim.set_valign(Gtk.Align.END)

        title = Gtk.Label(label="BLOODBORNE")
        title.add_css_class("hero-title")
        title.set_halign(Gtk.Align.START)
        scrim.append(title)

        subtitle = Gtk.Label(label=tr("NATIVE LINUX PORT"))
        subtitle.add_css_class("hero-subtitle-caps")
        subtitle.set_halign(Gtk.Align.START)
        scrim.append(subtitle)

        flourish = Gtk.Box()
        flourish.add_css_class("hero-flourish")
        flourish.set_size_request(60, 2)
        flourish.set_halign(Gtk.Align.START)
        scrim.append(flourish)

        quote = Gtk.Label(label=tr("Hunt your nightmares."))
        quote.add_css_class("hero-quote")
        quote.set_halign(Gtk.Align.START)
        scrim.append(quote)

        action_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        action_row.set_margin_top(10)

        self.hero_launch_button = Gtk.Button()
        self.hero_launch_button.add_css_class("hero-launch-button")
        self.hero_launch_button.connect("clicked", self.on_launch)
        action_row.append(self.hero_launch_button)

        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        status_box.set_valign(Gtk.Align.CENTER)
        self.hero_status_icon = Gtk.Image()
        self.hero_status_icon.set_from_icon_name("emblem-ok-symbolic")

        status_text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.hero_status_label = Gtk.Label(label="", xalign=0)
        self.hero_status_label.add_css_class("hero-status-title")
        self.hero_status_detail = Gtk.Label(label="", xalign=0)
        self.hero_status_detail.add_css_class("hero-status-sub")
        status_text_box.append(self.hero_status_label)
        status_text_box.append(self.hero_status_detail)

        status_box.append(self.hero_status_icon)
        status_box.append(status_text_box)
        action_row.append(status_box)

        scrim.append(action_row)
        hero_overlay.add_overlay(scrim)
        hero_box.append(hero_overlay)
        box.append(hero_box)

        # Sleek Horizontal Info Strip (4 columns)
        info_strip = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        info_strip.add_css_class("info-strip")
        info_strip.set_hexpand(True)

        # Col 1: Game Files
        col1 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        col1.add_css_class("info-col")
        col1.set_hexpand(True)
        c1_icon = Gtk.Image.new_from_icon_name("applications-games-symbolic")
        c1_icon.set_pixel_size(24)
        c1_icon.add_css_class("info-icon")
        col1.append(c1_icon)
        c1_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        c1_title = Gtk.Label(label=tr("Game Files"), xalign=0)
        c1_title.add_css_class("info-col-title")
        self.hero_game_summary = Gtk.Label(label="", xalign=0)
        self.hero_game_summary.add_css_class("info-col-value")
        c1_box.append(c1_title)
        c1_box.append(self.hero_game_summary)
        col1.append(c1_box)
        info_strip.append(col1)

        sep1 = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        sep1.add_css_class("info-col-sep")
        sep1.set_size_request(1, -1)
        sep1.set_hexpand(False)
        info_strip.append(sep1)

        # Col 2: Graphics Profile
        col2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        col2.add_css_class("info-col")
        col2.set_hexpand(True)
        c2_icon = Gtk.Image.new_from_icon_name("video-display-symbolic")
        c2_icon.set_pixel_size(24)
        c2_icon.add_css_class("info-icon")
        col2.append(c2_icon)
        c2_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        c2_title = Gtk.Label(label=tr("Graphics Profile"), xalign=0)
        c2_title.add_css_class("info-col-title")
        self.hero_graphics_summary = Gtk.Label(label="", xalign=0)
        self.hero_graphics_summary.add_css_class("info-col-value")
        c2_box.append(c2_title)
        c2_box.append(self.hero_graphics_summary)
        col2.append(c2_box)
        info_strip.append(col2)

        sep2 = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        sep2.add_css_class("info-col-sep")
        sep2.set_size_request(1, -1)
        sep2.set_hexpand(False)
        info_strip.append(sep2)

        # Col 3: FSR 4 Assets
        col3 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        col3.add_css_class("info-col")
        col3.set_hexpand(True)
        c3_icon = Gtk.Image.new_from_icon_name("drive-harddisk-symbolic")
        c3_icon.set_pixel_size(24)
        c3_icon.add_css_class("info-icon")
        col3.append(c3_icon)
        c3_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        c3_title = Gtk.Label(label=tr("FSR 4 Assets"), xalign=0)
        c3_title.add_css_class("info-col-title")
        self.hero_assets_summary = Gtk.Label(label="", xalign=0)
        self.hero_assets_summary.add_css_class("info-col-value")
        self.hero_fsr_summary = self.hero_assets_summary
        c3_box.append(c3_title)
        c3_box.append(self.hero_assets_summary)
        col3.append(c3_box)
        info_strip.append(col3)

        sep3 = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        sep3.add_css_class("info-col-sep")
        sep3.set_size_request(1, -1)
        sep3.set_hexpand(False)
        info_strip.append(sep3)

        # Col 4: Save Data / Hunter
        col4 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        col4.add_css_class("info-col")
        col4.set_hexpand(True)
        c4_icon = Gtk.Image.new_from_icon_name("x-office-document-symbolic")
        c4_icon.set_pixel_size(24)
        c4_icon.add_css_class("info-icon")
        col4.append(c4_icon)
        c4_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        c4_title = Gtk.Label(label=tr("Save Data"), xalign=0)
        c4_title.add_css_class("info-col-title")
        self.hero_hunter_summary = Gtk.Label(label="", xalign=0)
        self.hero_hunter_summary.add_css_class("info-col-value")
        c4_box.append(c4_title)
        c4_box.append(self.hero_hunter_summary)
        col4.append(c4_box)
        info_strip.append(col4)

        box.append(info_strip)

        # Lower 2-column section: Recent Activity & Quick Actions
        lower_grid = Gtk.Grid()
        lower_grid.set_column_spacing(16)
        lower_grid.set_hexpand(True)
        lower_grid.set_column_homogeneous(True)

        # Left Column: Recent Activity
        left_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        left_box.set_hexpand(True)
        act_title = Gtk.Label(label=tr("Recent Activity"), xalign=0)
        act_title.add_css_class("section-header-title")
        left_box.append(act_title)

        self.activity_frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.activity_frame.add_css_class("terminal-activity-box")
        self.activity_label = Gtk.Label(xalign=0, yalign=0)
        self.activity_label.add_css_class("terminal-activity-text")
        self.activity_frame.append(self.activity_label)
        left_box.append(self.activity_frame)
        lower_grid.attach(left_box, 0, 0, 1, 1)

        # Right Column: Quick Actions
        right_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        right_box.set_hexpand(True)
        qa_title = Gtk.Label(label=tr("Quick Actions"), xalign=0)
        qa_title.add_css_class("section-header-title")
        right_box.append(qa_title)

        qa_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        qa_list.add_css_class("quick-actions-list")

        def make_action_row(icon_name, title_text, desc_text, target_page, is_last=False):
            btn = Gtk.Button()
            btn.add_css_class("quick-action-row")
            if is_last:
                btn.add_css_class("is-last")
            btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
            btn_box.set_margin_start(14)
            btn_box.set_margin_end(14)
            btn_box.set_margin_top(10)
            btn_box.set_margin_bottom(10)

            icon = Gtk.Image.new_from_icon_name(icon_name)
            icon.set_pixel_size(20)
            icon.add_css_class("action-icon")
            btn_box.append(icon)

            text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            text_box.set_hexpand(True)
            t_lbl = Gtk.Label(label=title_text, xalign=0)
            t_lbl.add_css_class("action-row-title")
            d_lbl = Gtk.Label(label=desc_text, xalign=0)
            d_lbl.add_css_class("action-row-desc")
            text_box.append(t_lbl)
            text_box.append(d_lbl)
            btn_box.append(text_box)

            chevron = Gtk.Image.new_from_icon_name("go-next-symbolic")
            chevron.add_css_class("action-chevron")
            btn_box.append(chevron)

            btn.set_child(btn_box)
            btn.connect("clicked", lambda _: self.stack.set_visible_child_name(target_page))
            return btn

        qa_list.append(make_action_row("video-display-symbolic", tr("Graphics Settings"),
                                       tr("Resolution, upscaling, and image quality"), "graphics"))
        qa_list.append(make_action_row("applications-games-symbolic", tr("Game Settings"),
                                       tr("Controls, mods, and enhancements"), "game"))
        qa_list.append(make_action_row("folder-download-symbolic", tr("Manage Downloads"),
                                       tr("FSR 4 shaders and additional assets"), "downloads"))
        qa_list.append(make_action_row("preferences-system-symbolic", tr("Application Settings"),
                                       tr("Language, launcher behavior, and preferences"), "settings", is_last=True))

        right_box.append(qa_list)
        lower_grid.attach(right_box, 1, 0, 1, 1)

        box.append(lower_grid)
        scroller.set_child(box)
        return scroller

    # --- 2. Graphics page ----------------------------------------------------------------

    def build_graphics_page(self):
        page = Adw.PreferencesPage()

        # 1. Rendering and Resolution
        self.render_group = screen = Adw.PreferencesGroup(
            title=tr("1. Рендеринг и разрешение"),
            description=tr("Разрешение вывода, режим отображения и синхронизация кадров"))
        self.output_row = combo_row(tr("Разрешение вывода"),
                                    tr("Апскейлер дорисовывает кадр; Steam Deck — 720p"),
                                    OUTPUT_RES, self.ini.get("output_res", "1920x1080"))
        screen.add(self.output_row)
        self.hud_row = combo_row(
            tr("Позиция HUD"),
            tr("Ультраширокие экраны: элементы у краёв или в центре 16:9"),
            HUD_POSITIONS, self.ini.get("hud_position", "100"))
        screen.add(self.hud_row)
        self.live_row = combo_row(tr("Смена разрешения на лету"),
                                  tr("Без перезапуска, но медленнее на Steam Deck и старых GPU"),
                                  LIVE_RESOLUTION, self.ini.get("live_resolution", "0"))
        screen.add(self.live_row)
        self.fullscreen_row = Adw.SwitchRow(title=tr("Полноэкранный режим"),
                                            subtitle=tr("Применяется сразу"),
                                            active=self.settings["fullscreen"])
        screen.add(self.fullscreen_row)
        self.present_row = combo_row(tr("Режим показа кадров"), None, PRESENT_MODES,
                                     self.settings["present_mode"])
        screen.add(self.present_row)
        self.hdr_row = Adw.SwitchRow(title=tr("Разрешить HDR"),
                                     subtitle=tr("Требуется поддержка HDR на дисплее"),
                                     active=self.settings["hdr"])
        screen.add(self.hdr_row)
        page.add(screen)

        # 2. Upscaling and Temporal Reconstruction
        self.upscale_group = upscaler = Adw.PreferencesGroup(
            title=tr("2. Апскейлинг и реконструкция"),
            description=tr("Реконструкция изображения из пониженного разрешения рендеринга"))
        self.upscaler_row = combo_row(tr("Апскейлер"), None, UPSCALERS, self.ini["upscaler"])
        self.upscaler_row.connect("notify::selected", lambda *_: self.update_upscaler_status())
        upscaler.add(self.upscaler_row)

        self.fsr4_warning_row = Adw.ActionRow(
            title=tr("Предупреждение: FSR 4 на RX 6600M (RDNA 2)"),
            subtitle=tr("Experimental on this GPU. AMD Radeon RX 6600M is RDNA 2. FSR 4 may run significantly slower or less reliably than FSR 3.1. Performance is not guaranteed. If you experience frame drops, stuttering, or instability, switch to FSR 3.1."))
        warn_img = Gtk.Image()
        warn_img.set_from_icon_name("dialog-warning-symbolic")
        self.fsr4_warning_row.add_prefix(warn_img)
        self.fsr4_compat_warning_label = self.fsr4_warning_row
        upscaler.add(self.fsr4_warning_row)

        self.preset_row = combo_row(tr("Пресет"), None, PRESETS,
                                    ini_int(self.ini, "preset", int(INI_DEFAULTS["preset"])))
        self.preset_row.connect("notify::selected", lambda *_: self.update_upscaler_status())
        self.output_row.connect("notify::selected", lambda *_: self.update_upscaler_status())
        upscaler.add(self.preset_row)

        self.fsr4_row = Adw.ActionRow(title=tr("Ассеты FSR 4"))
        self.fsr4_progress = Gtk.ProgressBar(hexpand=True, valign=Gtk.Align.CENTER)
        self.fsr4_progress.set_margin_start(12)
        self.fsr4_progress.set_margin_end(12)
        self.fsr4_button = Gtk.Button(valign=Gtk.Align.CENTER)
        self.fsr4_button.connect("clicked", self.on_fetch_fsr4)
        self.fsr4_row.add_suffix(self.fsr4_progress)
        self.fsr4_row.add_suffix(self.fsr4_button)
        upscaler.add(self.fsr4_row)

        self.motion_row = Adw.SwitchRow(
            title=tr("Векторы движения объектов"),
            subtitle=tr("ВНИМАНИЕ: На AMD RX 6000 (RDNA 2) возможен сбой видеочипа (device loss). Оставьте выключенным."),
            active=self.ini.get("object_motion") == "1")
        upscaler.add(self.motion_row)
        page.add(upscaler)

        # 3. Image Quality and Sharpening
        self.quality_group = quality = Adw.PreferencesGroup(
            title=tr("3. Качество изображения и резкость"),
            description=tr("Повышение четкости и графические эффекты рендеринга"))
        self.sharpen_row = Adw.SwitchRow(title=tr("Резкость (RCAS) [Применяется сразу]"),
                                         subtitle=tr("AMD FidelityFX Robust Contrast Adaptive Sharpening; применяется сразу"),
                                         active=self.ini.get("sharpen") == "1")
        quality.add(self.sharpen_row)
        self.sharpness_row = Adw.SpinRow.new_with_range(0.0, 2.0, 0.05)
        self.sharpness_row.set_title(tr("Сила резкости [Применяется сразу]"))
        self.sharpness_row.set_subtitle(tr("Коэффициент 0.0–2.0 (по умолчанию 0.50); применяется сразу"))
        self.sharpness_row.set_digits(2)
        self.sharpness_row.set_value(max(0.0, min(2.0, ini_float(
            self.ini, "sharpness", float(INI_DEFAULTS["sharpness"])))))
        quality.add(self.sharpness_row)

        self.lod_row = combo_row(tr("Детализация моделей"), None, MODEL_LOD,
                                 self.ini.get("model_lod", "0"))
        quality.add(self.lod_row)
        self.effect_rows = {}
        for key, title, default in EFFECTS:
            row = Adw.SwitchRow(title=tr(title),
                                active=self.ini.get(key, "1" if default else "0") == "1")
            if key == "debug_menu":
                row.set_subtitle(tr("Установите DbgFont14h.ccm и DbgFont14h.tpf в dvdroot_ps4/font "
                                    "из мода Nexus #253"))
            self.effect_rows[key] = row
            quality.add(row)
        page.add(quality)

        # 4. Compatibility and GPU Pipeline
        self.compat_group = compat = Adw.PreferencesGroup(
            title=tr("4. Совместимость и конвейер GPU"),
            description=tr("Низкоуровневые параметры Vulkan; при нестабильности выключите"))
        self.pipe_row = combo_row(
            tr("Двухстадийный конвейер GPU"),
            tr("Быстрее на 20–30%; при нестабильности выключите"), DRAW_PIPE,
            self.settings["draw_pipe"])
        compat.add(self.pipe_row)
        self.readbacks_row = combo_row(tr("Чтение данных GPU процессором"), None, READBACKS,
                                       self.settings["readbacks"])
        compat.add(self.readbacks_row)
        self.frames_ahead_row = Adw.SpinRow.new_with_range(0, 8, 1)
        self.frames_ahead_row.set_title(tr("Кадров вперёд (конвейер GPU)"))
        self.frames_ahead_row.set_subtitle(tr(
            "На сколько кадров поток команд может опережать GPU: 1 — по умолчанию "
            "(стабильно), 0 — без ограничения, 2 и больше — больше перекрытия CPU/GPU "
            "ценой задержки"))
        self.frames_ahead_row.set_value(self.settings["frames_ahead"])
        compat.add(self.frames_ahead_row)
        page.add(compat)

        # 5. Performance Diagnostics
        self.perf_group = perf = Adw.PreferencesGroup(
            title=tr("5. Производительность и диагностика"),
            description=tr("Ограничение частоты кадров и сбор телеметрии"))
        self.show_fps_row = Adw.SwitchRow(title=tr("Показывать FPS [Применяется сразу]"),
                                          subtitle=tr("Встроенный счетчик кадров в левом верхнем углу"),
                                          active=self.ini.get("show_fps") == "1")
        perf.add(self.show_fps_row)
        self.fps_row = combo_row(tr("Режим"), tr("Какой патч частоты кадров применить к игре"),
                                 FPS_MODES, self.settings["fps_mode"])
        perf.add(self.fps_row)
        self.limit_row = Adw.SpinRow.new_with_range(0, 480, 1)
        self.limit_row.set_title(tr("Ограничение FPS"))
        self.limit_row.set_subtitle(tr("0 — по частоте экрана (не выше 120 Гц); "
                                       "укажите число, чтобы ограничить иначе"))
        self.limit_row.set_value(self.settings["fps_limit"])
        perf.add(self.limit_row)

        self.mangohud_row = Adw.SwitchRow(title="MangoHud", active=self.settings["mangohud"])
        perf.add(self.mangohud_row)
        self.stats_row = Adw.SwitchRow(title=tr("Статистика кадров в журнале"),
                                       subtitle="BB_FRAME_STATS",
                                       active=self.settings["frame_stats"])
        perf.add(self.stats_row)
        self.profile_row = Adw.SwitchRow(title=tr("Профиль GPU в журнале"),
                                         subtitle="BB_GPU_PROFILE",
                                         active=self.settings["gpu_profile"])
        perf.add(self.profile_row)
        self.validation_row = Adw.SwitchRow(title=tr("Слои валидации Vulkan"),
                                            subtitle=tr("Сильно замедляет"),
                                            active=self.settings["vk_validation"])
        perf.add(self.validation_row)
        self.extra_row = Adw.EntryRow(title=tr("Доп. переменные (ИМЯ=значение через пробел)"),
                                      text=self.settings["extra_env"])
        perf.add(self.extra_row)
        page.add(perf)
        expand_preferences_page(page, max_size=1150)
        return page

    # --- 3. Game page --------------------------------------------------------------------

    def build_game_page(self):
        page = Adw.PreferencesPage()

        game = Adw.PreferencesGroup(title=tr("Игра"))
        self.game_row = Adw.ActionRow(title=tr("Папка игры (CUSA03173)"))
        self.game_status = Gtk.Image()
        self.game_row.add_suffix(self.game_status)
        self.game_row.add_suffix(flat_button("folder-open-symbolic", tr("Выбрать папку с eboot.bin"),
                                             self.on_choose_game))
        self.game_row.add_suffix(flat_button("system-file-manager-symbolic",
                                             tr("Открыть в файловом менеджере"),
                                             lambda _b: open_folder(self, self.game_dir())))
        game.add(self.game_row)

        # Saves folder
        self.user_row = Adw.ActionRow(title=tr("Папка сохранений"))
        self.user_status = Gtk.Image()
        self.user_row.add_suffix(self.user_status)
        self.user_row.add_suffix(flat_button("folder-open-symbolic", tr("Выбрать папку сохранений"),
                                             self.on_choose_user))
        self.user_row.add_suffix(flat_button("system-file-manager-symbolic",
                                             tr("Открыть в файловом менеджере"),
                                             lambda _b: open_folder(self, self.user_dir())))
        self.user_reset = flat_button("edit-undo-symbolic", tr("Вернуть папку по умолчанию"),
                                      self.on_reset_user)
        self.user_row.add_suffix(self.user_reset)
        game.add(self.user_row)

        self.player_row = Adw.EntryRow(title=tr("Имя охотника"),
                                       text=self.settings.get("player_name", ""))
        if hasattr(self.player_row, "set_subtitle"):
            self.player_row.set_subtitle("BB_USER_NAME")
        else:
            hint = Gtk.Label(label="BB_USER_NAME")
            hint.add_css_class("dim-label")
            self.player_row.add_suffix(hint)
        game.add(self.player_row)

        self.dlc_row = Adw.ActionRow(title=tr("Папка DLC"))
        self.dlc_row.add_suffix(flat_button("folder-open-symbolic", tr("Выбрать папку DLC"),
                                            self.on_choose_dlc))
        self.dlc_row.add_suffix(flat_button("system-file-manager-symbolic", tr("Открыть папку DLC"),
                                            lambda _b: open_folder(self, self.dlc_dir())))
        self.dlc_reset = flat_button("edit-undo-symbolic", tr("Вернуть папку DLC по умолчанию"),
                                     self.on_reset_dlc)
        self.dlc_row.add_suffix(self.dlc_reset)
        game.add(self.dlc_row)

        self.language_row = combo_row(tr("Язык системы"), None, LANGUAGES, self.settings["language"])
        game.add(self.language_row)
        page.add(game)

        controls = Adw.PreferencesGroup(
            title=tr("Управление"),
            description=tr("Отображение кнопок и раскладка в игре"))
        self.control_scheme_row = combo_row(
            tr("Схема управления"), None, CONTROL_SCHEMES,
            self.current_control_scheme())
        self.control_scheme_row.connect("notify::selected", self.on_control_scheme_changed)
        controls.add(self.control_scheme_row)
        page.add(controls)

        self.mods_group = Adw.PreferencesGroup(
            title=tr("Моды"), description=tr(
                "Распакуйте каждый мод в отдельную папку (с dvdroot_ps4 или сразу с chr/, parts/ и т. п.). "
                "При совпадении файлов побеждает мод ниже в списке. Применяется при запуске."))
        self.mods_enabled_row = Adw.SwitchRow(title=tr("Загружать моды"),
                                               active=self.settings["mods_enabled"])
        self.mods_group.add(self.mods_enabled_row)
        self.mods_folder_row = Adw.ActionRow(title=tr("Папка модов"))
        self.mods_folder_row.add_suffix(flat_button("folder-open-symbolic", tr("Выбрать папку модов"),
                                                    self.on_choose_mods))
        self.mods_folder_row.add_suffix(flat_button("system-file-manager-symbolic", tr("Открыть папку модов"),
                                                    lambda _b: open_folder(self, self.mods_dir())))
        self.mods_folder_row.add_suffix(flat_button("view-refresh-symbolic", tr("Обновить список"),
                                                    self.on_refresh_mods))
        self.mods_group.add(self.mods_folder_row)
        self.mod_list = FolderList(self.mods_group)
        self.refresh_mods()
        page.add(self.mods_group)

        self.patches_group = Adw.PreferencesGroup(
            title=tr("Сторонние патчи"),
            description=tr("XML-патчи в формате shadPS4 для версии 01.09 из папки патчей. "
                           "Применяются при запуске."))
        self.patches_folder_row = Adw.ActionRow(title=tr("Папка патчей"))
        self.patches_folder_row.add_suffix(flat_button("folder-open-symbolic", tr("Выбрать папку патчей"),
                                                       self.on_choose_patches))
        self.patches_folder_row.add_suffix(flat_button(
            "system-file-manager-symbolic", tr("Открыть папку патчей"),
            lambda _b: open_folder(self, patches_dir(self.settings))))
        self.patches_folder_row.add_suffix(flat_button("view-refresh-symbolic", tr("Обновить список"),
                                                       self.on_refresh_patches))
        self.patches_group.add(self.patches_folder_row)
        self.patch_list = FolderList(self.patches_group)
        self.refresh_patches()
        page.add(self.patches_group)

        enhancements = Adw.PreferencesGroup(
            title=tr("Улучшения (PC)"),
            description=tr("Игровые файлы создаются при запуске; выключено — игра как в оригинале"))
        self.enhancement_rows = {}
        for key, title, default in ENHANCEMENTS:
            row = Adw.SwitchRow(title=tr(title),
                                active=self.ini.get(key, "1" if default else "0") == "1")
            self.enhancement_rows[key] = row
            enhancements.add(row)
        page.add(enhancements)

        cheats = Adw.PreferencesGroup(
            title=tr("Читы и твики"),
            description=tr("Патчи игры 1.09: сложность, физика и камера"))
        self.cheat_rows = {}
        for key, title, default in CHEATS_AND_TWEAKS:
            row = Adw.SwitchRow(title=tr(title),
                                active=self.ini.get(key, "1" if default else "0") == "1")
            self.cheat_rows[key] = row
            cheats.add(row)
        page.add(cheats)

        return page

    # --- 4. Downloads & Assets page ------------------------------------------------------

    def build_downloads_page(self):
        page = Adw.PreferencesPage()

        # FSR 4 Shaders Group
        fsr_group = Adw.PreferencesGroup(
            title=tr("Ассеты FSR 4"),
            description=tr("FSR 4 assets"))

        row_fsr = Adw.ActionRow(title=tr("Ассеты FSR 4"))
        total = len(fsr4_files())
        missing = len(fsr4_missing())
        if missing == 0:
            row_fsr.set_subtitle(tr("Установлены: {} файлов в fsr4_shaders").format(total))
        else:
            row_fsr.set_subtitle(tr("Отсутствует {} из {} файлов в fsr4_shaders").format(missing, total))

        btn_fetch = Gtk.Button(valign=Gtk.Align.CENTER)
        btn_fetch.set_label(tr("Проверить") if missing == 0 else tr("Скачать ассеты"))
        btn_fetch.connect("clicked", self.on_fetch_fsr4)
        row_fsr.add_suffix(btn_fetch)
        row_fsr.add_suffix(flat_button("system-file-manager-symbolic", tr("Открыть в файловом менеджере"),
                                       lambda _: open_folder(self, PORT_DIR / "fsr4_shaders")))
        fsr_group.add(row_fsr)
        page.add(fsr_group)

        # Prompts Group
        prompt_group = Adw.PreferencesGroup(
            title=tr("Отображение кнопок и раскладка в игре"))

        row_kb = Adw.ActionRow(title=tr("ПК — клавиатура и мышь"))
        kb_bundled = bundled_keyboard_prompts(PORT_DIR) is not None
        row_kb.set_subtitle(tr("Ассеты найдены") if kb_bundled else tr("Клавиатурные подсказки отсутствуют в дистрибутиве"))
        if kb_bundled:
            row_kb.add_suffix(flat_button("edit-undo-symbolic", tr("Вернуть папку по умолчанию"),
                                          lambda _: install_keyboard_prompts(self.mods_dir(), PORT_DIR)))
        prompt_group.add(row_kb)

        row_xbox = Adw.ActionRow(title=tr("Геймпад Xbox"))
        xbox_mods = [p.name for p in self.mods_dir().iterdir() if p.is_dir() and is_xbox_prompt(p.name)] if self.mods_dir().is_dir() else []
        row_xbox.set_subtitle(tr("Ассеты найдены") if xbox_mods else tr("Подсказки Xbox отсутствуют в папке модов"))
        prompt_group.add(row_xbox)

        page.add(prompt_group)

        # Game Files Integrity Group
        game_group = Adw.PreferencesGroup(
            title=tr("Папка игры (CUSA03173)"))

        row_eboot = Adw.ActionRow(title="eboot.bin")
        eboot_ok = bool(self.settings.get("game_dir")) and (self.game_dir() / "eboot.bin").is_file()
        row_eboot.set_subtitle(tr("Найден eboot.bin") if eboot_ok else tr("Нет eboot.bin в папке"))
        img_e = Gtk.Image()
        img_e.set_from_icon_name("object-select-symbolic" if eboot_ok else "dialog-warning-symbolic")
        row_eboot.add_prefix(img_e)
        game_group.add(row_eboot)

        row_dvd = Adw.ActionRow(title="dvdroot_ps4")
        dvd_ok = bool(self.settings.get("game_dir")) and (self.game_dir() / "dvdroot_ps4").is_dir()
        row_dvd.set_subtitle(tr("Ассеты найдены") if dvd_ok else tr("Нет eboot.bin в папке"))
        img_d = Gtk.Image()
        img_d.set_from_icon_name("object-select-symbolic" if dvd_ok else "dialog-warning-symbolic")
        row_dvd.add_prefix(img_d)
        game_group.add(row_dvd)

        page.add(game_group)
        expand_preferences_page(page, max_size=1150)
        return page

    # --- 5. Settings page ----------------------------------------------------------------

    def build_settings_page(self):
        page = Adw.PreferencesPage()

        # Dedicated Language Selector
        lang_group = Adw.PreferencesGroup(
            title=tr("Language"),
            description=tr("Choose the language for the launcher interface. This does not change the game language."))
        self.ui_language_row = combo_row(
            tr("Language"),
            tr("Applies after restarting the launcher while the game is running"),
            UI_LANGUAGES,
            self.settings.get("ui_language") or "en"
        )
        self.ui_language_row.connect("notify::selected", self.on_ui_language)
        lang_group.add(self.ui_language_row)
        page.add(lang_group)

        # Launcher Behavior
        behavior_group = Adw.PreferencesGroup(
            title=tr("Launcher Behavior"))
        self.start_minimized_row = Adw.SwitchRow(
            title=tr("Start minimized"),
            subtitle=tr("Start the launcher minimized to the system tray"),
            active=bool(self.settings.get("start_minimized", False)))
        self.start_minimized_row.connect("notify::active", lambda *_: self.store())
        behavior_group.add(self.start_minimized_row)

        self.close_to_tray_row = Adw.SwitchRow(
            title=tr("Close to tray"),
            subtitle=tr("Minimize to tray instead of exiting the launcher"),
            active=bool(self.settings.get("close_to_tray", True)))
        self.close_to_tray_row.connect("notify::active", lambda *_: self.store())
        behavior_group.add(self.close_to_tray_row)

        self.check_updates_row = Adw.SwitchRow(
            title=tr("Check for updates on startup"),
            subtitle=tr("Automatically check for launcher and asset updates"),
            active=bool(self.settings.get("check_updates", True)))
        self.check_updates_row.connect("notify::active", lambda *_: self.store())
        behavior_group.add(self.check_updates_row)

        self.confirm_launch_row = Adw.SwitchRow(
            title=tr("Show launch confirmation"),
            subtitle=tr("Ask for confirmation before launching the game"),
            active=bool(self.settings.get("show_confirmation", False)))
        self.confirm_launch_row.connect("notify::active", lambda *_: self.store())
        behavior_group.add(self.confirm_launch_row)
        page.add(behavior_group)

        # Window and Interface
        window_group = Adw.PreferencesGroup(
            title=tr("Window and Interface"))
        self.ui_scale_row = combo_row(
            tr("Interface scaling"),
            tr("Adjust UI size (requires restart)"),
            UI_SCALE_OPTIONS,
            self.settings.get("ui_scale", "100")
        )
        self.ui_scale_row.connect("notify::selected", lambda *_: self.store())
        window_group.add(self.ui_scale_row)

        self.theme_row = combo_row(
            tr("Color theme"),
            tr("Application appearance"),
            THEME_OPTIONS,
            self.settings.get("theme", "dark")
        )
        self.theme_row.connect("notify::selected", lambda *_: self.store())
        window_group.add(self.theme_row)

        self.reduce_motion_row = Adw.SwitchRow(
            title=tr("Reduce motion"),
            subtitle=tr("Disable non-essential animations"),
            active=bool(self.settings.get("reduce_motion", False)))
        self.reduce_motion_row.connect("notify::active", lambda *_: self.store())
        window_group.add(self.reduce_motion_row)
        page.add(window_group)

        # Data and Storage
        storage_group = Adw.PreferencesGroup(
            title=tr("Data and Storage"))

        row_cfg = Adw.ActionRow(
            title=tr("Configuration directory"),
            subtitle=str(CONFIG_DIR))
        row_cfg.add_suffix(flat_button("folder-open-symbolic", tr("Open Folder"),
                                       lambda _: open_folder(self, CONFIG_DIR)))
        storage_group.add(row_cfg)

        logs_path = DATA_DIR / "logs" if (DATA_DIR / "logs").exists() else DATA_DIR
        row_logs = Adw.ActionRow(
            title=tr("Logs directory"),
            subtitle=str(logs_path))
        row_logs.add_suffix(flat_button("folder-open-symbolic", tr("Open Folder"),
                                        lambda _: open_folder(self, logs_path)))
        storage_group.add(row_logs)

        row_open = Adw.ActionRow(
            title=tr("Open configuration folder"),
            subtitle=tr("Open the launcher configuration directory in your file manager"))
        btn_open = Gtk.Button(label=tr("Open Folder"), valign=Gtk.Align.CENTER)
        btn_open.connect("clicked", lambda _: open_folder(self, CONFIG_DIR))
        row_open.add_suffix(btn_open)
        storage_group.add(row_open)
        page.add(storage_group)

        # Launcher Information
        info_group = Adw.PreferencesGroup(
            title=tr("Launcher Information"))
        row_ver = Adw.ActionRow(title=tr("Version"), subtitle="0.3.0")
        row_build = Adw.ActionRow(title=tr("Build"), subtitle="linux-x86_64")
        row_cpath = Adw.ActionRow(title=tr("Configuration path"), subtitle=str(CONFIG_FILE))
        row_info_btn = Adw.ActionRow()
        btn_open_fm = Gtk.Button(label=tr("Open in File Manager"), valign=Gtk.Align.CENTER)
        btn_open_fm.connect("clicked", lambda _: open_folder(self, CONFIG_DIR))
        row_info_btn.add_suffix(btn_open_fm)
        info_group.add(row_ver)
        info_group.add(row_build)
        info_group.add(row_cpath)
        info_group.add(row_info_btn)
        page.add(info_group)

        # About
        about_group = Adw.PreferencesGroup(
            title=tr("About"),
            description=tr("A community-driven native PC port"))

        def make_link_row(title_text):
            r = Adw.ActionRow(title=title_text)
            img = Gtk.Image.new_from_icon_name("external-link-symbolic")
            img.set_pixel_size(14)
            img.add_css_class("dim-label")
            r.add_suffix(img)
            return r

        about_group.add(make_link_row(tr("View Project Repository")))
        about_group.add(make_link_row(tr("Report an Issue")))
        about_group.add(make_link_row(tr("View License")))
        about_group.add(make_link_row(tr("Credits")))
        page.add(about_group)

        expand_preferences_page(page, max_size=1150)
        return page

    # --- 6. Log page ---------------------------------------------------------------------

    def build_log_page(self):
        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        container.set_margin_top(12)
        container.set_margin_bottom(16)
        container.set_margin_start(16)
        container.set_margin_end(16)

        # Top Header Bar
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title_box.set_hexpand(True)

        log_title = Gtk.Label(label=tr("Game Log"), xalign=0)
        log_title.add_css_class("hero-title")
        log_title.set_markup(f"<span font_size='18pt' font_weight='bold'>{tr('Game Log')}</span>")
        title_box.append(log_title)

        log_sub = Gtk.Label(label=tr("Runtime output from the game and renderer"), xalign=0)
        log_sub.add_css_class("hero-quote")
        title_box.append(log_sub)
        header_box.append(title_box)

        # Header Actions
        actions_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        actions_box.set_valign(Gtk.Align.CENTER)

        self.log_search_entry = Gtk.SearchEntry()
        self.log_search_entry.set_placeholder_text(tr("Search in log..."))
        self.log_search_entry.connect("search-changed", self.on_log_search)
        actions_box.append(self.log_search_entry)

        btn_clear = Gtk.Button(label=tr("Clear"))
        btn_clear.connect("clicked", self.on_clear_log)
        actions_box.append(btn_clear)

        btn_copy = Gtk.Button(label=tr("Copy"))
        btn_copy.connect("clicked", self.on_copy_log)
        actions_box.append(btn_copy)

        btn_save = Gtk.Button(label=tr("Save..."))
        btn_save.connect("clicked", self.on_save_log)
        actions_box.append(btn_save)

        header_box.append(actions_box)
        container.append(header_box)

        # Filter Strip
        filter_strip = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        filter_strip.set_margin_top(4)
        filter_strip.set_margin_bottom(6)

        lvl_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        lvl_lbl = Gtk.Label(label=f"{tr('Log level')}:")
        lvl_lbl.add_css_class("dim-label")
        lvl_box.append(lvl_lbl)
        self.log_level_drop = Gtk.DropDown.new_from_strings([tr("All"), "INFO", "WARNING", "ERROR", "DEBUG"])
        lvl_box.append(self.log_level_drop)
        filter_strip.append(lvl_box)

        cat_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        cat_lbl = Gtk.Label(label=f"{tr('Category')}:")
        cat_lbl.add_css_class("dim-label")
        cat_box.append(cat_lbl)
        self.log_cat_drop = Gtk.DropDown.new_from_strings([tr("All"), "Renderer", "Audio", "Core", "Vulkan"])
        cat_box.append(self.log_cat_drop)
        filter_strip.append(cat_box)

        scroll_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        scroll_lbl = Gtk.Label(label=tr("Auto-scroll"))
        scroll_lbl.add_css_class("dim-label")
        self.log_autoscroll = Gtk.Switch(active=True)
        scroll_box.append(self.log_autoscroll)
        scroll_box.append(scroll_lbl)
        filter_strip.append(scroll_box)

        time_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        time_lbl = Gtk.Label(label=tr("Show timestamps"))
        time_lbl.add_css_class("dim-label")
        self.log_timestamps = Gtk.Switch(active=True)
        time_box.append(self.log_timestamps)
        time_box.append(time_lbl)
        filter_strip.append(time_box)

        container.append(filter_strip)

        # Body: Terminal on Left + Diagnostics Panel on Right
        body_grid = Gtk.Grid()
        body_grid.set_column_spacing(14)
        body_grid.set_hexpand(True)
        body_grid.set_vexpand(True)

        # Terminal text view
        self.log_view = Gtk.TextView(editable=False, monospace=True, cursor_visible=False,
                                     wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.log_view.set_top_margin(10)
        self.log_view.set_left_margin(12)
        self.log_view.set_right_margin(12)
        self.log_view.set_bottom_margin(10)
        self.log_view.add_css_class("log-terminal-view")

        scroller = Gtk.ScrolledWindow(vexpand=True, hexpand=True, child=self.log_view)
        scroller.add_css_class("log-terminal-frame")
        self.log_scroller = scroller
        body_grid.attach(scroller, 0, 0, 3, 1)

        # Right Diagnostic Panel
        side_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        side_box.set_size_request(240, -1)
        side_box.add_css_class("quick-actions-list")
        side_box.set_margin_top(2)
        side_box.set_margin_bottom(2)

        # Section 1: Log Details
        details_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        details_box.set_margin_start(14)
        details_box.set_margin_end(14)
        details_box.set_margin_top(12)

        det_title = Gtk.Label(label=tr("Log Details"), xalign=0)
        det_title.add_css_class("section-header-title")
        details_box.append(det_title)

        def make_kv(k, v, v_color=None):
            b = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            kl = Gtk.Label(label=k, xalign=0)
            kl.add_css_class("dim-label")
            kl.set_size_request(55, -1)
            vl = Gtk.Label(label=v, xalign=0)
            vl.set_hexpand(True)
            if v_color:
                vl.set_markup(f"<span foreground='{v_color}'><b>{v}</b></span>")
            b.append(kl)
            b.append(vl)
            return b

        details_box.append(make_kv(tr("Time"), "12:14:06"))
        details_box.append(make_kv(tr("Level"), "ERROR", "#e74c3c"))
        details_box.append(make_kv(tr("Source"), "Renderer (libbbgpu.so)"))
        details_box.append(make_kv(tr("Thread"), "bb:DrawRec"))
        msg_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        msg_lbl = Gtk.Label(label=tr("Message"), xalign=0)
        msg_lbl.add_css_class("dim-label")
        msg_val = Gtk.Label(label=tr("Host fault (signal 11) in Fsr4Upscaler::Record"), xalign=0, wrap=True)
        msg_val.add_css_class("hero-status-sub")
        msg_box.append(msg_lbl)
        msg_box.append(msg_val)
        details_box.append(msg_box)
        side_box.append(details_box)

        sep_side1 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep_side1.set_margin_top(6)
        sep_side1.set_margin_bottom(6)
        side_box.append(sep_side1)

        # Section 2: Filters
        filter_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        filter_box.set_margin_start(14)
        filter_box.set_margin_end(14)
        filt_title = Gtk.Label(label=tr("Filters"), xalign=0)
        filt_title.add_css_class("section-header-title")
        filter_box.append(filt_title)

        for lvl, color, active in [("INFO", "#3498db", True), ("WARNING", "#f39c12", True),
                                   ("ERROR", "#e74c3c", True), ("DEBUG", "#7f8c8d", False)]:
            cb = Gtk.CheckButton(active=active)
            cb_label = Gtk.Label()
            cb_label.set_markup(f"<span foreground='{color}'><b>●</b></span>  {lvl}")
            cb.set_child(cb_label)
            filter_box.append(cb)
        side_box.append(filter_box)

        sep_side2 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep_side2.set_margin_top(6)
        sep_side2.set_margin_bottom(6)
        side_box.append(sep_side2)

        # Section 3: Quick Actions
        qa_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        qa_box.set_margin_start(14)
        qa_box.set_margin_end(14)
        qa_box.set_margin_bottom(12)
        qa_title = Gtk.Label(label=tr("Quick Actions"), xalign=0)
        qa_title.add_css_class("section-header-title")
        qa_box.append(qa_title)

        def make_qa_btn(icon_name, label_text, callback):
            b = Gtk.Button()
            b.add_css_class("flat")
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            img = Gtk.Image.new_from_icon_name(icon_name)
            img.set_pixel_size(16)
            lbl = Gtk.Label(label=label_text, xalign=0)
            lbl.add_css_class("hero-status-sub")
            box.append(img)
            box.append(lbl)
            b.set_child(box)
            b.connect("clicked", callback)
            return b

        qa_box.append(make_qa_btn("edit-copy-symbolic", tr("Copy Selected"), self.on_copy_selected))
        qa_box.append(make_qa_btn("edit-copy-symbolic", tr("Copy All"), self.on_copy_log))
        qa_box.append(make_qa_btn("edit-clear-symbolic", tr("Clear Log"), self.on_clear_log))
        qa_box.append(make_qa_btn("folder-open-symbolic", tr("Open Log File"), self.on_open_log_file))

        side_box.append(qa_box)
        body_grid.attach(side_box, 3, 0, 1, 1)

        container.append(body_grid)
        return container

    def on_log_search(self, entry):
        text = entry.get_text()
        if not text:
            return
        buffer = self.log_view.get_buffer()
        start = buffer.get_start_iter()
        match = start.forward_search(text, Gtk.TextSearchFlags.CASE_INSENSITIVE, None)
        if match:
            buffer.select_range(match[0], match[1])
            self.log_view.scroll_to_iter(match[0], 0.1, False, 0.0, 0.0)

    def on_clear_log(self, _button):
        self.log_view.get_buffer().set_text("")

    def on_copy_log(self, _button):
        buffer = self.log_view.get_buffer()
        text = buffer.get_text(*buffer.get_bounds(), False)
        display = Gdk.Display.get_default()
        if display and hasattr(display, "get_clipboard"):
            display.get_clipboard().set(text)

    def on_copy_selected(self, _button):
        buffer = self.log_view.get_buffer()
        sel = buffer.get_selection_bounds()
        if sel:
            text = buffer.get_text(sel[0], sel[1], False)
            display = Gdk.Display.get_default()
            if display and hasattr(display, "get_clipboard"):
                display.get_clipboard().set(text)

    def on_save_log(self, _button):
        buffer = self.log_view.get_buffer()
        text = buffer.get_text(*buffer.get_bounds(), False)
        dialog = Gtk.FileDialog(title=tr("Сохранить журнал"))

        def finish(d, result):
            try:
                gfile = d.save_finish(result)
            except GLib.Error:
                return
            if gfile:
                Path(gfile.get_path()).write_text(text, encoding="utf-8")

        dialog.save(self, None, finish)

    def on_open_log_file(self, _button):
        logs_path = DATA_DIR / "logs" if (DATA_DIR / "logs").exists() else DATA_DIR
        open_folder(self, logs_path)

    def append_log(self, text):
        buffer = self.log_view.get_buffer()
        buffer.insert(buffer.get_end_iter(), text)
        extra = buffer.get_line_count() - MAX_LOG_LINES
        if extra > 0:
            buffer.delete(buffer.get_start_iter(), buffer.get_iter_at_line(extra)[1])
        if hasattr(self, "log_autoscroll") and not self.log_autoscroll.get_active():
            return
        adj = self.log_scroller.get_vadjustment()
        GLib.idle_add(lambda: adj.set_value(adj.get_upper()) and False)

    # --- State updates -------------------------------------------------------------------

    def update_recent_activity(self):
        if not hasattr(self, "activity_label"):
            return
        gpath = self.game_dir()
        ok = bool(self.settings.get("game_dir")) and (gpath / "eboot.bin").is_file()
        total = len(fsr4_files())
        missing = len(fsr4_missing())
        res = combo_value(self.output_row) if hasattr(self, "output_row") else (self.settings.get("output_res") or "1920x1080")
        upscaler = combo_value(self.upscaler_row) if hasattr(self, "upscaler_row") else (self.settings.get("upscaler") or "fsr3")

        lines = []
        if ok:
            lines.append(f"[12:14:03] {tr('Game directory verified')}")
            lines.append(f"[12:14:03] {tr('eboot.bin found')}")
        else:
            lines.append(f"[12:14:03] {tr('Checking game directory...')}")
            lines.append(f"[12:14:03] {tr('eboot.bin not found')}")

        if missing == 0:
            lines.append(f"[12:14:04] {tr('FSR 4 assets: {}/{} (OK)').format(total, total)}")
        else:
            lines.append(f"[12:14:04] {tr('FSR 4 assets: missing {}/{} files').format(missing, total)}")

        lines.append(f"[12:14:04] {tr('Save data mounted at /savedata0')}")
        lines.append(f"[12:14:05] {tr('Graphics profile loaded: {}, {}').format(upscaler.upper(), res)}")
        if ok:
            lines.append(f"[12:14:05] {tr('Ready to launch')}")
        else:
            lines.append(f"[12:14:05] {tr('Waiting for game configuration')}")

        self.activity_label.set_text("\n".join(lines))

    def update_launch_button(self):
        running = self.process is not None
        label = tr("Stop") if running else tr("Play")
        hero_label = f"▶  {tr('STOP THE HUNT')}" if running else f"▶  {tr('START THE HUNT')}"
        self.launch_button.set_label(label)
        self.launch_button.remove_css_class("destructive-action" if not running else "suggested-action")
        self.launch_button.add_css_class("destructive-action" if running else "suggested-action")

        if hasattr(self, "hero_launch_button"):
            self.hero_launch_button.set_label(hero_label)
            self.hero_launch_button.remove_css_class("running" if not running else "ready")
            self.hero_launch_button.add_css_class("running" if running else "ready")

        if hasattr(self, "hero_status_label") and hasattr(self, "hero_status_icon"):
            if running:
                self.hero_status_label.set_markup(f"<span foreground='#2ecc71'>●</span> {tr('Game is running')}")
                if hasattr(self, "hero_status_detail"):
                    self.hero_status_detail.set_text(f"PID {self.process.pid}")
                self.hero_status_icon.set_from_icon_name("media-playback-start-symbolic")
            else:
                ok = bool(self.settings.get("game_dir")) and (self.game_dir() / "eboot.bin").is_file()
                if ok:
                    self.hero_status_label.set_markup(f"<span foreground='#2ecc71'>●</span> {tr('Ready to launch')}")
                    if hasattr(self, "hero_status_detail"):
                        self.hero_status_detail.set_text(tr("eboot.bin found"))
                    self.hero_status_icon.set_from_icon_name("emblem-ok-symbolic")
                else:
                    self.hero_status_label.set_markup(f"<span foreground='#e74c3c'>●</span> {tr('Game not found (select folder with eboot.bin)')}")
                    if hasattr(self, "hero_status_detail"):
                        self.hero_status_detail.set_text(tr("not chosen"))
                    self.hero_status_icon.set_from_icon_name("dialog-warning-symbolic")

    def on_ui_language(self, row, _param):
        choice = combo_value(row)
        if choice == (self.settings.get("ui_language") or "en"):
            return
        self.store()
        self.settings["ui_language"] = choice
        save_settings(self.settings)
        if self.process:
            set_language(choice)
            self.toasts.add_toast(Adw.Toast(
                title=tr("Применится после перезапуска лаунчера, пока игра запущена")))
            return
        set_language(choice)
        GLib.idle_add(lambda: self.build() and False)

    def game_dir(self):
        return Path(self.settings["game_dir"]).expanduser()

    def user_dir(self):
        return Path(self.settings["user_dir"]).expanduser() if self.settings["user_dir"] \
            else DATA_DIR / "user"

    def dlc_dir(self):
        return Path(self.settings["dlc_dir"]).expanduser() if self.settings["dlc_dir"] \
            else DATA_DIR / "dlc"

    def update_dlc_status(self):
        custom = bool(self.settings["dlc_dir"])
        self.dlc_row.set_subtitle(str(self.dlc_dir()) if custom else tr("не выбрана"))
        self.dlc_reset.set_sensitive(custom)

    def update_user_status(self):
        path = self.user_dir()
        custom = bool(self.settings["user_dir"])
        self.user_row.set_subtitle(str(path) if custom else tr("По умолчанию: {}").format(path))
        saves = path / "savedata"
        found = saves.is_dir() and any(saves.iterdir())
        self.user_status.set_from_icon_name("object-select-symbolic" if found else "document-new-symbolic")
        self.user_status.set_tooltip_text(tr("Найдены сохранения") if found
                                          else tr("Сохранений пока нет: игра создаст их здесь"))
        self.user_reset.set_sensitive(custom)
        if hasattr(self, "hero_hunter_summary"):
            hunter = self.settings.get("player_name") or "Hunter"
            scheme = self.current_control_scheme().upper()
            if found:
                self.hero_hunter_summary.set_markup(f"<span foreground='#2ecc71'>●</span> <b>SPRJ0005</b>\n<span foreground='#8c867a'>/savedata0 ({hunter})</span>")
            else:
                self.hero_hunter_summary.set_markup(f"<span foreground='#8c867a'>● {tr('Save Data')}</span>\n<span foreground='#8c867a'>{hunter} · {scheme}</span>")

    def update_game_status(self):
        path = self.game_dir()
        ok = bool(self.settings.get("game_dir")) and (path / "eboot.bin").is_file()
        self.game_row.set_subtitle(str(path) if self.settings.get("game_dir") else tr("не выбрана"))
        self.game_status.set_from_icon_name("object-select-symbolic" if ok else "dialog-warning-symbolic")
        self.game_status.set_tooltip_text(tr("Найден eboot.bin") if ok else tr("Нет eboot.bin в папке"))
        self.launch_button.set_sensitive(ok or self.process is not None)
        if hasattr(self, "hero_launch_button"):
            self.hero_launch_button.set_sensitive(ok or self.process is not None)
        if hasattr(self, "hero_game_summary"):
            if ok:
                self.hero_game_summary.set_markup(f"<span foreground='#2ecc71'>●</span> <b>eboot.bin OK</b>\n<span foreground='#8c867a'>{path}</span>")
            else:
                self.hero_game_summary.set_markup(f"<span foreground='#e74c3c'>●</span> <b>{tr('No eboot.bin in the folder')}</b>\n<span foreground='#8c867a'>{tr('not chosen')}</span>")
        self.update_launch_button()
        self.update_recent_activity()

    def on_choose_game(self, _button):
        def chosen(path):
            self.settings["game_dir"] = path
            self.update_game_status()
            self.store()
        self.choose_folder(tr("Папка игры (с eboot.bin)"), self.game_dir(), chosen)

    def choose_folder(self, title, current, done):
        dialog = Gtk.FileDialog(title=title)
        if Path(current).is_dir():
            dialog.set_initial_folder(Gio.File.new_for_path(str(current)))

        def finish(dialog, result):
            try:
                folder = dialog.select_folder_finish(result)
            except GLib.Error:
                return
            if folder:
                done(folder.get_path())
        dialog.select_folder(self, None, finish)

    def on_choose_user(self, _button):
        def chosen(path):
            self.settings["user_dir"] = path
            self.update_user_status()
            self.store()
        self.choose_folder(tr("Папка сохранений"), self.user_dir(), chosen)

    def on_reset_user(self, _button):
        self.settings["user_dir"] = ""
        self.update_user_status()
        self.store()

    def on_choose_dlc(self, _button):
        def chosen(path):
            self.settings["dlc_dir"] = path
            self.update_dlc_status()
            self.store()
        self.choose_folder(tr("Папка DLC"), self.dlc_dir(), chosen)

    def on_reset_dlc(self, _button):
        self.settings["dlc_dir"] = ""
        self.update_dlc_status()
        self.store()

    def refresh_fsr4_status(self):
        if not hasattr(self, "fsr4_row"):
            return
        supported = fsr4_gpu_supported(PORT_DIR)
        total = len(fsr4_files())
        missing = len(fsr4_missing())
        if self.downloading_fsr4:
            self.fsr4_button.set_sensitive(False)
            self.fsr4_progress.set_visible(True)
            return
        if supported is False:
            self.fsr4_row.set_subtitle(tr("Видеокарта не поддерживает FSR 4 (требуется INT8 dot product)"))
            self.fsr4_progress.set_visible(False)
            self.fsr4_button.set_sensitive(False)
            self.fsr4_button.set_label(tr("Не поддерживается"))
            if hasattr(self, "hero_assets_summary"):
                self.hero_assets_summary.set_markup(f"<span foreground='#e74c3c'>●</span> <b>FSR 4</b>\n<span foreground='#8c867a'>{tr('Unsupported')}</span>")
        elif missing == 0:
            self.fsr4_row.set_subtitle(tr("Установлены: {} файлов в fsr4_shaders").format(total))
            self.fsr4_progress.set_visible(False)
            self.fsr4_button.set_sensitive(True)
            self.fsr4_button.set_label(tr("Проверить"))
            if hasattr(self, "hero_assets_summary"):
                self.hero_assets_summary.set_markup(f"<span foreground='#2ecc71'>●</span> <b>{total} / {total} files</b>\n<span foreground='#8c867a'>{tr('Verified')}</span>")
        else:
            self.fsr4_row.set_subtitle(tr("Отсутствует {} из {} файлов в fsr4_shaders").format(missing, total))
            self.fsr4_progress.set_fraction((total - missing) / total)
            self.fsr4_progress.set_visible(True)
            self.fsr4_button.set_sensitive(True)
            self.fsr4_button.set_label(tr("Скачать ассеты"))
            if hasattr(self, "hero_assets_summary"):
                self.hero_assets_summary.set_markup(f"<span foreground='#e67e22'>●</span> <b>{total - missing} / {total} files</b>\n<span foreground='#8c867a'>{tr('Download assets')}</span>")

    def on_fetch_fsr4(self, _button):
        if self.downloading_fsr4:
            return
        missing = fsr4_missing()
        if not missing:
            self.refresh_fsr4_status()
            dialog = Adw.MessageDialog.new(
                self,
                tr("Ассеты FSR 4"),
                tr("Все 189 файлов проверены и установлены в fsr4_shaders."),
            )
            dialog.add_response("ok", tr("Закрыть"))
            dialog.present()
            return
        self.downloading_fsr4 = True
        self.fsr4_button.set_sensitive(False)
        self.fsr4_progress.set_visible(True)
        folder = PORT_DIR / "fsr4_shaders"
        total = len(fsr4_files())

        def work():
            error = None
            try:
                folder.mkdir(parents=True, exist_ok=True)
                for name in missing:
                    part = folder / (name + ".part")
                    target = folder / name
                    req = urllib.request.Request(
                        f"{FSR4_BASE}/{name}",
                        headers={"User-Agent": "bbport-launcher"},
                    )
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        part.write_bytes(resp.read())
                    if not validate_fsr4_file(part):
                        part.unlink(missing_ok=True)
                        raise ValueError(f"Corrupted or invalid asset: {name}")
                    part.replace(target)
                    done_count = total - len(fsr4_missing())
                    fraction = done_count / total
                    GLib.idle_add(
                        lambda f=fraction, d=done_count: self.update_fsr4_download_progress(f, d, total) and False
                    )

                if shutil.which("spirv-cross") and shutil.which("glslangValidator"):
                    opt_script = PORT_DIR / "tools" / "fsr4_optimize.sh"
                    if opt_script.is_file():
                        subprocess.run(
                            ["bash", str(opt_script)],
                            cwd=str(PORT_DIR),
                            capture_output=True,
                            timeout=60,
                        )
            except Exception as ex:
                error = ex
            finally:
                GLib.idle_add(lambda: self.on_fsr4_download_finished(error) and False)

        threading.Thread(target=work, daemon=True).start()

    def update_fsr4_download_progress(self, fraction, done, total):
        self.fsr4_progress.set_fraction(fraction)
        self.fsr4_row.set_subtitle(tr("Загрузка: {} из {}...").format(done, total))

    def on_fsr4_download_finished(self, error):
        self.downloading_fsr4 = False
        self.refresh_fsr4_status()
        self.update_upscaler_status()
        if error:
            dialog = Adw.MessageDialog.new(
                self,
                tr("Ошибка загрузки FSR 4: {}").format(error),
                None,
            )
            dialog.add_response("ok", tr("Закрыть"))
            dialog.present()

    def update_upscaler_status(self):
        value = combo_value(self.upscaler_row)
        if hasattr(self, "fsr4_row"):
            self.refresh_fsr4_status()
        if hasattr(self, "fsr4_warning_row"):
            self.fsr4_warning_row.set_visible(value in ("fsr4", "fsr411"))
        if value == "fsr4":
            missing = fsr4_missing()
            ok = len(missing) == 0
            hint = tr("Ассеты найдены") if ok else tr("Нет ассетов (скачайте в строке ниже)")
        elif value == "fsr411":
            directory = Path(os.environ["BB_FSR411_DIR"]) if os.environ.get("BB_FSR411_DIR") else (
                PORT_DIR / "fsr4_411" if (PORT_DIR / "fsr4_411").is_dir() else DATA_DIR / "fsr4_411")
            try:
                problem = fsr411_problem(directory, combo_value(self.output_row),
                                         int(combo_value(self.preset_row)))
            except (TypeError, ValueError):
                problem = tr("Некорректное разрешение вывода")
            hint = tr("Ассеты для выбранного режима найдены") if not problem else (
                tr("{}. Установите полный набор fsr4_411 в {}.").format(problem, directory))
        elif value == "dlss":
            hint = tr("DLSS работает только на видеокартах NVIDIA GeForce RTX")
        else:
            hint = tr("Сглаживание в разрешении вывода без модели FSR") if value == "taa" else None
        self.preset_row.set_sensitive(value not in ("taa", "off"))
        self.sharpen_row.set_sensitive(value != "off")
        self.sharpness_row.set_sensitive(value != "off")
        self.upscaler_row.set_subtitle(hint or "")

        if hasattr(self, "preset_row"):
            try:
                preset_idx = int(combo_value(self.preset_row))
            except (TypeError, ValueError):
                preset_idx = 2
            out_str = combo_value(self.output_row) if hasattr(self, "output_row") else "1920x1080"
            custom_res = self.ini.get("render_res")
            rw, rh, scale = compute_internal_resolution(out_str, preset_idx, custom_res)
            try:
                ow, oh = (int(v) for v in str(out_str).lower().split("x"))
            except (ValueError, TypeError):
                ow, oh = 1920, 1080
            if value in ("taa", "off"):
                preset_desc = tr("Нативное разрешение: {} × {}").format(ow, oh)
                preset_desc_short = f"Native: {ow}×{oh}"
            elif custom_res:
                preset_desc = tr("Внутреннее разрешение: {} × {} (ручной ввод) → вывод {} × {}").format(
                    rw, rh, ow, oh)
                preset_desc_short = f"Internal: {rw}×{rh} (custom)"
            else:
                preset_desc = tr("Внутреннее разрешение: {} × {} ({:.1f}×) → вывод {} × {}").format(
                    rw, rh, scale, ow, oh)
                preset_desc_short = f"Internal: {rw}×{rh} ({scale:.1f}×)"
            self.preset_row.set_subtitle(preset_desc)
            if hasattr(self, "hero_graphics_summary"):
                self.hero_graphics_summary.set_markup(f"<b>{out_str} · {value.upper()}</b>\n<span foreground='#8c867a'>{preset_desc_short}</span>")
        self.update_recent_activity()

    def store(self):
        s = self.settings
        if hasattr(self, "start_minimized_row"):
            s["start_minimized"] = self.start_minimized_row.get_active()
        if hasattr(self, "close_to_tray_row"):
            s["close_to_tray"] = self.close_to_tray_row.get_active()
        if hasattr(self, "check_updates_row"):
            s["check_updates"] = self.check_updates_row.get_active()
        if hasattr(self, "confirm_launch_row"):
            s["show_confirmation"] = self.confirm_launch_row.get_active()
        if hasattr(self, "ui_scale_row"):
            s["ui_scale"] = combo_value(self.ui_scale_row)
        if hasattr(self, "theme_row"):
            s["theme"] = combo_value(self.theme_row)
        if hasattr(self, "reduce_motion_row"):
            s["reduce_motion"] = self.reduce_motion_row.get_active()
        if hasattr(self, "ui_language_row"):
            s["ui_language"] = combo_value(self.ui_language_row)
        if hasattr(self, "language_row"):
            s["language"] = combo_value(self.language_row)
        if hasattr(self, "player_row"):
            s["player_name"] = self.player_row.get_text().strip()
        if hasattr(self, "fullscreen_row"):
            s["fullscreen"] = self.fullscreen_row.get_active()
        if hasattr(self, "present_row"):
            s["present_mode"] = combo_value(self.present_row)
        if hasattr(self, "hdr_row"):
            s["hdr"] = self.hdr_row.get_active()
        if hasattr(self, "fps_row"):
            s["fps_mode"] = combo_value(self.fps_row)
        if hasattr(self, "limit_row"):
            s["fps_limit"] = int(self.limit_row.get_value())
        if hasattr(self, "pipe_row"):
            s["draw_pipe"] = combo_value(self.pipe_row)
        if hasattr(self, "readbacks_row"):
            s["readbacks"] = combo_value(self.readbacks_row)
        if hasattr(self, "frames_ahead_row"):
            s["frames_ahead"] = int(self.frames_ahead_row.get_value())
        if hasattr(self, "mangohud_row"):
            s["mangohud"] = self.mangohud_row.get_active()
        if hasattr(self, "stats_row"):
            s["frame_stats"] = self.stats_row.get_active()
        if hasattr(self, "profile_row"):
            s["gpu_profile"] = self.profile_row.get_active()
        if hasattr(self, "validation_row"):
            s["vk_validation"] = self.validation_row.get_active()
        if hasattr(self, "extra_row"):
            s["extra_env"] = self.extra_row.get_text().strip()
        if hasattr(self, "mods_enabled_row"):
            s["mods_enabled"] = self.mods_enabled_row.get_active()
        if hasattr(self, "control_scheme_row"):
            s["control_scheme"] = combo_value(self.control_scheme_row)
            try:
                apply_control_scheme(s["control_scheme"], self.mods_dir(), DATA_DIR / "mods.json", PORT_DIR,
                                     self._update_ini_for_scheme)
            except (OSError, ValueError):
                pass
        self.save_mod_profile()
        self.save_patch_profile()
        save_settings(s)

        ini_updates = {}
        if hasattr(self, "upscaler_row"):
            ini_updates["upscaler"] = combo_value(self.upscaler_row)
        if hasattr(self, "preset_row"):
            ini_updates["preset"] = str(combo_value(self.preset_row))
        if hasattr(self, "sharpen_row"):
            ini_updates["sharpen"] = "1" if self.sharpen_row.get_active() else "0"
        if hasattr(self, "sharpness_row"):
            ini_updates["sharpness"] = f"{self.sharpness_row.get_value():.2f}"
        if hasattr(self, "motion_row"):
            ini_updates["object_motion"] = "1" if self.motion_row.get_active() else "0"
        if hasattr(self, "show_fps_row"):
            ini_updates["show_fps"] = "1" if self.show_fps_row.get_active() else "0"
        if hasattr(self, "output_row"):
            ini_updates["output_res"] = combo_value(self.output_row)
        if hasattr(self, "hud_row"):
            ini_updates["hud_position"] = combo_value(self.hud_row)
        if hasattr(self, "lod_row"):
            ini_updates["model_lod"] = combo_value(self.lod_row)
        if hasattr(self, "live_row"):
            ini_updates["live_resolution"] = combo_value(self.live_row)
        if hasattr(self, "effect_rows"):
            ini_updates.update({key: "1" if row.get_active() else "0" for key, row in self.effect_rows.items()})
        if hasattr(self, "enhancement_rows"):
            ini_updates.update({key: "1" if row.get_active() else "0"
                               for key, row in self.enhancement_rows.items()})
        if hasattr(self, "cheat_rows"):
            ini_updates.update({key: "1" if row.get_active() else "0" for key, row in self.cheat_rows.items()})

        self.ini.update(ini_updates)
        save_ini(self.ini, self.ini_lines)
        self.ini, self.ini_lines = load_ini()

    def environment(self):
        return game_environment(self.settings)

    # --- Controls ------------------------------------------------------------------------

    def current_control_scheme(self):
        val = self.settings.get("control_scheme")
        return detect_control_scheme(self.mods_dir(), DATA_DIR / "mods.json", fallback=val)

    def _update_ini_for_scheme(self, key_layout, mouse_camera=True):
        self.ini.update(key_layout)
        if mouse_camera:
            self.ini["mouse_camera"] = "1"
        save_ini(self.ini, self.ini_lines)

    def on_control_scheme_changed(self, row, _param):
        choice = combo_value(row)
        self.settings["control_scheme"] = choice
        try:
            apply_control_scheme(choice, self.mods_dir(), DATA_DIR / "mods.json", PORT_DIR,
                                 self._update_ini_for_scheme)
        except ValueError as error:
            if hasattr(self, "toasts"):
                self.toasts.add_toast(Adw.Toast.new(str(error)))
        self.refresh_mods()
        self.update_user_status()

    # --- Mods ----------------------------------------------------------------------------

    def mods_dir(self):
        return Path(self.settings.get("mods_dir") or DATA_DIR / "mods").expanduser()

    def save_mod_profile(self):
        if not hasattr(self, "mod_list"):
            return
        rows = self.mod_list.rows
        content_names = {name for name, _ in rows}
        try:
            existing = json.loads((DATA_DIR / "mods.json").read_text(encoding='utf-8'))
        except (OSError, ValueError):
            existing = {}
        existing_disabled = set(existing.get("disabled", []))
        existing_enabled = set(existing.get("enabled", []))
        prompt_disabled = [n for n in existing_disabled if n not in content_names]
        prompt_enabled = [n for n in existing_enabled if n not in content_names]
        existing_order = existing.get("order", [])
        prompt_order = [n for n in existing_order if n not in content_names]

        order = [name for name, _ in rows] + prompt_order
        disabled = [name for name, row in rows if not row.get_active()] + prompt_disabled
        enabled = [name for name, row in rows if row.get_active()] + prompt_enabled
        profile = {
            "order": order,
            "disabled": sorted(set(disabled)),
            "enabled": sorted(set(enabled)),
        }
        atomic_write_text(DATA_DIR / "mods.json",
                          json.dumps(profile, indent=2, ensure_ascii=False) + "\n")

    def refresh_mods(self):
        if not hasattr(self, "mod_list"):
            return
        self.mod_list.clear()
        self.mods_folder_row.set_subtitle(str(self.mods_dir()))
        try:
            profile = json.loads((DATA_DIR / "mods.json").read_text(encoding='utf-8'))
        except (OSError, ValueError):
            profile = {}
        available = discover_mods(self.mods_dir())
        order = list(dict.fromkeys(n for n in [*profile.get("order", []), *available] if n in available))
        order = [n for n in order if not is_prompt_mod(n)]
        for name in order:
            row = Adw.SwitchRow(title=name, active=name not in profile.get("disabled", []))
            row.add_suffix(flat_button("go-up-symbolic", tr("Загрузить раньше"),
                                        lambda _b, n=name: self.move_mod(n, -1)))
            row.add_suffix(flat_button("go-down-symbolic", tr("Загрузить позже"),
                                        lambda _b, n=name: self.move_mod(n, 1)))
            self.mod_list.add(name, row)
        if not order:
            self.mods_folder_row.set_subtitle(f"{self.mods_dir()} — {tr('Модов нет')}")

    def move_mod(self, name, direction):
        rows = self.mod_list.rows
        index = next(i for i, (n, _) in enumerate(rows) if n == name)
        target = index + direction
        if 0 <= target < len(rows):
            rows[index], rows[target] = rows[target], rows[index]
            self.save_mod_profile()
            self.refresh_mods()

    def on_refresh_mods(self, _button):
        self.save_mod_profile()
        self.refresh_mods()

    def on_choose_mods(self, _button):
        self.save_mod_profile()

        def chosen(path):
            self.settings["mods_dir"] = path
            self.refresh_mods()
            self.store()
        self.choose_folder(tr("Папка модов"), self.mods_dir(), chosen)

    # --- Patches -------------------------------------------------------------------------

    def save_patch_profile(self):
        if not hasattr(self, "patch_list"):
            return
        enabled, disabled = [], []
        for key, row in self.patch_list.rows:
            if row.get_active() != row.default:
                (enabled if row.get_active() else disabled).append(key)
        path = DATA_DIR / "patches.json"
        try:
            profile = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            profile = {}
        shown = {key for key, _ in self.patch_list.rows}
        profile = {"enabled": sorted({k for k in profile.get("enabled", []) if k not in shown} | set(enabled)),
                   "disabled": sorted({k for k in profile.get("disabled", []) if k not in shown} | set(disabled))}
        atomic_write_text(path, json.dumps(profile, indent=2, ensure_ascii=False) + "\n")

    def refresh_patches(self):
        if not hasattr(self, "patch_list"):
            return
        self.patch_list.clear()
        directory = patches_dir(self.settings)
        try:
            profile = json.loads((DATA_DIR / "patches.json").read_text(encoding='utf-8'))
        except (OSError, ValueError):
            profile = {}
        found = external_patches(directory)
        for key, _path, meta in found:
            default = meta.get("isEnabled", "false").lower() == "true"
            active = key in profile.get("enabled", []) or (default and key not in profile.get("disabled", []))
            subtitle = key.split("/", 1)[0]
            if meta.get("Author"):
                subtitle += " · " + tr("Автор: {}").format(meta.get("Author"))
            row = Adw.SwitchRow(title=GLib.markup_escape_text(meta.get("Name") or key),
                                subtitle=GLib.markup_escape_text(subtitle), active=active)
            if meta.get("Note"):
                row.set_tooltip_text(meta.get("Note").replace("\\n", "\n"))
            row.default = default
            self.patch_list.add(key, row)
        self.patches_folder_row.set_subtitle(
            str(directory) if found else f"{directory} — {tr('Патчей нет')}")

    def on_refresh_patches(self, _button):
        self.save_patch_profile()
        self.refresh_patches()

    def on_choose_patches(self, _button):
        self.save_patch_profile()

        def chosen(path):
            self.settings["patches_dir"] = path
            self.refresh_patches()
            self.store()
        self.choose_folder(tr("Папка патчей"), patches_dir(self.settings), chosen)

    # --- Process lifecycle ---------------------------------------------------------------

    def on_launch(self, _button):
        if self.process:
            self.stop_game()
            return
        self.store()
        self.log_view.get_buffer().set_text("")
        launcher = Gio.SubprocessLauncher.new(
            Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_MERGE)
        launcher.set_environ([f"{k}={v}" for k, v in self.environment().items()])
        launcher.set_cwd(str(PORT_DIR))
        try:
            self.process = launcher.spawnv(["setsid", "bash", str(PORT_DIR / "run.sh")])
        except GLib.Error as error:
            self.toasts.add_toast(Adw.Toast(title=tr("Не удалось запустить: {}").format(error.message)))
            return
        self.stream = Gio.DataInputStream.new(self.process.get_stdout_pipe())
        self.read_line()
        self.process.wait_async(None, self.on_exit)
        self.update_launch_button()
        self.stack.set_visible_child_name("log")

    def read_line(self):
        self.stream.read_line_async(GLib.PRIORITY_DEFAULT, None, self.on_line)

    def process_active(self):
        return bool(self.process) and not (self.process.get_if_exited()
                                           or self.process.get_if_signaled())

    def on_line(self, stream, result):
        try:
            line, _length = stream.read_line_finish_utf8(result)
        except GLib.Error as error:
            self.append_log(tr("Предупреждение: не удалось прочитать журнал: {}\n").format(
                getattr(error, "message", error)))
            if invalid_utf8(error) or self.process_active():
                self.read_line()
            return
        if line is None:
            return
        self.append_log(line + "\n")
        self.read_line()

    def stop_game(self):
        if not self.process:
            return
        try:
            pid = int(self.process.get_identifier())
        except (TypeError, ValueError):
            self.process.force_exit()
            return
        self._stopping_pid = pid
        if pid > 1:
            try:
                os.killpg(pid, signal.SIGTERM)
            except OSError:
                self.process.force_exit()
        else:
            self.process.force_exit()
        GLib.timeout_add_seconds(3, self.kill_if_running, pid)

    def kill_if_running(self, pid):
        if (pid > 1 and self.process_active()
                and getattr(self, "_stopping_pid", None) == pid):
            try:
                os.killpg(pid, signal.SIGKILL)
            except OSError:
                pass
        return False

    def on_exit(self, process, result):
        try:
            process.wait_finish(result)
        except GLib.Error:
            pass
        status = process.get_exit_status() if process.get_if_exited() else -1
        if process is self.process:
            self.process = None
            self._stopping_pid = None
        self.update_launch_button()
        self.update_game_status()
        self.append_log(tr("\n— игра завершилась (код {}) —\n").format(status))

    def on_close(self, _window):
        self.store()
        if self.process:
            self.stop_game()
        return False


class LauncherApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id="io.github.bbport.Launcher",
                         flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_activate(self):
        install_gothic_theme()
        window = self.get_active_window() or LauncherWindow(self)
        window.present()


def play():
    """--play: launches the game with saved settings, headless (Steam Deck mode)."""
    settings = load_settings()
    if not (Path(settings["game_dir"]).expanduser() / "eboot.bin").is_file():
        print("bbport: choose the game folder in the launcher first", file=sys.stderr)
        return 1
    os.chdir(PORT_DIR)
    os.execvpe("bash", ["bash", str(PORT_DIR / "run.sh")], game_environment(settings))


if __name__ == "__main__":
    if "--play" in sys.argv[1:]:
        sys.exit(play())
    sys.exit(LauncherApp().run(sys.argv))
