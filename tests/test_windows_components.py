"""Integrity controls for the two same-run Windows build transports."""
from pathlib import Path
import copy
import gzip
import hashlib
import importlib.util
import json
import os
import struct
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import buildkit
import prepare_native_tests
import native_activation
import native_source_contract
import com_worker
import com_source_contract
import wasm_artifacts
import windows_arch
import pdf_search_text
import pdf_font_resolution
import menu_clipboard
import shape_creation_history
import nested_line_navigation
import stored_lineseg_origin
import picture_line_segment_owner
import virtual_picture_layout_admission
import hwpx_persistence_verification

FONT_SOURCE_PINS = {
    'apps/studio-host/src/main.ts': 'bb08b3373291803ae5ced45b0cba839fccece11256b1ca7e7cf305b6f5cfa89f',
    'apps/studio-host/src/ui/toolbar.ts': '203dc4cff5d4ce851466f4efb5107d2b138e0b95d4478ee1a2a93a5049bf62fe',
    'third_party/rhwp/rhwp-studio/src/engine/input-handler-keyboard.ts': '1076739c3742d73329e91cb3cdf2f638f03fcb21e7df0aa6a326963bf231b87c',
    'third_party/rhwp/rhwp-studio/src/engine/input-handler.ts': '9bbba9420b2a8d4c3630a1797976bf9e65b9b1b4a67c608f305e1f5a873c31ce',
}

HELPER = ROOT/'scripts/windows_components.py'
components = None
if HELPER.exists():
    spec = importlib.util.spec_from_file_location('windows_components', HELPER)
    components = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(components)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')


def pe(machine=0x8664):
    data = bytearray(256)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 60, 128)
    data[128:132] = b'PE\0\0'
    struct.pack_into('<H', data, 132, machine)
    return bytes(data)


class WindowsComponentsTests(unittest.TestCase):
    def test_pdf_font_resolution_actual_renderer_and_readonly_dependencies_are_mandatory(self):
        expected = (
            'third_party/rhwp/src/renderer/pdf.rs',
            'third_party/rhwp/src/renderer/pdf/opengeul_pdf_guard.rs',
            'third_party/rhwp/src/renderer/pdf/opengeul_font_policy.rs',
        )
        self.assertEqual(pdf_font_resolution.SOURCE_FILES, expected)
        self.assertEqual({name for name in expected
                          if pdf_font_resolution.INPUT_SOURCE_SHA256[name]
                          == pdf_font_resolution.OUTPUT_SOURCE_SHA256[name]}, set(expected[1:]))
        self.assertEqual(pdf_font_resolution.INPUT_SOURCE_SHA256[expected[0]],
                         pdf_search_text.PATCHED_SHA256[expected[0]])
        source = self.source(); c = self.helper(); config = c.configured()
        self.assertEqual(config['helpers'][pdf_font_resolution.HELPER],
                         digest(ROOT/pdf_font_resolution.HELPER))
        _, contract = c.source_contract(source, config)
        for name in expected:
            with self.subTest(source=name):
                self.assertIn(name, c.SOURCE_FILES)
                self.assertEqual(contract['preparedFiles'][name], digest(source/name))
                self.assertEqual(contract['coreSourceFiles'][name], digest(source/name))
        self.assertEqual(contract['pdfSearchText']['afterSha256'][expected[0]],
                         contract['pdfFontResolution']['beforeSha256'][expected[0]])
        self.assertNotEqual(contract['pdfSearchText']['afterSha256'][expected[0]],
                            contract['preparedFiles'][expected[0]])

    def test_pdf_font_resolution_native_registration_is_required_before_capture(self):
        source = self.source(); c = self.helper(); payload = self.payload('editor')
        manifest = source/'third_party/rhwp/Cargo.toml'; original = manifest.read_text()
        entry = ('\n[[test]]\nname = "opengeul_pdf_font_resolution"\n'
                 'path = "tests/opengeul_pdf_font_resolution.rs"\n'
                 'required-features = ["native-skia"]\n')
        self.assertEqual(original.count(entry), 1)
        for i, changed in enumerate((original.replace(entry, ''),
                                     original.replace(entry, entry.replace('required-features = ["native-skia"]',
                                                                          'required-features = []')))):
            manifest.write_text(changed)
            out = self.root/('invalid-font-native-registration-'+str(i))
            with self.subTest(case=i), self.assertRaisesRegex(ValueError, 'Native integration test'):
                c.capture('editor', payload, source, out, env=self.env)
            self.assertFalse(out.exists())
        manifest.write_text(original)

    def test_pdf_font_resolution_capture_rejects_forged_proof_and_each_source_dependency_drift(self):
        source = self.source(); c = self.helper(); payload = self.payload('editor')
        ledger_path = source/'.opengeul-overlay.json'
        original = json.loads(ledger_path.read_bytes())
        raw = {name:(source/name).read_bytes() for name in pdf_font_resolution.SOURCE_FILES}
        cases = [(kind, None) for kind in ('helper', 'extra-proof', 'extra-before-source', 'extra-after-source')]
        cases += [(kind, name) for name in raw
                  for kind in ('before', 'after', 'missing-source', 'unreviewed-source', 'coherent-legacy')]
        for i, (change, name) in enumerate(cases):
            for path, data in raw.items(): (source/path).write_bytes(data)
            ledger = copy.deepcopy(original); proof = ledger['pdfFontResolution']
            if change == 'helper': proof['helperSha256'] = '0'*64
            elif change == 'extra-proof': proof['optional'] = True
            elif change in ('extra-before-source', 'extra-after-source'):
                proof['beforeSha256' if change == 'extra-before-source' else 'afterSha256']['third_party/rhwp/src/unreviewed.rs'] = '0'*64
            elif change in ('before', 'after'): proof[change+'Sha256'][name] = '0'*64
            elif change == 'missing-source': (source/name).unlink()
            else:
                (source/name).write_bytes(b'owned former PDF font resolution source or readonly dependency\n')
                if change == 'coherent-legacy': proof['afterSha256'][name] = digest(source/name)
            write_json(ledger_path, ledger)
            out = self.root/('invalid-pdf-font-resolution-'+str(i))
            with self.subTest(change=change, source=name), self.assertRaises((ValueError, FileNotFoundError)):
                c.capture('editor', payload, source, out, env=self.env)
            self.assertFalse(out.exists())


    def test_pdf_font_resolution_capture_rejects_each_dependency_change_between_hash_observations(self):
        source = self.source(); c = self.helper(); actual_tree = c.tree
        payload = self.payload('editor')
        raw = {name:(source/name).read_bytes() for name in pdf_font_resolution.SOURCE_FILES}
        for i, name in enumerate(raw):
            for path, data in raw.items(): (source/path).write_bytes(data)
            def changed_core_inventory(folder, cap):
                if folder == source/'third_party/rhwp/src':
                    target = source/name
                    target.write_bytes(target.read_bytes()+b'// changed pdf_font_resolution dependency between observations\n')
                return actual_tree(folder, cap)
            out = self.root/('mismatched-pdf_font_resolution-core-observation-'+str(i))
            expected = 'PDF font resolution complete core source mismatch'
            with self.subTest(source=name), patch.object(c, 'tree', side_effect=changed_core_inventory), \
                    self.assertRaisesRegex(ValueError, expected):
                c.capture('editor', payload, source, out, env=self.env)
            self.assertFalse(out.exists())


    def test_matching_component_pair_cannot_omit_pdf_font_resolution_proof_or_any_dependency(self):
        folders = self.pair()
        original = {role:json.loads((folder/'provenance.json').read_bytes())
                    for role, folder in folders.items()}
        cases = [('proof', None)]+[(kind, name) for name in pdf_font_resolution.SOURCE_FILES
                                  for kind in ('prepared-source', 'core-source')]
        for change, name in cases:
            for role, folder in folders.items():
                value = copy.deepcopy(original[role]); source = value['source']
                if change == 'proof': source.pop('pdfFontResolution')
                else: source['preparedFiles' if change == 'prepared-source' else 'coreSourceFiles'].pop(name)
                write_json(folder/'provenance.json', value)
            with self.subTest(change=change, source=name): self.assert_rejected_without_outputs(folders)


    def test_matching_component_pair_rejects_pdf_font_resolution_coherent_legacy_and_fixed_proof_drift(self):
        folders = self.pair()
        original = {role:json.loads((folder/'provenance.json').read_bytes())
                    for role, folder in folders.items()}
        cases = [(kind, None) for kind in ('helper', 'extra-proof', 'extra-before-source', 'extra-after-source')]
        cases += [(kind, name) for name in pdf_font_resolution.SOURCE_FILES
                  for kind in ('before', 'after', 'observed-hash', 'coherent-legacy')]
        # Only the renderer changes; two compiled policy dependencies stay exact.
        cases += [('legacy-original-pin', name) for name in (pdf_font_resolution.PDF,)]
        cases += [('canonical-source1-stage', pdf_font_resolution.PDF)]
        for change, name in cases:
            for role, folder in folders.items():
                value = copy.deepcopy(original[role]); source = value['source']
                proof = source['pdfFontResolution']
                if change == 'helper': proof['helperSha256'] = '0'*64
                elif change == 'extra-proof': proof['optional'] = True
                elif change in ('extra-before-source', 'extra-after-source'):
                    proof['beforeSha256' if change == 'extra-before-source' else 'afterSha256']['third_party/rhwp/src/unreviewed.rs'] = '0'*64
                elif change in ('before', 'after'): proof[change+'Sha256'][name] = '0'*64
                elif change == 'observed-hash':
                    source['preparedFiles'][name] = source['coreSourceFiles'][name] = '0'*64
                else:
                    legacy = ('84bb9980b3a42e42998872bc9112a1714ef82984a5981b59c51d148f90b9e804'
                              if change == 'canonical-source1-stage' else
                              pdf_font_resolution.INPUT_SOURCE_SHA256[name] if change == 'legacy-original-pin'
                              else hashlib.sha256(b'owned former PDF font resolution source or readonly dependency\n').hexdigest())
                    proof['afterSha256'][name] = legacy
                    source['preparedFiles'][name] = source['coreSourceFiles'][name] = legacy
                write_json(folder/'provenance.json', value)
            with self.subTest(change=change, source=name): self.assert_rejected_without_outputs(folders)


    def test_rehashed_public_ledger_cannot_omit_or_replace_pdf_font_resolution_proof(self):
        folders = self.pair(); parity_path = folders['editor']/'source-parity.json'
        original_parity = json.loads(parity_path.read_bytes())
        original = {role:json.loads((folder/'provenance.json').read_bytes())
                    for role, folder in folders.items()}
        for change in ('missing', 'mismatch'):
            parity = copy.deepcopy(original_parity)
            if change == 'missing': parity.pop('pdfFontResolution')
            else: parity['pdfFontResolution']['helperSha256'] = '0'*64
            write_json(parity_path, parity)
            for role, folder in folders.items():
                value = copy.deepcopy(original[role]); value['source']['ledgerSha256'] = digest(parity_path)
                if role == 'editor':
                    value['files']['source-parity.json'] = {'size':parity_path.stat().st_size,
                                                          'sha256':digest(parity_path)}
                write_json(folder/'provenance.json', value)
            with self.subTest(change=change):
                self.assert_rejected_without_outputs(folders, 'PDF font resolution source/ledger proof mismatch')


    def test_pdf_font_resolution_missing_proof_cannot_publish_component(self):
        source = self.source(); c = self.helper()
        ledger_path = source/'.opengeul-overlay.json'
        ledger = json.loads(ledger_path.read_bytes())
        ledger.pop('pdfFontResolution', None)
        write_json(ledger_path, ledger)
        out = self.root/'missing-pdf-font-resolution-proof'
        with self.assertRaisesRegex(ValueError, 'PDF font resolution source/ledger proof mismatch'):
            c.capture('editor', self.payload('editor'), source, out, env=self.env)
        self.assertFalse(out.exists())

    def test_hwpx_persistence_compiled_and_dependency_sources_are_mandatory(self):
        expected = (
            'third_party/rhwp/src/cli/commands/edit/runtime.rs',
            'third_party/rhwp/src/serializer/hwpx/roundtrip.rs',
            'third_party/rhwp/src/serializer/hwpx/section.rs',
            'third_party/rhwp/src/model/identity/walk.rs',
            'third_party/rhwp/src/model/identity.rs',
            'third_party/rhwp/src/serializer/hwpx/field.rs',
        )
        self.assertEqual(hwpx_persistence_verification.SOURCE_FILES, expected)
        readonly = {
            'third_party/rhwp/src/serializer/hwpx/section.rs',
            'third_party/rhwp/src/model/identity/walk.rs',
            'third_party/rhwp/src/model/identity.rs',
        }
        self.assertEqual({name for name in expected
                          if hwpx_persistence_verification.INPUT_SOURCE_SHA256[name]
                          == hwpx_persistence_verification.OUTPUT_SOURCE_SHA256[name]}, readonly)
        for name in expected:
            with self.subTest(source=name):
                self.assertIn(name, self.helper().SOURCE_FILES,
                              'HWPX persistence code and readonly dependency must cross the explicit transport boundary')
        source = self.source(); c = self.helper(); config = c.configured()
        self.assertEqual(config['helpers'][hwpx_persistence_verification.HELPER],
                         digest(ROOT/hwpx_persistence_verification.HELPER))
        _, contract = c.source_contract(source, config)
        for name in expected:
            with self.subTest(source=name):
                self.assertEqual(contract['preparedFiles'][name], digest(source/name))
                self.assertEqual(contract['coreSourceFiles'][name], digest(source/name))

    def test_hwpx_persistence_missing_proof_cannot_publish_component(self):
        source = self.source(); c = self.helper()
        ledger_path = source/'.opengeul-overlay.json'
        ledger = json.loads(ledger_path.read_bytes())
        ledger.pop('hwpxPersistenceVerification', None)
        write_json(ledger_path, ledger)
        out = self.root/'missing-hwpx-persistence-proof'
        with self.assertRaisesRegex(ValueError, 'HWPX persistence verification source/ledger proof mismatch'):
            c.capture('editor', self.payload('editor'), source, out, env=self.env)
        self.assertFalse(out.exists())

    def test_hwpx_persistence_capture_rejects_forged_proof_and_each_source_dependency_drift(self):
        source = self.source(); c = self.helper(); payload = self.payload('editor')
        ledger_path = source/'.opengeul-overlay.json'
        original = json.loads(ledger_path.read_bytes())
        raw = {name:(source/name).read_bytes() for name in hwpx_persistence_verification.SOURCE_FILES}
        cases = [(kind, None) for kind in ('helper', 'extra-proof', 'extra-before-source', 'extra-after-source')]
        cases += [(kind, name) for name in raw
                  for kind in ('before', 'after', 'missing-source', 'unreviewed-source', 'coherent-legacy')]
        for i, (change, name) in enumerate(cases):
            for path, data in raw.items(): (source/path).write_bytes(data)
            ledger = copy.deepcopy(original); proof = ledger['hwpxPersistenceVerification']
            if change == 'helper': proof['helperSha256'] = '0'*64
            elif change == 'extra-proof': proof['optional'] = True
            elif change in ('extra-before-source', 'extra-after-source'):
                proof['beforeSha256' if change == 'extra-before-source' else 'afterSha256']['third_party/rhwp/src/unreviewed.rs'] = '0'*64
            elif change in ('before', 'after'): proof[change+'Sha256'][name] = '0'*64
            elif change == 'missing-source': (source/name).unlink()
            else:
                (source/name).write_bytes(b'owned former HWPX persistence source or readonly dependency\n')
                if change == 'coherent-legacy': proof['afterSha256'][name] = digest(source/name)
            write_json(ledger_path, ledger)
            out = self.root/('invalid-hwpx-persistence-'+str(i))
            with self.subTest(change=change, source=name), self.assertRaises((ValueError, FileNotFoundError)):
                c.capture('editor', payload, source, out, env=self.env)
            self.assertFalse(out.exists())

    def test_hwpx_persistence_capture_rejects_each_dependency_change_between_hash_observations(self):
        source = self.source(); c = self.helper(); actual_tree = c.tree
        payload = self.payload('editor')
        raw = {name:(source/name).read_bytes() for name in hwpx_persistence_verification.SOURCE_FILES}
        for i, name in enumerate(raw):
            for path, data in raw.items(): (source/path).write_bytes(data)
            def changed_core_inventory(folder, cap):
                if folder == source/'third_party/rhwp/src':
                    target = source/name
                    target.write_bytes(target.read_bytes()+b'// changed persistence dependency between observations\n')
                return actual_tree(folder, cap)
            out = self.root/('mismatched-persistence-core-observation-'+str(i))
            # section.rs is also protected by the unchanged earlier Origin3 gate.
            expected = ('(?:Stored line segment origin|HWPX persistence verification)'
                        ' complete core source mismatch')
            with self.subTest(source=name), patch.object(c, 'tree', side_effect=changed_core_inventory), \
                    self.assertRaisesRegex(ValueError, expected):
                c.capture('editor', payload, source, out, env=self.env)
            self.assertFalse(out.exists())

    def test_matching_component_pair_cannot_omit_persistence_proof_or_any_dependency(self):
        folders = self.pair()
        original = {role:json.loads((folder/'provenance.json').read_bytes())
                    for role, folder in folders.items()}
        cases = [('proof', None)]+[(kind, name) for name in hwpx_persistence_verification.SOURCE_FILES
                                  for kind in ('prepared-source', 'core-source')]
        for change, name in cases:
            for role, folder in folders.items():
                value = copy.deepcopy(original[role]); source = value['source']
                if change == 'proof': source.pop('hwpxPersistenceVerification')
                else: source['preparedFiles' if change == 'prepared-source' else 'coreSourceFiles'].pop(name)
                write_json(folder/'provenance.json', value)
            with self.subTest(change=change, source=name): self.assert_rejected_without_outputs(folders)

    def test_matching_component_pair_rejects_persistence_coherent_legacy_and_fixed_proof_drift(self):
        folders = self.pair()
        original = {role:json.loads((folder/'provenance.json').read_bytes())
                    for role, folder in folders.items()}
        cases = [(kind, None) for kind in ('helper', 'extra-proof', 'extra-before-source', 'extra-after-source')]
        cases += [(kind, name) for name in hwpx_persistence_verification.SOURCE_FILES
                  for kind in ('before', 'after', 'observed-hash', 'coherent-legacy')]
        # Only the three changed files have a distinct stale original pin.
        cases += [('legacy-original-pin', name) for name in hwpx_persistence_verification.REPLACEMENTS]
        for change, name in cases:
            for role, folder in folders.items():
                value = copy.deepcopy(original[role]); source = value['source']
                proof = source['hwpxPersistenceVerification']
                if change == 'helper': proof['helperSha256'] = '0'*64
                elif change == 'extra-proof': proof['optional'] = True
                elif change in ('extra-before-source', 'extra-after-source'):
                    proof['beforeSha256' if change == 'extra-before-source' else 'afterSha256']['third_party/rhwp/src/unreviewed.rs'] = '0'*64
                elif change in ('before', 'after'): proof[change+'Sha256'][name] = '0'*64
                elif change == 'observed-hash':
                    source['preparedFiles'][name] = source['coreSourceFiles'][name] = '0'*64
                else:
                    legacy = (hwpx_persistence_verification.INPUT_SOURCE_SHA256[name] if change == 'legacy-original-pin'
                              else hashlib.sha256(b'owned former persistence source or readonly dependency\n').hexdigest())
                    proof['afterSha256'][name] = legacy
                    source['preparedFiles'][name] = source['coreSourceFiles'][name] = legacy
                write_json(folder/'provenance.json', value)
            with self.subTest(change=change, source=name): self.assert_rejected_without_outputs(folders)

    def test_rehashed_public_ledger_cannot_omit_or_replace_persistence_proof(self):
        folders = self.pair(); parity_path = folders['editor']/'source-parity.json'
        original_parity = json.loads(parity_path.read_bytes())
        original = {role:json.loads((folder/'provenance.json').read_bytes())
                    for role, folder in folders.items()}
        for change in ('missing', 'mismatch'):
            parity = copy.deepcopy(original_parity)
            if change == 'missing': parity.pop('hwpxPersistenceVerification')
            else: parity['hwpxPersistenceVerification']['helperSha256'] = '0'*64
            write_json(parity_path, parity)
            for role, folder in folders.items():
                value = copy.deepcopy(original[role]); value['source']['ledgerSha256'] = digest(parity_path)
                if role == 'editor':
                    value['files']['source-parity.json'] = {'size':parity_path.stat().st_size,
                                                          'sha256':digest(parity_path)}
                write_json(folder/'provenance.json', value)
            with self.subTest(change=change):
                self.assert_rejected_without_outputs(folders, 'HWPX persistence verification source/ledger proof mismatch')

    def test_virtual_picture_layout_admission_compiled_source_is_mandatory(self):
        source = self.source(); c = self.helper()
        name = 'third_party/rhwp/src/document_core/commands/text_editing.rs'
        self.assertEqual(virtual_picture_layout_admission.SOURCE_FILES, (name,))
        self.assertIn(name, c.SOURCE_FILES,
                      'Actual virtual picture layout admission source must cross the explicit transport boundary')
        config = c.configured()
        self.assertEqual(config['helpers'][virtual_picture_layout_admission.HELPER],
                         digest(ROOT/virtual_picture_layout_admission.HELPER))
        _, contract = c.source_contract(source, config)
        self.assertEqual(contract['preparedFiles'][name], digest(source/name))
        self.assertEqual(contract['coreSourceFiles'][name], digest(source/name))

    def test_virtual_picture_layout_admission_missing_proof_cannot_publish_component(self):
        source = self.source(); c = self.helper()
        ledger_path = source/'.opengeul-overlay.json'
        ledger = json.loads(ledger_path.read_bytes())
        ledger.pop('virtualPictureLayoutAdmission', None)
        write_json(ledger_path, ledger)
        out = self.root/'missing-virtual-picture-layout-proof'
        with self.assertRaisesRegex(ValueError, 'Virtual picture layout admission source/ledger proof mismatch'):
            c.capture('editor', self.payload('editor'), source, out, env=self.env)
        self.assertFalse(out.exists())

    def test_virtual_picture_layout_capture_rejects_unreviewed_source_and_forged_proof_without_output(self):
        source = self.source(); c = self.helper(); payload = self.payload('editor')
        ledger_path = source/'.opengeul-overlay.json'
        original = json.loads(ledger_path.read_bytes())
        name, = virtual_picture_layout_admission.SOURCE_FILES
        original_bytes = (source/name).read_bytes()
        cases = ('helper', 'before', 'after', 'extra-proof', 'missing-source',
                 'unreviewed-source', 'coherent-legacy', 'extra-after-source')
        for i, change in enumerate(cases):
            (source/name).write_bytes(original_bytes)
            ledger = copy.deepcopy(original); proof = ledger['virtualPictureLayoutAdmission']
            if change == 'helper': proof['helperSha256'] = '0'*64
            elif change in ('before', 'after'): proof[change+'Sha256'][name] = '0'*64
            elif change == 'extra-proof': proof['optional'] = True
            elif change == 'extra-after-source': proof['afterSha256']['third_party/rhwp/src/unreviewed.rs'] = '0'*64
            elif change == 'missing-source': (source/name).unlink()
            else:
                (source/name).write_bytes(b'owned former body-only virtual picture layout source\n')
                if change == 'coherent-legacy': proof['afterSha256'][name] = digest(source/name)
            write_json(ledger_path, ledger)
            out = self.root/('invalid-virtual-picture-layout-'+str(i))
            with self.subTest(change=change), self.assertRaises((ValueError, FileNotFoundError)):
                c.capture('editor', payload, source, out, env=self.env)
            self.assertFalse(out.exists())

    def test_virtual_picture_layout_capture_rejects_actual_core_change_between_hash_observations(self):
        source = self.source(); c = self.helper(); actual_tree = c.tree
        name, = virtual_picture_layout_admission.SOURCE_FILES
        def changed_core_inventory(folder, cap):
            if folder == source/'third_party/rhwp/src':
                target = source/name
                target.write_bytes(target.read_bytes()+b'// changed virtual layout admission between source observations\n')
            return actual_tree(folder, cap)
        out = self.root/'mismatched-virtual-layout-core-observation'
        with patch.object(c, 'tree', side_effect=changed_core_inventory), \
                self.assertRaisesRegex(ValueError, 'Virtual picture layout admission complete core source mismatch'):
            c.capture('editor', self.payload('editor'), source, out, env=self.env)
        self.assertFalse(out.exists())

    def test_matching_component_pair_cannot_omit_virtual_layout_proof_or_compiled_source(self):
        folders = self.pair()
        original = {role:json.loads((folder/'provenance.json').read_bytes())
                    for role, folder in folders.items()}
        name, = virtual_picture_layout_admission.SOURCE_FILES
        for change in ('proof', 'prepared-source', 'core-source'):
            for role, folder in folders.items():
                value = copy.deepcopy(original[role]); source = value['source']
                if change == 'proof': source.pop('virtualPictureLayoutAdmission')
                else: source['preparedFiles' if change == 'prepared-source' else 'coreSourceFiles'].pop(name)
                write_json(folder/'provenance.json', value)
            with self.subTest(change=change): self.assert_rejected_without_outputs(folders)

    def test_matching_component_pair_rejects_virtual_layout_coherent_legacy_and_fixed_proof_observation_drift(self):
        folders = self.pair()
        original = {role:json.loads((folder/'provenance.json').read_bytes())
                    for role, folder in folders.items()}
        name, = virtual_picture_layout_admission.SOURCE_FILES
        cases = ('helper', 'before', 'after', 'observed-hash', 'legacy-original-pin',
                 'coherent-legacy', 'extra-proof', 'extra-before-source', 'extra-after-source')
        for change in cases:
            for role, folder in folders.items():
                value = copy.deepcopy(original[role]); source = value['source']
                proof = source['virtualPictureLayoutAdmission']
                if change == 'helper': proof['helperSha256'] = '0'*64
                elif change in ('before', 'after'): proof[change+'Sha256'][name] = '0'*64
                elif change == 'extra-proof': proof['optional'] = True
                elif change in ('extra-before-source', 'extra-after-source'):
                    proof['beforeSha256' if change == 'extra-before-source' else 'afterSha256']['third_party/rhwp/src/unreviewed.rs'] = '0'*64
                elif change == 'observed-hash':
                    # Leave the exact declared proof unchanged; only actual
                    # component observations are coherently altered in both inputs.
                    source['preparedFiles'][name] = source['coreSourceFiles'][name] = '0'*64
                else:
                    legacy = (virtual_picture_layout_admission.INPUT_SOURCE_SHA256[name] if change == 'legacy-original-pin'
                              else hashlib.sha256(b'owned former body-only virtual picture layout source\n').hexdigest())
                    proof['afterSha256'][name] = legacy
                    source['preparedFiles'][name] = source['coreSourceFiles'][name] = legacy
                write_json(folder/'provenance.json', value)
            with self.subTest(change=change): self.assert_rejected_without_outputs(folders)

    def test_rehashed_public_ledger_cannot_omit_or_replace_virtual_picture_layout_proof(self):
        folders = self.pair(); parity_path = folders['editor']/'source-parity.json'
        original_parity = json.loads(parity_path.read_bytes())
        original = {role:json.loads((folder/'provenance.json').read_bytes())
                    for role, folder in folders.items()}
        for change in ('missing', 'mismatch'):
            parity = copy.deepcopy(original_parity)
            if change == 'missing': parity.pop('virtualPictureLayoutAdmission')
            else: parity['virtualPictureLayoutAdmission']['helperSha256'] = '0'*64
            write_json(parity_path, parity)
            for role, folder in folders.items():
                value = copy.deepcopy(original[role]); value['source']['ledgerSha256'] = digest(parity_path)
                if role == 'editor':
                    value['files']['source-parity.json'] = {'size':parity_path.stat().st_size,
                                                          'sha256':digest(parity_path)}
                write_json(folder/'provenance.json', value)
            with self.subTest(change=change):
                self.assert_rejected_without_outputs(folders, 'Virtual picture layout admission source/ledger proof mismatch')

    def test_picture_line_segment_owner_compiled_source_is_mandatory(self):
        source = self.source(); c = self.helper()
        name = 'third_party/rhwp/src/document_core/commands/object_ops/picture.rs'
        self.assertEqual(picture_line_segment_owner.SOURCE_FILES, (name,))
        self.assertIn(name, c.SOURCE_FILES,
                      'Actual picture vector replacement source must cross the explicit transport boundary')
        config = c.configured()
        self.assertEqual(config['helpers'][picture_line_segment_owner.HELPER],
                         digest(ROOT/picture_line_segment_owner.HELPER))
        _, contract = c.source_contract(source, config)
        self.assertEqual(contract['preparedFiles'][name], digest(source/name))
        self.assertEqual(contract['coreSourceFiles'][name], digest(source/name))

    def test_picture_line_segment_owner_missing_proof_cannot_publish_component(self):
        source = self.source(); c = self.helper()
        ledger_path = source/'.opengeul-overlay.json'
        ledger = json.loads(ledger_path.read_bytes())
        ledger.pop('pictureLineSegmentOwner', None)
        write_json(ledger_path, ledger)
        out = self.root/'missing-picture-line-owner-proof'
        with self.assertRaisesRegex(ValueError, 'Picture line segment owner source/ledger proof mismatch'):
            c.capture('editor', self.payload('editor'), source, out, env=self.env)
        self.assertFalse(out.exists())

    def test_picture_owner_capture_rejects_unreviewed_source_and_forged_proof_without_output(self):
        source = self.source(); c = self.helper(); payload = self.payload('editor')
        ledger_path = source/'.opengeul-overlay.json'
        original = json.loads(ledger_path.read_bytes())
        name, = picture_line_segment_owner.SOURCE_FILES
        original_bytes = (source/name).read_bytes()
        cases = ('helper', 'before', 'after', 'extra-proof', 'missing-source',
                 'unreviewed-source', 'coherent-legacy', 'extra-after-source')
        for i, change in enumerate(cases):
            (source/name).write_bytes(original_bytes)
            ledger = copy.deepcopy(original); proof = ledger['pictureLineSegmentOwner']
            if change == 'helper': proof['helperSha256'] = '0'*64
            elif change in ('before', 'after'): proof[change+'Sha256'][name] = '0'*64
            elif change == 'extra-proof': proof['optional'] = True
            elif change == 'extra-after-source': proof['afterSha256']['third_party/rhwp/src/unreviewed.rs'] = '0'*64
            elif change == 'missing-source': (source/name).unlink()
            else:
                (source/name).write_bytes(b'owned former stale picture vector source\n')
                if change == 'coherent-legacy': proof['afterSha256'][name] = digest(source/name)
            write_json(ledger_path, ledger)
            out = self.root/('invalid-picture-owner-'+str(i))
            with self.subTest(change=change), self.assertRaises((ValueError, FileNotFoundError)):
                c.capture('editor', payload, source, out, env=self.env)
            self.assertFalse(out.exists())

    def test_picture_owner_capture_rejects_actual_core_change_between_hash_observations(self):
        source = self.source(); c = self.helper(); actual_tree = c.tree
        name, = picture_line_segment_owner.SOURCE_FILES
        def changed_core_inventory(folder, cap):
            if folder == source/'third_party/rhwp/src':
                target = source/name
                target.write_bytes(target.read_bytes()+b'// changed picture ownership between source observations\n')
            return actual_tree(folder, cap)
        out = self.root/'mismatched-picture-core-observation'
        with patch.object(c, 'tree', side_effect=changed_core_inventory), \
                self.assertRaisesRegex(ValueError, 'Picture line segment owner complete core source mismatch'):
            c.capture('editor', self.payload('editor'), source, out, env=self.env)
        self.assertFalse(out.exists())

    def test_matching_component_pair_cannot_omit_picture_proof_or_compiled_source(self):
        folders = self.pair()
        original = {role:json.loads((folder/'provenance.json').read_bytes())
                    for role, folder in folders.items()}
        name, = picture_line_segment_owner.SOURCE_FILES
        for change in ('proof', 'prepared-source', 'core-source'):
            for role, folder in folders.items():
                value = copy.deepcopy(original[role]); source = value['source']
                if change == 'proof': source.pop('pictureLineSegmentOwner')
                else: source['preparedFiles' if change == 'prepared-source' else 'coreSourceFiles'].pop(name)
                write_json(folder/'provenance.json', value)
            with self.subTest(change=change): self.assert_rejected_without_outputs(folders)

    def test_matching_component_pair_rejects_picture_coherent_legacy_and_fixed_proof_observation_drift(self):
        folders = self.pair()
        original = {role:json.loads((folder/'provenance.json').read_bytes())
                    for role, folder in folders.items()}
        name, = picture_line_segment_owner.SOURCE_FILES
        cases = ('helper', 'before', 'after', 'observed-hash', 'legacy-original-pin',
                 'coherent-legacy', 'extra-proof', 'extra-before-source', 'extra-after-source')
        for change in cases:
            for role, folder in folders.items():
                value = copy.deepcopy(original[role]); source = value['source']
                proof = source['pictureLineSegmentOwner']
                if change == 'helper': proof['helperSha256'] = '0'*64
                elif change in ('before', 'after'): proof[change+'Sha256'][name] = '0'*64
                elif change == 'extra-proof': proof['optional'] = True
                elif change in ('extra-before-source', 'extra-after-source'):
                    proof['beforeSha256' if change == 'extra-before-source' else 'afterSha256']['third_party/rhwp/src/unreviewed.rs'] = '0'*64
                elif change == 'observed-hash':
                    # Leave the exact declared proof unchanged; only actual
                    # component observations are coherently altered in both inputs.
                    source['preparedFiles'][name] = source['coreSourceFiles'][name] = '0'*64
                else:
                    legacy = (picture_line_segment_owner.INPUT_SOURCE_SHA256[name] if change == 'legacy-original-pin'
                              else hashlib.sha256(b'owned former stale picture vector source\n').hexdigest())
                    proof['afterSha256'][name] = legacy
                    source['preparedFiles'][name] = source['coreSourceFiles'][name] = legacy
                write_json(folder/'provenance.json', value)
            with self.subTest(change=change): self.assert_rejected_without_outputs(folders)

    def test_rehashed_public_ledger_cannot_omit_or_replace_picture_owner_proof(self):
        folders = self.pair(); parity_path = folders['editor']/'source-parity.json'
        original_parity = json.loads(parity_path.read_bytes())
        original = {role:json.loads((folder/'provenance.json').read_bytes())
                    for role, folder in folders.items()}
        for change in ('missing', 'mismatch'):
            parity = copy.deepcopy(original_parity)
            if change == 'missing': parity.pop('pictureLineSegmentOwner')
            else: parity['pictureLineSegmentOwner']['helperSha256'] = '0'*64
            write_json(parity_path, parity)
            for role, folder in folders.items():
                value = copy.deepcopy(original[role]); value['source']['ledgerSha256'] = digest(parity_path)
                if role == 'editor':
                    value['files']['source-parity.json'] = {'size':parity_path.stat().st_size,
                                                          'sha256':digest(parity_path)}
                write_json(folder/'provenance.json', value)
            with self.subTest(change=change):
                self.assert_rejected_without_outputs(folders, 'Picture line segment owner source/ledger proof mismatch')

    def test_registered_stored_origin_target_requires_real_native_skia_feature(self):
        source = self.source(); c = self.helper()
        manifest = source/'third_party/rhwp/Cargo.toml'
        entries = tomllib.loads(manifest.read_text())['test']
        target = [entry for entry in entries if entry['name'] == 'opengeul_stored_lineseg_origin']
        self.assertEqual(len(target), 1)
        self.assertEqual(target[0]['required-features'], ['native-skia'])
        try:
            c.source_contract(source, c.configured())
        except ValueError as error:
            self.fail('Correct stored-origin native-skia registration was rejected: '+str(error))
        original = manifest.read_text()
        block = ('name = "opengeul_stored_lineseg_origin"\n'
                 'path = "tests/opengeul_stored_lineseg_origin.rs"\n'
                 'required-features = ["native-skia"]\n')
        self.assertEqual(original.count(block), 1)
        manifest.write_text(original.replace(block, block.replace('required-features = ["native-skia"]\n', '')))
        with self.assertRaisesRegex(ValueError, 'Native integration test is not correctly registered'):
            c.source_contract(source, c.configured())

    def test_stored_line_origin_three_compiled_sources_and_public_proof_are_mandatory(self):
        source = self.source(); c = self.helper()
        self.assertEqual(len(stored_lineseg_origin.SOURCE_FILES), 3)
        self.assertTrue(set(stored_lineseg_origin.SOURCE_FILES) <= set(c.SOURCE_FILES))
        _, contract = c.source_contract(source, c.configured())
        for name in stored_lineseg_origin.SOURCE_FILES:
            self.assertEqual(contract['preparedFiles'][name], digest(source/name))
            self.assertEqual(contract['coreSourceFiles'][name], digest(source/name))
        ledger_path = source/'.opengeul-overlay.json'
        ledger = json.loads(ledger_path.read_bytes()); ledger.pop('storedLineSegmentOrigin')
        write_json(ledger_path, ledger)
        out = self.root/'missing-stored-origin-proof'
        with self.assertRaises(ValueError):
            c.capture('editor', self.payload('editor'), source, out, env=self.env)
        self.assertFalse(out.exists())

    def test_stored_origin_capture_rejects_proof_forgery_and_each_unreviewed_compiled_source(self):
        source = self.source(); c = self.helper(); payload = self.payload('editor')
        ledger_path = source/'.opengeul-overlay.json'
        original = json.loads(ledger_path.read_bytes())
        files = {name:(source/name).read_bytes() for name in stored_lineseg_origin.SOURCE_FILES}
        cases = ['helper', 'extra-proof']
        cases += [kind+':'+name for name in files
                  for kind in ('before', 'after', 'missing-source', 'unreviewed-source', 'coherent-legacy')]
        for i, change in enumerate(cases):
            for name, data in files.items(): (source/name).write_bytes(data)
            ledger = copy.deepcopy(original); proof = ledger['storedLineSegmentOrigin']
            if change == 'helper': proof['helperSha256'] = '0'*64
            elif change == 'extra-proof': proof['optional'] = True
            else:
                kind, name = change.split(':', 1)
                if kind in ('before', 'after'): proof[kind+'Sha256'][name] = '0'*64
                elif kind == 'missing-source': (source/name).unlink()
                else:
                    (source/name).write_bytes(b'owned former stored-row-dropping core source\n')
                    if kind == 'coherent-legacy': proof['afterSha256'][name] = digest(source/name)
            write_json(ledger_path, ledger)
            out = self.root/('invalid-stored-origin-'+str(i))
            with self.subTest(change=change), self.assertRaises((ValueError, FileNotFoundError)):
                c.capture('editor', payload, source, out, env=self.env)
            self.assertFalse(out.exists())

    def test_stored_origin_capture_rejects_mismatched_complete_core_inventory_before_output(self):
        source = self.source(); c = self.helper(); actual_tree = c.tree
        name = stored_lineseg_origin.SOURCE_FILES[0]
        def changed_core_inventory(folder, cap):
            if folder == source/'third_party/rhwp/src':
                target = source/name
                target.write_bytes(target.read_bytes()+b'// changed between actual source observations\n')
            return actual_tree(folder, cap)
        out = self.root/'mismatched-stored-core-observation'
        with patch.object(c, 'tree', side_effect=changed_core_inventory), \
                self.assertRaisesRegex(ValueError, 'Stored line segment origin complete core source mismatch'):
            c.capture('editor', self.payload('editor'), source, out, env=self.env)
        self.assertFalse(out.exists())

    def test_matching_component_pair_cannot_omit_stored_proof_or_any_explicit_source(self):
        folders = self.pair()
        original = {role:json.loads((folder/'provenance.json').read_bytes())
                    for role, folder in folders.items()}
        for change in ('proof', *stored_lineseg_origin.SOURCE_FILES):
            for role, folder in folders.items():
                value = copy.deepcopy(original[role])
                if change == 'proof': value['source'].pop('storedLineSegmentOrigin')
                else: value['source']['preparedFiles'].pop(change)
                write_json(folder/'provenance.json', value)
            with self.subTest(change=change): self.assert_rejected_without_outputs(folders)

    def test_matching_component_pair_rejects_coherent_stored_legacy_before_after_and_helper(self):
        folders = self.pair()
        original = {role:json.loads((folder/'provenance.json').read_bytes())
                    for role, folder in folders.items()}
        cases = ['helper']+[kind+':'+name for name in stored_lineseg_origin.SOURCE_FILES
                           for kind in ('before', 'after', 'observed-hash', 'legacy-original-pin', 'coherent-legacy')]
        for change in cases:
            for role, folder in folders.items():
                value = copy.deepcopy(original[role]); source = value['source']
                proof = source['storedLineSegmentOrigin']
                if change == 'helper': proof['helperSha256'] = '0'*64
                else:
                    kind, name = change.split(':', 1)
                    if kind in ('before', 'after'): proof[kind+'Sha256'][name] = '0'*64
                    elif kind == 'observed-hash':
                        source['preparedFiles'][name] = source['coreSourceFiles'][name] = '0'*64
                    else:
                        legacy = (stored_lineseg_origin.INPUT_SOURCE_SHA256[name] if kind == 'legacy-original-pin'
                                  else hashlib.sha256(b'owned former stored-row-dropping core source\n').hexdigest())
                        proof['afterSha256'][name] = legacy
                        source['preparedFiles'][name] = source['coreSourceFiles'][name] = legacy
                write_json(folder/'provenance.json', value)
            with self.subTest(change=change): self.assert_rejected_without_outputs(folders)

    def test_rehashed_public_ledger_cannot_omit_or_replace_stored_origin_proof(self):
        folders = self.pair(); parity_path = folders['editor']/'source-parity.json'
        original_parity = json.loads(parity_path.read_bytes())
        original = {role:json.loads((folder/'provenance.json').read_bytes())
                    for role, folder in folders.items()}
        for change in ('missing', 'mismatch'):
            parity = copy.deepcopy(original_parity)
            if change == 'missing': parity.pop('storedLineSegmentOrigin')
            else: parity['storedLineSegmentOrigin']['helperSha256'] = '0'*64
            write_json(parity_path, parity)
            for role, folder in folders.items():
                value = copy.deepcopy(original[role]); value['source']['ledgerSha256'] = digest(parity_path)
                if role == 'editor':
                    value['files']['source-parity.json'] = {'size':parity_path.stat().st_size,
                                                          'sha256':digest(parity_path)}
                write_json(folder/'provenance.json', value)
            with self.subTest(change=change):
                self.assert_rejected_without_outputs(folders, 'Stored line segment origin source/ledger proof mismatch')

    def test_nested_line_source_inventory_and_public_proof_are_mandatory(self):
        source = self.source(); c = self.helper()
        self.assertTrue(set(nested_line_navigation.SOURCE_FILES) <= set(c.SOURCE_FILES))
        config = c.configured()
        self.assertEqual(config['helpers'][nested_line_navigation.HELPER],
                         digest(ROOT/nested_line_navigation.HELPER))
        ledger_path = source/'.opengeul-overlay.json'
        ledger = json.loads(ledger_path.read_bytes())
        ledger.pop('nestedLineNavigation')
        write_json(ledger_path, ledger)
        out = self.root/'missing-nested-proof'
        with self.assertRaises(ValueError):
            c.capture('editor', self.payload('editor'), source, out, env=self.env)
        self.assertFalse(out.exists())

    def test_nested_line_capture_rejects_forged_proof_and_missing_or_rehashed_source(self):
        source = self.source(); c = self.helper(); payload = self.payload('editor')
        ledger_path = source/'.opengeul-overlay.json'
        original = json.loads(ledger_path.read_bytes())
        inputs = {name:(source/name).read_bytes() for name in nested_line_navigation.SOURCE_FILES}
        cases = ['before', 'after', 'helper', 'extra-proof']
        cases += [kind+':'+name for name in inputs
                  for kind in ('missing-source', 'unreviewed-source', 'coherent-mutated-source')]
        for change in cases:
            for name, data in inputs.items():
                (source/name).write_bytes(data)
            ledger = copy.deepcopy(original)
            proof = ledger['nestedLineNavigation']
            if change == 'before': proof['beforeSha256'][next(iter(inputs))] = '0'*64
            elif change == 'after': proof['afterSha256'][next(iter(inputs))] = '0'*64
            elif change == 'helper': proof['helperSha256'] = '0'*64
            elif change == 'extra-proof': proof['optional'] = True
            else:
                kind, name = change.split(':', 1)
                if kind == 'missing-source': (source/name).unlink()
                else:
                    (source/name).write_bytes(inputs[name]+b'// coherent unreviewed cursor replacement\n')
                    if kind == 'coherent-mutated-source': proof['afterSha256'][name] = digest(source/name)
            write_json(ledger_path, ledger)
            out = self.root/('invalid-nested-'+str(cases.index(change)))
            with self.subTest(change=change), self.assertRaises((ValueError, FileNotFoundError)):
                c.capture('editor', payload, source, out, env=self.env)
            self.assertFalse(out.exists())

    def test_flat_only_cursor_and_coherent_rehashed_ledger_cannot_capture(self):
        source = self.source(); c = self.helper()
        ledger_path = source/'.opengeul-overlay.json'
        ledger = json.loads(ledger_path.read_bytes())
        name = nested_line_navigation.SOURCE_FILES[0]
        (source/name).write_bytes(b'owned legacy flat-only cursor source fixture\n')
        ledger['nestedLineNavigation']['afterSha256'][name] = digest(source/name)
        write_json(ledger_path, ledger)
        out = self.root/'legacy-flat-nested-source'
        with self.assertRaises(ValueError):
            c.capture('editor', self.payload('editor'), source, out, env=self.env)
        self.assertFalse(out.exists())

    def test_matching_components_cannot_omit_nested_line_proof_or_compiled_path(self):
        folders = self.pair()
        originals = {role:json.loads((folder/'provenance.json').read_bytes())
                     for role, folder in folders.items()}
        for change in ('proof', *nested_line_navigation.SOURCE_FILES):
            for role, folder in folders.items():
                value = copy.deepcopy(originals[role])
                if change == 'proof': value['source'].pop('nestedLineNavigation')
                else: value['source']['preparedFiles'].pop(change)
                write_json(folder/'provenance.json', value)
            with self.subTest(change=change):
                self.assert_rejected_without_outputs(folders)

    def test_matching_components_reject_nested_before_after_helper_and_legacy_forgery(self):
        folders = self.pair()
        originals = {role:json.loads((folder/'provenance.json').read_bytes())
                     for role, folder in folders.items()}
        cases = ['before', 'after', 'helper', 'coherent-legacy', 'reviewed-original-flat-pin']
        cases += ['observed-hash:'+name for name in nested_line_navigation.SOURCE_FILES]
        for change in cases:
            for role, folder in folders.items():
                value = copy.deepcopy(originals[role])
                proof = value['source']['nestedLineNavigation']
                name = nested_line_navigation.SOURCE_FILES[0]
                if change == 'before': proof['beforeSha256'][name] = '0'*64
                elif change == 'after': proof['afterSha256'][name] = '0'*64
                elif change == 'helper': proof['helperSha256'] = '0'*64
                elif change.startswith('observed-hash:'):
                    value['source']['preparedFiles'][change.split(':', 1)[1]] = '0'*64
                else:
                    legacy = (nested_line_navigation.INPUT_SOURCE_SHA256[name]
                              if change == 'reviewed-original-flat-pin' else
                              hashlib.sha256(b'owned legacy flat-only cursor source fixture\n').hexdigest())
                    proof['afterSha256'][name] = legacy
                    value['source']['preparedFiles'][name] = legacy
                write_json(folder/'provenance.json', value)
            with self.subTest(change=change):
                self.assert_rejected_without_outputs(folders)

    def test_rehashed_public_ledger_cannot_drop_or_replace_nested_line_source_proof(self):
        folders = self.pair()
        parity_path = folders['editor']/'source-parity.json'
        original_parity = json.loads(parity_path.read_bytes())
        originals = {role:json.loads((folder/'provenance.json').read_bytes())
                     for role, folder in folders.items()}
        for change in ('missing', 'mismatch'):
            parity = copy.deepcopy(original_parity)
            if change == 'missing': parity.pop('nestedLineNavigation')
            else: parity['nestedLineNavigation']['helperSha256'] = '0'*64
            write_json(parity_path, parity)
            for role, folder in folders.items():
                value = copy.deepcopy(originals[role])
                value['source']['ledgerSha256'] = digest(parity_path)
                if role == 'editor':
                    value['files']['source-parity.json'] = {
                        'size':parity_path.stat().st_size, 'sha256':digest(parity_path)}
                write_json(folder/'provenance.json', value)
            with self.subTest(change=change):
                self.assert_rejected_without_outputs(folders, 'Nested line navigation source/ledger proof mismatch')

    def test_full_component_source_requires_shape_proof_and_connector_inventory(self):
        source=self.source();c=self.helper()
        self.assertTrue(set(shape_creation_history.SOURCE_FILES)<=set(c.SOURCE_FILES),'Both compiled shape sources must be explicit')
        path=source/'.opengeul-overlay.json';ledger=json.loads(path.read_bytes());ledger.pop('shapeCreationHistory',None);write_json(path,ledger)
        out=self.root/'missing-shape-proof'
        with self.assertRaises(ValueError):c.capture('editor',self.payload('editor'),source,out,env=self.env)
        self.assertFalse(out.exists())
    def test_rehashed_shape_before_after_or_helper_cannot_authorize_capture(self):
        source=self.source();path=source/'.opengeul-overlay.json';original=json.loads(path.read_bytes());c=self.helper();payload=self.payload('editor')
        for key in ('beforeSha256','afterSha256','helperSha256'):
            ledger=copy.deepcopy(original)
            if key=='helperSha256':ledger['shapeCreationHistory'][key]='0'*64
            else:ledger['shapeCreationHistory'][key][shape_creation_history.SOURCE_FILES[0]]='0'*64
            write_json(path,ledger);out=self.root/('invalid-shape-'+key)
            with self.subTest(key=key),self.assertRaises(ValueError):c.capture('editor',payload,source,out,env=self.env)
            self.assertFalse(out.exists())
    def test_legacy_menu_phase_cannot_replace_current_shape_source_contract(self):
        source=self.source();path=source/'.opengeul-overlay.json';ledger=json.loads(path.read_bytes())
        legacy=dict(menu_clipboard.PHASE_SOURCE_SHA256['hwpx'])
        ledger['menuClipboardPaste']['afterSha256']=legacy
        for name,value in legacy.items():
            if name==menu_clipboard.HANDLER:
                (source/name).write_bytes(b'owned prior shape handler')
        ledger['shapeCreationHistory']['afterSha256'][menu_clipboard.HANDLER]=legacy[menu_clipboard.HANDLER]
        ledger['asyncClipboardGuard']['afterSha256']['input-handler.ts']=legacy[menu_clipboard.HANDLER]
        ledger['imageInsertionGuard']['afterSha256']['engine/input-handler.ts']=legacy[menu_clipboard.HANDLER]
        ledger['asyncFontSelectionGuard']['afterSha256'][menu_clipboard.HANDLER]=legacy[menu_clipboard.HANDLER]
        # Make every other controlled fixture proof coherent. The production
        # Source caller must independently reject a legacy menu phase.
        shape_creation_history.OUTPUT_SOURCE_SHA256=dict(ledger['shapeCreationHistory']['afterSha256'])
        write_json(path,ledger)
        out=self.root/'legacy-final-menu'
        with self.assertRaises(ValueError):self.helper().capture('editor',self.payload('editor'),source,out,env=self.env)
        self.assertFalse(out.exists())
    def test_consumer_rejects_missing_shape_proof_even_when_both_components_agree(self):
        folders=self.pair()
        for folder in folders.values():
            path=folder/'provenance.json';value=json.loads(path.read_bytes());value['source'].pop('shapeCreationHistory');write_json(path,value)
        self.assert_rejected_without_outputs(folders)
    def test_rehashed_component_shape_proof_stays_bound_to_each_compiled_source(self):
        folders=self.pair();original={role:json.loads((folder/'provenance.json').read_bytes()) for role,folder in folders.items()}
        for key in ('beforeSha256','afterSha256','helperSha256'):
            for role,folder in folders.items():
                value=copy.deepcopy(original[role])
                if key=='helperSha256':value['source']['shapeCreationHistory'][key]='0'*64
                else:value['source']['shapeCreationHistory'][key][shape_creation_history.SOURCE_FILES[1]]='0'*64
                write_json(folder/'provenance.json',value)
            with self.subTest(key=key):self.assert_rejected_without_outputs(folders)
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = {'GITHUB_REPOSITORY': 'ATLKR/OpenGeul', 'GITHUB_SHA': 'a'*40,
                    'GITHUB_RUN_ID': '38147025695', 'GITHUB_RUN_ATTEMPT': '1'}

    def helper(self):
        self.assertIsNotNone(components, 'Windows component integrity helper is missing')
        return components

    def test_owned_composition_fixture_crlf_keeps_text_and_raw_byte_contracts_distinct(self):
        original_write_text = Path.write_text
        def windows_composition_write(path, data, *args, **kwargs):
            if path.name == 'input-handler-text.ts' and kwargs.get('newline') is None:
                kwargs['newline'] = '\r\n'
            return original_write_text(path, data, *args, **kwargs)
        # Use real files while exercising Windows' default text newline conversion.
        with patch.object(Path, 'write_text', windows_composition_write):
            source = self.source()
        path = source/'third_party/rhwp/rhwp-studio/src/engine/input-handler-text.ts'
        raw = path.read_bytes()
        self.assertIn(b'\r\n', raw)
        normalized_sha = hashlib.sha256(path.read_text(encoding='utf-8').encode('utf-8')).hexdigest()
        self.assertNotEqual(digest(path), normalized_sha)
        ledger = self.helper().read_json(source/'.opengeul-overlay.json')
        self.assertEqual(ledger['compositionFix']['afterSha256'], normalized_sha)
        _, contract = self.helper().source_contract(source, self.helper().configured())
        self.assertEqual(contract['compositionTextSha256'], normalized_sha)
        self.assertEqual(contract['preparedFiles'][path.relative_to(source).as_posix()], digest(path))
        path.write_bytes(raw.replace(b'synthetic prepared source', b'changed prepared source'))
        with self.assertRaisesRegex(ValueError, 'Incomplete composition source ledger'):
            self.helper().source_contract(source, self.helper().configured())

    def source(self):
        c = self.helper()
        source = self.root/'hop'
        for name in c.SOURCE_FILES:
            if name == com_source_contract.LEDGER_PATH or name.startswith('third_party/rhwp/src/opengeul_com_worker/'):
                continue
            path = source/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('synthetic prepared source: '+name+'\n', encoding='utf-8')
        for directory in ('third_party/rhwp/src', 'third_party/rhwp/vendor/svg2pdf/src'):
            path = source/directory/'owned-synthetic.rs'
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('// owned bounded source fixture\n')
        core = source/'third_party/rhwp'
        lock = json.loads((ROOT/'config/upstream.lock.json').read_text())
        # Controlled detached references exercise real git HEAD verification.
        for folder, name in ((source, 'hop'), (core, 'rhwp')):
            subprocess.run(['git', 'init', '-q', str(folder)], check=True)
            (folder/'.git/HEAD').write_text(lock[name]['commit']+'\n')
        original = '[package]\nname = "rhwp"\nversion = "0.8.7"\nautotests = false\n'
        (core/'Cargo.toml').write_text(original, encoding='utf-8')
        for upstream, local in c.COPIED_OVERLAYS.items():
            if upstream.startswith('third_party/rhwp/src/opengeul_com_worker/'):continue
            (source/upstream).write_bytes((ROOT/local).read_bytes())
        self.com_source(source)
        prepare_native_tests.prepare(core)
        manifest = (core/'Cargo.toml').read_text(encoding='utf-8')
        com_source_contract.REFERENCE['preparedManifestSha256'] = [
            hashlib.sha256(manifest.replace('\n', ending).encode()).hexdigest()
            for ending in ('\n','\r\n')]
        write_json(self.com_reference_path,com_source_contract.REFERENCE)
        self.native_source(source)
        namespace = {'patch': 'HWPX header raw-fragment inherited namespaces',
                     'upstreamHeaderSha256': 'b'*64,
                     'patchedHeaderSha256': digest(core/'src/parser/hwpx/header.rs'),
                     'helperSha256': digest(ROOT/'overlay/hwpx_namespaces.rs')}
        write_json(core/'.opengeul-namespaces.json', namespace)
        vendor = source/'apps/studio-host/vendor/rhwp-core'
        vendor.mkdir(parents=True)
        for name in wasm_artifacts.FILES:
            (vendor/name).write_bytes(b'synthetic owned WASM fixture')
        (vendor/'rhwp_bg.wasm').write_bytes(b'\0asm\1\0\0\0')
        (vendor/'package.json').write_text('{"version":"0.8.7"}')
        wasm_artifacts.capture(vendor)
        wasm = json.loads((vendor/'OPEN_GEUL_WASM.json').read_text())
        write_json(vendor/'PROVENANCE.json', {'originalUpstream': {}, 'opengeulRebuild': wasm})
        engine = source/'third_party/rhwp/rhwp-studio/src/engine'
        clipboard_files = ('input-handler-keyboard.ts', 'input-handler.ts')
        for name in clipboard_files:
            (engine/name).write_bytes(('// owned prepared async clipboard fixture: '+name+'\n').encode())
        insert = source/'third_party/rhwp/rhwp-studio/src/command/commands/insert.ts'
        insert.parent.mkdir(parents=True, exist_ok=True)
        insert.write_bytes(b'// owned prepared image insertion fixture\n')
        toolbar = source/'apps/studio-host/src/ui/toolbar.ts'
        toolbar.parent.mkdir(parents=True, exist_ok=True)
        toolbar.write_bytes(b'// owned prepared async font fixture\n')
        # Transport tests use bounded owned source bytes as immutable references.
        # Real pinned patching is exercised by the dedicated preparation/native tests.
        pdf_reference = {name: {path: digest(source/path) for path in getattr(pdf_search_text, name)}
                         for name in ('PATCHED_SHA256', 'PRESERVED_SHA256')}
        for name, reference in pdf_reference.items():
            override = patch.object(pdf_search_text, name, reference)
            override.start()
            self.addCleanup(override.stop)
        self.pdf_reference_path = self.root/'pdf-fixture-reference.json'
        write_json(self.pdf_reference_path, pdf_reference)
        pdf_proof = {'formatVersion': 1,
                     'helperSha256': digest(ROOT/pdf_search_text.HELPER),
                     'beforeSha256': pdf_search_text.SOURCE_SHA256,
                     'afterSha256': pdf_search_text.PATCHED_SHA256,
                     'preservedSha256': pdf_search_text.PRESERVED_SHA256}
        font_before = {name:digest(source/name) for name in pdf_font_resolution.SOURCE_FILES}
        renderer = source/pdf_font_resolution.PDF
        renderer.write_bytes(renderer.read_bytes()+b'// owned final installed PDF font selector\n')
        font_after = {name:digest(source/name) for name in pdf_font_resolution.SOURCE_FILES}
        for name, reference in (('INPUT_SOURCE_SHA256', font_before), ('OUTPUT_SOURCE_SHA256', font_after)):
            override = patch.object(pdf_font_resolution, name, reference)
            override.start(); self.addCleanup(override.stop)
        self.pdf_font_reference_path = self.root/'pdf-font-fixture-reference.json'
        write_json(self.pdf_font_reference_path, {'before':font_before, 'after':font_after})
        font_proof = {'beforeSha256':font_before, 'afterSha256':font_after,
                      'helperSha256':digest(ROOT/pdf_font_resolution.HELPER)}
        for name in shape_creation_history.SOURCE_FILES:
            path=source/name
            if not path.is_file():path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'owned shape transport source fixture')
        menu_final = {name: digest(source/name) for name in menu_clipboard.SOURCE_FILES}
        legacy_menu={**menu_final,menu_clipboard.HANDLER:hashlib.sha256(b'owned prior shape handler').hexdigest()}
        menu_phases = {
            'prepared': {**legacy_menu, menu_clipboard.LIB: hashlib.sha256(b'owned prior native fixture').hexdigest()},
            'hwpx': legacy_menu,
            'hwpx-windows': {**legacy_menu, menu_clipboard.LIB: hashlib.sha256(b'owned CRLF native fixture').hexdigest()},
            'prepared-shape-history': {**menu_final, menu_clipboard.LIB: hashlib.sha256(b'owned prior native fixture').hexdigest()},
            'hwpx-shape-history':menu_final,
            'hwpx-windows-shape-history':{**menu_final,menu_clipboard.LIB:hashlib.sha256(b'owned CRLF native fixture').hexdigest()},
        }
        menu_override = patch.object(menu_clipboard, 'PHASE_SOURCE_SHA256', menu_phases)
        menu_override.start()
        self.addCleanup(menu_override.stop)
        self.menu_reference_path = self.root/'menu-fixture-reference.json'
        write_json(self.menu_reference_path, menu_phases)
        shape_output={name:digest(source/name) for name in shape_creation_history.SOURCE_FILES}
        shape_override=patch.object(shape_creation_history,'OUTPUT_SOURCE_SHA256',shape_output)
        shape_override.start();self.addCleanup(shape_override.stop)
        self.shape_reference_path=self.root/'shape-fixture-reference.json'
        write_json(self.shape_reference_path,shape_output)
        shape_proof={'beforeSha256':shape_creation_history.INPUT_SOURCE_SHA256,
                     'afterSha256':shape_output,'helperSha256':digest(ROOT/shape_creation_history.HELPER)}
        nested_output = {name:digest(source/name) for name in nested_line_navigation.SOURCE_FILES}
        nested_override = patch.object(nested_line_navigation, 'OUTPUT_SOURCE_SHA256', nested_output)
        nested_override.start(); self.addCleanup(nested_override.stop)
        nested_scalar = patch.object(nested_line_navigation, 'OUTPUT_SHA256',
                                     nested_output[nested_line_navigation.CURSOR])
        nested_scalar.start(); self.addCleanup(nested_scalar.stop)
        self.nested_reference_path = self.root/'nested-fixture-reference.json'
        write_json(self.nested_reference_path, nested_output)
        nested_proof = {'beforeSha256':dict(nested_line_navigation.INPUT_SOURCE_SHA256),
                        'afterSha256':nested_output,
                        'helperSha256':digest(ROOT/nested_line_navigation.HELPER)}
        stored_output = {name:digest(source/name) for name in stored_lineseg_origin.SOURCE_FILES}
        stored_override = patch.object(stored_lineseg_origin, 'OUTPUT_SOURCE_SHA256', stored_output)
        stored_override.start(); self.addCleanup(stored_override.stop)
        self.stored_reference_path = self.root/'stored-origin-fixture-reference.json'
        write_json(self.stored_reference_path, stored_output)
        stored_proof = {'beforeSha256':dict(stored_lineseg_origin.INPUT_SOURCE_SHA256),
                        'afterSha256':stored_output,
                        'helperSha256':digest(ROOT/stored_lineseg_origin.HELPER)}
        picture_output = {name:digest(source/name) for name in picture_line_segment_owner.SOURCE_FILES}
        picture_override = patch.object(picture_line_segment_owner, 'OUTPUT_SOURCE_SHA256', picture_output)
        picture_override.start(); self.addCleanup(picture_override.stop)
        self.picture_reference_path = self.root/'picture-owner-fixture-reference.json'
        write_json(self.picture_reference_path, picture_output)
        picture_proof = {'beforeSha256':dict(picture_line_segment_owner.INPUT_SOURCE_SHA256),
                         'afterSha256':picture_output,
                         'helperSha256':digest(ROOT/picture_line_segment_owner.HELPER)}
        virtual_output = {name:digest(source/name) for name in virtual_picture_layout_admission.SOURCE_FILES}
        virtual_override = patch.object(virtual_picture_layout_admission, 'OUTPUT_SOURCE_SHA256', virtual_output)
        virtual_override.start(); self.addCleanup(virtual_override.stop)
        self.virtual_reference_path = self.root/'virtual-layout-fixture-reference.json'
        write_json(self.virtual_reference_path, virtual_output)
        virtual_proof = {'beforeSha256':dict(virtual_picture_layout_admission.INPUT_SOURCE_SHA256),
                         'afterSha256':virtual_output,
                         'helperSha256':digest(ROOT/virtual_picture_layout_admission.HELPER)}
        persistence_output = {name:digest(source/name) for name in hwpx_persistence_verification.SOURCE_FILES}
        persistence_override = patch.object(hwpx_persistence_verification, 'OUTPUT_SOURCE_SHA256', persistence_output)
        persistence_override.start(); self.addCleanup(persistence_override.stop)
        self.persistence_reference_path = self.root/'persistence-fixture-reference.json'
        write_json(self.persistence_reference_path, persistence_output)
        persistence_proof = {'beforeSha256':dict(hwpx_persistence_verification.INPUT_SOURCE_SHA256),
                             'afterSha256':persistence_output,
                             'helperSha256':digest(ROOT/hwpx_persistence_verification.HELPER)}
        menu_proof = {'beforeSha256': {**menu_clipboard.INPUT_SOURCE_SHA256, **menu_clipboard.INPUT_NATIVE_SHA256},
                      'afterSha256': menu_final,
                      'helperSha256': digest(ROOT/'overlay/menu-clipboard.ts'),
                      'hwpxPatcherSha256': digest(ROOT/'scripts/prepare_hwpx.py')}
        ledger = {'version': json.loads((ROOT/'config/product.json').read_text())['version'],
                  'source': 'OpenGeul distribution overlays', 'preservedFiles': {},
                  'baselinePreservedFiles': {}, 'changes': ['synthetic owned source'],
                  'hwpxSaveV1': True, 'extendedFiles': ['commands.rs','state.rs','lib.rs','tauri-bridge.ts','main.ts','file.ts','desktop-events.ts','edit.ts','document-open.ts'],
                  'compositionFix': {'beforeSha256': 'c'*64,
                     'afterSha256': hashlib.sha256((engine/'input-handler-text.ts').read_text(encoding='utf-8').encode('utf-8')).hexdigest(),
                     'helperSha256': digest(ROOT/'overlay/composition-final.ts'), 'evidence': 'synthetic'},
                  'namespacePatch': namespace, 'wasmRebuild': wasm,
                  'pdfSearchText': pdf_proof,
                  'pdfFontResolution': font_proof,
                  'menuClipboardPaste': menu_proof,
                  'shapeCreationHistory': shape_proof,
                  'nestedLineNavigation': nested_proof,
                  'storedLineSegmentOrigin': stored_proof,
                  'pictureLineSegmentOwner': picture_proof,
                  'virtualPictureLayoutAdmission': virtual_proof,
                  'hwpxPersistenceVerification': persistence_proof,
                  'asyncClipboardGuard': {
                      'beforeSha256': {
                          'input-handler-keyboard.ts': '1076739c3742d73329e91cb3cdf2f638f03fcb21e7df0aa6a326963bf231b87c',
                          'input-handler.ts': '9bbba9420b2a8d4c3630a1797976bf9e65b9b1b4a67c608f305e1f5a873c31ce',
                      },
                      'afterSha256': {name: digest(engine/name) for name in clipboard_files},
                  },
                  'imageInsertionGuard': {
                      'beforeSha256': {
                          'command/commands/insert.ts': '29e9c3d98e26a8c7b44cd59af8a31872abf4e618ae37d15e3049178cc5226364',
                          'engine/input-handler.ts': '9bbba9420b2a8d4c3630a1797976bf9e65b9b1b4a67c608f305e1f5a873c31ce',
                      },
                      'afterSha256': {'command/commands/insert.ts': digest(insert),
                                      'engine/input-handler.ts': digest(engine/'input-handler.ts')},
                  },
                  'asyncFontSelectionGuard': {
                      'beforeSha256': FONT_SOURCE_PINS,
                      'afterSha256': {name: digest(source/name) for name in FONT_SOURCE_PINS},
                  },
                  'comWorker': json.loads((source/com_source_contract.LEDGER_PATH).read_bytes()),
                  'nativeActivation': json.loads((source/native_source_contract.LEDGER_PATH).read_bytes())}
        write_json(source/'.opengeul-overlay.json', ledger)
        return source

    def com_source(self, source):
        core = source/'third_party/rhwp'
        (core/'src/main.rs').write_text('mod mcp_serve;\nfn main() {\n    let raw_args: Vec<String> = env::args().collect();\n    controlled_parser(raw_args);\n}\n')
        (core/'src/mcp_serve.rs').write_text('// owned transport fixture\n'+com_worker.OLD_TRANSPORT)
        ledger = com_worker.apply(source)
        (core/'Cargo.lock').write_bytes((ROOT/'overlay/cli-cargo.lock.toml').read_bytes())
        reference = {name:ledger[name] for name in ('originalFiles','patchedFiles')}
        replacement = patch.object(com_source_contract,'REFERENCE',reference)
        replacement.start();self.addCleanup(replacement.stop)
        self.com_reference_path = self.root/'owned-com-reference.json'
        write_json(self.com_reference_path,reference)

    def native_source(self, source):
        """소유한 작은 원본 fixture만 대체하고 실제 source policy는 그대로 실행한다."""
        native = source/'apps/desktop/src-tauri'
        config = self.helper().configured()
        original = '[package]\nname="hop-desktop"\nversion="'+config['product']['version']+'"\n[dependencies]\ntauri = { version = "=2.11.1", features = [] }\nopen = "5"\n[patch.crates-io]\n'
        (native/'Cargo.toml').write_text(native_activation.desktop_manifest(original), encoding='utf-8')
        lock = (ROOT/'overlay/desktop-cargo.lock.toml').read_text(encoding='utf-8')
        lock = buildkit.replace_once(lock, 'name = "hop-desktop"\nversion = "'+config['upstream']['hop']['version']+'"',
                                   'name = "hop-desktop"\nversion = "'+config['product']['version']+'"')
        (native/'Cargo.lock').write_text(lock, encoding='utf-8', newline='\n')
        references = {}
        for directory, actual in native_source_contract.REFERENCE.items():
            changed = ('Cargo.toml', 'src/app.rs', 'src/process.rs') if directory == 'tauri-2.11.1' else ('Cargo.toml', 'src/dialog/windows.rs')
            original_files = {name: ('owned original '+directory+'/'+name+'\n').encode()
                              for name in (*changed, 'LICENSE')}
            prepared_files = {name: (b'owned prepared '+content if name in changed else content)
                              for name, content in original_files.items()}
            for name, content in prepared_files.items():
                path = native/'opengeul-native'/directory/name
                path.parent.mkdir(parents=True, exist_ok=True);path.write_bytes(content)
            references[directory] = {key: actual[key] for key in ('name','version','archiveSha256')}
            references[directory]['originalFiles'] = {name: hashlib.sha256(value).hexdigest() for name,value in original_files.items()}
            references[directory]['patchedFiles'] = {name: hashlib.sha256(prepared_files[name]).hexdigest() for name in changed}
        replacement = patch.object(native_source_contract, 'REFERENCE', references)
        replacement.start();self.addCleanup(replacement.stop)
        self.native_reference_path = self.root/'owned-native-reference.json'
        write_json(self.native_reference_path, references)
        shim = {name: digest(ROOT/'overlay/native-open'/name) for name in native_source_contract.SHIM_FILES}
        ledger = {'formatVersion':1, 'patchInputSha256':digest(ROOT/'overlay/native-activation-patches.json'),
                  'originalManifestSha256':hashlib.sha256(original.encode()).hexdigest(),
                  'preparedManifestSha256':digest(native/'Cargo.toml'),
                  'preparedLockSha256':digest(native/'Cargo.lock'), 'crates':{}, 'shimFiles':shim}
        for directory,item in references.items():
            ledger['crates'][directory] = {key:item[key] for key in ('name','version','archiveSha256','originalFiles')}
            ledger['crates'][directory]['preparedFiles'] = {**item['originalFiles'],**item['patchedFiles']}
        (source/native_source_contract.LEDGER_PATH).write_bytes(native_source_contract.ledger_bytes(ledger))

    def cli_command(self, *arguments):
        # A subprocess cannot inherit a Python fixture constant. Substitute only
        # that immutable test input, then run the unchanged public argparse path.
        return [sys.executable, '-c',
                "import json,runpy,sys,native_source_contract,com_source_contract,pdf_search_text,pdf_font_resolution,menu_clipboard,shape_creation_history,nested_line_navigation,stored_lineseg_origin,picture_line_segment_owner,virtual_picture_layout_admission,hwpx_persistence_verification;from pathlib import Path;"
                "native_source_contract.REFERENCE=json.loads(Path(sys.argv[1]).read_text());"
                "com_source_contract.REFERENCE=json.loads(Path(sys.argv[2]).read_text());"
                "pdf_fixture=json.loads(Path(sys.argv[3]).read_text());"
                "pdf_search_text.PATCHED_SHA256=pdf_fixture['PATCHED_SHA256'];"
                "pdf_search_text.PRESERVED_SHA256=pdf_fixture['PRESERVED_SHA256'];"
                "menu_clipboard.PHASE_SOURCE_SHA256=json.loads(Path(sys.argv[4]).read_text());"
                "shape_creation_history.OUTPUT_SOURCE_SHA256=json.loads(Path(sys.argv[5]).read_text());"
                "nested_line_navigation.OUTPUT_SOURCE_SHA256=json.loads(Path(sys.argv[6]).read_text());"
                "nested_line_navigation.OUTPUT_SHA256=nested_line_navigation.OUTPUT_SOURCE_SHA256[nested_line_navigation.CURSOR];"
                "stored_lineseg_origin.OUTPUT_SOURCE_SHA256=json.loads(Path(sys.argv[7]).read_text());"
                "picture_line_segment_owner.OUTPUT_SOURCE_SHA256=json.loads(Path(sys.argv[8]).read_text());"
                "virtual_picture_layout_admission.OUTPUT_SOURCE_SHA256=json.loads(Path(sys.argv[9]).read_text());"
                "hwpx_persistence_verification.OUTPUT_SOURCE_SHA256=json.loads(Path(sys.argv[10]).read_text());"
                "font_fixture=json.loads(Path(sys.argv[11]).read_text());"
                "pdf_font_resolution.INPUT_SOURCE_SHA256=font_fixture['before'];"
                "pdf_font_resolution.OUTPUT_SOURCE_SHA256=font_fixture['after'];"
                "sys.argv=sys.argv[12:];runpy.run_path(sys.argv[0],run_name='__main__')",
                str(self.native_reference_path),str(self.com_reference_path),str(self.pdf_reference_path),
                str(self.menu_reference_path),str(self.shape_reference_path),str(self.nested_reference_path),
                str(self.stored_reference_path),str(self.picture_reference_path),str(self.virtual_reference_path),
                str(self.persistence_reference_path),str(self.pdf_font_reference_path),str(HELPER),*arguments]

    def payload(self, role, architecture='x64'):
        target = self.root/(role+'-payload')
        target.mkdir()
        machine = windows_arch.machine_for(architecture)
        if role == 'cli':
            (target/'Tools').mkdir()
            (target/'Tools/rhwp.exe').write_bytes(pe(machine))
        else:
            (target/'OpenGeul.exe').write_bytes(pe(machine))
            (target/'WebView2Loader.dll').write_bytes(pe(machine))
            (target/'AppxManifest.xml').write_text(buildkit.manifest(buildkit.DEV_IDENTITY, json.loads((ROOT/'config/product.json').read_text())['version'], architecture))
            buildkit.make_assets(target/'Assets')
            (target/'Assets/app.ico').unlink()
            (target/'Assets/app.png').unlink()
            (target/'Notices').mkdir()
            (target/'Notices/OpenGeul-LICENSE.txt').write_text('Owned synthetic fixture notice')
        return target

    def pair(self, architecture='x64'):
        c = self.helper()
        source = self.source()
        folders = {}
        for role in ('editor', 'cli'):
            folders[role] = self.root/(role+'-component')
            options = {} if architecture == 'x64' else {'architecture': architecture}
            c.capture(role, self.payload(role, architecture), source, folders[role], env=self.env, **options)
        return folders

    def combine(self, folders, env=None, architecture='x64'):
        options = {} if architecture == 'x64' else {'architecture': architecture}
        return self.helper().combine(folders['editor'], folders['cli'], self.root/'combined',
                                     self.root/'package-source', env=self.env if env is None else env, **options)

    def assert_rejected_without_outputs(self, folders, match=None, env=None, architecture='x64'):
        with self.assertRaisesRegex(ValueError, match or '.'):
            self.combine(folders, env, architecture)
        self.assertFalse((self.root/'combined').exists())
        self.assertFalse((self.root/'package-source').exists())

    def test_arm64_cli_capture_and_combine_restore_exact_runtime(self):
        source = self.source()
        folders = {role: self.root/(role+'-component') for role in ('editor', 'cli')}
        for role in folders:
            payload = self.payload(role, 'arm64')
            result = subprocess.run(
                self.cli_command('capture', '--architecture', 'arm64', '--role', role,
                 '--payload', str(payload), '--source', str(source), '--out', str(folders[role])),
                env={**os.environ, **self.env, 'PYTHONPATH':str(ROOT/'scripts')}, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run(
            self.cli_command('combine', '--architecture', 'arm64',
             '--editor', str(folders['editor']), '--cli', str(folders['cli']),
             '--payload', str(self.root/'combined'), '--source', str(self.root/'package-source')),
            env={**os.environ, **self.env, 'PYTHONPATH':str(ROOT/'scripts')}, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root/'combined/Tools/rhwp.exe').read_bytes(), pe(0xAA64))

    def test_arm64_components_bind_native_exes_dll_manifest_and_artifact_names(self):
        folders = self.pair('arm64')
        self.combine(folders, architecture='arm64')
        for name in ('OpenGeul.exe', 'WebView2Loader.dll', 'Tools/rhwp.exe'):
            self.assertEqual((self.root/'combined'/name).read_bytes(), pe(0xAA64))
        self.assertIn('ProcessorArchitecture="arm64"', (self.root/'combined/AppxManifest.xml').read_text())
        receipt = json.loads((self.root/'package-source/.opengeul-windows-components.json').read_text())
        for role in folders:
            record = json.loads((folders[role]/'provenance.json').read_text())
            self.assertEqual(record['target'], 'aarch64-pc-windows-msvc')
            self.assertEqual(record['formatVersion'], 2 if role == 'cli' else 1)
            self.assertEqual(record['helpers']['scripts/windows_arch.py'], digest(ROOT/'scripts/windows_arch.py'))
            self.assertEqual(receipt['components'][role]['artifactName'],
                             'opengeul-'+role+'-component-arm64-'+self.env['GITHUB_RUN_ID'])
            self.assertEqual(receipt['components'][role]['provenanceSha256'], digest(folders[role]/'provenance.json'))
        self.assertEqual(json.loads((folders['editor']/'provenance.json').read_text())['source'],
                         json.loads((folders['cli']/'provenance.json').read_text())['source'])

    def test_unsupported_component_architectures_fail_before_local_inputs_or_staging(self):
        c = self.helper()
        for architecture in ('ARM64', 'arm64ec', 'x86', '', None):
            with self.subTest(architecture=architecture), patch.object(c, 'configured', side_effect=AssertionError('Architecture must be validated first')):
                with self.assertRaises(ValueError):
                    c.capture('cli', self.root/'absent', self.root/'absent-source', self.root/'out',
                              architecture=architecture, env=self.env)
                with self.assertRaises(ValueError):
                    c.combine(self.root/'absent-editor', self.root/'absent-cli', self.root/'combined',
                              self.root/'package-source', architecture=architecture, env=self.env)
        self.assertFalse((self.root/'out').exists())
        self.assertFalse((self.root/'combined').exists())

    def test_arm64_capture_rejects_mixed_exe_dll_manifest_and_arm64ec_before_staging(self):
        c = self.helper()
        source = self.source()
        payloads = {role: self.payload(role, 'arm64') for role in ('editor', 'cli')}
        changes = [('editor', 'OpenGeul.exe', pe()), ('editor', 'WebView2Loader.dll', pe()),
                   ('editor', 'WebView2Loader.dll', pe(0xA641)), ('cli', 'Tools/rhwp.exe', pe()),
                   ('cli', 'Tools/rhwp.exe', pe(0xA641)),
                   ('editor', 'AppxManifest.xml', buildkit.manifest(buildkit.DEV_IDENTITY,
                        json.loads((ROOT/'config/product.json').read_text())['version']).encode())]
        for index, (role, name, data) in enumerate(changes):
            path = payloads[role]/name
            original = path.read_bytes()
            path.write_bytes(data)
            out = self.root/f'rejected-architecture-{index}'
            with self.subTest(role=role, name=name, index=index), patch.object(c.tempfile, 'mkdtemp', side_effect=AssertionError('Invalid architecture must precede staging')):
                with self.assertRaisesRegex(ValueError, 'arm64|architecture'):
                    c.capture(role, payloads[role], source, out, architecture='arm64', env=self.env)
            self.assertFalse(out.exists())
            path.write_bytes(original)

    def test_arm64_target_and_role_metadata_cannot_be_forged_before_staging(self):
        folders = self.pair('arm64')
        for role, folder in folders.items():
            path = folder/'provenance.json'
            original = json.loads(path.read_text())
            for key, value in [('target', 'x86_64-pc-windows-msvc'), ('target', 'arm64ec-pc-windows-msvc'),
                               ('role', 'cli' if role == 'editor' else 'editor')]:
                changed = copy.deepcopy(original); changed[key] = value
                write_json(path, changed)
                with self.subTest(role=role, key=key, value=value), patch.object(self.helper().tempfile, 'mkdtemp', side_effect=AssertionError('Identity must precede staging')):
                    self.assert_rejected_without_outputs(folders, 'identity', architecture='arm64')
            write_json(path, original)

    def test_arm64_recomputed_inventory_cannot_authorize_x64_or_arm64ec_runtime(self):
        folders = self.pair('arm64')
        for role, name in [('editor','OpenGeul.exe'), ('editor','WebView2Loader.dll'), ('cli','Tools/rhwp.exe')]:
            path = folders[role]/'payload'/(name+'.gz' if role == 'cli' else name)
            provenance = folders[role]/'provenance.json'
            original_data = path.read_bytes(); original = json.loads(provenance.read_text())
            for machine in (0x8664, 0xA641):
                raw = pe(machine)
                path.write_bytes(gzip.compress(raw, mtime=0) if role == 'cli' else raw)
                changed = copy.deepcopy(original)
                changed['files']['payload/'+name+('.gz' if role == 'cli' else '')] = {'size': path.stat().st_size, 'sha256': digest(path)}
                if role == 'cli':
                    changed['runtime'] = {'path': name, 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
                write_json(provenance, changed)
                with self.subTest(role=role, name=name, machine=machine), patch.object(self.helper().tempfile, 'mkdtemp', side_effect=AssertionError('Native PE validation must precede staging')):
                    self.assert_rejected_without_outputs(folders, 'arm64', architecture='arm64')
            path.write_bytes(original_data); write_json(provenance, original)

    def test_x64_editor_and_arm64_cli_cannot_join_for_either_expected_architecture(self):
        c = self.helper(); source = self.source()
        folders = {role: self.root/(role+'-component') for role in ('editor', 'cli')}
        c.capture('editor', self.payload('editor'), source, folders['editor'], env=self.env)
        c.capture('cli', self.payload('cli', 'arm64'), source, folders['cli'], architecture='arm64', env=self.env)
        for architecture in ('x64', 'arm64'):
            with self.subTest(architecture=architecture), patch.object(c.tempfile, 'mkdtemp', side_effect=AssertionError('Mixed architecture must precede staging')):
                self.assert_rejected_without_outputs(folders, 'identity', architecture=architecture)

    def test_arm64_workers_still_require_complete_core_source_parity(self):
        c = self.helper(); source = self.source()
        folders = {role: self.root/(role+'-component') for role in ('editor', 'cli')}
        c.capture('editor', self.payload('editor', 'arm64'), source, folders['editor'], architecture='arm64', env=self.env)
        (source/'third_party/rhwp/src/owned-synthetic.rs').write_text('// changed after editor build\n')
        c.capture('cli', self.payload('cli', 'arm64'), source, folders['cli'], architecture='arm64', env=self.env)
        self.assert_rejected_without_outputs(folders, 'source parity', architecture='arm64')

    def test_same_run_components_restore_complete_payload_and_exact_ledger(self):
        folders = self.pair()
        self.combine(folders)
        self.assertEqual((self.root/'combined/OpenGeul.exe').read_bytes(), pe())
        self.assertEqual((self.root/'combined/Tools/rhwp.exe').read_bytes(), pe())
        self.assertEqual((self.root/'package-source/.opengeul-overlay.json').read_bytes(),
                         (self.root/'hop/.opengeul-overlay.json').read_bytes())
        self.assertEqual(set(p.name for p in folders['editor'].iterdir()),
                         {'payload', 'provenance.json', 'source-parity.json'})
        self.assertEqual(set(p.name for p in folders['cli'].iterdir()), {'payload', 'provenance.json'})
        receipt_path = self.root/'package-source/.opengeul-windows-components.json'
        self.assertTrue(receipt_path.is_file(), 'Verified producer/runtime receipt must survive transport cleanup')
        receipt = json.loads(receipt_path.read_text())
        self.assertEqual(receipt['repository'], self.env['GITHUB_REPOSITORY'])
        self.assertEqual(receipt['commit'], self.env['GITHUB_SHA'])
        self.assertEqual(receipt['runId'], self.env['GITHUB_RUN_ID'])
        self.assertEqual(receipt['runAttempt'], '1')
        self.assertEqual(receipt['formatVersion'], 1)
        for role, runtime in [('editor','OpenGeul.exe'), ('cli','Tools/rhwp.exe')]:
            record = receipt['components'][role]
            self.assertEqual(record['artifactName'], 'opengeul-'+role+'-component-'+self.env['GITHUB_RUN_ID'])
            self.assertEqual(record['runtime'], runtime)
            self.assertEqual(record['size'], (self.root/'combined'/runtime).stat().st_size)
            self.assertEqual(record['sha256'], digest(self.root/'combined'/runtime))
            self.assertEqual(record['provenanceSha256'], digest(folders[role]/'provenance.json'))
        contract = json.loads((folders['editor']/'provenance.json').read_text())['source']
        self.assertEqual(receipt['sourceContractSha256'], hashlib.sha256((json.dumps(contract,indent=2,sort_keys=True)+'\n').encode()).hexdigest())

    def test_capture_requires_native_activation_ledger_before_creating_transport(self):
        source = self.source()
        (source/'apps/desktop/src-tauri/.opengeul-native-activation.json').unlink(missing_ok=True)
        out = self.root/'unbound-native-component'
        with self.assertRaises(ValueError):
            self.helper().capture('editor', self.payload('editor'), source, out, env=self.env)
        self.assertFalse(out.exists())

    def test_capture_requires_com_worker_ledger_before_creating_transport(self):
        source = self.source();(source/'third_party/rhwp/.opengeul-com-worker.json').unlink(missing_ok=True)
        out = self.root/'unbound-com-component'
        with self.assertRaises(ValueError):
            self.helper().capture('cli',self.payload('cli'),source,out,env=self.env)
        self.assertFalse(out.exists())

    def test_unlisted_com_worker_source_cannot_enter_a_component(self):
        source = self.source();extra = source/'third_party/rhwp/src/opengeul_com_worker/extra.rs'
        extra.parent.mkdir(parents=True,exist_ok=True);extra.write_text('// unreviewed COM source\n')
        out = self.root/'extra-com-component'
        with self.assertRaises(ValueError):
            self.helper().capture('editor',self.payload('editor'),source,out,env=self.env)
        self.assertFalse(out.exists())

    def test_both_components_require_the_same_full_com_proof_and_public_binding(self):
        folders = self.pair()
        records = [json.loads((folders[role]/'provenance.json').read_bytes()) for role in ('editor','cli')]
        for record in records:self.assertIn('comWorker',record['source'])
        self.assertEqual(records[0]['source']['comWorker'],records[1]['source']['comWorker'])
        public = json.loads((folders['editor']/'source-parity.json').read_bytes())
        self.assertEqual(public['comWorker'],records[0]['source']['comWorker']['ledger'])

    def test_consumer_rejects_missing_com_proof_even_when_both_records_agree(self):
        folders = self.pair()
        for folder in folders.values():
            path = folder/'provenance.json';record = json.loads(path.read_bytes())
            record['source'].pop('comWorker',None);write_json(path,record)
        self.assert_rejected_without_outputs(folders)

    def test_typed_dispatch_and_worker_code_tampering_fail_before_capture(self):
        source = self.source();payload = self.payload('cli')
        names = ['src/main.rs','src/mcp_serve.rs',*(f'src/opengeul_com_worker/{name}' for name in com_source_contract.FILES)]
        for index,name in enumerate(names):
            path = source/'third_party/rhwp'/name;original = path.read_bytes();path.write_bytes(original+b'// unreviewed change\n')
            out = self.root/('tampered-com-source-'+str(index))
            with self.subTest(path=name),self.assertRaises(ValueError):
                self.helper().capture('cli',payload,source,out,env=self.env)
            self.assertFalse(out.exists());path.write_bytes(original)

    def test_rehashed_dispatch_and_origin_ledgers_cannot_authorize_other_cli_source(self):
        source = self.source();payload = self.payload('cli');path = source/com_source_contract.LEDGER_PATH
        original = json.loads(path.read_bytes());config = self.helper().configured()
        for index,change in enumerate(('original','patched','helper','clsid','qualification')):
            altered = copy.deepcopy(original)
            if change == 'original':altered['originalFiles']['src/main.rs'] = '0'*64
            elif change == 'patched':altered['patchedFiles']['src/mcp_serve.rs'] = '0'*64
            elif change == 'helper':altered['helperSha256'] = '0'*64
            elif change == 'clsid':altered['fixedClsid'] = '00000000-0000-0000-0000-000000000000'
            else:altered['qualification'] = True
            path.write_bytes(com_source_contract.ledger_bytes(altered,config))
            out = self.root/('rehashed-com-source-'+str(index))
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,'COM worker'):
                self.helper().capture('cli',payload,source,out,env=self.env)
            self.assertFalse(out.exists())

    def test_com_manifest_native_test_prefix_and_exact_cli_lock_are_bound(self):
        source = self.source();payload = self.payload('cli');core = source/'third_party/rhwp'
        lock = core/'Cargo.lock';before = lock.read_bytes();lock.write_bytes(before+b'# unreviewed lock\n')
        with self.assertRaisesRegex(ValueError,'CLI lock'):
            self.helper().capture('cli',payload,source,self.root/'unreviewed-cli-lock',env=self.env)
        lock.write_bytes(before)
        manifest = core/'Cargo.toml';original = manifest.read_bytes()
        manifest.write_bytes(original+b'\n[unreviewed]\nfeature=true\n')
        with self.assertRaisesRegex(ValueError,'compiled native-test manifest mismatch'):
            self.helper().capture('cli',payload,source,self.root/'unreviewed-native-suffix',env=self.env)
        self.assertFalse((self.root/'unreviewed-cli-lock').exists());self.assertFalse((self.root/'unreviewed-native-suffix').exists())

    def test_com_consumer_rehash_cannot_change_fixed_source_dependency_or_test_prefix(self):
        folders = self.pair();originals = {role:json.loads((folder/'provenance.json').read_bytes()) for role,folder in folders.items()}
        config = self.helper().configured()
        for change in ('original','patched','copied','dependency','native-prefix','lock','raw-ledger','prepared-manifest'):
            for role,folder in folders.items():
                record = copy.deepcopy(originals[role]);source = record['source'];ledger = source['comWorker']['ledger']
                if change == 'original':ledger['originalFiles']['Cargo.toml'] = '0'*64
                elif change == 'patched':ledger['patchedFiles']['src/main.rs'] = '0'*64
                elif change == 'copied':ledger['copiedFiles']['src/opengeul_com_worker/mod.rs'] = '0'*64
                elif change == 'dependency':ledger['windowsDependencies']['windows-core'] = '=0.62.2'
                elif change == 'native-prefix':source['nativeTests']['originalManifestSha256'] = '0'*64
                elif change == 'prepared-manifest':source['preparedFiles']['third_party/rhwp/Cargo.toml'] = '0'*64
                elif change == 'lock':source['preparedFiles']['third_party/rhwp/Cargo.lock'] = '0'*64
                source['preparedFiles'][com_source_contract.LEDGER_PATH] = hashlib.sha256(com_source_contract.ledger_bytes(ledger,config)).hexdigest()
                if change == 'raw-ledger':source['preparedFiles'][com_source_contract.LEDGER_PATH] = '0'*64
                write_json(folder/'provenance.json',record)
            with self.subTest(change=change):self.assert_rejected_without_outputs(folders,'COM worker')

    def test_public_com_ledger_must_match_the_component_proof_after_rehash(self):
        folders = self.pair();path = folders['editor']/'source-parity.json';public = json.loads(path.read_bytes())
        public['comWorker']['helperSha256'] = '0'*64;write_json(path,public)
        for role,folder in folders.items():
            provenance = folder/'provenance.json';record = json.loads(provenance.read_bytes())
            record['source']['ledgerSha256'] = digest(path)
            if role == 'editor':record['files']['source-parity.json'] = {'size':path.stat().st_size,'sha256':digest(path)}
            write_json(provenance,record)
        self.assert_rejected_without_outputs(folders,'COM worker proof mismatch')

    def test_com_worker_directory_has_no_unlisted_empty_subtree_or_symlink(self):
        source = self.source();payload = self.payload('cli');root = source/'third_party/rhwp/src/opengeul_com_worker'
        empty = root/'unlisted';empty.mkdir()
        with self.assertRaisesRegex(ValueError,'complete module source inventory'):
            self.helper().capture('cli',payload,source,self.root/'extra-com-directory',env=self.env)
        empty.rmdir();path = root/'mod.rs';data = path.read_bytes();path.unlink()
        other = self.root/'outside-com.rs';other.write_bytes(data)
        try:path.symlink_to(other)
        except OSError:self.skipTest('Host cannot create owned symlink fixture')
        with self.assertRaisesRegex(ValueError,'symlink|reparse'):
            self.helper().capture('cli',payload,source,self.root/'outside-com-module',env=self.env)
        self.assertFalse((self.root/'extra-com-directory').exists());self.assertFalse((self.root/'outside-com-module').exists())

    def test_unlisted_native_vendor_source_cannot_enter_a_component(self):
        source = self.source()
        extra = source/'apps/desktop/src-tauri/opengeul-native/tauri-2.11.1/src/unreviewed.rs'
        extra.parent.mkdir(parents=True, exist_ok=True)
        extra.write_text('// unreviewed compiler source\n')
        with self.assertRaises(ValueError):
            self.helper().capture('cli', self.payload('cli'), source, self.root/'extra-native', env=self.env)
        self.assertFalse((self.root/'extra-native').exists())

    def test_both_producers_bind_the_same_required_full_native_activation_proof(self):
        folders = self.pair()
        records = [json.loads((folders[role]/'provenance.json').read_text()) for role in ('editor','cli')]
        for record in records:
            self.assertIn('nativeActivation', record['source'])
            self.assertIn('overlay/native-open/README.md', record['helpers'])
        self.assertEqual(records[0]['source']['nativeActivation'], records[1]['source']['nativeActivation'])
        native = records[0]['source']['nativeActivation']['ledger']
        self.assertEqual(set(native['crates']), {'tauri-2.11.1','tauri-runtime-wry-2.11.1'})
        self.assertEqual(set(native['shimFiles']), {'Cargo.toml','LICENSE.txt','README.md','src/activation.rs','src/lib.rs'})

    def test_consumer_rejects_missing_native_proof_even_when_both_records_agree(self):
        folders = self.pair()
        for folder in folders.values():
            path = folder/'provenance.json'
            record = json.loads(path.read_text())
            record['source'].pop('nativeActivation', None)
            write_json(path, record)
        self.assert_rejected_without_outputs(folders)

    def test_public_distribution_ledger_requires_the_actual_native_activation_proof(self):
        source = self.source();path = source/'.opengeul-overlay.json'
        ledger = json.loads(path.read_bytes());ledger.pop('nativeActivation',None);write_json(path,ledger)
        out = self.root/'missing-public-native-proof'
        with self.assertRaisesRegex(ValueError,'native activation|Native activation'):
            self.helper().capture('editor',self.payload('editor'),source,out,env=self.env)
        self.assertFalse(out.exists())

    def test_consumer_rejects_rehashed_public_native_proof_that_disagrees_with_both_producers(self):
        folders = self.pair();path = folders['editor']/'source-parity.json'
        parity = json.loads(path.read_bytes());parity['nativeActivation'] = {'unbound':'different proof'}
        write_json(path,parity)
        for role,folder in folders.items():
            provenance = folder/'provenance.json';value = json.loads(provenance.read_bytes())
            value['source']['ledgerSha256'] = digest(path)
            if role == 'editor':value['files']['source-parity.json'] = {'size':path.stat().st_size,'sha256':digest(path)}
            write_json(provenance,value)
        self.assert_rejected_without_outputs(folders,'native activation|Native activation')

    def test_actual_vendor_mutation_and_rehashed_ledger_cannot_authorize_new_source(self):
        source = self.source()
        path = source/'apps/desktop/src-tauri/opengeul-native/tauri-2.11.1/src/process.rs'
        path.write_bytes(path.read_bytes()+b'// changed compiler input\n')
        payload = self.payload('editor')
        with self.assertRaisesRegex(ValueError, 'compiler source inventory'):
            self.helper().capture('editor', payload, source, self.root/'tampered-vendor', env=self.env)
        ledger_path = source/native_source_contract.LEDGER_PATH
        ledger = json.loads(ledger_path.read_bytes())
        ledger['crates']['tauri-2.11.1']['preparedFiles']['src/process.rs'] = digest(path)
        ledger_path.write_bytes(native_source_contract.ledger_bytes(ledger))
        with self.assertRaisesRegex(ValueError, 'prepared source inventory'):
            self.helper().capture('editor', payload, source, self.root/'rehash-vendor', env=self.env)
        self.assertFalse((self.root/'tampered-vendor').exists())
        self.assertFalse((self.root/'rehash-vendor').exists())

    def test_mixed_original_inventory_or_crate_identity_cannot_become_source_proof(self):
        source = self.source();payload = self.payload('cli')
        path = source/native_source_contract.LEDGER_PATH
        original = json.loads(path.read_bytes())
        for index, change in enumerate(('archive','version','original','prepared','outside')):
            altered = copy.deepcopy(original);crate = altered['crates']['tauri-2.11.1']
            if change == 'archive':crate['archiveSha256'] = '0'*64
            elif change == 'version':crate['version'] = '2.11.0'
            elif change == 'original':crate['originalFiles']['src/app.rs'] = '0'*64
            elif change == 'prepared':crate['preparedFiles'].pop('src/app.rs')
            else:crate['originalFiles']['../outside.rs'] = '0'*64
            path.write_bytes(native_source_contract.ledger_bytes(altered))
            out = self.root/('invalid-native-origin-'+str(index))
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'native activation|Native activation'):
                self.helper().capture('cli', payload, source, out, env=self.env)
            self.assertFalse(out.exists())

    def test_vendor_symlink_and_unlisted_empty_directory_fail_before_staging(self):
        source = self.source();payload = self.payload('cli')
        directory = source/'apps/desktop/src-tauri/opengeul-native/tauri-2.11.1'
        extra = directory/'unlisted-empty';extra.mkdir()
        with self.assertRaisesRegex(ValueError, 'source directory'):
            self.helper().capture('cli', payload, source, self.root/'extra-directory', env=self.env)
        extra.rmdir()
        path = directory/'LICENSE';data = path.read_bytes();path.unlink()
        outside = self.root/'outside-vendor-license';outside.write_bytes(data)
        try:path.symlink_to(outside)
        except OSError as error:self.skipTest('Owned synthetic symlink fixture unavailable: '+str(error))
        with self.assertRaisesRegex(ValueError, 'symlink|reparse'):
            self.helper().capture('cli', payload, source, self.root/'outside-vendor', env=self.env)
        self.assertFalse((self.root/'extra-directory').exists())
        self.assertFalse((self.root/'outside-vendor').exists())

    def test_rehashed_native_consumer_metadata_still_requires_reviewed_origin_and_patch_bytes(self):
        folders = self.pair()
        originals = {role:json.loads((folder/'provenance.json').read_bytes()) for role,folder in folders.items()}
        for change in ('archive','origin','prepared','shim','manifest','lock','patch','raw-ledger'):
            for role,folder in folders.items():
                record = copy.deepcopy(originals[role]);source = record['source'];ledger = source['nativeActivation']['ledger']
                crate = ledger['crates']['tauri-2.11.1']
                if change == 'archive':crate['archiveSha256'] = '0'*64
                elif change == 'origin':crate['originalFiles']['src/app.rs'] = '0'*64
                elif change == 'prepared':crate['preparedFiles']['src/app.rs'] = '0'*64
                elif change == 'shim':ledger['shimFiles']['src/lib.rs'] = '0'*64
                elif change == 'manifest':ledger['preparedManifestSha256'] = '0'*64
                elif change == 'lock':ledger['preparedLockSha256'] = '0'*64
                elif change == 'patch':ledger['patchInputSha256'] = '0'*64
                source['preparedFiles'][native_source_contract.LEDGER_PATH] = hashlib.sha256(native_source_contract.ledger_bytes(ledger)).hexdigest()
                if change == 'raw-ledger':source['preparedFiles'][native_source_contract.LEDGER_PATH] = '0'*64
                write_json(folder/'provenance.json', record)
            with self.subTest(change=change):self.assert_rejected_without_outputs(folders)

    def test_native_ledger_serialization_is_order_independent_and_raw_lf_bound(self):
        folders = self.pair()
        for folder in folders.values():
            path = folder/'provenance.json';record = json.loads(path.read_bytes())
            ledger = record['source']['nativeActivation']['ledger']
            record['source']['nativeActivation']['ledger'] = {key:ledger[key] for key in reversed(list(ledger))}
            write_json(path, record)
        self.combine(folders)
        self.assertTrue((self.root/'combined/Tools/rhwp.exe').is_file())

    def test_native_lock_binds_product_version_derivation_without_mutating_the_seed(self):
        source = self.source();seed = ROOT/'overlay/desktop-cargo.lock.toml'
        before = seed.read_bytes()
        try:_, contract = self.helper().source_contract(source, self.helper().configured())
        except ValueError as error:self.fail('Correct product-version lock was rejected: '+str(error))
        self.assertNotEqual(contract['nativeActivation']['ledger']['preparedLockSha256'], digest(seed))
        self.assertEqual(contract['nativeActivation']['ledger']['preparedLockSha256'],
                         digest(source/'apps/desktop/src-tauri/Cargo.lock'))
        self.assertEqual(seed.read_bytes(), before)

    def test_reviewed_native_dependency_has_one_source_per_key_and_preserves_open_library_name(self):
        source = self.source();native = source/'apps/desktop/src-tauri'
        manifest = tomllib.loads((native/'Cargo.toml').read_text())
        windows = manifest['target']['cfg(windows)']['dependencies']
        nonwindows = manifest['target']['cfg(not(windows))']['dependencies']
        self.assertNotIn('open',windows,'Cargo cannot give the same dependency key two source paths')
        self.assertEqual(windows.get('opengeul-native-open'),{'path':'opengeul-native/native-open'})
        self.assertEqual(nonwindows['open'],'5')
        shim = tomllib.loads((native/'opengeul-native/native-open/Cargo.toml').read_text())
        self.assertEqual(shim['lib']['name'],'open','Protected open::that call sites must resolve unchanged')
        try:self.helper().source_contract(source,self.helper().configured())
        except (KeyError,ValueError) as error:self.fail('Reviewed unique dependency source was rejected: '+str(error))

    def test_rehashed_old_target_dependent_open_alias_is_rejected_before_transport(self):
        source = self.source();native = source/'apps/desktop/src-tauri';manifest = native/'Cargo.toml'
        text = buildkit.replace_once(manifest.read_text(),
            'opengeul-native-open = { path = "opengeul-native/native-open" }',
            'open = { package = "opengeul-native-open", path = "opengeul-native/native-open" }')
        manifest.write_text(text,encoding='utf-8',newline='\n')
        path = source/native_source_contract.LEDGER_PATH;ledger = json.loads(path.read_bytes())
        ledger['preparedManifestSha256'] = digest(manifest)
        path.write_bytes(native_source_contract.ledger_bytes(ledger))
        public_path = source/'.opengeul-overlay.json';public = json.loads(public_path.read_bytes())
        public['nativeActivation'] = ledger;write_json(public_path,public)
        out = self.root/'target-source-conflict'
        with self.assertRaisesRegex(ValueError,'dependency contract'):
            self.helper().capture('editor',self.payload('editor'),source,out,env=self.env)
        self.assertFalse(out.exists())

    def test_rehashed_native_manifest_with_wrong_product_version_is_rejected(self):
        source = self.source();manifest = source/'apps/desktop/src-tauri/Cargo.toml'
        version = self.helper().configured()['product']['version']
        manifest.write_text(buildkit.replace_once(manifest.read_text(), 'version="'+version+'"', 'version="0.0.1"'))
        path = source/native_source_contract.LEDGER_PATH;ledger = json.loads(path.read_bytes())
        ledger['preparedManifestSha256'] = digest(manifest)
        path.write_bytes(native_source_contract.ledger_bytes(ledger))
        out = self.root/'wrong-native-product-version'
        with self.assertRaisesRegex(ValueError, 'product version'):
            self.helper().capture('editor', self.payload('editor'), source, out, env=self.env)
        self.assertFalse(out.exists())

    def test_crlf_or_unbound_shim_helper_cannot_enter_native_source_contract(self):
        source = self.source();payload = self.payload('editor')
        path = source/native_source_contract.LEDGER_PATH
        original = path.read_bytes();path.write_bytes(original.replace(b'\n',b'\r\n'))
        with self.assertRaisesRegex(ValueError, 'raw ledger digest'):
            self.helper().capture('editor', payload, source, self.root/'crlf-native-ledger', env=self.env)
        path.write_bytes(original)
        shim = source/'apps/desktop/src-tauri/opengeul-native/native-open/src/lib.rs'
        shim.write_bytes(shim.read_bytes()+b'// changed helper\n')
        with self.assertRaisesRegex(ValueError, 'overlay helper mismatch'):
            self.helper().capture('editor', payload, source, self.root/'changed-native-shim', env=self.env)
        self.assertFalse((self.root/'crlf-native-ledger').exists())
        self.assertFalse((self.root/'changed-native-shim').exists())

    def test_cli_above_transport_cap_compresses_and_restores_exact_raw_runtime(self):
        c = self.helper()
        source = self.source()
        cli_payload = self.payload('cli')
        executable = cli_payload/'Tools/rhwp.exe'
        with executable.open('ab') as stream:
            for _ in range(33): stream.write(b'\0' * (1024 * 1024))
        expected = {'size': executable.stat().st_size, 'sha256': digest(executable)}
        self.assertGreater(expected['size'], c.CAPS['cli'])
        folders = {role: self.root/(role+'-component') for role in ('editor', 'cli')}
        c.capture('editor', self.payload('editor'), source, folders['editor'], env=self.env)
        try: c.capture('cli', cli_payload, source, folders['cli'], env=self.env)
        except ValueError as error: self.fail('Compressible production-sized CLI was rejected: '+str(error))
        record = json.loads((folders['cli']/'provenance.json').read_text())
        self.assertEqual(record['formatVersion'], 2)
        self.assertEqual(record['runtime'], {'path': 'Tools/rhwp.exe', **expected})
        self.assertEqual(set(record['files']), {'payload/Tools/rhwp.exe.gz'})
        self.assertLessEqual(sum(p.stat().st_size for p in folders['cli'].rglob('*') if p.is_file()), c.CAPS['cli'])
        self.assertFalse((folders['cli']/'payload/Tools/rhwp.exe').exists())
        self.combine(folders)
        restored = self.root/'combined/Tools/rhwp.exe'
        self.assertEqual({'size': restored.stat().st_size, 'sha256': digest(restored)}, expected)
        self.assertFalse((self.root/'combined/Tools/rhwp.exe.gz').exists())
        receipt = json.loads((self.root/'package-source/.opengeul-windows-components.json').read_text())
        self.assertEqual({k: receipt['components']['cli'][k] for k in ('size', 'sha256')}, expected)

    def rewrite_cli_transport(self, folders, data, raw=None):
        path = folders['cli']/'payload/Tools/rhwp.exe.gz'
        path.write_bytes(data)
        provenance = folders['cli']/'provenance.json'
        value = json.loads(provenance.read_text())
        value['files']['payload/Tools/rhwp.exe.gz'] = {'size': len(data), 'sha256': digest(path)}
        if raw is not None:
            value['runtime'] = {'path': 'Tools/rhwp.exe', 'size': len(raw),
                                'sha256': hashlib.sha256(raw).hexdigest()}
        write_json(provenance, value)

    def test_cli_gzip_capture_is_deterministic_and_editor_format_stays_one(self):
        folders = self.pair()
        out = self.root/'second-cli'
        self.helper().capture('cli', self.root/'cli-payload', self.root/'hop', out, env=self.env)
        path = 'payload/Tools/rhwp.exe.gz'
        self.assertEqual((folders['cli']/path).read_bytes(), (out/path).read_bytes())
        self.assertEqual((folders['cli']/'provenance.json').read_bytes(), (out/'provenance.json').read_bytes())
        self.assertEqual((out/path).read_bytes()[3:8], b'\0'*5, 'No filename flag or timestamp may enter transport')
        self.assertEqual(json.loads((folders['editor']/'provenance.json').read_text())['formatVersion'], 1)

    def test_large_editor_inventory_captures_all_fields_within_unchanged_metadata_cap(self):
        c=self.helper();source=self.source();payload=self.payload('editor')
        baseline=self.root/'small-editor';c.capture('editor',payload,source,baseline,env=self.env)
        expected=c.read_json(baseline/'provenance.json')
        assets=payload/'Notices/many';assets.mkdir()
        for index in range(3200):
            (assets/f'owned-runtime-{index:04}.txt').write_bytes(b'owned runtime resource')
        inventory,_=c.tree(payload,c.CAPS['editor'])
        expected['files']={**{'payload/'+name:record for name,record in inventory.items()},
            'source-parity.json':expected['files']['source-parity.json']}
        pretty=(json.dumps(expected,indent=2,sort_keys=True)+'\n').encode()
        compact=(json.dumps(expected,sort_keys=True,separators=(',',':'))+'\n').encode()
        self.assertGreater(len(pretty),c.MAX_METADATA);self.assertLess(len(compact),c.MAX_METADATA)
        out=self.root/'large-editor';c.capture('editor',payload,source,out,env=self.env)
        self.assertEqual((out/'provenance.json').read_bytes(),compact)
        actual=c.validate_component(out,'editor',c.identity(self.env),c.configured())
        self.assertEqual(actual,expected);self.assertEqual(len(actual['files']),len(inventory)+1)
        self.assertEqual(actual['formatVersion'],1)
        self.assertEqual((out/'source-parity.json').read_bytes(),(baseline/'source-parity.json').read_bytes())
        cli=self.root/'matching-cli';c.capture('cli',self.payload('cli'),source,cli,env=self.env)
        self.assertEqual(c.read_json(cli/'provenance.json')['formatVersion'],2)
        self.assertEqual(c.read_json(cli/'provenance.json')['source'],actual['source'])
        c.combine(out,cli,self.root/'combined',self.root/'package-source',env=self.env)
        combined,_=c.tree(self.root/'combined',c.MAX_PAYLOAD)
        self.assertEqual(combined,{**inventory,c.CLI_RUNTIME:{'size':len(pe()),'sha256':hashlib.sha256(pe()).hexdigest()}})
        self.assertEqual(c.read_json(self.root/'package-source/.opengeul-windows-components.json')['sourceContractSha256'],
            hashlib.sha256((json.dumps(actual['source'],indent=2,sort_keys=True)+'\n').encode()).hexdigest())

    def test_compact_encoding_preserves_default_source_contract_bytes_and_hash(self):
        c=self.helper();source=self.source();_,contract=c.source_contract(source,c.configured())
        pretty=(json.dumps(contract,indent=2,sort_keys=True)+'\n').encode()
        self.assertEqual(c.encoded(contract),pretty)
        self.assertEqual(c.encoded(contract,compact=False),pretty)
        compact=c.encoded(contract,compact=True)
        self.assertEqual(json.loads(compact),contract);self.assertLess(len(compact),len(pretty))
        self.assertEqual(c.encoded(contract),pretty)
        with self.assertRaisesRegex(ValueError,'metadata exceeds cap'):
            c.encoded({'owned':'x'*c.MAX_METADATA},compact=True)

    def test_editor_compact_metadata_still_over_cap_is_rejected_before_output(self):
        c=self.helper();source=self.source();payload=self.payload('editor')
        assets=payload/'Notices/many';assets.mkdir()
        for index in range(7000):
            (assets/f'owned-runtime-{index:04}.txt').write_bytes(b'owned runtime resource')
        out=self.root/'oversized-metadata'
        with self.assertRaisesRegex(ValueError,'metadata exceeds cap'):
            c.capture('editor',payload,source,out,env=self.env)
        self.assertFalse(out.exists())

    def test_recomputed_transport_cannot_authorize_invalid_gzip_streams(self):
        folders = self.pair()
        original = (folders['cli']/'payload/Tools/rhwp.exe.gz').read_bytes()
        corrupt = bytearray(original); corrupt[-8] ^= 1
        streams = {'truncated': original[:-1], 'CRC': bytes(corrupt),
                   'trailing': original+b'junk', 'concatenated': original+original,
                   'not-gzip': pe()}
        for name, data in streams.items():
            with self.subTest(stream=name):
                self.rewrite_cli_transport(folders, data)
                with patch.object(self.helper().tempfile, 'mkdtemp', side_effect=AssertionError('Validation must precede staging')):
                    self.assert_rejected_without_outputs(folders, '(?i)gzip')

    def test_forged_cli_runtime_path_size_hash_and_format_are_rejected_before_staging(self):
        folders = self.pair()
        path = folders['cli']/'provenance.json'
        original = json.loads(path.read_text())
        changes = [('path', '../rhwp.exe'), ('size', 255), ('size', 257), ('size', True),
                   ('size', 96*1024*1024+1), ('sha256', '0'*64)]
        for key, value in changes:
            with self.subTest(key=key, value=value):
                changed = copy.deepcopy(original)
                changed['runtime'][key] = value
                write_json(path, changed)
                with patch.object(self.helper().tempfile, 'mkdtemp', side_effect=AssertionError('Validation must precede staging')):
                    self.assert_rejected_without_outputs(folders, '(?i)runtime|cap')
        for change in ({'formatVersion': 1}, {'runtime': {'path': 'Tools/rhwp.exe', 'size': 256, 'sha256': '0'*64, 'extra': 0}}):
            with self.subTest(change=change):
                changed = copy.deepcopy(original); changed.update(change)
                write_json(path, changed)
                self.assert_rejected_without_outputs(folders)

    def test_gzip_expansion_is_bounded_by_declared_raw_size(self):
        folders = self.pair()
        self.rewrite_cli_transport(folders, gzip.compress(pe()+b'\0'*(2*1024*1024), mtime=0))
        with patch.object(self.helper().tempfile, 'mkdtemp', side_effect=AssertionError('Expansion must fail before staging')):
            self.assert_rejected_without_outputs(folders, 'runtime size|cap')

    def test_capture_raw_and_combined_restored_payload_budget_are_enforced(self):
        c = self.helper()
        source = self.source()
        payload = self.payload('cli')
        with patch.object(c, 'MAX_PAYLOAD', 255):
            with self.assertRaisesRegex(ValueError, 'cap'):
                c.capture('cli', payload, source, self.root/'over-raw-cap', env=self.env)
        self.assertFalse((self.root/'over-raw-cap').exists())
        payload.rename(self.root/'unused-cli-payload')
        folders = self.pair_from_source(source)
        editor = json.loads((folders['editor']/'provenance.json').read_text())
        editor_size = sum(v['size'] for n, v in editor['files'].items() if n.startswith('payload/'))
        with patch.object(c, 'MAX_PAYLOAD', editor_size+255), patch.object(c.tempfile, 'mkdtemp', side_effect=AssertionError('Combined cap must precede staging')):
            self.assert_rejected_without_outputs(folders, 'combined|cap')

    def test_capture_rechecks_cli_input_size_and_hash_after_inventory(self):
        c = self.helper()
        source = self.source()
        payload = self.payload('cli')
        path = payload/'Tools/rhwp.exe'
        contract = c.source_contract
        changed = bytearray(pe()); changed[200] ^= 1
        for index, data in enumerate((bytes(changed), pe()+b'growth')):
            with self.subTest(size=len(data)):
                path.write_bytes(pe())
                def change_after_inventory(source, config):
                    result = contract(source, config)
                    path.write_bytes(data)
                    return result
                out = self.root/('changed-input-'+str(index))
                with patch.object(c, 'source_contract', side_effect=change_after_inventory), patch.object(c.tempfile, 'mkdtemp', side_effect=AssertionError('Changed input must fail before staging')):
                    with self.assertRaisesRegex(ValueError, 'runtime input'):
                        c.capture('cli', payload, source, out, env=self.env)
                self.assertFalse(out.exists())

    def test_second_decode_rechecks_changed_transport_and_removes_private_staging(self):
        folders = self.pair()
        c = self.helper()
        validate = c.validate_component
        def change_after_validation(folder, role, current, config, *, architecture='x64'):
            result = validate(folder, role, current, config, architecture=architecture)
            if role == 'cli':
                path = folder/'payload/Tools/rhwp.exe.gz'
                path.write_bytes(gzip.compress(pe()+b'changed', mtime=0))
            return result
        with patch.object(c, 'validate_component', side_effect=change_after_validation):
            self.assert_rejected_without_outputs(folders)
        self.assertFalse(any(p.name.startswith(('.opengeul-joined-', '.opengeul-source-')) for p in self.root.iterdir()))

    def test_tampered_cli_is_rejected_before_any_editor_file_is_staged(self):
        folders = self.pair()
        (folders['cli']/'payload/Tools/rhwp.exe.gz').write_bytes(gzip.compress(pe()+b'tamper', mtime=0))
        self.assert_rejected_without_outputs(folders, 'inventory')

    def test_missing_and_extra_files_are_rejected(self):
        folders = self.pair()
        path = folders['editor']/'payload/Notices/OpenGeul-LICENSE.txt'
        original = path.read_bytes()
        path.unlink()
        self.assert_rejected_without_outputs(folders, 'inventory|payload')
        path.write_bytes(original)
        (folders['cli']/'unexpected.json').write_text('{}')
        self.assert_rejected_without_outputs(folders, '(?i)component')

    def test_cross_run_source_repository_attempt_and_role_are_rejected(self):
        folders = self.pair()
        path = folders['cli']/'provenance.json'
        original = json.loads(path.read_text())
        for key, value in [('runId','2'), ('commit','b'*40), ('repository','other/repo'),
                           ('runAttempt','2'), ('role','editor')]:
            with self.subTest(key=key):
                changed = copy.deepcopy(original)
                changed[key] = value
                write_json(path, changed)
                self.assert_rejected_without_outputs(folders)
        write_json(path, original)
        bad_env = dict(self.env, GITHUB_RUN_ATTEMPT='0')
        self.assert_rejected_without_outputs(folders, env=bad_env)

    def test_previous_successful_attempt_can_join_current_retry_same_run_source(self):
        c = self.helper()
        source = self.source()
        folders = {role: self.root/(role+'-component') for role in ('editor', 'cli')}
        c.capture('editor', self.payload('editor'), source, folders['editor'], env=self.env)
        retry = dict(self.env, GITHUB_RUN_ATTEMPT='2')
        c.capture('cli', self.payload('cli'), source, folders['cli'], env=retry)
        self.combine(folders, retry)
        self.assertEqual((self.root/'combined/Tools/rhwp.exe').read_bytes(), pe())
        receipt = json.loads((self.root/'package-source/.opengeul-windows-components.json').read_text())
        self.assertEqual(receipt['runAttempt'], '2')
        self.assertEqual(receipt['components']['editor']['runAttempt'], '1')
        self.assertEqual(receipt['components']['cli']['runAttempt'], '2')

    def test_future_and_invalid_component_attempts_are_rejected(self):
        folders = self.pair()
        path = folders['cli']/'provenance.json'
        original = json.loads(path.read_text())
        for attempt in ('3', '0', '-1', '1.5', 'not-a-number', 1):
            with self.subTest(attempt=attempt):
                value = copy.deepcopy(original)
                value['runAttempt'] = attempt
                write_json(path, value)
                self.assert_rejected_without_outputs(folders, env=dict(self.env, GITHUB_RUN_ATTEMPT='2'))

    def test_unlisted_core_source_changes_break_cross_worker_parity(self):
        c = self.helper()
        source = self.source()
        folders = {role: self.root/(role+'-component') for role in ('editor', 'cli')}
        c.capture('editor', self.payload('editor'), source, folders['editor'], env=self.env)
        path = source/'third_party/rhwp/src/owned-synthetic.rs'
        path.write_text('// different source for the CLI\n')
        c.capture('cli', self.payload('cli'), source, folders['cli'], env=self.env)
        self.assert_rejected_without_outputs(folders, 'source parity')

    def test_recomputed_inventory_cannot_authorize_wrong_machine_exe_or_dll(self):
        folders = self.pair()
        for role, name in [('cli','Tools/rhwp.exe'), ('editor','WebView2Loader.dll')]:
            with self.subTest(name=name):
                path = folders[role]/'payload'/(name+'.gz' if role == 'cli' else name)
                path.write_bytes(gzip.compress(pe(0x14c), mtime=0) if role == 'cli' else pe(0x14c))
                provenance = folders[role]/'provenance.json'
                value = json.loads(provenance.read_text())
                value['files']['payload/'+name+('.gz' if role == 'cli' else '')] = {'size': path.stat().st_size, 'sha256': digest(path)}
                if role == 'cli':
                    value['runtime'] = {'path': name, 'size': 256, 'sha256': hashlib.sha256(pe(0x14c)).hexdigest()}
                write_json(provenance, value)
                self.assert_rejected_without_outputs(folders, 'x64')
                path.write_bytes(gzip.compress(pe(), mtime=0) if role == 'cli' else pe())
                value['files']['payload/'+name+('.gz' if role == 'cli' else '')] = {'size': path.stat().st_size, 'sha256': digest(path)}
                if role == 'cli':
                    value['runtime']['sha256'] = hashlib.sha256(pe()).hexdigest()
                write_json(provenance, value)

    def test_local_helper_and_wasm_bindings_are_enforced_even_if_both_records_match(self):
        folders = self.pair()
        for role in folders:
            path = folders[role]/'provenance.json'
            value = json.loads(path.read_text())
            value['helpers']['overlay/font_policy.rs'] = '0'*64
            write_json(path, value)
        self.assert_rejected_without_outputs(folders, 'helper')

    def test_source_parity_byte_tampering_is_rejected(self):
        folders = self.pair()
        path = folders['editor']/'source-parity.json'
        path.write_bytes(path.read_bytes()+b' ')
        self.assert_rejected_without_outputs(folders, 'inventory')

    def test_capture_rejects_unregistered_native_test_before_output_creation(self):
        c = self.helper()
        source = self.source()
        path = source/'third_party/rhwp/Cargo.toml'
        path.write_text(path.read_text().replace('tests/opengeul_table_height.rs', 'tests/other.rs'))
        out = self.root/'component'
        with self.assertRaisesRegex(ValueError, '(?i)native'):
            c.capture('editor', self.payload('editor'), source, out, env=self.env)
        self.assertFalse(out.exists())

    def test_capture_checks_actual_namespace_test_overlay_and_wasm_bytes(self):
        c = self.helper()
        source = self.source()
        targets = ['third_party/rhwp/src/parser/hwpx/header.rs',
                   'third_party/rhwp/tests/opengeul_pdf_policy.rs',
                   'third_party/rhwp/src/renderer/pdf/opengeul_pdf_guard.rs',
                   'apps/studio-host/vendor/rhwp-core/rhwp_bg.wasm']
        for index, name in enumerate(targets):
            with self.subTest(name=name):
                path = source/name
                original = path.read_bytes()
                path.write_bytes(original+b'tamper')
                out = self.root/f'rejected-{index}'
                with self.assertRaises(ValueError):
                    c.capture('cli', self.payload('cli') if index == 0 else self.root/'cli-payload', source, out, env=self.env)
                self.assertFalse(out.exists())
                path.write_bytes(original)

    def test_required_password_composition_and_wasm_ledger_fields_are_enforced(self):
        c = self.helper()
        source = self.source()
        path = source/'.opengeul-overlay.json'
        original = json.loads(path.read_text())
        payload = self.payload('editor')
        for key in ('hwpxSaveV1', 'compositionFix', 'namespacePatch', 'wasmRebuild'):
            with self.subTest(key=key):
                changed = copy.deepcopy(original)
                del changed[key]
                write_json(path, changed)
                out = self.root/('missing-'+key)
                with self.assertRaises(ValueError):
                    c.capture('editor', payload, source, out, env=self.env)
                self.assertFalse(out.exists())

    def test_cancel_close_source_is_part_of_every_worker_contract(self):
        self.assertIn('apps/studio-host/src/core/desktop-events.ts', self.helper().SOURCE_FILES,
                      'Actual close-cancellation event source must be bound in the receipt contract')

    def test_cut_document_guard_source_is_part_of_every_worker_contract(self):
        self.assertIn('apps/studio-host/src/command/commands/edit.ts', self.helper().SOURCE_FILES,
                      'The actual async Cut document guard must be bound in the receipt contract')

    def test_capture_rejects_mutated_async_clipboard_keyboard_before_output(self):
        source = self.source()
        target = source/'third_party/rhwp/rhwp-studio/src/engine/input-handler-keyboard.ts'
        target.write_bytes(target.read_bytes()+b'// changed async paste target\n')
        out = self.root/'changed-async-keyboard'
        with self.assertRaisesRegex(ValueError, 'Async clipboard prepared source hash mismatch'):
            self.helper().capture('editor', self.payload('editor'), source, out, env=self.env)
        self.assertFalse(out.exists())

    def test_capture_rejects_mutated_async_clipboard_lifecycle_before_output(self):
        source = self.source()
        target = source/'third_party/rhwp/rhwp-studio/src/engine/input-handler.ts'
        target.write_bytes(target.read_bytes()+b'// removed context invalidation\n')
        out = self.root/'changed-async-lifecycle'
        with self.assertRaisesRegex(ValueError, 'Async clipboard prepared source hash mismatch'):
            self.helper().capture('cli', self.payload('cli'), source, out, env=self.env)
        self.assertFalse(out.exists())

    def test_async_clipboard_files_are_captured_with_the_ledger_after_hashes(self):
        c = self.helper()
        source = self.source()
        _, contract = c.source_contract(source, c.configured())
        ledger = c.read_json(source/'.opengeul-overlay.json')
        for filename in ('input-handler-keyboard.ts', 'input-handler.ts'):
            name = 'third_party/rhwp/rhwp-studio/src/engine/'+filename
            self.assertIn(name, contract['preparedFiles'])
            self.assertEqual(contract['preparedFiles'][name], digest(source/name))
            self.assertEqual(ledger['asyncClipboardGuard']['afterSha256'][filename], contract['preparedFiles'][name])

    def test_pdf_root_geometry_and_original_licenses_bind_both_worker_inputs(self):
        c = self.helper()
        source = self.source()
        _, contract = c.source_contract(source, c.configured())
        ledger = c.read_json(source/'.opengeul-overlay.json')
        self.assertEqual(contract['pdfSearchText'], ledger['pdfSearchText'])
        for name in pdf_search_text.SOURCE_FILES:
            self.assertEqual(contract['preparedFiles'][name], digest(source/name))
            if '/src/' in name:
                self.assertEqual(contract['coreSourceFiles'][name], digest(source/name))

    def test_rehashed_pdf_source_and_ledger_cannot_authorize_capture(self):
        c = self.helper()
        source = self.source()
        ledger_path = source/'.opengeul-overlay.json'
        ledger = c.read_json(ledger_path)
        target = source/pdf_search_text.PDF
        target.write_bytes(target.read_bytes()+b'// arbitrary changed PDF behavior\n')
        ledger['pdfSearchText']['afterSha256'] = dict(ledger['pdfSearchText']['afterSha256'])
        ledger['pdfSearchText']['afterSha256'][pdf_search_text.PDF] = digest(target)
        write_json(ledger_path, ledger)
        out = self.root/'forged-pdf-capture'
        with self.assertRaisesRegex(ValueError, 'PDF search text pinned source proof mismatch'):
            c.capture('cli', self.payload('cli'), source, out, env=self.env)
        self.assertFalse(out.exists())

    def test_matching_workers_cannot_join_with_coordinated_pdf_hash_forgery(self):
        folders = self.pair()
        for folder in folders.values():
            path = folder/'provenance.json'
            value = json.loads(path.read_bytes())
            proof = value['source']['pdfSearchText']
            proof['afterSha256'][pdf_search_text.PDF] = '0'*64
            value['source']['preparedFiles'][pdf_search_text.PDF] = '0'*64
            value['source']['coreSourceFiles'][pdf_search_text.PDF] = '0'*64
            write_json(path, value)
        self.assert_rejected_without_outputs(folders, 'PDF search text pinned source proof mismatch')

    def test_menu_clipboard_final_engine_native_and_helper_bytes_are_owned(self):
        c = self.helper()
        source = self.source()
        _, contract = c.source_contract(source, c.configured())
        ledger = c.read_json(source/'.opengeul-overlay.json')
        self.assertEqual(contract['menuClipboardPaste'], ledger['menuClipboardPaste'])
        for name in (*menu_clipboard.SOURCE_FILES, menu_clipboard.HELPER):
            self.assertEqual(contract['preparedFiles'][name], digest(source/name))
        self.assertEqual(ledger['menuClipboardPaste']['hwpxPatcherSha256'], digest(ROOT/'scripts/prepare_hwpx.py'))

    def test_rehashed_menu_native_source_and_proof_cannot_authorize_capture(self):
        c = self.helper()
        source = self.source()
        target = source/menu_clipboard.LIB
        target.write_bytes(target.read_bytes()+b'// arbitrary clipboard builder change\n')
        ledger_path = source/'.opengeul-overlay.json'
        ledger = c.read_json(ledger_path)
        ledger['menuClipboardPaste']['afterSha256'][menu_clipboard.LIB] = digest(target)
        write_json(ledger_path, ledger)
        out = self.root/'forged-menu-capture'
        with self.assertRaisesRegex(ValueError, 'Menu clipboard reviewed output proof mismatch'):
            c.capture('editor', self.payload('editor'), source, out, env=self.env)
        self.assertFalse(out.exists())

    def test_matching_workers_cannot_join_coordinated_menu_builder_forgery(self):
        folders = self.pair()
        for folder in folders.values():
            path = folder/'provenance.json'
            value = json.loads(path.read_bytes())
            value['source']['menuClipboardPaste']['afterSha256'][menu_clipboard.LIB] = '0'*64
            value['source']['preparedFiles'][menu_clipboard.LIB] = '0'*64
            write_json(path, value)
        self.assert_rejected_without_outputs(folders, 'Menu clipboard reviewed output proof mismatch')

    def test_menu_clipboard_requires_the_reviewed_hwpx_transform_before_capture(self):
        c = self.helper()
        source = self.source()
        ledger_path = source/'.opengeul-overlay.json'
        ledger = c.read_json(ledger_path)
        ledger['menuClipboardPaste']['afterSha256'] = dict(menu_clipboard.PHASE_SOURCE_SHA256['prepared'])
        ledger['menuClipboardPaste']['hwpxPatcherSha256'] = None
        write_json(ledger_path, ledger)
        out = self.root/'premature-menu-capture'
        with self.assertRaisesRegex(ValueError, 'Menu clipboard reviewed output proof mismatch'):
            c.capture('cli', self.payload('cli'), source, out, env=self.env)
        self.assertFalse(out.exists())

    def test_image_insertion_files_and_shared_handler_bind_final_prepared_bytes(self):
        c = self.helper()
        source = self.source()
        _, contract = c.source_contract(source, c.configured())
        ledger = c.read_json(source/'.opengeul-overlay.json')
        for filename in ('command/commands/insert.ts', 'engine/input-handler.ts'):
            name = 'third_party/rhwp/rhwp-studio/src/'+filename
            self.assertIn(name, contract['preparedFiles'])
            self.assertEqual(contract['preparedFiles'][name], digest(source/name))
            self.assertEqual(ledger['imageInsertionGuard']['afterSha256'][filename], contract['preparedFiles'][name])
        self.assertEqual(ledger['asyncClipboardGuard']['afterSha256']['input-handler.ts'],
                         ledger['imageInsertionGuard']['afterSha256']['engine/input-handler.ts'])

    def test_async_font_selection_files_bind_actual_provider_and_final_shared_bytes(self):
        c = self.helper()
        source = self.source()
        _, contract = c.source_contract(source, c.configured())
        ledger = c.read_json(source/'.opengeul-overlay.json')
        for name in FONT_SOURCE_PINS:
            with self.subTest(file=name):
                self.assertIn(name, contract['preparedFiles'])
                self.assertEqual(contract['preparedFiles'][name], digest(source/name))
                self.assertEqual(ledger['asyncFontSelectionGuard']['afterSha256'][name], contract['preparedFiles'][name])
        handler = 'third_party/rhwp/rhwp-studio/src/engine/input-handler.ts'
        self.assertEqual(ledger['asyncFontSelectionGuard']['afterSha256'][handler],
                         ledger['imageInsertionGuard']['afterSha256']['engine/input-handler.ts'])

    def test_capture_rejects_mutated_async_font_provider_before_output(self):
        source = self.source()
        payload = self.payload('editor')
        for name in ('apps/studio-host/src/main.ts', 'apps/studio-host/src/ui/toolbar.ts'):
            with self.subTest(file=name):
                target = source/name
                original = target.read_bytes()
                target.write_bytes(original+b'// removed actual font context provider\n')
                out = self.root/('changed-font-'+target.name)
                with self.assertRaisesRegex(ValueError, 'Async font selection prepared source hash mismatch'):
                    self.helper().capture('editor', payload, source, out, env=self.env)
                self.assertFalse(out.exists())
                target.write_bytes(original)

    def test_incomplete_or_forged_async_font_ledger_cannot_authorize_capture(self):
        c = self.helper()
        source = self.source()
        path = source/'.opengeul-overlay.json'
        original = c.read_json(path)
        payload = self.payload('editor')
        for change in ('missing', 'missing-before', 'missing-after', 'forged-before', 'forged-after', 'extra-file', 'extra-field'):
            with self.subTest(change=change):
                ledger = copy.deepcopy(original)
                guard = ledger['asyncFontSelectionGuard']
                if change == 'missing': del ledger['asyncFontSelectionGuard']
                elif change == 'missing-before': del guard['beforeSha256']
                elif change == 'missing-after': del guard['afterSha256']['apps/studio-host/src/main.ts']
                elif change == 'forged-before': guard['beforeSha256']['apps/studio-host/src/main.ts'] = '0'*64
                elif change == 'forged-after': guard['afterSha256']['apps/studio-host/src/main.ts'] = '0'*64
                elif change == 'extra-field': guard['unreviewed'] = True
                else: guard['afterSha256']['unreviewed.ts'] = '0'*64
                write_json(path, ledger)
                out = self.root/('invalid-font-'+change)
                with self.assertRaises(ValueError):
                    c.capture('editor', payload, source, out, env=self.env)
                self.assertFalse(out.exists())
        write_json(path, original)

    def test_matching_workers_with_forged_async_font_hashes_cannot_join(self):
        folders = self.pair()
        for folder in folders.values():
            path = folder/'provenance.json'
            value = json.loads(path.read_bytes())
            value['source']['preparedFiles']['apps/studio-host/src/main.ts'] = '0'*64
            write_json(path, value)
        self.assert_rejected_without_outputs(folders, 'Async font selection prepared source hash mismatch')

    def test_rehashed_forged_async_font_ledger_cannot_join_matching_workers(self):
        folders = self.pair()
        parity_path = folders['editor']/'source-parity.json'
        ledger = json.loads(parity_path.read_bytes())
        ledger['asyncFontSelectionGuard']['afterSha256']['apps/studio-host/src/main.ts'] = '0'*64
        write_json(parity_path, ledger)
        for role, folder in folders.items():
            path = folder/'provenance.json'
            value = json.loads(path.read_bytes())
            value['source']['ledgerSha256'] = digest(parity_path)
            if role == 'editor':
                value['files']['source-parity.json'] = {'size': parity_path.stat().st_size, 'sha256': digest(parity_path)}
            write_json(path, value)
        self.assert_rejected_without_outputs(folders, 'Async font selection prepared source hash mismatch')

    def test_capture_rejects_mutated_image_insertion_before_output(self):
        source = self.source()
        target = source/'third_party/rhwp/rhwp-studio/src/command/commands/insert.ts'
        target.write_bytes(target.read_bytes()+b'// removed image ownership\n')
        out = self.root/'changed-image-insertion'
        with self.assertRaisesRegex(ValueError, 'Image insertion prepared source hash mismatch'):
            self.helper().capture('editor', self.payload('editor'), source, out, env=self.env)
        self.assertFalse(out.exists())

    def test_incomplete_or_forged_image_insertion_ledger_cannot_authorize_capture(self):
        c = self.helper()
        source = self.source()
        path = source/'.opengeul-overlay.json'
        original = c.read_json(path)
        payload = self.payload('editor')
        for change in ('missing', 'missing-before', 'missing-after', 'forged-before', 'forged-after', 'extra-file'):
            with self.subTest(change=change):
                ledger = copy.deepcopy(original)
                guard = ledger['imageInsertionGuard']
                if change == 'missing': del ledger['imageInsertionGuard']
                elif change == 'missing-before': del guard['beforeSha256']
                elif change == 'missing-after': del guard['afterSha256']['engine/input-handler.ts']
                elif change == 'forged-before': guard['beforeSha256']['command/commands/insert.ts'] = '0'*64
                elif change == 'forged-after': guard['afterSha256']['command/commands/insert.ts'] = '0'*64
                else: guard['afterSha256']['unreviewed.ts'] = '0'*64
                write_json(path, ledger)
                out = self.root/('invalid-image-'+change)
                with self.assertRaises(ValueError):
                    c.capture('editor', payload, source, out, env=self.env)
                self.assertFalse(out.exists())
        write_json(path, original)

    def test_matching_workers_with_forged_image_insertion_hashes_cannot_join(self):
        folders = self.pair()
        filename = 'third_party/rhwp/rhwp-studio/src/command/commands/insert.ts'
        for folder in folders.values():
            path = folder/'provenance.json'
            value = json.loads(path.read_bytes())
            value['source']['preparedFiles'][filename] = '0'*64
            write_json(path, value)
        self.assert_rejected_without_outputs(folders, 'Image insertion prepared source hash mismatch')

    def test_rehashed_forged_image_insertion_ledger_cannot_join_matching_workers(self):
        folders = self.pair()
        parity_path = folders['editor']/'source-parity.json'
        ledger = json.loads(parity_path.read_bytes())
        ledger['imageInsertionGuard']['afterSha256']['command/commands/insert.ts'] = '0'*64
        write_json(parity_path, ledger)
        for role, folder in folders.items():
            path = folder/'provenance.json'
            value = json.loads(path.read_bytes())
            value['source']['ledgerSha256'] = digest(parity_path)
            if role == 'editor':
                value['files']['source-parity.json'] = {'size': parity_path.stat().st_size, 'sha256': digest(parity_path)}
            write_json(path, value)
        self.assert_rejected_without_outputs(folders, 'Image insertion prepared source hash mismatch')

    def test_incomplete_or_forged_async_clipboard_ledger_cannot_authorize_capture(self):
        c = self.helper()
        source = self.source()
        path = source/'.opengeul-overlay.json'
        original = c.read_json(path)
        payload = self.payload('editor')
        for change in ('missing', 'missing-before', 'missing-after', 'forged-before', 'forged-after', 'extra-file'):
            with self.subTest(change=change):
                ledger = copy.deepcopy(original)
                guard = ledger['asyncClipboardGuard']
                if change == 'missing': del ledger['asyncClipboardGuard']
                elif change == 'missing-before': del guard['beforeSha256']
                elif change == 'missing-after': del guard['afterSha256']['input-handler.ts']
                elif change == 'forged-before': guard['beforeSha256']['input-handler-keyboard.ts'] = '0'*64
                elif change == 'forged-after': guard['afterSha256']['input-handler.ts'] = '0'*64
                else: guard['afterSha256']['unreviewed.ts'] = '0'*64
                write_json(path, ledger)
                out = self.root/('invalid-async-'+change)
                with self.assertRaises(ValueError):
                    c.capture('editor', payload, source, out, env=self.env)
                self.assertFalse(out.exists())
        write_json(path, original)

    def test_matching_workers_with_forged_async_file_hashes_cannot_join(self):
        folders = self.pair()
        filename = 'third_party/rhwp/rhwp-studio/src/engine/input-handler-keyboard.ts'
        for folder in folders.values():
            path = folder/'provenance.json'
            value = json.loads(path.read_bytes())
            value['source']['preparedFiles'][filename] = '0'*64
            write_json(path, value)
        # The additive menu contract now rejects this shared keyboard at the
        # component boundary, before the older parity-ledger guard runs.
        self.assert_rejected_without_outputs(folders, 'Menu clipboard prepared source proof mismatch')

    def test_rehashed_forged_async_ledger_cannot_join_matching_workers(self):
        folders = self.pair()
        parity_path = folders['editor']/'source-parity.json'
        ledger = json.loads(parity_path.read_bytes())
        ledger['asyncClipboardGuard']['afterSha256']['input-handler.ts'] = '0'*64
        write_json(parity_path, ledger)
        for role, folder in folders.items():
            path = folder/'provenance.json'
            value = json.loads(path.read_bytes())
            value['source']['ledgerSha256'] = digest(parity_path)
            if role == 'editor':
                value['files']['source-parity.json'] = {'size': parity_path.stat().st_size, 'sha256': digest(parity_path)}
            write_json(path, value)
        self.assert_rejected_without_outputs(folders, 'Async clipboard prepared source hash mismatch')

    def test_product_information_is_bound_to_the_reviewed_copied_overlay(self):
        c = self.helper()
        name = 'apps/studio-host/src/ui/about-dialog.ts'
        self.assertEqual(c.COPIED_OVERLAYS.get(name), 'overlay/about-dialog.ts')
        self.assertIn(name, c.SOURCE_FILES)
        source = self.source()
        path = source/name
        path.write_bytes(path.read_bytes().replace(b'allenlim@allenlim.net', b'wrong@example.invalid'))
        output = self.root/'wrong-product-contact'
        with self.assertRaisesRegex(ValueError, 'overlay helper mismatch'):
            c.capture('editor', self.payload('editor'), source, output, env=self.env)
        self.assertFalse(output.exists())

    def test_workers_with_different_host_visibility_css_cannot_join(self):
        c = self.helper()
        source = self.source()
        style = source/'apps/studio-host/src/style.css'
        style.parent.mkdir(parents=True, exist_ok=True)
        style.write_text('.md-item { display: flex; }\n', encoding='utf-8')
        folders = {role: self.root/(role+'-component') for role in ('editor', 'cli')}
        c.capture('editor', self.payload('editor'), source, folders['editor'], env=self.env)
        style.write_text('.md-item { display: flex; }\n.md-item[hidden] { display: none; }\n', encoding='utf-8')
        c.capture('cli', self.payload('cli'), source, folders['cli'], env=self.env)
        self.assert_rejected_without_outputs(folders)

    def test_workers_with_different_password_replacement_loaders_cannot_join(self):
        c = self.helper()
        source = self.source()
        loader = source/'apps/studio-host/src/core/document-open.ts'
        loader.write_text('export const replacement = "before password guard";\n', encoding='utf-8')
        folders = {role: self.root/(role+'-component') for role in ('editor', 'cli')}
        c.capture('editor', self.payload('editor'), source, folders['editor'], env=self.env)
        loader.write_text('export const replacement = "guard before every password load";\n', encoding='utf-8')
        c.capture('cli', self.payload('cli'), source, folders['cli'], env=self.env)
        self.assert_rejected_without_outputs(folders)

    def test_missing_password_replacement_loader_fails_before_capture_output(self):
        c = self.helper()
        source = self.source()
        loader = source/'apps/studio-host/src/core/document-open.ts'
        loader.write_text('owned loader fixture\n', encoding='utf-8')
        loader.unlink()
        out = self.root/'missing-password-loader'
        with self.assertRaises(FileNotFoundError):
            c.capture('editor', self.payload('editor'), source, out, env=self.env)
        self.assertFalse(out.exists())

    def test_unchanged_password_loader_hash_is_retained_through_component_join(self):
        c = self.helper()
        source = self.source()
        name = 'apps/studio-host/src/core/document-open.ts'
        loader = source/name
        loader.write_text('export const replacement = "unchanged guarded loader";\n', encoding='utf-8')
        folders = {role: self.root/(role+'-component') for role in ('editor', 'cli')}
        for role in folders:
            c.capture(role, self.payload(role), source, folders[role], env=self.env)
            metadata = json.loads((folders[role]/'provenance.json').read_bytes())
            self.assertEqual(metadata['source']['preparedFiles'][name], digest(loader))
        self.combine(folders)
        self.assertTrue((self.root/'combined/OpenGeul.exe').is_file())
        self.assertTrue((self.root/'combined/Tools/rhwp.exe').is_file())

    def test_previous_save_ledger_without_password_replacement_guard_is_rejected(self):
        c = self.helper()
        source = self.source()
        path = source/'.opengeul-overlay.json'
        ledger = json.loads(path.read_text())
        ledger['extendedFiles'] = ['commands.rs','state.rs','lib.rs','tauri-bridge.ts','main.ts','file.ts','desktop-events.ts','edit.ts']
        write_json(path, ledger)
        out = self.root/'old-password-ledger'
        with self.assertRaisesRegex(ValueError, 'overlay ledger'):
            c.capture('editor', self.payload('editor'), source, out, env=self.env)
        self.assertFalse(out.exists())

    def test_previous_save_ledger_without_cut_document_guard_is_rejected(self):
        c = self.helper()
        source = self.source()
        path = source/'.opengeul-overlay.json'
        ledger = json.loads(path.read_text())
        ledger['extendedFiles'].remove('edit.ts')
        write_json(path, ledger)
        out = self.root/'old-cut-ledger'
        with self.assertRaisesRegex(ValueError, 'overlay ledger'):
            c.capture('editor', self.payload('editor'), source, out, env=self.env)
        self.assertFalse(out.exists())

    def test_previous_save_ledger_without_close_cancellation_is_rejected(self):
        c = self.helper()
        source = self.source()
        path = source/'.opengeul-overlay.json'
        ledger = json.loads(path.read_text())
        ledger['extendedFiles'].remove('desktop-events.ts')
        write_json(path, ledger)
        out = self.root/'old-ledger'
        with self.assertRaisesRegex(ValueError, 'overlay ledger'):
            c.capture('editor', self.payload('editor'), source, out, env=self.env)
        self.assertFalse(out.exists())

    def test_windows_crlf_composition_retains_logical_ledger_and_raw_source_hash(self):
        c = self.helper()
        source = self.source()
        path = source/'third_party/rhwp/rhwp-studio/src/engine/input-handler-text.ts'
        path.write_bytes(path.read_text(encoding='utf-8').encode('utf-8').replace(b'\n', b'\r\n'))
        out = self.root/'crlf-component'
        c.capture('editor', self.payload('editor'), source, out, env=self.env)
        value = json.loads((out/'provenance.json').read_text())
        ledger = json.loads((out/'source-parity.json').read_text())
        self.assertEqual(value['source']['compositionTextSha256'], ledger['compositionFix']['afterSha256'])
        self.assertEqual(value['source']['preparedFiles'][path.relative_to(source).as_posix()], digest(path))
        self.assertNotEqual(value['source']['compositionTextSha256'], digest(path))

    def test_git_heads_must_be_exact_pinned_upstream_commits(self):
        c = self.helper()
        source = self.source()
        payload = self.payload('cli')
        for folder in (source, source/'third_party/rhwp'):
            with self.subTest(folder=folder):
                head = folder/'.git/HEAD'
                original = head.read_bytes()
                head.write_text('d'*40+'\n')
                with self.assertRaisesRegex(ValueError, 'git HEAD'):
                    c.capture('cli', payload, source, self.root/'wrong-head', env=self.env)
                self.assertFalse((self.root/'wrong-head').exists())
                head.write_bytes(original)

    def test_identically_forged_wasm_records_fail_local_source_binding(self):
        folders = self.pair()
        parity_path = folders['editor']/'source-parity.json'
        parity = json.loads(parity_path.read_text())
        parity['wasmRebuild']['namespacePatcher'] = '0'*64
        write_json(parity_path, parity)
        for role in folders:
            path = folders[role]/'provenance.json'
            value = json.loads(path.read_text())
            value['source']['wasmRebuild'] = parity['wasmRebuild']
            value['source']['ledgerSha256'] = digest(parity_path)
            if role == 'editor':
                value['files']['source-parity.json'] = {'size': parity_path.stat().st_size, 'sha256': digest(parity_path)}
            write_json(path, value)
        self.assert_rejected_without_outputs(folders, 'WASM')

    def test_unsafe_windows_paths_case_collisions_and_symlinks_are_rejected(self):
        c = self.helper()
        # JSON can carry a conflicting Windows name even when NTFS cannot create
        # two case-insensitive files or literal reserved/backslash names. Exercise
        # the real consumer before staging rather than overwrite valid payloads.
        folders = self.pair()
        provenance = folders['editor']/'provenance.json'
        original = json.loads(provenance.read_text())
        for name in ('payload/opengeul.exe', 'payload/CON.dll', 'payload/COM¹.dll',
                     'payload/COM².dll', 'payload/LPT³.dll', 'payload/bad:name.dll',
                     'payload/bad\\name.dll', 'payload/trailing .dll '):
            with self.subTest(inventoryName=name):
                value = copy.deepcopy(original)
                value['files'][name] = value['files']['payload/OpenGeul.exe']
                write_json(provenance, value)
                self.assert_rejected_without_outputs(folders, 'inventory|path')
        source = self.root/'hop'
        payload = self.root/'editor-payload'
        link = payload/'Notices/link.txt'
        try:
            link.symlink_to(payload/'Notices/OpenGeul-LICENSE.txt')
        except (OSError, NotImplementedError):
            self.skipTest('Host cannot create symlinks')
        with self.assertRaisesRegex(ValueError, 'symlink|regular'):
            c.capture('editor', payload, source, self.root/'bad-link', env=self.env)

    def test_recomputed_manifest_cannot_authorize_traversal_or_extra_payload(self):
        folders = self.pair()
        path = folders['cli']/'provenance.json'
        value = json.loads(path.read_text())
        value['files']['../escape.exe'] = {'size': 256, 'sha256': '0'*64}
        write_json(path, value)
        self.assert_rejected_without_outputs(folders, 'path|inventory')

    def test_windows_crlf_native_manifest_retains_registration_and_raw_hash(self):
        c = self.helper()
        source = self.source()
        path = source/'third_party/rhwp/Cargo.toml'
        path.write_bytes(path.read_text(encoding='utf-8').encode('utf-8').replace(b'\n', b'\r\n'))
        out = self.root/'crlf-native'
        c.capture('cli', self.payload('cli'), source, out, env=self.env)
        value = json.loads((out/'provenance.json').read_text())
        self.assertEqual(value['source']['preparedFiles']['third_party/rhwp/Cargo.toml'], digest(path))

    def test_caps_are_checked_at_capture_and_join(self):
        c = self.helper()
        source = self.source()
        payload = self.payload('cli')
        with patch.dict(c.CAPS, {'cli': 128}):
            with self.assertRaisesRegex(ValueError, 'cap'):
                c.capture('cli', payload, source, self.root/'too-large', env=self.env)
        payload.rename(self.root/'unused-cli-payload')
        folders = self.pair_from_source(source)
        with patch.dict(c.CAPS, {'cli': 128}):
            self.assert_rejected_without_outputs(folders, 'cap')

    def pair_from_source(self, source):
        folders = {}
        for role in ('editor', 'cli'):
            folders[role] = self.root/(role+'-component')
            self.helper().capture(role, self.payload(role), source, folders[role], env=self.env)
        return folders

    def test_existing_destinations_and_symlink_ancestors_are_never_overwritten(self):
        folders = self.pair()
        output = self.root/'combined'
        output.mkdir()
        (output/'sentinel').write_text('keep')
        with self.assertRaises(ValueError):
            self.combine(folders)
        self.assertEqual((output/'sentinel').read_text(), 'keep')
        self.assertFalse((self.root/'package-source').exists())

    def test_destination_symlink_ancestor_is_rejected_before_any_output(self):
        folders = self.pair()
        actual = self.root/'actual'
        actual.mkdir()
        link = self.root/'alias'
        try:
            link.symlink_to(actual, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('Host cannot create symlinks')
        with self.assertRaisesRegex(ValueError, 'symlink|reparse'):
            self.helper().combine(folders['editor'], folders['cli'], link/'payload',
                                  self.root/'package-source', env=self.env)
        self.assertEqual(list(actual.iterdir()), [])
        self.assertFalse((self.root/'package-source').exists())


if __name__ == '__main__':
    unittest.main()
