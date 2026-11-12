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
import shlex
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
          'x64': ['moduleBootstrap', 'firebirdLoaderPath', 'zstdSourceLinks', 'gpgBuildCompilerPath', 'atlNativePaths', 'harfbuzzNativeMesonPaths', 'cliPublisherPolicyPlatform', 'winAccFocusOrder']}
RECIPES = {'arm64': 'windows-arm64-v1', 'x64': 'windows-x64-common-v2'}
GPG_PATH = 'solenv/gbuild/platform/com_MSC_defs.mk'
GPG_CONDITION = 'WNT_X86_64 && BUILD_PLATFORM=%cygwin'
GPG_FIXTURE = ROOT / 'suite/tests/fixtures/native-gpg-build-compiler/com_MSC_defs.mk'


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
    def test_x64_harfbuzz_transform_rejects_changed_repeated_or_forged_input(self):
        module = load('apply_native_source'); pin = manifest()['windowsHarfbuzzNativeMesonPaths']
        raw = (ROOT / 'suite/tests/fixtures/native-meson-path/ExternalProject_harfbuzz.mk').read_bytes()
        effective = module._harfbuzz_bytes(raw, pin)
        for field, value in [('path', '../escape'), ('condition', 'WNT_AARCH64'), ('size', True),
                             ('afterSize', 1.5), ('sha256', '0' * 64), ('afterSha256', '0' * 64), ('extra', False)]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                module._harfbuzz_bytes(raw, dict(pin, **{field: value}))
        for changed in (raw + b'\n', effective):
            with self.subTest(repeated=changed == effective), self.assertRaises(ValueError):
                module._harfbuzz_bytes(changed, pin)
        marker = b'# cannot use CROSS_COMPILING as condition since we have cross-compilation "light" for cases where\n'
        repeated = raw + marker
        with self.assertRaises(ValueError):
            module._harfbuzz_bytes(repeated, dict(pin, size=len(repeated), sha256=hashlib.sha256(repeated).hexdigest()))

    def test_x64_harfbuzz_reclassifies_only_its_pinned_input_and_preserves_arm(self):
        lock = manifest(); module = load('apply_native_source')
        self.assertIn('windowsHarfbuzzNativeMesonPaths', lock, 'Missing x64 native Meson descriptor')
        pin = lock['windowsHarfbuzzNativeMesonPaths']
        self.assertEqual({'path', 'size', 'sha256', 'afterSize', 'afterSha256', 'condition'}, set(pin))
        self.assertEqual('WNT_X86_64_MSC_WNT && MAKE_HOST=%-cygwin', pin['condition'])
        self.assertEqual((3074, '2e85211865e09766b1bc8b0664aa152a2e98277a0af572150902786b3ceefc50',
                          5920, '5bd3e604b5b253b064a62899efc7231c16c415f5533503e1fcbb1c8b00d68327'),
                         (pin['size'], pin['sha256'], pin['afterSize'], pin['afterSha256']))
        policy = (ENGINE / 'native-targets.json').read_bytes()
        arm = module._select_plan(lock, policy, 'arm64'); x64 = module._select_plan(lock, policy, 'x64')
        self.assertEqual('db6802d871b226b31d0e55343307c4b4bd88a74e961cb12cb3cf8d56565a6989',
                         hashlib.sha256(json.dumps(arm, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest())
        self.assertEqual((19, 4), (len(x64['sources']), len(x64['armGuardedSources'])))
        self.assertNotIn(pin['path'], [r['path'] for r in x64['armGuardedSources']])
        for field, value in [('path', '../escape'), ('condition', 'WNT_AARCH64'), ('size', True),
                             ('afterSize', 1.5), ('sha256', '0' * 64), ('afterSha256', 'invalid'), ('extra', False)]:
            changed = copy.deepcopy(lock); changed['windowsHarfbuzzNativeMesonPaths'][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): module._select_plan(changed, policy, 'x64')

    def test_x64_atl_descriptor_reclassifies_six_exact_inputs_without_changing_arm(self):
        lock = manifest(); module = load('apply_native_source')
        self.assertTrue('windowsAtlNativePaths' in lock, 'x64 native ATL source descriptor is missing')
        descriptor = lock['windowsAtlNativePaths']
        self.assertEqual({'condition', 'recipes'}, set(descriptor))
        self.assertEqual('WNT_X86_64_MSC && MAKE_HOST=%-cygwin', descriptor['condition'])
        original = [lock['atlNativePaths']['recipe'], *lock['atlConsumerNativePaths']['recipes']]
        self.assertEqual([r['path'] for r in original], [r['path'] for r in descriptor['recipes']])
        for before, row in zip(original, descriptor['recipes']):
            self.assertEqual({'path', 'size', 'sha256', 'afterSize', 'afterSha256'}, set(row))
            self.assertEqual({k: before[k] for k in ('path', 'size', 'sha256')},
                             {k: row[k] for k in ('path', 'size', 'sha256')})
            self.assertNotEqual(before['afterSha256'], row['afterSha256'])
        policy = (ENGINE / 'native-targets.json').read_bytes()
        arm = module._select_plan(lock, policy, 'arm64')
        self.assertEqual('db6802d871b226b31d0e55343307c4b4bd88a74e961cb12cb3cf8d56565a6989',
                         hashlib.sha256(json.dumps(arm, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest())
        selected = module._select_plan(lock, policy, 'x64')
        self.assertEqual((19, 4), (len(selected['sources']), len(selected['armGuardedSources'])))
        self.assertEqual(['moduleBootstrap', 'firebirdLoaderPath', 'zstdSourceLinks',
                          'gpgBuildCompilerPath', 'atlNativePaths', 'harfbuzzNativeMesonPaths', 'cliPublisherPolicyPlatform', 'winAccFocusOrder'], selected['recipe']['hooks'])
        guarded = {r['path'] for r in selected['armGuardedSources']}
        self.assertTrue(guarded.isdisjoint(r['path'] for r in original))
        for mutate in [lambda d: d.update(extra=False), lambda d: d.update(condition='WNT_AARCH64'),
                       lambda d: d['recipes'].reverse(), lambda d: d['recipes'].pop(),
                       lambda d: d['recipes'][0].update(size=True),
                       lambda d: d['recipes'][0].update(sha256='0' * 64),
                       lambda d: d['recipes'][0].update(afterSize=1.5)]:
            changed = copy.deepcopy(lock); mutate(changed['windowsAtlNativePaths'])
            with self.assertRaises(ValueError): module._select_plan(changed, policy, 'x64')

    def test_x64_atl_transforms_reject_changed_repeated_or_forged_pins(self):
        module = load('apply_native_source'); lock = manifest()
        for index, pin in enumerate(lock['windowsAtlNativePaths']['recipes']):
            path = (ROOT / 'suite/tests/fixtures/native-atl-path' / Path(pin['path']).name if index == 0 else
                    ROOT / 'suite/tests/fixtures/native-atl-consumers' / pin['path'])
            original = path.read_bytes(); changed = module._atl_bytes(original, pin)
            self.assertEqual(pin['afterSha256'], hashlib.sha256(changed).hexdigest())
            for field, value in [('path', '../escape'), ('size', True), ('afterSize', 1.5),
                                 ('sha256', '0' * 64), ('afterSha256', '0' * 64), ('extra', False)]:
                with self.subTest(path=pin['path'], field=field), self.assertRaises(ValueError):
                    module._atl_bytes(original, dict(pin, **{field: value}))
            for wrong in (original + b'\n', changed):
                with self.assertRaises(ValueError): module._atl_bytes(wrong, pin)

    def test_x64_zstd_source_link_exception_reclassifies_only_its_exact_input(self):
        module = load('apply_native_source'); lock = manifest()
        raw = (ENGINE / 'native-targets.json').read_bytes()
        plan = module._select_plan(lock, raw, 'x64')
        self.assertEqual(4, len(plan['armGuardedSources']))
        self.assertNotIn('external/zstd/UnpackedTarball_zstd.mk',
                         [row['path'] for row in plan['armGuardedSources']])
        self.assertEqual(ORDERS['x64'],
                         plan['recipe']['hooks'])
        arm = module._select_plan(lock, raw, 'arm64')
        self.assertEqual(13, len(arm['armGuardedSources']))
        self.assertEqual('db6802d871b226b31d0e55343307c4b4bd88a74e961cb12cb3cf8d56565a6989',
                         hashlib.sha256(json.dumps(arm, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest())

    def test_x64_zstd_descriptor_and_raw_source_drift_are_rejected(self):
        module = load('apply_native_source'); lock = manifest()
        self.assertIn('windowsZstdSourceLinks', lock)
        original = (ROOT / 'suite/tests/fixtures/native-zstd-unpack/UnpackedTarball_zstd.mk').read_bytes()
        pin = lock['windowsZstdSourceLinks']
        for field, value in [('path', '../escape'), ('condition', 'WNT_AARCH64'),
                             ('size', True), ('size', pin['size'] + 1), ('afterSize', 1.5),
                             ('afterSize', pin['afterSize'] + 1), ('sha256', '0' * 64),
                             ('afterSha256', '0' * 64)]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                module._zstd_bytes(original, dict(pin, **{field: value}))
        for changed in [original + b'\n', original[:-1]]:
            with self.assertRaises(ValueError): module._zstd_bytes(changed, pin)
        for mutate in [lambda p: p['windowsZstdSourceLinks'].update(extra=True),
                       lambda p: p.pop('windowsZstdSourceLinks'),
                       lambda p: p['windowsZstdSourceLinks'].update(condition='WNT_AARCH64')]:
            changed = copy.deepcopy(lock); mutate(changed)
            with self.assertRaises(ValueError):
                module._select_plan(changed, (ENGINE / 'native-targets.json').read_bytes(), 'x64')

    def test_x64_retains_the_pinned_firebird_loader_recipe_with_the_zstd_exception(self):
        module = load('apply_native_source'); lock = manifest()
        plan = module._select_plan(lock, (ENGINE / 'native-targets.json').read_bytes(), 'x64')
        self.assertEqual(4, len(plan['armGuardedSources']))
        self.assertNotIn('external/firebird/ExternalProject_firebird.mk',
                         [row['path'] for row in plan['armGuardedSources']])
        self.assertEqual(ORDERS['x64'], plan['recipe']['hooks'])
        original = (ROOT / 'suite/tests/fixtures/native-icu-path/ExternalProject_firebird.mk').read_bytes()
        pin = lock['windowsFirebirdLoaderPath']
        for field, value in [('sha256', '0' * 64), ('afterSha256', '0' * 64), ('size', pin['size'] + 1),
                             ('afterSize', pin['afterSize'] + 1)]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                module._loader_bytes(original, dict(pin, **{field: value}))

    def test_fixed_policy_selects_exact_finite_recipes(self):
        module = load('apply_native_source')
        for architecture in ORDERS:
            plan = module._select_plan(manifest(), (ENGINE / 'native-targets.json').read_bytes(), architecture)
            self.assertEqual(ORDERS[architecture], plan['recipe']['hooks'])
            self.assertEqual(RECIPES[architecture], plan['recipeId'])
            self.assertEqual(13 if architecture == 'arm64' else 4, len(plan['armGuardedSources']))
            self.assertEqual(17 if architecture == 'arm64' else 19, len(plan['sources']))
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
                     lambda p: p['windowsFirebirdLoaderPath'].update(condition='WNT_AARCH64'),
                     lambda p: p['windowsFirebirdLoaderPath'].update(path='../escape'),
                     lambda p: p['windowsFirebirdLoaderPath'].update(size=True),
                     lambda p: p['windowsFirebirdLoaderPath'].update(afterSize=1.5),
                     lambda p: p['windowsFirebirdLoaderPath'].update(unknown=True),
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

    def test_gpg_descriptor_is_exact_x64_input_without_changing_arm_plan_or_policy(self):
        module=load('apply_native_source');lock=manifest()
        self.assertIn('windowsGpgBuildCompilerPath',lock,'missing GPG source descriptor')
        pin=lock['windowsGpgBuildCompilerPath']
        self.assertEqual(dict(path=GPG_PATH,condition=GPG_CONDITION,size=10340,
            sha256='c52a23dbfb16031731e12ddd44ede7838bd45d4a88d8fa2d316e6a11fc7a2f14',afterSize=10480,
            afterSha256='f122cf42e9e7ff28fde1ce01f8233c6250f028c7f57c5cb7a723205a9cb72d6b'),pin)
        policy=(ENGINE/'native-targets.json').read_bytes()
        self.assertEqual('ba8d627adefb2dfe90e048546f6f55d54c8e739d0f4f21afbe8a556af54768bc',hashlib.sha256(policy).hexdigest())
        arm=module._select_plan(lock,policy,'arm64');x64=module._select_plan(lock,policy,'x64')
        self.assertEqual('db6802d871b226b31d0e55343307c4b4bd88a74e961cb12cb3cf8d56565a6989',
            hashlib.sha256(json.dumps(arm,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest())
        self.assertEqual((17,13),(len(arm['sources']),len(arm['armGuardedSources'])))
        self.assertEqual((19,4),(len(x64['sources']),len(x64['armGuardedSources'])))
        self.assertEqual(GPG_PATH,x64['sources'][6]['path'])
        self.assertNotIn(GPG_PATH,[row['path'] for row in arm['sources']])
        for field,value in [('path','../escape'),('condition','WNT_AARCH64'),('size',True),
                            ('afterSize',1.5),('sha256','invalid'),('afterSha256','invalid'),('extra',False)]:
            changed=copy.deepcopy(lock);changed['windowsGpgBuildCompilerPath'][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):
                module._select_plan(changed,policy,'x64')

    def test_gpg_transform_requires_single_pinned_preimage_and_rejects_repeat(self):
        module=load('apply_native_source');transform=getattr(module,'_gpg_build_compiler_bytes',None)
        self.assertTrue(callable(transform),'missing GPG source transform')
        raw=GPG_FIXTURE.read_bytes();pin=manifest()['windowsGpgBuildCompilerPath']
        effective=transform(raw,pin)
        self.assertEqual((10480,'f122cf42e9e7ff28fde1ce01f8233c6250f028c7f57c5cb7a723205a9cb72d6b'),
            (len(effective),hashlib.sha256(effective).hexdigest()))
        for field,value in [('path','../escape'),('condition','WNT_AARCH64'),('size',True),
                            ('afterSize',1.5),('sha256','0'*64),('afterSha256','0'*64),('extra',False)]:
            with self.subTest(field=field),self.assertRaises(ValueError):transform(raw,dict(pin,**{field:value}))
        for changed in (raw+b'\n',effective):
            with self.subTest(repeated=changed==effective),self.assertRaises(ValueError):transform(changed,pin)
        old=b'REAL_BUILD_CC="$(filter-out -%,$(CC_FOR_BUILD))"'
        duplicate=raw+old;forged=dict(pin,size=len(duplicate),sha256=hashlib.sha256(duplicate).hexdigest())
        with self.assertRaises(ValueError):transform(duplicate,forged)


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
        if architecture == 'x64':
            self.gpg_input(); self.policy_input()
        return self.module.apply_native_source(self.source, self.evidence, architecture=architecture)

    def policy_input(self):
        relative = 'cli_ure/CliNativeLibrary_cli_cppuhelper.mk'
        target = self.source / relative
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / 'suite/tests/fixtures/native-cli-policy' / relative).read_bytes())
        return target

    def gpg_input(self):
        target=self.source/GPG_PATH
        if not target.exists():
            target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(GPG_FIXTURE.read_bytes())
        return target

    def harfbuzz_replay(self, raw, *, inherited_pkg_config_path=None, **profile):
        from suite.tests import test_native_meson_path as replay
        from suite.tests.test_native_python_host import require_posix_recipe_replay
        require_cygwin = os.environ.get('OPENGEUL_MESON_REQUIRE_CYGWIN_REPLAY') == '1'
        require_posix_recipe_replay(os.name, Path('/usr/bin/make'), Path('/bin/bash'),
                                   require_cygwin)
        # Replace the mapping itself; the receiver only ever copies this literal
        # non-secret environment, including in Windows unit discovery.
        synthetic = {'PATH': '/usr/bin:/bin', 'PYTHONUTF8': '1',
                     'XDG_CACHE_HOME': '/tmp/opengeul-meson/cache',
                     'XDG_CONFIG_HOME': '/tmp/opengeul-meson/config',
                     'XDG_DATA_HOME': '/tmp/opengeul-meson/data'}
        if inherited_pkg_config_path is not None:
            synthetic['PKG_CONFIG_PATH'] = inherited_pkg_config_path
        profile = dict(cpu='X86_64', build='x86_64-pc-cygwin', target='x86_64-pc-cygwin') | profile
        with patch.object(os, 'environ', synthetic):
            if require_cygwin: replay.make_profile(require_cygwin=True)
            return replay.replay(self.folder, raw, **profile)

    def assert_harfbuzz_package_scope(self, observed, *, setup_entries, compile_path):
        self.assertEqual(2, len(observed))
        self.assertEqual(setup_entries, len(observed[0]['PKG_CONFIG_PATH'].split(';')))
        self.assertEqual(compile_path, observed[1]['PKG_CONFIG_PATH'])

    def test_x64_harfbuzz_setup_package_path_does_not_replace_compile_inheritance(self):
        from suite.tests import test_native_meson_path as replay
        path = 'external/harfbuzz/ExternalProject_harfbuzz.mk'; original = self.inputs[path]
        self.install('x64'); effective = (self.source / path).read_bytes()
        for inherited, prefix, expected_compile, setup_entries in (
                (None, '', None, 2),
                ('C:/synthetic inherited', 'C:/unchanged inherited', 'C:/unchanged inherited', 3)):
            with self.subTest(inherited=inherited is not None):
                before = self.harfbuzz_replay(original, prefix=prefix, inherited_pkg_config_path=inherited)
                after = self.harfbuzz_replay(effective, prefix=prefix, inherited_pkg_config_path=inherited)
                self.assertEqual(0, before.returncode); self.assertEqual(0, after.returncode)
                baseline = replay.observations(before); observed = replay.observations(after)
                self.assertEqual(2, len(baseline))
                self.assertEqual(expected_compile, baseline[1]['PKG_CONFIG_PATH'])
                try:
                    self.assert_harfbuzz_package_scope(observed, setup_entries=setup_entries, compile_path=expected_compile)
                except AttributeError:
                    self.fail('Compile receiver does not inherit the setup-only package assignment')

    def test_x64_harfbuzz_native_meson_receives_exact_compiler_argv_and_native_package_list(self):
        from suite.tests import test_native_meson_path as replay
        path = 'external/harfbuzz/ExternalProject_harfbuzz.mk'; original = self.inputs[path]
        self.install('x64'); effective = (self.source / path).read_bytes()
        before = self.harfbuzz_replay(original); after = self.harfbuzz_replay(effective)
        self.assertEqual(0, before.returncode); self.assertEqual(0, after.returncode)
        baseline = replay.observations(before); observed = replay.observations(after)
        self.assertEqual(2, len(observed)); split = replay.windows_split_args()
        for item in observed:
            for name in ('CC', 'CXX'): self.assertEqual([replay.NATIVE_COMPILER], split(item[name]))
            for name in ('PKG_CONFIG', 'AR', 'LD', 'NINJA'):
                self.assertEqual(baseline[0][name], item[name])
        self.assertEqual([r['args'] for r in baseline], [r['args'] for r in observed])
        self.assertEqual(['C:/Python With Spaces/lib/pkgconfig', 'D:/additional packages',
                          'C:/native' + str(self.folder / 'work/graphite'),
                          'C:/native' + str(self.folder / 'work/icu')], observed[0]['PKG_CONFIG_PATH'].split(';'))
        self.assertNotEqual([replay.NATIVE_COMPILER], split(baseline[0]['CC']))

    def test_x64_harfbuzz_other_profiles_keep_original_argv_and_environment(self):
        path = 'external/harfbuzz/ExternalProject_harfbuzz.mk'; original = self.inputs[path]
        self.install('x64'); effective = (self.source / path).read_bytes()
        profiles = [{'cpu': 'AARCH64'}, {'platform': 'LINUX'}, {'com': 'GCC'},
                    {'host': 'x86_64-pc-linux-gnu'}, {'host': 'x86_64-w64-mingw32'},
                    {'build': 'aarch64-pc-cygwin'}, {'wsl': 'TRUE'}, {'python': '/usr/bin/python3'},
                    {'system_python': 'TRUE'}, {'build_type': ''}]
        for profile in profiles:
            with self.subTest(profile=list(profile)):
                before = self.harfbuzz_replay(original, **profile); after = self.harfbuzz_replay(effective, **profile)
                self.assertEqual(0, before.returncode); self.assertEqual(0, after.returncode)
                self.assertEqual(before.stdout, after.stdout)

    def test_x64_harfbuzz_rejects_invalid_compilers_and_conversion_before_meson(self):
        path = 'external/harfbuzz/ExternalProject_harfbuzz.mk'
        self.install('x64'); effective = (self.source / path).read_bytes()
        for profile in [{'cc': ''}, {'cxx': ''}, {'cc': '/missing/cl.exe'},
                        {'cc': 'ccache /missing/cl.exe'}, {'cxx': '/missing/cl.exe -nologo'},
                        {'converter': 'fail'}, {'converter': 'empty'},
                        {'prefix': '/badpkg', 'converter': 'pkg-fail'},
                        {'prefix': '/badpkg', 'converter': 'pkg-empty'}]:
            with self.subTest(case=list(profile)):
                result = self.harfbuzz_replay(effective, **profile)
                self.assertNotEqual(0, result.returncode); self.assertEqual('', result.stdout)

    def test_x64_harfbuzz_retains_exact_evidence_and_cannot_qualify_an_engine(self):
        result = self.install('x64')
        self.assertIn('harfbuzzNativeMesonPaths', result['sourceHooks'], 'Missing native Meson source evidence')
        proof = result['sourceHooks']['harfbuzzNativeMesonPaths']; pin = self.lock['windowsHarfbuzzNativeMesonPaths']
        self.assertEqual({'schemaVersion', 'kind', 'path', 'condition', 'beforeBytes', 'afterBytes',
                          'beforeSha256', 'afterSha256', 'evidence', 'nativeBuildVerified',
                          'fullEngineQualified', 'acceptanceEligible', 'guiVerified'}, set(proof))
        self.assertIs(type(proof['schemaVersion']), int); self.assertEqual(1, proof['schemaVersion'])
        self.assertEqual('windows-x64-harfbuzz-native-meson-source-hook', proof['kind'])
        for field, key in [('path', 'path'), ('condition', 'condition'), ('beforeBytes', 'size'),
                           ('afterBytes', 'afterSize'), ('beforeSha256', 'sha256'), ('afterSha256', 'afterSha256')]:
            self.assertEqual(pin[key], proof[field])
        for phase, key in [('original', 'sha256'), ('effective', 'afterSha256')]:
            path = Path(proof['evidence'][phase])
            self.assertEqual(self.evidence / (phase + '-x64-ExternalProject_harfbuzz.mk'), path)
            self.assertEqual(pin[key], hashlib.sha256(path.read_bytes()).hexdigest())
        for flag in ('nativeBuildVerified', 'fullEngineQualified', 'acceptanceEligible', 'guiVerified'):
            self.assertIs(proof[flag], False)

    def test_x64_harfbuzz_real_cygwin_uses_builtin_host_and_actual_path_conversion(self):
        from suite.tests import test_native_meson_path as replay
        required = os.environ.get('OPENGEUL_MESON_REQUIRE_CYGWIN_REPLAY') == '1'
        if not sys.platform.startswith('cygwin'):
            if required: self.fail('Mandatory real Cygwin Python profile is unavailable')
            self.skipTest('Real Cygwin Python and cygpath are required for native path replay')
        path = 'external/harfbuzz/ExternalProject_harfbuzz.mk'; self.install('x64')
        result = self.harfbuzz_replay((self.source / path).read_bytes(), host=None, adapter=False, prefix='')
        self.assertEqual(0, result.returncode)
        observed = replay.observations(result); self.assertEqual(2, len(observed))
        compiler = self.folder / 'compiler with spaces' / "O'Brien" / 'cl.exe'
        converted = subprocess.run(['/usr/bin/cygpath', '-lm', str(compiler)],
            env={'PATH': '/usr/bin:/bin', 'PYTHONUTF8': '1'}, capture_output=True, text=True, timeout=10)
        self.assertEqual(0, converted.returncode); expected = converted.stdout.strip(); self.assertTrue(expected)
        for item in observed:
            self.assertEqual('real-cygwin-path-and-recipe-replay', item['profileClassification'])
            self.assertTrue(item['builtinMakeHost'].endswith('-cygwin'))
            for name in ('CC', 'CXX'): self.assertEqual([expected], replay.windows_split_args()(item[name]))
        self.assert_harfbuzz_package_scope(observed, setup_entries=2, compile_path=None)


    def test_x64_atl_retains_all_six_exact_recipes_and_group_evidence(self):
        result = self.install('x64')
        self.assertTrue('atlNativePaths' in result['sourceHooks'], 'x64 native ATL source hook is missing')
        proof = result['sourceHooks']['atlNativePaths']
        self.assertEqual({'schemaVersion', 'kind', 'condition', 'recipes', 'nativeBuildVerified',
                          'fullEngineQualified', 'acceptanceEligible', 'guiVerified'}, set(proof))
        self.assertEqual(1, proof['schemaVersion'])
        self.assertEqual('windows-x64-native-atl-source-hooks', proof['kind'])
        self.assertEqual('WNT_X86_64_MSC && MAKE_HOST=%-cygwin', proof['condition'])
        self.assertEqual(6, len(proof['recipes']))
        for i, (pin, row) in enumerate(zip(self.lock['windowsAtlNativePaths']['recipes'], proof['recipes']), 1):
            self.assertEqual({'path', 'beforeBytes', 'afterBytes', 'beforeSha256', 'afterSha256', 'evidence'}, set(row))
            self.assertEqual(pin['path'], row['path'])
            for field, key in [('beforeBytes', 'size'), ('afterBytes', 'afterSize'),
                               ('beforeSha256', 'sha256'), ('afterSha256', 'afterSha256')]:
                self.assertEqual(pin[key], row[field])
            self.assertEqual({'original', 'effective'}, set(row['evidence']))
            for label in ('original', 'effective'):
                path = Path(row['evidence'][label])
                self.assertEqual(self.evidence / f'{label}-x64-atl-{i:02d}-{Path(pin["path"]).name}', path)
                data = path.read_bytes()
                self.assertEqual(self.inputs[pin['path']] if label == 'original' else
                                 (self.source / pin['path']).read_bytes(), data)
            self.assertEqual(pin['afterSha256'], hashlib.sha256((self.source / pin['path']).read_bytes()).hexdigest())
        for key in ('nativeBuildVerified', 'fullEngineQualified', 'acceptanceEligible', 'guiVerified'):
            self.assertIs(proof[key], False)

    @unittest.skipUnless(os.name != 'nt' and shutil.which('make') and shutil.which('bash'),
                         'Portable argv replay does not replace native Windows compilation')
    def test_x64_atl_actual_make_argv_is_native_only_for_msc_cygwin(self):
        from suite.tests import test_native_atl_path as replay
        make, bash = Path(shutil.which('make')), Path(shutil.which('bash'))
        argv_root = self.folder / 'argv'; argv_root.mkdir()
        replay.consumer_adapter(argv_root)
        (argv_root / 'observe.py').write_text('import json,sys;print(json.dumps(sys.argv[1:]))\n')
        library = replay.LIB.replace('/arm64', '/x64')
        self.install('x64')
        # The shared legacy replay copies its mapping; replace the mapping itself
        # so neither this fixture nor that helper reads the real environment.
        synthetic = {'PATH': os.pathsep.join(dict.fromkeys(map(str, (make.parent, bash.parent,
                                                        Path(sys.executable).parent)))), 'PYTHONUTF8': '1'}
        with patch.object(os, 'environ', synthetic):
            for index, pin in enumerate(self.lock['windowsAtlNativePaths']['recipes']):
                name = pin['path']; original = self.inputs[name]; effective = (self.source / name).read_bytes()
                def invoke(raw, **kwargs):
                    return replay.replay_consumer(argv_root, name, raw, make, bash, cpu='X86_64', lib=library, **kwargs)
                before = invoke(original); after = invoke(effective)
                self.assertEqual((0, 0), (before.returncode, after.returncode), name)
                old = replay.observed_argv(before.stdout); actual = replay.observed_argv(after.stdout)
                native_include = replay.NATIVE + '/include'; native_lib = replay.NATIVE + '/lib/spectre/x64'
                expected = [[a.replace(replay.INCLUDE, native_include).replace(library, native_lib) for a in row] for row in old]
                atls = native_lib + '/atls.lib'
                self.assertEqual([[a for a in row if a != atls] for row in expected],
                                 [[a for a in row if a != atls] for row in actual], name)
                self.assertEqual(1 if index < 4 else 0, sum(row.count(atls) for row in actual), name)
                self.assertTrue(any('-I' + native_include in row for row in actual), name)
                self.assertFalse(any('-I' + replay.INCLUDE in row for row in actual), name)
                for kwargs in ({'com': 'GCC'}, {'host': 'x86_64-pc-linux-gnu'}, {'os_value': 'LINUX'}):
                    baseline = invoke(original, **kwargs); candidate = invoke(effective, **kwargs)
                    self.assertEqual((0, 0), (baseline.returncode, candidate.returncode), name)
                    self.assertEqual(baseline.stdout, candidate.stdout, (name, kwargs))
                arm_before = replay.replay_consumer(argv_root, name, original, make, bash, lib=library)
                arm_after = replay.replay_consumer(argv_root, name, effective, make, bash, lib=library)
                self.assertEqual((0, 0), (arm_before.returncode, arm_after.returncode), name)
                self.assertEqual(arm_before.stdout, arm_after.stdout, name)
                for wrong in ('', '/missing/atl', '/empty/atl'):
                    for key in ('include', 'lib'):
                        if index >= 4 and key == 'lib': continue  # Include-only consumers do not use ATL_LIB.
                        rejected = invoke(effective, **{key: wrong}) if key == 'include' else \
                            replay.replay_consumer(argv_root, name, effective, make, bash, cpu='X86_64', lib=wrong)
                        self.assertNotEqual(0, rejected.returncode, (name, key, wrong))

    @unittest.skipUnless(os.name != 'nt' and shutil.which('make') and shutil.which('bash'),
                         'Portable merged argv replay does not replace Windows linking')
    def test_x64_atl_emser_paths_reach_the_authentic_merged_receiver(self):
        from suite.tests import test_native_atl_path as replay
        make, bash = Path(shutil.which('make')), Path(shutil.which('bash'))
        argv_root = self.folder / 'merged-argv'; argv_root.mkdir()
        replay.consumer_adapter(argv_root)
        (argv_root / 'observe.py').write_text('import json,sys;print(json.dumps(sys.argv[1:]))\n')
        self.install('x64'); name = 'embedserv/Library_emser.mk'
        library = replay.LIB.replace('/arm64', '/x64'); native_lib = replay.NATIVE + '/lib/spectre/x64'
        synthetic = {'PATH': os.pathsep.join(dict.fromkeys(map(str, (make.parent, bash.parent,
                                                        Path(sys.executable).parent)))), 'PYTHONUTF8': '1'}
        def links(raw, **kwargs):
            result = replay.replay_emser_merged(argv_root, raw, make, bash, cpu='X86_64', lib=library, **kwargs)
            self.assertEqual(0, result.returncode)
            rows = replay.observed_argv(result.stdout)
            return ([row[1] for row in rows if row[0] == 'include'],
                    {Path(row[0].split('=', 1)[1]).name: row[1:] for row in rows if row[0].startswith('--receiver=')})
        with patch.object(os, 'environ', synthetic):
            original = self.inputs[name]; effective = (self.source / name).read_bytes()
            order, actual = links(effective)
            self.assertEqual(['Library_merged', 'Library_emser'], order)
            self.assertEqual(1, actual['mergedlo.dll'].count(native_lib + '/atls.lib'))
            self.assertEqual(1, actual['mergedlo.dll'].count('-LIBPATH:' + native_lib))
            _, before = links(original)
            strip = lambda row: [a for a in row if a not in (library + '/atls.lib', native_lib + '/atls.lib',
                                                             '-LIBPATH:' + native_lib)]
            self.assertEqual(strip(before['mergedlo.dll']), strip(actual['mergedlo.dll']))
            standalone_order, standalone = links(effective, merged=False)
            self.assertEqual(['Library_emser'], standalone_order)
            self.assertNotIn('mergedlo.dll', standalone)
            self.assertEqual(actual['emserlo.dll'], standalone['emserlo.dll'])

    @unittest.skipUnless(os.name != 'nt' and shutil.which('make') and shutil.which('bash'),
                         'GNU make replay is portable; native CreateProcess remains a Windows gate')
    def test_gpg_make_exports_convert_only_x64_cygwin_compiler_and_preserve_flags(self):
        original=self.gpg_input().read_bytes();self.install('x64');effective=(self.source/GPG_PATH).read_bytes()
        fakebin=self.folder/'fake-bin';fakebin.mkdir();calls=self.folder/'cygpath-calls'
        converter=fakebin/'cygpath'
        converter.write_text('#!'+sys.executable+'\nimport sys\nfrom pathlib import Path\n'
            +'Path('+repr(str(calls))+').open("a").write("1\\n")\n'
            +'assert sys.argv[1:]==["-w","/cygdrive/c/SyntheticTools/cl.exe"]\n'
            +'print("C:\\\\SyntheticTools\\\\cl.exe")\n')
        converter.chmod(0o700)
        observer=self.folder/'gpg-observe.py';observer.write_text(
            'import json,os\nprint(json.dumps({key:os.environ[key] for key in '
            '["REAL_BUILD_CC","REAL_BUILD_CC_FLAGS","CC_FOR_BUILD","RC"]}))\n')
        def replay(raw,cpu,build,os_name='WNT'):
            lines=raw.decode().splitlines(True);first=next(i for i,line in enumerate(lines)
                if line.startswith('gb_WIN_GPG_cross_setup_exports ='))
            last=first
            while lines[last].rstrip().endswith('\\'):last+=1
            definition=''.join(lines[first:last+1])
            makefile=self.folder/'gpg.mk';makefile.write_text(
                'OS := '+os_name+'\nCPUNAME := '+cpu+'\nBUILD_PLATFORM := '+build+'\n'
                +'CC_FOR_BUILD := /cygdrive/c/SyntheticTools/cl.exe -FS -Z7\n'
                +'SOLARINC := -IC:/SyntheticInclude\nILIB_FOR_BUILD := C:/SyntheticLib\n'
                +'gb_WIN_GPG_WINDRES_target := pe-x86-64\n'
                +'gb_Executable_get_target_for_build = /synthetic/$(1)\n'+definition
                +'\n.PHONY: all\nall:\n\t@$(gb_WIN_GPG_cross_setup_exports) && '
                +shlex.quote(sys.executable)+' '+shlex.quote(str(observer))+'\n')
            calls.unlink(missing_ok=True)
            env={'PATH':str(fakebin)+':/workspace/toolcache/opengeul-validation/powershell:/usr/bin:/bin',
                 'XDG_CACHE_HOME':'/workspace/toolcache/opengeul-validation/cache',
                 'XDG_CONFIG_HOME':'/workspace/toolcache/opengeul-validation/config',
                 'XDG_DATA_HOME':'/workspace/toolcache/opengeul-validation/data','PYTHONUTF8':'1'}
            result=subprocess.run(['make','--no-print-directory','-f',str(makefile),'SHELL=/bin/bash'],
                capture_output=True,text=True,timeout=10,env=env)
            self.assertEqual(0,result.returncode,'synthetic make evaluation failed')
            return json.loads(result.stdout),len(calls.read_text().splitlines()) if calls.exists() else 0
        baseline,count=replay(original,'X86_64','x86_64-pc-cygwin')
        self.assertEqual('/cygdrive/c/SyntheticTools/cl.exe',baseline['REAL_BUILD_CC']);self.assertEqual(0,count)
        actual,count=replay(effective,'X86_64','x86_64-pc-cygwin')
        self.assertEqual('C:\\SyntheticTools\\cl.exe',actual['REAL_BUILD_CC'],'GPG native compiler path was not converted')
        self.assertEqual(1,count);self.assertEqual('-FS -Z7',actual['REAL_BUILD_CC_FLAGS'])
        self.assertEqual({key:value for key,value in baseline.items() if key!='REAL_BUILD_CC'},
                         {key:value for key,value in actual.items() if key!='REAL_BUILD_CC'})
        for os_name,cpu,build in [('WNT','AARCH64','aarch64-pc-cygwin'),
                                  ('WNT','X86_64','x86_64-pc-windows-msvc'),('LINUX','X86_64','x86_64-pc-cygwin')]:
            with self.subTest(os=os_name,cpu=cpu,build=build):
                self.assertEqual((baseline,0),replay(effective,cpu,build,os_name))

    def test_gpg_hook_retains_exact_source_evidence_and_false_qualification(self):
        result=self.install('x64');self.assertIn('gpgBuildCompilerPath',result['sourceHooks'],'missing GPG source hook')
        proof=result['sourceHooks']['gpgBuildCompilerPath'];pin=self.lock['windowsGpgBuildCompilerPath']
        self.assertEqual({'schemaVersion','kind','path','condition','beforeBytes','afterBytes','beforeSha256','afterSha256',
            'evidence','nativeBuildVerified','fullEngineQualified','acceptanceEligible','guiVerified'},set(proof))
        self.assertEqual('windows-gpg-build-compiler-path-source-hook',proof['kind'])
        self.assertEqual(GPG_CONDITION,proof['condition'])
        for field,key in [('beforeBytes','size'),('afterBytes','afterSize'),('beforeSha256','sha256'),('afterSha256','afterSha256')]:
            self.assertEqual(pin[key],proof[field])
        self.assertEqual(GPG_FIXTURE.read_bytes(),Path(proof['evidence']['original']).read_bytes())
        self.assertEqual((self.source/GPG_PATH).read_bytes(),Path(proof['evidence']['effective']).read_bytes())
        for field in ['nativeBuildVerified','fullEngineQualified','acceptanceEligible','guiVerified']:
            self.assertIs(proof[field],False)
        before={p.relative_to(self.source).as_posix():p.read_bytes() for p in self.source.rglob('*') if p.is_file()}
        with self.assertRaises(ValueError):self.install('x64')
        self.assertEqual(before,{p.relative_to(self.source).as_posix():p.read_bytes() for p in self.source.rglob('*') if p.is_file()})

    def test_gpg_input_drift_is_rejected_before_any_source_or_evidence_write(self):
        target=self.gpg_input();self.policy_input();target.write_bytes(target.read_bytes()+b'\n')
        before={p.relative_to(self.source).as_posix():p.read_bytes() for p in self.source.rglob('*') if p.is_file()}
        with self.assertRaises(ValueError):self.install('x64')
        self.assertEqual([],list(self.evidence.iterdir()))
        self.assertEqual(before,{p.relative_to(self.source).as_posix():p.read_bytes() for p in self.source.rglob('*') if p.is_file()})

    def test_arm_still_has_exactly_twenty_one_outputs(self):
        self.install('arm64')
        self.assertEqual(21,sum(p.is_file() for p in self.source.rglob('*')))
        self.assertFalse((self.source/GPG_PATH).exists())

    @unittest.skipUnless(os.name != 'nt' and shutil.which('make'),
                         'GNU make target-policy replay is portable; Windows unpack remains a separate gate')
    def test_x64_zstd_sys_mode_is_confined_to_the_exact_cpu_and_unpack_target(self):
        name = 'external/zstd/UnpackedTarball_zstd.mk'
        original = self.inputs[name]
        self.install('x64'); effective = (self.source / name).read_bytes()
        observer = self.folder / 'link-mode.py'
        observer.write_text("import json,os\nprint(json.dumps(os.environ['CYGWIN']))\n")
        def replay(raw, os_name, cpu, target):
            recipe = self.folder / 'zstd.mk'; recipe.write_bytes(raw)
            makefile = self.folder / 'policy.mk'
            makefile.write_text('OS := ' + os_name + '\nCPUNAME := ' + cpu + '\nMSYSTEM :=\n'
                'CYGWIN := winsymlinks:nativestrict\nexport CYGWIN\nZSTD_TARBALL := zstd-source\n'
                'gb_UnpackedTarget_get_target = $(1)\ninclude ' + shlex.quote(str(recipe)) + '\n'
                '.PHONY: zstd-source other-source\nzstd-source other-source:\n\t@'
                + shlex.quote(sys.executable) + ' ' + shlex.quote(str(observer)) + '\n')
            result = subprocess.run(['make', '--no-print-directory', '-f', str(makefile), target],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            return json.loads(result.stdout)
        self.assertEqual('winsymlinks:nativestrict', replay(original, 'WNT', 'X86_64', 'zstd-source'))
        self.assertEqual('winsymlinks:sys', replay(effective, 'WNT', 'X86_64', 'zstd-source'))
        for os_name, cpu, target in [('WNT', 'X86_64', 'other-source'),
                                     ('WNT', 'AARCH64', 'zstd-source'), ('LINUX', 'X86_64', 'zstd-source')]:
            with self.subTest(os=os_name, cpu=cpu, target=target):
                self.assertEqual('winsymlinks:nativestrict', replay(effective, os_name, cpu, target))
        arm_source = self.folder / 'arm-zstd'; arm_path = arm_source / name
        arm_path.parent.mkdir(parents=True); arm_path.write_bytes(original)
        _, _, arm = self.module.ARM._zstd_source_links(arm_source, self.lock['zstdSourceLinks'])
        self.assertEqual('winsymlinks:sys', replay(arm, 'WNT', 'AARCH64', 'zstd-source'))
        self.assertEqual('winsymlinks:nativestrict', replay(arm, 'WNT', 'X86_64', 'zstd-source'))

    def test_x64_zstd_hook_retains_exact_raw_evidence_and_false_qualification_flags(self):
        result = self.install('x64')
        self.assertIn('zstdSourceLinks', result['sourceHooks'])
        proof = result['sourceHooks']['zstdSourceLinks']; pin = self.lock['windowsZstdSourceLinks']
        self.assertEqual({'schemaVersion', 'kind', 'path', 'condition', 'beforeBytes', 'afterBytes',
                          'beforeSha256', 'afterSha256', 'evidence', 'nativeBuildVerified',
                          'fullEngineQualified', 'acceptanceEligible', 'guiVerified'}, set(proof))
        self.assertEqual('windows-zstd-source-links-source-hook', proof['kind'])
        self.assertEqual('WNT_X86_64', proof['condition'])
        self.assertEqual(self.inputs[pin['path']], Path(proof['evidence']['original']).read_bytes())
        self.assertEqual((self.source / pin['path']).read_bytes(), Path(proof['evidence']['effective']).read_bytes())
        for field, key in [('beforeBytes', 'size'), ('afterBytes', 'afterSize'),
                           ('beforeSha256', 'sha256'), ('afterSha256', 'afterSha256')]:
            self.assertEqual(pin[key], proof[field])
        for field in ['nativeBuildVerified', 'fullEngineQualified', 'acceptanceEligible', 'guiVerified']:
            self.assertIs(proof[field], False)

    @unittest.skipUnless(os.name != 'nt' and shutil.which('make') and shutil.which('bash'),
                         'This nested GNU make replay requires POSIX make/Bash; it is not native Windows proof')
    def test_windows_loader_paths_survive_both_make_levels_for_each_owned_recipe(self):
        fixture = ROOT / 'suite/tests/fixtures/native-icu-path'
        for row in json.loads((fixture / 'source.json').read_text())['members']:
            self.assertEqual(row['fixtureSha256'], hashlib.sha256((fixture / row['fixture']).read_bytes()).hexdigest())
        project = 'external/firebird/ExternalProject_firebird.mk'
        original = self.inputs[project]
        self.install('x64'); x64 = (self.source / project).read_bytes()
        arm_source = self.folder / 'arm-source'; arm_source.mkdir()
        for name, raw in self.inputs.items():
            target = arm_source / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(raw)
        arm_evidence = self.folder / 'arm-evidence'; arm_evidence.mkdir()
        self.module.apply_native_source(arm_source, arm_evidence, architecture='arm64')
        arm = (arm_source / project).read_bytes()
        observer = self.folder / 'observe.py'
        observer.write_text("import json,os\np=os.environ['PATH'].split(':')\n"
                            "print(json.dumps({'icu':'/cygdrive/c/source/workdir/UnpackedTarball/icu/source/lib' in p,"
                            "'client':'/cygdrive/c/source/workdir/UnpackedTarball/firebird/gen/Release/firebird/bin' in p,"
                            "'concatenated':any('libPATH=' in x for x in p)}))\n")
        inner = self.folder / 'inner.mk'
        # These path rules match the pinned Firebird examples/defaults and its
        # locked Cygwin patch: examples runs a copy of isql outside BIN.
        inner.write_text('ROOT := C:/source/workdir/UnpackedTarball/firebird\nTARGET := Release\n'
                         'GEN_ROOT=$(ROOT)/gen\nFB_BUILD=$(GEN_ROOT)/$(TARGET)/firebird\nBIN=$(FB_BUILD)/bin\n'
                         'PATH := ./:$(BIN):$(PATH)\nexport PATH\nall:\n\t$(LIBO_TUNNEL_LIBRARY_PATH) '
                         + shlex.quote(sys.executable) + ' ' + shlex.quote(str(observer)) + '\n')
        def replay(raw, cpu):
            assignment = next(line.strip().removesuffix(' \\') for line in raw.decode().splitlines()
                              if line.strip().startswith('LIBO_TUNNEL_LIBRARY_PATH='))
            variables = 'OS := WNT\nCPUNAME := ' + cpu + '\n'
            for key, suffix in [('SRCDIR', ''), ('BUILDDIR', ''), ('INSTDIR', '/instdir'),
                                ('WORKDIR', '/workdir'), ('TARFILE_LOCATION', '/downloads')]:
                variables += key + ' := C:/source' + suffix + '\n' + key + '_CYG := /cygdrive/c/source' + suffix + '\n'
            variables += ('INSTDIR_FOR_BUILD := $(INSTDIR)\nLIBO_URE_LIB_FOLDER := program\nLIBO_BIN_FOLDER := program\n'
                          'gb_UnpackedTarball_workdir := $(WORKDIR)/UnpackedTarball\n'
                          'firebird_BUILDDIR := $(gb_UnpackedTarball_workdir)/firebird/gen/Release/firebird\n')
            outer = self.folder / 'outer.mk'
            outer.write_text(variables + (fixture / 'cyg-path.mk').read_text() + '\n'
                             + (fixture / 'windows-loader-path.mk').read_text() + '\nall:\n\t$(MAKE) --no-print-directory -f '
                             + shlex.quote(str(inner)) + ' ' + assignment + '\n')
            result = subprocess.run(['make', '--no-print-directory', '-f', str(outer), 'SHELL=' + shutil.which('bash')],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            return json.loads(result.stdout.splitlines()[-1])
        for cpu, effective in [('X86_64', x64), ('AARCH64', arm)]:
            with self.subTest(cpu=cpu):
                self.assertEqual({'icu': False, 'client': False, 'concatenated': True}, replay(original, cpu))
                self.assertEqual({'icu': True, 'client': True, 'concatenated': False}, replay(effective, cpu))
        self.assertEqual(replay(original, 'X86_64'), replay(arm, 'X86_64'))
        self.assertEqual(replay(original, 'AARCH64'), replay(x64, 'AARCH64'))

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
        self.assertEqual(13 if architecture == 'arm64' else 4, len(proof['armGuardedSources']))
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

    def test_x64_recipe_applies_exactly_bootstrap_loader_zstd_gpg_atl_meson_then_winacc(self):
        events = []; bootstrap = self.module.ARM.install_module_bootstrap; winacc = self.module.WINACC.install
        loader = self.module._install_firebird_loader_path
        zstd = self.module._install_zstd_source_links
        gpg = self.module._install_gpg_build_compiler_path
        atl = self.module._install_atl_native_paths
        meson = self.module._install_harfbuzz_native_meson_paths
        cli_policy = self.module._install_cli_policy_platform
        def common(*args): events.append('moduleBootstrap'); return bootstrap(*args)
        def loader_path(*args): events.append('firebirdLoaderPath'); return loader(*args)
        def zstd_links(*args): events.append('zstdSourceLinks'); return zstd(*args)
        def gpg_path(*args): events.append('gpgBuildCompilerPath'); return gpg(*args)
        def atl_paths(*args): events.append('atlNativePaths'); return atl(*args)
        def meson_paths(*args): events.append('harfbuzzNativeMesonPaths'); return meson(*args)
        def cli_platform(*args): events.append('cliPublisherPolicyPlatform'); return cli_policy(*args)
        def focus(*args): events.append('winAccFocusOrder'); return winacc(*args)
        with patch.object(self.module.ARM, 'install', side_effect=AssertionError('x64 selected full ARM installer')), \
                patch.object(self.module.ARM, 'install_module_bootstrap', side_effect=common), \
                patch.object(self.module, '_install_firebird_loader_path', side_effect=loader_path), \
                patch.object(self.module, '_install_zstd_source_links', side_effect=zstd_links), \
                patch.object(self.module, '_install_gpg_build_compiler_path', side_effect=gpg_path), \
                patch.object(self.module, '_install_atl_native_paths', side_effect=atl_paths), \
                patch.object(self.module, '_install_harfbuzz_native_meson_paths', side_effect=meson_paths), \
                patch.object(self.module, '_install_cli_policy_platform', side_effect=cli_platform), \
                patch.object(self.module.WINACC, 'install', side_effect=focus):
            result = self.install('x64')
        self.proof(result, 'x64'); self.assertEqual(ORDERS['x64'], events)
        hooks = result['sourceHooks']
        self.assertEqual({'kind', 'architecture', 'moduleBootstrap', 'firebirdLoaderPath', 'zstdSourceLinks', 'gpgBuildCompilerPath', 'atlNativePaths', 'harfbuzzNativeMesonPaths', 'cliPublisherPolicyPlatform',
                          'nativeBuildVerified', 'basePersistenceVerified'}, set(hooks))
        self.assertEqual('native-windows-common-source-hooks', hooks['kind']); self.assertEqual('x64', hooks['architecture'])
        self.assertIs(hooks['nativeBuildVerified'], False); self.assertIs(hooks['basePersistenceVerified'], False)
        for row in self.plan['sources'][:4]:
            self.assertEqual(row['afterSha256'], hashlib.sha256((self.source / row['path']).read_bytes()).hexdigest())
        pin = self.lock['windowsFirebirdLoaderPath']; proof = hooks['firebirdLoaderPath']
        self.assertEqual({'schemaVersion', 'kind', 'path', 'condition', 'beforeBytes', 'afterBytes',
                          'beforeSha256', 'afterSha256', 'evidence', 'nativeBuildVerified',
                          'fullEngineQualified', 'acceptanceEligible', 'guiVerified'}, set(proof))
        self.assertEqual('windows-firebird-loader-path-source-hook', proof['kind'])
        self.assertEqual(pin['path'], proof['path']); self.assertEqual(pin['condition'], proof['condition'])
        for field, key in [('beforeBytes', 'size'), ('afterBytes', 'afterSize'),
                           ('beforeSha256', 'sha256'), ('afterSha256', 'afterSha256')]:
            self.assertEqual(pin[key], proof[field])
        self.assertEqual(self.inputs[pin['path']], Path(proof['evidence']['original']).read_bytes())
        self.assertEqual((self.source / pin['path']).read_bytes(), Path(proof['evidence']['effective']).read_bytes())
        for field in ['nativeBuildVerified', 'fullEngineQualified', 'acceptanceEligible', 'guiVerified']:
            self.assertIs(proof[field], False)

    def test_x64_leaves_all_four_remaining_arm_only_targets_unchanged(self):
        result = self.install('x64'); self.proof(result, 'x64')
        changed = {name for name, raw in self.inputs.items() if (self.source / name).read_bytes() != raw}
        if (self.source/GPG_PATH).read_bytes()!=GPG_FIXTURE.read_bytes():changed.add(GPG_PATH)
        policy_path = 'cli_ure/CliNativeLibrary_cli_cppuhelper.mk'
        if (self.source / policy_path).read_bytes() != (ROOT / 'suite/tests/fixtures/native-cli-policy' / policy_path).read_bytes():
            changed.add(policy_path)
        self.assertEqual({'bin/unpack-sources', self.lock['winAccFocusOrder']['path'],
                          self.lock['windowsFirebirdLoaderPath']['path'],
                          self.lock['windowsZstdSourceLinks']['path'], GPG_PATH, self.lock['windowsHarfbuzzNativeMesonPaths']['path'],
                          *(pin['path'] for pin in self.lock['windowsAtlNativePaths']['recipes']),
                          'cli_ure/CliNativeLibrary_cli_cppuhelper.mk'}, changed)
        self.assertEqual(set(self.inputs)|{GPG_PATH, 'cli_ure/CliNativeLibrary_cli_cppuhelper.mk'}, {p.relative_to(self.source).as_posix() for p in self.source.rglob('*') if p.is_file()})

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

    def test_changed_loader_output_cannot_publish_x64_success(self):
        install = self.module._install_firebird_loader_path
        def corrupt(*args):
            result = install(*args)
            (self.source / self.lock['windowsFirebirdLoaderPath']['path']).write_bytes(b'changed loader output')
            return result
        with patch.object(self.module, '_install_firebird_loader_path', side_effect=corrupt) as loader:
            with self.assertRaises(ValueError): self.install('x64')
            self.assertEqual(1, loader.call_count)

    def test_cli_and_repeat_application_fail_closed(self):
        self.gpg_input(); self.policy_input()
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
