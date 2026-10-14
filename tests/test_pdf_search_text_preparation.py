"""Pinned, additive PDF root geometry preparation and transported source proof."""
from copy import deepcopy
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import pdf_search_text as pdf


def digest(data):
    return hashlib.sha256(data).hexdigest()


class PdfSearchTextPreparationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.source = Path(temp.name)
        self.texts = {
            pdf.LIB: ('use crate::render::{tree_to_stream, tree_to_xobject};\n'
                      'pub fn to_chunk(tree: &Tree, conversion_options: ConversionOptions) {\n'
                      '    tree_to_xobject(tree, chunk, ctx);\n}\n'),
            pdf.RENDER: ('pub fn tree_to_xobject(tree: &Tree, chunk: &mut Chunk, ctx: &mut Context) -> Result<Ref> {\n'
                         '    let bbox = tree.size().to_non_zero_rect(0.0, 0.0);\n'
                         '    x_object.bbox(bbox.to_pdf_rect());\n'
                         '    x_object.matrix([1.0 / bbox.width(), 0.0, 0.0, 1.0 / bbox.height(), 0.0, 0.0]);\n}\n'
                         '// nested SVG callers still use tree_to_xobject\n'),
            pdf.PDF: ('    opengeul_pdf_guard::enforce(&mut fontdb, svg_pages)?;\n'
                      '    svg2pdf::to_chunk(tree, conversion)\n'
                      '        content.transform([pd.width, 0.0, 0.0, pd.height, 0.0, 0.0]);\n'
                      '    opengeul_pdf_guard::reject_direct_export()?;\n'),
            pdf.PATCHES: '# Original upstream patch history\n',
        }
        self.original = {name: text.encode() for name, text in self.texts.items()}
        self.licenses = {name: ('Original license: '+name+'\n').encode()
                         for name in pdf.PRESERVED_SHA256}
        for name, data in {**self.original, **self.licenses}.items():
            path = self.source/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        # Replace only the immutable input/output references for this small,
        # owned fixture; execute the actual patching and validation functions.
        outputs = pdf.patched_texts(self.texts)
        for name, value in (
            ('SOURCE_SHA256', {n: digest(d) for n, d in self.original.items()}),
            ('PRESERVED_SHA256', {n: digest(d) for n, d in self.licenses.items()}),
            ('PATCHED_SHA256', {n: digest(t.encode()) for n, t in outputs.items()}),
        ):
            override = patch.object(pdf, name, value)
            override.start()
            self.addCleanup(override.stop)

    def inventory(self):
        files = {name: digest((self.source/name).read_bytes()) for name in pdf.SOURCE_FILES}
        core = {name: value for name, value in files.items() if '/src/' in name}
        helpers = {pdf.HELPER: digest((ROOT/pdf.HELPER).read_bytes())}
        return files, core, helpers

    def test_root_conversion_is_additive_and_font_policy_remains_enforced(self):
        proof = pdf.apply(self.source)
        lib = (self.source/pdf.LIB).read_text()
        self.assertIn(self.texts[pdf.LIB].split('\n', 1)[1], lib)
        self.assertIn('pub fn to_chunk_with_svg_size(', lib)
        render = (self.source/pdf.RENDER).read_text()
        self.assertIn('[1.0 / size.width(), 0.0, 0.0, 1.0 / size.height(), 0.0, 0.0]', render)
        self.assertIn('ctx, [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]', render)
        converted = (self.source/pdf.PDF).read_text()
        self.assertIn('svg2pdf::to_chunk_with_svg_size(tree, conversion)', converted)
        self.assertIn('content.transform([0.75, 0.0, 0.0, 0.75, 0.0, 0.0])', converted)
        self.assertIn('opengeul_pdf_guard::enforce(&mut fontdb, svg_pages)?', converted)
        self.assertIn('opengeul_pdf_guard::reject_direct_export()?', converted)
        for name, data in self.licenses.items():
            self.assertEqual((self.source/name).read_bytes(), data)
        self.assertTrue((self.source/pdf.PATCHES).read_text().startswith(self.texts[pdf.PATCHES]))
        pdf.validate(proof, *self.inventory())

    def test_tampered_source_or_license_is_rejected_before_any_write(self):
        for name in pdf.SOURCE_FILES:
            with self.subTest(name=name):
                path = self.source/name
                before = path.read_bytes()
                path.write_bytes(before + b'changed')
                snapshot = {n: (self.source/n).read_bytes() for n in pdf.SOURCE_FILES}
                with self.assertRaisesRegex(ValueError, 'pinned source|original license'):
                    pdf.apply(self.source)
                self.assertEqual(snapshot, {n: (self.source/n).read_bytes() for n in pdf.SOURCE_FILES})
                path.write_bytes(before)

    def test_unreviewed_patch_output_is_rejected_before_any_write(self):
        with patch.object(pdf, 'ADDITIVE_API', pdf.ADDITIVE_API + '\n// changed\n'):
            with self.assertRaisesRegex(ValueError, 'reviewed output'):
                pdf.apply(self.source)
        self.assertEqual(self.original, {n: (self.source/n).read_bytes() for n in self.original})

    def test_raw_crlf_and_bare_cr_source_drift_is_rejected_before_any_write(self):
        for name in self.original:
            for ending in (b'\r\n', b'\r'):
                with self.subTest(name=name, ending=ending):
                    path = self.source/name
                    path.write_bytes(self.original[name].replace(b'\n', ending))
                    snapshot = {n: (self.source/n).read_bytes() for n in pdf.SOURCE_FILES}
                    with self.assertRaisesRegex(ValueError, 'pinned source'):
                        pdf.apply(self.source)
                    self.assertEqual(snapshot, {n: (self.source/n).read_bytes() for n in pdf.SOURCE_FILES})
                    path.write_bytes(self.original[name])

    def test_twice_applied_patch_is_rejected_without_overwriting(self):
        pdf.apply(self.source)
        snapshot = {n: (self.source/n).read_bytes() for n in pdf.SOURCE_FILES}
        with self.assertRaisesRegex(ValueError, 'pinned source'):
            pdf.apply(self.source)
        self.assertEqual(snapshot, {n: (self.source/n).read_bytes() for n in pdf.SOURCE_FILES})

    def test_proof_and_both_source_inventories_reject_recoherent_tampering(self):
        proof = pdf.apply(self.source)
        files, core, helpers = self.inventory()
        for field in ('beforeSha256', 'afterSha256', 'preservedSha256'):
            for name in proof[field]:
                with self.subTest(field=field, name=name):
                    changed = deepcopy(proof)
                    changed[field][name] = '0'*64
                    with self.assertRaises(ValueError):
                        pdf.validate(changed, files, core, helpers)
        for inventory in (files, core):
            for name in inventory:
                with self.subTest(inventory='core' if inventory is core else 'prepared', name=name):
                    changed = dict(inventory)
                    changed[name] = '0'*64
                    arguments = (changed, core, helpers) if inventory is files else (files, changed, helpers)
                    with self.assertRaisesRegex(ValueError, 'source hash mismatch'):
                        pdf.validate(proof, *arguments)
        changed = deepcopy(proof)
        changed['afterSha256'][pdf.LIB] = '0'*64
        files[pdf.LIB] = core[pdf.LIB] = '0'*64
        with self.assertRaisesRegex(ValueError, 'pinned source proof'):
            pdf.validate(changed, files, core, helpers)

    def test_missing_or_extra_proof_fields_and_helper_mismatch_are_rejected(self):
        proof = pdf.apply(self.source)
        files, core, helpers = self.inventory()
        for key in proof:
            changed = deepcopy(proof)
            changed.pop(key)
            with self.assertRaisesRegex(ValueError, 'Invalid PDF'):
                pdf.validate(changed, files, core, helpers)
        for changed in ({**proof, 'qualification': True}, {**proof, 'formatVersion': True}):
            with self.assertRaisesRegex(ValueError, 'Invalid PDF'):
                pdf.validate(changed, files, core, helpers)
        with self.assertRaisesRegex(ValueError, 'helper mismatch'):
            pdf.validate(proof, files, core, {pdf.HELPER: '0'*64})


if __name__ == '__main__':
    unittest.main()
