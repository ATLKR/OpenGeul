"""Execute portable PowerShell boundaries; never claim Windows compiler proof."""
import json
import os
from pathlib import Path
import re
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

    def test_native_source_gate_requires_explicit_mdds_archive_and_existing_actual_source_module(self):
        script = self.root/'source-gate.sh'
        self.ps(f"Write-NativeSourceGate {quote(script)} '/owned/repo' '/owned/lo source' '/owned/firebird.tar.bz2' '/owned/mdds.tar.xz'")
        raw = script.read_text()
        self.assertIn('export OPENGEUL_FIREBIRD_PORT_REQUIRE_SOURCE=1', raw)
        self.assertIn("export OPENGEUL_MDDS_SOURCE_ARCHIVE='/owned/mdds.tar.xz'", raw)
        self.assertIn("export OPENGEUL_FIREBIRD_SOURCE_ARCHIVE='/owned/firebird.tar.bz2'", raw)
        self.assertIn("export OPENGEUL_LIBREOFFICE_FIREBIRD_PATCHES='/owned/lo source/external/firebird'", raw)
        self.assertIn('/usr/bin/python3 -m unittest suite.tests.test_firebird_arm64_port -v', raw)
        result = subprocess.run(['bash','-n',str(script)],capture_output=True,text=True)
        self.assertEqual(0,result.returncode,result.stderr)

    def test_actual_mdds_header_retention_copies_owned_bytes_and_rejects_drift_or_links(self):
        import hashlib
        names = ['flat_segment_tree.hpp', 'flat_segment_tree_def.inl', 'node.hpp']
        source = self.root / 'source'; include = source / 'workdir/UnpackedTarball/mdds/include/mdds'
        include.mkdir(parents=True)
        lock = {'headers': [], 'nodeHeader': None}
        for name in names:
            raw = ('retention boundary '+name+'\n').encode(); (include/name).write_bytes(raw)
            item = {'path':'include/mdds/'+name, 'afterBytes':len(raw), 'afterSha256':hashlib.sha256(raw).hexdigest()}
            if name == 'node.hpp': lock['nodeHeader'] = item
            else: lock['headers'].append(item)
        pin = self.root/'mdds.json'; pin.write_text(json.dumps(lock))
        def retain(label):
            evidence = self.root/label; evidence.mkdir()
            result = json.loads(self.ps(f"Save-ActualMddsHeaders {quote(source)} {quote(evidence)} (Get-Content {quote(pin)} -Raw|ConvertFrom-Json)|ConvertTo-Json -Depth 8 -Compress"))
            return evidence,result
        evidence,result = retain('good')
        self.assertTrue(result['matchesExpected'])
        self.assertEqual(3,len(result['files']))
        for item in result['files']:
            self.assertEqual('retained',item['status'])
            self.assertEqual(Path(item['sourcePath']).read_bytes(),Path(item['evidencePath']).read_bytes())
            self.assertEqual(item['expectedSha256'],item['sha256'])
        (include/names[0]).write_bytes(b'drift')
        _,result = retain('drift');self.assertFalse(result['matchesExpected'])
        self.assertEqual('retained',result['files'][0]['status'])
        self.assertFalse(result['files'][0]['matchesExpected'])
        (include/names[0]).unlink()
        _,result = retain('missing');self.assertFalse(result['matchesExpected'])
        self.assertEqual('missing',result['files'][0]['status'])
        (include/names[0]).symlink_to(include/names[1])
        _,result = retain('linked');self.assertFalse(result['matchesExpected'])
        self.assertEqual('rejected',result['files'][0]['status'])
        self.assertFalse((self.root/'linked'/('actual-mdds-'+names[0])).exists())

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
        good={'OS':'WNT','COM':'MSC','CPUNAME':'AARCH64','HOST_PLATFORM':'aarch64-pc-cygwin','BUILD_PLATFORM':'aarch64-pc-cygwin','WIN_HOST_ARCH':'arm64','WIN_BUILD_ARCH':'arm64','ENABLE_FIREBIRD_SDBC':'TRUE','SYSTEM_FIREBIRD':'','CROSS_COMPILING':'','BUILD_TYPE':'FIREBIRD ICU LIBATOMIC_OPS LIBTOMMATH','PKGFORMAT':'archive','ENABLE_ONLINE_UPDATE':'','ENABLE_ONLINE_UPDATE_MAR':'','ENABLE_BREAKPAD':''}
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
        self.assertEqual('bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1',data.get('coreCommit'))
        bad=json.loads(lock.read_text()); bad['runtime']['sourceUrl']='https://example.org/renamed.tar.xz'
        path=self.root/'bad.json';path.write_text(json.dumps(bad))
        self.rejected(f"Get-SourcePin {quote(path)}")

    def build_identity_fixture(self, original='a'*40):
        import hashlib
        runtime=self.root/'runtime';program=runtime/'program';program.mkdir(parents=True)
        for name,section in (('version.ini','Version'),('setup.ini','Bootstrap')):
            (program/name).write_bytes(f'[{section}]\r\nbuildid={original}\r\nVendor=LibreOffice\r\n'.encode())
        archive=self.root/'source.tar.xz';archive.write_bytes(b'authenticated source archive fixture')
        pin={'url':'https://download.documentfoundation.org/libreoffice/src/26.8.1/libreoffice-26.8.1.1.tar.xz',
             'version':'26.8.1.1','size':archive.stat().st_size,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
             'coreCommit':'bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1'}
        pin_path=self.root/'source-pin.json';pin_path.write_text(json.dumps(pin))
        evidence=self.root/'evidence';evidence.mkdir()
        call=f"Set-RuntimeBuildIdentity {quote(runtime)} {quote(archive)} (Get-Content {quote(pin_path)} -Raw|ConvertFrom-Json) {quote('a'*40)} {quote(evidence)}"
        return runtime,archive,pin_path,evidence,pin,call

    def test_runtime_identity_corrects_known_parent_git_or_empty_id_using_authenticated_source_pin(self):
        for original in ('a'*40,'','bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1'):
            with self.subTest(original=original),tempfile.TemporaryDirectory() as folder:
                old_root=self.root;self.root=Path(folder)
                try:
                    runtime,_,_,evidence,pin,call=self.build_identity_fixture(original)
                    before={name:(runtime/'program'/name).read_bytes() for name in ('version.ini','setup.ini')}
                    data=json.loads(self.ps(call+'|ConvertTo-Json -Depth 8 -Compress'))
                    self.assertEqual(pin['coreCommit'],data['expectedBuildId'])
                    self.assertEqual(pin['sha256'],data['sourceArchiveSha256'])
                    for name in before:
                        self.assertEqual(before[name],(evidence/('original-runtime-'+name)).read_bytes())
                        self.assertEqual(before[name].replace(('buildid='+original).encode(),('buildid='+pin['coreCommit']).encode()),
                                         (runtime/'program'/name).read_bytes())
                        self.assertEqual(original,data['files']['program/'+name]['originalBuildId'])
                        self.assertEqual(original!=pin['coreCommit'],data['files']['program/'+name]['corrected'])
                finally:self.root=old_root

    def test_runtime_identity_rejects_unrelated_parent_id_missing_duplicate_or_wrong_section_before_writes(self):
        for mutation in ('unrelated','missing','duplicate','spaced-key','leading-space','section','hidden-section','missing-file','archive-hash','archive-size'):
            with self.subTest(mutation=mutation),tempfile.TemporaryDirectory() as folder:
                old_root=self.root;self.root=Path(folder)
                try:
                    runtime,archive,_,evidence,_,call=self.build_identity_fixture()
                    path=runtime/'program/version.ini'
                    if mutation=='unrelated':path.write_bytes(path.read_bytes().replace(b'a'*40,b'f'*40))
                    elif mutation=='missing':path.write_bytes(b'[Version]\r\nVendor=LibreOffice\r\n')
                    elif mutation=='duplicate':path.write_bytes(path.read_bytes()+b'buildid='+b'a'*40+b'\r\n')
                    elif mutation=='spaced-key':path.write_bytes(path.read_bytes()+b'buildid ='+b'f'*40+b'\r\n')
                    elif mutation=='leading-space':path.write_bytes(path.read_bytes()+b' buildid='+b'f'*40+b'\r\n')
                    elif mutation=='section':path.write_bytes(path.read_bytes().replace(b'[Version]',b'[Other]'))
                    elif mutation=='hidden-section':path.write_bytes(b'[Version]\r\nVendor=LibreOffice\r\n [Other]\r\nbuildid='+b'a'*40+b'\r\n')
                    elif mutation=='missing-file':path.unlink()
                    elif mutation=='archive-hash':archive.write_bytes(b'x'*archive.stat().st_size)
                    else:archive.write_bytes(archive.read_bytes()+b'x')
                    before={p.name:p.read_bytes() for p in (runtime/'program').iterdir()}
                    self.rejected(call)
                    self.assertEqual(before,{p.name:p.read_bytes() for p in (runtime/'program').iterdir()})
                    self.assertEqual([],list(evidence.iterdir()))
                finally:self.root=old_root

    def test_final_runtime_identity_verification_rejects_wrong_missing_or_changed_effective_metadata(self):
        for mutation in ('unchanged','wrong-id','empty-id','missing-file','other-metadata'):
            with self.subTest(mutation=mutation),tempfile.TemporaryDirectory() as folder:
                old_root=self.root;self.root=Path(folder)
                try:
                    runtime,_,pin_path,_,pin,call=self.build_identity_fixture()
                    proof=self.root/'identity.json'
                    self.ps(call+f'|ConvertTo-Json -Depth 8|Set-Content {quote(proof)}')
                    path=runtime/'program/version.ini'
                    if mutation=='wrong-id':path.write_bytes(path.read_bytes().replace(pin['coreCommit'].encode(),b'f'*40))
                    elif mutation=='empty-id':path.write_bytes(path.read_bytes().replace(pin['coreCommit'].encode(),b''))
                    elif mutation=='missing-file':path.unlink()
                    elif mutation=='other-metadata':path.write_bytes(path.read_bytes()+b'other=changed\r\n')
                    check=f"Assert-RuntimeBuildIdentity {quote(runtime)} (Get-Content {quote(pin_path)} -Raw|ConvertFrom-Json) (Get-Content {quote(proof)} -Raw|ConvertFrom-Json)"
                    if mutation=='unchanged':self.ps(check+'|Out-Null')
                    else:self.rejected(check)
                finally:self.root=old_root

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

    def test_completed_fast_command_without_start_time_retains_success_and_truthful_receipt(self):
        # Wait for the real child, then expose the same null metadata observed
        # from fast git. Keep its original Process object and redirected pipes.
        prefix=self.root/'fast-exit'
        self.ps("$original=${function:Get-CommandCreationIdentity}; "
            "function Get-CommandCreationIdentity($Process) { "
            "if(-not $Process.WaitForExit(5000)){throw 'Fixture child did not exit'}; "
            "$Process|Add-Member -MemberType ScriptProperty -Name StartTime -Value {$null} -Force; "
            "& $original $Process }; "
            f"Invoke-LoggedCommand {quote(os.sys.executable)} @('-c','print(\"fast completed output\")') {quote(self.root)} {quote(prefix)}|Out-Null")
        receipt=json.loads((self.root/'fast-exit.command.json').read_text())
        self.assertTrue(receipt['passed']);self.assertEqual(0,receipt['exitCode'])
        self.assertTrue(receipt['directProcessDeathVerified']);self.assertTrue(receipt['pipeDrainComplete'])
        self.assertIsNone(receipt['creationUtcTicks'])
        self.assertEqual('unavailable-after-exit',receipt['creationIdentityStatus'])
        self.assertGreater(receipt['pid'],0)
        self.assertEqual('fast completed output',(self.root/'fast-exit.stdout.log').read_text().strip())

    def pipe_descendant(self,delay):
        child=self.root/'pipe-child.py'
        child.write_text("import os, pathlib, sys, time\n"
            "pathlib.Path(sys.argv[1]).write_text(str(os.getpid()))\n"
            f"time.sleep({delay!r})\nprint('descendant final stdout',flush=True)\n"
            "print('descendant final stderr',file=sys.stderr,flush=True)\n",encoding='utf-8')
        parent=self.root/'pipe-parent.py'
        parent.write_text("import pathlib, subprocess, sys, time\n"
            "subprocess.Popen([sys.executable,sys.argv[1],sys.argv[2]],stdout=sys.stdout,stderr=sys.stderr)\n"
            "deadline=time.monotonic()+2\n"
            "while not pathlib.Path(sys.argv[2]).exists() and time.monotonic()<deadline: time.sleep(.01)\n"
            "print('direct parent exited',flush=True)\n",encoding='utf-8')
        return parent,child,self.root/'descendant.pid'

    def test_exited_parent_cannot_restart_deadline_for_inherited_output_pipes(self):
        parent,child,pidfile=self.pipe_descendant(4)
        prefix=self.root/'inherited'
        self.ps(f"try {{ Invoke-LoggedCommand {quote(os.sys.executable)} @({quote(parent)},{quote(child)},{quote(pidfile)}) {quote(self.root)} {quote(prefix)} -TimeoutMinutes (1.0/60) | Out-Null }} catch {{ }}")
        receipt=json.loads((self.root/'inherited.command.json').read_text())
        self.assertFalse(receipt['passed'],'Direct exit 0 cannot qualify a command whose output EOF missed its deadline')
        self.assertEqual(0,receipt['exitCode'])
        self.assertLess(receipt['elapsedSeconds'],3)
        self.assertFalse(receipt['pipeDrainComplete'])
        self.assertFalse(receipt['forcedTermination'])
        self.assertTrue(receipt['directProcessDeathVerified'])
        self.assertEqual('unproved-after-direct-process-exit',receipt['processTreeCleanup'])
        self.assertIn('direct parent exited',(self.root/'inherited.stdout.log').read_text())

    def test_pipe_eof_inside_original_deadline_preserves_final_descendant_output(self):
        parent,child,pidfile=self.pipe_descendant(.15)
        prefix=self.root/'drained'
        self.ps(f"Invoke-LoggedCommand {quote(os.sys.executable)} @({quote(parent)},{quote(child)},{quote(pidfile)}) {quote(self.root)} {quote(prefix)} -TimeoutMinutes (2.0/60) | Out-Null")
        receipt=json.loads((self.root/'drained.command.json').read_text())
        self.assertTrue(receipt['passed'])
        self.assertTrue(receipt['pipeDrainComplete'])
        self.assertFalse(receipt['forcedTermination'])
        self.assertTrue(receipt['directProcessDeathVerified'])
        self.assertIn('descendant final stdout',(self.root/'drained.stdout.log').read_text())
        self.assertIn('descendant final stderr',(self.root/'drained.stderr.log').read_text())

    def test_running_command_timeout_forces_only_owned_tree_and_preserves_failure(self):
        prefix=self.root/'running'
        self.ps(f"try {{ Invoke-LoggedCommand {quote(os.sys.executable)} @('-c','import time;print(\"before timeout\",flush=True);time.sleep(20)') {quote(self.root)} {quote(prefix)} -TimeoutMinutes (1.0/60) | Out-Null }} catch {{ }}")
        receipt=json.loads((self.root/'running.command.json').read_text())
        self.assertFalse(receipt['passed'])
        self.assertTrue(receipt['forcedTermination'])
        self.assertTrue(receipt['directProcessDeathVerified'])
        self.assertFalse(receipt['pipeDrainComplete'])
        self.assertLess(receipt['elapsedSeconds'],7)
        self.assertIn('before timeout',(self.root/'running.stdout.log').read_text())

    def test_shared_build_budget_is_not_restarted_for_later_commands(self):
        body=f"$script:NativeEngineBuildBudget=New-NativeBuildBudget -MaximumMinutes (1.0/60); "
        for name,delay in (('first',.25),('second',3),('third',0)):
            body+=f"try {{ Invoke-LoggedCommand {quote(os.sys.executable)} @('-c','import time;time.sleep({delay})') {quote(self.root)} {quote(self.root/name)}|Out-Null }} catch {{ }}; "
        self.ps(body)
        receipts=[json.loads((self.root/(name+'.command.json')).read_text()) for name in ('first','second','third')]
        self.assertTrue(receipts[0]['passed'])
        self.assertFalse(receipts[1]['passed'])
        self.assertTrue(receipts[1]['forcedTermination'])
        self.assertLess(receipts[1]['effectiveTimeoutMilliseconds'],800)
        self.assertFalse(receipts[2]['passed'])
        self.assertNotIn('pid',receipts[2],'Expired build budget must reject before launch')
        self.assertIn('shared build deadline',receipts[2]['error'])

    def test_build_deadline_requires_utc_roundtrip_and_cannot_extend_local_maximum(self):
        self.ps("$budget=New-NativeBuildBudget -DeadlineUtc ([DateTime]::UtcNow.AddHours(10).ToString('o')); if($budget.record.timeoutMilliseconds -gt 330*60000){throw 'Extended local maximum'}")
        for deadline in ('2020-01-01T00:00:00.0000000Z','2026-10-17T01:00:00.0000000+01:00','not a timestamp'):
            self.rejected(f"New-NativeBuildBudget -DeadlineUtc {quote(deadline)}")

    def test_expired_build_deadline_retains_failure_before_native_host_or_commands(self):
        output=self.root/'expired-evidence'
        self.ps(f"function Get-NativeBuildHost {{ throw 'Native host must not run after deadline' }}; try {{ Invoke-NativeEngineBuild Full {quote(self.root/'expired-work')} {quote(output)} '' 4 -DeadlineUtc '2020-01-01T00:00:00.0000000Z' }} catch {{ }}")
        receipt=json.loads((output/'source-build-receipt.json').read_text())
        self.assertFalse(receipt['passed']);self.assertFalse(receipt['fullEngineQualified'])
        self.assertEqual('build-time-budget',receipt['stage'])
        self.assertIn('deadline',receipt['error'])
        self.assertNotIn('host',receipt)
        self.assertFalse((output/'OpenGeul-Office-engine-arm64.zip').exists())

    def test_final_deadline_cannot_leave_a_qualified_declaration_in_failure_receipt(self):
        target=self.root/'late-admission.json'
        body="$tokens=$null;$errors=$null;$text=Get-Content -LiteralPath "+quote(SOURCE)+" -Raw; "
        body+="$ast=[Management.Automation.Language.Parser]::ParseInput($text,[ref]$tokens,[ref]$errors); "
        body+="$build=$ast.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Invoke-NativeEngineBuild'},$true); "
        body+="$outer=$build.Body.Find({param($n) $n -is [Management.Automation.Language.TryStatementAst]},$true); "
        body+="$artifact=$outer.Body.Find({param($n) $n -is [Management.Automation.Language.AssignmentStatementAst] -and $n.Left.Extent.Text -eq '$receipt.artifact'},$true); "
        body+="$tail='if($Phase -eq ''Full'') {'+$text.Substring($artifact.Extent.EndOffset,$outer.Body.Extent.EndOffset-1-$artifact.Extent.EndOffset); "
        body+="$caught=$outer.CatchClauses[0].Body.Extent.Text;$caught=$caught.Substring(1,$caught.Length-2); "
        body+="$receipt=[ordered]@{passed=$false;fullEngineQualified=$false;status='failed'};$Phase='Full';$script:checks=0; "
        body+="function Assert-NativeBuildTimeRemaining {$script:checks++;if($script:checks -eq 2){throw 'Observed final shared build deadline'}}; "
        body+="try {& ([scriptblock]::Create('try {'+$tail+'} catch {'+$caught+'}'))} catch {}; "
        body+="if($script:checks -ne 2){throw 'Final deadline boundary was not exercised'}; Write-BuildJson "+quote(target)+" $receipt"
        self.ps(body)
        receipt=json.loads(target.read_text())
        self.assertFalse(receipt['passed']);self.assertFalse(receipt['fullEngineQualified'])
        self.assertEqual('failed',receipt['status'])
        self.assertIn('Observed final shared build deadline',receipt['error'])

    def test_shared_deadline_cancels_stalled_authenticated_download_body(self):
        import hashlib
        import http.server
        import threading
        import time
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(handler):
                handler.send_response(200);handler.send_header('Content-Length','2');handler.end_headers()
                handler.wfile.write(b'a');handler.wfile.flush();time.sleep(3)
                try:handler.wfile.write(b'z')
                except (BrokenPipeError,ConnectionResetError):pass
            def log_message(self,*args):pass
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
        server.daemon_threads=True
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        prefix=self.root/'download';receipt=self.root/'download.json'
        self.ps(f"$script:NativeEngineBuildBudget=New-NativeBuildBudget -MaximumMinutes (1.0/60); try {{ Get-AuthenticatedDownload 'http://127.0.0.1:{server.server_port}/fixture' {quote(prefix)} 2 SHA256 {quote(hashlib.sha256(b'az').hexdigest())} {quote(receipt)}|Out-Null }} catch {{ }}")
        data=json.loads(receipt.read_text())
        self.assertEqual('failed',data['status'],'Headers alone must not remove the deadline from the streamed body')
        self.assertLess(data['elapsedSeconds'],2)
        self.assertEqual(b'a',prefix.read_bytes(),'Partial original bytes remain available after cancellation')

    def test_workflow_establishes_deadline_before_checkout_outside_workspace(self):
        import textwrap
        import datetime
        workflow=SOURCE.parents[2]/'.github/workflows/office-native-engine.yml'
        text=workflow.read_text()
        first=text.split('        run: |\n',1)[1].split('      - name: Preserve exact source bytes',1)[0]
        runner=self.root/'runner-temp';runner.mkdir();github_env=self.root/'github-env'
        self.ps(f"$env:RUNNER_TEMP={quote(runner)};$env:GITHUB_ENV={quote(github_env)};$env:GITHUB_RUN_ID='123';$env:GITHUB_RUN_ATTEMPT='1';\n"+textwrap.dedent(first))
        values=dict(line.split('=',1) for line in github_env.read_text().splitlines())
        path=Path(values['OPENGEUL_ENGINE_BUDGET_RECEIPT'])
        self.assertEqual(runner,path.parent.parent)
        receipt=json.loads(path.read_text());self.assertEqual('first-user-step',receipt['origin'])
        self.assertFalse(receipt['runnerSetupIncluded']);self.assertEqual(30,receipt['nominalReserveMinutes'])
        start=datetime.datetime.fromisoformat(receipt['startedUtc'].replace('Z','+00:00'))
        end=datetime.datetime.fromisoformat(receipt['deadlineUtc'].replace('Z','+00:00'))
        self.assertEqual(330*60,(end-start).total_seconds())
        self.assertEqual(receipt['deadlineUtc'],values['OPENGEUL_ENGINE_BUILD_DEADLINE_UTC'])
        self.assertIn('-DeadlineUtc $env:OPENGEUL_ENGINE_BUILD_DEADLINE_UTC',text)
        self.assertIn('Copy-Item -LiteralPath $env:OPENGEUL_ENGINE_BUDGET_RECEIPT',text)

    def test_engine_archive_uses_bounded_command_and_preserves_exact_runtime_bytes(self):
        import zipfile
        runtime=self.root/'runtime';runtime.mkdir();(runtime/'nested').mkdir()
        (runtime/'nested/한글.txt').write_bytes(b'exact native runtime fixture')
        evidence=self.root/'zip-evidence';evidence.mkdir();archive=evidence/'engine.zip'
        self.ps(f"$script:NativeEngineBuildBudget=New-NativeBuildBudget -MaximumMinutes (5.0/60); Write-NativeEngineArchive {quote(runtime)} {quote(archive)} {quote(evidence)}")
        with zipfile.ZipFile(archive) as package:
            self.assertEqual(['nested/한글.txt'],package.namelist())
            self.assertEqual(b'exact native runtime fixture',package.read('nested/한글.txt'))
        receipt=json.loads((evidence/'package-native-engine.command.json').read_text())
        self.assertTrue(receipt['passed']);self.assertTrue(receipt['pipeDrainComplete'])
        self.assertLessEqual(receipt['effectiveTimeoutMilliseconds'],5000)
        self.assertEqual(str(runtime),receipt['arguments'][-2])
        self.assertEqual(str(archive),receipt['arguments'][-1])

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
        names=('concrt140.dll','msvcp140.dll','msvcp140_1.dll','msvcp140_2.dll','msvcp140_atomic_wait.dll','msvcp140_codecvt_ids.dll','vcruntime140.dll','vcruntime140_threads.dll')
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
        self.assertEqual('arm64',plan['architecture'])
        self.assertEqual(8,len(plan['files']))
        self.assertEqual(str(source),plan['sourceDirectory'])
        self.assertEqual('Microsoft.VC143.CRT',plan['redistFamily'])
        self.assertEqual('14.50.12345',plan['compilerToolsVersion'])
        self.assertEqual(set(names),{row['name'] for row in plan['files']})
        self.rejected(self.crt_mock()+f"Get-AppLocalCrtPlan {quote(tools)} 'v143'")

    def test_architecture_family_preserves_x64_default_and_native_arm64_exact_eight(self):
        raw=self.ps("@{default=@(Get-CrtNames);x64=@(Get-CrtNames 'x64');arm64=@(Get-CrtNames 'arm64')}|ConvertTo-Json -Compress")
        families=json.loads(raw)
        self.assertEqual(families['default'],families['x64'])
        self.assertEqual(9,len(families['x64']));self.assertEqual(8,len(families['arm64']))
        self.assertIn('vcruntime140_1.dll',families['x64'])
        self.assertNotIn('vcruntime140_1.dll',families['arm64'])
        self.rejected("Get-CrtNames 'x86'")

    def test_native_crt_preflight_does_not_require_or_stage_x64_one(self):
        tools,source,names=self.crt_fixture()
        (source/'vcruntime140_1.dll').write_bytes(b'foreign x64 evidence, never native')
        raw=self.ps(self.crt_mock()+f"Get-AppLocalCrtPlan {quote(tools)} 'v145'|ConvertTo-Json -Depth 12 -Compress")
        self.assertEqual(set(names),{row['name'] for row in json.loads(raw)['files']})
        self.rejected(self.crt_mock()+f"Assert-CrtFile {quote(source/'vcruntime140_1.dll')} '14.50.12345.0'")

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

    def test_native_crt_stage_copies_only_eight_authentic_bytes_and_redistribution_terms(self):
        tools,source,names=self.crt_fixture()
        (source/'arbitrary.dll').write_bytes(b'never copy')
        program=self.root/'instdir/program';program.mkdir(parents=True)
        terms=self.root/'terms.html';terms.write_text('Preserved Microsoft Visual Studio2026 redistribution terms')
        raw=self.ps(self.crt_mock()+f"$plan=Get-AppLocalCrtPlan {quote(tools)} 'v145'; Install-AppLocalCrt $plan {quote(program)} {quote(terms)}|ConvertTo-Json -Depth 12 -Compress")
        receipt=json.loads(raw)
        self.assertEqual('arm64',receipt['architecture'])
        self.assertEqual(8,len(receipt['files']))
        self.assertEqual(set(names),{p.name for p in program.iterdir()})
        for name in names:self.assertEqual((source/name).read_bytes(),(program/name).read_bytes())
        self.assertTrue((program.parent/'share/readme/Microsoft-VC145-redistribution.html').is_file())

    def test_native_crt_stage_rejects_extra_one_before_copying_native_family(self):
        tools,source,names=self.crt_fixture()
        program=self.root/'instdir/program';program.mkdir(parents=True)
        foreign=program/'vcruntime140_1.dll';foreign.write_bytes(b'preserve foreign bytes')
        terms=self.root/'terms.html';terms.write_text('Owned terms snapshot')
        self.rejected(self.crt_mock()+f"$plan=Get-AppLocalCrtPlan {quote(tools)} 'v145';Install-AppLocalCrt $plan {quote(program)} {quote(terms)}")
        self.assertEqual([foreign],list(program.iterdir()))
        self.assertEqual(b'preserve foreign bytes',foreign.read_bytes())

    def test_native_crt_stage_rejects_legacy_versioned_runtime_before_copy(self):
        tools,source,names=self.crt_fixture()
        program=self.root/'instdir/program';program.mkdir(parents=True)
        legacy=program/'msvcr120.dll';legacy.write_bytes(b'preserve legacy runtime')
        terms=self.root/'terms.html';terms.write_text('Owned terms snapshot')
        self.rejected(self.crt_mock()+f"$plan=Get-AppLocalCrtPlan {quote(tools)} 'v145';Install-AppLocalCrt $plan {quote(program)} {quote(terms)}")
        self.assertEqual([legacy],list(program.iterdir()))

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

    def test_native_import_closure_function_runs_source_bound_helper_with_exact_architecture(self):
        from suite.tests.test_crt import CrtImportClosureTests
        from suite.tests.test_payload import pe
        runtime=self.root/'runtime';runtime.mkdir()
        CrtImportClosureTests().fixture(runtime)
        (runtime/'program/soffice.bin').write_bytes(pe(0xaa64))
        evidence=self.root/'evidence';evidence.mkdir()
        repo=SOURCE.parents[2]
        raw=self.ps(f"Invoke-CrtImportAudit {quote(os.sys.executable)} {quote(repo)} {quote(runtime)} {quote(evidence)}|ConvertTo-Json -Depth 12 -Compress")
        proof=json.loads(raw.splitlines()[-1])
        self.assertTrue(proof['passed']);self.assertEqual('arm64',proof['architecture'])
        self.assertEqual(9,proof['checkedPeCount'])
        self.assertTrue((evidence/'crt-import-closure.json').is_file())
        self.assertTrue((evidence/'crt-import-closure.command.json').is_file())

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

    def test_isql_verify_quotes_reserved_result_alias_without_changing_columns(self):
        sql=json.loads(self.ps("Get-IsqlSql -DatabasePath 'C:\\owned\\proof.fdb'|ConvertTo-Json -Compress"))
        aliases=re.findall(r'\bAS\s+("[^"]+"|[A-Z_]+)',sql['verify'])
        self.assertEqual(['ROW_COUNT','TOTAL','ROW_ONE','ROW_THREE'],[name.strip('"') for name in aliases])
        # Firebird 3.0.13 keywords.cpp marks ROW_COUNT reserved; parse.y's
        # symbol_item_alias_name accepts SYMBOL, not that context-variable token.
        # A double-quoted identifier becomes SYMBOL and keeps SET LIST's label.
        for alias in aliases:
            if alias.strip('"') in {'ROW_COUNT'}:
                self.assertEqual('"'+alias.strip('"')+'"',alias,'Reserved Firebird result alias must be delimited')
        self.assertIn('COUNT(*) AS ',sql['verify'])
        self.assertIn('SUM(AMOUNT) AS TOTAL',sql['verify'])
        self.assertIn('WHEN ID=1 AND AMOUNT=55 THEN 1 ELSE 0 END) AS ROW_ONE',sql['verify'])
        self.assertIn('WHEN ID=3 AND AMOUNT=13 THEN 1 ELSE 0 END) AS ROW_THREE',sql['verify'])
        self.assertIn('FROM OPENGEUL_ARM64_PROBE;',sql['verify'])

    def test_full_qualification_rejects_missing_base_native_or_crud_semantics(self):
        report=self.root/'base.json'
        good={'schemaVersion':1,'passed':True,'guiVerified':False,'nativeProcesses':[{'processMachine':0,'nativeMachine':43620,'role':'uno-python'},{'processMachine':0,'nativeMachine':43620,'role':'uno-host','jobOwned':True,'phase':'create'},{'processMachine':0,'nativeMachine':43620,'role':'uno-host','jobOwned':True,'phase':'reopen'}],'rows':[{'id':1,'text':'Engine-OpenGeul-base 한글','amount':42}],'independentReopenVerified':True}
        report.write_text(json.dumps(good))
        self.ps(f"Assert-BaseProof {quote(report)}|Out-Null")
        for field,value in [('passed',False),('rows',[]),('independentReopenVerified',False),('nativeProcesses',[{'processMachine':34404,'nativeMachine':43620}]),('nativeProcesses',[{'processMachine':0,'nativeMachine':43620,'role':'soffice-launcher'}]*3)]:
            report.write_text(json.dumps(dict(good,**{field:value})))
            self.rejected(f"Assert-BaseProof {quote(report)}")


if __name__=='__main__':unittest.main()
