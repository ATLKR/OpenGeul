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
CONSUMER_FIXTURE = ROOT / 'suite/tests/fixtures/native-atl-consumers'
CONSUMER_RECIPES = (
    'embedserv/Library_emser.mk',
    'extensions/Library_oleautobridge.mk',
    'winaccessibility/Library_uacccom.mk',
    'winaccessibility/Library_winaccessibility.mk',
    'winaccessibility/WinResTarget_uacccom.mk',
)
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


def consumer_lock():
    value = json.loads((PORT/'source-build.json').read_text())
    if 'atlConsumerNativePaths' not in value:
        raise AssertionError('Authenticated native ATL consumer source hooks are missing')
    return value['atlConsumerNativePaths']


def consumer_plan(root):
    module = installer()
    if not callable(getattr(module, '_atl_consumer_native_paths', None)):
        raise AssertionError('Native ATL consumer source planner is missing')
    return module._atl_consumer_native_paths(root, consumer_lock())


def write_consumer_source(root):
    for name in CONSUMER_RECIPES:
        target = root/name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((CONSUMER_FIXTURE/name).read_bytes())


def consumer_adapter(root, native=NATIVE):
    # Explicit argv-only Linux/POSIX adapter. Strict actual-source mode below
    # uses the real builtin MAKE_HOST and cygpath, without this adapter.
    path = root/'cygpath'
    path.write_text('#!'+sys.executable+'\nimport sys\np=sys.argv[-1]\n'
        'assert sys.argv[1]=="-lm"\n'
        'if "missing" in p: sys.exit(7)\n'
        'if "empty" not in p: print(p.replace("/cygdrive/c/PROGRA~1/MICROS~2/atlmfc", '+repr(native)+'))\n')
    path.chmod(0o755)


def complete_make_macro(raw, name):
    start = raw.index(('define '+name+'\n').encode())
    end = raw.index(b'\nendef', start)+len(b'\nendef')
    return raw[start:end]+b'\n'


def replay_consumer(root, name, raw, make, bash, os_value='WNT', cpu='AARCH64',
                    com='MSC', host='x86_64-pc-cygwin', include=INCLUDE,
                    lib=LIB, adapter=True, dbgutil='FALSE'):
    observer = shlex.quote(sys.executable)+' '+shlex.quote(str(root/'observe.py'))
    resource = name == CONSUMER_RECIPES[-1]
    variables = ('SHELL := '+str(bash)+'\nOS := '+os_value+'\nCPUNAME := '+cpu+'\nCOM := '+com+'\n'
        +('MAKE_HOST := '+host+'\n' if host is not None else '')+
        'ATL_INCLUDE := '+include+'\nATL_LIB := '+lib+'\nSRCDIR := source\n'
        'INCLUDE := -Iexisting/include\nDEFS := -DEXISTING_DEFINITION\n'
        'TARGETTYPE := Library\nWORKDIR := C:/work\nENABLE_DBGUTIL := '+dbgutil+'\n'
        'CXX := configured-cxx\nCC := configured-cc\nLIB := configured-library-state\n'
        'gb_LINK := '+observer+'\ngb_RC := '+observer+'\n'
        'gb_CObject__compiler = '+observer+'\n'
        'gb_Helper_abbreviate_dirs = $(1)\n'
        'gb_Helper_remove_overridden_flags = $(1)\n'
        'gb_LinkTarget_get_target = all\n'
        'gb_Library_set_include = $(call gb_LinkTarget_set_include,$(1),$(2))\n'
        'gb_Library_add_ldflags = $(call gb_LinkTarget_add_ldflags,$(1),$(2))\n'
        'gb_Library_add_libs = $(call gb_LinkTarget_add_libs,$(1),$(2))\n'
        'gb_Library_add_defs = $(call gb_LinkTarget_add_defs,$(1),$(2))\n'
        'gb_Library_use_system_win32_libs = $(call gb_LinkTarget_add_libs,$(1),$(addsuffix .lib,$(2)))\n'
        'gb_FULLDEPS := TRUE\ntrue := TRUE\n'
        'gb_WinResTarget_get_target = rc\n'
        'gb_WinResTarget_get_clean_target = clean\n'
        'gb_WinResTarget_get_dep_target = dep\n'
        'gb_CustomTarget_workdir := C:/custom\n'
        'gb_CustomTarget_get_target = custom\n'
        'gb_Executable_get_target_for_build = '+observer+'\n'
        'global_before := $(OS)|$(CPUNAME)|$(COM)|$(MAKE_HOST)|$(ATL_INCLUDE)|$(ATL_LIB)|$(INCLUDE)|$(PATH)|$(LIB)|$(CXX)|$(CC)\n')
    macros = ((FIXTURE/'linktarget-atl.mk').read_bytes()+b'\n'+
              (CONSUMER_FIXTURE/'linktarget-defs.mk').read_bytes()+b'\n'+
              (FIXTURE/'msc-compile-argv.mk').read_bytes()+b'\n')
    if resource:
        winres = (CONSUMER_FIXTURE/'solenv/gbuild/WinResTarget.mk').read_bytes()
        for macro in ('gb_WinResTarget_add_defs', 'gb_WinResTarget__add_include',
                      'gb_WinResTarget_set_include', 'gb_WinResTarget_set_rcfile',
                      'gb_WinResTarget__use_custom_headers', 'gb_WinResTarget_use_custom_headers'):
            macros += complete_make_macro(winres, macro)+b'\n'
        macros += (CONSUMER_FIXTURE/'msc-resource-argv.mk').read_bytes()+b'\n'
        source = root/'source/winaccessibility/source/UAccCOM/UAccCOM.rc'
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b'// argv replay input only; no native resource compilation\n')
        commands = (b'\n.PHONY: all rc dep custom\nall: rc dep\ncustom:\nrc:\n'
                    b'\t@$(call gb_WinResTarget__command,resource.res,UAccCOM,$(RCFILE))\n'
                    b'dep:\n\t@$(call gb_WinResTarget__command_dep,resource.d,UAccCOM,resource.res)\n')
    else:
        commands = (b'\n.PHONY: all\nall:\n'
            b'\t@$(call gb_CObject__command_pattern,object.obj,-O2 -GL,source.cpp,object.d)\n'+
            b'\t@'+(FIXTURE/'msc-link-argv.mk').read_bytes().lstrip(b'\t'))
    # An immediate post-recipe assertion checks global state before target-only
    # INCLUDE/DEFS assignments apply. It does not hide altered global variables.
    invariant = (b'\nglobal_after := $(OS)|$(CPUNAME)|$(COM)|$(MAKE_HOST)|$(ATL_INCLUDE)|$(ATL_LIB)|$(INCLUDE)|$(PATH)|$(LIB)|$(CXX)|$(CC)\n'
                 b'ifneq ($(global_before),$(global_after))\n$(error Recipe changed global configured state)\nendif\n')
    makefile = root/'consumer-replay.mk'
    makefile.write_bytes(variables.encode()+macros+raw+invariant+commands)
    env = dict(os.environ)
    if adapter: env['PATH'] = str(root)+os.pathsep+env['PATH']
    return subprocess.run([str(make),'--no-print-directory','-s','-f',str(makefile),'all'],
                          cwd=root, env=env, capture_output=True, text=True, timeout=30)


def assert_consumer_native_argv(case, name, before, after, native_include, native_lib):
    case.assertEqual(2, len(before), name)
    case.assertEqual(2, len(after), name)
    expected = [[item.replace(INCLUDE, native_include).replace(LIB, native_lib)
                 for item in argv] for argv in before]
    if name == CONSUMER_RECIPES[-1]:
        case.assertEqual(expected, after, name+' RC and dependency argv/order')
        case.assertIn('-I'+native_include, after[0], name+' RC include')
        case.assertIn('-I'+native_include, after[1], name+' dependency include')
    else:
        case.assertEqual(expected[0], after[0], name+' compile argv/order')
        atls = native_lib+'/atls.lib'
        # Only atls.lib moves around the authentic sort(T_LIBS) boundary.
        # Everything else retains its exact argv sequence, including LIBPATH,
        # /DEF, every system library (and any deliberate duplicate), and flags.
        case.assertEqual([item for item in expected[1] if item != atls],
                         [item for item in after[1] if item != atls], name+' link argv/order')
        case.assertEqual(1 if name in CONSUMER_RECIPES[:3] else 0,
                         after[1].count(atls), name+' intact atls.lib operand')
        case.assertEqual(name in CONSUMER_RECIPES[:2],
                         '-LIBPATH:'+native_lib in after[1], name+' original LIBPATH policy')


def assert_consumer_replays(case, root, make, bash, candidates, actual=False):
    (root/'observe.py').write_text('import json,sys;print(json.dumps(sys.argv[1:]))\n')
    if not actual: consumer_adapter(root)
    for name, _, effective in candidates:
        # The planner source may live elsewhere; match the explicit finite path.
        name = next(path for path in CONSUMER_RECIPES if name.as_posix().endswith('/'+path))
        original = (CONSUMER_FIXTURE/name).read_bytes()
        kwargs = {'host':None, 'adapter':False} if actual else {}
        if actual:
            include = root/'include'
            include.mkdir(exist_ok=True)
            lib = root/'library'
            lib.mkdir(exist_ok=True)
            kwargs.update(include=str(include), lib=str(lib))
            converted = [subprocess.run(['cygpath','-lm',str(path)],capture_output=True,
                        text=True,check=True).stdout.strip() for path in (include,lib)]
            baseline = replay_consumer(root,name,original,make,bash,**kwargs)
            candidate = replay_consumer(root,name,effective,make,bash,**kwargs)
            case.assertEqual(0, baseline.returncode, baseline.stderr)
            case.assertEqual(0, candidate.returncode, candidate.stderr)
            # Replace the actual configured inputs into a normalized baseline
            # for the common exact argv oracle; no receiver output is invented.
            before = [[item.replace(str(include),INCLUDE).replace(str(lib),LIB)
                       for item in argv] for argv in observed_argv(baseline.stdout)]
            assert_consumer_native_argv(case,name,before,observed_argv(candidate.stdout),*converted)
            if name in CONSUMER_RECIPES[:3]:
                long_lib = root/'library with  double spaces'
                long_lib.mkdir(exist_ok=True)
                converted_lib = subprocess.run(['cygpath','-lm',str(long_lib)],
                    capture_output=True,text=True,check=True).stdout.strip()
                long = replay_consumer(root,name,effective,make,bash,
                    host=None,adapter=False,include=str(include),lib=str(long_lib))
                case.assertEqual(0,long.returncode,long.stderr)
                long_argv = observed_argv(long.stdout)
                case.assertEqual(1,long_argv[1].count(converted_lib+'/atls.lib'))
                case.assertEqual(name in CONSUMER_RECIPES[:2],'-LIBPATH:'+converted_lib in long_argv[1])
            continue
        baseline = replay_consumer(root,name,original,make,bash)
        candidate = replay_consumer(root,name,effective,make,bash)
        case.assertEqual(0, baseline.returncode, baseline.stderr)
        case.assertEqual(0, candidate.returncode, candidate.stderr)
        before, after = observed_argv(baseline.stdout), observed_argv(candidate.stdout)
        case.assertIn('-I'+INCLUDE,before[0],name+' authentic pristine Cygwin include')
        assert_consumer_native_argv(case,name,before,after,NATIVE+'/include',NATIVE+'/lib/spectre/arm64')
        for os_value,cpu,com,host in (
                ('WNT','X86_64','MSC','x86_64-pc-cygwin'),
                ('WNT','INTEL','MSC','x86_64-pc-cygwin'),
                ('LINUX','AARCH64','MSC','x86_64-pc-cygwin'),
                ('WNT','AARCH64','CLANG','x86_64-pc-cygwin'),
                ('WNT','AARCH64','MSC','x86_64-w64-mingw32'),
                ('WNT','AARCH64','MSC','x86_64-pc-linux-gnu'),
                ('WNT','AARCH64','MSC','x86_64-pc-msys'),
                ('WNT','AARCH64','MSC','x86_64-pc-wsl')):
            profile = dict(os_value=os_value,cpu=cpu,com=com,host=host)
            old = replay_consumer(root,name,original,make,bash,**profile)
            new = replay_consumer(root,name,effective,make,bash,**profile)
            case.assertEqual(0,old.returncode,old.stderr)
            case.assertEqual(0,new.returncode,new.stderr)
            case.assertEqual(old.stdout,new.stdout,name+' exact non-target argv '+repr(profile))
        multiple = replay_consumer(root,name,effective,make,bash,include=INCLUDE+' '+INCLUDE+'/extras')
        case.assertEqual(0,multiple.returncode,multiple.stderr)
        case.assertEqual(['-I'+NATIVE+'/include','-I'+NATIVE+'/include/extras'],
                         [item for item in observed_argv(multiple.stdout)[0]
                          if item.startswith('-I'+NATIVE)],name+' include order')
        doubled = NATIVE.replace('Program Files','Program  Files')
        consumer_adapter(root,doubled)
        spaces = replay_consumer(root,name,effective,make,bash)
        case.assertEqual(0,spaces.returncode,spaces.stderr)
        assert_consumer_native_argv(case,name,before,observed_argv(spaces.stdout),
                                   doubled+'/include',doubled+'/lib/spectre/arm64')
        consumer_adapter(root)
        for value in ('/missing/atl','/empty/atl',''):
            for key in ('include','lib') if name in CONSUMER_RECIPES[:3] else ('include',):
                failed = replay_consumer(root,name,effective,make,bash,**{key:value})
                case.assertNotEqual(0,failed.returncode,name+' '+key+' '+value)
                case.assertIn('ATL',failed.stderr)
                case.assertEqual('',failed.stdout)
        if name in CONSUMER_RECIPES[3:]:
            for value in ('/missing/atl','/empty/atl',''):
                unused = replay_consumer(root,name,effective,make,bash,lib=value)
                case.assertEqual(0,unused.returncode,name+' must ignore unused ATL_LIB: '+unused.stderr)
                case.assertEqual(after,observed_argv(unused.stdout))
        else:
            # Deliberately put an otherwise quoted long native atls.lib operand
            # back through the authentic sorted T_LIBS route. GNU make word
            # sorting destroys its intact argv even though Bash sees quotes.
            naive = original.replace(b'$(ATL_LIB)/atls.lib',
                ('"'+NATIVE+'/lib/spectre/arm64/atls.lib"').encode())
            rejected = replay_consumer(root,name,naive,make,bash)
            case.assertEqual(0,rejected.returncode,rejected.stderr)
            case.assertNotIn(NATIVE+'/lib/spectre/arm64/atls.lib',observed_argv(rejected.stdout)[1],
                             name+' must detect naive quoted long path in sorted T_LIBS')
        if name == CONSUMER_RECIPES[-1]:
            debug = replay_consumer(root,name,effective,make,bash,dbgutil='TRUE')
            case.assertEqual(0,debug.returncode,debug.stderr)
            case.assertEqual([[item for item in argv if item != '-DPRODUCT'] for argv in after],
                             observed_argv(debug.stdout),'Preserve resource product/debug definition')


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
        driver = (ROOT/'suite/scripts/build-native-engine.ps1').read_text()
        functions = driver.split('function Write-NativeSourceGate(',1)
        self.assertEqual(2,len(functions))
        body, closing, _ = functions[1].partition('\n}')
        self.assertEqual('\n}',closing)
        # Parse the quoted source literals without running a native Windows
        # process from the actual Cygwin source gate.
        lexer = shlex.shlex(body,posix=False,punctuation_chars=',()')
        lexer.whitespace_split = True
        literals = [token for token in lexer
                    if len(token)>1 and token[0] in "\"'" and token[-1]==token[0]]
        self.assertEqual([['/usr/bin/python3','-m','unittest',
            'suite.tests.test_firebird_arm64_port','suite.tests.test_native_python_host',
            'suite.tests.test_native_atl_path','suite.tests.test_native_meson_path','-v']],
            [shlex.split(token[1:-1]) for token in literals
             if token.startswith("'/usr/bin/python3 ")])
        self.assertEqual([
            'export PATH=/usr/local/bin:/usr/bin:/bin:`$PATH',
            'export OPENGEUL_FIREBIRD_PORT_REQUIRE_SOURCE=1',
            'export OPENGEUL_ATL_REQUIRE_CYGWIN_REPLAY=1',
            'export OPENGEUL_MESON_REQUIRE_CYGWIN_REPLAY=1',
            'export OPENGEUL_FIREBIRD_SOURCE_ARCHIVE=$(Quote-Bash $FirebirdArchive)',
            'export OPENGEUL_MDDS_SOURCE_ARCHIVE=$(Quote-Bash $MddsArchive)',
            "export OPENGEUL_LIBREOFFICE_FIREBIRD_PATCHES=$(Quote-Bash ($SourceRoot+'/external/firebird'))",
            'export OPENGEUL_LIBREOFFICE_ATL_SOURCE=$(Quote-Bash $SourceRoot)',
            'export OPENGEUL_LIBREOFFICE_MESON_SOURCE=$(Quote-Bash $SourceRoot)',
            "export OPENGEUL_LIBREOFFICE_PYTHON_PATCHES=$(Quote-Bash ($SourceRoot+'/external/python3'))"],
            [token[1:-1] for token in literals if token.startswith('"export ')])

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


class AtlConsumerSourceTests(unittest.TestCase):
    def test_five_complete_authentic_recipes_are_pinned_and_planned_without_writes(self):
        manifest = json.loads((CONSUMER_FIXTURE/'source.json').read_text())
        self.assertEqual('296ba78e7ab0d381b94c3d6342f4ebb2320ee5097ca58781b9b744cab90b9785',manifest['archiveSha256'])
        for pin in manifest['members']:
            raw = (CONSUMER_FIXTURE/pin['fixture']).read_bytes()
            self.assertEqual(pin['fixtureBytes'],len(raw))
            self.assertEqual(pin['fixtureSha256'],hashlib.sha256(raw).hexdigest())
        self.assertEqual(list(CONSUMER_RECIPES),[pin['path'] for pin in consumer_lock()['recipes']])
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_consumer_source(root)
            planned = consumer_plan(root)
            self.assertEqual(list(CONSUMER_RECIPES),[path.relative_to(root).as_posix() for path,_,_ in planned])
            for (path,before,after),pin in zip(planned,consumer_lock()['recipes']):
                self.assertEqual((CONSUMER_FIXTURE/pin['path']).read_bytes(),before)
                self.assertEqual(before,path.read_bytes(),'Planning must not write any source')
                self.assertEqual(pin['size'],len(before))
                self.assertEqual(pin['sha256'],hashlib.sha256(before).hexdigest())
                self.assertEqual(pin['afterSize'],len(after))
                self.assertEqual(pin['afterSha256'],hashlib.sha256(after).hexdigest())
                self.assertNotEqual(before,after)
                prefix = {'embedserv/Library_emser.mk':'emser',
                    'extensions/Library_oleautobridge.mk':'oleautobridge',
                    'winaccessibility/Library_uacccom.mk':'uacccom',
                    'winaccessibility/Library_winaccessibility.mk':'winaccessibility',
                    'winaccessibility/WinResTarget_uacccom.mk':'uacccom_resource'}[pin['path']]+'_native_atl'
                variable = prefix.encode()
                marker = (b'$(eval $(call gb_WinResTarget_WinResTarget,UAccCOM))'
                    if pin['path']==CONSUMER_RECIPES[-1] else
                    ('$(eval $(call gb_Library_Library,'+
                        ('UAccCOM' if pin['path']==CONSUMER_RECIPES[2] else prefix.removesuffix('_native_atl'))+'))').encode())
                start=after.index(b'# OpenGeul: keep native ATL arguments local to this recipe.\n')
                end=after.index(marker,start)
                restored=after[:start]+after[end:]
                original_include=(b'-I$(ATL_INCLUDE)' if pin['path']==CONSUMER_RECIPES[0] else
                    b'$(foreach inc,$(ATL_INCLUDE),-I$(inc))' if pin['path']==CONSUMER_RECIPES[1] else
                    b'$(foreach i,$(ATL_INCLUDE), -I$(i))')
                restored=restored.replace(b'$('+variable+b'_INCLUDE)',original_include)
                restored=restored.replace(b'$('+variable+b'_LIBS)',b'$(ATL_LIB)/atls.lib')
                restored=restored.replace(b'-LIBPATH:$('+variable+b'_LIB) $('+variable+b'_LINK_LIB)',b'-LIBPATH:$(ATL_LIB)')
                restored=restored.replace(b'UAccCOM.def $('+variable+b'_LINK_LIB)',b'UAccCOM.def')
                self.assertEqual(before,restored,'Semantic reverse must restore the complete authentic recipe')

    def test_each_missing_changed_linked_recipe_or_ancestor_fails_without_writes(self):
        for name in CONSUMER_RECIPES:
            for variant in ('missing','changed','linked-recipe','linked-parent'):
                with self.subTest(recipe=name,variant=variant),tempfile.TemporaryDirectory() as folder:
                    root=Path(folder)
                    write_consumer_source(root)
                    target=root/name
                    if variant=='missing': target.unlink()
                    elif variant=='changed': target.write_bytes(target.read_bytes()+b'changed')
                    elif variant=='linked-recipe':
                        saved=root/'saved';saved.write_bytes(target.read_bytes());target.unlink();target.symlink_to(saved)
                    else:
                        saved=root/'saved-dir';target.parent.rename(saved);target.parent.symlink_to(saved,target_is_directory=True)
                    before={path.relative_to(root).as_posix():path.read_bytes()
                            for path in root.rglob('*') if path.is_file()}
                    with self.assertRaises((ValueError,FileNotFoundError)):
                        consumer_plan(root)
                    self.assertEqual(before,{path.relative_to(root).as_posix():path.read_bytes()
                                     for path in root.rglob('*') if path.is_file()})

    def test_changed_recipe_set_or_output_pin_fails_without_writes(self):
        for variant in ('missing','reordered','duplicate','unexpected','before-size','before-sha','after-size','after-sha'):
            with self.subTest(variant=variant),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);write_consumer_source(root)
                spec=json.loads(json.dumps(consumer_lock()))
                if variant=='missing': spec['recipes'].pop()
                elif variant=='reordered': spec['recipes'].reverse()
                elif variant=='duplicate': spec['recipes'][1]=spec['recipes'][0]
                elif variant=='unexpected': spec['recipes'][0]['path']='extensions/Library_so_activex.mk'
                else:
                    key={'before-size':'size','before-sha':'sha256','after-size':'afterSize','after-sha':'afterSha256'}[variant]
                    spec['recipes'][0][key]=0 if key in ('size','afterSize') else '0'*64
                before={name:(root/name).read_bytes() for name in CONSUMER_RECIPES}
                with self.assertRaises((ValueError,FileNotFoundError)):
                    installer()._atl_consumer_native_paths(root,spec)
                self.assertEqual(before,{name:(root/name).read_bytes() for name in CONSUMER_RECIPES})


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
            write_consumer_source(root)
            assert_consumer_replays(self,root,make,bash,consumer_plan(root))


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
        consumer_manifest=json.loads((CONSUMER_FIXTURE/'source.json').read_text())
        for pin in consumer_manifest['members']:
            actual=source/Path(pin['member']).relative_to('libreoffice-26.8.1.1')
            self.assertFalse(any(path.is_symlink() for path in (actual,*actual.parents)),'Actual ATL consumer source must be unlinked')
            raw=installer()._regular(actual)
            self.assertEqual(pin['bytes'],len(raw))
            self.assertEqual(pin['sha256'],hashlib.sha256(raw).hexdigest())
            if 'physicalLfRanges' in pin:
                lines=raw.split(b'\n')
                sliced=b''.join(b'\n'.join(lines[start-1:end])+b'\n' for start,end in pin['physicalLfRanges'])
                self.assertEqual((CONSUMER_FIXTURE/pin['fixture']).read_bytes(),sliced)
        consumers=consumer_plan(source)
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
                assert_consumer_replays(self,root,make,bash,consumers,actual=True)


if __name__ == '__main__': unittest.main()
