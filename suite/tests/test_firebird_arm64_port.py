"""Port evidence uses authenticated upstream source, not synthetic PE files.

Set OPENGEUL_FIREBIRD_SOURCE_ARCHIVE to the pinned Firebird source tar.bz2 and
OPENGEUL_LIBREOFFICE_FIREBIRD_PATCHES to the pinned LO external/firebird folder
and OPENGEUL_MDDS_SOURCE_ARCHIVE to the pinned MDDS archive. Optional
OPENGEUL_LIBREOFFICE_MDDS_PATCHES overrides the sibling external/mdds directory
for the actual patch-application/compiler checks. No test downloads inputs.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tarfile
import tempfile
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
PORT = ROOT / 'suite/engine-build'
SOURCE_SHA = 'bd263c4f685fb8fc3f1dcb8be8a411033cc31c5404d1dfce5d3849aa3f63a64d'


def module():
    spec = importlib.util.spec_from_file_location('firebird_arm64_port', PORT / 'enable_firebird_arm64.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class PortInputs(unittest.TestCase):
    def test_source_and_patch_are_locked(self):
        self.assertTrue((PORT / 'source-build.json').is_file(), 'Authenticated source-build manifest is missing')
        lock = json.loads((PORT / 'source-build.json').read_text())
        self.assertEqual(lock['libreoffice']['sha256'], '296ba78e7ab0d381b94c3d6342f4ebb2320ee5097ca58781b9b744cab90b9785')
        self.assertEqual(lock['firebird']['sha256'], SOURCE_SHA)
        self.assertEqual(lock['firebird']['version'], '3.0.13.33818-0')
        patch = PORT / lock['portPatch']['filename']
        self.assertEqual(hashlib.sha256(patch.read_bytes()).hexdigest(), lock['portPatch']['sha256'])
        self.assertIn('--enable-firebird-sdbc', lock['configureOptions'])
        self.assertFalse(lock['nativeBuildVerified'])

    def test_changed_lo_hook_is_rejected_without_publishing_patch(self):
        self.assertTrue((PORT / 'enable_firebird_arm64.py').is_file(), 'Source hook installer is missing')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root / 'external/firebird/UnpackedTarball_firebird.mk'
            target.parent.mkdir(parents=True)
            target.write_bytes(b'changed source hook')
            before = list(target.parent.iterdir())
            with self.assertRaisesRegex(ValueError, 'SHA256'):
                module().install(root)
            self.assertEqual(list(target.parent.iterdir()), before)
            self.assertEqual(target.read_bytes(), b'changed source hook')


class AuthenticatedSource(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        value = os.environ.get('OPENGEUL_FIREBIRD_SOURCE_ARCHIVE')
        patches = os.environ.get('OPENGEUL_LIBREOFFICE_FIREBIRD_PATCHES')
        cls.required = os.environ.get('OPENGEUL_FIREBIRD_PORT_REQUIRE_SOURCE') == '1'
        if not value or not patches:
            if cls.required:
                raise AssertionError('Mandatory pinned Firebird source inputs are missing')
            raise unittest.SkipTest('Pinned local Firebird archive and LO patch folder are required')
        cls.archive, cls.lo_patches = Path(value), Path(patches)
        configure = cls.lo_patches.parent.parent / 'configure.ac'
        if not configure.is_file():
            configure = cls.lo_patches / 'configure.ac'
        cls.lo_configure = Path(os.environ.get('OPENGEUL_LIBREOFFICE_CONFIGURE_AC', str(configure)))
        actual = hashlib.sha256(cls.archive.read_bytes()).hexdigest()
        if actual != SOURCE_SHA:
            raise AssertionError('Firebird source archive differs from the pinned SHA256')
        cls.mdds_archive = None
        mdds_value = os.environ.get('OPENGEUL_MDDS_SOURCE_ARCHIVE')
        cls.mdds_patches = Path(os.environ.get('OPENGEUL_LIBREOFFICE_MDDS_PATCHES', str(cls.lo_patches.parent / 'mdds')))
        if mdds_value:
            cls.mdds_archive = Path(mdds_value)
            if cls.mdds_archive.stat().st_size != 648256 or hashlib.sha256(cls.mdds_archive.read_bytes()).hexdigest() != '673f5bb94612dbba581fc92b99b5e5dd1a53e29496a5dbc936432f6b0687c112':
                raise AssertionError('MDDS source archive differs from the pinned size/SHA256')
        elif cls.required:
            raise AssertionError('Mandatory pinned MDDS source archive is missing')
        cls.compiler = shutil.which('cc') or shutil.which('gcc')
        cls.cxx = shutil.which('c++') or shutil.which('g++')
        if not cls.compiler or not shutil.which('patch'):
            if cls.required:
                raise AssertionError('Mandatory C compiler/preprocessor or GNU patch is missing')
            raise unittest.SkipTest('A C preprocessor/compiler and GNU patch are required')

    def mdds_recipe(self, root):
        harfbuzz = root / 'external/harfbuzz/ExternalProject_harfbuzz.mk'
        harfbuzz.parent.mkdir(parents=True, exist_ok=True)
        harfbuzz.write_bytes((ROOT / 'suite/tests/fixtures/native-meson-path' / harfbuzz.name).read_bytes())
        atl = root / 'extensions/Library_so_activex.mk'
        atl.parent.mkdir(exist_ok=True)
        atl.write_bytes((ROOT / 'suite/tests/fixtures/native-atl-path' / atl.name).read_bytes())
        for relative in ('embedserv/Library_emser.mk', 'extensions/Library_oleautobridge.mk',
                         'winaccessibility/Library_uacccom.mk', 'winaccessibility/Library_winaccessibility.mk',
                         'winaccessibility/WinResTarget_uacccom.mk'):
            consumer = root / relative
            consumer.parent.mkdir(parents=True, exist_ok=True)
            consumer.write_bytes((ROOT / 'suite/tests/fixtures/native-atl-consumers' / relative).read_bytes())
        python = root / 'external/python3/ExternalProject_python3.mk'
        python.parent.mkdir(parents=True, exist_ok=True)
        python.write_bytes((ROOT / 'suite/tests/fixtures/native-python-host' / python.name).read_bytes())
        target = root / 'external/mdds/UnpackedTarball_mdds.mk'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / 'suite/tests/fixtures/native-mdds-equality' / target.name).read_bytes())
        upstream = 'gcc-12-silence-use-after-free.patch.1'
        (target.parent / upstream).write_bytes((self.mdds_patches / upstream).read_bytes())
        return target

    def test_real_mdds_patch_selection_replays_exact_native_candidate(self):
        if self.mdds_archive is None:
            self.skipTest('Pinned local MDDS archive is required')
        archive, patches = self.mdds_archive, self.mdds_patches
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            hook = root / 'external/firebird/UnpackedTarball_firebird.mk'; hook.parent.mkdir(parents=True)
            hook.write_bytes((self.lo_patches / hook.name).read_bytes())
            (hook.parent / 'ExternalProject_firebird.mk').write_bytes((ROOT / 'suite/tests/fixtures/native-icu-path/ExternalProject_firebird.mk').read_bytes())
            (root / 'configure.ac').write_bytes(self.lo_configure.read_bytes())
            bootstrap = root / 'bin/unpack-sources'; bootstrap.parent.mkdir()
            bootstrap.write_bytes((ROOT / 'suite/tests/fixtures/native-source-tar/unpack-sources').read_bytes())
            zstd = root / 'external/zstd/UnpackedTarball_zstd.mk'; zstd.parent.mkdir()
            zstd.write_bytes((ROOT / 'suite/tests/fixtures/native-zstd-unpack/UnpackedTarball_zstd.mk').read_bytes())
            recipe = self.mdds_recipe(root); original = recipe.read_bytes()
            def selection(raw, platform):
                makefile = root / 'selection.mk'
                makefile.write_text('OS := '+platform[0]+'\nCPUNAME := '+platform[1]+'\n'
                    'gb_UnpackedTarball_add_patches = $(eval selected += $(2))\n'+raw.decode()+
                    '\nall:\n\t@echo $(selected)\n')
                result = subprocess.run(['make', '--no-print-directory', '-f', str(makefile)], capture_output=True, text=True, check=True)
                return result.stdout.split()
            gcc = 'external/mdds/gcc-12-silence-use-after-free.patch.1'
            own = 'external/mdds/opengeul-arm64-equality.patch.1'
            for platform in [('WNT','AARCH64'), ('WNT','X86_64'), ('LINUX','AARCH64')]:
                self.assertEqual([gcc], selection(original, platform))
            evidence = root / 'evidence'; evidence.mkdir()
            receipt = module().install(root, evidence)
            self.assertEqual([gcc, own], selection(recipe.read_bytes(), ('WNT','AARCH64')))
            for platform in [('WNT','X86_64'), ('LINUX','AARCH64')]:
                self.assertEqual([gcc], selection(recipe.read_bytes(), platform))
            lock = json.loads((PORT / 'source-build.json').read_text())['mddsEquality']
            unpack = root / 'unpack'; unpack.mkdir()
            with tarfile.open(archive, 'r:xz') as source:
                for member in source:
                    name = Path(member.name)
                    self.assertFalse(name.is_absolute() or '..' in name.parts)
                    if member.isfile():
                        target = unpack.joinpath(*name.parts[1:]); target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(source.extractfile(member).read())
            upstream = patches / Path(gcc).name
            self.assertEqual(lock['upstreamPatch']['sha256'], hashlib.sha256(upstream.read_bytes()).hexdigest())
            for item in lock['headers']:
                raw = (unpack / item['path']).read_bytes()
                self.assertEqual(item['beforeSha256'], hashlib.sha256(raw).hexdigest())
            self.apply(unpack, upstream, 1)
            self.apply(unpack, root / own, 1)
            for item in lock['headers'] + [lock['nodeHeader']]:
                raw = (unpack / item['path']).read_bytes()
                self.assertEqual(item['afterBytes'], len(raw))
                self.assertEqual(item['afterSha256'], hashlib.sha256(raw).hexdigest())
            self.assertEqual(original, (evidence / 'original-UnpackedTarball_mdds.mk').read_bytes())
            self.assertEqual(recipe.read_bytes(), (evidence / 'effective-UnpackedTarball_mdds.mk').read_bytes())
            self.assertEqual(lock['recipe']['afterSha256'], receipt['mddsEquality']['afterSha256'])
            self.assertEqual(lock['patch']['sha256'], receipt['mddsEquality']['patchSha256'])

    def source_tree(self, folder):
        root = Path(folder) / 'firebird'
        root.mkdir()
        # Only regular members enter this disposable tree; no source binaries execute.
        with tarfile.open(self.archive, 'r:bz2') as source:
            for member in source:
                name = Path(member.name)
                if name.is_absolute() or '..' in name.parts:
                    raise AssertionError('Unsafe authenticated source member')
                if member.isfile():
                    target = root.joinpath(*name.parts[1:])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(source.extractfile(member).read())
        lock = json.loads((PORT / 'source-build.json').read_text())
        for item in lock['upstreamWindowsPatches']:
            patch = self.lo_patches / item['filename']
            self.assertEqual(hashlib.sha256(patch.read_bytes()).hexdigest(), item['sha256'])
            self.apply(root, patch, item['strip'])
        return root

    def apply(self, root, patch, strip=0):
        arguments = ['patch', '--batch', '--forward', '--fuzz=0', '-p' + str(strip), '-i', str(patch.resolve())]
        subprocess.run(arguments[:1] + ['--dry-run'] + arguments[1:], cwd=root, capture_output=True, check=True)
        subprocess.run(arguments, cwd=root, capture_output=True, check=True)

    def compile_cpu(self, root, architecture):
        header = (root / 'src/common/common.h').read_text()
        start = header.index('#ifdef WIN_NT')
        end = header.index('#endif /* WIN_NT */', start) + len('#endif /* WIN_NT */')
        branch = header[start:end]
        macros = {'arm64': '_M_ARM64', 'x64': '_M_AMD64', 'x86': '_M_IX86'}
        cpus = {'arm64': 'CpuArm64', 'x64': 'CpuAmd', 'x86': 'CpuIntel'}
        text = ('#define _MSC_VER 1940\n#define ' + macros[architecture] + ' 1\n'
                '#include "' + str(root / 'builds/make.new/config/config.h.in') + '"\n'
                + branch + '\n'
                'enum { CpuIntel = 0, CpuAmd = 1, CpuArm64 = 15 };\n'
                '_Static_assert(FB_CPU == ' + cpus[architecture] + ', "incorrect native CPU");\n')
        text += ('#ifndef I386\n#error x86 identity missing\n#endif\n' if architecture == 'x86'
                 else '#ifdef I386\n#error native 64-bit CPU misclassified as x86\n#endif\n')
        return subprocess.run([self.compiler, '-std=c11', '-x', 'c', '-fsyntax-only', '-'],
                              input=text, text=True, capture_output=True)

    def test_real_source_reproduces_arm_cpu_defect_then_port_preserves_x64_x86(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.source_tree(folder)
            old = self.compile_cpu(root, 'arm64')
            self.assertNotEqual(old.returncode, 0, 'Unpatched source no longer reproduces the CPU defect')
            self.assertIn('incorrect native CPU', old.stderr)
            implementation = (root / 'src/common/classes/DbImplementation.cpp').read_text()
            self.assertRegex(implementation, r'CpuArm64\s*=\s*15;')
            self.apply(root, PORT / 'firebird-windows-arm64.patch')
            for architecture in ('arm64', 'x64', 'x86'):
                result = self.compile_cpu(root, architecture)
                self.assertEqual(result.returncode, 0, architecture + ': ' + result.stderr)

    def compile_fpe(self, root, architecture):
        if not self.cxx:
            if self.required:self.fail('Mandatory C++ compiler for actual FpeControl source check is missing')
            self.skipTest('A C++ compiler is required for the FpeControl source check')
        include=root/'test-api';include.mkdir(exist_ok=True)
        # Declaration-only surface from Microsoft's official UCRT float.h:
        # microsoft/win32metadata/generation/WinSDK/RecompiledIdlHeaders/ucrt/float.h
        # SHA256 54277b70e18bf90ab6573b12ee37334ec3d7a43afca360529e37337f1ac5c6ba.
        # The authoritative header guards __control87_2 with _M_IX86; this
        # fixture supplies no implementation and claims no Windows ABI/runtime.
        (include/'float.h').write_text(
            '#define _MCW_EM 0x0008001f\n'
            '#if defined(_M_IX86)\n#define _CW_DEFAULT 0x0009001f\n'
            '#else\n#define _CW_DEFAULT 0x0008001f\n#endif\n'
            'extern "C" unsigned int _clearfp(void);\n'
            'extern "C" unsigned int _controlfp(unsigned int, unsigned int);\n'
            'extern "C" int _fpclass(double);\nextern "C" int _finite(double);\n'
            'extern "C" int _isnan(double);\n#define _FPCLASS_NINF 0x0004\n'
            '#ifdef _M_IX86\n'
            'extern "C" int __control87_2(unsigned int, unsigned int, unsigned int*, unsigned int*);\n'
            '#endif\n')
        # Avoid importing the host Linux math declarations into the Windows
        # source check. The required Microsoft math names above are declarations.
        (include/'math.h').write_text('#pragma once\n')
        macros={'arm64':'#define _M_ARM64 1\n','x64':'#define _M_AMD64 1\n#define _M_X64 1\n',
                'x86':'#define _M_IX86 1\n'}
        text=('#include <cstddef>\n#define _MSC_VER 1940\n'+macros[architecture]+
              '#include "'+str(root/'builds/make.new/config/config.h.in')+'"\n'+
              '#include "'+str(root/'src/common/classes/FpeControl.h')+'"\n'+
              'void exercise_source() { Firebird::FpeControl state; Firebird::FpeControl::maskAll(); }\n')
        return subprocess.run([self.cxx,'-std=c++11','-x','c++','-fsyntax-only','-I'+str(include),'-'],
                              input=text,text=True,capture_output=True)

    def test_real_fpe_source_rejects_x86_only_api_on_arm64_then_preserves_x64_i386(self):
        with tempfile.TemporaryDirectory() as folder:
            root=self.source_tree(folder)
            original=(root/'src/common/classes/FpeControl.h').read_bytes()
            self.assertEqual(hashlib.sha256(original).hexdigest(),
                             'ebc4c409cf9f69d04375310c83e72f1e13792f16c79b33360a5ae916d9acaa80')
            failed=self.compile_fpe(root,'arm64')
            self.assertNotEqual(failed.returncode,0,'Original ARM64 FPE defect no longer reproduces')
            self.assertIn('__control87_2',failed.stderr)
            for architecture in ('x64','x86'):
                before=self.compile_fpe(root,architecture)
                self.assertEqual(before.returncode,0,architecture+': '+before.stderr)
            self.apply(root,PORT/'firebird-windows-arm64.patch')
            self.assertEqual((root/'src/common/classes/FpeControl.h').read_bytes(),
                             original.replace(b'#ifdef AMD64\n',b'#if defined(AMD64) || defined(ARM64)\n'),
                             'Floating-point masks, calls, order or non-ARM branches changed')
            for architecture in ('arm64','x64','x86'):
                after=self.compile_fpe(root,architecture)
                self.assertEqual(after.returncode,0,architecture+': '+after.stderr)

    def compile_msvc_platform(self, root, architecture):
        if not self.cxx:
            if self.required:self.fail('Mandatory C++ compiler for the MSVC platform-header check is missing')
            self.skipTest('A C++ compiler is required for the MSVC platform-header check')
        macros={'arm64':'#define _M_ARM64 1\n','x64':'#define _M_AMD64 1\n#define _M_X64 1\n',
                'x86':'#define _M_IX86 1\n','unknown':'','arm64ec':'#define _M_ARM64 1\n#define _M_ARM64EC 1\n'}
        text=('#define _MSC_VER 1940\n'+macros[architecture]+
              '#include "'+str(root/'src/include/gen/autoconfig_msvc.h')+'"\n')
        if architecture in ('arm64','x64','x86'):
            common=(root/'src/common/common.h').read_text()
            start=common.index('#ifdef WIN_NT');end=common.index('#endif /* WIN_NT */',start)+len('#endif /* WIN_NT */')
            cpu={'arm64':'CpuArm64','x64':'CpuAmd','x86':'CpuIntel'}[architecture]
            size=4 if architecture=='x86' else 8
            text+=('enum { CpuIntel=0, CpuAmd=1, CpuArm64=15 };\n'+common[start:end]+'\n'+
                   'static_assert(FB_CPU=='+cpu+',"wrong CPU identity from fixed MSVC header");\n'+
                   'static_assert(SIZEOF_VOID_P=='+str(size)+',"wrong pointer-size definition");\n'+
                   'static_assert(SIZEOF_SIZE_T=='+str(size)+',"wrong size_t definition");\n'+
                   'static_assert(FB_ALIGNMENT=='+str(size)+',"wrong Firebird alignment definition");\n'+
                   'static_assert(SIZEOF_LONG==4,"Windows long must remain 32-bit");\n'+
                   'static_assert(FB_DOUBLE_ALIGN==8,"double alignment must remain eight");\n'+
                   '#ifndef WIN_NT\n#error Windows platform missing\n#endif\n'+
                   '#ifdef WORDS_BIGENDIAN\n#error Windows ARM64 must remain little endian\n#endif\n')
            expected={'arm64':'ARM64','x64':'AMD64','x86':'I386'}[architecture]
            for name in ('ARM64','AMD64','I386'):
                text+=('#ifndef ' if name==expected else '#ifdef ')+name+'\n#error incorrect architecture alias '+name+'\n#endif\n'
        # This uses actual source headers and macro/type-definition assertions.
        # The host compiler does not establish a Windows ABI or execute ODS.
        return subprocess.run([self.cxx,'-std=c++11','-Wno-unknown-pragmas','-x','c++','-fsyntax-only','-'],
                              input=text,text=True,capture_output=True)

    def test_real_msvc_header_rejects_arm64_then_port_preserves_windows_platform_definitions(self):
        with tempfile.TemporaryDirectory() as folder:
            root=self.source_tree(folder);header=root/'src/include/gen/autoconfig_msvc.h';original=header.read_bytes()
            lock=json.loads((PORT/'source-build.json').read_text())['msvcPlatformHeader']
            self.assertEqual('src/include/gen/autoconfig_msvc.h',lock['path'])
            with tarfile.open(self.archive,'r:bz2') as archive:
                members=[item for item in archive if item.isfile() and item.name.endswith('/'+lock['path'])]
                self.assertEqual(1,len(members))
                archived=archive.extractfile(members[0]).read()
            self.assertEqual(lock['archiveBytes'],len(archived))
            self.assertEqual(lock['archiveSha256'],hashlib.sha256(archived).hexdigest())
            self.assertEqual(lock['beforeBytes'],len(original))
            self.assertEqual(lock['beforeSha256'],hashlib.sha256(original).hexdigest())
            failed=self.compile_msvc_platform(root,'arm64')
            self.assertNotEqual(0,failed.returncode,'Original fixed MSVC header no longer reproduces C1189')
            self.assertIn('unknown target platform',failed.stderr)
            for architecture in ('x64','x86'):
                before=self.compile_msvc_platform(root,architecture)
                self.assertEqual(0,before.returncode,architecture+': '+before.stderr)
            self.apply(root,PORT/'firebird-windows-arm64.patch')
            branch=(b'#elif defined(_M_ARM64) && !defined(_M_ARM64EC)\n#define ARM64\n'
                    b'/* sizeof(void *) */\n#define SIZEOF_VOID_P 8\n'
                    b'/* sizeof(size_t) */\n#define SIZEOF_SIZE_T 8\n'
                    b'/* Firebird alignment, matching the 64-bit Windows layout */\n#define FB_ALIGNMENT 8\n')
            self.assertEqual(original.replace(b'#else\n#error unknown target platform\n',branch+b'#else\n#error unknown target platform\n'),
                             header.read_bytes(),'Only the pure ARM64 fixed-header branch may change')
            self.assertEqual(lock['afterBytes'],header.stat().st_size)
            self.assertEqual(lock['afterSha256'],hashlib.sha256(header.read_bytes()).hexdigest())
            for architecture in ('arm64','x64','x86'):
                result=self.compile_msvc_platform(root,architecture)
                self.assertEqual(0,result.returncode,architecture+': '+result.stderr)
            for architecture in ('unknown','arm64ec'):
                result=self.compile_msvc_platform(root,architecture)
                self.assertNotEqual(0,result.returncode,'Unsupported target was accepted as pure ARM64')
                self.assertIn('unknown target platform',result.stderr)

    def compile_remote_architecture(self, root, architecture, protocol, remote):
        if not self.cxx:
            if self.required:self.fail('Mandatory C++ compiler for the remote architecture source check is missing')
            self.skipTest('A C++ compiler is required for the remote architecture source check')
        macros={'arm64':'#define _M_ARM64 1\n','x64':'#define _M_AMD64 1\n#define _M_X64 1\n',
                'x86':'#define _M_IX86 1\n'}
        start=protocol.index('enum P_ARCH\n')
        enum=protocol[start:protocol.index('};',start)+2]
        common=(root/'src/common/common.h').read_text()
        start=common.index('#ifdef WIN_NT')
        windows=common[start:common.index('#endif /* WIN_NT */',start)+len('#endif /* WIN_NT */')]
        # Compile the complete real remote header and its exact protocol enum.
        # The already-tested fixed MSVC header supplies the Windows/CPU macros.
        # Skip unrelated common declarations; this check claims no Windows ABI.
        text=('#define _MSC_VER 1940\n'+macros[architecture]+
              '#include "'+str(root/'src/include/gen/autoconfig_msvc.h')+'"\n'+
              windows+'\n#define COMMON_COMMON_H\ntypedef unsigned short USHORT;\n'+enum+'\n'+remote+'\n'+
              'static_assert(ARCHITECTURE=='+str({'arm64':44,'x64':40,'x86':29}[architecture])+',"wrong remote architecture");\n')
        return subprocess.run([self.cxx,'-std=c++11','-Wno-unknown-pragmas','-x','c++','-fsyntax-only',
                               '-I'+str(root/'src/remote'),'-'],input=text,text=True,capture_output=True)

    def test_real_remote_architecture_backports_upstream_arm64_identity_without_reusing_old_ids(self):
        with tempfile.TemporaryDirectory() as folder:
            root=self.source_tree(folder)
            paths=('src/remote/remote_def.h','src/remote/protocol.h')
            original={path:(root/path).read_bytes() for path in paths}
            self.apply(root,PORT/'firebird-windows-arm64.patch')
            before=self.compile_remote_architecture(root,'arm64',original[paths[1]].decode(),original[paths[0]].decode())
            self.assertNotEqual(0,before.returncode,'Original remote header no longer reproduces the ARM64 identity gap')
            self.assertIn('ARCHITECTURE',before.stderr)
            for architecture in ('x64','x86'):
                result=self.compile_remote_architecture(root,architecture,original[paths[1]].decode(),original[paths[0]].decode())
                self.assertEqual(0,result.returncode,architecture+': '+result.stderr)
            for architecture in ('arm64','x64','x86'):
                result=self.compile_remote_architecture(root,architecture,(root/paths[1]).read_text(),(root/paths[0]).read_text())
                self.assertEqual(0,result.returncode,architecture+': '+result.stderr)
            lock=json.loads((PORT/'source-build.json').read_text())['remoteArchitecture']
            self.assertEqual('c02ba31824f5cee34cc8966fc44b38e6b395152a',lock['upstreamCommit'])
            self.assertEqual({'name':'arch_winnt_arm64','value':44},lock['identity'])
            branch=(b'#elif defined(WIN_NT) && defined(ARM64)\n'
                    b'const P_ARCH ARCHITECTURE\t= arch_winnt_arm64;\n')
            self.assertEqual(original[paths[0]].replace(b'#elif defined(I386)\n',branch+b'#elif defined(I386)\n'),
                             (root/paths[0]).read_bytes(),'Only the native Windows ARM64 identity branch may change')
            self.assertEqual(original[paths[1]].replace(b'\tarch_max\t\t\t= 44\t',
                             b'\tarch_winnt_arm64\t= 44,\n\tarch_max\t\t\t= 45\t'),
                             (root/paths[1]).read_bytes(),'Existing protocol identities and negotiation must remain unchanged')
            with tarfile.open(self.archive,'r:bz2') as archive:
                archived={path:archive.extractfile(next(item for item in archive.getmembers()
                          if item.isfile() and item.name.endswith('/'+path))).read() for path in paths}
            for item in lock['headers']:
                path=item['path'];effective=(root/path).read_bytes()
                self.assertEqual(archived[path],original[path],'Upstream patches unexpectedly changed the pinned remote header')
                self.assertEqual(item['beforeBytes'],len(original[path]))
                self.assertEqual(item['beforeSha256'],hashlib.sha256(original[path]).hexdigest())
                self.assertEqual(item['afterBytes'],len(effective))
                self.assertEqual(item['afterSha256'],hashlib.sha256(effective).hexdigest())

    def test_real_common_archive_recipe_selects_explicit_native_librarian_and_keeps_other_platforms(self):
        with tempfile.TemporaryDirectory() as folder:
            root=self.source_tree(folder)
            target=root/'builds/posix/Makefile.in';original=target.read_bytes()
            self.apply(root,PORT/'firebird-windows-arm64.patch')
            text=target.read_text();start=text.index('$(COMMON_LIB):')
            recipe=text[start:text.index('#________________________________________________________________',start)]
            tools=Path(folder)/"selected VS's native tools";tools.mkdir()
            librarian=tools/'lib.exe';capture=Path(folder)/'native-arguments.json'
            librarian.write_text('#!'+sys.executable+'\nimport json,os,pathlib,sys\n'+
                'pathlib.Path(os.environ["ARCHIVE_CAPTURE"]).write_text(json.dumps(sys.argv[1:]))\n'+
                'code=int(os.environ.get("ARCHIVE_EXIT","0"))\n'+
                'if code: sys.exit(code)\n'+
                'out=next(arg[5:] for arg in sys.argv[1:] if arg.startswith("/OUT:"))\n'+
                'pathlib.Path(out).write_bytes(b"native command fixture only")\n')
            librarian.chmod(0o700)
            objects=[]
            for name in ('first','second'):
                obj=Path(folder)/(name+'.o')
                result=subprocess.run([self.compiler,'-x','c','-c','-o',str(obj),'-'],
                    input='int '+name+'(void) {return 1;}\n',text=True,capture_output=True)
                self.assertEqual(0,result.returncode,result.stderr);objects.append(obj)
            makefile=Path(folder)/'archive.mk';output=Path(folder)/'common.lib'
            env=dict(os.environ,ARCHIVE_CAPTURE=str(capture))
            def run(platform,cpu,tool=str(librarian),exit_code='0'):
                output.unlink(missing_ok=True);capture.unlink(missing_ok=True)
                makefile.write_text('COMMON_LIB := '+str(output).replace(' ','\\ ')+'\n'+
                    'Common_Objects := '+' '.join(map(str,objects))+'\nRM := rm -f\nSTATICLIB_LINK := ar crus\n'+
                    'PLATFORM := '+platform+'\nCpuType := '+cpu+'\nOPENGEUL_FIREBIRD_LIB := '+tool+'\n'+recipe)
                return subprocess.run(['make','--no-print-directory','-f',str(makefile)],
                    capture_output=True,text=True,env=dict(env,ARCHIVE_EXIT=exit_code))
            result=run('win32','aarch64')
            self.assertEqual(0,result.returncode,result.stdout+result.stderr)
            self.assertTrue(capture.is_file(),'ARM64 recipe used GNU ar instead of the selected native librarian')
            self.assertEqual(['/NOLOGO','/OUT:'+str(output),*map(str,objects)],json.loads(capture.read_text()))
            self.assertEqual(b'native command fixture only',output.read_bytes())
            output=Path(folder)/'archive output/common.lib';output.parent.mkdir()
            result=run('win32','aarch64')
            self.assertEqual(0,result.returncode,result.stdout+result.stderr)
            self.assertEqual(['/NOLOGO','/OUT:'+str(output),*map(str,objects)],json.loads(capture.read_text()))
            result=run('win32','aarch64',exit_code='7')
            self.assertNotEqual(0,result.returncode,'Native librarian failure was hidden')
            self.assertIn('Error 7',result.stderr);self.assertFalse(output.exists())
            result=run('win32','aarch64',tool='')
            self.assertNotEqual(0,result.returncode,'Missing selected librarian fell back to PATH')
            self.assertFalse(capture.exists());self.assertFalse(output.exists())
            # The original GNU recipe is intentionally unchanged for all other
            # CPU/platform selections; use unspaced output as that recipe expects.
            output=Path(folder)/'other-common.lib'
            for platform,cpu in (('win32','x86_64'),('win32','i686'),('LINUX','aarch64')):
                result=run(platform,cpu)
                self.assertEqual(0,result.returncode,result.stdout+result.stderr)
                self.assertFalse(capture.exists(),'Other platform used the ARM64-only librarian')
                symbols=subprocess.run(['nm',str(output)],capture_output=True,text=True)
                self.assertEqual(0,symbols.returncode,symbols.stderr)
                self.assertIn('first',symbols.stdout);self.assertIn('second',symbols.stdout)
            lock=json.loads((PORT/'source-build.json').read_text())['commonArchiveRecipe']
            self.assertEqual('builds/posix/Makefile.in',lock['path'])
            self.assertEqual(lock['beforeSha256'],hashlib.sha256(original).hexdigest())
            self.assertEqual(lock['afterSha256'],hashlib.sha256(target.read_bytes()).hexdigest())
            self.assertIn(b'\t$(STATICLIB_LINK) $@ $^\n',target.read_bytes())

    def test_real_windows_icu_path_survives_both_make_levels_with_both_directories_and_old_x64_behavior(self):
        fixture=ROOT/'suite/tests/fixtures/native-icu-path'
        provenance=json.loads((fixture/'source.json').read_text())
        self.assertEqual('296ba78e7ab0d381b94c3d6342f4ebb2320ee5097ca58781b9b744cab90b9785',provenance['archiveSha256'])
        for item in provenance['members']:
            self.assertEqual(item['fixtureSha256'],hashlib.sha256((fixture/item['fixture']).read_bytes()).hexdigest())
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);project=root/'external/firebird/ExternalProject_firebird.mk';project.parent.mkdir(parents=True)
            firebird_source=self.source_tree(root)
            examples=(firebird_source/'builds/posix/Makefile.in.examples').read_text()
            defaults=(firebird_source/'builds/posix/make.defaults').read_text()
            platform=(firebird_source/'builds/posix/prefix.mingw').read_text()
            # The authenticated Windows recipe puts the actual client DLL in
            # bin. Its examples copy of isql runs outside that application dir.
            self.assertIn('LIB=$(BIN)\n',platform)
            self.assertIn('$(EXAMPLES_DEST)/isql$(EXEC_EXT)',examples)
            self.assertIn('$(LN) $(ISQL) $(EXAMPLES_DEST)/isql$(EXEC_EXT)',examples)
            self.assertIn('ROOT:=$(shell cygpath -m -a ../..)\n',examples)
            example_path='\n'.join(line for line in examples.splitlines()
                                   if line.startswith('PATH :=') or line=='export PATH')
            locations='\n'.join(next(line for line in defaults.splitlines() if line.startswith(key+'='))
                                for key in ('GEN_ROOT','FB_BUILD','BIN'))
            original=(fixture/project.name).read_bytes();project.write_bytes(original)
            hook=project.with_name('UnpackedTarball_firebird.mk');hook.write_bytes((self.lo_patches/hook.name).read_bytes())
            (root/'configure.ac').write_bytes(self.lo_configure.read_bytes())
            bootstrap=root/'bin/unpack-sources';bootstrap.parent.mkdir()
            bootstrap.write_bytes((ROOT/'suite/tests/fixtures/native-source-tar/unpack-sources').read_bytes())
            zstd=root/'external/zstd/UnpackedTarball_zstd.mk';zstd.parent.mkdir()
            zstd.write_bytes((ROOT/'suite/tests/fixtures/native-zstd-unpack/UnpackedTarball_zstd.mk').read_bytes())
            self.mdds_recipe(root)
            evidence=root/'evidence';evidence.mkdir()
            bash=shutil.which('bash')
            self.assertTrue(bash,'Actual Bash is required for the nested make source replay')
            observer=root/'observe.py';observer.write_text('import json,os;print(json.dumps(os.environ["PATH"].split(":")))\n')
            inner=root/'inner.mk';inner.write_text('SHELL := '+bash+'\n'+
                'ROOT := C:/source/workdir/UnpackedTarball/firebird\nTARGET := Release\n'+locations+'\n'+
                example_path+'\nall:\n\t$(LIBO_TUNNEL_LIBRARY_PATH) '+shlex.quote(sys.executable)+' '+shlex.quote(str(observer))+'\n')
            def replay(raw,cpu):
                assignment=next(line.strip().removesuffix(' \\') for line in raw.decode().splitlines()
                                if line.strip().startswith('LIBO_TUNNEL_LIBRARY_PATH='))
                variables=('SHELL := '+bash+'\nOS := WNT\nCPUNAME := '+cpu+'\n'+
                    'SRCDIR := C:/source\nSRCDIR_CYG := /cygdrive/c/source\n'+
                    'BUILDDIR := C:/source\nBUILDDIR_CYG := /cygdrive/c/source\n'+
                    'INSTDIR := C:/source/instdir\nINSTDIR_CYG := /cygdrive/c/source/instdir\n'+
                    'WORKDIR := C:/source/workdir\nWORKDIR_CYG := /cygdrive/c/source/workdir\n'+
                    'TARFILE_LOCATION := C:/downloads\nTARFILE_LOCATION_CYG := /cygdrive/c/downloads\n'+
                    'INSTDIR_FOR_BUILD := $(INSTDIR)\nLIBO_URE_LIB_FOLDER := program\nLIBO_BIN_FOLDER := program\n'+
                    'gb_UnpackedTarball_workdir := $(WORKDIR)/UnpackedTarball\n'+
                    'firebird_BUILDDIR := $(gb_UnpackedTarball_workdir)/firebird/gen/Release/firebird\n')
                outer=root/'outer.mk';outer.write_text(variables+(fixture/'cyg-path.mk').read_text()+'\n'+
                    (fixture/'windows-loader-path.mk').read_text()+'\nall:\n\t$(MAKE) --no-print-directory -f '+
                    shlex.quote(str(inner))+' '+assignment+'\n')
                result=subprocess.run(['make','--no-print-directory','-f',str(outer),'SHELL='+bash],
                    capture_output=True,text=True,env=dict(os.environ,PATH='/usr/bin:/bin'),timeout=10)
                self.assertEqual(0,result.returncode,result.stdout+result.stderr)
                return json.loads(result.stdout.splitlines()[-1])
            icu='/cygdrive/c/source/workdir/UnpackedTarball/icu/source/lib'
            firebird='/cygdrive/c/source/workdir/UnpackedTarball/firebird/gen/Release/firebird/bin'
            before=replay(original,'AARCH64')
            self.assertNotIn(icu,before,'Pinned original no longer reproduces concatenated PATH assignments')
            self.assertTrue(any('icu/source/libPATH=' in entry for entry in before))
            # Reproduce the intermediate ICU fix used in Native15: the mixed
            # C:/ examples PATH does not supply a canonical Cygwin bin entry,
            # and appending Firebird/lib misses prefix.mingw's LIB=$(BIN).
            old=(b'$(call gb_Helper_extend_ld_path,$(gb_UnpackedTarball_workdir)/icu/source/lib)'
                 b'$(call gb_Helper_extend_ld_path,$(firebird_BUILDDIR)/lib)')
            prior=original.replace(old,b'$(if $(filter WNT_AARCH64,$(OS)_$(CPUNAME)),'+
                b'$(call gb_Helper_extend_ld_path,$(gb_UnpackedTarball_workdir)/icu/source/lib:$(firebird_BUILDDIR)/lib),'+old+b')')
            self.assertEqual('94d52186250e98ced4237146faca6d0448c9562d74ce1c3cb3254bd9d351c5b2',hashlib.sha256(prior).hexdigest())
            prior_entries=replay(prior,'AARCH64')
            self.assertIn(icu,prior_entries)
            self.assertNotIn(firebird,prior_entries)
            mixed='/source/workdir/UnpackedTarball/firebird/gen/Release/firebird/bin'
            self.assertIn('C',prior_entries);self.assertIn(mixed,prior_entries)
            receipt=module().install(root,evidence)
            effective=project.read_bytes();after=replay(effective,'AARCH64')
            self.assertIn(icu,after,'Owned ARM64 child lost the complete authenticated ICU library directory')
            self.assertIn(firebird,after,'ARM64 helper misses the actual Windows client DLL directory')
            self.assertEqual(['/cygdrive/c/source/instdir/program','/cygdrive/c/source/instdir/program',
                              './','C',mixed,'/usr/bin','/bin',icu,firebird],after,'Existing helper base paths and directory order changed')
            self.assertFalse(any('libPATH=' in entry for entry in after))
            self.assertEqual(replay(original,'X86_64'),replay(effective,'X86_64'),'x64 helper behavior changed')
            lock=json.loads((PORT/'source-build.json').read_text())['icuBuildPath']
            self.assertEqual(lock['sha256'],hashlib.sha256(original).hexdigest())
            self.assertEqual(lock['afterSha256'],hashlib.sha256(effective).hexdigest())
            self.assertEqual(original,(evidence/'original-ExternalProject_firebird.mk').read_bytes())
            self.assertEqual(effective,(evidence/'effective-ExternalProject_firebird.mk').read_bytes())
            self.assertEqual(lock['afterSha256'],receipt['icuBuildPath']['afterSha256'])

    def test_real_zstd_unpack_environment_changes_only_its_arm64_archive_target(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);hook=root/'external/firebird/UnpackedTarball_firebird.mk';hook.parent.mkdir(parents=True)
            hook.write_bytes((self.lo_patches/hook.name).read_bytes())
            hook.with_name('ExternalProject_firebird.mk').write_bytes((ROOT/'suite/tests/fixtures/native-icu-path/ExternalProject_firebird.mk').read_bytes())
            (root/'configure.ac').write_bytes(self.lo_configure.read_bytes())
            bootstrap=root/'bin/unpack-sources';bootstrap.parent.mkdir()
            bootstrap.write_bytes((ROOT/'suite/tests/fixtures/native-source-tar/unpack-sources').read_bytes())
            recipe=root/'external/zstd/UnpackedTarball_zstd.mk';recipe.parent.mkdir()
            original=(ROOT/'suite/tests/fixtures/native-zstd-unpack/UnpackedTarball_zstd.mk').read_bytes();recipe.write_bytes(original)
            self.mdds_recipe(root)
            self.assertEqual('3d7f5ddeccdbebdd72cf34e6122e0c1d33093374d27b7779d6a6f81f76d55909',hashlib.sha256(original).hexdigest())
            observer=root/'observe.py';observer.write_text('import json,os,sys;print(json.dumps([sys.argv[1],os.environ["CYGWIN"]]))\n')
            def replay(raw,cpu,os_name='WNT'):
                recipe.write_bytes(raw)
                makefile=root/'scope.mk';makefile.write_text(
                    'all: unpacked/zstd-1.5.7.tar.gz unpacked/other.tar.gz outer\n'+
                    'OS := '+os_name+'\nCPUNAME := '+cpu+'\nZSTD_TARBALL := zstd-1.5.7.tar.gz\n'+
                    'gb_UnpackedTarget_get_target = unpacked/$(1)\ninclude '+str(recipe)+'\n'+
                    'unpacked/zstd-1.5.7.tar.gz unpacked/other.tar.gz outer:\n\t@'+
                    shlex.quote(sys.executable)+' '+shlex.quote(str(observer))+' $@\n')
                result=subprocess.run(['make','--no-print-directory','-f',str(makefile)],cwd=root,
                    env=dict(os.environ,CYGWIN='winsymlinks:nativestrict'),capture_output=True,text=True,timeout=10)
                self.assertEqual(0,result.returncode,result.stdout+result.stderr)
                return dict(json.loads(line) for line in result.stdout.splitlines())
            strict={name:'winsymlinks:nativestrict' for name in ('unpacked/zstd-1.5.7.tar.gz','unpacked/other.tar.gz','outer')}
            self.assertEqual(strict,replay(original,'AARCH64'))
            evidence=root/'evidence';evidence.mkdir();receipt=module().install(root,evidence)
            effective=recipe.read_bytes()
            self.assertEqual(dict(strict,**{'unpacked/zstd-1.5.7.tar.gz':'winsymlinks:sys'}),replay(effective,'AARCH64'))
            self.assertEqual(strict,replay(effective,'X86_64'))
            self.assertEqual(strict,replay(effective,'AARCH64','LINUX'))
            self.assertTrue(effective.startswith(original),'Pristine upstream zstd workaround bytes changed')
            lock=json.loads((PORT/'source-build.json').read_text())['zstdSourceLinks']
            self.assertEqual(lock['afterSha256'],hashlib.sha256(effective).hexdigest())
            self.assertEqual(original,(evidence/'original-UnpackedTarball_zstd.mk').read_bytes())
            self.assertEqual(effective,(evidence/'effective-UnpackedTarball_zstd.mk').read_bytes())
            self.assertEqual(lock['afterSha256'],receipt['zstdSourceLinks']['afterSha256'])

    def test_explicit_enable_flag_is_not_overwritten_by_arm64_defaults(self):
        autoconf = shutil.which('autoconf')
        if not autoconf:
            if self.required:
                self.fail('Mandatory GNU Autoconf is missing')
            self.skipTest('GNU Autoconf is required for the actual option-parsing probe')
        original = self.lo_configure.read_text()
        lock = json.loads((PORT / 'source-build.json').read_text())
        self.assertEqual(hashlib.sha256(original.encode()).hexdigest(), lock['configureSource']['sha256'])
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'configure.ac').write_text(original)
            self.apply(root, PORT / 'libreoffice-enable-arm64-firebird.patch')
            changed = (root / 'configure.ac').read_text()
            defaults = re.compile(r'    if test "\$host_cpu" = "aarch64"; then\n.*?    fi', re.S)
            for label, body, expected in [('before', original, 'no'), ('after', changed, 'yes')]:
                probe = root / label
                probe.mkdir()
                # The exact upstream Windows ARM defaults and AC_ARG_ENABLE
                # semantics reproduce startup argument parsing without a Windows SDK.
                (probe / 'configure.ac').write_text(
                    'AC_INIT([OpenGeulFirebirdFlagProbe], [1])\nhost_cpu=aarch64\n'
                    + defaults.search(body).group(0)
                    + '\nAC_ARG_ENABLE([firebird-sdbc], [], [], '
                      '[test "${enable_firebird_sdbc+set}" = set || enable_firebird_sdbc=yes])\n'
                      'AC_MSG_NOTICE([FIREBIRD=$enable_firebird_sdbc])\nAC_OUTPUT\n')
                subprocess.run([autoconf], cwd=probe, capture_output=True, check=True)
                result = subprocess.run(['sh', './configure', '--enable-firebird-sdbc'],
                                        cwd=probe, capture_output=True, text=True, check=True)
                self.assertIn('FIREBIRD=' + expected, result.stdout)

    def test_changed_configure_is_rejected_before_source_mutation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            hook = root / 'external/firebird/UnpackedTarball_firebird.mk'
            hook.parent.mkdir(parents=True)
            original = (self.lo_patches / hook.name).read_bytes()
            hook.write_bytes(original)
            configure = root / 'configure.ac'
            configure.write_bytes(self.lo_configure.read_bytes() + b'\nchanged\n')
            with self.assertRaisesRegex(ValueError, 'configure.ac SHA256'):
                module().install(root)
            self.assertEqual(hook.read_bytes(), original)
            self.assertFalse((hook.parent / 'firebird-windows-arm64.patch').exists())

    def test_lo_hook_cli_serializes_original_source_hash_and_all_consumer_evidence(self):
        lock = json.loads((PORT / 'source-build.json').read_text())
        with tempfile.TemporaryDirectory(prefix='source hook cli ') as folder:
            root = Path(folder)
            originals = {
                lock['sourceHook']['path']: (self.lo_patches / 'UnpackedTarball_firebird.mk').read_bytes(),
                'external/firebird/ExternalProject_firebird.mk': (ROOT / 'suite/tests/fixtures/native-icu-path/ExternalProject_firebird.mk').read_bytes(),
                'configure.ac': self.lo_configure.read_bytes(),
                'bin/unpack-sources': (ROOT / 'suite/tests/fixtures/native-source-tar/unpack-sources').read_bytes(),
                'external/zstd/UnpackedTarball_zstd.mk': (ROOT / 'suite/tests/fixtures/native-zstd-unpack/UnpackedTarball_zstd.mk').read_bytes(),
            }
            for relative, raw in originals.items():
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
            self.mdds_recipe(root)
            evidence = root / 'evidence'; evidence.mkdir()
            self.cli_command = [sys.executable, str(PORT / 'enable_firebird_arm64.py'),
                                '--libreoffice-source', str(root), '--evidence-directory', str(evidence)]
            self.cli_result = subprocess.run(self.cli_command, cwd=ROOT, capture_output=True, text=True, timeout=30)
            self.assertEqual(0, self.cli_result.returncode, self.cli_result.stdout + self.cli_result.stderr)
            receipt = json.loads(self.cli_result.stdout)
            self.assertEqual('', self.cli_result.stderr)
            self.assertIsInstance(receipt['beforeSha256'], str)
            self.assertEqual(lock['sourceHook']['sha256'], receipt['beforeSha256'])
            self.assertEqual(lock['sourceHook']['path'], receipt['sourceHook'])
            self.assertEqual('source-hook-installed-native-build-pending', receipt['status'])
            self.assertFalse(receipt['nativeBuildVerified'])
            self.assertFalse(receipt['basePersistenceVerified'])
            recipes = receipt['atlConsumerNativePaths']['recipes']
            self.assertEqual([pin['path'] for pin in lock['atlConsumerNativePaths']['recipes']],
                             [item['path'] for item in recipes])
            self.assertEqual(5, len(recipes))
            for pin, item in zip(lock['atlConsumerNativePaths']['recipes'], recipes):
                self.assertEqual(pin['sha256'], item['beforeSha256'])
                self.assertEqual(pin['afterSha256'], item['afterSha256'])
                for kind, size_key, sha_key in (('original', 'size', 'sha256'),
                                               ('effective', 'afterSize', 'afterSha256')):
                    retained = evidence / (kind + '-' + Path(pin['path']).name)
                    self.assertEqual(retained, Path(item['evidence'][kind]))
                    raw = retained.read_bytes()
                    self.assertEqual(pin[size_key], len(raw))
                    self.assertEqual(pin[sha_key], hashlib.sha256(raw).hexdigest())
                    if kind == 'effective': self.assertEqual(raw, (root / pin['path']).read_bytes())

    def test_lo_hook_installation_is_pinned_and_arm64_only(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root / 'external/firebird/UnpackedTarball_firebird.mk'
            target.parent.mkdir(parents=True)
            original = (self.lo_patches / target.name).read_bytes()
            target.write_bytes(original)
            project=target.with_name('ExternalProject_firebird.mk')
            project_original=(ROOT/'suite/tests/fixtures/native-icu-path/ExternalProject_firebird.mk').read_bytes()
            project.write_bytes(project_original)
            configure = root / 'configure.ac'
            configure.write_bytes(self.lo_configure.read_bytes())
            bootstrap = root / 'bin/unpack-sources'
            bootstrap.parent.mkdir()
            pristine = (ROOT / 'suite/tests/fixtures/native-source-tar/unpack-sources').read_bytes()
            bootstrap.write_bytes(pristine)
            zstd=root/'external/zstd/UnpackedTarball_zstd.mk';zstd.parent.mkdir()
            zstd_original=(ROOT/'suite/tests/fixtures/native-zstd-unpack/UnpackedTarball_zstd.mk').read_bytes();zstd.write_bytes(zstd_original)
            mdds = self.mdds_recipe(root)
            mdds_original = mdds.read_bytes()
            python = root / 'external/python3/ExternalProject_python3.mk'
            python_original = python.read_bytes()
            atl = root / 'extensions/Library_so_activex.mk'
            atl_original = atl.read_bytes()
            harfbuzz = root / 'external/harfbuzz/ExternalProject_harfbuzz.mk'
            harfbuzz_original = harfbuzz.read_bytes()
            python_targets = python.with_name('opengeul-native-arm64-tools.targets')
            upstream = mdds.parent / 'gcc-12-silence-use-after-free.patch.1'
            upstream_original = upstream.read_bytes()
            evidence = root / 'evidence'
            evidence.mkdir()
            consumer_paths = ('embedserv/Library_emser.mk', 'extensions/Library_oleautobridge.mk',
                              'winaccessibility/Library_uacccom.mk', 'winaccessibility/Library_winaccessibility.mk',
                              'winaccessibility/WinResTarget_uacccom.mk')
            consumer_originals = {relative: (root / relative).read_bytes() for relative in consumer_paths}
            self.assertIn('atlConsumerNativePaths', json.loads((PORT / 'source-build.json').read_text()),
                          'Five authentic ATL consumers require a pinned install plan')
            def tree_state():
                return {str(path.relative_to(root)): ('link', os.readlink(path)) if path.is_symlink()
                        else ('directory',) if path.is_dir() else ('file', path.read_bytes())
                        for path in root.rglob('*')}
            new_invalid = tuple(('atl-consumer', relative, failure) for relative in consumer_paths
                                for failure in ('missing', 'changed', 'linked-recipe', 'linked-parent',
                                                'original-evidence', 'effective-evidence'))
            for invalid in ('changed-helper', 'linked-helper', 'evidence-collision', 'changed-build-recipe', 'linked-build-recipe', 'build-evidence-collision', 'changed-zstd-recipe', 'linked-zstd-recipe', 'zstd-evidence-collision', 'changed-mdds-recipe', 'linked-mdds-recipe', 'mdds-evidence-collision', 'mdds-patch-collision', 'changed-mdds-upstream-patch', 'changed-mdds-patch', 'changed-python-recipe', 'linked-python-recipe', 'python-targets-collision', 'python-evidence-collision', 'python-payload-evidence-collision', 'forged-python-targets', 'missing-python-lock', 'changed-atl-recipe', 'linked-atl-recipe', 'atl-original-evidence-collision', 'atl-effective-evidence-collision', 'missing-atl-lock', 'changed-harfbuzz-recipe', 'linked-harfbuzz-recipe', 'harfbuzz-original-evidence-collision', 'harfbuzz-effective-evidence-collision', 'missing-harfbuzz-lock', 'missing-atl-consumers-lock') + new_invalid:
                with self.subTest(invalid=invalid):
                    consumer = None
                    saved_parent = None
                    if isinstance(invalid, tuple):
                        _, relative, failure = invalid
                        consumer = root / relative
                        if failure == 'missing':
                            consumer.unlink()
                        elif failure == 'changed':
                            consumer.write_bytes(consumer_originals[relative] + b'changed')
                        elif failure == 'linked-recipe':
                            saved_consumer = root / 'saved-atl-consumer'
                            saved_consumer.write_bytes(consumer_originals[relative])
                            consumer.unlink(); consumer.symlink_to(saved_consumer)
                        elif failure == 'linked-parent':
                            saved_parent = root / 'saved-atl-consumer-parent'
                            consumer.parent.rename(saved_parent)
                            consumer.parent.symlink_to(saved_parent, target_is_directory=True)
                        else:
                            kind = failure.split('-', 1)[0]
                            (evidence / (kind + '-' + consumer.name)).write_bytes(b'prior consumer evidence')
                    elif invalid == 'changed-harfbuzz-recipe':
                        harfbuzz.write_bytes(harfbuzz_original+b'changed')
                    elif invalid == 'linked-harfbuzz-recipe':
                        saved_harfbuzz=root/'saved-harfbuzz'; saved_harfbuzz.write_bytes(harfbuzz_original)
                        harfbuzz.unlink(); harfbuzz.symlink_to(saved_harfbuzz)
                    elif invalid == 'harfbuzz-original-evidence-collision':
                        (evidence/'original-ExternalProject_harfbuzz.mk').write_bytes(b'prior evidence')
                    elif invalid == 'harfbuzz-effective-evidence-collision':
                        (evidence/'effective-ExternalProject_harfbuzz.mk').write_bytes(b'prior evidence')
                    elif invalid == 'changed-atl-recipe':
                        atl.write_bytes(atl_original+b'changed')
                    elif invalid == 'linked-atl-recipe':
                        saved_atl = root/'saved-atl'; saved_atl.write_bytes(atl_original)
                        atl.unlink(); atl.symlink_to(saved_atl)
                    elif invalid == 'atl-original-evidence-collision':
                        (evidence/'original-Library_so_activex.mk').write_bytes(b'prior evidence')
                    elif invalid == 'atl-effective-evidence-collision':
                        (evidence/'effective-Library_so_activex.mk').write_bytes(b'prior evidence')
                    elif invalid == 'changed-helper':
                        bootstrap.write_bytes(pristine + b'\nchanged\n')
                    elif invalid == 'linked-helper':
                        saved = root / 'original-helper'
                        saved.write_bytes(pristine)
                        bootstrap.unlink()
                        bootstrap.symlink_to(saved)
                    elif invalid == 'evidence-collision':
                        (evidence / 'effective-unpack-sources').write_bytes(b'prior evidence')
                    elif invalid == 'changed-build-recipe':
                        project.write_bytes(project_original+b'\nchanged\n')
                    elif invalid == 'linked-build-recipe':
                        saved_project=root/'original-build-recipe';saved_project.write_bytes(project_original)
                        project.unlink();project.symlink_to(saved_project)
                    elif invalid == 'build-evidence-collision':
                        (evidence/'effective-ExternalProject_firebird.mk').write_bytes(b'prior evidence')
                    elif invalid == 'changed-zstd-recipe':
                        zstd.write_bytes(zstd_original+b'\nchanged\n')
                    elif invalid == 'linked-zstd-recipe':
                        saved_zstd=root/'original-zstd-recipe';saved_zstd.write_bytes(zstd_original)
                        zstd.unlink();zstd.symlink_to(saved_zstd)
                    elif invalid == 'zstd-evidence-collision':
                        (evidence/'effective-UnpackedTarball_zstd.mk').write_bytes(b'prior evidence')
                    elif invalid == 'changed-mdds-recipe':
                        mdds.write_bytes(mdds_original+b'changed')
                    elif invalid == 'linked-mdds-recipe':
                        saved_mdds=root/'original-mdds';saved_mdds.write_bytes(mdds_original)
                        mdds.unlink();mdds.symlink_to(saved_mdds)
                    elif invalid == 'mdds-evidence-collision':
                        (evidence/'effective-UnpackedTarball_mdds.mk').write_bytes(b'prior evidence')
                    elif invalid == 'mdds-patch-collision':
                        (mdds.parent/'opengeul-arm64-equality.patch.1').write_bytes(b'prior patch')
                    elif invalid == 'changed-mdds-upstream-patch':
                        upstream.write_bytes(upstream_original+b'changed')
                    elif invalid == 'changed-python-recipe':
                        python.write_bytes(python_original+b'changed')
                    elif invalid == 'linked-python-recipe':
                        saved_python = root/'saved-python'; saved_python.write_bytes(python_original)
                        python.unlink(); python.symlink_to(saved_python)
                    elif invalid == 'python-targets-collision':
                        python_targets.write_bytes(b'prior targets')
                    elif invalid == 'python-evidence-collision':
                        (evidence/'effective-ExternalProject_python3.mk').write_bytes(b'prior evidence')
                    elif invalid == 'python-payload-evidence-collision':
                        (evidence/'effective-opengeul-native-arm64-tools.targets').write_bytes(b'prior evidence')
                    expected_bootstrap = bootstrap.read_bytes()
                    expected_project=project.read_bytes()
                    expected_zstd=zstd.read_bytes()
                    expected_mdds=mdds.read_bytes()
                    expected_python=python.read_bytes()
                    expected_atl=atl.read_bytes()
                    expected_harfbuzz=harfbuzz.read_bytes()
                    installer = module()
                    if invalid == 'changed-mdds-patch':
                        bundle = root/'changed-port'; bundle.mkdir(exist_ok=True)
                        for name in ('source-build.json', 'firebird-windows-arm64.patch', 'libreoffice-enable-arm64-firebird.patch', 'opengeul-arm64-equality.patch.1'):
                            shutil.copyfile(PORT/name,bundle/name)
                        bad_patch = bundle/'opengeul-arm64-equality.patch.1'
                        bad_patch.write_bytes(bad_patch.read_bytes()+b'changed')
                        installer.HERE = bundle
                    elif invalid in ('forged-python-targets', 'missing-python-lock', 'missing-atl-lock', 'missing-harfbuzz-lock', 'missing-atl-consumers-lock'):
                        bundle = root/invalid; bundle.mkdir()
                        for name in ('source-build.json', 'firebird-windows-arm64.patch', 'libreoffice-enable-arm64-firebird.patch', 'opengeul-arm64-equality.patch.1', 'opengeul-native-arm64-tools.targets'):
                            shutil.copyfile(PORT/name,bundle/name)
                        if invalid == 'forged-python-targets':
                            (bundle/'opengeul-native-arm64-tools.targets').write_bytes(b'forged targets')
                        else:
                            manifest = json.loads((bundle/'source-build.json').read_text())
                            if invalid == 'missing-atl-consumers-lock':
                                self.assertIn('atlConsumerNativePaths', manifest, 'Five authentic ATL consumers require a pinned install plan')
                            del manifest[{'missing-python-lock':'pythonNativeHost', 'missing-atl-lock':'atlNativePaths',
                                          'missing-harfbuzz-lock':'harfbuzzNativeMesonPaths',
                                          'missing-atl-consumers-lock':'atlConsumerNativePaths'}[invalid]]
                            (bundle/'source-build.json').write_text(json.dumps(manifest))
                        installer.HERE = bundle
                    expected_tree = tree_state() if isinstance(invalid, tuple) else None
                    if invalid in ('missing-python-lock', 'missing-atl-lock', 'missing-harfbuzz-lock', 'missing-atl-consumers-lock'):
                        with self.assertRaises(KeyError):
                            installer.install(root, evidence)
                    elif expected_tree is not None:
                        with self.assertRaisesRegex((ValueError, FileNotFoundError), 'SHA256|regular file|regular.*director|exists|No such file'):
                            installer.install(root, evidence)
                    else:
                        with self.assertRaisesRegex(ValueError, 'SHA256|regular file|exists'):
                            installer.install(root, evidence)
                    if expected_tree is not None:
                        self.assertEqual(expected_tree, tree_state(), 'Consumer validation must precede every source/evidence write')
                    self.assertEqual(original, target.read_bytes())
                    self.assertEqual(self.lo_configure.read_bytes(), configure.read_bytes())
                    self.assertEqual(expected_bootstrap, bootstrap.read_bytes())
                    self.assertEqual(expected_project,project.read_bytes())
                    self.assertEqual(expected_zstd,zstd.read_bytes())
                    self.assertEqual(expected_mdds,mdds.read_bytes())
                    self.assertEqual(expected_python,python.read_bytes())
                    self.assertEqual(expected_atl,atl.read_bytes())
                    self.assertEqual(expected_harfbuzz,harfbuzz.read_bytes())
                    self.assertFalse((evidence/'original-ExternalProject_python3.mk').exists())
                    self.assertFalse((evidence/'original-UnpackedTarball_mdds.mk').exists())
                    self.assertFalse((target.parent / 'firebird-windows-arm64.patch').exists())
                    self.assertFalse((evidence / 'original-unpack-sources').exists())
                    self.assertFalse((evidence/'original-ExternalProject_firebird.mk').exists())
                    self.assertFalse((evidence/'original-UnpackedTarball_zstd.mk').exists())
                    if consumer is not None:
                        if saved_parent is not None:
                            consumer.parent.unlink()
                            saved_parent.rename(consumer.parent)
                        if consumer.is_symlink(): consumer.unlink()
                        consumer.write_bytes(consumer_originals[relative])
                        (evidence / ('original-' + consumer.name)).unlink(missing_ok=True)
                        (evidence / ('effective-' + consumer.name)).unlink(missing_ok=True)
                    if bootstrap.is_symlink():
                        bootstrap.unlink()
                    bootstrap.write_bytes(pristine)
                    (evidence / 'effective-unpack-sources').unlink(missing_ok=True)
                    if project.is_symlink():project.unlink()
                    project.write_bytes(project_original)
                    (evidence/'effective-ExternalProject_firebird.mk').unlink(missing_ok=True)
                    if zstd.is_symlink():zstd.unlink()
                    zstd.write_bytes(zstd_original)
                    (evidence/'effective-UnpackedTarball_zstd.mk').unlink(missing_ok=True)
                    if mdds.is_symlink():mdds.unlink()
                    mdds.write_bytes(mdds_original)
                    upstream.write_bytes(upstream_original)
                    (mdds.parent/'opengeul-arm64-equality.patch.1').unlink(missing_ok=True)
                    (evidence/'effective-UnpackedTarball_mdds.mk').unlink(missing_ok=True)
                    if atl.is_symlink(): atl.unlink()
                    atl.write_bytes(atl_original)
                    (evidence/'original-Library_so_activex.mk').unlink(missing_ok=True)
                    (evidence/'effective-Library_so_activex.mk').unlink(missing_ok=True)
                    if harfbuzz.is_symlink(): harfbuzz.unlink()
                    harfbuzz.write_bytes(harfbuzz_original)
                    (evidence/'original-ExternalProject_harfbuzz.mk').unlink(missing_ok=True)
                    (evidence/'effective-ExternalProject_harfbuzz.mk').unlink(missing_ok=True)
                    if python.is_symlink(): python.unlink()
                    python.write_bytes(python_original)
                    python_targets.unlink(missing_ok=True)
                    (evidence/'effective-ExternalProject_python3.mk').unlink(missing_ok=True)
                    (evidence/'effective-opengeul-native-arm64-tools.targets').unlink(missing_ok=True)
            receipt = module().install(root, evidence)
            consumer_receipt = receipt['atlConsumerNativePaths']
            self.assertEqual(consumer_paths, tuple(item['path'] for item in consumer_receipt['recipes']))
            for item in consumer_receipt['recipes']:
                relative = item['path']
                consumer = root / relative
                self.assertEqual(consumer_originals[relative], Path(item['evidence']['original']).read_bytes())
                self.assertEqual(consumer.read_bytes(), Path(item['evidence']['effective']).read_bytes())
                self.assertEqual(hashlib.sha256(consumer_originals[relative]).hexdigest(), item['beforeSha256'])
                self.assertEqual(hashlib.sha256(consumer.read_bytes()).hexdigest(), item['afterSha256'])
            self.assertEqual(harfbuzz_original,(evidence/'original-ExternalProject_harfbuzz.mk').read_bytes())
            self.assertEqual(harfbuzz.read_bytes(),(evidence/'effective-ExternalProject_harfbuzz.mk').read_bytes())
            self.assertEqual(hashlib.sha256(harfbuzz_original).hexdigest(),receipt['harfbuzzNativeMesonPaths']['beforeSha256'])
            self.assertEqual(hashlib.sha256(harfbuzz.read_bytes()).hexdigest(),receipt['harfbuzzNativeMesonPaths']['afterSha256'])
            self.assertEqual({'original','effective'},set(receipt['harfbuzzNativeMesonPaths']['evidence']))
            self.assertEqual(atl_original,(evidence/'original-Library_so_activex.mk').read_bytes())
            self.assertEqual(atl.read_bytes(),(evidence/'effective-Library_so_activex.mk').read_bytes())
            self.assertEqual(hashlib.sha256(atl_original).hexdigest(),receipt['atlNativePaths']['beforeSha256'])
            self.assertEqual(hashlib.sha256(atl.read_bytes()).hexdigest(),receipt['atlNativePaths']['afterSha256'])
            self.assertEqual({'original','effective'},set(receipt['atlNativePaths']['evidence']))
            self.assertFalse(receipt['nativeBuildVerified'])
            self.assertEqual(python_original,(evidence/'original-ExternalProject_python3.mk').read_bytes())
            self.assertEqual(python.read_bytes(),(evidence/'effective-ExternalProject_python3.mk').read_bytes())
            self.assertEqual(python_targets.read_bytes(),(evidence/'effective-opengeul-native-arm64-tools.targets').read_bytes())
            self.assertEqual(hashlib.sha256(python_targets.read_bytes()).hexdigest(),receipt['pythonNativeHost']['targetsSha256'])
            changed = target.read_text()
            self.assertTrue(changed.startswith(original.decode()))
            self.assertIn('ifeq ($(OS)_$(CPUNAME),WNT_AARCH64)', changed)
            self.assertGreater(changed.index('external/firebird/firebird-windows-arm64.patch'),
                               changed.index('external/firebird/firebird-cygwin-msvc-warnings.patch'))
            self.assertEqual(receipt['portPatchSha256'],
                             hashlib.sha256((PORT/'firebird-windows-arm64.patch').read_bytes()).hexdigest())
            self.assertFalse('        enable_coinmp=no\n        enable_firebird_sdbc=no\n' in configure.read_text(), 'ARM64 Firebird is still forcibly disabled')
            self.assertEqual(receipt['status'], 'source-hook-installed-native-build-pending')
            self.assertEqual(pristine, (evidence / 'original-unpack-sources').read_bytes())
            self.assertEqual(bootstrap.read_bytes(), (evidence / 'effective-unpack-sources').read_bytes())
            self.assertEqual(hashlib.sha256(bootstrap.read_bytes()).hexdigest(),
                             receipt['moduleBootstrap']['afterSha256'])
            self.assertEqual((target.parent / 'firebird-windows-arm64.patch').read_bytes(),
                             (PORT / 'firebird-windows-arm64.patch').read_bytes())
            with self.assertRaisesRegex(ValueError, 'SHA256|already exists'):
                module().install(root)


if __name__ == '__main__':
    unittest.main()
