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

import bbport_launcher_win as core
import bbport_startup
import bbsc_preview
from bbport_pkg_setup import PackageSetupError, install_game
from bbport_readiness import check_readiness, valid_trophy_key


def choice_rows(options):
    return [{'value': str(value), 'text': label[0]} for value, label in options]


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
        row('live_resolution', 'Live resolution changes', 'choice', core.LIVE,
            'Lets the in-game menu change the upscaling preset without a restart, at some cost in speed.'),
        row('sharpen', 'Sharpening (RCAS)', 'toggle', hint='Sharpens the upscaled image.'),
        row('sharpness', 'Sharpness (0.00–1.00)'),
        row('object_motion', 'Object motion vectors', 'toggle',
            hint='Motion data for moving characters: fewer ghosting trails with an upscaler.'),
        row('model_lod', 'Model detail', 'choice', core.LODS,
            'How soon distant models switch to simpler versions. Highest costs GPU time.'),
        row('show_fps', 'Show FPS counter', 'toggle'),
        *[row(key, title[0], 'toggle', hint=EFFECT_HINTS.get(key, '')) for key, title, _ in core.EFFECTS],
    ],
    'Display': [
        row('fps_mode', 'Frame rate', 'choice', core.FPS_MODES),
        row('frame_cap', 'Unlocked mode limit', 'choice', core.FRAME_CAPS),
        row('frames_ahead', 'Frames ahead', 'choice', core.FRAMES_AHEAD),
        row('fullscreen', 'Fullscreen', 'toggle'),
        row('present_mode', 'Presentation mode', 'choice', core.PRESENT_MODES),
        row('hdr', 'HDR output', 'toggle'),
    ],
    'Game': [
        row('game_dir', 'Game folder (contains eboot.bin)', 'folder'),
        row('user_dir', 'Saves folder', 'folder'),
        row('dlc_dir', 'DLC folder (base-game dumps only, e.g. SPEXPANSIONDLC03)', 'folder'),
        row('language', 'Game language', 'choice', core.LANGUAGES),
        row('player_name', 'Hunter name'),
        *[row(key, title[0], 'toggle') for key, title, _ in core.EXTRAS[:1]],
    ],
    'Controller': [
        row('mouse_camera', 'Mouse camera (click the game window to use it)', 'toggle'),
        row('mouse_menu', "Mouse pointer in the game's menus (hover, click, right-click back)", 'toggle'),
        row('mouse_sensitivity', 'Mouse sensitivity', 'choice', core.MOUSE_SPEEDS),
        row('mouse_invert_y', 'Invert mouse Y', 'toggle'),
        row('move_smoothing', 'Keyboard movement smoothing (WASD direction changes)', 'choice',
            core.MOVE_SMOOTHING),
        row('debug_camera', 'Free camera', 'toggle'),
        row('debug_menu', 'Debug menu', 'toggle'),
    ],
    'Cheats': [
        *[row(key, title[0], 'toggle') for key, title, _ in core.CHEATS],
        *[row(key, title[0], 'toggle') for key, title, _ in core.TWEAKS],
    ],
    'Online': [
        row('online', 'Play online', 'toggle'),
        row('online_community', 'Community game server'),
        row('online_server', 'shadNet server'),
        row('online_webapi', 'shadNet WebAPI'),
        row('online_npid', 'Online account ID'),
        row('online_password', 'Online password', 'password'),
        row('online_upnp', 'UPnP', 'toggle'),
    ],
    'Mods': [
        row('mods_enabled', 'Enable mods', 'toggle'),
        row('mods_dir', 'Mods folder', 'folder'),
        row('patches_dir', 'External patches folder', 'folder'),
    ],
    'Enhancements': [
        *[row(key, title[0], 'toggle') for key, title, _ in core.ENHANCEMENTS],
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
        ('Display & frame rate', ['output_res', 'fullscreen', 'hdr', 'fps_mode', 'frame_cap',
                                  'frames_ahead', 'present_mode']),
        ('Upscaling', ['upscaler', 'preset', 'live_resolution', 'sharpen', 'sharpness',
                       'object_motion']),
        ('Image effects', ['model_lod'] + [key for key, _, _ in core.EFFECTS]),
        ('Overlay', ['show_fps']),
    ],
    'Controls': [
        ('Button prompts', []),
        ('Mouse', ['mouse_camera', 'mouse_menu', 'mouse_sensitivity', 'mouse_invert_y']),
        ('Keyboard', ['move_smoothing']),
    ],
    'Game & Saves': [
        ('Game files', ['game_dir', 'dlc_dir']),
        ('Your data', ['user_dir']),
        ('In-game preferences', ['language', 'player_name'] + [key for key, _, _ in core.EXTRAS[:1]]),
    ],
    'Online': [
        ('Play online', ['online', 'online_npid', 'online_password']),
        ('Connection details', ['online_community', 'online_server', 'online_webapi', 'online_upnp']),
    ],
    'Mods & Patches': [
        ('Installed mods', ['mods_enabled', 'mods_dir']),
        ('Built-in enhancements', [key for key, _, _ in core.ENHANCEMENTS]),
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
    'user_dir': 'save folder save path', 'game_dir': 'eboot install game files',
    'online_npid': 'account id username', 'mouse_camera': 'camera controls', 'mouse_menu': 'cursor pointer click menus',
    'ui_language': 'launcher language', 'mods_enabled': 'load mods',
}
SEARCH_ACTIONS = [
    ('Controls', 'Button prompts', 'Xbox and PlayStation prompts', 'button controller'),
    ('Visuals', 'Upscaling', 'Download FSR 4 assets', 'fsr shader'),
    ('Game & Saves', 'Game files', 'Install from ZIP / PKG', 'game files setup'),
    ('Game & Saves', 'Your data', 'Import trophy keys', 'keys.json trophies'),
    ('Game & Saves', 'Your data', 'Open saves folder', 'save path'),
    ('Online', 'Play online', 'Test connection', 'server reachability'),
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
    bbscPreviewFinished = Signal(str)
    setupRunningChanged = Signal()
    setupCompleted = Signal(str)
    setupFailed = Signal(str)
    gameStarted = Signal()
    gameFinished = Signal(int, bool)  # exit code, whether the game got as far as running
    presetApplied = Signal()

    def __init__(self, route=None):
        super().__init__()
        self.app = {**core.APP_DEFAULTS, **core.load_json(core.CONFIG_FILE, {})}
        self._route = dict(route or LAUNCHER_ROUTE)
        self._problem = self._route.get('problem', '')
        self._game_started = False
        self._checks_started = False
        self.ini, self.ini_lines = core.load_ini()
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
        self._bbsc_preview_running = False
        self.workerNotice.connect(self._set_notice)
        self.updateAvailable.connect(self._offer_update)
        self.gpuDetected.connect(self._set_gpu_status)
        self.connectionResult.connect(self._show_connection_result)
        self.bbscPreviewFinished.connect(self._finish_bbsc_preview)
        self.setupCompleted.connect(self._complete_game_setup)
        self.setupFailed.connect(self._fail_game_setup)
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
                f"{self.app.get('fps_mode', 'uncap').upper()} FPS  ·  "
                f"{self.ini.get('upscaler', 'dlss').upper()}")

    @Property('QVariantMap', notify=changed)
    def setupFacts(self):
        fps = str(self.app.get('fps_mode', 'uncap'))
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
        return bool(self.app.get('online') and '@' in str(self.app.get('online_npid', '')))

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
        return ('xbox' in name.lower() and 'prompt' in name.lower()) or name == core.KEYBOARD_PROMPTS

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
        if core.KEYBOARD_PROMPTS in enabled:
            return 'Keyboard'
        return 'Xbox' if enabled else 'PlayStation'

    @Property(str, notify=changed)
    def fsrStatus(self):
        missing = core.fsr4_missing()
        return 'FSR 4 assets ready' if not missing else f'{len(missing)} FSR 4 assets missing'

    @Slot(str, result='QVariantList')
    def fields(self, page):
        # The revision makes the rows differ after a preset, so the page builds them anew.
        return [{**field, 'revision': self._settings_revision} for field in FIELDS.get(page, [])]

    @Slot(str, result='QVariantList')
    def categorySections(self, category):
        return [name for name, _ in SETTINGS_SECTIONS.get(category, [])]

    @Slot(str, str, result='QVariantList')
    def sectionFields(self, category, section):
        for name, keys in SETTINGS_SECTIONS.get(category, []):
            if name == section:
                # The revision makes the rows differ after a preset, so the page builds them anew.
                return [{**SETTING_FIELDS[key], 'revision': self._settings_revision} for key in keys]
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

    def _write(self):
        core.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        core.CONFIG_FILE.write_text(json.dumps(self.app, indent=2, ensure_ascii=False), encoding='utf-8')
        core.save_ini({k: self.ini[k] for k in core.INI_DEFAULTS}, self.ini_lines)
        self.ini, self.ini_lines = core.load_ini()
        self.changed.emit()

    @Slot()
    def installFromArchive(self):
        if self._setup_running or self.running:
            self._set_notice('Close the game or wait for the current setup to finish.')
            return
        source, _ = QFileDialog.getOpenFileName(
            None, 'Choose cusa-03173.zip or CUSA03173.pkg', str(Path.home() / 'Downloads'),
            'Game archive or base PKG (*.zip *.pkg)')
        if not source:
            return
        update = None
        if Path(source).suffix.casefold() == '.pkg':
            update, _ = QFileDialog.getOpenFileName(
                None, 'Choose CUSA03173 Update v1.09.pkg', str(Path(source).parent), 'Update PKG (*.pkg)')
            if not update:
                return
        parent = QFileDialog.getExistingDirectory(
            None, 'Choose where to create the CUSA03173 game folder', str(Path.home()))
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
        else:
            self.app[key] = value
        self._write()

    @Slot(str, result=bool)
    def checked(self, key):
        value = self.value(key)
        return value is True or value == '1'

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
            self.setValue(key, folder)
            if key in ('mods_dir', 'patches_dir'):
                self.refresh_addons()

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
    def play(self):
        if self._bbsc_preview_running:
            self._set_notice('Close the BBSC preview game before starting another session.')
            return
        if self._setup_running:
            self._set_notice('Wait for the game files to finish installing.')
            return
        if self.process:
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
        self._write()
        self._log = ''
        self.logChanged.emit()
        self._game_started = False
        try:
            self.process = subprocess.Popen(core.run_command(), cwd=core.PORT_DIR,
                                            env=core.game_environment(self.app), stdin=subprocess.DEVNULL,
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
    _gameExited = Signal(int)

    @Slot(str)
    def _receive_line(self, line):
        self._append_log(line)
        if 'Entering original x86-64 code' in line:
            if not self._game_started:
                self._game_started = True
                self.gameStarted.emit()
            self._set_notice('The game is running.')
        elif 'restarting through run.py' in line:
            self._set_notice('Restarting with the new settings…')

    @Slot(int)
    def _receive_exit(self, code):
        self._append_log(f'\n— The game exited (code {code}) —\n')
        self.process = None
        if self.job:
            self.job.close()
            self.job = None
        self.runningChanged.emit()
        if self._game_started or code == 0:
            self._set_notice('Ready to hunt.')
        else:
            self._set_notice(f'The game could not start (exit code {code}). See the log for details.')
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
        """Xbox and Keyboard: prompt images the port ships (Dommo's Xbox prompts; JinkiJinn's
        PCBButtons key images, copied into the mods folder the first time, with the keys those
        images show bound in bbport.ini). PlayStation: the game's own."""
        if choice not in ('Xbox', 'PlayStation', 'Keyboard'):
            return
        names = [m['name'] for m in self._mods if self._is_prompt_mod(m['name'])]
        xbox = [n for n in names if n != core.KEYBOARD_PROMPTS]
        if choice == 'Xbox' and not xbox:
            self._set_notice('The Xbox prompts are missing from the mods folder. Download the latest release.')
            return
        if choice == 'Keyboard' and core.KEYBOARD_PROMPTS not in names:
            try:
                core.install_keyboard_prompts(self._mods_dir())
            except (OSError, ValueError) as error:
                self._set_notice(str(error))
                return
            self.refresh_addons()
            names = [m['name'] for m in self._mods if self._is_prompt_mod(m['name'])]
        profile_file = core.DATA_DIR / 'mods.json'
        profile_file.parent.mkdir(parents=True, exist_ok=True)
        profile = core.load_json(profile_file, {})
        disabled, enabled = set(profile.get('disabled', [])), set(profile.get('enabled', []))
        chosen = {'Xbox': xbox[:1], 'Keyboard': [core.KEYBOARD_PROMPTS]}.get(choice, [])
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
                shutil.rmtree(core.UPDATE_DIR, ignore_errors=True)
                core.UPDATE_DIR.mkdir(parents=True, exist_ok=True)
                archive = core.UPDATE_DIR / 'update.zip'
                request = urllib.request.Request(url, headers={'User-Agent': 'bbport-launcher'})
                with urllib.request.urlopen(request, timeout=60) as reply, open(archive, 'wb') as out:
                    while chunk := reply.read(1 << 20):
                        out.write(chunk)
                with zipfile.ZipFile(archive) as package:
                    package.extractall(core.UPDATE_DIR / 'new')
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

    @Slot()
    def openShadNetRegistration(self):
        webbrowser.open('https://shadps4.net/shadnet/register/')

    @Slot()
    def openBBSCRelease(self):
        webbrowser.open(bbsc_preview.RELEASE_URL)

    @Slot()
    def launchBBSCPreview(self):
        if self.process or self._bbsc_preview_running:
            self._set_notice('Close the current game before starting BBSC.')
            return
        game = Path(self.app.get('game_dir') or '')
        info = core.game_info(game)
        if not info or info[1] != core.PATCH_VERSION:
            self._set_notice('Choose your CUSA03173 version 1.09 game folder first.')
            return
        if self.app.get('user_dir') and Path(self.app['user_dir']).resolve() != (core.PORT_DIR / 'user').resolve():
            self._set_notice('BBSC 0.0.1 needs the default saves folder. Use a separate BBport copy to test it.')
            return
        package = QFileDialog.getExistingDirectory(
            None, 'Choose the extracted BBSC-0.0.1-BBport folder', str(core.PORT_DIR))
        if not package:
            return
        try:
            bbsc_preview.validate(package, core.PORT_DIR, game)
        except bbsc_preview.PreviewError as error:
            QMessageBox.warning(None, 'BBSC preview', str(error))
            return
        answer = QMessageBox.question(
            None, 'BBSC 0.0.1 test build',
            'BBSC says co-op in native BBport has not been tested yet. This preview backs up '
            'your saves and restores your server override when it ends. Its own account and '
            'public server are separate from the normal Online settings. Start the test?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._bbsc_preview_running = True
        self._set_notice('Preparing BBSC preview and backing up saves…')

        def work():
            try:
                code, backup = bbsc_preview.run_preview(package, core.PORT_DIR, game)
                detail = f' Saves backed up to {backup}.' if backup else ' No existing savedata folder.'
                message = f'BBSC preview exited with code {code}.{detail}'
            except (OSError, bbsc_preview.PreviewError) as error:
                message = f'BBSC preview could not start: {error}'
            self.bbscPreviewFinished.emit(message)

        threading.Thread(target=work, daemon=False).start()

    @Slot(str)
    def _finish_bbsc_preview(self, message):
        self._bbsc_preview_running = False
        self._set_notice(message)

    @Slot()
    def testConnection(self):
        self._set_notice('Testing online servers…')
        def work():
            server = str(self.app['online_server']).strip() or core.APP_DEFAULTS['online_server']
            result = core.server_check(server, core.webapi_setting(self.app),
                                       core.community_address(self.app['online_community']))
            self.connectionResult.emit(result)
        threading.Thread(target=work, daemon=True).start()

    @Slot(str)
    def _show_connection_result(self, result):
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

