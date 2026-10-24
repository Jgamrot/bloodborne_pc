"""Independent CPU regressions. Run with unittest discover -s tests.

BB_CPU_TEST_ROOT selects a reviewed checkout without copying game data.
BB_CPU_DEPS_DIR explicitly selects optional Capstone/Keystone test packages.
BB_CPU_GAME_DIR names a 1.09 game folder: the allocator span tests read their function
bytes from its eboot.bin (the repository holds no game bytes) and skip without it.
Native cases execute only audited translated baseline bodies, never BMI input.
"""
import copy
import ctypes as ct
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import random
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get('BB_CPU_TEST_ROOT', HERE.parent)).resolve()
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / 'scripts'))
if os.environ.get('BB_CPU_DEPS_DIR'):
    sys.path.insert(0, os.environ['BB_CPU_DEPS_DIR'])
import cpu_compat
from cpu_harness import (NativeHarness, REGISTERS, MASK64, reference, register_name,
                         audit_baseline, movbe_reference, ARITHMETIC_FLAGS)
from allocator_fixture import (SOURCE_SHA256, FUNCTION_SHA256, FUNCTION_START,
                               FUNCTION_END, SPANS, span_bytes,
                               expected_state, subtract32)

try:
    import capstone
    import keystone
    if not hasattr(capstone, 'Cs') or not hasattr(keystone, 'Ks'):
        raise ImportError('Test dependency files are inaccessible')
except ImportError as error:
    DEPENDENCY_ERROR = str(error)
else:
    DEPENDENCY_ERROR = None


def fixture():
    image = bytearray(b'\x90' * 4096)
    original = bytes.fromhex('c4e2f8f3c8')  # BLSR rax, rax, decoded only
    image[32:37] = original
    digest = 'a' * 64
    return dict(image=image, segments=[(0, 4096, 5)], main={'sha256': digest},
                modules=[], relocations=[], plan={'version': cpu_compat.PLAN_VERSION, 'modules': {'eboot.bin': digest},
                'sites': [{'module': 'eboot.bin', 'address': 32, 'length': 5,
                           'check': cpu_compat.site_check(original),
                           'body': '90', 'mnemonic': 'blsr'}], 'unhandled': []}, active=True)


def short_fixture(code=bytes.fromhex('f30fbdc1'), moved=bytes.fromhex('89c3'), translation='90'):
    """A short span: an LZCNT (or `code`) too short for a jump and the instruction after it."""
    data = fixture()
    original = code + moved
    data['image'][32:32 + len(original)] = original
    data['plan']['sites'][0] = {
        'kind': 'short_span', 'module': 'eboot.bin', 'address': 32, 'length': len(original),
        'check': cpu_compat.site_check(original), 'mnemonic': 'lzcnt', 'body': translation, 'rip_fixups': [],
        'span': {'pieces': [['lzcnt', 32, len(code), len(translation) // 2], ['move', 32 + len(code), len(moved), 0]],
                 'function': [0, 4096],
                 'entry_audit': {'method': cpu_compat.SHORT_SPAN_METHOD, 'global_indirect_proof': False,
                                 'known_entries': [], 'unresolved_candidates': []}}}
    return data


class ApplyImageTests(unittest.TestCase):
    def reject(self, data):
        before = copy.deepcopy(data)
        with self.assertRaises(ValueError):
            cpu_compat.patch_image(**data)
        self.assertEqual(before, data, 'Rejection mutated caller data')

    def test_positive_jump_return_segment_report_and_input_immutability(self):
        data = fixture()
        before = copy.deepcopy(data)
        image, segments, report = cpu_compat.patch_image(**data)
        self.assertEqual(data, before)
        self.assertIsInstance(image, bytearray)
        target = 37 + struct.unpack_from('<i', image, 33)[0]
        self.assertEqual(image[32], 0xe9)
        self.assertEqual(image[target], 0x90)
        self.assertEqual(image[target + 1], 0xe9)
        self.assertEqual(target + 6 + struct.unpack_from('<i', image, target + 2)[0], 37)
        self.assertTrue(any(start <= target < start + size and flags & 1 for start, size, flags in segments))
        self.assertEqual(image[:32], before['image'][:32])
        self.assertEqual(image[37:4096], before['image'][37:])
        self.assertEqual(report['patched_sites'], 1)
        self.assertEqual(report['counts_by_instruction'], {'blsr': 1})
        self.assertEqual(report['schema_version'], 1)
        json.dumps(report)

    def test_disabled_ignores_invalid_or_missing_plan_and_keeps_bytes(self):
        data = fixture()
        data.update(active=False, plan={'bad': object()})
        image, segments, report = cpu_compat.patch_image(**data)
        self.assertEqual(image, data['image'])
        self.assertEqual(segments, data['segments'])
        self.assertFalse(report['enabled'])
        self.assertEqual(report['patched_sites'], 0)
        data.update(active=None, plan=None)
        with patch.dict(os.environ, {'BB_LEGACY_CPU': '0', 'BB_CONFIG': 'does-not-exist.ini'}):
            self.assertEqual(cpu_compat.patch_image(**data)[0], data['image'])

    def test_reject_hash_signature_address_length_and_plan_defects(self):
        mutations = [
            lambda d: d['main'].update(sha256='b' * 64),
            lambda d: d['image'].__setitem__(32, 0),
            lambda d: d['plan'].update(version=999),
            lambda d: d['plan'].update(version=3),
            lambda d: d['plan'].update(version=4),
            lambda d: d['plan'].update(version=True),
            lambda d: d['plan'].pop('unhandled'),
            lambda d: d['plan']['sites'][0].update(address=-1),
            lambda d: d['plan']['sites'][0].update(address=4094),
            lambda d: d['plan']['sites'][0].update(address=True),
            lambda d: d['plan']['sites'][0].update(length=4),
            lambda d: d['plan']['sites'][0].update(length=6),
            lambda d: d['plan']['sites'][0].update(length=True),
            lambda d: d['plan']['sites'][0].update(check='0' * 16),
            lambda d: d['plan']['sites'][0].update(check='xx' * 8),
            lambda d: d['plan']['sites'][0].pop('check'),
            lambda d: d['plan']['sites'][0].update(body=''),
            lambda d: d['plan']['sites'][0].update(body='90' * 4097),
            lambda d: d['plan']['sites'][0].update(module='missing.prx'),
            lambda d: d['plan']['sites'][0].update(mnemonic='unsupported'),
            lambda d: d['plan']['sites'][0].update(mnemonic='blsr rax, rax'),
            lambda d: d['plan']['sites'].append(copy.deepcopy(d['plan']['sites'][0])),
            lambda d: d.update(segments=[(0, 4096, 4)]),
            lambda d: d.update(segments=[(0, 4097, 5)]),
            lambda d: d.update(segments=[(0, 2000, 5), (1000, 1000, 5)]),
            lambda d: d.update(relocations=[(29, 0, 0, 0)]),
            lambda d: d.update(relocations=[(36, 0, 0, 0)]),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(defect=index):
                data = fixture()
                mutate(data)
                self.reject(data)

    def test_relocation_next_to_site_is_preserved(self):
        data = fixture()
        data['relocations'] = [(24, 0, 0, 0), (37, 0, 0, 0)]
        result = cpu_compat.patch_image(**data)[0]
        self.assertEqual(result[24:32], data['image'][24:32])
        self.assertEqual(result[37:45], data['image'][37:45])

    def test_module_base_and_rip_fixup(self):
        data = fixture()
        site = data['plan']['sites'][0]
        site.update(body='488b0500000000', rip_fixups=[{'offset': 3, 'next_offset': 7, 'target': 100}])
        result, _, _ = cpu_compat.patch_image(**data)
        target = 37 + struct.unpack_from('<i', result, 33)[0]
        self.assertEqual(target + 7 + struct.unpack_from('<i', result, target + 3)[0], 100)
        for defect in ({'offset': 6}, {'next_offset': 6}, {'target': 4096}, {'offset': -1}):
            invalid = copy.deepcopy(data)
            invalid['plan']['sites'][0]['rip_fixups'][0].update(defect)
            self.reject(invalid)
        invalid = copy.deepcopy(data)
        invalid['plan']['sites'][0]['rip_fixups'] *= 2
        self.reject(invalid)
        data = fixture()
        data['image'].extend(b'\x90' * 4096)
        data['image'][4128:4133] = data['image'][32:37]
        data['segments'].append((4096, 4096, 5))
        data['modules'] = [{'file': 'test.prx', 'base': 4096, 'size': 4096, 'sha256': 'b' * 64}]
        data['plan']['modules']['test.prx'] = 'b' * 64
        data['plan']['sites'][0]['module'] = 'test.prx'
        result = cpu_compat.patch_image(**data)[0]
        self.assertEqual(result[4128], 0xe9)
        self.assertEqual(result[32:37], data['image'][32:37])

    def test_image_limit_is_checked_without_large_allocation(self):
        with patch.object(cpu_compat, 'MAX_IMAGE_SIZE', 4096):
            self.reject(fixture())

    def test_atomic_publication_preserves_prior_artifact_on_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / 'image.bin'
            destination.write_bytes(b'previous complete image')
            with self.assertRaisesRegex(RuntimeError, 'fixture failure'):
                with cpu_compat.atomic_output(destination) as stream:
                    stream.write(b'incomplete')
                    raise RuntimeError('fixture failure')
            self.assertEqual(destination.read_bytes(), b'previous complete image')
            self.assertEqual(list(Path(directory).iterdir()), [destination])
            with cpu_compat.atomic_output(destination) as stream:
                stream.write(b'new complete image')
            self.assertEqual(destination.read_bytes(), b'new complete image')

    def test_unhandled_count_instructions_fail_closed_and_override_is_explicit(self):
        for mnemonic in ('lzcnt', 'tzcnt'):
            data = fixture()
            data['plan']['unhandled'] = [{'module': 'eboot.bin', 'address': '0x64',
                                         'mnemonic': mnemonic,
                                         'reason': 'Too short for guarded jump'}]
            with self.subTest(instruction=mnemonic):
                with patch.dict(os.environ, {'BB_LEGACY_CPU_ALLOW_PARTIAL': '0'}):
                    self.reject(data)
                with patch.dict(os.environ, {'BB_LEGACY_CPU_ALLOW_PARTIAL': '1'}):
                    report = cpu_compat.patch_image(**data)[2]
                    self.assertEqual(report['unhandled_count'], 1)
                    self.assertEqual(report['unhandled_by_reason'], {'Too short for guarded jump': 1})

    def test_short_span_moves_neighbors_from_the_image(self):
        data = short_fixture()
        self.assertNotIn('89c3', json.dumps(data['plan']))
        image, segments, report = cpu_compat.patch_image(**data)
        target = 37 + struct.unpack_from('<i', image, 33)[0]
        self.assertEqual(image[32], 0xe9)
        self.assertEqual(image[37], 0x90)
        self.assertEqual(image[target:target + 3], bytes.fromhex('9089c3'))
        self.assertEqual(image[target + 3], 0xe9)
        self.assertEqual(target + 8 + struct.unpack_from('<i', image, target + 4)[0], 38)
        self.assertEqual(image[38:4096], data['image'][38:])
        self.assertEqual((report['patched_sites'], report['short_span_patches'], report['unhandled_count'],
                          report['semantic_risk_sites'], report['counts_by_instruction']),
                         (1, 1, 0, 0, {'lzcnt': 1}))
        # Entries at the span's first byte or right after it are fine.
        data['main']['symbols'] = [{'section': 1, 'value': 32}, {'section': 1, 'value': 38}]
        data['relocations'] = [(1000, 0, 30, 2)]
        self.assertEqual(cpu_compat.patch_image(**data)[2]['short_span_patches'], 1)

    def test_short_span_defects_reject(self):
        pieces = lambda d: d['plan']['sites'][0]['span']['pieces']
        site = lambda d: d['plan']['sites'][0]
        audit = lambda d: d['plan']['sites'][0]['span']['entry_audit']
        mutations = [
            lambda d: pieces(d)[1].__setitem__(1, 37),
            lambda d: pieces(d)[0].__setitem__(3, 2),
            lambda d: pieces(d)[1].__setitem__(3, 1),
            lambda d: pieces(d)[1].__setitem__(0, 'call'),
            lambda d: pieces(d)[1].__setitem__(2, True),
            lambda d: pieces(d).pop(),
            lambda d: pieces(d).extend([['move', 38, 1, 0]] * 3),
            lambda d: pieces(d)[0].__setitem__(0, 'movbe'),
            lambda d: site(d).update(mnemonic='tzcnt'),
            lambda d: site(d).update(length=31),
            lambda d: site(d).update(kind='span'),
            lambda d: site(d).update(rip_fixups=[{'offset': 0, 'next_offset': 4, 'target': 0}]),
            lambda d: site(d)['span'].update(safe=True),
            lambda d: site(d)['span'].pop('entry_audit'),
            lambda d: audit(d).update(method='safe'),
            lambda d: audit(d).update(global_indirect_proof=True),
            lambda d: audit(d).update(known_entries=[{'kind': 'symbol', 'address': 36}]),
            lambda d: audit(d).update(unresolved_candidates=[{'source': 0, 'target': 36}]),
            lambda d: d['main'].update(symbols=[{'section': 1, 'value': 36}]),
            lambda d: d.update(relocations=[(1000, 0, 30, 6)]),
            lambda d: d['main'].update(relocs=[(1000, 8, 0, 33)]),
            lambda d: d['image'].__setitem__(37, 0xc2),
            lambda d: d['plan'].update(version=4),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(defect=index):
                data = short_fixture()
                mutate(data)
                self.reject(data)

    def test_short_sites_switch_and_bsr_simulation(self):
        data = short_fixture()
        with patch.dict(os.environ, {'BB_LEGACY_CPU_SHORT_SITES': '0'}):
            image, _, report = cpu_compat.patch_image(**data)
            self.assertEqual(image[:4096], data['image'])
            self.assertEqual((report['patched_sites'], report['unhandled_count'], report['semantic_risk_sites'],
                              report['short_sites'], report['simulated_bsr_sites']), (0, 1, 1, False, 0))
            with patch.dict(os.environ, {'BB_LEGACY_CPU_ALLOW_PARTIAL': '0'}):
                self.reject(data)
            with patch.dict(os.environ, {'BB_LEGACY_CPU_SIMULATE_BSR': '1'}):
                image, _, report = cpu_compat.patch_image(**data)
                self.assertEqual(image[32:38], bytes.fromhex('3e0fbdc189c3'))
                self.assertEqual(report['simulated_bsr_sites'], 1)
        with patch.dict(os.environ, {'BB_LEGACY_CPU_SIMULATE_BSR': '1'}):
            report = cpu_compat.patch_image(**data)[2]
            self.assertEqual((report['short_span_patches'], report['simulated_bsr_sites']), (1, 0))
        # A long instruction translated along goes back to its own site.
        data = short_fixture(moved=bytes.fromhex('c4e2f8f3c8'), translation='9090')
        data['plan']['sites'][0]['span']['pieces'] = [['lzcnt', 32, 4, 1], ['blsr', 36, 5, 1]]
        with patch.dict(os.environ, {'BB_LEGACY_CPU_SHORT_SITES': '0'}):
            image, _, report = cpu_compat.patch_image(**data)
        target = 41 + struct.unpack_from('<i', image, 37)[0]
        self.assertEqual(image[32:36], data['image'][32:36])
        self.assertEqual(image[36], 0xe9)
        self.assertEqual(image[target], 0x90)
        self.assertEqual(target + 6 + struct.unpack_from('<i', image, target + 2)[0], 41)
        self.assertEqual((report['patched_sites'], report['counts_by_instruction'], report['unhandled_count']),
                         (1, {'blsr': 1}, 1))
        self.assertEqual(cpu_compat.patch_image(**data)[2]['counts_by_instruction'], {'lzcnt': 1, 'blsr': 1})

    def test_bsr_simulation_of_plan_unhandled_sites(self):
        data = fixture()
        data['image'][64:69] = bytes.fromhex('66f30fbcc1')
        data['image'][80:84] = bytes.fromhex('0f38f007')
        data['plan']['unhandled'] = [
            {'module': 'eboot.bin', 'address': '0x40', 'mnemonic': 'tzcnt', 'reason': 'short'},
            {'module': 'eboot.bin', 'address': '0x50', 'mnemonic': 'movbe', 'reason': 'short'}]
        self.assertEqual(cpu_compat.patch_image(**data)[0][64:84], data['image'][64:84])
        with patch.dict(os.environ, {'BB_LEGACY_CPU_SIMULATE_BSR': '1'}):
            image, _, report = cpu_compat.patch_image(**data)
        self.assertEqual(image[64:69], bytes.fromhex('663e0fbcc1'))
        self.assertEqual(image[80:84], data['image'][80:84])
        self.assertEqual(report['simulated_bsr_sites'], 1)

    def test_bit_scan_prefix_forms(self):
        for code, prefixes in (('f30fbdc1', '3e'), ('f30fbc07', '3e'), ('66f30fbdc1', '663e'),
                               ('f3480fbdc1', '3e48'), ('49f3490fbdc1', '493e49'), ('f3f30fbcc1', '3e3e'),
                               ('f34c0fbd4c2408', '3e4c'), ('f30fb8c1', None), ('0fbdc1', None),
                               ('f3', None), ('', None)):
            with self.subTest(code=code):
                found = cpu_compat.as_bit_scan(bytes.fromhex(code))
                self.assertEqual(found.hex() if found is not None else None, prefixes)

    def test_switch_defaults(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(cpu_compat.short_sites_enabled())
            self.assertFalse(cpu_compat.simulate_bsr())
        with patch.dict(os.environ, {'BB_LEGACY_CPU_SHORT_SITES': '0', 'BB_LEGACY_CPU_SIMULATE_BSR': '1'}):
            self.assertFalse(cpu_compat.short_sites_enabled())
            self.assertTrue(cpu_compat.simulate_bsr())


class ReferenceTests(unittest.TestCase):
    def test_documented_boundary_values(self):
        self.assertEqual(reference('blsr', 64, 0), (0, 65, 2241))
        self.assertEqual(reference('blsi', 32, 0x80000000), (0x80000000, 129, 2241))
        self.assertEqual(reference('blsmsk', 32, 0), (0xffffffff, 129, 2241))
        self.assertEqual(reference('tzcnt', 32, 0), (32, 1, 65))
        self.assertEqual(reference('lzcnt', 64, 1 << 63), (0, 64, 65))
        self.assertEqual(reference('bextr', 32, 0xffffffff, (255 << 8) | 31), (1, 0, 2113))
        self.assertEqual(reference('bextr', 32, 0xffffffff, (32 << 8) | 32), (0, 64, 2113))

    def test_movbe_documented_byte_order_and_width(self):
        self.assertEqual(movbe_reference(16, 0x1234), 0x3412)
        self.assertEqual(movbe_reference(32, 0x12345678), 0x78563412)
        self.assertEqual(movbe_reference(64, 0x0123456789abcdef), 0xefcdab8967452301)
        self.assertEqual(movbe_reference(16, 0xabcd1234), 0x3412)

    def test_allocator_cmp_sub_defined_flag_boundaries(self):
        for left, right, result, flags in (
                (0, 1, 0xffffffff, 0x95), (16, 1, 15, 0x14),
                (0x80000000, 1, 0x7fffffff, 0x814),
                (0x7fffffff, 0xffffffff, 0x80000000, 0x885),
                (16, 16, 0, 0x44), (31, 32, 0xffffffff, 0x85)):
            self.assertEqual(subtract32(left, right), (result, flags))


@unittest.skipIf(DEPENDENCY_ERROR or os.name != 'nt', DEPENDENCY_ERROR or 'Windows x64 only')
class TranslatedBodyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('tested_cpu_builder', ROOT / 'tools/build_cpu_compat.py')
        cls.builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.builder)
        cls.random = random.Random(0x37701650)
        cls.executions = 0
        cls.movbe_executions = 0

    def check(self, harness, mnemonic, width, destination, registers, source, other=0, stack_values=None):
        value, flags, defined = reference(mnemonic, width, source, other)
        expected = dict(registers, rsp=harness.guest_rsp)
        expected[destination] = (registers[destination] & ~0xffff | value) if width == 16 else value
        actual, actual_flags, before, after = harness.run(registers, stack_values=stack_values)
        self.assertEqual(actual, expected, f'{mnemonic}/{width}, destination={destination}')
        self.assertEqual(actual_flags & defined, flags)
        self.assertEqual(after, before, 'Translated body modified the SysV red zone')
        type(self).executions += 1

    def registers(self):
        return {reg: self.random.getrandbits(64) for reg in REGISTERS[:-1]}

    def test_persisted_plan_bodies_match_generator_and_decode_as_baseline(self):
        path = ROOT / 'tools/legacy-cpu-plan.json'
        if not path.exists():
            self.skipTest('Persisted plan absent from the selected test checkout')
        plan = json.loads(path.read_text(encoding='utf-8'))
        # The plan has no operands: with a game folder, decode them from its modules.
        game = os.environ.get('BB_CPU_GAME_DIR')
        modules = {}
        if game:
            for name, relative in (('eboot.bin', 'eboot.bin'), ('libc.prx', 'sce_module/libc.prx'),
                                   ('libSceFios2.prx', 'sce_module/libSceFios2.prx')):
                modules[name] = self.builder.module(Path(game) / relative)
        decoder = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
        for site in plan['sites']:
            body = bytes.fromhex(site['body'])
            with self.subTest(module=site['module'], address=site['address']):
                self.assertNotIn('bytes', site)
                audit_baseline(body, capstone)
                mod = modules.get(site['module'])
                if mod is None or site.get('kind') == 'count_span':
                    continue
                at = self.builder.file_offset(mod, site['address'], site['length'], True)
                original = bytes(mod['elf'][at:at + site['length']])
                self.assertEqual(cpu_compat.site_check(original), site['check'])
                if site.get('kind') == 'short_span':
                    # The body holds the translations only; moved instructions stay in the dump.
                    rows = list(decoder.disasm_lite(original, site['address']))
                    pieces = site['span']['pieces']
                    self.assertEqual([(r[0], r[1]) for r in rows], [(p[1], p[2]) for p in pieces])
                    expected = b''
                    for row, (kind, _, length, size) in zip(rows, pieces):
                        if kind == 'move':
                            self.assertTrue(self.builder.movable(row, row is rows[-1]), row)
                        else:
                            self.assertEqual(row[2], kind)
                            expected += self.builder.body(row[2], row[3])
                    self.assertEqual(body, expected)
                    self.assertTrue(any(p[0] == site['mnemonic'] and p[2] < 5 for p in pieces))
                    continue
                _, length, mnemonic, operands = next(decoder.disasm_lite(original, site['address']))
                self.assertEqual((length, mnemonic), (site['length'], site['mnemonic']))
                self.assertEqual(body, self.builder.body(mnemonic, operands))

    def test_every_gpr_width_alias_and_arithmetic_edges(self):
        names = REGISTERS[:-1]
        for width in (32, 64):
            values = [0, 1, 2, 3, 1 << (width - 1), (1 << width) - 1,
                      (1 << (width - 1)) - 1] + [self.random.getrandbits(width) for _ in range(5)]
            for mnemonic in ('andn', 'blsr', 'blsi', 'blsmsk', 'bextr', 'lzcnt', 'tzcnt'):
                for index, destination in enumerate(names):
                    for alias in ('distinct', 'source', 'control', 'all'):
                        source = destination if alias in ('source', 'all') else names[(index + 1) % len(names)]
                        other = destination if alias in ('control', 'all') else names[(index + 2) % len(names)]
                        regs = [destination, source] + ([other] if mnemonic in ('andn', 'bextr') else [])
                        operands = ', '.join(register_name(reg, width) for reg in regs)
                        body = self.builder.body(mnemonic, operands)
                        with self.subTest(instruction=mnemonic + ' ' + operands, alias=alias):
                            with NativeHarness(body, keystone, capstone) as harness:
                                for value in values:
                                    registers = self.registers()
                                    registers[source] = value
                                    if other != source:
                                        registers[other] = ((width + 1) << 8) | (value & 255) if mnemonic == 'bextr' else self.random.getrandbits(width)
                                    self.check(harness, mnemonic, width, destination, registers,
                                               registers[source], registers[other])

    def test_bextr_position_length_grid(self):
        for width in (32, 64):
            operands = ', '.join(register_name(reg, width) for reg in ('rcx', 'r10', 'r11'))
            with NativeHarness(self.builder.body('bextr', operands), keystone, capstone) as harness:
                for start in (0, 1, width - 1, width, width + 1, 255):
                    for length in (0, 1, width - 1, width, width + 1, 255):
                        for source in (0, (1 << width) - 1, 1 << (width - 1)):
                            registers = self.registers()
                            registers.update(r10=source, r11=(length << 8) | start | 0xffff0000)
                            self.check(harness, 'bextr', width, 'rcx', registers, source, registers['r11'])

    def test_count_16_bit_preserves_upper_destination(self):
        for mnemonic in ('lzcnt', 'tzcnt'):
            for destination in REGISTERS[:-1]:
                for source in (destination, 'rcx'):
                    operands = register_name(destination, 16) + ', ' + register_name(source, 16)
                    with NativeHarness(self.builder.body(mnemonic, operands), keystone, capstone) as harness:
                        for value in (0, 1, 0x8000, 0xffff):
                            registers = self.registers()
                            registers[source] = (registers[source] & ~0xffff) | value
                            self.check(harness, mnemonic, 16, destination, registers, registers[source])

    def test_memory_base_index_destination_alias_and_stack_redzone(self):
        memory = (ct.c_uint64 * 8)()
        for width in (32, 64):
            size = 'qword' if width == 64 else 'dword'
            for mnemonic in ('andn', 'bextr', 'blsr', 'blsi', 'blsmsk', 'lzcnt', 'tzcnt'):
                for address in ('rdi + rbx*2 + 16', 'rsp - 64', 'rsp + 32'):
                    destination = 'rdi'  # Also tests overwriting the address register.
                    args = [register_name(destination, width), f'{size} ptr [{address}]']
                    if mnemonic == 'andn':
                        args = [args[0], register_name('r10', width), args[1]]
                    elif mnemonic == 'bextr':
                        args += [register_name('rcx', width)]
                    with NativeHarness(self.builder.body(mnemonic, ', '.join(args)), keystone, capstone) as harness:
                        for value in (0, 1, 0xffffffffffffffff, 0x8000000000000000):
                            registers = self.registers()
                            registers.update(rdi=ct.addressof(memory), rbx=4, r10=0xf0f0, rcx=0xff01)
                            memory[3] = value
                            stack_values = {-64: value, 32: value}
                            source, other = (registers['r10'], value) if mnemonic == 'andn' else (value, registers['rcx'])
                            self.check(harness, mnemonic, width, destination, registers, source, other, stack_values)

    def check_movbe(self, harness, width, direction, register, registers, value, flags,
                    *, memory_address=None, target_offset=16, stack_offset=None):
        """Observe memory writes and flags separately from the body generator."""
        count = width // 8
        expected_registers = dict(registers, rsp=harness.guest_rsp)
        source = value if direction == 'load' else registers[register]
        swapped = movbe_reference(width, source)
        if direction == 'load':
            expected_registers[register] = ((registers[register] & ~0xffff) | swapped) if width == 16 else swapped
        initial_memory = bytearray(range(64))
        initial_memory[target_offset:target_offset + 8] = value.to_bytes(8, 'little')
        if memory_address is not None:
            ct.memmove(memory_address, bytes(initial_memory), 64)
        stack_values = {stack_offset: value} if stack_offset is not None else None
        output, actual_flags, before_zone, after_zone = harness.run(registers, flags, stack_values)
        self.assertEqual(output, expected_registers, f'MOVBE {direction}{width}, {register}')
        self.assertEqual(actual_flags & ARITHMETIC_FLAGS, flags & ARITHMETIC_FLAGS,
                         'MOVBE changed defined arithmetic flags')
        if stack_offset is not None:
            expected_stack = bytearray(harness.stack_window_before)
            if direction == 'store':
                start = stack_offset + 128
                expected_stack[start:start + count] = swapped.to_bytes(count, 'little')
            self.assertEqual(harness.stack_window_after, expected_stack,
                             'MOVBE changed stack bytes beyond its intended store')
        else:
            expected_memory = initial_memory
            if direction == 'store':
                expected_memory[target_offset:target_offset + count] = swapped.to_bytes(count, 'little')
            self.assertEqual(ct.string_at(memory_address, 64), expected_memory,
                             'MOVBE byte order, width or adjacent memory is wrong')
            self.assertEqual(after_zone, before_zone, 'MOVBE changed red zone')
        type(self).executions += 1
        type(self).movbe_executions += 1

    def test_movbe_load_store_all_gprs_aliases_widths_and_flags(self):
        memory = (ct.c_ubyte * 64)()
        values = (0, 1, MASK64, 0x0123456789abcdef, 0x8000000000000080)
        flags_cases = (0x202, 0x202 | ARITHMETIC_FLAGS) + tuple(
            0x202 | bit for bit in (1, 4, 16, 64, 128, 2048))
        names = REGISTERS[:-1]
        for width in (16, 32, 64):
            size = {16: 'word', 32: 'dword', 64: 'qword'}[width]
            for direction in ('load', 'store'):
                for index, register in enumerate(names):
                    for alias in (False, True):
                        base = register if alias else names[(index + 1) % len(names)]
                        operands = [register_name(register, width), f'{size} ptr [{base} + 16]']
                        if direction == 'store':
                            operands.reverse()
                        with self.subTest(instruction='movbe ' + ', '.join(operands), alias=alias):
                            with NativeHarness(self.builder.body('movbe', ', '.join(operands)), keystone, capstone) as harness:
                                for value in values:
                                    for flags in flags_cases:
                                        registers = self.registers()
                                        registers[register] = value
                                        registers[base] = ct.addressof(memory)
                                        self.check_movbe(harness, width, direction, register, registers,
                                                         value, flags, memory_address=ct.addressof(memory))

    def test_movbe_stack_index_and_rip_memory(self):
        memory = (ct.c_ubyte * 64)()
        for width in (16, 32, 64):
            size = {16: 'word', 32: 'dword', 64: 'qword'}[width]
            for direction in ('load', 'store'):
                for address in ('rsp - 64', 'rsp + 32', 'rdi + rbx*2 + 8', 'rip + 4'):
                    register = 'rbx' if 'rbx' in address else 'r10'
                    operands = [register_name(register, width), f'{size} ptr [{address}]']
                    if direction == 'store':
                        operands.reverse()
                    kwargs = {'rip_data': bytes(64), 'rip_offset': 16} if address.startswith('rip') else {}
                    body = self.builder.body('movbe', ', '.join(operands))
                    with self.subTest(instruction='movbe ' + ', '.join(operands)):
                        with NativeHarness(body, keystone, capstone, **kwargs) as harness:
                            for value in (0, 1, 0x123456789abcdef0, MASK64):
                                for flags in (0x202, 0x202 | ARITHMETIC_FLAGS):
                                    registers = self.registers()
                                    registers.update(rdi=ct.addressof(memory), rbx=4, r10=value)
                                    options = {'memory_address': ct.addressof(memory)}
                                    if address.startswith('rsp'):
                                        options = {'stack_offset': -64 if '-' in address else 32}
                                    elif address.startswith('rip'):
                                        options = {'memory_address': harness.rip_data_address}
                                    self.check_movbe(harness, width, direction, register, registers, value,
                                                     flags, **options)

    def test_movbe_deliberate_endian_width_flag_and_source_defects_are_detected(self):
        memory = (ct.c_ubyte * 64)()
        assembler = keystone.Ks(keystone.KS_ARCH_X86, keystone.KS_MODE_64)
        cases = [('load', 'mov eax, dword ptr [rdi + 16]', b''),
                 ('load', None, bytes(assembler.asm('stc')[0])),
                 ('store', 'mov qword ptr [rdi + 16], rax', b''),
                 ('store', None, bytes(assembler.asm('mov rax, 123')[0]))]
        for direction, replacement, suffix in cases:
            operands = 'eax, dword ptr [rdi + 16]' if direction == 'load' else 'dword ptr [rdi + 16], eax'
            body = bytes(assembler.asm(replacement)[0]) if replacement else self.builder.body('movbe', operands)
            with self.subTest(direction=direction, defect=replacement or suffix.hex()):
                with NativeHarness(body + suffix, keystone, capstone) as harness:
                    registers = self.registers()
                    registers.update(rdi=ct.addressof(memory), rax=0x0123456789abcdef)
                    with self.assertRaises(AssertionError):
                        self.check_movbe(harness, 32, direction, 'rax', registers, 0x0123456789abcdef,
                                         0x202, memory_address=ct.addressof(memory))
        # Original MOVBE bytes are rejected before the native harness can call them.
        with self.assertRaises(ValueError):
            audit_baseline(bytes.fromhex('0f38f04104'), capstone)

    def test_movbe_rip_fixups_roundtrip_through_guarded_image(self):
        assembler = keystone.Ks(keystone.KS_ARCH_X86, keystone.KS_MODE_64)
        decoder = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
        decoder.detail = True
        for width in (16, 32, 64):
            size = {16: 'word', 32: 'dword', 64: 'qword'}[width]
            for direction in ('load', 'store'):
                operands = [register_name('rax', width), f'{size} ptr [rip + 64]']
                if direction == 'store':
                    operands.reverse()
                instruction_text = 'movbe ' + ', '.join(operands)
                original = bytes(assembler.asm(instruction_text)[0])
                instruction = next(decoder.disasm(original, 32))
                body = self.builder.body('movbe', instruction.op_str)
                fixups = self.builder.rip_fixups(instruction, body)
                self.assertEqual(len(fixups), 1)
                self.assertEqual(fixups[0]['target'], 32 + len(original) + 64)
                data = fixture()
                data['image'][32:32 + len(original)] = original
                data['plan']['sites'][0].update(length=len(original), check=cpu_compat.site_check(original),
                    body=body.hex(), mnemonic='movbe', rip_fixups=fixups)
                translated = cpu_compat.patch_image(**data)[0]
                target = 37 + struct.unpack_from('<i', translated, 33)[0]
                fixup = fixups[0]
                actual = target + fixup['next_offset'] + struct.unpack_from('<i', translated, target + fixup['offset'])[0]
                self.assertEqual(actual, 32 + len(original) + 64)

    def test_deliberate_result_flag_register_and_redzone_defects_are_detected(self):
        good = self.builder.body('blsr', 'rax, rdx')
        assembler = keystone.Ks(keystone.KS_ARCH_X86, keystone.KS_MODE_64)
        defects = ('mov rax, 123', 'stc', 'mov rbx, 123', 'mov byte ptr [rsp-8], 0')
        for defect in defects:
            bad = good + bytes(assembler.asm(defect)[0])
            with self.subTest(defect=defect), NativeHarness(bad, keystone, capstone) as harness:
                registers = self.registers()
                registers['rdx'] = 7
                with self.assertRaises(AssertionError):
                    self.check(harness, 'blsr', 64, 'rax', registers, 7)
        for source_bytes in ('c4e2f8f3c8', 'f3480fbcc0', 'f3480fbdc0', 'c3'):
            with self.assertRaises(ValueError):
                audit_baseline(bytes.fromhex(source_bytes), capstone)

    def test_short_span_shapes(self):
        span = self.builder.short_span
        lz, mov = (0x10, 4, 'lzcnt', 'eax, ecx'), (0x14, 2, 'mov', 'ebx, eax')
        start, end, pieces = span([lz, mov, (0x16, 2, 'jmp', '0x10')], 0)
        self.assertEqual((start, end, [p[0] for p in pieces]), (0x10, 0x16, ['translate', 'move']))
        self.assertEqual(span([lz, (0x14, 1, 'ret', '')], 0)[1], 0x15)
        self.assertEqual(span([lz, (0x14, 5, 'blsr', 'eax, ecx')], 0)[2][1][0], 'translate')
        for following in ((0x14, 7, 'mov', 'eax, dword ptr [rip + 0x10]'), (0x14, 2, 'jmp', '0x10'),
                          (0x14, 9, 'mov', 'rax, qword ptr fs:[0]'), (0x14, 5, 'call', '0x100'),
                          (0x14, 9, 'movbe', 'eax, dword ptr [rip + 0x10]'), (0x14, 2, 'jmp', 'rax')):
            with self.subTest(following=following), self.assertRaises(ValueError):
                span([lz, following], 0)
        with self.assertRaises(ValueError):
            span([lz], 0)
        previous = (0x0c, 4, 'mov', 'edx, dword ptr [rcx]')
        movbe = (0x10, 4, 'movbe', 'dword ptr [rcx], edx')
        start, end, pieces = span([previous, movbe, (0x14, 2, 'jmp', '0x0')], 1, backward=True)
        self.assertEqual((start, end, [p[0] for p in pieces]), (0x0c, 0x14, ['move', 'translate']))
        for before in ((0x0f, 1, 'ret', ''), (0x0b, 5, 'call', '0x100'), (0x0c, 4, 'lzcnt', 'eax, ecx')):
            with self.subTest(before=before), self.assertRaises(ValueError):
                span([before, movbe], 1, backward=True)

    def test_jump_table_targets_name_instruction_starts(self):
        image = bytearray(0x100)
        rows = [(0x0, 7, 'lea', 'rax, [rip + 0x39]'), (0x7, 2, 'jmp', 'rax'),
                (0x9, 4, 'lzcnt', 'eax, ecx'), (0xd, 2, 'mov', 'ebx, eax')]
        struct.pack_into('<4i', image, 0x40, 0x9 - 0x40, 0xd - 0x40, 0xa - 0x40, 0x200)
        mod = {'ph': [{'type': 1, 'vaddr': 0, 'filesz': len(image), 'offset': 0}], 'elf': image}
        self.assertEqual(self.builder.jump_table_targets(mod, rows), {0x9, 0xd})
        rows[1] = (0x7, 2, 'jmp', '0x9')
        self.assertEqual(self.builder.jump_table_targets(mod, rows), set())

    def test_short_span_trampoline_runs_both_instructions(self):
        # lzcnt eax, ecx followed by mov ebx, eax or mov rbx, rax.
        for width, moved in ((32, '89c3'), (32, '4889c3')):
            data = short_fixture(moved=bytes.fromhex(moved), translation=self.builder.body('lzcnt', 'eax, ecx').hex())
            image, _, report = cpu_compat.patch_image(**data)
            target = 37 + struct.unpack_from('<i', image, 33)[0]
            size = len(data['plan']['sites'][0]['body']) // 2 + len(moved) // 2
            self.assertEqual(image[target + size], 0xe9)
            with NativeHarness(bytes(image[target:target + size]), keystone, capstone) as harness:
                for value in (0, 1, 0x80000000, MASK64, 0x0000000100000000):
                    registers = self.registers()
                    registers['rcx'] = value
                    count, flags, defined = reference('lzcnt', width, value)
                    output, actual_flags, before, after = harness.run(registers)
                    self.assertEqual(output, dict(registers, rax=count, rbx=count, rsp=harness.guest_rsp))
                    self.assertEqual(actual_flags & defined, flags)
                    self.assertEqual(after, before)

    @classmethod
    def tearDownClass(cls):
        print(f'CPU baseline executions={cls.executions}; MOVBE executions={cls.movbe_executions}; '
              f'seed=0x37701650; root={ROOT}', flush=True)


@unittest.skipIf(DEPENDENCY_ERROR or os.name != 'nt', DEPENDENCY_ERROR or 'Windows x64 only')
@unittest.skipUnless(os.environ.get('BB_CPU_GAME_DIR'), 'BB_CPU_GAME_DIR (a 1.09 game folder) not set')
class AllocatorSpanTests(unittest.TestCase):
    """D015 public application and full-state oracle; no original count executes."""

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('tested_allocator_builder', ROOT / 'tools/build_cpu_compat.py')
        cls.builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.builder)
        plan = json.loads((ROOT / 'tools/legacy-cpu-plan.json').read_text(encoding='utf-8'))
        cls.sites = [copy.deepcopy(s) for s in plan['sites'] if s.get('kind') == 'count_span']
        if plan['version'] != cpu_compat.PLAN_VERSION or {s['address'] for s in cls.sites} != {s[0] for s in SPANS}:
            raise AssertionError('Selected CPU subject must contain exactly the four D015 spans')
        mod = cls.builder.module(Path(os.environ['BB_CPU_GAME_DIR']) / 'eboot.bin')
        at = cls.builder.file_offset(mod, FUNCTION_START, FUNCTION_END - FUNCTION_START, True)
        cls.function = bytes(mod['elf'][at:at + FUNCTION_END - FUNCTION_START])
        if mod['sha256'] != SOURCE_SHA256 or hashlib.sha256(cls.function).hexdigest() != FUNCTION_SHA256:
            raise AssertionError('BB_CPU_GAME_DIR is not the inspected 1.09 eboot.bin')
        cls.base_image = bytearray((FUNCTION_END + 4095) & ~4095)
        cls.base_image[FUNCTION_START:FUNCTION_END] = cls.function
        cls.base_hash = hashlib.sha256(cls.base_image).hexdigest()
        cls.random = random.Random(0xd0153770)
        cls.executions = 0
        cls.context_executions = 0
        cls.rejections = 0
        with patch.dict(os.environ, {'BB_LEGACY_CPU_ALLOW_PARTIAL': '1'}):
            cls.translated, cls.segments, cls.report = cpu_compat.patch_image(**cls.fixture())
        cls.reports = {s['address']: s for s in cls.report['span_sites']}

    @classmethod
    def fixture(cls):
        return dict(image=cls.base_image, segments=[(0, len(cls.base_image), 5)],
                    main={'sha256': SOURCE_SHA256}, modules=[], relocations=[], active=True,
                    plan={'version': cpu_compat.PLAN_VERSION, 'modules': {'eboot.bin': SOURCE_SHA256},
                          'sites': copy.deepcopy(cls.sites), 'unhandled': []})

    def reject(self, data, *, override='1'):
        before = {key: copy.deepcopy(value) for key, value in data.items() if key != 'image'}
        image_hash = hashlib.sha256(data['image']).hexdigest()
        with patch.dict(os.environ, {'BB_LEGACY_CPU_ALLOW_PARTIAL': override}):
            with self.assertRaises(ValueError):
                cpu_compat.patch_image(**data)
        self.assertEqual(before, {key: value for key, value in data.items() if key != 'image'})
        self.assertEqual(image_hash, hashlib.sha256(data['image']).hexdigest())
        type(self).rejections += 1

    def applied_body(self, span):
        report = self.reports[span[0]]
        start = report['trampoline_start']
        return bytes(self.translated[start:start + report['trampoline_size'] - 5])

    def registers(self, source, value):
        # Every high half starts nonzero, including destinations and aliases.
        registers = {reg: self.random.getrandbits(64) | (1 << 63) for reg in REGISTERS[:-1]}
        registers[source] = (registers[source] & ~0xffffffff) | value
        return registers

    def check(self, harness, span, registers, flags, *, context=False):
        expected, expected_flags, mask = expected_state(span, registers, harness.guest_rsp,
                                                         include_context=context)
        actual, actual_flags, before, after = harness.run(registers, flags)
        self.assertEqual(actual, expected, f'Full state mismatch at {span[0]:#x}')
        self.assertEqual(actual_flags & mask, expected_flags, f'Defined flags at {span[0]:#x}')
        self.assertEqual(after, before, 'Allocator span changed red zone')
        self.assertEqual(harness.stack_window_after, harness.stack_window_before,
                         'Allocator span changed observable stack memory')
        type(self).executions += 1
        type(self).context_executions += int(context)

    def values(self):
        values = {0, 1, 0xffffffff, 0x80000000, 0xffff, 0x10000, 0xffff0000,
                  0x55555555, 0xaaaaaaaa}
        for bit in range(32):
            power = 1 << bit
            values.update((power - 1, power, power + 1))
        values.update(self.random.getrandbits(32) for _ in range(64))
        return sorted(values)

    def parts(self, span):
        return span_bytes(self.function, span)

    def assert_transfer(self, image, span, report):
        start, (original, tail, _) = span[0], self.parts(span)
        end = start + len(original)
        target, size = report['trampoline_start'], report['trampoline_size']
        self.assertEqual((report['image_start'], report['image_end']), (start, end))
        self.assertEqual(image[start], 0xe9)
        self.assertEqual(start + 5 + struct.unpack_from('<i', image, start + 1)[0], target)
        self.assertEqual(image[start + 5:end], b'\x90' * (len(original) - 5))
        self.assertEqual(report['replacement_bytes'], image[start:end].hex())
        self.assertEqual(image[target + size - 5], 0xe9)
        self.assertEqual(target + size + struct.unpack_from('<i', image, target + size - 4)[0], end)
        self.assertEqual(hashlib.sha256(image[target:target + size]).hexdigest(), report['trampoline_sha256'])
        self.assertEqual(image[target + size - 5 - len(tail):target + size - 5], tail)

    def test_public_four_spans_transfer_report_and_unchanged_surroundings(self):
        self.assertEqual(len(self.sites), 4)
        expected = bytearray(self.base_image)
        for span in SPANS:
            report = self.reports[span[0]]
            self.assert_transfer(self.translated, span, report)
            start, end = report['image_start'], report['image_end']
            expected[start:end] = self.translated[start:end]
            body = self.applied_body(span)
            audit_baseline(body, capstone)
            self.assertTrue(any(s <= report['trampoline_start'] and
                                report['trampoline_start'] + report['trampoline_size'] <= s + n and flags & 1
                                for s, n, flags in self.segments))
        self.assertEqual(self.translated[:len(expected)], expected)
        self.assertEqual(hashlib.sha256(self.base_image).hexdigest(), self.base_hash)
        self.assertEqual(self.report['plan_version'], cpu_compat.PLAN_VERSION)
        self.assertEqual(self.report['patched_sites'], 4)
        self.assertEqual(self.report['span_patches'], 4)
        self.assertEqual(self.report['counts_by_instruction'], {'lzcnt': 3, 'tzcnt': 1})
        self.assertEqual(self.report['semantic_risk_sites'], 0)
        self.assertEqual(self.report['unhandled_count'], 0)
        self.assertFalse(self.report['complete_coverage'])
        self.assertTrue(self.report['spans_experimental'])
        self.assertTrue(self.report['span_execution_allowed'])
        self.assertEqual(self.report['span_entry_safety'], 'known_entries_checked_global_indirect_unproven')
        evidence = self.report['span_entry_evidence']
        self.assertEqual(len(evidence), 1)
        path = ROOT / evidence[0]['reference']
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), evidence[0]['sha256'])
        self.assertIs(evidence[0]['global_indirect_proof'], False)
        json.dumps(self.report)

    def test_full_state_flags_upper_halves_aliases_and_stack(self):
        flags_cases = (0x202, 0x202 | ARITHMETIC_FLAGS) + tuple(
            0x202 | bit for bit in (1, 4, 16, 64, 128, 2048))
        for span in SPANS:
            with NativeHarness(self.applied_body(span), keystone, capstone) as harness:
                for value in self.values():
                    for flags in flags_cases:
                        with self.subTest(span=hex(span[0]), source=hex(value), flags=hex(flags)):
                            self.check(harness, span, self.registers(span[3], value), flags)

    def test_arithmetic_context_and_zero_remainder_are_distinct(self):
        # Independent integer property over the complete documented size domain.
        for size in range(1, 65537):
            source = size - 1
            count = 32 - source.bit_length()
            expected_bucket = 0
            while (1 << expected_bucket) < size:
                expected_bucket += 1
            self.assertEqual(subtract32(32, count)[0], expected_bucket)
        for span in (SPANS[0], SPANS[2], SPANS[3]):
            body = self.applied_body(span) + self.parts(span)[2]
            with NativeHarness(body, keystone, capstone) as harness:
                values = range(65536) if span == SPANS[0] else self.values()
                for value in values:
                    registers = self.registers(span[3], value)
                    self.check(harness, span, registers, 0x202, context=True)
                    expected = expected_state(span, registers, harness.guest_rsp, include_context=True)[0]
                    bucket = expected[span[5]]
                    self.assertEqual(bucket, value.bit_length() if span[6] == 32 else
                                     ((value.bit_length() - 1) & 0xffffffff))
        self.assertEqual(subtract32(31, 32), (0xffffffff, 0x85))

    def test_tzcnt_cmp_boundary_flags_and_following_jb(self):
        span = SPANS[1]
        cases = ((1, 0, 0x85), (1 << 15, 15, 0x85), (1 << 16, 16, 0x44),
                 (1 << 31, 31, 0x04), (0, 32, 0x00))
        with NativeHarness(self.applied_body(span), keystone, capstone) as harness:
            for value, count, flags in cases:
                registers = self.registers('rax', value)
                self.check(harness, span, registers, 0x202 | ARITHMETIC_FLAGS)
                state, actual_flags, mask = expected_state(span, registers, harness.guest_rsp)
                self.assertEqual((state['rcx'], actual_flags, mask), (count, flags, 0x8d5))
                self.assertEqual(bool(actual_flags & 1), count < 16, 'Following JB condition')

    def test_gate_is_independent_of_zero_remaining_counts_and_disabled_mode(self):
        data = self.fixture()
        for override in ('0', '', 'true'):
            self.reject(data, override=override)
        with patch.dict(os.environ, {}, clear=True):
            # Fork default: the partial profile runs unless BB_LEGACY_CPU_ALLOW_PARTIAL refuses it.
            self.assertTrue(cpu_compat.patch_image(**data)[2]['span_execution_allowed'])
        data.update(active=False, plan={'invalid': object()})
        result, segments, report = cpu_compat.patch_image(**data)
        self.assertEqual(result, self.base_image)
        self.assertEqual(segments, data['segments'])
        self.assertEqual(report['span_patches'], 0)
        self.assertFalse(report['enabled'])
        self.assertFalse(report['span_execution_allowed'])

    def test_tail_whitelist_context_body_and_version_defects_reject(self):
        for span_index, span in enumerate(SPANS):
            # The persisted plan is sorted independently; locate the matching tuple.
            site_index = next(i for i, s in enumerate(self.sites) if s['address'] == span[0])
            original, tail, _ = self.parts(span)
            mutations = {
                'tail_omitted': lambda s: s.update(length=4),
                'tail_shortened': lambda s: s.update(length=s['length'] - 1),
                'tail_extended': lambda s: s.update(length=s['length'] + 1),
                'check': lambda s: s.update(check='0' * 16),
                'tail_metadata': lambda s: s['span'].update(tail_bytes='90'),
                'old_bytes_field': lambda s: s.update(bytes=original.hex()),
                'instruction_neighbor': lambda s: s.update(mnemonic=s['mnemonic'] + '; nop'),
                'mnemonic_swapped': lambda s: s.update(mnemonic='tzcnt' if s['mnemonic'] == 'lzcnt' else 'lzcnt'),
                'unlisted_address': lambda s: s.update(address=s['address'] + 1),
                'wrong_module': lambda s: s.update(module='libc.prx'),
                'count_length': lambda s: s['span'].update(count_length=5),
                'lengths': lambda s: s['span'].update(instruction_lengths=[5, len(original) - 5]),
                'bool_length': lambda s: s['span'].update(instruction_lengths=[True, len(original) - 4]),
                'context_start': lambda s: s['span'].update(function_start=FUNCTION_START + 1),
                'context_end': lambda s: s['span'].update(function_end=FUNCTION_END - 1),
                'context_hash': lambda s: s['span'].update(function_sha256='0' * 64),
                'missing_evidence': lambda s: s['span'].pop('entry_evidence'),
                'extra_metadata': lambda s: s['span'].update(safe=True),
                'return_address': lambda s: s.update(return_address=s['address'] + 4),
                'return_target': lambda s: s.update(return_target=s['address'] + 4),
                'rip_fixup': lambda s: s.update(rip_fixups=[{'offset': 1, 'next_offset': 5, 'target': 0}]),
                'body_tail_duplicate': lambda s: s.update(body=s['body'] + tail.hex()),
                'body_altered': lambda s: s.update(body='90'),
            }
            for label, mutate in mutations.items():
                with self.subTest(span=span_index, defect=label):
                    data = self.fixture()
                    mutate(data['plan']['sites'][site_index])
                    self.reject(data)
            for version, stripped in ((3, False), (4, False), (4, True), (cpu_compat.PLAN_VERSION, True)):
                data = self.fixture()
                data['plan']['version'] = version
                if stripped:
                    for site in data['plan']['sites']:
                        site.pop('kind')
                        site.pop('span')
                with self.subTest(version=version, stripped=stripped):
                    self.reject(data)
            for address in (span[0] + 4, span[0] + len(original) - 1, FUNCTION_START):
                data = self.fixture()
                data['image'] = bytearray(self.base_image)
                data['image'][address] ^= 1
                self.reject(data)
        data = self.fixture()
        data['main']['sha256'] = data['plan']['modules']['eboot.bin'] = 'b' * 64
        self.reject(data)
        data = self.fixture()
        data['image'] = self.translated
        data['segments'] = self.segments
        self.reject(data)

    def test_entries_unknown_candidates_and_resolved_relocations_reject(self):
        for site_index, site in enumerate(self.sites):
            start, end = site['address'], site['address'] + site['length']
            for kind in ('symbol', 'function', 'direct_branch', 'relocation', 'jump_table', 'landing_pad'):
                for address in (start + 1, start + 4, end - 1):
                    data = self.fixture()
                    data['plan']['sites'][site_index]['span']['entry_evidence']['known_entries'] = [
                        {'kind': kind, 'address': address}]
                    with self.subTest(kind=kind, address=hex(address)):
                        self.reject(data)
            evidence_mutations = (
                {'sha256': 'f' * 64}, {'reference': 'unreviewed.json'}, {'method': 'safe'},
                {'global_indirect_proof': True}, {'global_indirect_proof': 0},
                {'known_entries': [{'kind': 'unknown', 'address': start}]},
                {'known_entries': [{'kind': 'symbol', 'address': True}]},
                {'unresolved_candidates': [{'address': start + 4, 'decoded_instruction_boundary': False}]},
            )
            for mutation in evidence_mutations:
                data = self.fixture()
                data['plan']['sites'][site_index]['span']['entry_evidence'].update(mutation)
                self.reject(data)
            for kind in ('symbol', 'resolved_relocation', 'elf_symbol_addend', 'elf_relative'):
                data = self.fixture()
                if kind == 'symbol':
                    data['main']['symbols'] = [{'section': 1, 'value': start + 4}]
                elif kind == 'resolved_relocation':
                    data['relocations'] = [(0, 0, start, 4)]
                elif kind == 'elf_symbol_addend':
                    data['main']['symbols'] = [{'section': 1, 'value': start}]
                    data['main']['relocs'] = [(0, 1, 0, 4)]
                else:
                    data['main']['relocs'] = [(0, 8, 0, start + 4)]
                self.reject(data)
            data = self.fixture()
            data['plan']['sites'][site_index]['span']['entry_evidence']['known_entries'] = [
                {'kind': 'direct_branch', 'address': start}, {'kind': 'landing_pad', 'address': end}]
            with patch.dict(os.environ, {'BB_LEGACY_CPU_ALLOW_PARTIAL': '1'}):
                self.assertEqual(cpu_compat.patch_image(**data)[2]['span_patches'], 4)

    def test_entire_span_overlap_mapping_and_relocation_adjacency(self):
        for site in self.sites:
            start, end = site['address'], site['address'] + site['length']
            for relocation in (start - 7, start + 4, end - 1):
                data = self.fixture()
                data['relocations'] = [(relocation, 1, 0, 0)]
                self.reject(data)
            data = self.fixture()
            data['relocations'] = [(start - 8, 1, 0, 0), (end, 1, 0, 0)]
            with patch.dict(os.environ, {'BB_LEGACY_CPU_ALLOW_PARTIAL': '1'}):
                self.assertEqual(cpu_compat.patch_image(**data)[2]['span_patches'], 4)
            for address in (start, start + 4):
                data = self.fixture()
                data['plan']['sites'].append({'module': 'eboot.bin', 'address': address, 'length': 5,
                    'check': cpu_compat.site_check(self.base_image[address:address + 5]), 'body': '90', 'mnemonic': 'blsr'})
                self.reject(data)
            data = self.fixture()
            split = start + 5
            data['segments'] = [(0, split, 5), (split, len(self.base_image) - split, 5)]
            self.reject(data)

    def test_purposeful_semantic_and_transfer_mutants_are_detected(self):
        assembler = keystone.Ks(keystone.KS_ARCH_X86, keystone.KS_MODE_64)
        asm = lambda code: bytes(assembler.asm(code)[0])
        lz, tz, alias = SPANS[0], SPANS[1], SPANS[2]
        lz_count = self.builder.body(lz[1], lz[2])
        tz_count = self.builder.body(tz[1], tz[2])
        alias_count = self.builder.body(alias[1], alias[2])
        mutants = (
            ('BSR semantics', lz, asm('bsr eax, eax; mov ecx, 32'), 512),
            ('MOV before count alias', alias, self.parts(alias)[1] + alias_count, 512),
            ('MOV omitted', lz, lz_count, 512),
            ('MOV changes flags', lz, self.applied_body(lz) + asm('stc'), 512),
            ('index correct GPR clobber', alias, self.applied_body(alias) + asm('mov rbx, 0'), 512),
            ('CMP omitted', tz, tz_count, 1),
            ('CMP wrong immediate', tz, tz_count + asm('cmp ecx, 15'), 1 << 15),
            ('upper bits preserved', lz, self.applied_body(lz) + asm('movabs rax, 0xffff000000000016'), 512),
            ('red zone write', lz, self.applied_body(lz) + asm('mov byte ptr [rsp-8], 0'), 512),
        )
        for label, span, body, value in mutants:
            with self.subTest(defect=label), NativeHarness(body, keystone, capstone) as harness:
                with self.assertRaises(AssertionError):
                    self.check(harness, span, self.registers(span[3], value), 0x202)
        span = SPANS[0]
        report = self.reports[span[0]]
        malformed = bytearray(self.translated)
        location = report['trampoline_start'] + report['trampoline_size'] - 4
        struct.pack_into('<i', malformed, location, span[0] + 4 - (location + 4))
        with self.assertRaises(AssertionError):
            self.assert_transfer(malformed, span, report)
        for original in ('f30fbdc0', 'f30fbcc8'):
            with self.assertRaises(ValueError):
                audit_baseline(bytes.fromhex(original), capstone)

    @classmethod
    def tearDownClass(cls):
        print(f'Allocator baseline executions={cls.executions}; context executions={cls.context_executions}; '
              f'rejected mutations={cls.rejections}; seed=0xd0153770; root={ROOT}', flush=True)


if __name__ == '__main__':
    unittest.main()
