import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from fromsoft import dcx_compress
import shader_catalog
import shader_code

GAME = Path(os.environ['BB_TEST_GAME_DIR']) if os.environ.get('BB_TEST_GAME_DIR') else None


def footer(shader_hash, length, kind=0):
    """An OrbShdr footer: signature, version, the type/length word, then the hash and a CRC."""
    return (b'OrbShdr' + b'\x00' + struct.pack('<I', (length << 8) | (kind << 2)) + b'\x00' * 4 +
            struct.pack('<QI', shader_hash, 0))


class ExtractionTests(unittest.TestCase):
    def test_code_follows_the_header_and_a_copy_shader_follows_its_footer(self):
        code = struct.pack('<4I', 1, 2, 3, 4)
        copy = struct.pack('<2I', 7, 8)
        header = b'Shdr' + b'\x00' * 20 + struct.pack('<I', 24)  # code at header + 16 + 24
        blob = b'pad.' + header + b'\x00' * 12 + code + b'\x00' * 8 + footer(0x1234, len(code), 5)
        blob += copy + footer(0x1234, len(copy), shader_code.COPY_SHADER)
        found = list(shader_code.programs(blob))
        self.assertEqual(found, [(0x1234, 5, code), (0x1234, shader_code.COPY_SHADER, copy)])

    def test_a_damaged_archive_is_skipped(self):
        with tempfile.TemporaryDirectory() as folder:
            shaders = Path(folder) / 'dvdroot_ps4' / 'shader'
            shaders.mkdir(parents=True)
            (shaders / 'broken.shaderbnd.dcx').write_bytes(dcx_compress(b'x' * 1000)[:-5])
            self.assertEqual(shader_code.collect(folder, None), {})


class CatalogTests(unittest.TestCase):
    def test_only_current_records_are_merged_once(self):
        with tempfile.TemporaryDirectory() as folder:
            cache, catalog = Path(folder) / 'cache', Path(folder) / 'catalog'
            cache.mkdir()
            (cache / 'a.meta').write_bytes(struct.pack('<I', shader_catalog.SHADER_META_VERSION) + b'x')
            (cache / 'old.meta').write_bytes(struct.pack('<I', 7) + b'x')
            (cache / 'p.key').write_bytes(struct.pack('<I', shader_catalog.PIPELINE_KEY_VERSION) + b'y')
            (cache / 'a.spv').write_bytes(b'not shipped')
            self.assertEqual(shader_catalog.merge(catalog, [cache]), (2, 2))
            self.assertEqual(sorted(p.name for p in catalog.iterdir()), ['a.meta', 'p.key'])
            self.assertEqual(shader_catalog.merge(catalog, [cache]), (0, 2))

    def test_the_cache_profile_and_shader_build_are_not_shipped(self):
        # Any build seeds from the catalog; only the cache it seeds records the shader build.
        with tempfile.TemporaryDirectory() as folder:
            cache, catalog = Path(folder) / 'cache', Path(folder) / 'catalog'
            cache.mkdir()
            (cache / 'a.meta').write_bytes(struct.pack('<I', shader_catalog.SHADER_META_VERSION))
            (cache / 'build.bin').write_bytes(b'0123456789abcdef')
            (cache / 'profile.bin').write_bytes(b'\x01' * 64)
            self.assertEqual(shader_catalog.merge(catalog, [cache]), (1, 1))
            self.assertEqual([p.name for p in catalog.iterdir()], ['a.meta'])

    def test_rejected_translations_are_left_out(self):
        with tempfile.TemporaryDirectory() as folder:
            cache, catalog = Path(folder) / 'cache', Path(folder) / 'catalog'
            cache.mkdir()
            for name in ('a.meta', 'b.meta'):
                (cache / name).write_bytes(struct.pack('<I', shader_catalog.SHADER_META_VERSION))
            self.assertEqual(shader_catalog.merge(catalog, [cache], exclude=['b.meta']), (1, 1))


@unittest.skipUnless(GAME, 'BB_TEST_GAME_DIR not set')
class RealGameTests(unittest.TestCase):
    def test_every_shader_archive_program_is_found(self):
        found = shader_code.collect(GAME, None)
        self.assertGreater(len(found), 4000)
        # Geometry shaders keep their copy shaders under the same hash.
        copies = [key for key in found if key[1]]
        self.assertTrue(copies)
        self.assertTrue(all((key[0], False) in found for key in copies))


if __name__ == '__main__':
    unittest.main()
