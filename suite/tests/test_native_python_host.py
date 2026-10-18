"""Replay the authenticated Python recipe; no Windows build claim is made here."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
PORT = ROOT / 'suite/engine-build'
FIXTURE = ROOT / 'suite/tests/fixtures/native-python-host/ExternalProject_python3.mk'
RECIPE_SHA = 'b31e4d779484a4d153155b025daf8b03678e1984abde4fe5c6c038ccb7d43445'


def installer():
    spec = importlib.util.spec_from_file_location('python_host_installer', PORT / 'enable_firebird_arm64.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def require_posix_recipe_replay(os_name, make, bash, required):
    """Native Windows unit discovery skips; the Cygwin source gate must replay."""
    if os_name == 'nt' or not make.is_file() or not bash.is_file():
        message = 'POSIX GNU make/Bash recipe replay requires a POSIX Python and both tools'
        if required:
            raise AssertionError('Mandatory '+message)
        raise unittest.SkipTest(message)
    return make, bash


class PythonHostReplayCapabilityTests(unittest.TestCase):
    def capability(self, os_name, make, bash, required):
        self.assertTrue(callable(globals().get('require_posix_recipe_replay')),
                        'Explicit POSIX replay capability gate is missing')
        return require_posix_recipe_replay(os_name, make, bash, required)

    def test_native_windows_replay_is_named_skip_without_strict_source_mode(self):
        with self.assertRaisesRegex(unittest.SkipTest, 'POSIX GNU make/Bash'):
            self.capability('nt', Path('/usr/bin/make'), Path('/bin/bash'), False)

    def test_strict_source_mode_rejects_windows_or_missing_replay_tools(self):
        for os_name, make, bash in (
                ('nt', Path('/usr/bin/make'), Path('/bin/bash')),
                ('posix', Path('/missing/opengeul/make'), Path('/bin/bash')),
                ('posix', Path('/usr/bin/make'), Path('/missing/opengeul/bash'))):
            with self.subTest(os_name=os_name, make=str(make), bash=str(bash)):
                with self.assertRaisesRegex(AssertionError, 'Mandatory POSIX GNU make/Bash'):
                    self.capability(os_name, make, bash, True)

    def test_missing_tools_have_named_skip_without_strict_source_mode(self):
        with self.assertRaisesRegex(unittest.SkipTest, 'POSIX GNU make/Bash'):
            self.capability('posix', Path('/missing/opengeul/make'), Path('/bin/bash'), False)


class PythonHostSourceTests(unittest.TestCase):
    def lock(self):
        lock = json.loads((PORT / 'source-build.json').read_text())
        self.assertTrue('pythonNativeHost' in lock, 'Python native host source hook is missing')
        return lock['pythonNativeHost']

    def test_authentic_recipe_uses_late_import_only_for_windows_arm64(self):
        lock = self.lock()
        self.assertEqual(RECIPE_SHA, hashlib.sha256(FIXTURE.read_bytes()).hexdigest())
        provenance = json.loads(FIXTURE.with_name('source.json').read_text())
        self.assertEqual('296ba78e7ab0d381b94c3d6342f4ebb2320ee5097ca58781b9b744cab90b9785', provenance['archiveSha256'])
        self.assertEqual(RECIPE_SHA, provenance['sha256'])
        with tempfile.TemporaryDirectory(prefix='python host ') as folder:
            root = Path(folder)
            target = root / lock['recipe']['path']; target.parent.mkdir(parents=True)
            target.write_bytes(FIXTURE.read_bytes())
            planned = installer()._python_native_host(root, lock)
            self.assertEqual(target, planned[0])
            original, effective = planned[1:3]
            self.assertEqual(FIXTURE.read_bytes(), original)
            self.assertEqual(lock['recipe']['afterSha256'], hashlib.sha256(effective).hexdigest())
            self.assertEqual(planned[4], (PORT / lock['targets']['filename']).read_bytes())

    def test_payload_changes_only_arm64_compiler_and_linker_host(self):
        lock = self.lock()
        raw = (PORT / lock['targets']['filename']).read_bytes()
        self.assertEqual(lock['targets']['sha256'], hashlib.sha256(raw).hexdigest())
        tree = ET.fromstring(raw)
        ns = '{http://schemas.microsoft.com/developer/msbuild/2003}'
        self.assertEqual([ns+'PropertyGroup'], [item.tag for item in tree])
        group = tree[0]
        self.assertEqual("'$(Platform)' == 'ARM64'", group.attrib['Condition'])
        self.assertEqual({'CLToolPath': '$(VCToolsInstallDir)bin\\Hostarm64\\arm64\\',
                          'LinkToolPath': '$(CLToolPath)'},
                         {item.tag.removeprefix(ns): item.text for item in group})
        self.assertEqual({'Condition'}, set(group.attrib))
        self.assertFalse(any(item.attrib for item in group))

    def test_changed_missing_linked_recipe_or_payload_collision_fails_before_writes(self):
        lock = self.lock()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); target = root / lock['recipe']['path']
            target.parent.mkdir(parents=True)
            payload = target.parent / lock['targets']['filename']
            for variant in ('changed', 'missing', 'linked', 'collision'):
                with self.subTest(variant=variant):
                    target.unlink(missing_ok=True); payload.unlink(missing_ok=True)
                    target.write_bytes(FIXTURE.read_bytes())
                    if variant == 'changed': target.write_bytes(b'forged')
                    elif variant == 'missing': target.unlink()
                    elif variant == 'linked':
                        saved = root / 'saved'; saved.write_bytes(target.read_bytes())
                        target.unlink(); target.symlink_to(saved)
                    else: payload.write_bytes(b'prior payload')
                    before = {path: path.read_bytes() for path in (target,payload) if path.exists()}
                    with self.assertRaises((ValueError, FileNotFoundError)):
                        installer()._python_native_host(root, lock)
                    self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_producer_requires_actual_authenticated_python_recipe(self):
        driver = (ROOT / 'suite/scripts/build-native-engine.ps1').read_text()
        self.assertTrue('export OPENGEUL_LIBREOFFICE_PYTHON_PATCHES=' in driver)
        self.assertTrue('suite.tests.test_native_python_host' in driver)

    def test_mandatory_actual_source_gate_rejects_missing_or_forged_recipe(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / FIXTURE.name).write_bytes(b'forged recipe')
            for source in (None, str(root)):
                env = dict(os.environ, OPENGEUL_FIREBIRD_PORT_REQUIRE_SOURCE='1')
                env.pop('OPENGEUL_LIBREOFFICE_PYTHON_PATCHES', None)
                if source: env['OPENGEUL_LIBREOFFICE_PYTHON_PATCHES'] = source
                result = subprocess.run([sys.executable,'-m','unittest',
                    'suite.tests.test_native_python_host.ActualPythonSourceTests','-v'],
                    cwd=ROOT,env=env,capture_output=True,text=True,timeout=30)
                self.assertNotEqual(0, result.returncode)
                self.assertIn('FAILED (failures=1)', result.stderr)
                self.assertNotIn('skipped', result.stderr)


class PythonHostRecipeReplayTests(unittest.TestCase):
    def test_posix_recipe_replay_preserves_scope_and_quoted_windows_paths(self):
        make, bash = require_posix_recipe_replay(
            os.name, Path('/usr/bin/make'), Path('/bin/bash'),
            os.environ.get('OPENGEUL_FIREBIRD_PORT_REQUIRE_SOURCE') == '1')
        lock = PythonHostSourceTests().lock()
        with tempfile.TemporaryDirectory(prefix='python host ') as folder:
            root = Path(folder)
            target = root / lock['recipe']['path']; target.parent.mkdir(parents=True)
            target.write_bytes(FIXTURE.read_bytes())
            planned = installer()._python_native_host(root, lock)
            original, effective = planned[1:3]
            # Execute the actual recipe through GNU make and Bash. Record the
            # resulting MSBuild argv, including a native drive path with spaces.
            observer = root / 'MSBuild.exe'
            observer.write_text('#!'+sys.executable+'\nimport json,sys;print(json.dumps(sys.argv[1:]))\n')
            observer.chmod(0o755)
            def replay(raw, platform, source_dir='C:/owned/source with spaces'):
                variables = ('SHELL := '+str(bash)+'\nOS := '+platform[0]+'\nCPUNAME := '+platform[1]+'\n'
                    'SRCDIR := '+source_dir+'\n'
                    'gb_ExternalProject_get_state_target = all\n'
                    'gb_ExternalProject_run = $(2)\n'
                    'gb_MSBUILD_CONFIG_AND_PLATFORM := /p:Configuration=Release /p:Platform=ARM64\n')
                makefile = root / 'recipe.mk'; makefile.write_bytes(variables.encode()+raw)
                result = subprocess.run([str(make),'--no-print-directory','-s','-f',str(makefile)],
                    cwd=root,env=dict(os.environ,PATH=str(root)+os.pathsep+os.environ['PATH']),
                    capture_output=True,text=True,check=True)
                return json.loads(result.stdout)
            baseline = replay(original, ('WNT','AARCH64'))
            native = replay(effective, ('WNT','AARCH64'))
            added = '/p:ForceImportAfterCppTargets=C:/owned/source with spaces/external/python3/'+lock['targets']['filename']
            self.assertEqual(baseline, [item for item in native if item != added])
            self.assertEqual(1, native.count(added))
            self.assertEqual(baseline, replay(effective, ('WNT','X86_64')))
            # Native21 retained config_host.mk physical LF648 exports this
            # mixed Windows path. The source recipe needs no Cygwin conversion.
            actual_source = 'C:/a/OpenGeul/OpenGeul/.work/native-engine/libreoffice-26.8.1.1'
            actual = replay(effective, ('WNT','AARCH64'), actual_source)
            self.assertIn('/p:ForceImportAfterCppTargets='+actual_source+'/external/python3/'+lock['targets']['filename'], actual)


class ActualPythonSourceTests(unittest.TestCase):
    def test_actual_upstream_recipe_matches_authenticated_fixture_and_source_plan(self):
        value = os.environ.get('OPENGEUL_LIBREOFFICE_PYTHON_PATCHES')
        if not value:
            if os.environ.get('OPENGEUL_FIREBIRD_PORT_REQUIRE_SOURCE') == '1':
                self.fail('Mandatory pinned LibreOffice Python source recipe is missing')
            self.skipTest('Pinned local LibreOffice Python source recipe is required')
        raw = (Path(value) / FIXTURE.name).read_bytes()
        self.assertEqual(RECIPE_SHA, hashlib.sha256(raw).hexdigest())
        self.assertEqual(FIXTURE.read_bytes(), raw)
        lock = PythonHostSourceTests().lock()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); target = root / lock['recipe']['path']
            target.parent.mkdir(parents=True); target.write_bytes(raw)
            plan = installer()._python_native_host(root, lock)
            self.assertEqual(lock['recipe']['afterSha256'], hashlib.sha256(plan[2]).hexdigest())


if __name__ == '__main__': unittest.main()
