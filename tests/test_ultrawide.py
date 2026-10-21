from paths import ROOT
import struct
import unittest

import hud_layout
from patches import (CAMERA_ASPECT, EBOOT_BASE, HUD_PROJECTION_WIDTH, MARKER_BIAS, OUTPUT_SIZE,
                     ULTRAWIDE_TEMPLATE, compile_patches, hud_canvas, scaled_sizes, ultrawide,
                     ultrawide_writes)

XML = ROOT / 'patches/Bloodborne.xml'
SEGMENTS = [(0, 0x6000000)]


def apply(writes):
    image = {}
    for offset, data in writes:
        for i, byte in enumerate(data):
            image[offset + i] = byte
    return image


def value(image, offset, size=4):
    return bytes(image[offset + i] for i in range(size))


class UltrawideTests(unittest.TestCase):
    def test_canvas(self):
        self.assertEqual(hud_canvas((3440, 1440)), (2580, 1080))
        self.assertEqual(hud_canvas((2560, 1080)), (2560, 1080))
        # 16:9 and narrower keep the game's own coordinates.
        self.assertEqual(hud_canvas((3840, 2160)), OUTPUT_SIZE)
        self.assertEqual(hud_canvas((1920, 1200)), OUTPUT_SIZE)

    def test_2560x1080_matches_the_community_patch(self):
        ours = apply(ultrawide_writes(XML, (2560, 1080), '01.09', SEGMENTS))
        theirs = apply(compile_patches(XML, [ULTRAWIDE_TEMPLATE], '01.09', SEGMENTS))
        # Scene and UI viewport sizes come from resolution_writes instead.
        for offset, byte in ours.items():
            self.assertEqual(theirs[offset], byte, hex(offset + EBOOT_BASE))

    def test_3440x1440_values(self):
        image = apply(ultrawide_writes(XML, (3440, 1440), '01.09', SEGMENTS))
        aspect, = struct.unpack('<f', value(image, CAMERA_ASPECT))
        width, = struct.unpack('<f', value(image, HUD_PROJECTION_WIDTH))
        self.assertAlmostEqual(aspect, 3440 / 1440, places=5)
        self.assertEqual(width, 2580.0)
        for site in MARKER_BIAS:
            bias, = struct.unpack('<f', value(image, site))
            self.assertAlmostEqual(bias, 0.5 * 1920 / 2580, places=6)


class HudLayoutTests(unittest.TestCase):
    def test_matrix_round_trip(self):
        for matrix in [(None, None, (0, 0)), (None, None, (-6600, 2988)),
                       ((65536, 65536), None, (3704, 2988)), ((-65536, 65536), (12, -7), (1, -1))]:
            data = hud_layout.write_matrix(matrix)
            self.assertEqual(hud_layout.read_matrix(data, 0)[0], matrix)

    def test_moves_named_placements(self):
        # A movie with PlayerHUD (sprite 2, holding Soul) and AutoSaveIcon on the root timeline.
        def place(depth, character, x, name):
            body = bytes([0x26]) + struct.pack('<HH', depth, character)
            body += hud_layout.write_matrix((None, None, (x * 20, 0))) + name.encode() + b'\0'
            return hud_layout.tag(26, body)
        sprite = hud_layout.tag(39, struct.pack('<HH', 2, 1) + place(1, 1, 1357, 'Soul') +
                                hud_layout.tag(1, b'') + hud_layout.tag(0, b''))
        rect = hud_layout.Writer()
        rect.unsigned(16, 5)
        for v in (0, 1920 * 20, 0, 1080 * 20):
            rect.unsigned(v, 16)
        body = rect.bytes() + b'\0\x1e\1\0' + sprite + place(1, 2, 185, 'PlayerHUD') + \
            place(2, 3, 1767, 'AutoSaveIcon') + hud_layout.tag(1, b'') + hud_layout.tag(0, b'')
        movie = b'GFX\x0b' + struct.pack('<I', 8 + len(body)) + body
        out = hud_layout.layout(movie, 2580, 330)
        self.assertEqual(struct.unpack_from('<I', out, 4)[0], len(out))
        start = hud_layout.stage_start(out)
        found = {}
        for code, _, b, length in hud_layout.tags(out, start, len(out)):
            if code == 26:
                _, span, name = hud_layout.place_fields(out, b, code)
                found[name] = hud_layout.read_matrix(out, span[0])[0][2][0] / 20
            if code == 39:
                for c2, _, b2, _ in hud_layout.tags(out, b + 4, b + length):
                    if c2 == 26:
                        _, span, name = hud_layout.place_fields(out, b2, c2)
                        found[name] = hud_layout.read_matrix(out, span[0])[0][2][0] / 20
        self.assertEqual(found, {'Soul': 1357 + 660, 'PlayerHUD': 185 - 330, 'AutoSaveIcon': 1767 + 330})


def movie(*root_tags):
    rect = hud_layout.Writer()
    rect.unsigned(16, 5)
    for v in (0, 1920 * 20, 0, 1080 * 20):
        rect.unsigned(v, 16)
    body = rect.bytes() + b'\x00\x1e\x01\x00' + b''.join(root_tags) + hud_layout.tag(1, b'') + hud_layout.tag(0, b'')
    return b'GFX\x0b' + struct.pack('<I', 8 + len(body)) + body


def solid_shape(shape, x0, x1):
    bounds = hud_layout.Writer()
    bounds.unsigned(17, 5)
    for v in (x0 * 20, x1 * 20, 0, 1080 * 20):
        bounds.unsigned(v & 0x1FFFF, 17)
    # One solid black fill, no line styles, no records.
    return hud_layout.tag(2, struct.pack('<H', shape) + bounds.bytes() + b'\x01\x00\x00\x00\x00\x00\x00')


def place(depth, character, x=0, y=0, name=None):
    flags = 0x06 | (0x20 if name else 0)
    body = bytes([flags]) + struct.pack('<HH', depth, character)
    body += hud_layout.write_matrix((None, None, (round(x * 20), round(y * 20))))
    return hud_layout.tag(26, body + (name.encode() + b'\x00' if name else b''))


def root_x(data, name_or_depth):
    found = {}
    for code, _, body, _ in hud_layout.tags(data, hud_layout.stage_start(data), len(data)):
        if code == 26:
            character, span, name = hud_layout.place_fields(data, body, code)
            depth, = struct.unpack_from('<H', data, body + 1)
            found[name or depth] = hud_layout.read_matrix(data, span[0])[0]
    return found[name_or_depth]


class BackdropTests(unittest.TestCase):
    def test_full_screen_backdrop_is_widened_around_the_centre(self):
        data = movie(solid_shape(1, 0, 1920), solid_shape(2, 0, 600), place(1, 1), place(2, 2))
        out = hud_layout.layout(data, 2580)
        scale, _, (tx, _) = root_x(out, 1)
        factor = 2580 / 1920 * 1.01
        self.assertAlmostEqual(scale[0] / 65536, factor, places=3)
        self.assertAlmostEqual(tx / 20 + 960 * factor, 960, delta=1)  # centred
        self.assertEqual(root_x(out, 2), root_x(data, 2))  # a small shape stays

    def test_nothing_to_widen(self):
        self.assertIsNone(hud_layout.layout(movie(solid_shape(1, 0, 600), place(1, 1)), 2580))


if __name__ == '__main__':
    unittest.main()


class OutputPipelineTests(unittest.TestCase):
    """The six outputs the Windows run.py pipeline must classify (patches.hud_canvas)."""

    CASES = {
        '1920x1080': (None, None),
        '2560x1440': (None, None),
        '1280x800': ('1280x800', None),
        '2560x1080': ('2560x1080', 2560),
        '3440x1440': ('2580x1080', 2580),
        '5120x1440': ('3840x1080', 3840),
    }

    def test_ui_viewport_and_hud_canvas(self):
        for output, (ui_res, canvas_width) in self.CASES.items():
            with self.subTest(output=output):
                size = tuple(int(value) for value in output.split('x'))
                wide = ultrawide(size)
                if size[0] * 9 == size[1] * 16:
                    self.assertIsNone(ui_res)  # run.py leaves BB_UI_RES unset
                elif wide:
                    canvas = hud_canvas(size)
                    self.assertEqual(f'{canvas[0]}x{canvas[1]}', ui_res)
                    self.assertEqual(canvas[0], canvas_width)
                else:
                    self.assertEqual(output, ui_res)  # the output is the movie viewport

    def test_render_size_stays_below_each_output(self):
        expected_quality = {
            '2560x1440': (1706, 960),
            '1280x800': (854, 534),
            '2560x1080': (1706, 720),
            '3440x1440': (2294, 960),
            '5120x1440': (3414, 960),
        }
        for output in self.CASES:
            for preset in ('0', '1', '2', '3', '4'):
                with self.subTest(output=output, preset=preset):
                    sizes = scaled_sizes({'upscaler': 'fsr3', 'preset': preset,
                                          'output_res': output})
                    if output == '1920x1080':
                        self.assertIsNone(sizes)  # native live host targets
                        continue
                    render, out = sizes
                    self.assertEqual(out, tuple(int(v) for v in output.split('x')))
                    self.assertLessEqual(render[0], out[0])
                    self.assertLessEqual(render[1], out[1])
                    if preset == '1':
                        self.assertEqual(render, expected_quality[output])
