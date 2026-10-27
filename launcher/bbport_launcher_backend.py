"""UI-independent settings, launch and file operations for the Windows launcher.

The Qt Quick view talks to this object through a small set of slots. The game still
uses the same settings.json, bbport.ini, mods.json and run.py as the original UI.
"""
import ctypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
import zipfile

from PySide6.QtCore import QObject, Property, Signal, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFileDialog, QMessageBox

import bbport_bindings as bindings_config
import bbport_coop as coop
import bbport_launcher_win as core
import bbport_startup
from bbport_pkg_setup import PackageSetupError, install_game
from bbport_readiness import check_readiness, valid_trophy_key

THD_REFUSED = core.THD_REFUSED_NOTE[0]


def choice_rows(options):
    return [{'value': str(value), 'text': label[0]} for value, label in options]


# scripts/patches.py ONLINE_BLOCKED and gpu/shim/bbport_settings.cpp OnlineBlocked.
OFF_ONLINE = "Off when playing online with The Hunter's Dream (seamless co-op keeps it)."


def row(key, label, kind='text', options=None, hint=''):
    return {'key': key, 'label': label, 'kind': kind, 'options': choice_rows(options or []), 'hint': hint}


# What the graphics rows do, and which ones cost GPU time (the presets change those).
EFFECT_HINTS = {
    'effect_chromatic_aberration': 'Colour fringes at the screen edges. Look only.',
    'effect_dof': 'Blurs the background in cutscenes and close-ups. Look only.',
    'effect_motion_blur': 'Blur while turning the camera. Look only.',
    'effect_ssao': 'Soft shadows in corners and creases. Costs GPU time.',
    'effect_game_aa': "The game's own edge smoothing, under the upscaler. Look only.",
    'effect_dynamic_shadows': 'Shadows cast by lamps, torches and other moving lights. Costs GPU time.',
    'effect_ssr': 'Reflections on wet streets; not in the original game. Costs GPU time.',
}

FIELDS = {
    'Graphics': [
        row('upscaler', 'Upscaler', 'choice', core.UPSCALERS,
            'Renders below the output size and rebuilds a sharp image. DLSS needs an NVIDIA RTX card; FSR 3.1 works on any.'),
        row('preset', 'Upscaling preset', 'choice', core.PRESETS,
            'How far below the output the game renders: higher factors are faster and softer.'),
        row('output_res', 'Output resolution', 'choice', core.OUTPUTS, "The final image size, usually your display's."),
        row('frame_gen', 'Frame generation', 'choice', core.FRAME_GENERATION,
            "Makes frames between two of the game's: 60 FPS on screen becomes 120. Needs a display that "
            'fast; adds a little input latency. DLSS needs a GeForce RTX 40/50 and its frame generation files.'),
        row('frame_gen_multiplier', 'Frame generation multiplier', 'choice', core.FRAME_GEN_MULTIPLIERS,
            '3× and 4× need DLSS on a GeForce RTX 50.'),
        row('frame_gen_fit_display', 'Fit frame generation to the display', 'toggle',
            hint="Generates only the frames your display's refresh rate can show."),
        row('hud_position', 'HUD position (ultrawide)', 'choice', core.HUD_POSITIONS,
            '21:9 and 32:9 outputs: health, items and Blood Echoes at the screen edges, or in the '
            'centred 16:9 area as on a 16:9 screen. Applies at the next start.'),
        row('live_resolution', 'Live resolution changes', 'choice', core.LIVE,
            'Lets the in-game menu change the upscaling preset without a restart, at some cost in speed.'),
        row('sharpen', 'Sharpening (RCAS)', 'toggle', hint='Sharpens the upscaled image.'),
        row('sharpness', 'Sharpness (0.00–1.00)'),
        row('object_motion', 'Object motion vectors', 'toggle',
            hint='Motion data for moving characters: fewer ghosting trails with an upscaler.'),
        row('model_lod', 'Model detail', 'choice', core.LODS,
            'How soon distant models switch to simpler versions. Highest costs GPU time.'),
        row('vram_budget_mb', 'Video memory pressure target', 'choice', core.VRAM_BUDGETS,
            'Starts clearing old textures and buffers before the chosen amount. This is not a hard VRAM cap; '
            'lower values may cause stutter. Restart the game to apply.'),
        row('show_fps', 'Show FPS counter', 'toggle'),
        *[row(key, title[0], 'toggle', hint=EFFECT_HINTS.get(key, '')) for key, title, _ in core.EFFECTS],
    ],
    'Display': [
        row('fps_mode', 'Frame rate', 'choice', core.FPS_MODES),
        row('frame_cap', 'Unlocked mode limit', 'choice', core.FRAME_CAPS),
        row('frames_ahead', 'Frames ahead', 'choice', core.FRAMES_AHEAD),
        row('fullscreen', 'Fullscreen', 'toggle'),
        row('fullscreen_mode', 'Fullscreen type', 'choice', core.FULLSCREEN_MODES,
            'Exclusive switches the display to its own mode: notifications and other windows do not show over the game.'),
        row('display', 'Monitor', 'choice', core.DISPLAYS,
            'The monitor the game window and fullscreen go to, in the order the game log lists them.'),
        row('present_mode', 'Presentation mode', 'choice', core.PRESENT_MODES),
        row('hdr', 'HDR output', 'toggle'),
    ],
    'Game': [
        row('game_dir', 'Game folder (contains eboot.bin)', 'folder'),
        row('user_dir', 'Saves folder', 'folder'),
        row('dlc_dir', 'DLC folder (base-game dumps only, e.g. SPEXPANSIONDLC03)', 'folder'),
        row('language', 'Game language', 'choice', core.LANGUAGES),
        row('voice_language', 'Voice language', 'choice', core.VOICE_LANGUAGES,
            'As in the game uses the original voice setting; other choices use available tracks.'),
        row('player_name', 'Hunter name'),
        *[row(key, title[0], 'toggle') for key, title, _ in core.EXTRAS[:1]],
    ],
    'Controller': [
        row('mouse_camera', 'Mouse camera (click the game window to use it)', 'toggle'),
        row('mouse_menu', "Mouse pointer in the game's menus (hover, click, right-click back)", 'toggle'),
        row('mouse_sensitivity', 'Mouse sensitivity', 'choice', core.MOUSE_SPEEDS),
        row('mouse_invert_y', 'Invert mouse Y', 'toggle'),
        row('mouse_hide_cursor', 'Hide the mouse cursor in the game (for mouse-to-controller tools)', 'toggle'),
        row('move_smoothing', 'Keyboard movement smoothing (WASD direction changes)', 'choice',
            core.MOVE_SMOOTHING),
        row('debug_camera', 'Free camera', 'toggle', hint=OFF_ONLINE),
        row('debug_menu', 'Debug menu', 'toggle', hint=OFF_ONLINE),
    ],
    'Cheats': [
        *[row(key, title[0], 'toggle', hint=OFF_ONLINE) for key, title, _ in core.CHEATS],
        *[row(key, title[0], 'toggle') for key, title, _ in core.TWEAKS],
    ],
    'Online': [
        row('online_upnp', 'UPnP', 'toggle',
            hint='Opens a port on your router for summons. Turn it off on Tailscale or another VPN.'),
    ],
    'Co-op': [
        row('coop_name', 'Co-op name', hint='Your name in co-op, 3-16 letters, numbers, - or _.'),
        row('coop_password', 'Co-op password', 'password',
            hint="For your co-op account on the host's server. Use one you use nowhere else."),
        row('coop_invite', 'Host invite code',
            hint='Paste the BBCOOP- code your host sent you. Leave empty when you host.'),
    ],
    'Mods': [
        row('mods_enabled', 'Enable mods', 'toggle'),
        row('mods_dir', 'Mods folder', 'folder'),
        row('patches_dir', 'External patches folder', 'folder'),
    ],
    'Enhancements': [
        *[row(key, title[0], 'toggle') for key, title, _ in core.ENHANCEMENTS],
    ],
    'Atlas': [
        *[row(key, title[0], 'toggle') for key, title, _ in core.ATLAS],
        row('atlas_npc_mode', 'NPC markers', 'choice', core.ATLAS_NPC_MODES),
    ],
    # Launch behaviour (launchDirectly, close_on_play, shortcuts) lives on Home; the update
    # toggle has its own row with "Check now" in Main.qml.
    'Advanced': [
        row('ui_language', 'Launcher language', 'choice', [('', ('System default',))] + core.UI_LANGUAGES),
        row('draw_pipe', 'Draw pipeline', 'choice', core.DRAW_PIPE),
        row('readbacks', 'GPU readbacks', 'choice', core.READBACKS),
        row('extra_env', 'Extra environment variables'),
    ],
    'Diagnostics': [
        row('frame_stats', 'Frame statistics', 'toggle'),
        row('gpu_profile', 'GPU profiling', 'toggle'),
        row('vk_validation', 'Vulkan validation', 'toggle'),
    ],
}

# The Settings workspace groups the existing controls by player task. The legacy
# field definitions remain the single source for control types and options.
SETTINGS_SECTIONS = {
    'Visuals': [
        ('Display & frame rate', ['output_res', 'hud_position', 'fullscreen', 'fullscreen_mode', 'display', 'hdr', 'fps_mode', 'frame_cap',
                                  'frames_ahead', 'present_mode']),
        ('Upscaling', ['upscaler', 'preset', 'live_resolution', 'sharpen', 'sharpness',
                       'object_motion']),
        ('Frame generation', ['frame_gen', 'frame_gen_multiplier', 'frame_gen_fit_display']),
        ('Image effects', ['model_lod'] + [key for key, _, _ in core.EFFECTS]),
        ('Video memory', ['vram_budget_mb']),
        ('Overlay', ['show_fps']),
    ],
    'Controls': [
        ('Button prompts', []),
        ('Key bindings', []),
        ('Mouse', ['mouse_camera', 'mouse_menu', 'mouse_sensitivity', 'mouse_invert_y', 'mouse_hide_cursor']),
        ('Keyboard', ['move_smoothing']),
    ],
    'Game & Saves': [
        ('Game files', ['game_dir', 'dlc_dir']),
        ('Your data', ['user_dir']),
        ('In-game preferences', ['language', 'voice_language', 'player_name'] + [key for key, _, _ in core.EXTRAS[:1]]),
    ],
    # Online is The Hunter's Dream only; how PLAY starts the game is chosen on the Home page.
    'Online': [
        ("The Hunter's Dream", ['online_upnp']),
    ],
    'Co-op': [
        ('Seamless co-op', ['coop_name', 'coop_password']),
        ('Host a session', []),
        ('Join a host', ['coop_invite']),
    ],
    'Mods & Patches': [
        ('Installed mods', ['mods_enabled', 'mods_dir']),
        ('Built-in enhancements', [key for key, _, _ in core.ENHANCEMENTS]),
        ("Hunter's Atlas (map)", [key for key, _, _ in core.ATLAS] + ['atlas_npc_mode']),
        ('External patches', ['patches_dir']),
        ('Gameplay patches', [key for key, _, _ in core.CHEATS] + [key for key, _, _ in core.TWEAKS]),
    ],
    'System': [
        ('Launch', ['ui_language']),
        ('Updates', []),
        ('Engine', ['draw_pipe', 'readbacks', 'extra_env']),
        ('Developer', ['debug_camera', 'debug_menu', 'frame_stats', 'gpu_profile', 'vk_validation']),
        ('Maintenance', []),
        ('Logs', []),
    ],
}
SETTING_FIELDS = {field['key']: field for fields in FIELDS.values() for field in fields}
SEARCH_TERMS = {
    'output_res': 'screen resolution display', 'fps_mode': 'fps frame rate',
    'frame_cap': 'fps limit unlocked', 'upscaler': 'dlss fsr taa',
    'vram_budget_mb': 'vram video memory texture cache pressure budget',
    'user_dir': 'save folder save path', 'game_dir': 'eboot install game files',
    'online_npid': 'account id username', 'mouse_camera': 'camera controls', 'mouse_menu': 'cursor pointer click menus',
    'mouse_hide_cursor': 'cursor pointer hide invisible',
    'ui_language': 'launcher language', 'mods_enabled': 'load mods',
}
SEARCH_ACTIONS = [
    ('Controls', 'Button prompts', 'Xbox and PlayStation prompts', 'button controller'),
    ('Visuals', 'Upscaling', 'Download FSR 4 assets', 'fsr shader'),
    ('Game & Saves', 'Game files', 'Install from ZIP / PKG', 'game files setup'),
    ('Game & Saves', 'Your data', 'Import trophy keys', 'keys.json trophies'),
    ('Game & Saves', 'Your data', 'Open saves folder', 'save path'),
    ('Online', "The Hunter's Dream", 'Sign in with Discord', 'discord account hunters dream thd online'),
    ('Mods & Patches', 'Installed mods', 'Refresh mods', 'load order'),
    ('System', 'Launch', 'Desktop shortcut', 'start menu'),
    ('System', 'Launch', 'Add to Steam', 'integration'),
    ('System', 'Logs', 'Copy log', 'activity diagnostics'),
    ('System', 'Maintenance', 'Clear shader cache', 'shaders'),
]

LAUNCHER_ROUTE = {'mode': 'launcher', 'page': 'Home', 'step': 0, 'problem': ''}


class LauncherBackend(QObject):
    changed = Signal()
    logChanged = Signal()
    noticeChanged = Signal()
    runningChanged = Signal()
    closeRequested = Signal()
    updateAvailable = Signal(str, str, str)
    workerNotice = Signal(str)
    gpuDetected = Signal(str)
    connectionResult = Signal(str)
    setupRunningChanged = Signal()
    setupCompleted = Signal(str)
    setupFailed = Signal(str)
    coopChanged = Signal()
    _coopDone = Signal(str)
    _coopProgress = Signal(str)
    thdChanged = Signal()
    playModeChanged = Signal()
    _thdUpdate = Signal(str, str)        # status, code
    _thdDone = Signal(str, str, str)     # error, online id, token
    gameStarted = Signal()
    gameFinished = Signal(int, bool)  # exit code, whether the game got as far as running
    presetApplied = Signal()
    _repairDone = Signal(str, str)  # error, notice

    def __init__(self, route=None):
        super().__init__()
        self.app = core.app_settings(core.load_json(core.CONFIG_FILE, {}))
        for signal in (self.changed, self.coopChanged, self.thdChanged):
            signal.connect(self.playModeChanged)
        self._route = dict(route or LAUNCHER_ROUTE)
        self._atlas_progress = ''  # Hunter's Atlas: the map preparation's progress line
        self._problem = self._route.get('problem', '')
        self._game_started = False
        self._checks_started = False
        self.ini, self.ini_lines = core.load_ini()
        self._remember_written()
        self.process = None
        self.job = None
        self._log = ''
        self._notice = 'Ready to hunt.'
        self._mods = []
        self._patches = []
        # A newer release found earlier (a direct launch checks quietly): shown at once.
        self._update = core.remembered_update() if self.app.get('check_updates') else None
        self._settings_revision = 0
        self._gpu_status = 'Checking graphics card…'
        self._setup_running = False
        # Files of the port folder run.py needs but cannot find (#171); Repair puts them back.
        self._missing = core.missing_port_files()
        self._repairing = False
        if self._missing:
            self._notice = self._incomplete_text()
        self._repairDone.connect(self._repair_finished)
        self.workerNotice.connect(self._set_notice)
        self.updateAvailable.connect(self._offer_update)
        self.gpuDetected.connect(self._set_gpu_status)
        self.connectionResult.connect(self._show_connection_result)
        self.setupCompleted.connect(self._complete_game_setup)
        self.setupFailed.connect(self._fail_game_setup)
        # Seamless co-op (bbport_coop): the servers this launcher hosts, and the last message.
        self._coop_host = coop.Host()
        self._coop_busy = False
        self._coop_status = ''
        self._coop_invite = ''
        self._coop_launch_env = None
        self._coopDone.connect(self._coop_finished)
        self._coopProgress.connect(self._coop_show_progress)
        # The Hunter's Dream's Discord sign-in (a code approved on its website).
        self._thd_status = ''
        self._thd_code = ''
        self._thd_busy = False
        self._thd_cancel = False
        self._thdUpdate.connect(self._thd_update)
        self._thdDone.connect(self._thd_finished)
        self.refresh_addons()
        if self._route['mode'] != 'direct':
            self.start_background_checks()

    def start_background_checks(self):
        """GPU detection and the update check, once the launcher window is shown; a direct
        launch skips them so nothing competes with the game starting."""
        if self._checks_started:
            return
        self._checks_started = True
        threading.Thread(target=self._detect_gpu, daemon=True).start()
        if self.app.get('check_updates'):
            self.checkForUpdates(False)

    @Property(str, notify=noticeChanged)
    def notice(self):
        return self._notice

    @Property(str, constant=True)
    def version(self):
        return core.VERSION

    @Property(str, notify=logChanged)
    def log(self):
        return self._log

    @Property(bool, notify=runningChanged)
    def running(self):
        return self.process is not None

    @Property(bool, notify=setupRunningChanged)
    def setupRunning(self):
        return self._setup_running

    # --- First-run setup and start-up routing -------------------------------------------------

    def open_at(self, page, step=0):
        """Page (and wizard step) the launcher window opens on; set before loading Main.qml."""
        self._route.update(page=page, step=step)

    @Property(str, constant=True)
    def startPage(self):
        return self._route['page']

    @Property(int, constant=True)
    def wizardStartStep(self):
        return self._route['step']

    def _problem_active(self):
        if self._problem == 'game':
            return not bbport_startup.game_ok(self.app)
        if self._problem == 'saves':
            return not bbport_startup.writable(bbport_startup.saves_folder(self.app, core.DATA_DIR))
        return False

    @Property(str, notify=changed)
    def startupProblem(self):
        """Banner text while the start-up problem persists; empty once fixed or dismissed."""
        return bbport_startup.PROBLEMS[self._problem][0] if self._problem_active() else ''

    @Property(int, notify=changed)
    def fixStep(self):
        return bbport_startup.PROBLEMS.get(self._problem, ('', 1))[1]

    @Property(bool, notify=changed)
    def launchDirectly(self):
        return bool(self.app.get('launchDirectly'))

    @Property(bool, notify=changed)
    def closeOnPlay(self):
        return bool(self.app.get('close_on_play'))

    @Slot(str, str, result=bool)
    def confirm(self, title, text):
        answer = QMessageBox.question(None, title, text,
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        return answer == QMessageBox.StandardButton.Yes

    @Slot()
    def dismissProblem(self):
        self._problem = ''
        self.changed.emit()

    @Slot()
    def completeSetup(self):
        self.app.update(setupCompleted=True, setupSkipped=False, setupVersion=bbport_startup.SETUP_VERSION)
        self._write()

    @Slot()
    def skipSetup(self):
        self.app.update(setupSkipped=True, setupVersion=bbport_startup.SETUP_VERSION)
        if not bbport_startup.game_ok(self.app):
            self._problem = 'game'
        self._write()

    @Property(str, notify=changed)
    def gameStatus(self):
        info = core.game_info(self.app.get('game_dir'))
        return f'Game ready · version {info[1]}' if info else 'Choose your game folder to begin'

    @Property(str, notify=changed)
    def setupSummary(self):
        return (f"{self.ini.get('output_res', '1920x1080').replace('x', ' × ')}  ·  "
                f"{self.app.get('fps_mode', '120').upper()} FPS  ·  "
                f"{self.ini.get('upscaler', 'dlss').upper()}")

    @Property('QVariantMap', notify=changed)
    def setupFacts(self):
        fps = str(self.app.get('fps_mode', '120'))
        return {
            'resolution': self.ini.get('output_res', '1920x1080').replace('x', ' × '),
            'frameRate': 'Unlocked' if fps == 'uncap' else f'{fps} FPS',
            'upscaler': str(self.ini.get('upscaler', 'dlss')).upper(),
            'display': 'Fullscreen' if self.app.get('fullscreen') else 'Windowed',
        }

    @Slot(result=bool)
    def controllerConnected(self):
        try:
            xinput = ctypes.windll.xinput1_4
            return any(xinput.XInputGetState(index, ctypes.create_string_buffer(16)) == 0
                       for index in range(4))
        except (AttributeError, OSError):
            return False

    @Property(str, notify=changed)
    def gameFolder(self):
        return str(self.app.get('game_dir', ''))

    @Property(str, notify=changed)
    def saveStatus(self):
        return self.readiness[2]['detail']

    @Property(bool, notify=changed)
    def savesWritable(self):
        return bbport_startup.writable(bbport_startup.saves_folder(self.app, core.DATA_DIR))

    @Property(bool, notify=changed)
    def onlineIdInvalid(self):
        return False  # the shadNet account fields are gone; PLAY checks playModeBlocked

    @Property('QVariantList', notify=changed)
    def readiness(self):
        return check_readiness(self.app.get('game_dir'),
                               self.app.get('user_dir') or core.DATA_DIR / 'user',
                               core.game_info)

    @Slot()
    def refreshReadiness(self):
        self.changed.emit()

    @Property(str, notify=changed)
    def gpuStatus(self):
        return self._gpu_status

    @Slot(str)
    def _set_gpu_status(self, status):
        self._gpu_status = status
        self.changed.emit()

    # --- Graphics presets (core.GRAPHICS_PRESETS) ---------------------------------------------

    @Property(str, notify=changed)
    def graphicsPreset(self):
        return core.graphics_preset_of(self.ini, self.app)

    @Property(str, notify=changed)
    def recommendedPreset(self):
        return core.recommended_graphics_preset(self._gpu_status) or ''

    @Slot(str, result=str)
    def presetLabel(self, name):
        return core.GRAPHICS_PRESET_INFO.get(name, ('', ''))[0]

    @Slot(str, result=str)
    def presetDescription(self, name):
        return core.GRAPHICS_PRESET_INFO.get(name, ('', ''))[1]

    @Property(int, notify=presetApplied)
    def settingsRevision(self):
        """Bumped when a preset rewrites several rows at once, so the pages rebuild them."""
        return self._settings_revision

    @Slot(str)
    def applyGraphicsPreset(self, name):
        if name not in core.GRAPHICS_PRESETS:
            return
        core.apply_graphics_preset(name, self.ini, self.app)
        self._write()
        self._settings_revision += 1
        self.presetApplied.emit()
        label = core.GRAPHICS_PRESET_INFO[name][0]
        self._set_notice(f'{label} preset chosen. Restart the game to apply it.' if self.running else
                         f'{label} preset chosen. It applies the next time the game starts.')

    def _detect_gpu(self):
        exe = core.PORT_DIR / 'bin' / 'bb-gpu-capabilities.exe'
        if not exe.is_file():
            exe = core.PORT_DIR / 'out' / 'bb-gpu-capabilities.exe'
        if not exe.is_file():
            self.gpuDetected.emit('Graphics card check unavailable')
            return
        env = dict(os.environ)
        clang = next((p / 'msys64' / 'clang64' / 'bin' for p in core.PORT_DIR.parents
                      if (p / 'msys64' / 'clang64' / 'bin').is_dir()), None)
        if clang:
            env['PATH'] = str(clang) + os.pathsep + env.get('PATH', '')
        try:
            result = subprocess.run([str(exe), '--live-resolution'], capture_output=True, text=True,
                                    timeout=30, env=env, creationflags=core.NO_WINDOW)
            names = [line[5:].split(':')[0] for line in result.stderr.splitlines() if line.startswith('GPU: ')]
            self.gpuDetected.emit(names[0] if names else 'Vulkan graphics card not detected')
        except (OSError, subprocess.TimeoutExpired):
            self.gpuDetected.emit('Graphics card check unavailable')

    @Property('QVariantList', notify=changed)
    def mods(self):
        return self._mods

    @staticmethod
    def _is_prompt_mod(name):
        return (('xbox' in name.lower() and 'prompt' in name.lower()) or name == core.KEYBOARD_PROMPTS
                or name in core.LEGACY_PROMPT_MODS)

    @Property('QVariantList', notify=changed)
    def contentMods(self):
        """Mods for the Mods page; the button prompt mod is chosen on the Controller page."""
        return [m for m in self._mods if not self._is_prompt_mod(m['name'])]

    @Property('QVariantList', notify=changed)
    def patches(self):
        return self._patches

    @Property(str, notify=changed)
    def promptChoice(self):
        """From the mods in use, so a choice made in the game's overlay shows here too."""
        enabled = {m['name'] for m in self._mods if self._is_prompt_mod(m['name']) and m['enabled']}
        if enabled & {core.KEYBOARD_PROMPTS, core.LEGACY_KEYBOARD_PROMPTS}:
            return 'Keyboard'
        return 'Xbox' if enabled else 'PlayStation'

    @Property(str, notify=changed)
    def fsrStatus(self):
        missing = core.fsr4_missing()
        return 'FSR 4 assets ready' if not missing else f'{len(missing)} FSR 4 assets missing'

    def scene_size_text(self):
        """The size the game renders at before upscaling (patches.py scaled_sizes), so a soft
        image at 4K is explained: Balanced renders 3840x2160 at 2258x1270."""
        try:
            w, h = (int(v) for v in str(self.ini.get('output_res', '1920x1080')).lower().split('x'))
        except ValueError:
            return ''
        scale = 1.0
        if self.ini.get('upscaler', 'dlss') not in ('off', 'taa'):
            try:
                scale = core.PRESET_SCALE_VALUES[int(self.ini.get('preset', '0') or 0)]
            except (ValueError, IndexError):
                return ''
        rw, rh = (max(2, round(v / scale / 2) * 2) for v in (w, h))
        if scale == 1.0:
            return f'Now: the game renders at the output size, {w} × {h}.'
        return f'Now: the game renders at {rw} × {rh} and upscales it to {w} × {h}.'

    def live_field(self, field):
        if field['key'] == 'preset':
            return {**field, 'hint': f"{field['hint']} {self.scene_size_text()}".strip()}
        return field

    @Slot(str, result='QVariantList')
    def fields(self, page):
        # The revision makes the rows differ after a preset, so the page builds them anew.
        return [{**self.live_field(field), 'revision': self._settings_revision} for field in FIELDS.get(page, [])]

    @Slot(str, result='QVariantList')
    def categorySections(self, category):
        return [name for name, _ in SETTINGS_SECTIONS.get(category, [])]

    @Slot(str, str, result='QVariantList')
    def sectionFields(self, category, section):
        for name, keys in SETTINGS_SECTIONS.get(category, []):
            if name == section:
                # The revision makes the rows differ after a preset, so the page builds them anew.
                return [{**self.live_field(SETTING_FIELDS[key]), 'revision': self._settings_revision}
                        for key in keys]
        return []

    @Slot(str, result='QVariantList')
    def searchSettings(self, query):
        words = query.lower().split()
        if not words:
            return []
        results = []

        def add(category, section, label, key='', terms=''):
            label_text = f'{label} {terms} {SEARCH_TERMS.get(key, "")}'.lower()
            section_text = section.lower()
            category_text = category.lower()
            haystack = f'{label_text} {section_text} {category_text}'
            if all(word in haystack for word in words):
                score = sum(4 if word in label_text else 2 if word in section_text else 1
                            for word in words)
                results.append((score, {'category': category, 'section': section,
                                        'label': label, 'key': key}))

        for category, sections in SETTINGS_SECTIONS.items():
            for section, keys in sections:
                candidates = [(key, SETTING_FIELDS[key]['label']) for key in keys]
                if not keys:
                    candidates = [('', section)]
                for key, label in candidates:
                    add(category, section, label, key)
        for category, section, label, terms in SEARCH_ACTIONS:
            add(category, section, label, '', terms)
        return [item for _, item in sorted(results, key=lambda result: -result[0])[:30]]

    @Slot(str, result='QVariant')
    def value(self, key):
        return self.ini.get(key, '') if key in core.INI_DEFAULTS else self.app.get(key, '')

    def _remember_written(self):
        """What settings.json and bbport.ini held when this launcher last read or wrote them."""
        self._written_app = json.loads(json.dumps(self.app))
        self._written_ini = dict(self.ini)

    def _sync_from_disk(self):
        """Takes what the game wrote while the launcher was open: the in-game menu saves to
        bbport.ini and the in-game Fullscreen switch to settings.json. A value the launcher changed
        itself since its last write stays; any other the launcher would have written back over the
        game's (after Supermedo 40a883e, ethan; Awaken's 0.9.30 release notes)."""
        saved = core.load_json(core.CONFIG_FILE, None)
        if isinstance(saved, dict) and saved:
            for key, value in core.app_settings(saved).items():
                if self.app.get(key) == self._written_app.get(key) and value != self._written_app.get(key):
                    self.app[key] = value
        disk, lines = core.load_ini()
        for key, value in disk.items():
            if self.ini.get(key) == self._written_ini.get(key) and value != self._written_ini.get(key):
                self.ini[key] = value
        self.ini_lines = lines

    def _write(self):
        self._sync_from_disk()
        core.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        core.CONFIG_FILE.write_text(json.dumps(self.app, indent=2, ensure_ascii=False), encoding='utf-8')
        core.save_ini({k: self.ini[k] for k in core.INI_DEFAULTS}, self.ini_lines)
        self.ini, self.ini_lines = core.load_ini()
        self._remember_written()
        self.changed.emit()

    @Slot()
    def installFromArchive(self):
        if self._setup_running or self.running:
            self._set_notice('Close the game or wait for the current setup to finish.')
            return
        source, _ = QFileDialog.getOpenFileName(
            None, 'Step 1: choose the game ZIP or the BASE game PKG (CUSA03173.pkg, not the update)', str(Path.home() / 'Downloads'),
            'Game archive or base PKG (*.zip *.pkg)')
        if not source:
            return
        update = None
        if Path(source).suffix.casefold() == '.pkg':
            update, _ = QFileDialog.getOpenFileName(
                None, 'Step 2: choose the plain 1.09 UPDATE PKG (not 720p or 1080p)', str(Path(source).parent), 'Update PKG (*.pkg)')
            # Game of the Year PKGs may already hold 1.09: no separate update then (#43).
            if not update and QMessageBox.question(
                    None, 'No update PKG',
                    f'Is {Path(source).name} already updated to 1.09 (a PKG with the update merged in)?\n\n'
                    'Yes installs it without an update PKG; the installer checks the version.') != QMessageBox.Yes:
                return
        parent = QFileDialog.getExistingDirectory(
            None, 'Last step: choose where to create the CUSA03173 game folder', str(Path.home()))
        if not parent:
            return
        target = Path(parent) / 'CUSA03173'
        if target.exists():
            QMessageBox.warning(None, 'Game folder already exists',
                                f'{target} already exists. Choose another location so no game files are replaced.')
            return
        extractor = core.PORT_DIR / 'tools' / 'pkg-extractor' / 'pkg_extractor.exe'
        if not extractor.is_file() and not core.FROZEN:
            extractor = core.PORT_DIR / 'out' / 'vendor' / 'pkg-extractor' / 'pkg_extractor.exe'
        self._setup_running = True
        self.setupRunningChanged.emit()
        self._set_notice('Preparing your game files. Keep the launcher open…')

        def work():
            try:
                installed = install_game(source, parent, extractor, update, self.workerNotice.emit)
                self.setupCompleted.emit(str(installed))
            except PackageSetupError as error:
                self.setupFailed.emit(str(error))
            except Exception as error:
                self.setupFailed.emit(f'Unexpected installer error: {error}')
        threading.Thread(target=work, daemon=True).start()

    @Slot(str)
    def _complete_game_setup(self, folder):
        self.app['game_dir'] = folder
        self._write()
        self._setup_running = False
        self.setupRunningChanged.emit()
        info = core.game_info(folder)
        if info and info[1] == '01.09':
            self._set_notice('Game installed and version 1.09 verified. Press PLAY.')
        else:
            self._set_notice('Game installed. Check that the launcher reports version 1.09 before playing.')

    @Slot(str)
    def _fail_game_setup(self, message):
        self._setup_running = False
        self.setupRunningChanged.emit()
        self._set_notice(message)
        QMessageBox.warning(None, 'Game installation could not finish', message)

    @Slot(str, 'QVariant')
    def setValue(self, key, value):
        if key not in core.APP_DEFAULTS and key not in core.INI_DEFAULTS:
            return
        if key in core.INI_DEFAULTS:
            if key in core.INI_FLAGS:
                value = '1' if value in (True, 1, '1', 'true') else '0'
            elif key == 'sharpness':
                try:
                    value = f'{max(0.0, min(1.0, float(value))):.2f}'
                except (ValueError, TypeError):
                    value = self.ini.get(key, '0.50')
            self.ini[key] = str(value)
            if key in ('upscaler', 'preset', 'output_res'):
                self._settings_revision += 1  # the preset's hint names the new scene size
        else:
            self.app[key] = value
        self._write()

    @Slot(str, result=bool)
    def checked(self, key):
        value = self.value(key)
        return value is True or value == '1'

    # --- Keyboard and mouse bindings (Controls > Key bindings) --------------------------------
    # The game reads key_<action>= lines from bbport.ini (src/input_bindings.c). Each action
    # takes up to three bindings and a binding up to three inputs held together, which is what
    # the page's slots show; a change is written at once and applies the next time the game starts.
    @Property('QVariantList', notify=changed)
    def bindings(self):
        values = bindings_config.read(core.ini_path())
        rows = []
        for action, label, defaults in bindings_config.ACTIONS:
            slots = values.get(action, defaults)
            cells = []
            for index in range(bindings_config.SLOTS):
                binding = slots[index] if index < len(slots) else []
                cells.append({
                    'text': bindings_config.pretty_binding(binding) if binding else '—',
                    'bound': bool(binding),
                    'value': bindings_config.format_value([binding]) if binding else '',
                })
            rows.append({'action': action, 'label': label, 'slots': cells,
                         'summary': bindings_config.summary(slots)})
        return rows

    def _binding_slots(self, action):
        values = bindings_config.read(core.ini_path())
        slots = [list(binding) for binding in values.get(action, [])]
        while len(slots) < bindings_config.SLOTS:
            slots.append([])
        return slots

    def _save_binding_slots(self, action, slots):
        bindings_config.write(core.ini_path(), action, slots)
        self.ini_lines = core.load_ini()[1]
        self.changed.emit()

    @Slot(str, int, str)
    def setBinding(self, action, slot, value):
        """Slot SLOT of ACTION becomes VALUE ("Left Shift+Mouse1", "X", "Mouse2")."""
        if action not in bindings_config.ACTION_LABELS or not 0 <= slot < bindings_config.SLOTS:
            return
        slots = self._binding_slots(action)
        inputs = [part.strip() for part in str(value).split('+') if part.strip()]
        slots[slot] = inputs[:bindings_config.COMBO_PARTS]
        self._save_binding_slots(action, slots)

    @Slot(str, int)
    def clearBinding(self, action, slot):
        if action not in bindings_config.ACTION_LABELS or not 0 <= slot < bindings_config.SLOTS:
            return
        slots = self._binding_slots(action)
        slots[slot] = []
        self._save_binding_slots(action, slots)

    @Slot()
    def resetBindings(self):
        """Back to the keys bbport ships with: the key_ lines are removed."""
        bindings_config.remove_all(core.ini_path())
        self.ini_lines = core.load_ini()[1]
        self.changed.emit()

    @Slot(str, int, int, bool, result=str)
    def bindingText(self, action, slot, qt_key, numpad):
        """What a captured key would be written as, for the page's preview."""
        name = bindings_config.key_name(qt_key, numpad)
        return name

    @Slot(int, result=str)
    def mouseButtonName(self, button):
        return bindings_config.mouse_name(button)


    @Slot()
    def importTrophyKeys(self):
        source, _ = QFileDialog.getOpenFileName(
            None, 'Choose your trophy keys.json', '',
            'JSON files (*.json)'
        )
        if not source:
            return

        try:
            data = json.loads(Path(source).read_text(encoding='utf-8-sig'))
            trophy_key = data['TrophyKeySet']['ReleaseTrophyKey']
            if not valid_trophy_key(trophy_key):
                raise ValueError('ReleaseTrophyKey must be 32 hexadecimal characters')
        except (OSError, ValueError, KeyError, TypeError) as error:
            QMessageBox.warning(None, 'Invalid trophy keys',
                                f'This is not a valid trophy keys.json: {error}')
            return

        user_dir = Path(self.app.get('user_dir') or core.DATA_DIR / 'user')
        destination = user_dir / 'keys.json'

        if destination.exists():
            if Path(source).resolve() == destination.resolve():
                self._set_notice('Trophy keys are already installed.')
                return
            answer = QMessageBox.question(
                None, 'Replace trophy keys?',
                'This folder already contains keys.json. Replace it?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        try:
            user_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        except OSError as error:
            QMessageBox.warning(None, 'Import failed', str(error))
            return

        self._set_notice('Trophy keys installed successfully.')
        self.changed.emit()
    @Slot(str)
    def browse(self, key):
        if key not in ('game_dir', 'user_dir', 'dlc_dir', 'mods_dir', 'patches_dir'):
            return
        folder = QFileDialog.getExistingDirectory(None, f'Choose {key.replace("_", " ")}', str(self.value(key) or core.DATA_DIR))
        if folder:
            old_user = Path(self.value('user_dir') or core.DATA_DIR / 'user')
            self.setValue(key, folder)
            if key == 'user_dir':
                self._carry_trophy_keys(old_user, Path(folder))
            if key in ('mods_dir', 'patches_dir'):
                self.refresh_addons()

    def _carry_trophy_keys(self, old_user, new_user):
        """The game reads keys.json from the saves folder: one imported before the saves folder
        was changed (the setup wizard asks for it first) stayed behind, and trophy names were
        missing. It moves along unless the new folder has its own."""
        source, target = old_user / 'keys.json', new_user / 'keys.json'
        if source.is_file() and not target.exists() and source.resolve() != target.resolve():
            try:
                new_user.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            except OSError as error:
                self._set_notice(f'Copy keys.json to the new saves folder yourself: {error}')
                return
            self._set_notice('Trophy keys copied to the new saves folder.')
            self.changed.emit()

    @Slot(str)
    def openFolder(self, key):
        path = self.value(key) if key else core.PORT_DIR
        if not path:
            path = core.DATA_DIR / {'user_dir': 'user', 'mods_dir': 'mods', 'patches_dir': 'patches'}.get(key, '')
        path = Path(path)
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
        os.startfile(str(path))

    def _set_notice(self, message):
        self._notice = message
        self.noticeChanged.emit()

    def _append_log(self, value):
        self._log = (self._log + value)[-350000:]
        self.logChanged.emit()

    @Slot()
    def play(self, env=None):
        if self._setup_running:
            self._set_notice('Wait for the game files to finish installing.')
            return
        if self.process:
            return
        if self._repairing:
            self._set_notice('Wait for the repair to finish.')
            return
        if self._check_port_files():
            return
        if not core.game_info(self.app.get('game_dir')):
            self._set_notice('Choose the game folder containing eboot.bin first.')
            return
        if not self.savesWritable:
            self._set_notice('Choose a writable saves folder before playing.')
            return
        if self.onlineIdInvalid:
            self._set_notice('Online ID must be your account name, not an email address.')
            return
        if (env is None and self.app.get('online') and core.hunters_dream_selected(self.app)
                and not self.thdSignedIn and not self.thdRefused):
            self._set_notice("The Hunter's Dream: sign in with Discord on the Online page first.")
            return
        self._write()
        self._log = ''
        self.logChanged.emit()
        if env is None and self.playMode == 'huntersdream' and self.thdRefused:
            self._append_log(f'{THD_REFUSED} Starting offline.\n')
        self._game_started = False
        try:
            self.process = subprocess.Popen(core.run_command(), cwd=core.PORT_DIR,
                                            env=env or core.game_environment(self.app), stdin=subprocess.DEVNULL,
                                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                            creationflags=core.NO_WINDOW)
        except OSError as error:
            self._set_notice(f'Could not start: {error}')
            self.process = None
            return
        self.job = core.GameJob(self.process)
        self.runningChanged.emit()
        self._set_notice('Preparing the game…')
        threading.Thread(target=self._read_output, args=(self.process,), daemon=True).start()
        if self.app.get('close_on_play'):
            from PySide6.QtCore import QTimer
            QTimer.singleShot(5000, self.closeRequested.emit)

    def _read_output(self, process):
        with core.open_run_log(self.app.get('user_dir') or core.DATA_DIR / 'user') as log:
            for raw in iter(process.stdout.readline, b''):
                line = raw.decode('utf-8', errors='replace')
                log.write(line)
                self._outputLine.emit(line)
        self._gameExited.emit(process.wait())

    _outputLine = Signal(str)
    _gameExited = Signal(object)  # Windows status codes do not fit a Qt int

    @Slot(str)
    def _receive_line(self, line):
        self._append_log(line)
        if core.note_game_output(line):
            self.thdChanged.emit()
        if 'Entering original x86-64 code' in line:
            if not self._game_started:
                self._game_started = True
                self.gameStarted.emit()
            self._set_notice('The game is running.')
        elif 'restarting through run.py' in line:
            self._set_notice('Restarting with the new settings…')

    @Slot(object)
    def _receive_exit(self, code):
        text = core.exit_code_text(code)
        code = core.exit_status(code)
        self._append_log(f'\n— The game exited (code {text}) —\n')
        self.process = None
        if self.job:
            self.job.close()
            self.job = None
        self.runningChanged.emit()
        self._sync_from_disk()  # what the in-game menu changed, shown at once
        self._remember_written()
        self._settings_revision += 1
        self.presetApplied.emit()  # the pages rebuild their rows with those values
        self.changed.emit()
        if self._game_started or code == 0:
            self._set_notice('Ready to hunt.')
        elif not self._check_port_files():
            self._set_notice(f'The game could not start (exit code {text}). See the log for details.')
        self.gameFinished.emit(code, self._game_started)

    def connect_workers(self):
        self._outputLine.connect(self._receive_line)
        self._gameExited.connect(self._receive_exit)

    @Slot()
    def stop(self):
        if self.job:
            self.job.terminate()

    @Slot()
    def refresh_addons(self):
        from mods import discover
        from patches import external_patches
        folder = Path(self.app.get('mods_dir') or core.DATA_DIR / 'mods')
        profile = core.load_json(core.DATA_DIR / 'mods.json', {})
        disabled = set(profile.get('disabled', []))
        names = discover(folder)
        order = [n for n in profile.get('order', []) if n in names]
        order += [n for n in sorted(names) if n not in order]
        self._mods = [{'name': n, 'enabled': n not in disabled} for n in order]
        patch_profile = core.load_json(core.DATA_DIR / 'patches.json', {})
        patch_folder = Path(self.app.get('patches_dir') or core.DATA_DIR / 'patches')
        found = external_patches(patch_folder, core.PATCH_VERSION)
        enabled = set(patch_profile.get('enabled', []))
        denied = set(patch_profile.get('disabled', []))
        self._patches = [{'name': name,
                          'enabled': name in enabled or (name not in denied and
                                       meta.get('isEnabled', 'false').lower() == 'true')}
                         for name, _path, meta in found]
        self.changed.emit()

    @Slot(str, bool)
    def setMod(self, name, enabled):
        profile_file = core.DATA_DIR / 'mods.json'
        profile_file.parent.mkdir(parents=True, exist_ok=True)
        profile = core.load_json(profile_file, {})
        names = [m['name'] for m in self._mods]
        if name not in names:
            return
        disabled = set(profile.get('disabled', []))
        (disabled.discard if enabled else disabled.add)(name)
        profile.update({'order': names, 'disabled': sorted(disabled)})
        profile_file.write_text(json.dumps(profile, indent=2), encoding='utf-8')
        self.refresh_addons()
        self._set_notice('Mod change saved. Restart the game to apply it.')

    @Slot(str, int)
    def moveMod(self, name, step):
        names = [m['name'] for m in self._mods]
        if name not in names:
            return
        index = names.index(name)
        other = index + step
        if not 0 <= other < len(names):
            return
        names[index], names[other] = names[other], names[index]
        profile_file = core.DATA_DIR / 'mods.json'
        profile_file.parent.mkdir(parents=True, exist_ok=True)
        profile = core.load_json(profile_file, {})
        profile['order'] = names
        profile_file.write_text(json.dumps(profile, indent=2), encoding='utf-8')
        self.refresh_addons()

    @Slot(str, bool)
    def setPatch(self, name, enabled):
        profile_file = core.DATA_DIR / 'patches.json'
        profile_file.parent.mkdir(parents=True, exist_ok=True)
        profile = core.load_json(profile_file, {})
        enabled_names = set(profile.get('enabled', []))
        disabled_names = set(profile.get('disabled', []))
        (enabled_names.add if enabled else enabled_names.discard)(name)
        (disabled_names.discard if enabled else disabled_names.add)(name)
        profile.update({'enabled': sorted(enabled_names), 'disabled': sorted(disabled_names)})
        profile_file.write_text(json.dumps(profile, indent=2), encoding='utf-8')
        self.refresh_addons()

    def _mods_dir(self):
        return Path(self.app.get('mods_dir') or core.DATA_DIR / 'mods')

    @Slot(str)
    def setPrompt(self, choice):
        """Xbox and Keyboard: Kenney's prompt images, written into the game's own
        menu/common.tpf.dcx the first time (core.install_prompt_pack); Keyboard also binds the keys
        its images show in bbport.ini. PlayStation: the game's own."""
        if choice not in ('Xbox', 'PlayStation', 'Keyboard'):
            return
        names = [m['name'] for m in self._mods if self._is_prompt_mod(m['name'])]
        if choice in core.PROMPT_PACKS and core.PROMPT_PACKS[choice][0] not in names:
            try:
                core.install_prompt_pack(choice, self.app.get('game_dir'), self._mods_dir())
            except (OSError, ValueError) as error:
                self._set_notice(str(error))
                return
            self.refresh_addons()
            names = [m['name'] for m in self._mods if self._is_prompt_mod(m['name'])]
        profile_file = core.DATA_DIR / 'mods.json'
        profile_file.parent.mkdir(parents=True, exist_ok=True)
        profile = core.load_json(profile_file, {})
        disabled, enabled = set(profile.get('disabled', [])), set(profile.get('enabled', []))
        chosen = [core.PROMPT_PACKS[choice][0]] if choice in core.PROMPT_PACKS else []
        for name in names:
            (disabled.discard if name in chosen else disabled.add)(name)
            (enabled.add if name in chosen else enabled.discard)(name)
        profile.update({'enabled': sorted(enabled), 'disabled': sorted(disabled)})
        profile_file.write_text(json.dumps(profile, indent=2), encoding='utf-8')
        if choice == 'Keyboard':  # the keys the images show
            core.save_ini(core.KEYBOARD_PROMPT_LAYOUT, self.ini_lines)
            self.ini, self.ini_lines = core.load_ini()
        self.refresh_addons()
        self._set_notice(f'{choice} button prompts selected. Restart the game to apply them.'
                         + (' Keys now match the prompt images (E interact, Left Shift dodge, Q item, F transform).'
                            if choice == 'Keyboard' else ''))

    @Property(str, notify=changed)
    def atlasStatus(self):
        if self._atlas_progress:
            return self._atlas_progress
        sys.path.insert(0, str(core.PORT_DIR / 'scripts'))
        import atlas
        return ('Maps ready.' if atlas.ready(core.ATLAS_DIR) else
                'Maps not prepared yet: Prepare maps makes them from your game (5-15 minutes, once).')

    @Slot()
    def prepareAtlas(self):
        """Hunter's Atlas: the maps from the player's own game (scripts/atlas.py prepare)."""
        if self._atlas_progress:
            return
        game = self.app.get('game_dir')
        self._atlas_progress = 'Preparing maps…'
        self.changed.emit()

        def work():
            import json as json_lines
            sys.path.insert(0, str(core.PORT_DIR / 'scripts'))
            import atlas

            def progress(line):
                try:
                    record = json_lines.loads(line)
                except ValueError:
                    return
                if 'progress' in record:
                    self._atlas_progress = f"Preparing maps: {record['progress']}% · {record.get('stage', '')}"
                    self.changed.emit()
            try:
                atlas.prepare(game, core.ATLAS_DIR, progress)
                message = "Hunter's Atlas maps ready. Turn the map on and play: Map is in the game's quick menu."
            except (OSError, ValueError, RuntimeError) as error:
                message = f'Preparing the maps failed: {error}'
            self._atlas_progress = ''
            self.workerNotice.emit(message)
            self.changed.emit()
        threading.Thread(target=work, daemon=True).start()

    @Slot()
    def downloadFsr4(self):
        missing = core.fsr4_missing()
        if not missing:
            self._set_notice('FSR 4 assets are already installed.')
            return
        self._set_notice(f'Downloading {len(missing)} FSR 4 files…')
        def work():
            try:
                folder = core.PORT_DIR / 'fsr4_shaders'
                folder.mkdir(parents=True, exist_ok=True)
                for name in missing:
                    part = folder / (name + '.part')
                    with urllib.request.urlopen(f'{core.FSR4_BASE}/{name}', timeout=60) as reply:
                        part.write_bytes(reply.read())
                    part.replace(folder / name)
                self.workerNotice.emit('FSR 4 assets installed.')
            except OSError as error:
                self.workerNotice.emit(f'FSR 4 download failed: {error}')
            self.changed.emit()
        threading.Thread(target=work, daemon=True).start()

    @Slot(bool)
    def checkForUpdates(self, manual=True):
        def work():
            try:
                version, url, page = core.latest_release()
                if core.release_is_newer(version):
                    self.updateAvailable.emit(version, url or '', page)
                else:
                    self.updateAvailable.emit('', '', '')  # forget a remembered one
                    if manual:
                        self.workerNotice.emit(f'You have the latest version ({core.VERSION}).')
            except (OSError, ValueError, KeyError) as error:
                if manual:
                    self.workerNotice.emit(f'Could not check for updates: {error}')
        threading.Thread(target=work, daemon=True).start()

    @Slot(str, str, str)
    def _offer_update(self, version, url, page):
        if not version:
            if self._update:
                self._update = None
                self.noticeChanged.emit()
            return
        self._update = (version, url or None, page)
        self._set_notice(f'Version {version} is available.')

    @Property(bool, notify=noticeChanged)
    def hasUpdate(self):
        return self._update is not None

    @Property(str, notify=noticeChanged)
    def updateVersion(self):
        return self._update[0] if self._update else ''

    @Slot()
    def viewRelease(self):
        webbrowser.open(self._update[2] if self._update else core.RELEASES_PAGE)

    @Slot()
    def installUpdate(self):
        if not self._update:
            self.checkForUpdates(True)
            return
        version, url, page = self._update
        if self.running:
            self._set_notice('Close the game before updating.')
            return
        if not core.FROZEN or not url:
            webbrowser.open(page)
            return
        if QMessageBox.question(None, 'Bloodborne',
                                f'Install version {version} now? Saves, settings and mods are kept.') != QMessageBox.Yes:
            return
        def work():
            try:
                if not core.remove_update_folder():
                    raise OSError('an update is still being installed; try again in a minute')
                core.UPDATE_DIR.mkdir(parents=True, exist_ok=True)
                archive = core.UPDATE_DIR / 'update.zip'
                request = urllib.request.Request(url, headers={'User-Agent': 'bbport-launcher'})
                with urllib.request.urlopen(request, timeout=60) as reply, open(archive, 'wb') as out:
                    while chunk := reply.read(1 << 20):
                        out.write(chunk)
                core.extract_update(archive, core.UPDATE_DIR / 'new')
                new = next((p.parent for p in (core.UPDATE_DIR / 'new').rglob('Bloodborne.exe')), None)
                if not new:
                    raise OSError('Bloodborne.exe is missing from the download')
                subprocess.Popen([str(new / 'Bloodborne.exe'), '--install-update', str(core.PORT_DIR), str(os.getpid())],
                                 cwd=new, stdin=subprocess.DEVNULL, creationflags=core.NO_WINDOW)
                self.closeRequested.emit()
            except (OSError, zipfile.BadZipFile) as error:
                self.workerNotice.emit(f'Update failed: {error}')
        self._set_notice(f'Downloading version {version}…')
        threading.Thread(target=work, daemon=True).start()

    # --- Repair: an incomplete port folder ------------------------------------------------------

    def _incomplete_text(self):
        more = f' and {len(self._missing) - 1} more' if len(self._missing) > 1 else ''
        return f'This copy of the port is incomplete: {self._missing[0]}{more} missing. Repair puts the files back.'

    def _check_port_files(self):
        """True (with the notice and the Repair row shown) when port files are missing."""
        was, self._missing = self._missing, core.missing_port_files()
        if bool(was) != bool(self._missing):
            self.changed.emit()
        if self._missing:
            self._set_notice(self._incomplete_text())
        return bool(self._missing)

    @Property(bool, notify=changed)
    def portIncomplete(self):
        return bool(self._missing)

    @Property(bool, notify=changed)
    def repairing(self):
        return self._repairing

    def _repair_fallback(self, error=None):
        more = f' and {len(self._missing) - 1} more' if len(self._missing) > 1 else ''
        text = (f'This copy of the port is incomplete: {self._missing[0]}{more} missing from {core.PORT_DIR}. '
                f'Download the port again from {core.RELEASES_PAGE} and unpack the whole zip.') if self._missing else ''
        if error:
            text = f'Repair failed: {error}. {text}'.strip()
        self._set_notice(text)
        webbrowser.open(core.RELEASES_PAGE)

    @Slot()
    def repairPort(self):
        if self._repairing:
            return
        if self.running:
            self._set_notice('Close the game before repairing.')
            return
        if not core.FROZEN or core.COOP_TEST:
            self._repair_fallback()
            return
        if QMessageBox.question(None, 'Bloodborne', f'Download version {core.VERSION} from GitHub and put its files '
                                'back? Saves, settings and mods are kept.') != QMessageBox.Yes:
            return
        self._repairing = True
        self.changed.emit()

        def work():
            try:
                missing, failed = core.repair_port(lambda percent: self.workerNotice.emit(
                    f'Downloading version {core.VERSION}… {percent}%'))
            except OSError as error:
                self._repairDone.emit(str(error), '')
                return
            if missing:
                self._repairDone.emit('some files could not be restored', '')
            elif failed:
                self._repairDone.emit('', 'Repaired, but some files were in use and were not replaced: '
                                          f'{", ".join(map(str, failed[:3]))}.')
            else:
                self._repairDone.emit('', f'Repaired: the files of version {core.VERSION} are back.')
        self._set_notice(f'Downloading version {core.VERSION}…')
        threading.Thread(target=work, daemon=True).start()

    @Slot(str, str)
    def _repair_finished(self, error, notice):
        self._repairing = False
        self._missing = core.missing_port_files()
        self.changed.emit()
        if error:
            self._repair_fallback(error)
        else:
            self._set_notice(notice)

    @Slot()
    def createShortcut(self):
        if core.FROZEN:
            target, arguments, icon = sys.executable, '', f'{sys.executable},0'
        else:
            pythonw = Path(sys.executable).with_name('pythonw.exe')
            target = str(pythonw if pythonw.exists() else sys.executable)
            arguments = str(Path(core.__file__).resolve())
            icon = str(core.PORT_DIR / 'launcher' / 'bloodborne.ico')
        def ps_string(value):
            return "'" + str(value).replace("'", "''") + "'"
        quoted = chr(34) + arguments + chr(34) if arguments else ''

        def shortcut(folder, name, extra):
            options = ' '.join(part for part in (quoted, extra) if part)
            return (f'$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath("{folder}")'
                    f'+"\\{name}.lnk");'
                    f'$s.TargetPath={ps_string(target)};$s.WorkingDirectory={ps_string(core.PORT_DIR)};'
                    f'$s.IconLocation={ps_string(icon)};'
                    + (f'$s.Arguments={ps_string(options)};' if options else '') + '$s.Save();')
        # The Start Menu entry always opens the launcher, since a plain start may launch the game directly.
        script = shortcut('Desktop', 'Bloodborne', '') + shortcut('Programs', 'Bloodborne (Launcher)', '--launcher')
        result = subprocess.run(['powershell', '-NoProfile', '-Command', script], capture_output=True,
                                creationflags=core.NO_WINDOW)
        self._set_notice('Desktop and Start Menu shortcuts created.' if result.returncode == 0 else
                         result.stderr.decode(errors='replace')[:300])

    @Slot()
    def addToSteam(self):
        import bbport_steam
        steam = bbport_steam.steam_folder()
        configs = bbport_steam.user_configs(steam) if steam else []
        if not configs:
            self._set_notice('Steam was not found on this PC or no account has signed in.')
            return
        if core.FROZEN:
            exe, options = core.PORT_DIR / 'Play Bloodborne.exe', ''
        else:
            pythonw = Path(sys.executable).with_name('pythonw.exe')
            exe = pythonw if pythonw.exists() else Path(sys.executable)
            options = f'"{Path(core.__file__).resolve()}" --play'
        self._write()
        restart = False
        if bbport_steam.steam_running():
            if QMessageBox.question(None, 'Bloodborne',
                                    'Steam must close while the game is added. Close Steam now?') != QMessageBox.Yes:
                return
            subprocess.Popen([str(steam / 'steam.exe'), '-shutdown'], creationflags=core.NO_WINDOW)
            for _ in range(60):
                time.sleep(0.5)
                if not bbport_steam.steam_running():
                    break
            else:
                self._set_notice('Steam did not close. Close it yourself and try again.')
                return
            time.sleep(1)
            restart = True
        try:
            for config in configs:
                bbport_steam.add_shortcut(config / 'shortcuts.vdf', 'Bloodborne', str(exe), str(core.PORT_DIR),
                                          str(exe), options)
        except (OSError, ValueError) as error:
            self._set_notice(f'Could not add the game to Steam: {error}')
            return
        if restart:
            os.startfile('steam://open/games')
        self._set_notice('Bloodborne was added to your Steam library.')


    # --- Seamless co-op (experimental): BBSC, hosted on one player's PC over Tailscale -------------

    @Property(str, notify=coopChanged)
    def coopStatus(self):
        if self._coop_status:
            return self._coop_status
        if not (coop.installed('client') and coop.installed('server')):
            return 'Not set up yet: Set up co-op downloads BBSC (about 40 MB) from its GitHub release.'
        if self._coop_host.running:
            return f'Hosting on {self._coop_host.address}. Send your friend the invite code.'
        return "Ready. Host a session, or paste a host's invite code and play."

    @Property(str, notify=coopChanged)
    def coopInvite(self):
        return self._coop_invite

    @Property(bool, notify=coopChanged)
    def coopHosting(self):
        return self._coop_host.running

    @Property(bool, notify=coopChanged)
    def coopBusy(self):
        return self._coop_busy

    def _coop_run(self, message, work):
        if self._coop_busy:
            return
        self._coop_busy = True
        self._coop_status = message
        self.coopChanged.emit()

        def run():
            try:
                result = work()
            except (coop.CoopError, OSError, ValueError) as error:
                result = f'Co-op: {error}'
            except Exception as error:  # download and process errors: report, never crash the UI
                result = f'Co-op: {type(error).__name__}: {error}'
            self._coopDone.emit(result or '')

        threading.Thread(target=run, daemon=True).start()

    @Slot(str)
    def _coop_finished(self, message):
        self._coop_busy = False
        self._coop_status = message
        self.coopChanged.emit()
        env, self._coop_launch_env = self._coop_launch_env, None
        if env:
            self.play(env)

    def _coop_progress(self, text):
        self._coopProgress.emit(text)  # from the worker thread: queued to the UI thread

    @Slot(str)
    def _coop_show_progress(self, text):
        self._coop_status = text
        self.coopChanged.emit()

    def _coop_ensure_packages(self):
        for kind in ('client', 'server'):
            if not coop.installed(kind):
                coop.download(kind, progress=self._coop_progress)

    def _coop_game_exe(self):
        for candidate in (core.PORT_DIR / 'bin' / 'bb-probe.exe', core.PORT_DIR / 'out' / 'bb-probe.exe'):
            if candidate.is_file():
                return candidate
        raise coop.CoopError('bb-probe.exe is missing from this install.')

    def _coop_account(self):
        return self.app.get('coop_name', '').strip(), self.app.get('coop_password', '')

    @Slot()
    def openCoopHelp(self):
        webbrowser.open(coop.RELEASES)

    @Slot()
    def coopSetup(self):
        def work():
            for kind in ('client', 'server'):
                coop.download(kind, progress=self._coop_progress)
            return 'Co-op is set up. Host a session, or paste an invite code and play.'
        self._coop_run('Downloading BBSC…', work)

    @Slot()
    def coopStartHosting(self):
        name, password = self._coop_account()
        if not name or not password:
            self._coop_status = 'Fill in your co-op name and password first; they make your account on your server.'
            self.coopChanged.emit()
            return

        def work():
            self._coop_ensure_packages()
            address, network = coop.host_address()
            if not address:
                raise coop.CoopError('No network found. Connect Tailscale, then try again.')
            game = self._coop_game_exe()
            if not coop.setup_done(game):
                self._coop_progress('First time: say Yes to the Windows prompt (firewall and C++ runtime)…')
                coop.run_setup(game)
            key = coop.registration_key()
            self._coop_host.start(address)
            how = coop.create_account(address, key, name, password)
            self._coop_invite = coop.make_invite(address, key)
            return (f'Hosting on {network} ({address}); your account is {how}. Copy the invite code '
                    'for your friend, then press Play co-op. Keep this launcher open while you play.')
        self._coop_run('Starting the co-op servers…', work)

    @Slot()
    def coopStopHosting(self):
        self._coop_host.stop()
        self._coop_invite = ''
        self._coop_status = 'Stopped hosting.'
        self.coopChanged.emit()

    @Slot()
    def coopCopyInvite(self):
        if self._coop_invite:
            QGuiApplication.clipboard().setText(self._coop_invite)
            self._coop_status = 'Invite code copied. Send it to your friend in a private message.'
            self.coopChanged.emit()

    @Slot()
    def coopPlay(self):
        if self.process or self._coop_busy:
            return
        name, password = self._coop_account()
        if not name or not password:
            self._coop_status = 'Fill in your co-op name and password first.'
            self.coopChanged.emit()
            return
        if self._coop_host.running:
            address, key = self._coop_host.address, coop.registration_key()
        else:
            try:
                address, key = coop.read_invite(self.app.get('coop_invite', ''))
            except coop.CoopError as error:
                self._coop_status = f'{error}. Or host a session yourself.'
                self.coopChanged.emit()
                return
        self._write()

        def work():
            self._coop_ensure_packages()
            game = self._coop_game_exe()
            if not coop.setup_done(game):
                self._coop_progress('First time: say Yes to the Windows prompt (firewall)…')
                coop.run_setup(game)
            coop.create_account(address, key, name, password)
            backup = coop.backup_saves(self.app.get('user_dir') or core.DATA_DIR / 'user')
            self._coop_launch_env = coop.co_op_environment(core.game_environment(self.app), address,
                                                           name, password, game, save_copy=backup)
            where = f' Saves backed up to {backup}.' if backup else ''
            return f'Starting co-op with {address}. Host: ring the Hunt Bell. Guest: ring the Kin Bell.{where}'
        self._coop_run('Getting co-op ready…', work)

    def shutdown_coop(self):
        """The launcher is closing: hosted servers stop with it."""
        self._coop_host.stop()

    # --- The Hunter's Dream (BB_NET_BACKEND=thd): Discord sign-in by device code -------------------

    @Property(bool, constant=True)
    def huntersDreamPool(self):
        return core.HUNTERS_DREAM_POOL

    # --- Play mode: what PLAY starts (offline, The Hunter's Dream, seamless co-op) ----------------

    @Property(str, notify=playModeChanged)
    def playMode(self):
        return core.play_mode(self.app)

    @Slot(str)
    def setPlayMode(self, mode):
        if mode not in core.PLAY_MODES or (mode == 'huntersdream' and not core.HUNTERS_DREAM_POOL):
            return
        self.app['play_mode'] = mode
        # The game's online switch follows: on for The Hunter's Dream; co-op launches turn it on
        # for themselves, pointed at the host.
        self.app['online'] = mode == 'huntersdream'
        if mode == 'huntersdream':
            self.app['online_pool'] = 'huntersdream'
        self._write()

    def _coop_ready(self):
        name, password = self._coop_account()
        return bool(name and password and (self._coop_host.running or self.app.get('coop_invite', '').strip()))

    @Property(bool, notify=playModeChanged)
    def playModeBlocked(self):
        mode = self.playMode
        if mode == 'huntersdream':
            return not self.thdSignedIn and not self.thdRefused
        if mode == 'coop':
            return not self._coop_ready()
        return False

    @Property(str, notify=playModeChanged)
    def playModeSummary(self):
        """One line under PLAY: what it will start."""
        mode = self.playMode
        if mode == 'huntersdream':
            if self.thdRefused:
                return f'{THD_REFUSED} PLAY starts offline.'
            if self.thdSignedIn:
                return f"Online on The Hunter's Dream as {self.app.get('thd_online_id')}: messages, bloodstains and summons with everyone."
            return "Online on The Hunter's Dream: sign in with Discord first (Settings → Online)."
        if mode == 'coop':
            name, password = self._coop_account()
            if not name or not password:
                return 'Seamless co-op: choose a co-op name and password first (Settings → Co-op).'
            if self._coop_host.running:
                return f'Seamless co-op: you host on {self._coop_host.address}; send your friends the invite code.'
            if self.app.get('coop_invite', '').strip():
                return "Seamless co-op: joining your host's server from the invite code."
            return "Seamless co-op: start hosting, or paste a host's invite code (Settings → Co-op)."
        return 'Offline: your own world, no servers.'

    @Property('QVariantList', notify=playModeChanged)
    def playModeSettings(self):
        """Where the setting that blocks PLAY is: [category, section]."""
        if self.playMode == 'huntersdream':
            return ['Online', "The Hunter's Dream"]
        if self.playMode == 'coop':
            name, password = self._coop_account()
            return ['Co-op', 'Seamless co-op' if not (name and password) else 'Host a session']
        return ['Online', "The Hunter's Dream"]

    @Slot()
    def playSelected(self):
        """PLAY: the selected mode."""
        if self.playMode == 'coop':
            self.coopPlay()
        else:
            self.play()

    @Property(bool, notify=thdChanged)
    def thdSignedIn(self):
        return bool(self.app.get('thd_token') and self.app.get('thd_online_id'))

    # The Hunter's Dream refused this launcher's build (core.thd_refused): no sign-in, PLAY offline.
    @Property(bool, notify=thdChanged)
    def thdRefused(self):
        return core.HUNTERS_DREAM_POOL and core.thd_refused()

    @Property(str, notify=thdChanged)
    def thdStatus(self):
        if self.thdRefused:
            return THD_REFUSED
        if self._thd_status:
            return self._thd_status
        if self.thdSignedIn:
            return f"Signed in to The Hunter's Dream as {self.app.get('thd_online_id')}."
        return "Not signed in to The Hunter's Dream."

    @Property(str, notify=thdChanged)
    def thdCode(self):
        return self._thd_code

    @Property(bool, notify=thdChanged)
    def thdBusy(self):
        return self._thd_busy

    @Slot()
    def thdSignIn(self):
        if self._thd_busy or self.thdRefused:
            return
        self._thd_busy, self._thd_cancel, self._thd_code = True, False, ''
        self._thd_status = 'Starting the sign-in…'
        self.thdChanged.emit()
        game = self.app.get('online_community', '')

        def on_code(page, code):
            self._thdUpdate.emit('On the page that opened, sign in with Discord and approve this code '
                                 '(not in its "code from the game" box):', code)
            webbrowser.open(page)

        def work():
            try:
                name, token = core.thd_sign_in(game, on_code, lambda: self._thd_cancel)
            except (OSError, ValueError) as error:
                self._thdDone.emit(f'Sign-in failed: {core.connection_error_text(error)}', '', '')
                return
            self._thdDone.emit('', name, token)
        threading.Thread(target=work, daemon=True).start()

    @Slot(str, str)
    def _thd_update(self, status, code):
        self._thd_status, self._thd_code = status, code
        self.thdChanged.emit()

    @Slot(str, str, str)
    def _thd_finished(self, error, name, token):
        self._thd_busy, self._thd_code = False, ''
        if error:
            self._thd_status = error
        else:
            self.app['thd_online_id'], self.app['thd_token'] = name, token
            self._thd_status = ''
            self._write()
        self.thdChanged.emit()

    @Slot()
    def thdCancel(self):
        self._thd_cancel = True
        self._thd_status = 'Cancelling…'
        self.thdChanged.emit()

    @Slot()
    def thdSignOut(self):
        self.app['thd_online_id'], self.app['thd_token'] = '', ''
        self._thd_status = "Signed out of The Hunter's Dream on this PC."
        self._write()
        self.thdChanged.emit()

    @Slot()
    def thdCopyCode(self):
        if self._thd_code:
            QGuiApplication.clipboard().setText(self._thd_code)
            self._set_notice('Sign-in code copied.')

    @Slot()
    def openShadNetRegistration(self):
        webbrowser.open('https://shadps4.net/shadnet/register/')

    @Slot()
    def testConnection(self):
        if self.thdRefused:
            self.connectionResult.emit(THD_REFUSED)
            return
        self._set_notice("Testing The Hunter's Dream…")
        online_id, token = (self.app.get('thd_online_id', ''), self.app.get('thd_token', '')) \
            if self.thdSignedIn else ('', '')

        def work():
            community = core.community_address(self.app['online_community'])
            result = core.server_check_hunters_dream(community)
            result += '\n' + core.thd_account_check(community, online_id, token)
            self.connectionResult.emit(result)
        threading.Thread(target=work, daemon=True).start()

    @Slot(str)
    def _show_connection_result(self, result):
        self.thdChanged.emit()  # the check may have learned that the server refuses this build
        QMessageBox.information(None, 'Online connection', result)
        self._set_notice('Online connection test finished.')

    @Slot(str)
    def action(self, name):
        if name == 'openGame':
            self.openFolder('game_dir')
        elif name == 'openSaves':
            self.openFolder('user_dir')
        elif name == 'openMods':
            self.openFolder('mods_dir')
        elif name == 'openPort':
            self.openFolder('')
        elif name == 'openConfig':
            self._write()
            os.startfile(str(core.ini_path()))
        elif name == 'mod19':
            webbrowser.open('https://www.nexusmods.com/bloodborne/mods/19')
        elif name == 'releases':
            webbrowser.open(core.RELEASES_PAGE)
        elif name == 'clearCache':
            if self.running:
                self._set_notice('Close the game before clearing its cache.')
            else:
                shutil.rmtree(Path(self.app.get('user_dir') or core.DATA_DIR / 'user') / 'cache', ignore_errors=True)
                self._set_notice('Shader cache cleared. The next launch will rebuild it.')
        elif name == 'copyLog':
            QGuiApplication.clipboard().setText(self._log)
            self._set_notice('Log copied to clipboard.')
        elif name == 'clearLog':
            self._log = ''
            self.logChanged.emit()

