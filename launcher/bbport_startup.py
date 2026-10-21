"""Start-up routing: first-run setup, direct launch, and the overrides that open the launcher.

Runs before any window exists, so it only does quick file checks and never touches game,
save or trophy data.
"""
import ctypes
import os
from pathlib import Path
import sys
import tempfile

# Bump when the wizard changes enough that everyone should see it again.
SETUP_VERSION = 1

# Banner text and the wizard step that fixes each start-up problem.
PROBLEMS = {'game': ('Game files not found', 1), 'saves': ('Saves folder is not writable', 2)}


def expanded(value):
    """A configured folder with `~` and Windows `%VARIABLE%` expanded."""
    return Path(os.path.expandvars(os.path.expanduser(str(value))))


def game_ok(settings):
    return (expanded(settings.get('game_dir') or '.') / 'eboot.bin').is_file()


def writable(folder):
    """A folder the game can write saves to; a missing one counts when its nearest existing
    parent is writable, because the launcher creates it on first launch."""
    folder = Path(folder)
    while not folder.exists():
        if folder.parent == folder:
            return False
        folder = folder.parent
    if not folder.is_dir():
        return False
    try:
        with tempfile.NamedTemporaryFile(prefix='.bbport-check-', dir=folder, delete=True):
            return True
    except OSError:
        return False


def saves_folder(settings, data_dir):
    folder = settings.get('user_dir')
    return expanded(folder) if folder else Path(data_dir) / 'user'


def migrate(saved, settings):
    """Settings from launchers older than the setup state: a working game folder means setup is
    already done; a dismissed old wizard counts as skipped. Returns True when SAVED changed."""
    if not saved or 'setupCompleted' in saved:
        return False
    if game_ok(settings):
        saved['setupCompleted'] = True
    elif saved.get('setup_seen'):
        saved['setupSkipped'] = True
    saved['setupVersion'] = SETUP_VERSION
    saved.setdefault('launchDirectly', True)
    saved.pop('setup_seen', None)
    return True


def setup_pending(settings):
    done = settings.get('setupCompleted') or settings.get('setupSkipped')
    try:
        current = int(settings.get('setupVersion', 0)) >= SETUP_VERSION
    except (TypeError, ValueError):
        current = False
    return not done or not current


def launcher_keys_held():
    """Shift or Ctrl held down right now (Windows only)."""
    if sys.platform != 'win32':
        return False
    try:
        state = ctypes.windll.user32.GetAsyncKeyState
        return any(state(key) & 0x8000 for key in (0x10, 0x11))  # VK_SHIFT, VK_CONTROL
    except (AttributeError, OSError):
        return False


def choose_route(settings, args, keys_held, game_valid, saves_valid):
    """{'mode': 'direct' | 'launcher', 'page', 'step' (wizard), 'problem' (PROBLEMS key or '')}."""
    def launcher(page, step=0, problem=''):
        return {'mode': 'launcher', 'page': page, 'step': step, 'problem': problem}

    if '--setup' in args or setup_pending(settings):
        return launcher('Setup')
    if not game_valid:
        return launcher('Game', PROBLEMS['game'][1], 'game')
    if not saves_valid:
        return launcher('Game', PROBLEMS['saves'][1], 'saves')
    if keys_held or '--launcher' in args or not settings.get('launchDirectly', True):
        return launcher('Home')
    return {'mode': 'direct', 'page': 'Home', 'step': 0, 'problem': ''}


def route(settings, args, data_dir, keys_held):
    return choose_route(settings, args, keys_held, game_ok(settings),
                        writable(saves_folder(settings, data_dir)))
