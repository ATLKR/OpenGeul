"""Archive-only engine packaging retains runtime/native qualification gates."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from suite.tests.test_native_engine_build import PWSH, SOURCE, quote


class NativeEngineArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def ps(self, body):
        script = self.root/'case.ps1'
        script.write_text("$ErrorActionPreference='Stop'\n. "+quote(SOURCE)+'\n'+body)
        result = subprocess.run([PWSH,'-NoLogo','-NoProfile','-File',str(script)],
                                text=True,capture_output=True,timeout=30)
        self.assertEqual(0,result.returncode,result.stdout+'\n'+result.stderr)
        return result.stdout.strip()

    def test_explicit_archive_override_retains_native_runtime_options_and_build_targets(self):
        data = json.loads(self.ps("[pscustomobject]@{arguments=@(Get-ConfigureArguments);targets=@(Get-BuildTargets Full)}|ConvertTo-Json -Compress"))
        formats = [value for value in data['arguments'] if value.startswith('--with-package-format=')]
        self.assertEqual(['--with-package-format=archive'], formats)
        self.assertIn('--with-distro=LibreOfficeWinArm64',data['arguments'])
        self.assertIn('--enable-firebird-sdbc',data['arguments'])
        self.assertIn('--enable-database-connectivity',data['arguments'])
        self.assertIn('--with-lang=en-US ko',data['arguments'])
        for forbidden in ('--without-java','--disable-odk','--without-help','--disable-harfbuzz'):
            self.assertNotIn(forbidden,data['arguments'])
        self.assertEqual(['ExternalProject_firebird','firebird','build'],data['targets'])

    def test_generated_config_requires_exact_archive_format_and_records_it(self):
        config = self.root/'config_host.mk'
        good = dict(OS='WNT',COM='MSC',CPUNAME='AARCH64',HOST_PLATFORM='aarch64-pc-cygwin',
                    BUILD_PLATFORM='aarch64-pc-cygwin',ENABLE_FIREBIRD_SDBC='TRUE',SYSTEM_FIREBIRD='',
                    CROSS_COMPILING='',BUILD_TYPE='FIREBIRD ICU LIBATOMIC_OPS LIBTOMMATH',PKGFORMAT='archive',
                    ENABLE_ONLINE_UPDATE='',ENABLE_ONLINE_UPDATE_MAR='',ENABLE_BREAKPAD='')
        def write(values): config.write_text(''.join('export '+key+'='+value+'\n' for key,value in values.items()))
        write(good)
        parsed = json.loads(self.ps(f"Assert-GeneratedConfiguration {quote(config)}|ConvertTo-Json -Compress"))
        self.assertEqual('archive',parsed['PKGFORMAT'])
        for value in ('msi','archive msi','msi archive','ARCHIVE','installed',''):
            with self.subTest(format=value):
                write(dict(good,PKGFORMAT=value))
                self.ps(f"$rejected=$false;try{{Assert-GeneratedConfiguration {quote(config)}}}catch{{$rejected=$true}};if(-not $rejected){{throw 'Wrong package format admitted'}}")
        write({key:value for key,value in good.items() if key!='PKGFORMAT'})
        self.ps(f"$rejected=$false;try{{Assert-GeneratedConfiguration {quote(config)}}}catch{{$rejected=$true}};if(-not $rejected){{throw 'Missing package format admitted'}}")

    @unittest.skipUnless(os.name=='posix' and os.environ.get('OPENGEUL_LIBREOFFICE_CONFIGURE_SOURCE'),
                         'Actual authenticated upstream source shell checks require explicit local input')
    def test_pinned_upstream_msi_only_prerequisites_do_not_apply_to_archive(self):
        raw = Path(os.environ['OPENGEUL_LIBREOFFICE_CONFIGURE_SOURCE']).read_bytes()
        manifest = json.loads((SOURCE.parents[1]/'engine-build/source-build.json').read_text())
        self.assertEqual(manifest['configureSource']['sha256'],hashlib.sha256(raw).hexdigest())
        text = raw.decode()
        perl = text[text.index('perl_use_string="use Cwd ; use Digest::MD5"'):text.index('if test "$with_system_hsqldb" = "yes"; then')]
        start = text.index('    if test -n "$with_lang" -a "$with_lang" != "en-US"; then',text.index('dnl TODO: solenv/bin/modules/installer/windows/msiglobal.pm'))
        end = text.index('\nfi\nAC_SUBST(WINDOWS_SDK_HOME)',start)
        language = text[start:end].replace('AC_MSG_ERROR([WiLangId.vbs not found - building translated packages will fail])','echo installer-language-tool-required')
        arguments = json.loads(self.ps('@(Get-ConfigureArguments)|ConvertTo-Json -Compress'))
        effective = next((value.split('=',1)[1] for value in reversed(arguments) if value.startswith('--with-package-format=')),'msi')
        self.assertEqual('archive',effective)
        for package,requires_msi in (('msi',True),(effective,False)):
            script = self.root/(package+'.sh')
            script.write_text("set -eu\n_os=WINNT\nWSL_ONLY_AS_HELPER=\nwith_lang='en-US ko'\nWINDOWS_SDK_WILANGID_unix=/definitely/missing/WiLangId.vbs\n"+
                              'PKGFORMAT='+package+'\nwith_package_format='+package+'\n'+perl+'\necho "$perl_use_string"\n'+language+'\n')
            result = subprocess.run(['/bin/bash',str(script)],text=True,capture_output=True,timeout=5)
            self.assertEqual(0,result.returncode,result.stderr)
            self.assertEqual(requires_msi,'Font::TTF::Font' in result.stdout)
            self.assertEqual(requires_msi,'installer-language-tool-required' in result.stdout)


if __name__=='__main__':unittest.main()
