"""Keyboard and mouse bindings of bbport (src/input_bindings.c), for the launcher.

The game reads them from bbport.ini:

    key_<action>=<binding>, <binding>, <binding>

A binding is one input or up to three joined with '+' that must all be held
("Left Shift+Mouse1" is Shift and the left button together); commas separate bindings, so an
action can have a key and a mouse button on its own. This module holds the action table (the
same one as the engine's BindInfo), the key names SDL uses, and the reading and writing of the
lines, so the Controls page and the engine never disagree about the format.
"""
import re

# One entry per action of the engine's INFO table: (action, label, default bindings).
# A default binding is a list of inputs held together; an empty list means unbound.
ACTIONS = [
    ('move_forward', 'Move forward', [['W']]),
    ('move_back', 'Move back', [['S']]),
    ('move_left', 'Move left', [['A']]),
    ('move_right', 'Move right', [['D']]),
    ('walk', 'Walk (hold)', [['Left Alt']]),
    ('roll', 'Dodge / sprint (Circle)', [['Space']]),
    ('lock_on', 'Lock on (R3)', [['Q']]),
    ('attack', 'Attack (R1)', [['Mouse1']]),
    ('strong_attack', 'Strong attack (R2)', [['V']]),
    ('strong_modifier', 'Strong attack modifier', [['Left Shift']]),
    ('transform', 'Transform weapon (L1)', [['C'], ['Mouse3']]),
    ('firearm', 'Firearm (L2)', [['X'], ['Mouse2']]),
    ('blood_vial', 'Blood vial (Triangle)', [['R']]),
    ('use_item', 'Use item (Square)', [['F']]),
    ('interact', 'Interact; confirm in menus (Cross)', [['E']]),
    ('switch_item', 'Switch quick item (d-pad down)', [['Down']]),
    ('switch_right', 'Switch right hand weapon (d-pad right)', [['Right']]),
    ('switch_left', 'Switch left hand weapon (d-pad left)', [['Left']]),
    ('dpad_up', 'D-pad up', [['Up']]),
    ('gestures', 'Gestures (touchpad left)', [['G']]),
    ('personal_effects', 'Personal effects (touchpad right)', [['T']]),
    ('look_up', 'Camera up', [['I']]),
    ('look_down', 'Camera down', [['K']]),
    ('look_left', 'Camera left', [['J']]),
    ('look_right', 'Camera right', [['L']]),
    ('menu', 'Game menu (Options)', [['Escape']]),
    ('confirm', 'Menu confirm', [['Return']]),
    ('back', 'Menu back', [['Backspace']]),
    ('l3', 'Left stick press (L3)', [['Left Ctrl']]),
]
ACTION_NAMES = [action for action, _, _ in ACTIONS]
ACTION_LABELS = {action: label for action, label, _ in ACTIONS}

SLOTS = 3            # bindings per action (BIND_SLOTS in the engine)
COMBO_PARTS = 3      # inputs in one combination (BIND_COMBO_PARTS)

MOUSE_NAMES = ('Mouse1', 'Mouse2', 'Mouse3', 'Mouse4', 'Mouse5', 'WheelUp', 'WheelDown')
MOUSE_PRETTY = {
    'Mouse1': 'Left click', 'Mouse2': 'Right click', 'Mouse3': 'Middle click',
    'Mouse4': 'Mouse 4', 'Mouse5': 'Mouse 5', 'WheelUp': 'Wheel up', 'WheelDown': 'Wheel down',
}
# Names the engine knows (SDL_GetScancodeFromName) shown as people say them.
KEY_PRETTY = {
    'Left Shift': 'Shift', 'Right Shift': 'Right Shift', 'Left Ctrl': 'Ctrl', 'Right Ctrl': 'Right Ctrl',
    'Left Alt': 'Alt', 'Right Alt': 'Right Alt', 'Return': 'Enter', 'Keypad Enter': 'Numpad Enter',
    'Escape': 'Esc', 'PageUp': 'Page Up', 'PageDown': 'Page Down', 'PrintScreen': 'Print Screen',
}

# Qt's key codes (Qt.Key_*) to the name SDL gives the same key. Qt sends the same value for the
# left and right modifier, so the left one is written; the right ones stay editable in bbport.ini.
QT_KEYS = {
    0x01000000: 'Escape', 0x01000001: 'Tab', 0x01000003: 'Backspace', 0x01000004: 'Return',
    0x01000005: 'Keypad Enter', 0x01000006: 'Insert', 0x01000007: 'Delete', 0x01000008: 'Pause',
    0x01000009: 'PrintScreen', 0x01000010: 'Home', 0x01000011: 'End', 0x01000012: 'Left',
    0x01000013: 'Up', 0x01000014: 'Right', 0x01000015: 'Down', 0x01000016: 'PageUp',
    0x01000017: 'PageDown', 0x01000020: 'Left Shift', 0x01000021: 'Left Ctrl', 0x01000023: 'Left Alt',
    0x01000022: 'Left GUI', 0x01000024: 'CapsLock', 0x01000025: 'Numlock', 0x01000026: 'ScrollLock',
    0x01000055: 'Menu', 0x20: 'Space',
    ord('-'): '-', ord('='): '=', ord('['): '[', ord(']'): ']', ord('\\'): '\\', ord(';'): ';',
    ord("'"): "'", ord('`'): '`', ord(','): ',', ord('.'): '.', ord('/'): '/',
}
for _letter in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ':
    QT_KEYS[ord(_letter)] = _letter
for _digit in '0123456789':
    QT_KEYS[ord(_digit)] = _digit
for _n in range(1, 25):                     # Qt.Key_F1 = 0x01000030
    QT_KEYS[0x01000030 + _n - 1] = f'F{_n}'


def key_name(qt_key, numpad=False):
    """The SDL name of a key Qt reported, '' when it is not a key bbport can bind."""
    if numpad:
        digits = '0123456789'
        if 0x30 <= qt_key <= 0x39:
            return f'Keypad {digits[qt_key - 0x30]}'
        if qt_key == 0x2E:
            return 'Keypad .'
        if qt_key == 0x2F:
            return 'Keypad /'
        if qt_key == 0x2A:
            return 'Keypad *'
        if qt_key == 0x2D:
            return 'Keypad -'
        if qt_key == 0x2B:
            return 'Keypad +'
    if 0x30 <= qt_key <= 0x39 or 0x41 <= qt_key <= 0x5A:
        return chr(qt_key)
    return QT_KEYS.get(qt_key, '')


def mouse_name(button):
    """The engine's name of a Qt mouse button (Qt.LeftButton is 1), '' for anything else."""
    return MOUSE_NAMES[button - 1] if 1 <= button <= len(MOUSE_NAMES) else ''


def pretty(name):
    return MOUSE_PRETTY.get(name) or KEY_PRETTY.get(name) or name


def pretty_binding(binding):
    return ' + '.join(pretty(name) for name in binding)


def parse_value(value):
    """The bindings of a key_<action> value: [[...], [...]] of input names, at most SLOTS."""
    slots = []
    for chunk in str(value or '').split(','):
        inputs = [part.strip() for part in chunk.split('+') if part.strip()]
        inputs = [name for name in inputs if name.lower() != 'none']
        if inputs:
            slots.append(inputs[:COMBO_PARTS])
        if len(slots) == SLOTS:
            break
    return slots


def format_value(slots):
    """The text of a key_<action> line for these bindings ("none" when unbound)."""
    parts = []
    for slot in slots[:SLOTS]:
        inputs = [name for name in slot if name][:COMBO_PARTS]
        if inputs:
            parts.append('+'.join(inputs))
    return ', '.join(parts) if parts else 'none'


def defaults():
    return {action: [list(binding) for binding in bindings] for action, _, bindings in ACTIONS}


def read(path):
    """Every action's bindings as bbport.ini has them, the defaults for the lines it lacks."""
    result = defaults()
    try:
        text = open(path, encoding='utf-8', errors='replace').read()
    except OSError:
        return result
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith('key_') or '=' not in line:
            continue
        action, value = line[4:].split('=', 1)
        action = action.strip()
        if action in result:
            result[action] = parse_value(value)
    return result


def write(path, action, slots):
    """Rewrites that action's key_ line in bbport.ini, keeping every other line as it is."""
    value = format_value(slots)
    try:
        lines = open(path, encoding='utf-8', errors='replace').read().splitlines()
    except OSError:
        lines = []
    prefix = f'key_{action}'
    out, written = [], False
    for line in lines:
        stripped = line.strip()
        if not written and stripped.startswith(prefix + '='):
            out.append(f'{prefix}={value}')
            written = True
            continue
        out.append(line)
    if not written:
        out.append(f'{prefix}={value}')
    open(path, 'w', encoding='utf-8', newline='').write('\n'.join(out) + '\n')


def remove_all(path):
    """Drops every key_ line, so the engine's defaults apply again."""
    try:
        lines = open(path, encoding='utf-8', errors='replace').read().splitlines()
    except OSError:
        return
    kept = [line for line in lines if not line.strip().startswith('key_')]
    open(path, 'w', encoding='utf-8', newline='').write('\n'.join(kept) + '\n')


def summary(slots):
    """A one-line description for a row's hint ("Shift + Left click, X")."""
    if not slots:
        return 'Not bound'
    return ', '.join(pretty_binding(slot) for slot in slots)
