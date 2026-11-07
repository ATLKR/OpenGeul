"""Finite source recipes; source installation never qualifies a native engine.

Set OPENGEUL_NATIVE_SOURCE_RECIPE_SOURCE to an authenticated pristine LO tree.
OPENGEUL_NATIVE_SOURCE_RECIPE_REQUIRE_SOURCE=1 makes missing or changed inputs
fatal. Tests copy only the fixed inputs; the retained source is never modified.
"""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / 'suite/engine-build'
CORE = 'bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1'
ORDERS = {'arm64': ['arm64Full', 'winAccFocusOrder'],
          'x64': ['moduleBootstrap', 'winAccFocusOrder']}
RECIPES = {'arm64': 'windows-arm64-v1', 'x64': 'windows-x64-common-v2'}


def load(name):
    path = ENGINE / (name + '.py')
    assert path.is_file(), 'Authenticated finite source recipe dispatcher is missing'
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def manifest():
    return json.loads((ENGINE / 'source-build.json').read_bytes())


def normalize_receipt_paths(value, source, retained):
    if isinstance(value, dict):
        return {key: normalize_receipt_paths(item, source, retained) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize_receipt_paths(item, source, retained) for item in value]
    if isinstance(value, str):
        for root, label in [(str(retained), '<evidence>'), (str(source), '<source>')]:
            if value == root or value.startswith((root + '/', root + '\\')):
                return label + value[len(root):]
    return value


class ReceiptNormalizationTests(unittest.TestCase):
    def test_receipt_paths_are_normalized_before_json_escaping(self):
        for source, retained, separator in [
                (r'C:\synthetic\source', r'C:\synthetic\evidence', '\\'),
                (r'C:\synthetic\한글\source', r'C:\synthetic\한글\evidence', '\\'),
                ('/synthetic/한글 "quoted"/source', '/synthetic/한글 "quoted"/evidence', '/')]:
            with self.subTest(separator=separator, unicode_path='한글' in source):
                def receipt(source_root, evidence_root):
                    return {'sourceHooks': {'targetsPath': source_root + separator + 'build.targets',
                                             'evidence': {'original': evidence_root + separator + 'original.mk'},
                                             'nested': [source_root, {'root': evidence_root}]},
                            'winAcc': {'beforeSha256': 'a' * 64, 'nativeBuildVerified': False},
                            'text': '한글 "quotes" and literal \\n', 'number': 17, 'empty': None}
                value = receipt(source, retained); original = copy.deepcopy(value)
                normalized = normalize_receipt_paths(value, source, retained)
                self.assertEqual(receipt('<source>', '<evidence>'), normalized)
                self.assertEqual(original, value)
                self.assertEqual(normalized, json.loads(json.dumps(normalized)))

    def test_receipt_normalization_preserves_non_path_data_and_parity_differences(self):
        source, retained = '/synthetic/source', '/synthetic/evidence'
        value = {'path': source + '/file', 'otherRoot': source + '-other/file',
                 'message': 'prefix ' + source + '/file', source + '/field': 'unchanged',
                 'serialized': json.dumps({'path': retained + '/file'}),
                 'sha256': 'a' * 64, 'passed': False, 'count': 0, 'absent': None}
        expected = dict(value, path='<source>/file')
        normalized = normalize_receipt_paths(value, source, retained)
        self.assertEqual(expected, normalized)
        for key, changed in [('sha256', 'b' * 64), ('passed', True), ('count', 1)]:
            with self.subTest(field=key):
                self.assertNotEqual(normalized, normalize_receipt_paths(dict(value, **{key: changed}), source, retained))


class RecipePolicyTests(unittest.TestCase):
    def test_fixed_policy_selects_exact_finite_recipes(self):
        module = load('apply_native_source')
        for architecture in ORDERS:
            plan = module._select_plan(manifest(), (ENGINE / 'native-targets.json').read_bytes(), architecture)
            self.assertEqual(ORDERS[architecture], plan['recipe']['hooks'])
            self.assertEqual(RECIPES[architecture], plan['recipeId'])
            self.assertEqual(13, len(plan['armGuardedSources']))
            self.assertEqual(17, len(plan['sources']))
            self.assertIn('sourceDependencies', plan)
            self.assertEqual(1 if architecture == 'arm64' else 0, len(plan['sourceDependencies']))

    def test_unknown_missing_duplicate_reordered_or_modified_hook_fails(self):
        module = load('apply_native_source')
        for architecture, order in ORDERS.items():
            for hooks in [order + ['unknown'], order[:1], order + order[:1], order[::-1],
                          [{'id': order[0]}, order[1]], [order[0] + '-modified', order[1]]]:
                with self.subTest(architecture=architecture, hooks=hooks):
                    lock = manifest()
                    lock['nativeSourceRecipes'][RECIPES[architecture]]['hooks'] = hooks
                    with self.assertRaises(ValueError):
                        module._select_plan(lock, (ENGINE / 'native-targets.json').read_bytes(), architecture)

    def test_schema_membership_core_architecture_and_source_membership_drift_fail(self):
        module = load('apply_native_source')
        mutations = [lambda p: p['nativeSourceRecipes'].pop(RECIPES['arm64']),
                     lambda p: p['nativeSourceRecipes'].update(unknown={}),
                     lambda p: p['nativeSourceRecipes'][RECIPES['x64']].update(schemaVersion=2),
                     lambda p: p['nativeSourceRecipes'][RECIPES['x64']].update(architecture='arm64'),
                     lambda p: p['nativeSourceRecipes'][RECIPES['x64']].update(coreCommit='0' * 40),
                     lambda p: p['moduleBootstrap'].update(path='../escape'),
                     lambda p: p['atlConsumerNativePaths']['recipes'].reverse(),
                     lambda p: p['winAccFocusOrder']['sources'].pop()]
        for mutate in mutations:
            lock = manifest(); mutate(lock)
            with self.assertRaises(ValueError):
                module._select_plan(lock, (ENGINE / 'native-targets.json').read_bytes(), 'x64')
        for architecture in ['X64', 'amd64', '', None]:
            with self.assertRaises(ValueError):
                module._select_plan(manifest(), (ENGINE / 'native-targets.json').read_bytes(), architecture)

    def test_policy_bytes_and_duplicate_json_names_fail_closed(self):
        module = load('apply_native_source')
        raw = (ENGINE / 'native-targets.json').read_bytes()
        for changed in [raw + b' ', raw.replace(b'windows-x64-common-v2', b'windows-arm64-v1')]:
            with self.assertRaises(ValueError): module._select_plan(manifest(), changed, 'x64')
        for raw in [b'{"a":1,"a":2}', b'{"a":{"b":1,"b":2}}']:
            with self.assertRaises(ValueError): module._decode_json(raw)

    def test_exact_winacc_original_and_candidate_behavioral_witnesses(self):
        from suite.tests.test_winacc_focus_order import WinAccFocusOrderTests
        witness = WinAccFocusOrderTests('test_exact_extracted_methods_original_red_candidate_green')
        result = unittest.TestResult(); witness.run(result)
        self.assertEqual([], result.errors + result.failures)
        if os.name != 'nt': self.assertEqual([], result.skipped)


class ActualSourceRecipeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        value = os.environ.get('OPENGEUL_NATIVE_SOURCE_RECIPE_SOURCE')
        required = os.environ.get('OPENGEUL_NATIVE_SOURCE_RECIPE_REQUIRE_SOURCE') == '1'
        if not value:
            if required: raise AssertionError('Mandatory pinned source recipe inputs are missing')
            raise unittest.SkipTest('Explicit pinned source recipe fixture path is required')
        cls.module = load('apply_native_source')
        cls.lock = manifest()
        cls.plan = cls.module._select_plan(cls.lock, (ENGINE / 'native-targets.json').read_bytes(), 'arm64')
        cls.inputs = {}
        for row in cls.plan['sources'] + cls.plan['sourceDependencies']:
            raw = cls.module._regular(Path(value) / row['path'])
            if hashlib.sha256(raw).hexdigest() != row['beforeSha256']:
                raise AssertionError('Pinned source recipe input SHA256 mismatch')
            cls.inputs[row['path']] = raw

    def setUp(self):
        self.folder = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.source = self.folder / 'source'; self.source.mkdir()
        self.evidence = self.folder / 'evidence'; self.evidence.mkdir()
        for name, raw in self.inputs.items():
            target = self.source / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(raw)

    def install(self, architecture):
        return self.module.apply_native_source(self.source, self.evidence, architecture=architecture)

    def unchanged(self):
        self.assertEqual({name: (self.source / name).read_bytes() for name in self.inputs}, self.inputs)

    def proof(self, result, architecture):
        self.assertEqual({'sourceHooks', 'winAccFocusOrderSourcePatch', 'sourceRecipeProof'}, set(result))
        proof = result['sourceRecipeProof']
        self.assertEqual({'schemaVersion', 'kind', 'architecture', 'recipeId', 'policySha256',
                          'manifestSha256', 'recipeSha256', 'hookOrder', 'armGuardedSources',
                          'nativeBuildVerified', 'fullEngineQualified', 'acceptanceEligible', 'guiVerified'}, set(proof))
        self.assertEqual(1, proof['schemaVersion'])
        self.assertEqual('native-engine-source-recipe-install', proof['kind'])
        self.assertEqual(architecture, proof['architecture'])
        self.assertEqual(RECIPES[architecture], proof['recipeId'])
        self.assertEqual(ORDERS[architecture], proof['hookOrder'])
        for key in ['nativeBuildVerified', 'fullEngineQualified', 'acceptanceEligible', 'guiVerified']:
            self.assertIs(proof[key], False)
        for filename, key in [('source-build.json', 'manifestSha256'), ('native-targets.json', 'policySha256')]:
            self.assertEqual(hashlib.sha256((ENGINE / filename).read_bytes()).hexdigest(), proof[key])
        plan = self.module._select_plan(self.lock, (ENGINE / 'native-targets.json').read_bytes(), architecture)
        self.assertEqual(hashlib.sha256(json.dumps(plan, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest(), proof['recipeSha256'])
        self.assertEqual(13, len(proof['armGuardedSources']))
        for pin, row in zip(plan['armGuardedSources'], proof['armGuardedSources']):
            expected = pin['beforeSha256'] if architecture == 'x64' else pin['afterSha256']
            self.assertEqual({'path': pin['path'], 'beforeSha256': pin['beforeSha256'],
                              'sha256': expected, 'unchanged': architecture == 'x64'}, row)
            self.assertEqual(expected, hashlib.sha256((self.source / row['path']).read_bytes()).hexdigest())

    def test_arm_recipe_outputs_match_frozen_manifest(self):
        result = self.install('arm64'); self.proof(result, 'arm64')
        self.assertEqual('arm64', result['sourceHooks']['architecture'])
        self.assertEqual(self.lock['sourceHook']['afterSha256'], result['sourceHooks']['afterSha256'])
        for row in self.plan['sources']:
            self.assertEqual(row['afterSha256'], hashlib.sha256((self.source / row['path']).read_bytes()).hexdigest())

    def test_arm_full_installer_then_winacc_without_duplicate_bootstrap(self):
        direct = self.folder / 'direct'; shutil.copytree(self.source, direct)
        evidence = self.folder / 'direct-evidence'; evidence.mkdir()
        expected = {'sourceHooks': load('enable_firebird_arm64').install(direct, evidence),
                    'winAccFocusOrderSourcePatch': load('apply_winacc_focus_order').install(direct, evidence, CORE)}
        events = []
        arm = self.module.ARM.install; winacc = self.module.WINACC.install
        def full(*args): events.append('arm64Full'); return arm(*args)
        def focus(*args): events.append('winAccFocusOrder'); return winacc(*args)
        with patch.object(self.module.ARM, 'install', side_effect=full), \
                patch.object(self.module.ARM, 'install_module_bootstrap', wraps=self.module.ARM.install_module_bootstrap) as bootstrap, \
                patch.object(self.module.WINACC, 'install', side_effect=focus):
            result = self.install('arm64')
        self.assertEqual(ORDERS['arm64'], events); self.assertEqual(1, bootstrap.call_count)
        actual = {key: result[key] for key in expected}
        self.assertEqual(normalize_receipt_paths(expected, direct, evidence),
                         normalize_receipt_paths(actual, self.source, self.evidence))
        self.assertEqual({p.relative_to(direct).as_posix(): p.read_bytes() for p in direct.rglob('*') if p.is_file()},
                         {p.relative_to(self.source).as_posix(): p.read_bytes() for p in self.source.rglob('*') if p.is_file()})

    def test_x64_recipe_applies_exactly_module_bootstrap_then_winacc(self):
        events = []; bootstrap = self.module.ARM.install_module_bootstrap; winacc = self.module.WINACC.install
        def common(*args): events.append('moduleBootstrap'); return bootstrap(*args)
        def focus(*args): events.append('winAccFocusOrder'); return winacc(*args)
        with patch.object(self.module.ARM, 'install', side_effect=AssertionError('x64 selected full ARM installer')), \
                patch.object(self.module.ARM, 'install_module_bootstrap', side_effect=common), \
                patch.object(self.module.WINACC, 'install', side_effect=focus):
            result = self.install('x64')
        self.proof(result, 'x64'); self.assertEqual(ORDERS['x64'], events)
        hooks = result['sourceHooks']
        self.assertEqual({'kind', 'architecture', 'moduleBootstrap', 'nativeBuildVerified', 'basePersistenceVerified'}, set(hooks))
        self.assertEqual('native-windows-common-source-hooks', hooks['kind']); self.assertEqual('x64', hooks['architecture'])
        self.assertIs(hooks['nativeBuildVerified'], False); self.assertIs(hooks['basePersistenceVerified'], False)
        for row in self.plan['sources'][:4]:
            self.assertEqual(row['afterSha256'], hashlib.sha256((self.source / row['path']).read_bytes()).hexdigest())

    def test_x64_leaves_all_13_arm_guarded_targets_unchanged(self):
        result = self.install('x64'); self.proof(result, 'x64')
        changed = {name for name, raw in self.inputs.items() if (self.source / name).read_bytes() != raw}
        self.assertEqual({'bin/unpack-sources', self.lock['winAccFocusOrder']['path']}, changed)
        self.assertEqual(set(self.inputs), {p.relative_to(self.source).as_posix() for p in self.source.rglob('*') if p.is_file()})

    def test_every_input_drift_rejects_before_any_recipe_write(self):
        for name, raw in self.inputs.items():
            target = self.source / name; target.write_bytes(raw + b'\n')
            architectures = ['arm64', 'x64'] if name in {row['path'] for row in self.plan['sources']} else ['arm64']
            for architecture in architectures:
                with self.subTest(path=name, architecture=architecture), self.assertRaises(ValueError): self.install(architecture)
                self.assertEqual([], list(self.evidence.iterdir()))
            target.write_bytes(raw); self.unchanged()

    def test_evidence_collision_and_overlapping_directories_reject_before_write(self):
        collision = self.evidence / 'unrelated'; collision.write_bytes(b'prior evidence')
        with self.assertRaises(ValueError): self.install('x64')
        collision.unlink(); self.unchanged()
        inside = self.source / 'evidence'; inside.mkdir()
        for source, evidence in [(self.source, inside), (self.source, self.source), (self.folder, self.evidence)]:
            with self.assertRaises(ValueError): self.module.apply_native_source(source, evidence, architecture='x64')
        self.unchanged(); self.assertEqual([], list(self.evidence.iterdir()))

    def test_hardlinks_symlinks_and_linked_ancestors_reject_before_write(self):
        target = self.source / 'bin/unpack-sources'; raw = target.read_bytes()
        saved = self.folder / 'saved'; target.rename(saved); os.link(saved, target)
        with self.assertRaises(ValueError): self.install('x64')
        self.assertEqual(raw, saved.read_bytes()); target.unlink(); target.symlink_to(saved)
        with self.assertRaises(ValueError): self.install('x64')
        target.unlink(); saved.rename(target)
        alias = self.folder / 'alias'; alias.symlink_to(self.source, target_is_directory=True)
        with self.assertRaises(ValueError): self.module.apply_native_source(alias, self.evidence, architecture='x64')
        self.unchanged(); self.assertEqual([], list(self.evidence.iterdir()))

    def test_changed_arm_payload_output_cannot_publish_recipe_success(self):
        install = self.module.ARM.install
        def corrupt(*args):
            receipt = install(*args)
            (self.source / 'external/firebird/firebird-windows-arm64.patch').write_bytes(b'changed payload')
            return receipt
        with patch.object(self.module.ARM, 'install', side_effect=corrupt), self.assertRaises(ValueError):
            self.install('arm64')

    def test_protected_source_drift_during_hooks_cannot_publish_x64_success(self):
        install = self.module.WINACC.install
        def corrupt(*args):
            receipt = install(*args)
            (self.source / 'configure.ac').write_bytes(b'changed protected source')
            return receipt
        with patch.object(self.module.WINACC, 'install', side_effect=corrupt), self.assertRaises(ValueError):
            self.install('x64')

    def test_cli_and_repeat_application_fail_closed(self):
        command = [sys.executable, str(ENGINE / 'apply_native_source.py'), '--libreoffice-source', str(self.source),
                   '--evidence-directory', str(self.evidence), '--architecture', 'x64']
        result = subprocess.run(command, capture_output=True, timeout=20)
        self.assertEqual(0, result.returncode); self.assertEqual(b'', result.stderr)
        self.proof(json.loads(result.stdout), 'x64')
        before = {p.relative_to(self.source).as_posix(): p.read_bytes() for p in self.source.rglob('*') if p.is_file()}
        result = subprocess.run(command, capture_output=True, timeout=20)
        self.assertEqual(1, result.returncode); self.assertEqual(b'', result.stderr)
        self.assertEqual({'schemaVersion': 1, 'passed': False, 'errorCode': 'source-recipe-input'}, json.loads(result.stdout))
        self.assertEqual(before, {p.relative_to(self.source).as_posix(): p.read_bytes() for p in self.source.rglob('*') if p.is_file()})


if __name__ == '__main__': unittest.main()
