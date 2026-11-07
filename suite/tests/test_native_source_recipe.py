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
          'x64': ['moduleBootstrap', 'firebirdLoaderPath', 'zstdSourceLinks', 'winAccFocusOrder']}
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
    def test_x64_zstd_source_link_exception_reclassifies_only_its_exact_input(self):
        module = load('apply_native_source'); lock = manifest()
        raw = (ENGINE / 'native-targets.json').read_bytes()
        plan = module._select_plan(lock, raw, 'x64')
        self.assertEqual(11, len(plan['armGuardedSources']))
        self.assertNotIn('external/zstd/UnpackedTarball_zstd.mk',
                         [row['path'] for row in plan['armGuardedSources']])
        self.assertEqual(['moduleBootstrap', 'firebirdLoaderPath', 'zstdSourceLinks', 'winAccFocusOrder'],
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
        self.assertEqual(11, len(plan['armGuardedSources']))
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
            self.assertEqual(13 if architecture == 'arm64' else 11, len(plan['armGuardedSources']))
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
        self.assertEqual(13 if architecture == 'arm64' else 11, len(proof['armGuardedSources']))
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

    def test_x64_recipe_applies_exactly_bootstrap_loader_zstd_then_winacc(self):
        events = []; bootstrap = self.module.ARM.install_module_bootstrap; winacc = self.module.WINACC.install
        loader = self.module._install_firebird_loader_path
        zstd = self.module._install_zstd_source_links
        def common(*args): events.append('moduleBootstrap'); return bootstrap(*args)
        def loader_path(*args): events.append('firebirdLoaderPath'); return loader(*args)
        def zstd_links(*args): events.append('zstdSourceLinks'); return zstd(*args)
        def focus(*args): events.append('winAccFocusOrder'); return winacc(*args)
        with patch.object(self.module.ARM, 'install', side_effect=AssertionError('x64 selected full ARM installer')), \
                patch.object(self.module.ARM, 'install_module_bootstrap', side_effect=common), \
                patch.object(self.module, '_install_firebird_loader_path', side_effect=loader_path), \
                patch.object(self.module, '_install_zstd_source_links', side_effect=zstd_links), \
                patch.object(self.module.WINACC, 'install', side_effect=focus):
            result = self.install('x64')
        self.proof(result, 'x64'); self.assertEqual(ORDERS['x64'], events)
        hooks = result['sourceHooks']
        self.assertEqual({'kind', 'architecture', 'moduleBootstrap', 'firebirdLoaderPath', 'zstdSourceLinks',
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

    def test_x64_leaves_all_11_arm_only_targets_unchanged(self):
        result = self.install('x64'); self.proof(result, 'x64')
        changed = {name for name, raw in self.inputs.items() if (self.source / name).read_bytes() != raw}
        self.assertEqual({'bin/unpack-sources', self.lock['winAccFocusOrder']['path'],
                          self.lock['windowsFirebirdLoaderPath']['path'],
                          self.lock['windowsZstdSourceLinks']['path']}, changed)
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
