"""Synthetic material + actual PDF/PNG reader; no Windows/legacy download."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'ci'), str(ROOT / 'e2e'), str(ROOT / 'e2e/print_tests'), str(ROOT / 'scripts')]
import paired_print_evidence as api
import paired_print_contract as core
import paired_print_collect as exporter
import print_raster
from paired_print_windows import read_single_raster
import test_paired_renderer_admission as fixture_data
from test_paired_pair_contract import Port, font_state


class PairedPrintEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / 'workspace'
        self.workspace.mkdir()
        self.work = self.workspace / 'paired-private-attempts'
        self.output = self.workspace / 'paired-print-evidence'
        self.source, self.run_id, self.attempt = 'a' * 40, 17, 1
        f = fixture_data.RendererAdmissionTests()
        f.setUp()
        self.value, self.wasm_source = copy.deepcopy(f.value), copy.deepcopy(f.wasm_source)
        for name in ('paired-current-runtime', 'package', 'wasm-input', 'print-fixtures', 'inputs/e2e-fixtures'):
            (self.workspace / name).mkdir(parents=True)
        exe = b'EXPLICIT-SYNTHETIC-CURRENT-BINARY'
        (self.workspace / 'paired-current-runtime/OpenGeul.exe').write_bytes(exe)
        component = self.value['windowsComponents']['components']['editor']
        component['sha256'], component['size'] = hashlib.sha256(exe).hexdigest(), len(exe)
        (self.workspace / 'package/current.msix').write_bytes(b'EXPLICIT-SYNTHETIC-ARCHIVE')
        (self.workspace / 'package/current-portable.zip').write_bytes(b'EXPLICIT-SYNTHETIC-ARCHIVE')
        self.value['sha256'] = hashlib.sha256((self.workspace / 'package/current.msix').read_bytes()).hexdigest()
        wasm = self.value['sourceParity']['wasmRebuild']
        for name in api.WASM_FILES:
            data = b'\0asm\1\0\0\0' if name == 'rhwp_bg.wasm' else b'SYNTHETIC-' + name.encode('ascii')
            if name == 'package.json': data = json.dumps({'version': '0.9.0'}).encode()
            (self.workspace / 'wasm-input' / name).write_bytes(data)
            wasm['artifacts'][name] = hashlib.sha256(data).hexdigest()
        (self.workspace / 'wasm-input/OPEN_GEUL_WASM.json').write_text(json.dumps(wasm))
        self.update_package()
        self.fixtures = []
        for code, _, name in api.CASES:
            data = b'EXPLICIT-SYNTHETIC-FIXTURE-' + bytes([code])
            (self.workspace / name).write_bytes(data)
            self.fixtures.append({'caseCode': code, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)})
        self.expected = core.expected_renderers(harness_source=self.source, run_id=17, attempt=1,
            current_editor_sha256=component['sha256'], current_editor_bytes=len(exe),
            current_wasm_sha256=wasm['artifacts']['rhwp_bg.wasm'], current_js_sha256=wasm['artifacts']['rhwp.js'])
        port = Port()
        port.oracle_passed = True
        self.report = core.run_comparison(self.expected, self.fixtures, port)
        self.profiles = []
        from reportlab.pdfgen.canvas import Canvas
        import pypdfium2 as pdfium
        reference = None
        for row in self.report['observations']:
            role, code = row['roleCode'], row['caseCode']
            folder = self.work / f'role-{role}-case-{code}'
            (folder / 'pdf-check').mkdir(parents=True)
            pdf = folder / 'printed.pdf'
            canvas = Canvas(str(pdf), pagesize=(595.28, 841.86))
            canvas.rect(80, 700, 70, 30, fill=1)
            canvas.save()
            reading = read_single_raster(pdf, {'pages': [{'size_pt': [595.28, 841.86]}]})
            row['raster'], row['pdfSha256'], row['pdfBytes'] = reading['raster'], reading['pdfSha256'], reading['pdfBytes']
            with pdfium.PdfDocument(pdf) as document:
                page = document[0]
                bitmap = page.render(scale=3)
                try: bitmap.to_pil().convert('L').save(folder / 'pdf-check/page-1.png')
                finally: bitmap.close(); page.close()
            png = (folder / 'pdf-check/page-1.png').read_bytes()
            row['pngSha256'], row['pngBytes'] = hashlib.sha256(png).hexdigest(), len(png)
            reference = reading['raster']
            self.profiles.append({'roleCode': role, 'caseCode': code, 'scopeCode': 1,
                'actualSelectedProfileKnown': False, 'volume': 1, 'fileId': role * 10 + code, 'createdNs': 300})
        self.book = self.root / 'synthetic-reference.json'
        self.book.write_text(json.dumps({'schema': 1, 'scale': 3, 'sourceRun': 'synthetic-only',
            'productCommit': 'synthetic-only', 'cases': {n: [reference] for _, n, _ in api.CASES}}))
        for patcher in (mock.patch.object(print_raster, 'REFERENCE', self.book),
                        mock.patch.object(api, 'check_legacy', return_value=None),  # authentic legacy payload is absent
                        mock.patch.object(api, 'wasm_expected', return_value=self.wasm_source)):
            patcher.start()
            self.addCleanup(patcher.stop)
        exporter.collect(self.work, self.output, self.report, self.profiles)

    def update_package(self):
        (self.workspace / 'package/provenance.json').write_text(json.dumps(self.value))
        files = sorted(p for p in (self.workspace / 'package').iterdir() if p.name != 'SHA256SUMS.txt')
        (self.workspace / 'package/SHA256SUMS.txt').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + p.name + '\n' for p in files))

    def change_metadata(self, mutate):
        p = self.output / 'comparison.numeric.json'
        value = json.loads(p.read_bytes())
        mutate(value)
        p.write_text(json.dumps(value))

    def verify(self, source=None, run_id=None, attempt=None):
        return api.verify(self.workspace, source or self.source, run_id or self.run_id,
                          attempt or self.attempt, font_reader=font_state)

    def test_complete_pair_is_admitted_only_as_nonqualification_evidence(self):
        result = self.verify()
        self.assertTrue(result['admitted'])
        self.assertEqual(result['files'], 9)
        self.assertFalse(result['qualification'])
        self.assertFalse(result['acceptanceEligible'])

    def test_original_ink_failure_can_be_uploaded_without_becoming_success(self):
        book = json.loads(self.book.read_bytes())
        for value in book['cases'].values(): value[0]['maskSha256'] = '9' * 64
        self.book.write_text(json.dumps(book))
        def fail(m):
            for row in m['comparison']['observations']:
                row['originalOraclePassed'], row['primaryErrorCode'] = False, 1
            m['comparison']['originalOracleAllPassed'], m['comparison']['exitCode'] = False, 1
        self.change_metadata(fail)
        self.assertTrue(self.verify()['admitted'])
        self.assertEqual(json.loads((self.output / 'comparison.numeric.json').read_bytes())['comparison']['exitCode'], 1)

    def test_other_source_run_or_attempt_never_chooses_its_own_expected_binding(self):
        for kw in ({'source': 'b' * 40}, {'run_id': 18}, {'attempt': 2}):
            with self.subTest(kind=next(iter(kw))):
                with self.assertRaises(ValueError): self.verify(**kw)

    def test_changed_selected_fixture_is_rejected(self):
        (self.workspace / api.CASES[0][2]).write_bytes(b'CHANGED')
        with self.assertRaises(ValueError): self.verify()

    def test_changed_current_runtime_is_rejected(self):
        (self.workspace / 'paired-current-runtime/OpenGeul.exe').write_bytes(b'CHANGED')
        with self.assertRaises(ValueError): self.verify()

    def test_changed_current_wasm_is_rejected(self):
        (self.workspace / 'wasm-input/rhwp.js').write_bytes(b'CHANGED')
        with self.assertRaises(ValueError): self.verify()

    def test_declared_current_source_drift_is_rejected_even_with_fresh_checksums(self):
        self.value['commit'] = 'b' * 40
        self.update_package()
        with self.assertRaises(ValueError): self.verify()

    def test_unknown_or_raw_export_file_is_rejected(self):
        (self.output / 'process.log').write_bytes(b'NO-RAW-COLLECTION')
        with self.assertRaises(ValueError): self.verify()

    def test_unknown_metadata_key_or_qualification_claim_is_rejected(self):
        self.change_metadata(lambda m: m.update({'qualification': True}))
        with self.assertRaises(ValueError): self.verify()

    def test_unknown_retirement_or_effective_profile_claim_is_rejected(self):
        self.change_metadata(lambda m: m.update({'actualSelectedProfileKnown': True}))
        with self.assertRaises(ValueError): self.verify()

    def test_source_row_ownership_and_retirement_cannot_be_omitted(self):
        self.change_metadata(lambda m: m['comparison']['observations'][0].update({'retainedRootExited': False}))
        with self.assertRaises(ValueError): self.verify()

    def test_oracle_pass_claim_is_checked_against_the_actual_pdf(self):
        book = json.loads(self.book.read_bytes())
        for value in book['cases'].values(): value[0]['maskSha256'] = '9' * 64
        self.book.write_text(json.dumps(book))
        with self.assertRaises(ValueError): self.verify()

    def test_post_read_metadata_swap_is_rejected(self):
        original, calls = api.inspect_print_pdf, []
        def changed(*args):
            result = original(*args)
            calls.append(1)
            if len(calls) == 1:
                self.change_metadata(lambda m: m.update({'qualification': True}))
            return result
        with mock.patch.object(api, 'inspect_print_pdf', side_effect=changed):
            with self.assertRaises(ValueError): self.verify()

    def test_wrong_actual_exported_raster_is_rejected_even_after_hash_rewrite(self):
        from PIL import Image
        path = self.output / 'role-1-case-1.png'
        Image.new('L', (1786, 2526), 0).save(path)
        data = path.read_bytes()
        def change(m):
            row = m['files'][1]
            row['sha256'], row['bytes'] = hashlib.sha256(data).hexdigest(), len(data)
            m['comparison']['observations'][0]['pngSha256'] = row['sha256']
            m['comparison']['observations'][0]['pngBytes'] = row['bytes']
        self.change_metadata(change)
        with self.assertRaises(ValueError): self.verify()

    def test_freshly_checked_package_header_cannot_name_a_changed_actual_msix(self):
        (self.workspace / 'package/current.msix').write_bytes(b'CHANGED')
        self.update_package()
        with self.assertRaises(ValueError): self.verify()

    def test_single_hardlinked_export_is_rejected(self):
        import os
        os.link(self.output / 'role-1-case-1.pdf', self.root / 'hardlink')
        with self.assertRaises(ValueError): self.verify()

    def test_font_sample_change_during_replay_is_rejected(self):
        calls = []
        def changing():
            calls.append(1)
            result = font_state()
            if len(calls) > 1: result['files'][0]['sha256'] = '9' * 64
            return result
        with self.assertRaises(ValueError):
            api.verify(self.workspace, self.source, 17, 1, font_reader=changing)


class ParentPatchIsolationTests(unittest.TestCase):
    def test_fixture_cleanup_does_not_stop_an_unrelated_active_parent_patch(self):
        import types
        marker = types.SimpleNamespace(value=0)
        parent = mock.patch.object(marker, 'value', 1)
        parent.start()
        fixture = PairedPrintEvidenceTests('test_complete_pair_is_admitted_only_as_nonqualification_evidence')
        try:
            try: fixture.setUp()
            finally: fixture.doCleanups()
            self.assertEqual(marker.value, 1)
        finally: parent.stop()


if __name__ == '__main__': unittest.main()
