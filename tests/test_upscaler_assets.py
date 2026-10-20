import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'launcher'))
from bbport_assets import (
    fsr411_problem,
    fsr4_files,
    validate_fsr4_file,
    fsr4_missing,
    fsr4_gpu_supported,
)


class UpscalerAssetsTests(unittest.TestCase):
    def test_tier_depends_on_output_not_render_preset(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertIn('t2160_m0/spd.spv', fsr411_problem(root, '3840x2160', 3))
            self.assertIn('t2160_m0/spd.spv', fsr411_problem(root, '2560x1440', 0))
            self.assertIn('t1080_m1/spd.spv', fsr411_problem(root, '1280x720', 4))

    def test_partial_model_is_not_reported_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / 't2160_m0'
            folder.mkdir()
            (folder / 'spd.spv').write_bytes(bytes(20))
            self.assertIn('prepass.spv', fsr411_problem(root, '3840x2160', 0))

    def test_complete_model_and_wrong_initializer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / 't1080_m0'
            folder.mkdir()
            names = ['spd', 'prepass', 'pass0_post', 'postpass', 'rcas']
            for i in range(1, 13):
                names.extend([f'pass{i}', f'pass{i}_post'])
            for name in names:
                (folder / (name+'.spv')).write_bytes(bytes(20))
            (folder / 'initializer.bin').write_bytes(bytes(8))
            self.assertIn('initializer.bin', fsr411_problem(root, '1920x1080', 1))
            (folder / 'initializer.bin').write_bytes(bytes(131072))
            self.assertIsNone(fsr411_problem(root, '1920x1080', 1))

    def test_fsr4_files_count_and_content(self):
        files = fsr4_files()
        self.assertEqual(len(files), 189)
        self.assertIn('LICENSE-FSR4-v07.txt', files)
        self.assertIn('rcas.spv', files)
        self.assertIn('spd_auto_exposure.spv', files)
        self.assertIn('fsr4_model_v07_i8_quality_initializers.bin', files)
        self.assertIn('fsr4_model_v07_i8_quality_1080_pass1.spv', files)
        self.assertIn('fsr4_model_v07_i8_balanced_2160_post.spv', files)

    def test_validate_fsr4_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Empty file
            empty = root / 'empty.spv'
            empty.touch()
            self.assertFalse(validate_fsr4_file(empty))

            # Non-modulo-4 SPIR-V
            bad_spv = root / 'bad.spv'
            bad_spv.write_bytes(b'\x03\x02\x23\x07' + bytes(17))
            self.assertFalse(validate_fsr4_file(bad_spv))

            # Valid SPIR-V
            valid_spv = root / 'valid.spv'
            valid_spv.write_bytes(b'\x03\x02\x23\x07' + bytes(16))
            self.assertTrue(validate_fsr4_file(valid_spv))

            # Initializer binary
            init_bad = root / 'fsr4_model_v07_i8_quality_initializers.bin'
            init_bad.write_bytes(bytes(100))
            self.assertFalse(validate_fsr4_file(init_bad))
            init_good = root / 'fsr4_model_v07_i8_quality_initializers.bin'
            init_good.write_bytes(bytes(89216))
            self.assertTrue(validate_fsr4_file(init_good))

            # Pre-weights binary
            weights_bad = root / 'fsr4_model_v07_i8_quality_pre_weights.bin'
            weights_bad.write_bytes(bytes(500))
            self.assertFalse(validate_fsr4_file(weights_bad))
            weights_good = root / 'fsr4_model_v07_i8_quality_pre_weights.bin'
            weights_good.write_bytes(bytes(1024))
            self.assertTrue(validate_fsr4_file(weights_good))

            # JSON manifest
            json_file = root / 'fsr4_model_v07_i8_quality_shader_manifest.json'
            json_file.write_text('{"version": 1}', encoding='utf-8')
            self.assertTrue(validate_fsr4_file(json_file))

            # License text
            lic_file = root / 'LICENSE-FSR4-v07.txt'
            lic_file.write_text('AMD FidelityFX MIT License', encoding='utf-8')
            self.assertTrue(validate_fsr4_file(lic_file))

    def test_fsr4_missing_reports_all_when_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            missing = fsr4_missing(root)
            self.assertEqual(len(missing), 189)

