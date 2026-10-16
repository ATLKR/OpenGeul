"""Portable boundary regressions for actual-Windows engine evidence."""
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / 'e2e' / 'engine_smoke.py'
SPEC = importlib.util.spec_from_file_location('suite_engine_smoke', SOURCE)
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


def observations(module):
    if module == 'base':
        return {'databaseUrl': 'sdbc:embedded:firebird',
                'rows': [{'id': 1, 'text': smoke.marker('base'), 'amount': 42}]}
    if module == 'math':
        return {'formula': smoke.FORMULA}
    result = {'text': smoke.marker(module)}
    if module in smoke.UI_MODULES:
        result['text'] += ' UI-OpenGeul-' + module
    if module == 'calc':
        result.update(formula='=SUM(B1:C1)', value=42)
    if module in ('draw', 'impress'):
        result['pageCount'] = 1
    if module == 'draw':
        result.update(position=[1000, 1000], size=[6000, 2500])
    return result


class EngineEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.suite = self.root / 'suite'
        self.output = self.root / 'evidence'
        self.suite.mkdir()
        (self.output / 'fixtures').mkdir(parents=True)
        self.modules = {module: {'factory': factory, 'filters': {}}
                        for module, factory in smoke.FACTORIES.items()}
        (self.suite / 'suite-product.json').write_text(json.dumps(
            {'schemaVersion': 1, 'modules': self.modules}), encoding='utf-8')
        for name in smoke.FILES.values():
            (self.output / 'fixtures' / name).write_bytes(b'before close')

    def fake_engine(self, path, cleanup_error=False, delete=False):
        class Engine:
            cleanup_errors = []

            def __init__(self, suite):
                self.cleanup_errors = []

            def start(self):
                pass

            def load(self, url):
                return object()

            def close_document(self, document):
                path.write_bytes(b'after model close')

            def cleanup(self):
                if delete:
                    path.unlink()
                else:
                    path.write_bytes(b'final persisted bytes after process cleanup')
                if cleanup_error:
                    self.cleanup_errors.append('owned process remained alive')
        return Engine

    def test_hash_records_final_bytes_after_model_close_and_process_cleanup(self):
        path = self.output / 'fixtures' / smoke.FILES['base']
        with patch.object(smoke, 'Engine', self.fake_engine(path)), \
                patch.object(smoke, 'observe', return_value=observations('base')):
            result = smoke.run_case(self.suite, self.output, 'base', self.modules['base'], True)
        final = path.read_bytes()
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['sha256'], hashlib.sha256(final).hexdigest())
        self.assertEqual(result['bytes'], len(final))
        self.assertEqual(result['observed']['rows'], observations('base')['rows'])
        self.assertNotIn('uiSuffix', result['expected'])

    def test_final_hash_failure_is_structured_and_cannot_pass(self):
        path = self.output / 'fixtures' / smoke.FILES['base']
        with patch.object(smoke, 'Engine', self.fake_engine(path, delete=True)), \
                patch.object(smoke, 'observe', return_value=observations('base')):
            result = smoke.run_case(self.suite, self.output, 'base', self.modules['base'], True)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['error']['type'], 'FileNotFoundError')
        self.assertNotIn('sha256', result)
        self.assertNotIn('bytes', result)

    def test_cleanup_failure_does_not_publish_a_success_hash(self):
        path = self.output / 'fixtures' / smoke.FILES['base']
        with patch.object(smoke, 'Engine', self.fake_engine(path, cleanup_error=True)), \
                patch.object(smoke, 'observe', return_value=observations('base')):
            result = smoke.run_case(self.suite, self.output, 'base', self.modules['base'], True)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('cleanupErrors', result)
        self.assertNotIn('sha256', result)

    def baseline(self, modules):
        (self.output / 'engine-smoke.json').write_text(json.dumps(
            {'cases': [{'module': module, 'status': 'passed'} for module in modules]}), encoding='utf-8')

    def test_post_gui_reopens_all_six_modules_and_keeps_their_semantic_checks(self):
        self.baseline(smoke.FILES)
        seen = []

        def run_case(suite, output, module, specification, verify_ui):
            seen.append(module)
            self.assertTrue(verify_ui)
            smoke.verify_content(module, observations(module), verify_ui)
            return {'module': module, 'status': 'passed'}

        with patch.object(smoke, 'run_case', side_effect=run_case), redirect_stdout(io.StringIO()):
            code = smoke.main(['--suite', str(self.suite), '--output', str(self.output), '--verify-ui'])
        self.assertEqual(code, 0)
        self.assertEqual(seen, list(smoke.FILES))
        report = json.loads((self.output / 'ui-engine-verification.json').read_text())
        self.assertTrue(report['passed'])
        self.assertEqual(len(report['cases']), 6)

    def test_post_gui_rejects_three_module_baseline_before_reopening_anything(self):
        self.baseline(smoke.UI_MODULES)
        with patch.object(smoke, 'run_case') as run, redirect_stderr(io.StringIO()):
            code = smoke.main(['--suite', str(self.suite), '--output', str(self.output), '--verify-ui'])
        self.assertEqual(code, 2)
        run.assert_not_called()

    def test_ui_suffix_required_only_for_modules_with_keyboard_edit_cases(self):
        for module in smoke.FILES:
            with self.subTest(module=module):
                value = observations(module)
                smoke.verify_content(module, value, True)
                if module in smoke.UI_MODULES:
                    value['text'] = smoke.marker(module)
                    with self.assertRaisesRegex(AssertionError, 'GUI edit'):
                        smoke.verify_content(module, value, True)

    def test_post_gui_keeps_draw_geometry_math_formula_and_base_sql_guards(self):
        for module, key, wrong in [('draw', 'size', [1, 1]), ('math', 'formula', 'x'),
                                   ('base', 'rows', []), ('base', 'databaseUrl', 'jdbc:')]:
            with self.subTest(module=module, key=key):
                value = observations(module)
                value[key] = wrong
                with self.assertRaises(AssertionError):
                    smoke.verify_content(module, value, True)


if __name__ == '__main__':
    unittest.main()
