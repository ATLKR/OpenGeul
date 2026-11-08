"""Offline Writer acquisition checks real PowerShell against synthetic HTTP/ZIP bytes."""
import copy
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

from suite.tests import test_fetch_source_engine as fetch


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/fetch-writer-server-observer.ps1'
PWSH = shutil.which('pwsh')
ENGINE = 'OpenGeul-Office-engine-arm64-writer-server-observer.zip'
RECEIPT = 'writer-server-observer-source-build-receipt.json'
MARKERS = ('writer-server-observer-diagnostic.json', 'program/opengeul-writer-server-observer-diagnostic.json')
CORE = 'bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1'


def child_environment(root, *, windows=False, read=os.environ.get):
    profile = root / 'profile'; profile.mkdir(exist_ok=True)
    temporary = root / 'temp'; temporary.mkdir(exist_ok=True)
    result = dict(GH_TOKEN=fetch.SECRET, GITHUB_TOKEN=fetch.SECRET, HOME=str(profile), USERPROFILE=str(profile),
                  TEMP=str(temporary), TMP=str(temporary), LOCALAPPDATA=str(profile), APPDATA=str(profile),
                  XDG_CACHE_HOME=str(profile), XDG_CONFIG_HOME=str(profile), XDG_DATA_HOME=str(profile),
                  POWERSHELL_TELEMETRY_OPTOUT='1', DOTNET_CLI_TELEMETRY_OPTOUT='1')
    if windows:
        for name in ('SystemRoot', 'WINDIR'):
            value = read(name)
            if type(value) is str and 0 < len(value) <= 32767 and not any(ord(c) < 32 for c in value):
                result[name] = value
    return result


def arm_dll(machine=0xaa64):
    data = bytearray(512); data[:2] = b'MZ'; struct.pack_into('<I', data, 60, 128)
    data[128:132] = b'PE\0\0'; struct.pack_into('<H', data, 132, machine)
    struct.pack_into('<H', data, 150, 0x2000); struct.pack_into('<H', data, 152, 0x20b)
    return bytes(data)


class ChildEnvironmentTests(unittest.TestCase):
    def test_only_two_bounded_windows_values_can_enter_literal_fixture_environment(self):
        with tempfile.TemporaryDirectory() as folder:
            seen = []
            def read(name):
                seen.append(name)
                return 'C:\\Windows' if name == 'SystemRoot' else 'bad\x00value'
            environment = child_environment(Path(folder), windows=True, read=read)
            self.assertEqual(seen, ['SystemRoot', 'WINDIR'])
            self.assertEqual(environment['SystemRoot'], 'C:\\Windows')
            self.assertNotIn('WINDIR', environment); self.assertNotIn('PATH', environment)
            self.assertEqual(environment['GH_TOKEN'], 'fetch-test-secret-do-not-record')
            self.assertTrue(Path(environment['HOME']).is_relative_to(Path(folder)))


@unittest.skipUnless(PWSH, 'Existing PowerShell runtime unavailable')
class WriterObserverFetchTests(unittest.TestCase):
    def save(self, root, name, value):
        (root / (name + '.json')).write_text(json.dumps(value), encoding='utf-8')

    def fixture(self, root):
        libraries = [('program/UAccCOM.dll', arm_dll()), ('program/winaccessibility.dll', arm_dll())]
        marker = dict(schemaVersion=1, family='writer-server-observer-diagnostic', kind='writer-server-observer-diagnostic',
                      sourceCommit='a'*40, sourceTree='b'*40, coreCommit=CORE, sourceLockSha256='c'*64,
                      patchSha256='d'*64, wireSchema=dict(path='wire-schema.json', bytes=7855, sha256='e'*64),
                      ipcVersion=1, sinkAbiVersion=2, mappingBytes=131328, descriptorSchemaVersion=1,
                      requiredRebuiltLibraries=['UAccCOM', 'winaccessibility'],
                      binaries=[dict(path=name, bytes=len(data), sha256=fetch.sha(data), machine=0xaa64) for name, data in libraries],
                      fullEngineQualified=False, acceptanceEligible=False, guiVerified=False)
        raw = json.dumps(marker).encode()
        entries = [(name, data, 0) for name, data in libraries] + [(name, raw, 0) for name in MARKERS]
        engine = fetch.zip_bytes(entries)
        hooks = dict(schemaVersion=1, kind='writer-server-observer-diagnostic-source', target='windows-arm64',
                     coreCommit=CORE, lockSha256='c'*64, passed=True, fullEngineQualified=False,
                     acceptanceEligible=False, guiVerified=False, ipcVersion=1, sinkAbiVersion=2,
                     mappingBytes=131328, descriptorSchemaVersion=1,
                     requiredRebuiltLibraries=['UAccCOM', 'winaccessibility'],
                     patch=dict(path='source.patch', bytes=9937, sha256='d'*64), wireSchema=copy.deepcopy(marker['wireSchema']))
        proof = dict(schemaVersion=1, kind='native-office-engine-writer-server-observer-diagnostic', phase='Full',
                     architecture='arm64', stage='complete', status='native-engine-writer-server-observer-diagnostic-built',
                     passed=True, fullEngineQualified=False, acceptanceEligible=False, guiVerified=False,
                     sourceCommit='a'*40, sourceTree='b'*40, sourceRun=123, runAttempt=1, sourceLockSha256='c'*64,
                     sourcePin=dict(coreCommit=CORE), host=dict(isWindows=True, processMachine=0, nativeMachine=0xaa64),
                     writerServerObserverSourceHooks=hooks, writerServerObserverRuntime=copy.deepcopy(marker),
                     artifact=dict(path='producer-private-output.zip', size=len(engine), sha256=fetch.sha(engine)))
        lock = dict(schemaVersion=1, kind='writer-server-observer-diagnostic-input', architecture='arm64',
                    repository='ATLKR/OpenGeul', repositoryId=1405493151, sourceCommit='a'*40, sourceTree='b'*40,
                    runId=123, runAttempt=1, artifactId=456, sourceLockSha256='c'*64, coreCommit=CORE,
                    patchSha256='d'*64, wireSchemaSha256='e'*64)
        artifact = dict(id=456, name='opengeul-native-arm64-writer-server-observer-123-1', expired=False,
                        workflow_run=dict(id=123, repository_id=1405493151, head_repository_id=1405493151,
                                          head_sha='a'*40, head_branch='work/opengeul-office-native-writer-observer'))
        repository = dict(id=1405493151, full_name='ATLKR/OpenGeul', private=False)
        run = dict(id=123, run_attempt=1, head_sha='a'*40, status='completed', conclusion='success', event='push',
                   head_branch='work/opengeul-office-native-writer-observer', path='.github/workflows/office-native-engine.yml',
                   actor=dict(login='ATLKR', id=65988341, type='User'), repository=repository, head_repository=copy.deepcopy(repository))
        jobs = dict(total_count=1, jobs=[dict(id=999, run_id=123, head_sha='a'*40,
                    name='native-firebird-and-office', status='completed', conclusion='success')])
        scenario = dict(redirectStatus=302, blobStatus=200, throwDownload=False, unknownLength=False,
                        location='https://blob.example.test/file?sig='+fetch.SIGNED_SECRET)
        for name, value in (('run', run), ('jobs', jobs), ('scenario', scenario)):
            self.save(root, name, value)
        self.pack(root, lock, artifact, proof, engine)
        return lock, artifact, proof, entries, marker

    def pack(self, root, lock, artifact, proof, engine, *, outer_entries=None):
        proof['artifact'].update(size=len(engine), sha256=fetch.sha(engine))
        raw = json.dumps(proof).encode()
        outer = fetch.zip_bytes(outer_entries if outer_entries is not None else [(ENGINE, engine, 0), (RECEIPT, raw, 0)])
        (root / 'outer.zip').write_bytes(outer)
        lock.update(artifactSha256=fetch.sha(outer), artifactSize=len(outer))
        artifact.update(digest='sha256:'+fetch.sha(outer), size_in_bytes=len(outer))
        self.save(root, 'lock', lock); self.save(root, 'artifact', artifact)

    def execute(self, root, *, seconds=1200, extra=''):
        self.assertTrue(SCRIPT.is_file(), 'A distinct Writer observer fetcher is required')
        scripts = root / 'scripts'; scripts.mkdir(exist_ok=True)
        shutil.copyfile(SCRIPT, scripts / SCRIPT.name)
        shutil.copyfile(fetch.ROOT/'suite/scripts/fetch-source-engine.ps1', scripts/'fetch-source-engine.ps1')
        harness = fetch.HARNESS.replace('Invoke-SourceEngineFetch', 'Invoke-WriterServerObserverFetch').replace('SourceLockPath=', 'DiagnosticLockPath=')
        harness = harness.replace('. $Script\n', ". $Script -Output (Join-Path $Root 'output') -TimeoutSeconds 23\n"
            "if ($Output -cne (Join-Path $Root 'output') -or $TimeoutSeconds -ne 23) { throw 'Imported parameters changed.' }\n"+extra+'\n')
        harness = harness.replace('var response=new HttpResponseMessage(HttpStatusCode.OK);',
            'if(options.TryGetProperty("delayEndpoint",out var delayed) && delayed.GetString()==endpoint) await Task.Delay(5000,token);\n'
            'var response=new HttpResponseMessage(options.TryGetProperty("metadataStatus",out var code) && endpoint!="blob" && endpoint!="redirect"?(HttpStatusCode)code.GetInt32():HttpStatusCode.OK);')
        (root/'harness.ps1').write_text(harness, encoding='utf-8')
        process = subprocess.run([PWSH, '-NoLogo', '-NoProfile', '-File', str(root/'harness.ps1'), '-Root', str(root),
                    '-Script', str(scripts/SCRIPT.name), '-FetchTimeoutSeconds', str(seconds)],
                    env=child_environment(root, windows=os.name == 'nt'), capture_output=True, text=True, timeout=30)
        output = process.stdout + process.stderr
        self.assertNotIn(fetch.SECRET, output); self.assertNotIn(fetch.SIGNED_SECRET, output)
        for path in (root/'output').glob('*.json'):
            self.assertNotIn(fetch.SECRET, path.read_text()); self.assertNotIn(fetch.SIGNED_SECRET, path.read_text())
        events = json.loads((root/'events.json').read_text()) if (root/'events.json').exists() else []
        return process, events

    def test_authenticated_outer_joins_both_markers_and_native_arm_dll_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); lock, _, _, _, _=self.fixture(root)
            process, events=self.execute(root)
            self.assertEqual(process.returncode, 0, process.stdout+process.stderr)
            audit=json.loads((root/'output/writer-server-observer-download.json').read_text())
            self.assertTrue(audit['passed']); self.assertEqual(audit['sourceTree'], 'b'*40)
            self.assertEqual(audit['artifactSha256'], lock['artifactSha256'])
            self.assertEqual(audit['engineSha256'], fetch.sha((root/'output'/ENGINE).read_bytes()))
            self.assertEqual(audit['receiptSha256'], fetch.sha((root/'output'/RECEIPT).read_bytes()))
            self.assertEqual([e['endpoint'] for e in events], ['artifact','run','jobs','redirect','blob'])
            self.assertEqual([e['authenticated'] for e in events], [True,True,True,True,False])
            self.assertNotIn('producer-private', json.dumps(audit))

    def test_external_lock_rejects_missing_tree_extra_abi_and_wrong_scalar_types_before_http(self):
        for key, value in [('sourceTree', None), ('sinkAbiVersion', 2), ('artifactSize', True), ('wireSchemaSha256', 'bad')]:
            with self.subTest(key=key), tempfile.TemporaryDirectory() as folder:
                root=Path(folder); lock, _, _, _, _=self.fixture(root)
                if value is None: del lock[key]
                else: lock[key]=value
                self.save(root,'lock',lock); process, events=self.execute(root)
                self.assertNotEqual(process.returncode, 0); self.assertEqual(events, [])

    def test_server_owner_branch_job_and_family_are_checked_before_download(self):
        cases=[('run','head_branch','main'),('run','event','workflow_dispatch'),('run','run_attempt',2),
               ('run.actor','id',1),('run.repository','private',True),('run','head_sha','f'*40),
               ('artifact','name','opengeul-native-arm64-calc-dispatch-123-1'),('artifact','digest','sha256:'+'f'*64),
               ('jobs.jobs.0','name','other-job'),('jobs.jobs.0','conclusion','failure')]
        for target,key,value in cases:
            with self.subTest(target=target,key=key), tempfile.TemporaryDirectory() as folder:
                root=Path(folder); self.fixture(root); name,*parts=target.split('.')
                document=json.loads((root/(name+'.json')).read_text()); item=document
                for part in parts: item=item[int(part)] if isinstance(item,list) else item[part]
                item[key]=value; self.save(root,name,document)
                process,events=self.execute(root); self.assertNotEqual(process.returncode,0)
                self.assertFalse(any(e['endpoint'] in ('redirect','blob') for e in events))

    def test_outer_hash_rejects_before_receipt_or_inner_zip_extraction(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); self.fixture(root); data=bytearray((root/'outer.zip').read_bytes()); data[-1]^=1; (root/'outer.zip').write_bytes(data)
            process,_=self.execute(root); self.assertNotEqual(process.returncode,0)
            self.assertFalse((root/'output'/RECEIPT).exists()); self.assertFalse((root/'output'/ENGINE).exists())

    def test_receipt_flags_tree_source_and_abi_cannot_self_authorize(self):
        cases=[('sourceTree','f'*40),('sourceLockSha256','f'*64),('fullEngineQualified',True),
               ('writerServerObserverSourceHooks.sinkAbiVersion',True),
               ('writerServerObserverSourceHooks.patch.sha256','f'*64),
               ('writerServerObserverRuntime.sourceTree','f'*40),('writerServerObserverRuntime.acceptanceEligible',True)]
        for dotted,value in cases:
            with self.subTest(field=dotted), tempfile.TemporaryDirectory() as folder:
                root=Path(folder); lock,artifact,proof,entries,_=self.fixture(root); item=proof; parts=dotted.split('.')
                for part in parts[:-1]: item=item[part]
                item[parts[-1]]=value; self.pack(root,lock,artifact,proof,fetch.zip_bytes(entries))
                process,_=self.execute(root); self.assertNotEqual(process.returncode,0)

    def test_inner_markers_must_match_each_other_receipt_and_external_schema_pins(self):
        for mode in ('missing','different','wire','alias','duplicate'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as folder:
                root=Path(folder); lock,artifact,proof,entries,marker=self.fixture(root)
                if mode=='missing': entries=entries[:-1]
                elif mode=='different': entries[-1]=(MARKERS[1],json.dumps(marker,indent=2).encode(),0)
                elif mode=='wire':
                    marker['wireSchema']['sha256']='f'*64; raw=json.dumps(marker).encode(); entries=entries[:2]+[(p,raw,0) for p in MARKERS]
                elif mode=='alias': entries.append(('PROGRAM/UACCCOM.DLL',arm_dll(),0))
                else: entries.append(entries[-1])
                self.pack(root,lock,artifact,proof,fetch.zip_bytes(entries)); process,_=self.execute(root)
                self.assertNotEqual(process.returncode,0)

    def test_inner_dll_bytes_and_headers_must_join_both_native_descriptors(self):
        for mode in ('hash','foreign','missing','symlink'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as folder:
                root=Path(folder); lock,artifact,proof,entries,marker=self.fixture(root)
                if mode=='hash':
                    changed=bytearray(arm_dll()); changed[-1]^=1
                    entries[0]=(entries[0][0],bytes(changed),0)
                elif mode=='foreign':
                    data=arm_dll(0x8664); marker['binaries'][0].update(bytes=len(data),sha256=fetch.sha(data))
                    proof['writerServerObserverRuntime']=copy.deepcopy(marker); raw=json.dumps(marker).encode()
                    entries[0]=(entries[0][0],data,0); entries[-2:]=[(p,raw,0) for p in MARKERS]
                elif mode=='missing': entries=entries[1:]
                else: entries[0]=(entries[0][0],entries[0][1],0o120777<<16)
                self.pack(root,lock,artifact,proof,fetch.zip_bytes(entries)); process,_=self.execute(root)
                self.assertNotEqual(process.returncode,0)

    def test_unsafe_outer_paths_and_unknown_redirects_are_not_fallback_downloads(self):
        for mode in ('outer-path','redirect','denied'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as folder:
                root=Path(folder); lock,artifact,proof,entries,_=self.fixture(root)
                if mode=='outer-path': self.pack(root,lock,artifact,proof,fetch.zip_bytes(entries),outer_entries=[('../'+ENGINE,b'x',0),(RECEIPT,b'{}',0)])
                else:
                    scenario=json.loads((root/'scenario.json').read_text())
                    scenario['location']='http://blob.example.test/file' if mode=='redirect' else scenario['location']
                    if mode=='denied': scenario['metadataStatus']=403
                    self.save(root,'scenario',scenario)
                process,events=self.execute(root); self.assertNotEqual(process.returncode,0)
                if mode!='outer-path': self.assertFalse(any(e['endpoint']=='blob' for e in events))
                if mode=='denied': self.assertEqual([e['endpoint'] for e in events],['artifact'])

    def test_one_cancellation_deadline_covers_metadata_and_sanitized_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); self.fixture(root); scenario=json.loads((root/'scenario.json').read_text()); scenario['delayEndpoint']='jobs'; self.save(root,'scenario',scenario)
            process,events=self.execute(root,seconds=1); self.assertNotEqual(process.returncode,0)
            audit=json.loads((root/'output/writer-server-observer-download.json').read_text())
            self.assertTrue(audit['deadlineExceeded']); self.assertFalse(audit['passed'])
            self.assertEqual([e['endpoint'] for e in events],['artifact','run','jobs'])

    def test_audit_finalization_failure_cannot_replace_sanitized_primary_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); self.fixture(root); scenario=json.loads((root/'scenario.json').read_text()); scenario['throwDownload']=True; self.save(root,'scenario',scenario)
            extra="function Write-EngineFetchJson { param($Path,$Value) if($Path.EndsWith('writer-server-observer-download.json')){throw 'unsafe finalizer replacement'}; $Value|ConvertTo-Json -Depth 15|Set-Content -LiteralPath $Path }"
            process,_=self.execute(root,extra=extra); self.assertNotEqual(process.returncode,0)
            self.assertIn('Writer observer fetch failed at authenticated-outer-zip',process.stderr)
            self.assertNotIn('unsafe finalizer replacement',process.stderr)


if __name__ == '__main__':
    unittest.main()
