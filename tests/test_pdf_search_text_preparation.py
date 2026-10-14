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
import pdf_font_resolution as fonts


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
                      '    options.fontdb = std::sync::Arc::new(fontdb);\n'
                      '    svg2pdf::to_chunk(tree, conversion)\n'
                      '        content.transform([pd.width, 0.0, 0.0, pd.height, 0.0, 0.0]);\n'
                      '    opengeul_pdf_guard::reject_direct_export()?;\n'),
            pdf.PATCHES: '# Original upstream patch history\n',
            pdf.SVG: ('fn draw_text() {\n'
                      '                let common_attrs = attrs_for_cluster(cluster_str, &color);\n'
                      '                // original positioned glyph emission\n}\n'),
            pdf.TEXT: ('fn write_font() {\n    let mut flags = FontFlags::empty();\n}\n'
                       'pub struct Font {\n    pub face_index: u32,\n}\n'
                       'fn render() {\n'
                       '            font_names\n'
                       '                .entry(font.reference)\n'
                       '                .or_insert_with(|| rc.add_font(font.reference));\n'
                       '                let name = font_names.get(&font.reference).unwrap();\n'
                       '                // original outline_transform, set_text_matrix and show remain\n}\n'
                       'fn fill_fonts() {\n'
                       '                                            face_index,\n'
                       '                            font.glyph_remapper.remap(g.id.0);\n}\n'),
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

    def owned_font_successor(self):
        proof = pdf.apply(self.source)
        for name, overlay in ((fonts.GUARD, 'opengeul_pdf_guard.rs'),
                              (fonts.POLICY, 'font_policy.rs')):
            path = self.source/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((ROOT/'overlay'/overlay).read_bytes())
        before = {name:digest((self.source/name).read_bytes()) for name in fonts.SOURCE_FILES}
        renderer = (self.source/fonts.PDF).read_bytes()
        anchor = b'    options.fontdb = std::sync::Arc::new(fontdb);\n'
        self.assertEqual(renderer.count(anchor), 1)
        final = renderer.replace(anchor, anchor +
                b'    options.font_resolver.select_font = opengeul_pdf_guard::installed_base_font_selector();\n')
        after = {**before, fonts.PDF:digest(final)}
        # Only immutable references for these small owned files are substituted;
        # both actual patchers and the actual source validators remain in use.
        for name, value in (('INPUT_SOURCE_SHA256', before), ('OUTPUT_SOURCE_SHA256', after)):
            override = patch.object(fonts, name, value)
            override.start(); self.addCleanup(override.stop)
        successor = fonts.apply(self.source)
        files, core, helpers = self.inventory()
        for name in fonts.SOURCE_FILES:
            files[name] = core[name] = digest((self.source/name).read_bytes())
        helpers[fonts.HELPER] = digest((ROOT/fonts.HELPER).read_bytes())
        return proof, successor, files, core, helpers

    def test_reviewed_font_successor_requires_explicit_handoff_and_actual_final_bytes(self):
        proof, successor, files, core, helpers = self.owned_font_successor()
        self.assertEqual(proof['afterSha256'][pdf.PDF], successor['beforeSha256'][pdf.PDF])
        self.assertNotEqual(proof['afterSha256'][pdf.PDF], files[pdf.PDF])
        self.assertEqual(files[pdf.PDF], successor['afterSha256'][pdf.PDF])
        with self.assertRaisesRegex(ValueError, 'PDF search text prepared source hash mismatch'):
            pdf.validate(proof, files, core, helpers)
        try:
            pdf.validate(proof, files, core, helpers, successor=successor)
        except TypeError as error:
            self.fail('Actual PDF validator cannot consume the reviewed successor stage: '+str(error))

    def test_font_successor_proof_helper_and_each_actual_dependency_are_strict(self):
        proof, successor, files, core, helpers = self.owned_font_successor()
        cases = [('missing-proof', None), ('extra-proof', None), ('helper', None),
                 ('current-helper', None), ('extra-before', None), ('extra-after', None)]
        cases += [(kind, name) for name in fonts.SOURCE_FILES
                  for kind in ('before', 'after', 'prepared', 'core', 'missing-prepared',
                               'missing-core', 'coherent-legacy')]
        for change, name in cases:
            next_proof = deepcopy(successor); prepared = dict(files)
            actual_core = dict(core); actual_helpers = dict(helpers)
            if change == 'missing-proof': next_proof = {}
            elif change == 'extra-proof': next_proof['optional'] = True
            elif change == 'helper': next_proof['helperSha256'] = '0'*64
            elif change == 'current-helper': actual_helpers[fonts.HELPER] = '0'*64
            elif change in ('extra-before', 'extra-after'):
                next_proof['beforeSha256' if change == 'extra-before' else 'afterSha256']['unreviewed.rs'] = '0'*64
            elif change in ('before', 'after'): next_proof[change+'Sha256'][name] = '0'*64
            elif change == 'prepared': prepared[name] = '0'*64
            elif change == 'core': actual_core[name] = '0'*64
            elif change == 'missing-prepared': prepared.pop(name)
            elif change == 'missing-core': actual_core.pop(name)
            else:
                next_proof['afterSha256'][name] = '0'*64
                prepared[name] = actual_core[name] = '0'*64
            with self.subTest(change=change, source=name), self.assertRaises(ValueError):
                pdf.validate(proof, prepared, actual_core, actual_helpers, successor=next_proof)

    def test_even_an_internally_exact_successor_cannot_claim_an_unrelated_prior_stage(self):
        proof, successor, files, core, helpers = self.owned_font_successor()
        unrelated = {**fonts.INPUT_SOURCE_SHA256, fonts.PDF:'0'*64}
        forged = deepcopy(successor); forged['beforeSha256'] = unrelated
        # The current successor validator still accepts its own exact immutable
        # input fixture; the stage handoff must independently reject this join.
        with patch.object(fonts, 'INPUT_SOURCE_SHA256', unrelated):
            fonts.validate_contract(forged, files, helpers)
            with self.assertRaisesRegex(ValueError, 'PDF.*stage handoff'):
                pdf.validate(proof, files, core, helpers, successor=forged)

    def test_font_successor_cannot_replace_other_source1_sources_or_original_licenses(self):
        proof, successor, files, core, helpers = self.owned_font_successor()
        for name in pdf.SOURCE_FILES:
            if name == pdf.PDF: continue
            altered = dict(files); altered[name] = '0'*64
            with self.subTest(source=name), self.assertRaisesRegex(ValueError, 'PDF search text prepared source hash mismatch'):
                pdf.validate(proof, altered, core, helpers, successor=successor)

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

    def test_layout_advances_preserve_positioned_glyphs_and_share_existing_font_resources(self):
        pdf.apply(self.source)
        svg = (self.source/pdf.SVG).read_text()
        self.assertIn('original positioned glyph emission', svg)
        self.assertIn('opengeul-layout-advance-', svg)
        self.assertIn('advance.to_bits()', svg)
        text = (self.source/pdf.TEXT).read_text()
        self.assertIn('original outline_transform, set_text_matrix and show remain', text)
        self.assertIn('.font_descriptor(descriptor_ref)', text)
        self.assertIn('.to_unicode(cmap_ref)', text)
        self.assertIn('font.layout_advances.entry(key)', text)
        self.assertIn('width.is_finite() && width > 0.0', text)
        self.assertIn('positioned_glyphs.len()).sum::<usize>() != 1', text)
        self.assertNotIn('actual_text(', text)

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
