"""ARM9dea recipe flags, with a retained historical portable PCH-rule oracle.

The bf6 rule fixture is not evidence of a 9dea Windows gbuild execution.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


BACKEND = Path(__file__).resolve().parents[1] / 'engine-build/writer-server-observer-diagnostic'
UPSTREAM = BACKEND / 'tests/upstream'
RULE = UPSTREAM / 'solenv/gbuild/PrecompiledHeaders.mk'
RULE_SHA256 = '9441712b408fd544fb93fbd7045a3153c838535006b789df3bfbb4c58c702e91'
DEFINE = '-DOPENGEUL_WRITER_SERVER_OBSERVER_DIAGNOSTIC'
RECIPE = 'winaccessibility/Library_winaccessibility.mk'


def install_source(root, target):
    source = root / 'source'
    shutil.copytree(UPSTREAM, source)
    (source / 'include').mkdir()
    spec = importlib.util.spec_from_file_location('writer_pch_install', BACKEND / 'install.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.install(source, target)
    return source


def library_definitions(text, library):
    return [value.strip() for value in re.findall(
        r'gb_Library_add_defs,' + re.escape(library) + r',([^)]*)', text)]


class CommonPchContract(unittest.TestCase):
    def test_rule_is_the_unmodified_pinned_upstream_checker(self):
        self.assertEqual(hashlib.sha256(RULE.read_bytes()).hexdigest(), RULE_SHA256)
        metadata = json.loads(RULE.with_suffix('.mk.source.json').read_text())
        self.assertEqual(metadata['coreCommit'], 'bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1')
        self.assertEqual(metadata['sha256'], RULE_SHA256)

    def test_both_installed_targets_preserve_common_pch_flags_and_native_guard(self):
        baseline = (UPSTREAM / RECIPE).read_text()
        for target in ('windows-arm64',):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as temporary:
                source = install_source(Path(temporary), target)
                installed = (source / RECIPE).read_text()
                self.assertIn('gb_Library_use_common_precompiled_header,winaccessibility', installed)
                self.assertEqual(library_definitions(installed, 'winaccessibility'),
                                 library_definitions(baseline, 'winaccessibility'),
                                 'A diagnostic-only definition breaks the shared system PCH')
                self.assertIn(DEFINE, (source / 'winaccessibility/Library_uacccom.mk').read_text())
                self.assertIn('!defined(OPENGEUL_WRITER_SERVER_OBSERVER_DIAGNOSTIC)',
                              (BACKEND / 'native.cpp').read_text())

    def test_real_gbuild_checker_accepts_installed_recipe_and_rejects_added_define(self):
        make = shutil.which('make') or shutil.which('gmake')
        if make is None:
            self.skipTest('GNU make unavailable; source flag contract still executes')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = install_source(root, 'windows-arm64')
            makefile = root / 'probe.mk'
            makefile.write_text(
                'gb_ENABLE_PCH := 1\n'
                f'include {RULE.as_posix()}\n'
                'gb_Library_add_defs = observed_defs += $(strip $(2))\n'
                f'include {(source / RECIPE).as_posix()}\n'
                '$(file >actual.txt,$(strip $(call gb_PrecompiledHeader_check_flags_internal,'
                '-DBASE,-DBASE $(observed_defs),pch/inc/pch/precompiled_system)))\n'
                '$(file >negative.txt,$(strip $(call gb_PrecompiledHeader_check_flags_internal,'
                f'-DBASE,-DBASE {DEFINE},pch/inc/pch/precompiled_system)))\n'
                '.PHONY: all\nall: ;\n')
            result = subprocess.run([make, '-rR', '-f', str(makefile), 'all'], cwd=root,
                                    env={}, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual((root / 'actual.txt').read_text().strip(), '',
                             'Installed recipe is incompatible with the real shared-PCH checker')
            self.assertEqual((root / 'negative.txt').read_text().strip(), DEFINE,
                             'The checker must retain its rejection of incompatible definitions')


if __name__ == '__main__':
    unittest.main()
