"""Authenticated HarfBuzz recipe replay; Linux results are argv adapters only."""
import ast
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import typing
import unittest

from suite.tests.test_native_python_host import installer, require_posix_recipe_replay

ROOT = Path(__file__).resolve().parents[2]
PORT = ROOT / 'suite/engine-build'
FIXTURE = ROOT / 'suite/tests/fixtures/native-meson-path'
RECIPE = 'external/harfbuzz/ExternalProject_harfbuzz.mk'
SOURCE_FLAG = 'OPENGEUL_FIREBIRD_PORT_REQUIRE_SOURCE'
CYGWIN_FLAG = 'OPENGEUL_MESON_REQUIRE_CYGWIN_REPLAY'
SOURCE_ENV = 'OPENGEUL_LIBREOFFICE_MESON_SOURCE'
NATIVE_COMPILER = "C:/Program Files/Microsoft Visual Studio/O'Brien/Hostarm64/arm64/cl.exe"
PREFIX = 'C:\\Python With Spaces\\lib\\pkgconfig;D:/additional packages'


def lock():
    value = json.loads((PORT / 'source-build.json').read_text())
    if 'harfbuzzNativeMesonPaths' not in value:
        raise AssertionError('Authenticated HarfBuzz Meson source hook is missing')
    return value['harfbuzzNativeMesonPaths']


def plan(source):
    module = installer()
    if not callable(getattr(module, '_harfbuzz_native_meson_paths', None)):
        raise AssertionError('HarfBuzz native Meson source planner is missing')
    return module._harfbuzz_native_meson_paths(source, lock())


def windows_split_args():
    """Run only the exact authenticated Meson Windows argument parser on POSIX."""
    source = (FIXTURE / 'universal.py').read_text()
    tree = ast.parse(source)
    branch = next(node for node in tree.body if isinstance(node, ast.If)
                  and isinstance(node.test, ast.Call)
                  and getattr(node.test.func, 'id', None) == 'is_windows'
                  and any(isinstance(item, ast.FunctionDef) and item.name == 'split_args'
                          for item in node.body))
    function = next(node for node in branch.body
                    if isinstance(node, ast.FunctionDef) and node.name == 'split_args')
    namespace = {'T': typing, '_whitespace': ' \t\n\r'}
    exec(compile(ast.Module(body=[function], type_ignores=[]), '<authenticated Meson Windows split_args>', 'exec'), namespace)
    return namespace['split_args']


def authentic_function(filename, name):
    raw = (FIXTURE / filename).read_text()
    start = raw.index('define ' + name + '\n')
    return raw[start:raw.index('\nendef', start)+len('\nendef')]+'\n'


def make_profile(require_cygwin=False, require_tools=False):
    """Query the genuine builtin before any adapter overrides MAKE_HOST."""
    make, bash = require_posix_recipe_replay(os.name, Path('/usr/bin/make'), Path('/bin/bash'),
                                           require_cygwin or require_tools)
    result = subprocess.run([str(make),'--no-print-directory','-s','-f','-','host'],
        input='host:\n\t@echo $(MAKE_HOST)\n',capture_output=True,text=True,check=True,timeout=10)
    host = result.stdout.strip()
    if require_cygwin and not host.endswith('-cygwin'):
        raise AssertionError('Mandatory actual Cygwin GNU make profile is missing: '+host)
    return make, bash, host


def replay(root, raw, *, cpu='AARCH64', platform='WNT', com='MSC',
           host='x86_64-pc-cygwin', python='', system_python='',
           build='aarch64-pc-cygwin', target='aarch64-pc-cygwin', wsl='',
           build_type='MESON', prefix=PREFIX, cc=None, cxx=None, adapter=True,
           converter='ok', system_icu=''):
    """Expand the whole genuine recipe and ExternalProject_run before Bash."""
    require_posix_recipe_replay(os.name, Path('/usr/bin/make'), Path('/bin/bash'),
        os.environ.get(SOURCE_FLAG) == '1' or os.environ.get(CYGWIN_FLAG) == '1')
    make, bash, builtin_host = make_profile(os.environ.get(CYGWIN_FLAG) == '1',
                                          os.environ.get(SOURCE_FLAG) == '1')
    work = root/'work'; (work/'harfbuzz').mkdir(parents=True, exist_ok=True)
    compiler = root/'compiler with spaces'/"O'Brien"/'cl.exe'
    compiler.parent.mkdir(parents=True, exist_ok=True); compiler.touch()
    cc = str(compiler) if cc is None else cc
    cxx = str(compiler) if cxx is None else cxx
    # This observer is a test receiver, never a fabricated compiler or Meson.
    (root/'observe.py').write_text('import json,os,sys\n'
        'print(json.dumps({"args":sys.argv[1:],"CC":os.environ.get("CC"),'
        '"CXX":os.environ.get("CXX"),"PKG_CONFIG_PATH":os.environ.get("PKG_CONFIG_PATH"),'
        '"PKG_CONFIG":os.environ.get("PKG_CONFIG"),"AR":os.environ.get("AR"),'
        '"LD":os.environ.get("LD"),"NINJA":os.environ.get("NINJA"),'
        '"builtinMakeHost":os.environ["OPENGEUL_MESON_REPLAY_BUILTIN_MAKE_HOST"],'
        '"profileClassification":os.environ["OPENGEUL_MESON_REPLAY_CLASSIFICATION"]}))\n')
    observer = shlex.quote(sys.executable)+' '+shlex.quote(str(root/'observe.py'))
    if adapter:
        (root/'cygpath').write_text('#!'+sys.executable+'\nimport sys\n'
            'p=sys.argv[-1]\n'
            'assert sys.argv[1]=="-lm"\n'
            +('sys.exit(7) if "badpkg" in p else None\n' if converter == 'pkg-fail' else
              'sys.exit(0) if "badpkg" in p else None\n' if converter == 'pkg-empty' else '')
            +('sys.exit(7)\n' if converter == 'fail' else 'sys.exit(0)\n' if converter == 'empty' else
              'print('+repr(NATIVE_COMPILER)+' if p.endswith("cl.exe") else '
              'p.replace("\\\\", "/") if len(p)>2 and p[1]==":" else "C:/native"+p)\n'))
        (root/'cygpath').chmod(0o755)
    env = dict(os.environ)
    env['OPENGEUL_MESON_REPLAY_BUILTIN_MAKE_HOST'] = builtin_host
    env['OPENGEUL_MESON_REPLAY_CLASSIFICATION'] = (
        'real-cygwin-path-and-recipe-replay' if host is None and not adapter and builtin_host.endswith('-cygwin')
        else 'adapter-only')
    env['AR'] = env['LD'] = ''
    env.pop('NINJA', None)
    if adapter: env['PATH'] = str(root)+os.pathsep+env['PATH']
    variables = ('SHELL := '+str(bash)+'\n.DEFAULT_GOAL := all\n'
        'OS := '+platform+'\nOS_FOR_BUILD := '+platform+'\nCPUNAME := '+cpu+'\nCOM := '+com+'\n'
        +('MAKE_HOST := '+host+'\n' if host is not None else '')+
        'BUILD_PLATFORM := '+build+'\nHOST_PLATFORM := '+target+'\nWSL := '+wsl+'\n'
        'PYTHON_FOR_BUILD := '+python+'\nSYSTEM_PYTHON := '+system_python+'\nBUILD_TYPE := '+build_type+'\n'
        'export CC := '+cc+'\nexport CXX := '+cxx+'\n'
        'PKG_CONFIG_PATH := '+prefix+'\nexport PKG_CONFIG := C:/tools/pkgconf-2.4.3.exe\n'
        'LIBO_PATH_SEPARATOR := :\nSYSTEM_ICU := '+system_icu+'\n'
        'CXXFLAGS_CXX11 := -std:c++20 -permissive- -Zc:__cplusplus,preprocessor\n'
        'WHITESPACE := $(subst ,, )\nCOMMA := ,\n'
        'gb_UnpackedTarball_workdir := '+str(work)+'\nEXTERNAL_WORKDIR := '+str(work/'harfbuzz')+'\n'
        'MESON = '+observer+' meson.py\n'
        'gb_ExternalProject_get_state_target = all\n'
        'gb_Helper_print_on_error = $(1)\n')
    # Exact configured compiler bindings, not a substitute invented recipe.
    msc = (FIXTURE/'com_MSC_defs.mk').read_text().splitlines(keepends=True)
    variables += ''.join(msc[22:38])
    makefile = root/'replay.mk'
    makefile.write_text(variables+'\n'+authentic_function('ExternalProject.mk', 'gb_ExternalProject_run')+'\n'+raw.decode())
    (root/'all').unlink(missing_ok=True)
    result = subprocess.run([str(make),'--no-print-directory','-s','-f',str(makefile)],
        cwd=root, env=env, capture_output=True, text=True, timeout=30)
    return result


def observations(result):
    return [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]


class MesonSourceTests(unittest.TestCase):
    def test_complete_original_sources_and_planned_hook_are_authenticated(self):
        manifest = json.loads((FIXTURE/'source.json').read_text())
        self.assertTrue(manifest['sourceAuthenticated'])
        for pin in manifest['members']:
            raw = (FIXTURE/pin['fixture']).read_bytes()
            self.assertEqual(pin['fixtureBytes'], len(raw))
            self.assertEqual(pin['fixtureSha256'], hashlib.sha256(raw).hexdigest())
        for pin in [manifest['meson']]:
            raw = (FIXTURE/pin['fixture']).read_bytes()
            self.assertEqual(pin['bytes'], len(raw))
            self.assertEqual(pin['sha256'], hashlib.sha256(raw).hexdigest())
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder); recipe = source/RECIPE; recipe.parent.mkdir(parents=True)
            original = (FIXTURE/recipe.name).read_bytes(); recipe.write_bytes(original)
            actual, before, after = plan(source)
            self.assertEqual(recipe, actual); self.assertEqual(original, before)
            self.assertEqual(original, recipe.read_bytes(), 'Planning must not mutate source')
            self.assertEqual(lock()['recipe']['afterSize'], len(after))
            self.assertEqual(lock()['recipe']['afterSha256'], hashlib.sha256(after).hexdigest())

    def test_missing_changed_or_linked_source_is_rejected_without_writes(self):
        for kind in ('missing', 'changed', 'linked', 'linked-parent', 'repeated'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as folder:
                source = Path(folder); recipe = source/RECIPE; recipe.parent.mkdir(parents=True)
                original = (FIXTURE/recipe.name).read_bytes(); recipe.write_bytes(original)
                if kind == 'missing': recipe.unlink()
                elif kind == 'changed': recipe.write_bytes(original+b'changed')
                elif kind == 'repeated': recipe.write_bytes(plan(source)[2])
                elif kind == 'linked':
                    saved=source/'saved'; saved.write_bytes(original); recipe.unlink(); recipe.symlink_to(saved)
                else:
                    saved=source/'saved-dir'; recipe.parent.rename(saved); recipe.parent.symlink_to(saved, target_is_directory=True)
                before = recipe.read_bytes() if recipe.exists() else None
                with self.assertRaises((ValueError, FileNotFoundError)): plan(source)
                self.assertEqual(before, recipe.read_bytes() if recipe.exists() else None)

    def test_producer_requires_source_authentication_and_real_cygwin_replay_separately(self):
        driver=(ROOT/'suite/scripts/build-native-engine.ps1').read_text()
        for expected in ('export '+SOURCE_ENV+'=', 'export '+CYGWIN_FLAG+'=1',
                         'suite.tests.test_native_meson_path -v'):
            self.assertIn(expected, driver)


class MesonRecipeReplayTests(unittest.TestCase):
    def candidate(self, source, original):
        # Before implementation the original recipe supplies a meaningful RED
        # at the actual command/env boundary instead of an import failure.
        if not hasattr(installer(), '_harfbuzz_native_meson_paths'):
            effective = original
        else:
            recipe=source/RECIPE; recipe.parent.mkdir(parents=True); recipe.write_bytes(original)
            effective = plan(source)[2]
        require_posix_recipe_replay(os.name, Path('/usr/bin/make'), Path('/bin/bash'),
            os.environ.get(SOURCE_FLAG) == '1' or os.environ.get(CYGWIN_FLAG) == '1')
        return effective

    def test_genuine_recipe_passes_both_compilers_and_native_dependency_entries(self):
        with tempfile.TemporaryDirectory(prefix='meson-replay-') as folder:
            root=Path(folder); original=(FIXTURE/'ExternalProject_harfbuzz.mk').read_bytes()
            effective=self.candidate(root, original)
            before=replay(root, original); self.assertEqual(0,before.returncode,before.stderr)
            candidate=replay(root,effective); self.assertEqual(0,candidate.returncode,candidate.stderr)
            baseline=observations(before); after=observations(candidate)
            self.assertEqual(2,len(after)); split=windows_split_args()
            for key in ('CC','CXX'):
                self.assertEqual([NATIVE_COMPILER],split(after[0][key]))
                self.assertTrue(after[0][key].startswith('"'))
                self.assertEqual(after[0][key],after[1][key])
                self.assertFalse(split(baseline[0][key])[0].startswith('C:/'))
            self.assertEqual(baseline[0]['args'],after[0]['args'])
            self.assertEqual(baseline[1]['args'],after[1]['args'])
            self.assertEqual(['meson.py','compile','-C','builddir','libs'],after[1]['args'])
            self.assertEqual(['C:/Python With Spaces/lib/pkgconfig','D:/additional packages',
                             'C:/native'+str(root/'work/graphite'),
                             'C:/native'+str(root/'work/icu')], after[0]['PKG_CONFIG_PATH'].split(';'))
            for key in ('PKG_CONFIG','AR','LD','NINJA'): self.assertEqual(baseline[0][key],after[0][key])
            self.assertEqual('',after[0]['AR']); self.assertEqual('',after[0]['LD'])
            self.assertIsNone(after[0]['NINJA'])
            # HARFBUZZ-MESON-001: both spellings exist, so collapsing internal
            # whitespace would silently select another configured executable.
            single=root/'compiler with spaces'/"O'Brien"/'cl.exe'
            double=root/'compiler  with spaces'/"O'Brien"/'cl.exe'
            double.parent.mkdir(parents=True); double.write_bytes(b'double-space identity')
            single.write_bytes(b'single-space identity')
            configured='$(subst ,, )'+str(double)+'  '
            result=replay(root,effective,cc=configured,cxx=configured)
            self.assertEqual(0,result.returncode,result.stderr)
            calls=root/'converted-paths.jsonl'
            (root/'cygpath').write_text('#!'+sys.executable+'\nimport json,pathlib,sys\n'
                'p=sys.argv[-1]\n'
                'with pathlib.Path('+repr(str(calls))+').open("a") as f: f.write(json.dumps(p)+"\\n")\n'
                'print("C:/native"+p)\n')
            (root/'cygpath').chmod(0o755)
            env=dict(os.environ); env['PATH']=str(root)+os.pathsep+env['PATH']
            env['OPENGEUL_MESON_REPLAY_BUILTIN_MAKE_HOST']=observations(result)[0]['builtinMakeHost']
            env['OPENGEUL_MESON_REPLAY_CLASSIFICATION']='adapter-only'
            env['AR']=env['LD']=''; env.pop('NINJA',None)
            # Reuse the complete authentic recipe expansion already prepared
            # by replay(); this observer runs no compiler or native Meson.
            checked=subprocess.run(['/usr/bin/make','--no-print-directory','-s','-B',
                '-f',str(root/'replay.mk')],cwd=root,env=env,capture_output=True,text=True,timeout=30)
            self.assertEqual(0,checked.returncode,checked.stderr)
            self.assertEqual([str(double),str(double)],
                             [json.loads(line) for line in calls.read_text().splitlines()][:2])
            selected=observations(checked)
            for record in selected:
                for key in ('CC','CXX'):
                    self.assertEqual(['C:/native'+str(double)],split(record[key]))
            self.assertEqual(b'double-space identity',double.read_bytes())
            self.assertEqual(b'single-space identity',single.read_bytes())

    def test_other_profiles_keep_the_complete_original_recipe_behavior(self):
        profiles=[{'cpu':'X86_64'},{'platform':'LINUX'},{'com':'GCC'},
                  {'host':'x86_64-w64-mingw32'},{'host':'x86_64-pc-linux-gnu'},
                  {'python':'/usr/bin/python3'},{'system_python':'TRUE'},
                  {'build':'x86_64-pc-cygwin'},{'wsl':'TRUE'},{'build_type':''}]
        with tempfile.TemporaryDirectory(prefix='meson-replay-') as folder:
            root=Path(folder); original=(FIXTURE/'ExternalProject_harfbuzz.mk').read_bytes()
            effective=self.candidate(root, original)
            for profile in profiles:
                with self.subTest(profile=profile):
                    before=replay(root,original,**profile); after=replay(root,effective,**profile)
                    self.assertEqual(0,after.returncode,after.stderr)
                    self.assertEqual(before.stdout,after.stdout)

    def test_failed_empty_or_non_executable_compiler_rejects_before_meson(self):
        with tempfile.TemporaryDirectory(prefix='meson-replay-') as folder:
            root=Path(folder); effective=self.candidate(root,(FIXTURE/'ExternalProject_harfbuzz.mk').read_bytes())
            executable=root/'compiler with spaces'/"O'Brien"/'cl.exe'
            for kwargs in ({'cc':''},{'cxx':''},{'cc':'ccache '+str(executable)},
                           {'cxx':str(executable)+' -nologo'},{'cc':'/missing/cl.exe'},
                           {'converter':'fail'},{'converter':'empty'},
                           {'prefix':'/badpkg','converter':'pkg-fail'},
                           {'prefix':'/badpkg','converter':'pkg-empty'}):
                with self.subTest(kwargs=kwargs):
                    result=replay(root,effective,**kwargs)
                    self.assertNotEqual(0,result.returncode)
                    self.assertIn('HarfBuzz Meson',result.stderr)
                    self.assertEqual('',result.stdout)

    def test_native_list_preserves_drive_colons_spaces_and_conditional_icu(self):
        with tempfile.TemporaryDirectory(prefix='meson-replay-') as folder:
            root=Path(folder); effective=self.candidate(root,(FIXTURE/'ExternalProject_harfbuzz.mk').read_bytes())
            for prefix, expected in [('',[]),('C:/one:D:/two',['C:/one','D:/two']),
                                     ('/first path:/second path',['C:/native/first path','C:/native/second path']),
                                     ("C:/O'Brien;D:/with space",["C:/O'Brien",'D:/with space'])]:
                with self.subTest(prefix=prefix):
                    result=replay(root,effective,prefix=prefix,system_icu='TRUE')
                    self.assertEqual(0,result.returncode,result.stderr)
                    entries=observations(result)[0]['PKG_CONFIG_PATH'].split(';')
                    self.assertEqual(expected+['C:/native'+str(root/'work/graphite')],entries)


class ActualMesonSourceTests(unittest.TestCase):
    def test_actual_source_authenticates_and_optional_real_cygwin_replay_uses_builtin_host(self):
        required=os.environ.get(SOURCE_FLAG)=='1' or os.environ.get(CYGWIN_FLAG)=='1'
        value=os.environ.get(SOURCE_ENV)
        if not value:
            if required: self.fail('Mandatory pinned LibreOffice HarfBuzz Meson source is missing')
            self.skipTest('Pinned local LibreOffice HarfBuzz Meson source is required')
        source=Path(value); manifest=json.loads((FIXTURE/'source.json').read_text())
        for pin in manifest['members']:
            actual=source/Path(pin['member']).relative_to('libreoffice-26.8.1.1')
            self.assertFalse(any(p.is_symlink() for p in (actual,*actual.parents)))
            raw=installer()._regular(actual)
            self.assertEqual(pin['bytes'],len(raw)); self.assertEqual(pin['sha256'],hashlib.sha256(raw).hexdigest())
        candidate=plan(source)[2]
        make,_,builtin_host=make_profile(os.environ.get(CYGWIN_FLAG)=='1',
                                         os.environ.get(SOURCE_FLAG)=='1')
        print(json.dumps({'kind':'harfbuzz-meson-source-profile','sourceAuthenticated':True,
                          'builtinMakeHost':builtin_host,'classification':
                          'real-cygwin-path-and-recipe-replay' if os.environ.get(CYGWIN_FLAG)=='1'
                          else 'adapter-only','nativeWindowsQualification':False}))
        if os.environ.get(CYGWIN_FLAG)=='1':
            with tempfile.TemporaryDirectory(prefix='meson-real-cygwin-') as folder:
                root=Path(folder); result=replay(root,candidate,host=None,adapter=False,prefix='')
                self.assertEqual(0,result.returncode,result.stderr)
                current=observations(result)[0]; split=windows_split_args()
                expected=subprocess.run(['cygpath','-lm',str(root/'compiler with spaces'/"O'Brien"/'cl.exe')],
                    capture_output=True,text=True,check=True).stdout.strip()
                for key in ('CC','CXX'): self.assertEqual([expected],split(current[key]))
                self.assertEqual(2,len(current['PKG_CONFIG_PATH'].split(';')))


class MesonGateFlagTests(unittest.TestCase):
    def invoke(self, source=None, require_source=False, require_cygwin=False):
        env=dict(os.environ)
        for key in (SOURCE_ENV,SOURCE_FLAG,CYGWIN_FLAG): env.pop(key,None)
        if source: env[SOURCE_ENV]=str(source)
        if require_source: env[SOURCE_FLAG]='1'
        if require_cygwin: env[CYGWIN_FLAG]='1'
        return subprocess.run([sys.executable,'-m','unittest',
            'suite.tests.test_native_meson_path.ActualMesonSourceTests','-v'],
            cwd=ROOT,env=env,capture_output=True,text=True,timeout=30)

    def test_each_strict_flag_rejects_missing_or_forged_source_without_skip(self):
        with tempfile.TemporaryDirectory() as folder:
            for kwargs in ({'require_source':True},{'require_cygwin':True},
                           {'require_source':True,'require_cygwin':True}):
                for source in (None,Path(folder)):
                    with self.subTest(kwargs=kwargs,source=source):
                        result=self.invoke(source,**kwargs)
                        self.assertNotEqual(0,result.returncode)
                        self.assertNotIn('skipped',result.stderr)

    def test_source_authentication_and_real_cygwin_requirements_are_independent(self):
        require_posix_recipe_replay(os.name,Path('/usr/bin/make'),Path('/bin/bash'),
            os.environ.get(SOURCE_FLAG)=='1' or os.environ.get(CYGWIN_FLAG)=='1')
        # Use the complete authenticated originals as a pinned local source tree.
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder); manifest=json.loads((FIXTURE/'source.json').read_text())
            for pin in manifest['members']:
                actual=source/Path(pin['member']).relative_to('libreoffice-26.8.1.1')
                actual.parent.mkdir(parents=True,exist_ok=True); actual.write_bytes((FIXTURE/pin['fixture']).read_bytes())
            result=self.invoke(source,require_source=True)
            self.assertEqual(0,result.returncode,result.stdout+result.stderr)
            self.assertNotIn('skipped',result.stderr)
            make,_=require_posix_recipe_replay(os.name,Path('/usr/bin/make'),Path('/bin/bash'),False)
            profile=subprocess.run([str(make),'-s','-f','-','host'],input='host:\n\t@echo $(MAKE_HOST)\n',
                capture_output=True,text=True,check=True).stdout.strip()
            for require_source in (False,True):
                strict=self.invoke(source,require_source=require_source,require_cygwin=True)
                self.assertNotIn('skipped',strict.stderr)
                if profile.endswith('-cygwin'): self.assertEqual(0,strict.returncode,strict.stderr)
                else:
                    self.assertNotEqual(0,strict.returncode)
                    self.assertIn('Mandatory actual Cygwin GNU make profile is missing',strict.stderr)


if __name__ == '__main__': unittest.main()
