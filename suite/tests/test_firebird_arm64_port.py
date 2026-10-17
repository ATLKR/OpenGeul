"""Port evidence uses authenticated upstream source, not synthetic PE files.

Set OPENGEUL_FIREBIRD_SOURCE_ARCHIVE to the pinned Firebird source tar.bz2 and
OPENGEUL_LIBREOFFICE_FIREBIRD_PATCHES to the pinned LO external/firebird folder
for the actual patch-application/compiler checks. No test downloads inputs.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
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
        cls.compiler = shutil.which('cc') or shutil.which('gcc')
        if not cls.compiler or not shutil.which('patch'):
            if cls.required:
                raise AssertionError('Mandatory C compiler/preprocessor or GNU patch is missing')
            raise unittest.SkipTest('A C preprocessor/compiler and GNU patch are required')

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

    def test_lo_hook_installation_is_pinned_and_arm64_only(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root / 'external/firebird/UnpackedTarball_firebird.mk'
            target.parent.mkdir(parents=True)
            original = (self.lo_patches / target.name).read_bytes()
            target.write_bytes(original)
            configure = root / 'configure.ac'
            configure.write_bytes(self.lo_configure.read_bytes())
            receipt = module().install(root)
            changed = target.read_text()
            self.assertTrue(changed.startswith(original.decode()))
            self.assertIn('ifeq ($(OS)_$(CPUNAME),WNT_AARCH64)', changed)
            self.assertFalse('        enable_coinmp=no\n        enable_firebird_sdbc=no\n' in configure.read_text(), 'ARM64 Firebird is still forcibly disabled')
            self.assertEqual(receipt['status'], 'source-hook-installed-native-build-pending')
            self.assertEqual((target.parent / 'firebird-windows-arm64.patch').read_bytes(),
                             (PORT / 'firebird-windows-arm64.patch').read_bytes())
            with self.assertRaisesRegex(ValueError, 'SHA256|already exists'):
                module().install(root)


if __name__ == '__main__':
    unittest.main()
