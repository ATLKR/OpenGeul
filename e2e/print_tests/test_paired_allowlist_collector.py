import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FILE = ROOT / 'paired_print_collect.py'
if FILE.exists():
    spec = importlib.util.spec_from_file_location('paired_collect_candidate', FILE)
    api = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(api)
else:
    api = None
from test_paired_pair_contract import Port
import paired_print_contract as core


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(api, 'allowlist collector absent')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.work, self.out = self.root / 'private', self.root / 'allowlisted'
        self.work.mkdir()
        self.expected = core.expected_renderers(harness_source='a' * 40, run_id=17, attempt=1,
            current_editor_sha256='b' * 64, current_editor_bytes=300,
            current_wasm_sha256='c' * 64, current_js_sha256='d' * 64)
        self.fixtures = [{'caseCode': 1, 'sha256': 'e' * 64, 'bytes': 200},
                         {'caseCode': 6, 'sha256': 'f' * 64, 'bytes': 300}]
        port = Port()
        port.oracle_passed = True
        self.report = core.run_comparison(self.expected, self.fixtures, port)
        self.profiles = []
        from PIL import Image
        for role in (1, 2):
            for case in (1, 6):
                path = self.work / f'role-{role}-case-{case}'
                (path / 'pdf-check').mkdir(parents=True)
                (path / 'printed.pdf').write_bytes(b'%PDF-SYNTHETIC\n%%EOF')
                from PIL import ImageDraw
                image = Image.new('L', (1786, 2526), 255)
                ImageDraw.Draw(image).rectangle((264, 306, 325, 430), fill=0)
                image.save(path / 'pdf-check/page-1.png')
                import hashlib
                row = next(r for r in self.report['observations'] if (r['roleCode'], r['caseCode']) == (role, case))
                from print_raster import fingerprint
                row['raster'] = fingerprint(image)
                for key, file in (('pdf', path / 'printed.pdf'), ('png', path / 'pdf-check/page-1.png')):
                    data = file.read_bytes()
                    row[key + 'Sha256'], row[key + 'Bytes'] = hashlib.sha256(data).hexdigest(), len(data)
                (path / 'native-screen.png').write_bytes(b'NEVER-COLLECT')
                (path / 'process.log').write_bytes(b'NEVER-COLLECT')
                (path / 'session').mkdir()
                (path / 'session/trace.zip').write_bytes(b'NEVER-COLLECT')
                self.profiles.append({'roleCode': role, 'caseCode': case, 'scopeCode': 1,
                    'actualSelectedProfileKnown': False, 'volume': 1, 'fileId': role * 10 + case,
                    'createdNs': 300})

    def collect(self):
        return api.collect(self.work, self.out, self.report, self.profiles)

    def test_only_four_pdfs_four_rasters_and_numeric_receipt_leave_private_tree(self):
        result = self.collect()
        names = sorted(p.name for p in self.out.iterdir())
        self.assertEqual(len(names), 9)
        self.assertTrue(all(name.endswith(('.pdf', '.png', '.json')) for name in names))
        self.assertFalse(result['qualification'])
        self.assertFalse(result['actualSelectedProfileKnown'])
        self.assertFalse(result['actualSelectedFontIdentityKnown'])
        self.assertNotIn('NEVER-COLLECT', (self.out / 'comparison.numeric.json').read_text())

    def test_original_oracle_failure_remains_exit_one(self):
        row = self.report['observations'][0]
        row['primaryErrorCode'], row['originalOraclePassed'] = 1, False
        self.report['originalOracleAllPassed'], self.report['exitCode'] = False, 1
        self.assertEqual(self.collect()['comparison']['exitCode'], 1)

    def test_unknown_or_raw_report_field_is_rejected(self):
        self.report['rawError'] = 'SYNTHETIC-NEVER-COLLECT'
        with self.assertRaises(core.Rejected): self.collect()
        self.assertFalse(self.out.exists())

    def test_false_retirement_cannot_become_a_comparison_artifact(self):
        self.report['observations'][0]['retainedRootExited'] = False
        with self.assertRaises(core.Rejected): self.collect()

    def test_report_qualification_cannot_be_relabelled(self):
        self.report['qualification'] = True
        with self.assertRaises(core.Rejected): self.collect()

    def test_profile_intent_cannot_be_promoted_to_effective_profile(self):
        self.profiles[0]['actualSelectedProfileKnown'] = True
        with self.assertRaises(core.Rejected): self.collect()

    def test_missing_profile_prevents_complete_comparison(self):
        self.profiles.pop()
        with self.assertRaises(core.Rejected): self.collect()

    def test_hardlink_source_is_not_exported(self):
        import os
        source = self.work / 'role-1-case-1/printed.pdf'
        os.link(source, self.root / 'alias')
        with self.assertRaises(core.Rejected): self.collect()

    def test_oversized_png_is_rejected_before_export(self):
        source = self.work / 'role-1-case-1/pdf-check/page-1.png'
        with source.open('r+b') as stream: stream.truncate(8 * 1024 * 1024 + 1)
        with self.assertRaises(core.Rejected): self.collect()

    def test_existing_output_is_not_overwritten(self):
        self.out.mkdir()
        marker = self.out / 'do-not-overwrite'
        marker.write_bytes(b'UNCHANGED')
        with self.assertRaises(core.Rejected): self.collect()
        self.assertEqual(marker.read_bytes(), b'UNCHANGED')

    def test_pdf_swap_after_retirement_cannot_become_bound_evidence(self):
        (self.work / 'role-1-case-1/printed.pdf').write_bytes(b'%PDF-OTHER\n%%EOF')
        with self.assertRaises(core.Rejected): self.collect()

    def test_png_swap_after_retirement_cannot_become_bound_evidence(self):
        from PIL import Image
        Image.new('L', (1786, 2526), 0).save(self.work / 'role-1-case-1/pdf-check/page-1.png')
        with self.assertRaises(core.Rejected): self.collect()

    def test_ancillary_text_chunk_is_rejected_before_the_image_decoder(self):
        import hashlib
        from PIL import Image, PngImagePlugin
        path = self.work / 'role-1-case-1/pdf-check/page-1.png'
        with Image.open(path) as image:
            copy = image.copy()
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text('synthetic-only', 'DO-NOT-COLLECT-ANCILLARY-TEXT')
        copy.save(path, pnginfo=metadata)
        raw = path.read_bytes()
        row = self.report['observations'][0]
        row['pngSha256'], row['pngBytes'] = hashlib.sha256(raw).hexdigest(), len(raw)
        with self.assertRaises(core.Rejected): self.collect()


if __name__ == '__main__': unittest.main()
