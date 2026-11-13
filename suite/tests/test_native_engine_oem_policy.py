"""Execute the OEM network-service policy and exact pinned configure condition."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from suite.tests.test_native_engine_build import PWSH, SOURCE, quote


class NativeEngineOemPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def ps(self,body):
        path=self.root/'case.ps1'
        path.write_text("$ErrorActionPreference='Stop'\n. "+quote(SOURCE)+'\n'+body)
        result=subprocess.run([PWSH,'-NoLogo','-NoProfile','-File',str(path)],text=True,capture_output=True,timeout=30)
        self.assertEqual(0,result.returncode,result.stdout+'\n'+result.stderr)
        return result.stdout.strip()

    def test_explicit_policy_disables_only_optional_tdf_network_services(self):
        arguments=json.loads(self.ps('@(Get-ConfigureArguments)|ConvertTo-Json -Compress'))
        for option in ('--disable-online-update','--disable-online-update-mar','--disable-breakpad'):
            self.assertEqual(1,arguments.count(option),option)
        self.assertFalse(any(value.startswith('--with-privacy-policy-url') for value in arguments))
        for option in ('--with-distro=LibreOfficeWinArm64','--with-package-format=archive',
                       '--enable-firebird-sdbc','--enable-database-connectivity','--with-lang=en-US ko'):
            self.assertIn(option,arguments)
        for option in ('--without-java','--disable-odk','--without-help','--disable-harfbuzz',
                       '--disable-database-connectivity','--disable-firebird-sdbc'):
            self.assertNotIn(option,arguments)

    def test_generated_policy_requires_present_empty_flags_and_no_service_build_tokens(self):
        path=self.root/'config_host.mk'
        fields=('ENABLE_ONLINE_UPDATE','ENABLE_ONLINE_UPDATE_MAR','ENABLE_BREAKPAD')
        good=dict(OS='WNT',COM='MSC',CPUNAME='AARCH64',HOST_PLATFORM='aarch64-pc-cygwin',
                  BUILD_PLATFORM='aarch64-pc-cygwin',ENABLE_FIREBIRD_SDBC='TRUE',SYSTEM_FIREBIRD='',
                  CROSS_COMPILING='',BUILD_TYPE='FIREBIRD ICU LIBATOMIC_OPS LIBTOMMATH',PKGFORMAT='archive',
                  **{field:'' for field in fields})
        def write(value):path.write_text(''.join('export '+key+'='+value+'\n' for key,value in value.items()))
        write(good)
        parsed=json.loads(self.ps(f'Assert-GeneratedConfiguration {quote(path)}|ConvertTo-Json -Compress'))
        self.assertTrue(all(field in parsed and parsed[field]=='' for field in fields))
        wrong=[]
        for field in fields:
            wrong.append({key:value for key,value in good.items() if key!=field})
            wrong.extend(dict(good,**{field:value}) for value in ('TRUE','FALSE','0','no'))
        wrong.extend(dict(good,BUILD_TYPE=good['BUILD_TYPE']+' '+token) for token in ('BREAKPAD','ONLINEUPDATE'))
        for index,values in enumerate(wrong):
            with self.subTest(case=index):
                write(values)
                self.ps(f"$rejected=$false;try{{Assert-GeneratedConfiguration {quote(path)}}}catch{{$rejected=$true}};if(-not $rejected){{throw 'Enabled or missing network policy admitted'}}")

    @unittest.skipUnless(os.name=='posix' and shutil.which('autoconf') and os.environ.get('OPENGEUL_LIBREOFFICE_CONFIGURE_SOURCE'),
                         'Pinned upstream configure condition requires explicit local source and Autoconf')
    def test_actual_pinned_privacy_condition_rejects_enabled_services_and_accepts_oem_overrides(self):
        raw=Path(os.environ['OPENGEUL_LIBREOFFICE_CONFIGURE_SOURCE']).read_bytes()
        manifest=json.loads((SOURCE.parents[1]/'engine-build/source-build.json').read_text())
        self.assertEqual(manifest['configureSource']['sha256'],hashlib.sha256(raw).hexdigest())
        text=raw.decode()
        breakpad=text[text.index('DEFAULT_CRASHDUMP_VALUE="true"'):text.index('AC_SUBST(DEFAULT_CRASHDUMP_VALUE)')+len('AC_SUBST(DEFAULT_CRASHDUMP_VALUE)')]
        updates=text[text.index('AC_MSG_CHECKING([whether to enable online update])'):text.index('AC_SUBST(PRIVACY_POLICY_URL)')+len('AC_SUBST(PRIVACY_POLICY_URL)')]
        (self.root/'configure.ac').write_text('AC_INIT([network-policy-source-check],[1])\n'+
            'AC_ARG_ENABLE([online-update])\nAC_ARG_ENABLE([online-update-mar])\nAC_ARG_ENABLE([breakpad])\n'+
            'AC_ARG_WITH([privacy-policy-url],[],[],[with_privacy_policy_url=undefined])\n'+
            'enable_curl=yes\nBUILD_TYPE="LibO FIREBIRD LIBATOMIC_OPS LIBTOMMATH"\n'+breakpad+'\n'+updates+
            '\nAC_SUBST([BUILD_TYPE])\nAC_CONFIG_FILES([policy.mk])\nAC_OUTPUT\n')
        keys=('ENABLE_ONLINE_UPDATE','ENABLE_ONLINE_UPDATE_MAR','ENABLE_BREAKPAD','BUILD_TYPE','PRIVACY_POLICY_URL')
        (self.root/'policy.mk.in').write_text(''.join(key+'=@'+key+'@\n' for key in keys))
        result=subprocess.run(['autoconf'],cwd=self.root,text=True,capture_output=True,timeout=20)
        self.assertEqual(0,result.returncode,result.stderr)
        enabled=['--enable-online-update','--enable-online-update-mar','--enable-breakpad']
        result=subprocess.run(['/bin/sh','configure',*enabled],cwd=self.root,text=True,capture_output=True,timeout=10)
        self.assertNotEqual(0,result.returncode)
        self.assertIn('no --with-privacy-policy-url',result.stderr)
        arguments=json.loads(self.ps('@(Get-ConfigureArguments)|ConvertTo-Json -Compress'))
        overrides=[value for value in arguments if value in ('--disable-online-update','--disable-online-update-mar','--disable-breakpad')]
        result=subprocess.run(['/bin/sh','configure',*enabled,*overrides],cwd=self.root,text=True,capture_output=True,timeout=10)
        self.assertEqual(0,result.returncode,result.stdout+result.stderr)
        effective=dict(line.split('=',1) for line in (self.root/'policy.mk').read_text().splitlines())
        self.assertTrue(all(effective[key]=='' for key in keys[:3]))
        self.assertEqual('undefined',effective['PRIVACY_POLICY_URL'])
        self.assertNotIn('BREAKPAD',effective['BUILD_TYPE'].split())
        self.assertNotIn('ONLINEUPDATE',effective['BUILD_TYPE'].split())
        for token in ('FIREBIRD','LIBATOMIC_OPS','LIBTOMMATH'):
            self.assertIn(token,effective['BUILD_TYPE'].split())


if __name__=='__main__':unittest.main()
