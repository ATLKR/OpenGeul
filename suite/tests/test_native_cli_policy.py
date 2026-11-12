"""Replay publisher-policy target flags; native PE qualification stays separate."""
import importlib.util
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / 'suite/engine-build'
FIXTURE = ROOT / 'suite/tests/fixtures/native-cli-policy'
POLICY_PATH = 'cli_ure/CliNativeLibrary_cli_cppuhelper.mk'


def recipe():
    spec = importlib.util.spec_from_file_location('cli_policy_source_recipe', ENGINE / 'apply_native_source.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CliPublisherPolicyTests(unittest.TestCase):
    def pin(self):
        return json.loads((ENGINE / 'source-build.json').read_bytes())['windowsCliPublisherPolicyPlatform']

    def test_public_source_fixture_is_pinned_to_the_core_commit(self):
        pins = json.loads((FIXTURE / 'source.json').read_bytes())
        self.assertEqual('9dea406ab7695df6325b11b0e19fdca8db4b7276', pins['coreCommit'])
        self.assertEqual(['solenv/gbuild/CliAssembly.mk', 'solenv/gbuild/CliNativeLibrary.mk', POLICY_PATH],
                         [row['path'] for row in pins['files']])
        for row in pins['files']:
            raw = (FIXTURE / row['path']).read_bytes()
            self.assertEqual(row['size'], len(raw))
            self.assertEqual(row['sha256'], hashlib.sha256(raw).hexdigest())

    def replay(self, raw, *, platform_os='WNT', cpu='X86_64', target='cli_cppuhelper'):
        folder = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        source = folder / 'source'; source.mkdir()
        (source / 'cli_ure/version').mkdir(parents=True)
        (source / POLICY_PATH).write_bytes(raw)
        (source / 'cli_ure/version/version.txt').write_text(
            'CLI_CPPUHELPER_POLICY_ASSEMBLY := policy.1.0.cli_cppuhelper.dll\n'
            'CLI_CPPUHELPER_POLICY_VERSION := 1.0.0.0\n')
        for name in ('cli_ure/source/native/cli_cppuhelper_config',
                     'cli_ure/source/cliuno.snk', 'solenv/bin/clipatchconfig.pl'):
            path = source / name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'synthetic fixture only\n')
        work = folder / 'work'
        getters = {
            'CliConfigTarget_get_target': 'config', 'CliConfigTarget_get_clean_target': 'config-clean',
            'CliAssemblyTarget_get_target': 'assembly', 'CliAssemblyTarget_get_clean_target': 'assembly-clean',
            'CliAssemblyTarget_get_assembly_target': 'output', 'CliAssemblyTarget_get_dll': 'library',
            'CliAssembly_get_target': 'assembly-mark', 'CliAssembly_get_clean_target': 'assembly-mark-clean',
            'CliNativeLibrary_get_target': 'native', 'CliNativeLibrary_get_clean_target': 'native-clean',
            'CliNativeLibrary_get_preparation_target': 'native-prepare',
            'Library_get_target': 'library', 'Library_get_headers_target': 'headers'}
        lines = ['SRCDIR := ' + source.as_posix(), 'WORKDIR := ' + work.as_posix(),
                 'OS := ' + platform_os, 'CPUNAME := ' + cpu,
                 'GNUCOPY := cp', 'PERL := perl', 'gb_Helper_abbreviate_dirs = $(1)',
                 'gb_Helper_MISCDUMMY := synthetic']
        lines += ['gb_' + name + ' = $(WORKDIR)/' + part + '/$(1)' for name, part in getters.items()]
        lines += ['include ' + (FIXTURE / name).as_posix() for name in
                  ('solenv/gbuild/CliAssembly.mk', 'solenv/gbuild/CliNativeLibrary.mk')]
        lines += ['include ' + (source / POLICY_PATH).as_posix()]
        if target != 'cli_cppuhelper':
            lines += ['$(eval $(call gb_CliNativeLibrary_CliNativeLibrary,' + target + '))',
                      '$(eval $(call gb_CliNativeLibrary_set_configfile,' + target + ',cli_ure/source/native/cli_cppuhelper_config,cli_ure/version/version.txt))',
                      '$(eval $(call gb_CliNativeLibrary_set_policy,' + target + ',policy.synthetic.dll,1.0.0.0))']
        makefile = folder / 'Makefile'; makefile.write_text('\n'.join(lines) + '\n')
        command = ['make', '--no-print-directory', '-n', '-rR', '-f', str(makefile),
                   str(work / 'assembly' / target)]
        result = subprocess.run(command, cwd=folder, env={'PATH': '/usr/bin:/bin', 'PYTHONUTF8': '1'},
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
        self.assertEqual(0, result.returncode, 'GNU make policy recipe replay failed')
        text = result.stdout.decode('utf-8')
        options = re.findall(r'-(platform|version|out|keyfile|link):([^\s&]+)', text)
        self.assertEqual(1, sum(name == 'platform' for name, _ in options))
        return {name: value.replace(folder.as_posix(), '<fixture>') for name, value in options}

    def test_x64_policy_transform_is_present(self):
        self.assertTrue(callable(getattr(recipe(), '_cli_policy_bytes', None)),
                        'Authenticated x64 publisher policy source transform is missing')

    @unittest.skipUnless(os.name != 'nt' and shutil.which('make'), 'POSIX GNU make recipe replay')
    def test_x64_policy_recipe_targets_the_native_assembly_architecture(self):
        module = recipe(); raw = (FIXTURE / POLICY_PATH).read_bytes()
        transform = getattr(module, '_cli_policy_bytes', None)
        if callable(transform):
            pin = json.loads((ENGINE / 'source-build.json').read_bytes())['windowsCliPublisherPolicyPlatform']
            raw = transform(raw, pin)
        self.assertEqual('x64', self.replay(raw)['platform'])

    @unittest.skipUnless(os.name != 'nt' and shutil.which('make'), 'POSIX GNU make recipe replay')
    def test_original_recipe_targets_x86_and_change_preserves_nonplatform_arguments(self):
        raw = (FIXTURE / POLICY_PATH).read_bytes()
        before = self.replay(raw)
        after = self.replay(recipe()._cli_policy_bytes(raw, self.pin()))
        self.assertEqual('x86', before.pop('platform'))
        self.assertEqual('x64', after.pop('platform'))
        self.assertEqual(before, after)
        self.assertEqual({'out', 'version', 'keyfile', 'link'}, set(after))

    @unittest.skipUnless(os.name != 'nt' and shutil.which('make'), 'POSIX GNU make recipe replay')
    def test_other_platforms_and_other_native_cli_targets_keep_original_recipe(self):
        raw = (FIXTURE / POLICY_PATH).read_bytes()
        effective = recipe()._cli_policy_bytes(raw, self.pin())
        for profile in ({'cpu': 'INTEL'}, {'cpu': 'AARCH64'}, {'platform_os': 'LINUX'},
                        {'target': 'synthetic_other_cli'}):
            with self.subTest(profile=profile):
                before = self.replay(raw, **profile)
                after = self.replay(effective, **profile)
                self.assertEqual('x86', before['platform'])
                self.assertEqual(before, after)

    def test_transform_rejects_changed_repeated_and_forged_inputs(self):
        module = recipe(); raw = (FIXTURE / POLICY_PATH).read_bytes(); pin = self.pin()
        effective = module._cli_policy_bytes(raw, pin)
        self.assertEqual((1119, '6519e9014c32f8323e3501f49d189e6da428b3d3b1f85d7ad96471aedcfd051f'),
                         (len(effective), hashlib.sha256(effective).hexdigest()))
        for field, value in [('path', '../escape'), ('condition', 'WNT_AARCH64'), ('size', True),
                             ('afterSize', 1.5), ('sha256', '0' * 64), ('afterSha256', '0' * 64), ('extra', False)]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                module._cli_policy_bytes(raw, dict(pin, **{field: value}))
        for changed in (raw + b'\n', effective):
            with self.assertRaises(ValueError): module._cli_policy_bytes(changed, pin)
        duplicate = raw + b'$(eval $(call gb_CliNativeLibrary_CliNativeLibrary,cli_cppuhelper))\n'
        forged = dict(pin, size=len(duplicate), sha256=hashlib.sha256(duplicate).hexdigest())
        with self.assertRaises(ValueError): module._cli_policy_bytes(duplicate, forged)

    def test_plan_adds_only_the_policy_source_to_x64_and_preserves_arm(self):
        module = recipe(); lock = json.loads((ENGINE / 'source-build.json').read_bytes())
        policy = (ENGINE / 'native-targets.json').read_bytes()
        arm = module._select_plan(lock, policy, 'arm64'); x64 = module._select_plan(lock, policy, 'x64')
        self.assertEqual('9b10511f31066a5966014c6357268b4d1dcfa3ffa24eb9c97c8bc0c05dbef0fe',
                         hashlib.sha256(json.dumps(arm, sort_keys=True, separators=(',', ':')).encode()).hexdigest())
        self.assertNotIn(POLICY_PATH, [row['path'] for row in arm['sources']])
        self.assertEqual(1, sum(row['path'] == POLICY_PATH for row in x64['sources']))
        self.assertNotIn(POLICY_PATH, [row['path'] for row in x64['armGuardedSources']])
        self.assertEqual(['cliPublisherPolicyPlatform', 'x86CompanionStaticRuntime', 'winAccFocusOrder', 'flexFatalCompatibility', 'dotnetProjectGraph'], x64['recipe']['hooks'][-5:])
        for field, value in [('path', '../escape'), ('condition', 'WNT_AARCH64'), ('size', True),
                             ('afterSize', 1.5), ('sha256', 'invalid'), ('afterSha256', 'invalid'), ('extra', False)]:
            changed = copy.deepcopy(lock); changed['windowsCliPublisherPolicyPlatform'][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                module._select_plan(changed, policy, 'x64')

    def test_installer_retains_original_and_effective_source_without_qualification(self):
        module = recipe(); pin = self.pin(); raw = (FIXTURE / POLICY_PATH).read_bytes()
        folder = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        source = folder / 'source'; target = source / POLICY_PATH; target.parent.mkdir(parents=True)
        target.write_bytes(raw); evidence = folder / 'evidence'; evidence.mkdir()
        proof = module._install_cli_policy_platform(source, evidence, pin)
        self.assertEqual(raw, Path(proof['evidence']['original']).read_bytes())
        effective = module._cli_policy_bytes(raw, pin)
        self.assertEqual(effective, target.read_bytes())
        self.assertEqual(effective, Path(proof['evidence']['effective']).read_bytes())
        for flag in ('nativeBuildVerified', 'fullEngineQualified', 'acceptanceEligible', 'guiVerified'):
            self.assertIs(False, proof[flag])
        with self.assertRaises(ValueError): module._install_cli_policy_platform(source, evidence, pin)
        self.assertEqual(effective, target.read_bytes())


if __name__ == '__main__':
    unittest.main()
