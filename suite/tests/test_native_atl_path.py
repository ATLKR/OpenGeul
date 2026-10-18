"""Authentic ActiveX recipe argv replay; this does not build or qualify Office."""
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

from suite.tests.test_native_python_host import installer, require_posix_recipe_replay

ROOT = Path(__file__).resolve().parents[2]
PORT = ROOT / 'suite/engine-build'
FIXTURE = ROOT / 'suite/tests/fixtures/native-atl-path'
RECIPE = 'extensions/Library_so_activex.mk'
RECIPE_SHA = '7da1d1e5798d99aa895c170e0c419a4b4d3595e38d177f754ddf8fd5b1b7a89c'
INCLUDE = '/cygdrive/c/PROGRA~1/MICROS~2/atlmfc/include'
LIB = '/cygdrive/c/PROGRA~1/MICROS~2/atlmfc/lib/spectre/arm64'
NATIVE = 'C:/Program Files/Microsoft Visual Studio/atlmfc'


def lock():
    value = json.loads((PORT / 'source-build.json').read_text())
    if 'atlNativePaths' not in value:
        raise AssertionError('Authenticated native ATL source hook is missing')
    return value['atlNativePaths']


def plan(root):
    module = installer()
    if not callable(getattr(module, '_atl_native_paths', None)):
        raise AssertionError('Native ATL source planner is missing')
    return module._atl_native_paths(root, lock())


def replay_recipe(root, raw, make, bash, os_value='WNT', cpu='AARCH64',
                  host='x86_64-pc-cygwin', include=INCLUDE, lib=LIB, adapter=True):
    observer = shlex.quote(sys.executable)+' '+shlex.quote(str(root/'observe.py'))
    variables = ('SHELL := '+str(bash)+'\nOS := '+os_value+'\nCPUNAME := '+cpu+'\n'
        +('MAKE_HOST := '+host+'\n' if host is not None else '')+
        'ATL_INCLUDE := '+include+'\nATL_LIB := '+lib+'\nSRCDIR := C:/source\n'
        'TARGETTYPE := Library\nWORKDIR := C:/work\n'
        'gb_LINK := '+observer+'\n'
        'gb_CObject__compiler = '+observer+'\n'
        'gb_Helper_abbreviate_dirs = $(1)\n'
        'gb_Helper_remove_overridden_flags = $(1)\n'
        'gb_LinkTarget_get_target = all\n'
        'gb_Library_set_include = $(call gb_LinkTarget_set_include,$(1),$(2))\n'
        'gb_Library_add_ldflags = $(call gb_LinkTarget_add_ldflags,$(1),$(2))\n'
        'gb_Library_add_libs = $(call gb_LinkTarget_add_libs,$(1),$(2))\n'
        'gb_Library_use_system_win32_libs = $(call gb_LinkTarget_add_libs,$(1),$(addsuffix .lib,$(2)))\n')
    # Authentic target assignments and the actual native link argv expansion,
    # including sort(T_LIBS), run before Bash. No native compiler is fabricated.
    link = (FIXTURE/'msc-link-argv.mk').read_bytes()
    makefile = root/'replay.mk'
    makefile.write_bytes(variables.encode()+(FIXTURE/'linktarget-atl.mk').read_bytes()+b'\n'+
        (FIXTURE/'msc-compile-argv.mk').read_bytes()+b'\n'+raw+
        b'\nall:\n\t@$(call gb_CObject__command_pattern,object.obj,-O2 -GL,source.cpp,object.d)\n'+
        b'\t@'+link.lstrip(b'\t'))
    env = dict(os.environ)
    if adapter: env['PATH'] = str(root)+os.pathsep+env['PATH']
    return subprocess.run([str(make),'--no-print-directory','-s','-f',str(makefile)],
        cwd=root, env=env, capture_output=True, text=True, timeout=30)


def observed_argv(output):
    return [json.loads(line) for line in output.split('\n') if line]


class AtlSourceTests(unittest.TestCase):
    def test_pristine_recipe_and_profile_are_authenticated_and_plan_is_exact(self):
        manifest = json.loads((FIXTURE / 'source.json').read_text())
        self.assertEqual('296ba78e7ab0d381b94c3d6342f4ebb2320ee5097ca58781b9b744cab90b9785', manifest['archiveSha256'])
        for pin in manifest['members']:
            raw = (FIXTURE / pin['fixture']).read_bytes()
            self.assertEqual(pin['fixtureBytes'], len(raw))
            self.assertEqual(pin['fixtureSha256'], hashlib.sha256(raw).hexdigest())
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); target = root / RECIPE
            target.parent.mkdir(); original = (FIXTURE / target.name).read_bytes()
            self.assertEqual(RECIPE_SHA, hashlib.sha256(original).hexdigest())
            target.write_bytes(original)
            actual, before, after = plan(root)
            self.assertEqual(target, actual)
            self.assertEqual(original, before)
            self.assertEqual(original, target.read_bytes(), 'Planning must not write source')
            self.assertEqual(lock()['recipe']['afterSha256'], hashlib.sha256(after).hexdigest())
            self.assertEqual(lock()['recipe']['afterSize'], len(after))

    def test_missing_changed_linked_recipe_and_linked_directory_fail_without_writes(self):
        for variant in ('missing', 'changed', 'linked-recipe', 'linked-parent'):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as folder:
                root = Path(folder); target = root / RECIPE; target.parent.mkdir()
                raw = (FIXTURE / target.name).read_bytes(); target.write_bytes(raw)
                if variant == 'missing': target.unlink()
                elif variant == 'changed': target.write_bytes(raw+b'changed')
                elif variant == 'linked-recipe':
                    saved = root / 'saved'; saved.write_bytes(raw); target.unlink(); target.symlink_to(saved)
                else:
                    saved = root / 'saved-dir'; target.parent.rename(saved); target.parent.symlink_to(saved, target_is_directory=True)
                before = target.read_bytes() if target.exists() else None
                with self.assertRaises((ValueError, FileNotFoundError)):
                    plan(root)
                self.assertEqual(before, target.read_bytes() if target.exists() else None)

    def test_producer_mandates_actual_source_and_replay(self):
        driver = (ROOT / 'suite/scripts/build-native-engine.ps1').read_text()
        self.assertTrue('export OPENGEUL_LIBREOFFICE_ATL_SOURCE=' in driver)
        self.assertTrue('suite.tests.test_native_atl_path -v' in driver)

    def test_strict_gate_rejects_missing_or_forged_actual_source_without_skip(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); target = root / RECIPE; target.parent.mkdir(); target.write_bytes(b'forged')
            for value in (None, str(root)):
                env = dict(os.environ, OPENGEUL_FIREBIRD_PORT_REQUIRE_SOURCE='1')
                env.pop('OPENGEUL_LIBREOFFICE_ATL_SOURCE', None)
                if value: env['OPENGEUL_LIBREOFFICE_ATL_SOURCE'] = value
                result = subprocess.run([sys.executable, '-m', 'unittest',
                    'suite.tests.test_native_atl_path.ActualAtlSourceTests', '-v'],
                    cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
                self.assertNotEqual(0, result.returncode)
                self.assertIn('FAILED', result.stderr)
                self.assertNotIn('skipped', result.stderr)


class AtlRecipeReplayTests(unittest.TestCase):
    def test_actual_recipe_argv_normalizes_only_arm64_cygwin_and_fails_closed(self):
        make, bash = require_posix_recipe_replay(os.name, Path('/usr/bin/make'), Path('/bin/bash'),
            os.environ.get('OPENGEUL_FIREBIRD_PORT_REQUIRE_SOURCE') == '1' or
            os.environ.get('OPENGEUL_ATL_REQUIRE_CYGWIN_REPLAY') == '1')
        with tempfile.TemporaryDirectory(prefix='atl recipe ') as folder:
            root = Path(folder); target = root / RECIPE; target.parent.mkdir()
            original = (FIXTURE / target.name).read_bytes(); target.write_bytes(original)
            effective = plan(root)[2]
            # Explicit argv-only POSIX adapter. It is not a Windows compiler or
            # a proof of Cygwin/native behavior; strict mode below uses cygpath.
            adapter = root / 'cygpath'
            adapter.write_text('#!'+sys.executable+'\nimport sys\np=sys.argv[-1]\n'
                'assert sys.argv[1]=="-lm"\n'
                'if "missing" in p: sys.exit(7)\n'
                'if "empty" not in p: print(p.replace("/cygdrive/c/PROGRA~1/MICROS~2/atlmfc", '+repr(NATIVE)+'))\n')
            adapter.chmod(0o755)
            observe = root / 'observe.py'; observe.write_text('import json,sys;print(json.dumps(sys.argv[1:]))\n')
            def replay(raw, **kwargs):
                return replay_recipe(root, raw, make, bash, **kwargs)
            baseline = replay(original); self.assertEqual(0, baseline.returncode, baseline.stderr)
            before = sum(observed_argv(baseline.stdout), [])
            self.assertIn('-I'+INCLUDE, before); self.assertIn('-LIBPATH:'+LIB, before); self.assertIn(LIB+'/atls.lib', before)
            candidate = replay(effective); self.assertEqual(0, candidate.returncode, candidate.stderr)
            after = sum(observed_argv(candidate.stdout), [])
            expected = [item.replace(INCLUDE, NATIVE+'/include').replace(LIB, NATIVE+'/lib/spectre/arm64') for item in before]
            self.assertCountEqual(expected, after)
            self.assertEqual(1, after.count(NATIVE+'/lib/spectre/arm64/atls.lib'))
            multiple = replay(effective, include=INCLUDE+' '+INCLUDE+'/extras')
            self.assertEqual(0, multiple.returncode, multiple.stderr)
            self.assertEqual(['-I'+NATIVE+'/include', '-I'+NATIVE+'/include/extras'],
                             [item for item in observed_argv(multiple.stdout)[0] if item.startswith('-I')])
            for os_value, cpu, host in [('WNT','X86_64','x86_64-pc-cygwin'), ('LINUX','AARCH64','x86_64-pc-cygwin'),
                                      ('WNT','AARCH64','x86_64-w64-mingw32'), ('WNT','AARCH64','x86_64-pc-linux-gnu')]:
                current = replay(effective, os_value=os_value, cpu=cpu, host=host)
                self.assertEqual(0, current.returncode, current.stderr)
                self.assertEqual(baseline.stdout, current.stdout)
            broken = effective.replace(b'$(so_activex_ATL_LINK_LIB)', b'').replace(b'$(so_activex_ATL_LIBS)', b'$(so_activex_ATL_LIB)/atls.lib')
            rejected = replay(broken)
            self.assertEqual(0, rejected.returncode, rejected.stderr)
            self.assertNotEqual(after, sum(observed_argv(rejected.stdout), []), 'Authentic sorted T_LIBS boundary must detect a naive quoted long path')
            for value in ('/missing/atl', '/empty/atl', ''):
                for key in ('include', 'lib'):
                    failed = replay(effective, **{key:value})
                    self.assertNotEqual(0, failed.returncode, key+': '+value)
                    self.assertIn('ATL', failed.stderr)
                    self.assertEqual('', failed.stdout)


class AtlGateFlagTests(unittest.TestCase):
    def actual_source(self):
        value = os.environ.get('OPENGEUL_LIBREOFFICE_ATL_SOURCE')
        if not value:
            if (os.environ.get('OPENGEUL_FIREBIRD_PORT_REQUIRE_SOURCE') == '1' or
                    os.environ.get('OPENGEUL_ATL_REQUIRE_CYGWIN_REPLAY') == '1'):
                self.fail('Mandatory pinned LibreOffice ATL source is missing')
            self.skipTest('Pinned local LibreOffice ATL source is required for the gate matrix')
        return value

    def invoke(self, source, require_source=False, require_cygwin=False, replay=False):
        env = dict(os.environ)
        for key in ('OPENGEUL_LIBREOFFICE_ATL_SOURCE', 'OPENGEUL_FIREBIRD_PORT_REQUIRE_SOURCE',
                    'OPENGEUL_ATL_REQUIRE_CYGWIN_REPLAY'):
            env.pop(key, None)
        if source: env['OPENGEUL_LIBREOFFICE_ATL_SOURCE'] = source
        if require_source: env['OPENGEUL_FIREBIRD_PORT_REQUIRE_SOURCE'] = '1'
        if require_cygwin: env['OPENGEUL_ATL_REQUIRE_CYGWIN_REPLAY'] = '1'
        command = [sys.executable, '-m', 'unittest',
                   'suite.tests.test_native_atl_path.ActualAtlSourceTests']
        if replay: command.append('suite.tests.test_native_atl_path.AtlRecipeReplayTests')
        return subprocess.run(command+['-v'], cwd=ROOT, env=env,
                              capture_output=True, text=True, timeout=30)

    def test_shared_strict_source_mode_authenticates_and_replays_without_cygwin_requirement(self):
        require_posix_recipe_replay(os.name, Path('/usr/bin/make'), Path('/bin/bash'),
            os.environ.get('OPENGEUL_FIREBIRD_PORT_REQUIRE_SOURCE') == '1' or
            os.environ.get('OPENGEUL_ATL_REQUIRE_CYGWIN_REPLAY') == '1')
        result = self.invoke(self.actual_source(), require_source=True, replay=True)
        self.assertEqual(0, result.returncode, result.stdout+result.stderr)
        self.assertNotIn('skipped', result.stderr)
        self.assertIn('Ran 2 tests', result.stderr)

    def test_strict_cygwin_flag_alone_requires_source_without_skip(self):
        result = self.invoke(None, require_cygwin=True)
        self.assertNotEqual(0, result.returncode, result.stdout+result.stderr)
        self.assertIn('Mandatory pinned LibreOffice ATL source is missing', result.stderr)
        self.assertNotIn('skipped', result.stderr)

    def test_strict_cygwin_flag_alone_checks_the_actual_make_profile(self):
        make, _ = require_posix_recipe_replay(os.name, Path('/usr/bin/make'), Path('/bin/bash'),
            os.environ.get('OPENGEUL_FIREBIRD_PORT_REQUIRE_SOURCE') == '1' or
            os.environ.get('OPENGEUL_ATL_REQUIRE_CYGWIN_REPLAY') == '1')
        profile = subprocess.run([str(make), '--no-print-directory', '-f', '-', 'host'],
            input='host:\n\t@echo $(MAKE_HOST)\n', capture_output=True, text=True, check=True)
        result = self.invoke(self.actual_source(), require_cygwin=True)
        self.assertNotIn('skipped', result.stderr)
        if profile.stdout.strip().endswith('-cygwin'):
            self.assertEqual(0, result.returncode, result.stdout+result.stderr)
        else:
            self.assertNotEqual(0, result.returncode, result.stdout+result.stderr)
            self.assertIn('Mandatory actual Cygwin GNU make profile is missing', result.stderr)


class ActualAtlSourceTests(unittest.TestCase):
    def test_actual_source_matches_pristine_recipe_and_real_cygwin_profile(self):
        require_cygwin = os.environ.get('OPENGEUL_ATL_REQUIRE_CYGWIN_REPLAY') == '1'
        required = os.environ.get('OPENGEUL_FIREBIRD_PORT_REQUIRE_SOURCE') == '1' or require_cygwin
        value = os.environ.get('OPENGEUL_LIBREOFFICE_ATL_SOURCE')
        if not value:
            if required: self.fail('Mandatory pinned LibreOffice ATL source is missing')
            self.skipTest('Pinned local LibreOffice ATL source is required')
        source = Path(value)
        manifest = json.loads((FIXTURE/'source.json').read_text())
        for pin in manifest['members']:
            actual = source / Path(pin['member']).relative_to('libreoffice-26.8.1.1')
            self.assertFalse(any(path.is_symlink() for path in (actual, *actual.parents)), 'Actual ATL source must be unlinked')
            raw = installer()._regular(actual)
            self.assertEqual(pin['bytes'], len(raw))
            self.assertEqual(pin['sha256'], hashlib.sha256(raw).hexdigest())
        candidate = plan(source)[2]
        self.assertEqual(lock()['recipe']['afterSha256'], hashlib.sha256(candidate).hexdigest())
        if require_cygwin:
            make, bash = require_posix_recipe_replay(os.name, Path('/usr/bin/make'), Path('/bin/bash'), True)
            result = subprocess.run([str(make), '--no-print-directory', '-f', '-', 'host'],
                input='host:\n\t@echo $(MAKE_HOST)\n', capture_output=True, text=True, check=True)
            self.assertTrue(result.stdout.strip().endswith('-cygwin'), 'Mandatory actual Cygwin GNU make profile is missing')
            with tempfile.TemporaryDirectory(prefix='atl-replay-') as folder:
                root = Path(folder); include = root/'include'; include.mkdir()
                lib = root/'library with spaces'; lib.mkdir()
                (root/'observe.py').write_text('import json,sys;print(json.dumps(sys.argv[1:]))\n')
                converted = []
                for path in (include, lib):
                    result = subprocess.run(['cygpath','-lm',str(path)], capture_output=True, text=True, check=True)
                    converted.append(result.stdout.strip())
                actual = replay_recipe(root, candidate, make, bash, host=None, include=str(include), lib=str(lib), adapter=False)
                self.assertEqual(0, actual.returncode, actual.stdout+actual.stderr)
                argv = observed_argv(actual.stdout)
                self.assertIn('-I'+converted[0], argv[0])
                self.assertIn('-LIBPATH:'+converted[1], argv[1])
                self.assertIn(converted[1]+'/atls.lib', argv[1])
                self.assertIn('ole32.lib', argv[1])


if __name__ == '__main__': unittest.main()
