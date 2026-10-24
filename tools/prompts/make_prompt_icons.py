# SPDX-License-Identifier: GPL-2.0-or-later
"""Builds launcher/assets/prompts/<pack>.json, the Xbox and keyboard button prompts the launcher
writes into the player's own menu/common.tpf.dcx (scripts/prompt_icons.py).

The images are Kenney's Input Prompts 1.5 (CC0, tools/prompts/kenney/License.txt). Each game
texture slot gets one image, or a few side by side, encoded as BC7 mode 6 blocks in row order.
Needs Pillow and numpy; the launcher only reads the JSON.

    python tools/prompts/make_prompt_icons.py
"""
import base64
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

HERE = Path(__file__).resolve().parent
KENNEY = HERE / 'kenney'
OUT = HERE.parents[1] / 'launcher' / 'assets' / 'prompts'

# The game's prompt slots (KG_*): the PlayStation glyph each one shows. Cancel is Cross and OK is
# Circle in the Western layout; TP_L and TP_R are the touchpad's halves (gestures, items).
SLOTS = ('Cancel', 'OK', 'R_L', 'R_U', 'L1', 'L2', 'L3', 'R1', 'R2', 'R3', 'LS', 'RS',
         'L_U', 'L_D', 'L_LR', 'L_UD', 'L_UDLR', 'Start', 'TP_L', 'TP_R')

# Xbox: the button in the same place. The port's pad code stands in for the touchpad with View
# (left half) and View + d-pad right (right half), src/runtime_pad.c.
XBOX = {
    'Cancel': ['xbox_button_color_a'], 'OK': ['xbox_button_color_b'],
    'R_L': ['xbox_button_color_x'], 'R_U': ['xbox_button_color_y'],
    'L1': ['xbox_lb'], 'L2': ['xbox_lt'], 'R1': ['xbox_rb'], 'R2': ['xbox_rt'],
    'L3': ['xbox_stick_l_press'], 'R3': ['xbox_stick_r_press'],
    'LS': ['xbox_stick_l'], 'RS': ['xbox_stick_r'],
    'L_U': ['xbox_dpad_up'], 'L_D': ['xbox_dpad_down'], 'L_LR': ['xbox_dpad_horizontal'],
    'L_UD': ['xbox_dpad_vertical'], 'L_UDLR': ['xbox_dpad_all'],
    'Start': ['xbox_button_menu'], 'TP_L': ['xbox_button_view'],
    'TP_R': ['xbox_button_view', 'xbox_dpad_right'],
}
# Keyboard: the keys of launcher KEYBOARD_PROMPT_LAYOUT and src/key_prompts.c IMAGE_LAYOUT, and
# the default arrows and WASD (src/input_bindings.c). Strong attack is Left Ctrl + Mouse1.
KEYBOARD = {
    'Cancel': ['keyboard_e'], 'OK': ['keyboard_shift'], 'R_L': ['keyboard_q'], 'R_U': ['keyboard_r'],
    'L1': ['keyboard_f'], 'L2': ['mouse_right'], 'L3': ['keyboard_space'],
    'R1': ['mouse_left'], 'R2': ['keyboard_ctrl', 'mouse_left'], 'R3': ['mouse_scroll'],
    'LS': ['wasd'], 'RS': ['mouse_move'],
    'L_U': ['keyboard_arrows_up'], 'L_D': ['keyboard_arrows_down'],
    'L_LR': ['keyboard_arrows_horizontal'], 'L_UD': ['keyboard_arrows_vertical'],
    'L_UDLR': ['keyboard_arrows_all'],
    'Start': ['keyboard_escape'], 'TP_L': ['keyboard_g'], 'TP_R': ['keyboard_h'],
}
# MENU_Common_00091 (1024x512) holds the HUD's Circle, Cross and L3 glyphs at x 661, 694, 726,
# y 123, 26 pixels each; the 4x4 blocks from (660, 120) to (756, 152) hold nothing else.
ATLAS = {'name': 'MENU_Common_00091', 'x': 165, 'y': 30, 'w': 24, 'h': 8}
ATLAS_GLYPHS = (('OK', 14, 16), ('Cancel', 47, 16), ('L3', 79, 16))  # slot, centre in the rect
ATLAS_SIZE = 26
ICON_SIZE = 32
PACKS = {'xbox': XBOX, 'keyboard': KEYBOARD}


def kenney(name):
    folder = 'xbox' if name.startswith('xbox_') else 'keyboard'
    image = Image.open(KENNEY / folder / f'{name}.png').convert('RGBA')
    return image.crop(image.getbbox())


def wasd():
    """W over A S D, the movement keys in one image."""
    keys = [kenney(f'keyboard_{k}') for k in 'wasd']
    size = keys[0].width
    image = Image.new('RGBA', (size * 3, size * 2))
    image.alpha_composite(keys[0], (size, 0))
    for i, key in enumerate(keys[1:]):
        image.alpha_composite(key, (i * size, size))
    return image


def compose(names, size):
    """The images side by side, scaled to fit a size x size square, centred."""
    parts = [wasd() if n == 'wasd' else kenney(n) for n in names]
    height = max(p.height for p in parts)
    row = Image.new('RGBA', (sum(p.width for p in parts), height))
    x = 0
    for p in parts:
        row.alpha_composite(p, (x, (height - p.height) // 2))
        x += p.width
    scale = (size - 2) / max(row.size)
    fitted = row.convert('RGBa').resize((max(1, round(row.width * scale)), max(1, round(row.height * scale))),
                                        Image.LANCZOS).convert('RGBA')
    out = Image.new('RGBA', (size, size))
    out.alpha_composite(fitted, ((size - fitted.width) // 2, (size - fitted.height) // 2))
    return out


def bleed(image):
    """Gives fully transparent pixels the colour of their opaque neighbours, so filtering at the
    glyph's edge does not pull in the source's transparent colour."""
    rgba = np.asarray(image, dtype=np.float32)
    alpha = rgba[..., 3:4] / 255
    pre = Image.fromarray((rgba[..., :3] * alpha).astype(np.uint8))
    weight = Image.fromarray((alpha[..., 0] * 255).astype(np.uint8))
    blur = ImageFilter.GaussianBlur(3)
    colour = np.asarray(pre.filter(blur), dtype=np.float32)
    total = np.asarray(weight.filter(blur), dtype=np.float32)[..., None] / 255
    fill = np.where(total > 1e-3, colour / np.maximum(total, 1e-3), 255)
    rgb = np.where(alpha > 0, rgba[..., :3], np.clip(fill, 0, 255))
    return np.concatenate([rgb, rgba[..., 3:4]], axis=2).round().astype(np.uint8)


# BC7 mode 6: one subset, RGBA endpoints of 7 bits plus a p-bit each, 4-bit indices.
WEIGHTS = np.array([0, 4, 9, 13, 17, 21, 26, 30, 34, 38, 43, 47, 51, 55, 60, 64])


def _palette(e0, e1):
    return ((64 - WEIGHTS[:, None]) * e0 + WEIGHTS[:, None] * e1 + 32) >> 6


def _quantise(endpoint, pbit):
    q = np.clip(np.round((endpoint - pbit) / 2), 0, 127).astype(np.int64)
    return q, (q << 1) | pbit


def _fit(pixels, lo, hi):
    best = None
    for p0 in (0, 1):
        for p1 in (0, 1):
            q0, e0 = _quantise(lo, p0)
            q1, e1 = _quantise(hi, p1)
            palette = _palette(e0, e1)
            error = ((pixels[:, None, :] - palette[None, :, :]) ** 2).sum(axis=2)
            indices = error.argmin(axis=1)
            total = error[np.arange(16), indices].sum()
            if best is None or total < best[0]:
                best = (total, q0, q1, p0, p1, indices)
    return best


def encode_block(pixels):
    """16 RGBA pixels (row order) as one 16-byte BC7 mode 6 block."""
    pixels = pixels.astype(np.int64)
    mean = pixels.mean(axis=0)
    centred = pixels - mean
    axis = np.linalg.svd(centred.astype(np.float64), full_matrices=False)[2][0] if centred.any() else np.ones(4)
    projection = centred @ axis
    lo, hi = mean + axis * projection.min(), mean + axis * projection.max()
    best = _fit(pixels, lo, hi)
    for _ in range(2):  # least-squares endpoints for the chosen indices
        w = WEIGHTS[best[5]] / 64
        a = np.stack([1 - w, w], axis=1)
        if np.linalg.matrix_rank(a) < 2:
            break
        solved = np.linalg.lstsq(a, pixels.astype(np.float64), rcond=None)[0]
        candidate = _fit(pixels, solved[0], solved[1])
        if candidate[0] >= best[0]:
            break
        best = candidate
    _, q0, q1, p0, p1, indices = best
    if indices[0] >= 8:  # the anchor index keeps its top bit clear
        q0, q1, p0, p1, indices = q1, q0, p1, p0, 15 - indices
    bits, at = 1 << 6, 7
    for channel in range(4):
        for value in (q0[channel], q1[channel]):
            bits |= int(value) << at
            at += 7
    bits |= p0 << at | p1 << (at + 1)
    at += 2
    for i, index in enumerate(indices):
        bits |= int(index) << at
        at += 3 if i == 0 else 4
    assert at == 128
    return bits.to_bytes(16, 'little')


def encode(image):
    """An RGBA image (sides multiple of 4) as BC7 blocks in row order."""
    rgba = bleed(image)
    h, w = rgba.shape[:2]
    return b''.join(encode_block(rgba[y:y + 4, x:x + 4].reshape(16, 4))
                    for y in range(0, h, 4) for x in range(0, w, 4))


def atlas_rect(slots):
    rect = Image.new('RGBA', (ATLAS['w'] * 4, ATLAS['h'] * 4))
    for slot, cx, cy in ATLAS_GLYPHS:
        glyph = compose(slots[slot], ATLAS_SIZE)
        rect.alpha_composite(glyph, (cx - ATLAS_SIZE // 2, cy - ATLAS_SIZE // 2))
    return rect


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for pack, slots in PACKS.items():
        assert set(slots) == set(SLOTS), pack
        data = {
            'source': "Kenney's Input Prompts 1.5 (kenney.nl, CC0)",
            'textures': {f'KG_{s}': base64.b64encode(encode(compose(slots[s], ICON_SIZE))).decode() for s in SLOTS},
            'atlas': {**ATLAS, 'blocks': base64.b64encode(encode(atlas_rect(slots))).decode()},
        }
        (OUT / f'{pack}.json').write_text(json.dumps(data, indent=1) + '\n', encoding='utf-8')
        print(f'{pack}: {len(SLOTS)} glyphs and the HUD atlas glyphs')


if __name__ == '__main__':
    main()
