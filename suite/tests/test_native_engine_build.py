"""Execute portable PowerShell boundaries; never claim Windows compiler proof."""
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

SOURCE=Path(__file__).resolve().parents[1]/'scripts/build-native-engine.ps1'
PWSH=shutil.which('pwsh') or '/workspace/work/opengeul-improvements/work/ime-api-review/powershell/pwsh'


def quote(value): return "'"+str(value).replace("'","''")+"'"


class NativeEngineBuildTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SOURCE.is_file(),'Native ARM64 source-build driver is missing')
        self.assertTrue(Path(PWSH).is_file(),'Portable PowerShell is required for command-boundary tests')
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def ps(self,body):
        script=self.root/'case.ps1'
        script.write_text("$ErrorActionPreference='Stop'\n. "+quote(SOURCE)+"\n"+body,encoding='utf-8')
        result=subprocess.run([PWSH,'-NoLogo','-NoProfile','-File',str(script)],text=True,capture_output=True,timeout=30)
        self.assertEqual(0,result.returncode,result.stdout+'\n'+result.stderr)
        return result.stdout.strip()

    def rejected(self,body):
        self.ps("$rejected=$false; try { "+body+" } catch { $rejected=$true }; if(-not $rejected){ throw 'Unsafe condition was accepted' }")

    def test_native_host_requires_real_windows_arm64_and_unemulated_controller(self):
        self.ps("Assert-NativeBuildHost ([pscustomobject]@{isWindows=$true;processMachine=0;nativeMachine=43620})")
        for props in ("isWindows=$false;processMachine=0;nativeMachine=43620", "isWindows=$true;processMachine=34404;nativeMachine=43620", "isWindows=$true;processMachine=0;nativeMachine=34404"):
            self.rejected("Assert-NativeBuildHost ([pscustomobject]@{"+props+"})")

    def test_fresh_directories_refuse_existing_overlap_and_linked_parent(self):
        work=self.root/'work'; output=self.root/'output'
        self.ps(f"$paths=New-BuildDirectories {quote(work)} {quote(output)}; if(-not(Test-Path $paths.work)){{throw 'No owned work directory'}}")
        self.rejected(f"New-BuildDirectories {quote(work)} {quote(self.root/'fresh')}")
        self.rejected(f"New-BuildDirectories {quote(self.root/'outer')} {quote(self.root/'outer/inner')}")
        link=self.root/'link'
        try: link.symlink_to(work,target_is_directory=True)
        except (OSError,NotImplementedError): return
        self.rejected(f"New-BuildDirectories {quote(link/'new')} {quote(self.root/'another')}")

    def test_config_requires_native_firebird_not_just_successful_configure(self):
        config=self.root/'config_host.mk'
        good={'OS':'WNT','COM':'MSC','CPUNAME':'AARCH64','HOST_PLATFORM':'aarch64-pc-cygwin','BUILD_PLATFORM':'aarch64-pc-cygwin','WIN_HOST_ARCH':'arm64','WIN_BUILD_ARCH':'arm64','ENABLE_FIREBIRD_SDBC':'TRUE','SYSTEM_FIREBIRD':'','CROSS_COMPILING':'','BUILD_TYPE':'FIREBIRD ICU LIBATOMIC_OPS LIBTOMMATH'}
        def write(values): config.write_text(''.join(f'export {key}={value}\n' for key,value in values.items()))
        write({key:value for key,value in good.items() if key not in ('WIN_HOST_ARCH','WIN_BUILD_ARCH')})
        self.ps(f"$config=Assert-GeneratedConfiguration {quote(config)}; if($config.CPUNAME -ne 'AARCH64'){{throw 'Wrong parsed config'}}")
        for field,value in [('CPUNAME','X86_64'),('ENABLE_FIREBIRD_SDBC',''),('CROSS_COMPILING','TRUE'),('CROSS_COMPILING','yes'),('SYSTEM_FIREBIRD','TRUE'),('BUILD_TYPE','ICU'),('HOST_PLATFORM','x86_64-pc-cygwin')]:
            with self.subTest(field=field):
                write(dict(good,**{field:value}))
                self.rejected(f"Assert-GeneratedConfiguration {quote(config)}")

    def test_failure_receipt_and_config_logs_survive_native_host_rejection(self):
        work=self.root/'failed-work';output=self.root/'failed-evidence'
        self.ps(f"function Get-NativeBuildHost {{ throw 'observed wrong actual host' }}; try {{ Invoke-NativeEngineBuild Full {quote(work)} {quote(output)} '' 4 }} catch {{ }}")
        receipt=json.loads((output/'source-build-receipt.json').read_text())
        self.assertFalse(receipt['passed'])
        self.assertFalse(receipt['fullEngineQualified'])
        self.assertEqual('native-host',receipt['stage'])
        self.assertIn('observed wrong actual host',receipt['error'])
        self.assertFalse((output/'OpenGeul-Office-engine-arm64.zip').exists())

    def test_generated_native_base_probe_has_valid_python_syntax(self):
        probe=self.root/'probe.py'
        self.ps(f"Write-BaseProofScript {quote(probe)}")
        compile(probe.read_text(encoding='utf-8'),str(probe),'exec')

    def test_recipe_explicit_native_triples_visual_studio_and_firebird_first(self):
        raw=self.ps("[pscustomobject]@{configure=@(Get-ConfigureArguments);firebird=@(Get-BuildTargets Firebird);full=@(Get-BuildTargets Full)}|ConvertTo-Json -Compress")
        data=json.loads(raw)
        for argument in ('--build=aarch64-pc-cygwin','--host=aarch64-pc-cygwin','--with-visual-studio=2026','--enable-firebird-sdbc','--without-system-firebird'):
            self.assertIn(argument,data['configure'])
        self.assertEqual(['ExternalProject_firebird','firebird'],data['firebird'])
        self.assertEqual(data['firebird']+['build'],data['full'])
        self.assertFalse(any('cross-build' in arg for arg in data['configure']))

    def test_bash_scripts_are_utf8_without_bom_or_windows_crlf(self):
        script=self.root/'actual.sh'
        self.ps(f"Write-BashScript {quote(script)} @('set -euo pipefail','printf bash-native-boundary')")
        data=script.read_bytes()
        self.assertNotIn(b'\r',data)
        self.assertFalse(data.startswith(b'\xef\xbb\xbf'))
        if os.name!='nt':
            result=subprocess.run(['/bin/bash',str(script)],capture_output=True,text=True,timeout=5)
            self.assertEqual(0,result.returncode,result.stderr)
            self.assertEqual('bash-native-boundary',result.stdout)

    def test_extra_source_modules_are_authenticated_and_cache_is_explicit(self):
        raw=self.ps("[pscustomobject]@{pins=@(Get-ExtraSourcePins);configure=@(Get-ConfigureArguments '/owned/source-cache')}|ConvertTo-Json -Depth 8 -Compress")
        data=json.loads(raw)
        self.assertEqual(3,len(data['pins']))
        self.assertEqual([53513324,62319860,236160656],[pin['size'] for pin in data['pins']])
        for pin in data['pins']:
            self.assertTrue(pin['url'].startswith('https://download.documentfoundation.org/libreoffice/src/26.8.1/'))
            self.assertEqual(64,len(pin['sha256']))
        self.assertIn('--with-external-tar=/owned/source-cache',data['configure'])

    def test_authenticated_source_uses_exact_official_url_size_and_hash(self):
        lock=SOURCE.parents[1]/'config/runtime.lock.json'
        data=json.loads(self.ps(f"Get-SourcePin {quote(lock)}|ConvertTo-Json -Compress"))
        self.assertEqual(302435508,data['size'])
        self.assertEqual('296ba78e7ab0d381b94c3d6342f4ebb2320ee5097ca58781b9b744cab90b9785',data['sha256'])
        self.assertEqual(json.loads(lock.read_text())['runtime']['sourceUrl'],data['url'])
        bad=json.loads(lock.read_text()); bad['runtime']['sourceUrl']='https://example.org/renamed.tar.xz'
        path=self.root/'bad.json';path.write_text(json.dumps(bad))
        self.rejected(f"Get-SourcePin {quote(path)}")

    def test_authentication_rejects_wrong_size_or_hash_before_execution(self):
        fixture=self.root/'owned';fixture.write_bytes(b'authenticated')
        import hashlib
        digest=hashlib.sha256(fixture.read_bytes()).hexdigest()
        self.ps(f"Confirm-FileIdentity {quote(fixture)} 13 SHA256 {quote(digest)}|Out-Null")
        self.rejected(f"Confirm-FileIdentity {quote(fixture)} 12 SHA256 {quote(digest)}")
        self.rejected(f"Confirm-FileIdentity {quote(fixture)} 13 SHA256 {quote('0'*64)}")

    def test_command_boundary_preserves_stdout_stderr_and_nonzero_receipt(self):
        prefix=self.root/'command'
        body=f"try {{ Invoke-LoggedCommand -FilePath {quote(os.sys.executable)} -Arguments @('-c','import sys;print(\"stdout retained\");print(\"stderr retained\",file=sys.stderr);sys.exit(9)') -WorkingDirectory {quote(self.root)} -LogPrefix {quote(prefix)} }} catch {{ }}"
        self.ps(body)
        self.assertIn('stdout retained',(self.root/'command.stdout.log').read_text())
        self.assertIn('stderr retained',(self.root/'command.stderr.log').read_text())
        receipt=json.loads((self.root/'command.command.json').read_text())
        self.assertEqual(9,receipt['exitCode'])
        self.assertFalse(receipt['passed'])
        self.assertIn('import sys;',receipt['arguments'][1])

    def test_successful_command_retains_exact_spaced_arguments(self):
        prefix=self.root/'success'
        self.ps(f"Invoke-LoggedCommand {quote(os.sys.executable)} @('-c','import sys;print(sys.argv[1])','exact spaced argument') {quote(self.root)} {quote(prefix)}|Out-Null")
        self.assertEqual('exact spaced argument',(self.root/'success.stdout.log').read_text().strip())
        self.assertTrue(json.loads((self.root/'success.command.json').read_text())['passed'])

    def test_pe_machine_rejects_emulated_products_and_truncated_headers(self):
        path=self.root/'native.exe'
        data=bytearray(512);data[:2]=b'MZ';struct.pack_into('<I',data,60,128);data[128:132]=b'PE\0\0';struct.pack_into('<H',data,132,0xAA64);struct.pack_into('<H',data,148,240);struct.pack_into('<H',data,152,0x20B)
        path.write_bytes(data)
        self.ps(f"$pe=Get-ProductPeIdentity {quote(path)}; if($pe.machine -ne 43620){{throw 'Not ARM64'}}")
        struct.pack_into('<H',data,132,0x8664);path.write_bytes(data)
        self.rejected(f"Get-ProductPeIdentity {quote(path)}")
        path.write_bytes(b'MZ')
        self.rejected(f"Get-ProductPeIdentity {quote(path)}")

    def test_il_only_anycpu_dll_is_preserved_but_native_x86_flags_fail(self):
        path=self.root/'managed.dll'
        data=bytearray(1024);data[:2]=b'MZ';struct.pack_into('<I',data,60,128);data[128:132]=b'PE\0\0'
        struct.pack_into('<H',data,132,0x14c);struct.pack_into('<H',data,134,1);struct.pack_into('<H',data,148,224);struct.pack_into('<H',data,150,0x2000)
        opt=152;struct.pack_into('<H',data,opt,0x10b);struct.pack_into('<I',data,opt+92,16);struct.pack_into('<II',data,opt+96+14*8,0x2000,72)
        section=opt+224;struct.pack_into('<IIII',data,section+8,512,0x2000,512,512)
        struct.pack_into('<I',data,512,72);struct.pack_into('<III',data,520,0x2080,32,1);data[640:644]=b'BSJB'
        path.write_bytes(data)
        self.ps(f"$pe=Get-ProductPeIdentity {quote(path)};if($pe.role -ne 'managedAnyCpu'){{throw 'IL-only AnyCPU rejected'}}")
        for offset,value in [(528,3),(576,0x2222)]:
            bad=bytearray(data);struct.pack_into('<I',bad,offset,value);path.write_bytes(bad)
            self.rejected(f"Get-ProductPeIdentity {quote(path)}")

    def test_only_exact_authenticated_python_template_metadata_is_admitted(self):
        raw=self.ps("@(Get-PinnedPythonTemplates)|ConvertTo-Json -Compress")
        pins=json.loads(raw)
        self.assertEqual(10,len(pins))
        chosen=pins[0]
        self.ps(f"Assert-PythonTemplateAdmission {quote(chosen['path'])} {chosen['machine']} {quote(chosen['sha256'])}|Out-Null")
        for path,machine,digest in [('program/python.exe',chosen['machine'],chosen['sha256']),
                                    (chosen['path'],0xAA64,chosen['sha256']),
                                    (chosen['path'],chosen['machine'],'0'*64)]:
            self.rejected(f"Assert-PythonTemplateAdmission {quote(path)} {machine} {quote(digest)}")

    def test_external_archives_match_authenticated_download_list_before_qualification(self):
        import hashlib
        cache=self.root/'cache';cache.mkdir()
        archive=cache/'Python-owned.tar.xz';archive.write_bytes(b'pinned Python input')
        digest=hashlib.sha256(archive.read_bytes()).hexdigest()
        pins=self.root/'pins.log';pins.write_text('PIN|PYTHON_TARBALL|Python-owned.tar.xz|'+digest+'\n')
        output=self.root/'source-inputs.json'
        self.ps(f"Write-ExternalSourceInventory {quote(cache)} {quote(pins)} {quote(output)} @{{}} '' -RequirePython|Out-Null")
        data=json.loads(output.read_text())
        self.assertEqual(digest,data['archives'][0]['sha256'])
        self.assertTrue(data['pythonSourceVerified'])
        archive.write_bytes(b'tampered')
        self.rejected(f"Write-ExternalSourceInventory {quote(cache)} {quote(pins)} {quote(self.root/'bad-inputs.json')} @{{}} '' -RequirePython")
        archive.write_bytes(b'pinned Python input')
        (cache/'unknown-pip.zip').write_bytes(b'not upstream pinned')
        self.rejected(f"Write-ExternalSourceInventory {quote(cache)} {quote(pins)} {quote(self.root/'unknown-inputs.json')} @{{}} '' -RequirePython")

    def test_reused_command_prefix_preserves_original_receipt(self):
        prefix=self.root/'once'
        self.ps(f"Invoke-LoggedCommand {quote(os.sys.executable)} @('-c','print(123)') {quote(self.root)} {quote(prefix)}|Out-Null")
        original=(self.root/'once.command.json').read_bytes()
        self.rejected(f"Invoke-LoggedCommand {quote(os.sys.executable)} @('-c','print(456)') {quote(self.root)} {quote(prefix)}")
        self.assertEqual(original,(self.root/'once.command.json').read_bytes())

    def crt_fixture(self,family='Microsoft.VC145.CRT',redist_version='14.50.12350'):
        tools=self.root/'VS/VC/Tools/MSVC/14.50.12345'
        tools.mkdir(parents=True)
        source=self.root/('VS/VC/Redist/MSVC/'+redist_version+'/arm64/'+family)
        source.mkdir(parents=True)
        names=('concrt140.dll','msvcp140.dll','msvcp140_1.dll','msvcp140_2.dll','msvcp140_atomic_wait.dll','msvcp140_codecvt_ids.dll','vcruntime140.dll','vcruntime140_1.dll','vcruntime140_threads.dll')
        data=bytearray(512);data[:2]=b'MZ';struct.pack_into('<I',data,60,128);data[128:132]=b'PE\0\0';struct.pack_into('<H',data,132,0xAA64);struct.pack_into('<H',data,148,240);struct.pack_into('<H',data,152,0x20B)
        for name in names:(source/name).write_bytes(data)
        return tools,source,names

    def crt_mock(self):
        return "function Get-CrtSigningIdentity($Path) { [pscustomobject]@{status='Valid';signerSubject='CN=Microsoft Corporation, O=Microsoft Corporation, C=US';signerThumbprint=('a'*40);fileVersion='14.50.12350.0';productVersion='14.50.12350.0';fileVersionParts=@(14,50,12350,0);productVersionParts=@(14,50,12350,0);companyName='Microsoft Corporation';originalFilename=[IO.Path]::GetFileName($Path)} }; "

    def test_source_run_binding_matches_real_git_tree_and_rejects_dirty_or_wrong_run_sha(self):
        repo=self.root/'bound-repo';repo.mkdir()
        driver=repo/'driver.ps1';driver.write_text('# committed driver\n')
        manifest=repo/'source-build.json';manifest.write_text('{"schemaVersion":1}\n')
        def git(*arguments):
            result=subprocess.run(['git','-C',str(repo),*arguments],text=True,capture_output=True,timeout=5)
            self.assertEqual(0,result.returncode,result.stderr)
            return result.stdout.strip()
        git('init','-q');git('config','user.email','fixture@example.invalid');git('config','user.name','Fixture')
        git('add','.');git('commit','-qm','fixture')
        head=git('rev-parse','HEAD');tree=git('rev-parse','HEAD^{tree}')
        logs=self.root/'source-logs';logs.mkdir()
        env=f"$env:GITHUB_SHA='{head}';$env:GITHUB_RUN_ID='39000146117';$env:GITHUB_RUN_ATTEMPT='2'; "
        raw=self.ps(env+f"Get-SourceRunBinding {quote(repo)} {quote(driver)} {quote(manifest)} {quote(logs)}|ConvertTo-Json -Compress")
        data=json.loads(raw.splitlines()[-1])
        self.assertEqual(head,data['sourceCommit']);self.assertEqual(tree,data['sourceTree'])
        self.assertEqual(39000146117,data['sourceRun']);self.assertEqual(2,data['runAttempt'])
        import hashlib
        self.assertEqual(hashlib.sha256(driver.read_bytes()).hexdigest(),data['driverSha256'])
        self.assertEqual(hashlib.sha256(manifest.read_bytes()).hexdigest(),data['sourcePortManifestSha256'])
        wrong=self.root/'wrong-run';wrong.mkdir()
        self.rejected(env.replace(head,'0'*40)+f"Get-SourceRunBinding {quote(repo)} {quote(driver)} {quote(manifest)} {quote(wrong)}")
        driver.write_text('# uncommitted changed driver\n')
        dirty=self.root/'dirty-run';dirty.mkdir()
        self.rejected(env+f"Get-SourceRunBinding {quote(repo)} {quote(driver)} {quote(manifest)} {quote(dirty)}")

    def test_native_crt_preflight_binds_configured_vs_and_permits_current_abi_folder(self):
        tools,source,names=self.crt_fixture(family='Microsoft.VC143.CRT')
        raw=self.ps(self.crt_mock()+f"Get-AppLocalCrtPlan {quote(tools)} 'v145'|ConvertTo-Json -Depth 12 -Compress")
        plan=json.loads(raw)
        self.assertEqual(9,len(plan['files']))
        self.assertEqual(str(source),plan['sourceDirectory'])
        self.assertEqual('Microsoft.VC143.CRT',plan['redistFamily'])
        self.assertEqual('14.50.12345',plan['compilerToolsVersion'])
        self.assertEqual(set(names),{row['name'] for row in plan['files']})
        self.rejected(self.crt_mock()+f"Get-AppLocalCrtPlan {quote(tools)} 'v143'")

    def test_native_crt_same_tool_version_directory_is_accepted(self):
        tools,source,names=self.crt_fixture(redist_version='14.50.12345')
        self.ps(self.crt_mock()+f"Get-AppLocalCrtPlan {quote(tools)} 'v145'|Out-Null")

    def test_native_crt_preflight_rejects_older_toolset_missing_file_and_bad_pe(self):
        tools,source,names=self.crt_fixture(redist_version='14.44.99999')
        self.rejected(self.crt_mock()+f"Get-AppLocalCrtPlan {quote(tools)} 'v145'")
        new=source.parents[2]/'14.50.12350/arm64/Microsoft.VC145.CRT'
        new.parent.mkdir(parents=True);shutil.move(str(source),str(new))
        (new/names[-1]).unlink()
        self.rejected(self.crt_mock()+f"Get-AppLocalCrtPlan {quote(tools)} 'v145'")
        (new/names[-1]).write_bytes(b'MZ')
        self.rejected(self.crt_mock()+f"Get-AppLocalCrtPlan {quote(tools)} 'v145'")

    def test_native_crt_preflight_rejects_nonmicrosoft_signature_and_older_dll_version(self):
        tools,source,names=self.crt_fixture()
        base=self.crt_mock()
        for changed in (base.replace("status='Valid'","status='NotTrusted'"),base.replace('O=Microsoft Corporation','O=Other Corporation'),base.replace('@(14,50,12350,0)','@(14,44,99999,0)')):
            self.rejected(changed+f"Get-AppLocalCrtPlan {quote(tools)} 'v145'")

    def test_native_crt_stage_copies_only_nine_authentic_bytes_and_redistribution_terms(self):
        tools,source,names=self.crt_fixture()
        (source/'arbitrary.dll').write_bytes(b'never copy')
        program=self.root/'instdir/program';program.mkdir(parents=True)
        terms=self.root/'terms.html';terms.write_text('Preserved Microsoft Visual Studio2026 redistribution terms')
        raw=self.ps(self.crt_mock()+f"$plan=Get-AppLocalCrtPlan {quote(tools)} 'v145'; Install-AppLocalCrt $plan {quote(program)} {quote(terms)}|ConvertTo-Json -Depth 12 -Compress")
        receipt=json.loads(raw)
        self.assertEqual(9,len(receipt['files']))
        self.assertEqual(set(names),{p.name for p in program.iterdir()})
        for name in names:self.assertEqual((source/name).read_bytes(),(program/name).read_bytes())
        self.assertTrue((program.parent/'share/readme/Microsoft-VC145-redistribution.html').is_file())

    def test_native_crt_stage_rejects_linked_notice_directory_before_any_copy(self):
        tools,source,names=self.crt_fixture()
        program=self.root/'instdir/program';program.mkdir(parents=True)
        outside=self.root/'outside';outside.mkdir()
        share=program.parent/'share';share.mkdir()
        try:(share/'readme').symlink_to(outside,target_is_directory=True)
        except (OSError,NotImplementedError):return
        terms=self.root/'terms.html';terms.write_text('Owned terms snapshot')
        self.rejected(self.crt_mock()+f"$plan=Get-AppLocalCrtPlan {quote(tools)} 'v145';Install-AppLocalCrt $plan {quote(program)} {quote(terms)}")
        self.assertEqual([],list(program.iterdir()))
        self.assertEqual([],list(outside.iterdir()))

    def test_native_crt_stage_rejects_collision_or_changed_source_before_any_copy(self):
        tools,source,names=self.crt_fixture()
        program=self.root/'program';program.mkdir()
        target=program/names[0];target.write_bytes(b'preserve collision')
        terms=self.root/'terms.html';terms.write_text('Owned terms snapshot')
        self.rejected(self.crt_mock()+f"$plan=Get-AppLocalCrtPlan {quote(tools)} 'v145';Install-AppLocalCrt $plan {quote(program)} {quote(terms)}")
        self.assertEqual([target],list(program.iterdir()))
        self.assertEqual(b'preserve collision',target.read_bytes())
        target.unlink()
        self.rejected(self.crt_mock()+f"$plan=Get-AppLocalCrtPlan {quote(tools)} 'v145';[IO.File]::WriteAllText({quote(source/names[0])},'changed');Install-AppLocalCrt $plan {quote(program)} {quote(terms)}")
        self.assertEqual([],list(program.iterdir()))

    def test_isql_oracle_requires_exact_committed_rows_and_rollback(self):
        output=self.root/'isql.log'
        output.write_text('ROW_COUNT 2\nTOTAL 68\nROW_ONE 1\nROW_THREE 1\n')
        self.ps(f"Assert-IsqlOutput {quote(output)}")
        output.write_text('ROW_COUNT 2\nTOTAL 42\nROW_ONE 1\nROW_THREE 1\n')
        self.rejected(f"Assert-IsqlOutput {quote(output)}")
        sql=self.ps("Get-IsqlSql -DatabasePath 'C:\\owned\\proof.fdb'|ConvertTo-Json -Compress")
        sql=json.loads(sql)
        self.assertIn('ROLLBACK;',sql['create'])
        self.assertIn('DELETE FROM OPENGEUL_ARM64_PROBE',sql['create'])
        self.assertIn('ROW_THREE',sql['verify'])

    def test_full_qualification_rejects_missing_base_native_or_crud_semantics(self):
        report=self.root/'base.json'
        good={'schemaVersion':1,'passed':True,'guiVerified':False,'nativeProcesses':[{'processMachine':0,'nativeMachine':43620,'role':'uno-python'},{'processMachine':0,'nativeMachine':43620,'role':'uno-host','jobOwned':True,'phase':'create'},{'processMachine':0,'nativeMachine':43620,'role':'uno-host','jobOwned':True,'phase':'reopen'}],'rows':[{'id':1,'text':'Engine-OpenGeul-base 한글','amount':42}],'independentReopenVerified':True}
        report.write_text(json.dumps(good))
        self.ps(f"Assert-BaseProof {quote(report)}|Out-Null")
        for field,value in [('passed',False),('rows',[]),('independentReopenVerified',False),('nativeProcesses',[{'processMachine':34404,'nativeMachine':43620}]),('nativeProcesses',[{'processMachine':0,'nativeMachine':43620,'role':'soffice-launcher'}]*3)]:
            report.write_text(json.dumps(dict(good,**{field:value})))
            self.rejected(f"Assert-BaseProof {quote(report)}")


if __name__=='__main__':unittest.main()
