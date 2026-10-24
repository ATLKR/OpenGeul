"""Authenticated artifact fetching uses fake HTTP clients and real ZIP bytes."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import unittest
import warnings
import zipfile

ROOT = Path(__file__).resolve().parents[2]
PWSH = shutil.which('pwsh')
SECRET = 'fetch-test-secret-do-not-record'
SIGNED_SECRET = 'signed-test-secret-do-not-record'
ENGINE = 'OpenGeul-Office-engine-arm64.zip'
RECEIPT = 'source-build-receipt.json'

HARNESS = r'''
param([string]$Root,[string]$Script,[int]$FetchTimeoutSeconds=1200)
$ErrorActionPreference='Stop'
Add-Type @'
using System;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;
using System.Text.Json;
using System.Collections.Generic;
public sealed class EngineProxySpy : IWebProxy {
 public static int Calls;
 public ICredentials Credentials { get; set; }
 public bool IsBypassed(Uri destination) { Interlocked.Increment(ref Calls);return true; }
 public Uri GetProxy(Uri destination) { Interlocked.Increment(ref Calls);return destination; }
}
public sealed class EngineFakeHttp : HttpMessageHandler {
 public static List<object> Events = new List<object>();
 string root; bool api;
 // Real transport is exclusively to the owned 127.0.0.1 fixture, never a system proxy.
 HttpClient local = new HttpClient(new HttpClientHandler { AllowAutoRedirect=false, UseProxy=false });
 public EngineFakeHttp(string root, bool api) { this.root=root;this.api=api; }
 protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken token) {
  string path=request.RequestUri.AbsolutePath;
  string endpoint=api?(path.EndsWith("/zip")?"redirect":path.Contains("/artifacts/")?"artifact":"run"):"blob";
  Events.Add(new { endpoint=endpoint, authenticated=request.Headers.Authorization!=null });
  if(api && (request.Headers.Authorization==null || request.Headers.Authorization.ToString()!="Bearer fetch-test-secret-do-not-record")) throw new Exception("API requires authentication");
  if(!api && request.Headers.Authorization!=null) throw new Exception("Signed download leaked Authorization");
  using var scenario=JsonDocument.Parse(File.ReadAllText(Path.Combine(root,"scenario.json")));
  var options=scenario.RootElement;
  if(options.TryGetProperty("loopbackOrigin",out var loopback)) {
   using var forwarded=new HttpRequestMessage(HttpMethod.Get,loopback.GetString()+"/"+endpoint);
   return await local.SendAsync(forwarded,HttpCompletionOption.ResponseHeadersRead,token);
  }
  if(endpoint=="blob" && options.GetProperty("throwDownload").GetBoolean()) throw new HttpRequestException("https://blob.example.test/file?sig=signed-test-secret-do-not-record");
  var response=new HttpResponseMessage(HttpStatusCode.OK);
  if(endpoint=="redirect") {
   response.StatusCode=(HttpStatusCode)options.GetProperty("redirectStatus").GetInt32();
   response.Headers.Location=new Uri(options.GetProperty("location").GetString());
  } else if(endpoint=="blob") {
   response.StatusCode=(HttpStatusCode)options.GetProperty("blobStatus").GetInt32();
   var bytes=File.ReadAllBytes(Path.Combine(root,"outer.zip"));
   response.Content=options.GetProperty("unknownLength").GetBoolean()?(HttpContent)new EngineUnknownLength(bytes):new ByteArrayContent(bytes);
  } else response.Content=new StringContent(File.ReadAllText(Path.Combine(root,endpoint+".json")));
  return response;
 }
 protected override void Dispose(bool disposing) { if(disposing)local.Dispose();base.Dispose(disposing); }
}
public sealed class EngineUnknownLength : HttpContent {
 byte[] bytes;
 public EngineUnknownLength(byte[] bytes) { this.bytes=bytes; }
 protected override bool TryComputeLength(out long length) { length=0;return false; }
 protected override Task SerializeToStreamAsync(Stream stream, TransportContext context) { return stream.WriteAsync(bytes,0,bytes.Length); }
 protected override Task<Stream> CreateContentReadStreamAsync() { return Task.FromResult<Stream>(new MemoryStream(bytes)); }
}
'@
[IO.File]::WriteAllText((Join-Path $Root 'harness-ready'), 'compiled')
. $Script
$scenario=Get-Content (Join-Path $Root 'scenario.json') -Raw|ConvertFrom-Json
# This process belongs only to the fixture; never inspect or change host proxy settings.
if($scenario.proxySpy) { [Net.Http.HttpClient]::DefaultProxy=[EngineProxySpy]::new() }
$api=[Net.Http.HttpClient]::new([EngineFakeHttp]::new($Root,$true))
$download=[Net.Http.HttpClient]::new([EngineFakeHttp]::new($Root,$false))
try {
 $parameters=@{SourceLockPath=(Join-Path $Root 'lock.json');Output=(Join-Path $Root 'output');ApiClient=$api;DownloadClient=$download}
 if((Get-Command Invoke-SourceEngineFetch).Parameters.ContainsKey('TimeoutSeconds')) {$parameters.TimeoutSeconds=$FetchTimeoutSeconds}
 Invoke-SourceEngineFetch @parameters
} finally {
 ConvertTo-Json -InputObject @([EngineFakeHttp]::Events) -Depth 5|Set-Content (Join-Path $Root 'events.json')
 @{calls=[EngineProxySpy]::Calls}|ConvertTo-Json|Set-Content (Join-Path $Root 'proxy-calls.json')
 $api.Dispose();$download.Dispose()
}
'''


def sha(data):
    return hashlib.sha256(data).hexdigest()


def zip_bytes(entries):
    buffer = io.BytesIO()
    with warnings.catch_warnings(), zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        warnings.filterwarnings('ignore', message='Duplicate name:')
        for name, data, attributes in entries:
            info = zipfile.ZipInfo('fixture')
            info.filename = info.orig_filename = name
            info.external_attr = attributes
            archive.writestr(info, data)
    return buffer.getvalue()


@contextmanager
def loopback_responses(root, *, stalled=None, header_delay=0):
    """Actual local HTTP headers/body; original authenticated URLs stay in the fake handler."""
    release=threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            endpoint=self.path.lstrip('/')
            try:
                if header_delay:release.wait(header_delay)
                if endpoint=='redirect':
                    self.send_response(302);self.send_header('Location','https://blob.example.test/file?sig='+SIGNED_SECRET)
                    data=b''
                else:
                    self.send_response(200)
                    data=(root/('outer.zip' if endpoint=='blob' else endpoint+'.json')).read_bytes()
                self.send_header('Content-Length',str(len(data)));self.end_headers()
                if endpoint==stalled and data:
                    self.wfile.write(data[:1]);self.wfile.flush()
                    release.wait(4)
                    self.wfile.write(data[1:])
                elif data:self.wfile.write(data)
            except (BrokenPipeError,ConnectionResetError):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
    worker=threading.Thread(target=lambda:server.serve_forever(poll_interval=.05),daemon=True);worker.start()
    try:yield 'http://127.0.0.1:'+str(server.server_port)
    finally:
        release.set();server.shutdown();server.server_close();worker.join(timeout=2)


@unittest.skipUnless(PWSH, 'PowerShell runtime unavailable')
class FetchSourceEngineTests(unittest.TestCase):
    def fixture(self, root, entries=None, *, engine_payload=b'actual engine fixture'):
        engine = zip_bytes([('program/soffice.bin', engine_payload, 0)])
        receipt = b'{"schemaVersion":1,"boundedFixture":true}\n'
        outer = zip_bytes(entries if entries is not None else [(ENGINE, engine, 0), (RECEIPT, receipt, 0)])
        (root/'outer.zip').write_bytes(outer)
        lock = {'schemaVersion': 1, 'architecture': 'arm64', 'runtime': {
            'format': 'source-built-zip', 'size': len(engine), 'sha256': sha(engine),
            'sourceBuild': {'receiptSha256': sha(receipt), 'sourceCommit': 'a'*40,
                            'runId': 123, 'artifactId': 456, 'artifactSha256': sha(outer),
                            'patchManifestSha256': 'b'*64, 'artifactSize': len(outer)}}}
        artifact = {'id': 456, 'name': 'opengeul-native-arm64-engine-123-1', 'size_in_bytes': len(outer),
                    'digest': 'sha256:'+sha(outer), 'expired': False,
                    'workflow_run': {'id': 123, 'repository_id': 789, 'head_repository_id': 789, 'head_sha': 'a'*40}}
        run = {'id': 123, 'run_attempt': 1, 'head_sha': 'a'*40, 'status': 'completed', 'conclusion': 'success',
               'path': '.github/workflows/office-native-engine.yml',
               'repository': {'id': 789, 'full_name': 'ATLKR/OpenGeul'},
               'head_repository': {'id': 789, 'full_name': 'ATLKR/OpenGeul'}}
        scenario = {'redirectStatus': 302, 'blobStatus': 200, 'throwDownload': False, 'unknownLength': False,
                    'location': 'https://blob.example.test/file?sig='+SIGNED_SECRET}
        for name, value in (('lock', lock), ('artifact', artifact), ('run', run), ('scenario', scenario)):
            self.save(root, name, value)
        return lock, artifact, run, scenario, engine, receipt

    def save(self, root, name, value):
        (root/(name+'.json')).write_text(json.dumps(value), encoding='utf-8')

    def run_fetch(self, root, token=True, token_name='GH_TOKEN', timeout_seconds=1200):
        script = ROOT/'suite/scripts/fetch-source-engine.ps1'
        self.assertTrue(script.is_file(), 'Authenticated source-engine fetch script is required')
        harness = root/'harness.ps1'; harness.write_text(HARNESS, encoding='utf-8')
        env = dict(os.environ)
        env.pop('GH_TOKEN', None); env.pop('GITHUB_TOKEN', None)
        if token: env[token_name] = SECRET
        result = subprocess.run([PWSH, '-NoProfile', '-File', str(harness), '-Root', str(root),
                                 '-Script', str(script), '-FetchTimeoutSeconds', str(timeout_seconds)], capture_output=True, text=True, timeout=30, env=env)
        output = result.stdout+result.stderr
        self.assertTrue((root/'harness-ready').is_file(), output)
        self.assertNotIn(SECRET, output); self.assertNotIn(SIGNED_SECRET, output)
        for path in (root/'output').glob('*.json'):
            self.assertNotIn(SECRET, path.read_text()); self.assertNotIn(SIGNED_SECRET, path.read_text())
        events = json.loads((root/'events.json').read_text()) if (root/'events.json').exists() else []
        return result, events if isinstance(events, list) else [events]

    def test_fetch_authenticates_metadata_downloads_without_auth_and_preserves_exact_inner_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); lock, _, _, _, engine, receipt = self.fixture(root)
            result, events = self.run_fetch(root)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertEqual((root/'output'/ENGINE).read_bytes(), engine)
            self.assertEqual((root/'output'/RECEIPT).read_bytes(), receipt)
            self.assertEqual([event['endpoint'] for event in events], ['artifact', 'run', 'redirect', 'blob'])
            self.assertEqual([event['authenticated'] for event in events], [True, True, True, False])
            audit = json.loads((root/'output/source-engine-download.json').read_text())
            self.assertTrue(audit['passed'])
            self.assertEqual(1200,audit['timeoutSeconds']);self.assertFalse(audit['deadlineExceeded'])
            self.assertEqual(audit['artifactSha256'], lock['runtime']['sourceBuild']['artifactSha256'])
            self.assertEqual(audit['engineSha256'], lock['runtime']['sha256'])
            metadata = json.loads((root/'output/artifact-server-metadata.json').read_text())
            self.assertEqual(metadata['artifact']['id'], 456)
            self.assertEqual(metadata['run']['head_sha'], 'a'*40)

    def test_loopback_fixture_never_consults_process_default_proxy(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);_,_,_,scenario,engine,receipt=self.fixture(root)
            with loopback_responses(root) as origin:
                scenario.update(loopbackOrigin=origin,proxySpy=True);self.save(root,'scenario',scenario)
                result,events=self.run_fetch(root)
            self.assertEqual(0,result.returncode,result.stdout+result.stderr)
            self.assertEqual(['artifact','run','redirect','blob'],[event['endpoint'] for event in events])
            self.assertEqual(0,json.loads((root/'proxy-calls.json').read_text())['calls'],
                             'Owned loopback requests must not perform ambient proxy discovery')
            self.assertEqual(engine,(root/'output'/ENGINE).read_bytes())
            self.assertEqual(receipt,(root/'output'/RECEIPT).read_bytes())

    def test_actual_stalled_metadata_and_artifact_bodies_cancel_with_sanitized_audit(self):
        for endpoint in ('artifact','blob'):
            with self.subTest(endpoint=endpoint),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);_,_,_,scenario,_,_=self.fixture(root)
                with loopback_responses(root,stalled=endpoint) as origin:
                    scenario['loopbackOrigin']=origin;self.save(root,'scenario',scenario)
                    result,events=self.run_fetch(root,timeout_seconds=1)
                self.assertNotEqual(0,result.returncode,'A body stall must not outlive the original fetch budget')
                audit=json.loads((root/'output/source-engine-download.json').read_text())
                detail=json.dumps(dict(audit=audit,events=events))
                self.assertFalse(audit['passed'],detail);self.assertTrue(audit['deadlineExceeded'],detail)
                self.assertEqual(1,audit['timeoutSeconds'],detail);self.assertLess(audit['elapsedSeconds'],3,detail)
                self.assertEqual('github-metadata' if endpoint=='artifact' else 'authenticated-outer-zip',audit['stage'],detail)
                self.assertFalse((root/'output'/ENGINE).exists())
                partial=root/'output/github-artifact.zip'
                if endpoint=='blob':
                    self.assertTrue(partial.is_file());self.assertGreater(partial.stat().st_size,0)
                    self.assertLess(partial.stat().st_size,(root/'outer.zip').stat().st_size)
                else:self.assertFalse(partial.exists())

    def test_original_deadline_is_shared_across_metadata_and_download_headers(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);_,_,_,scenario,_,_=self.fixture(root)
            with loopback_responses(root,header_delay=.6) as origin:
                scenario['loopbackOrigin']=origin;self.save(root,'scenario',scenario)
                result,events=self.run_fetch(root,timeout_seconds=2)
            self.assertNotEqual(0,result.returncode,'Four fresh per-request budgets must not replace the original total deadline')
            self.assertGreaterEqual(len(events),3)
            audit=json.loads((root/'output/source-engine-download.json').read_text())
            detail=json.dumps(dict(audit=audit,events=events))
            self.assertFalse(audit['passed'],detail);self.assertTrue(audit['deadlineExceeded'],detail)
            self.assertEqual(2,audit['timeoutSeconds'],detail);self.assertLess(audit['elapsedSeconds'],4,detail)
            self.assertEqual('authenticated-outer-zip',audit['stage'],detail)
            self.assertFalse((root/'output'/ENGINE).exists())

    def test_timeout_override_is_positive_and_never_exceeds_production_cap(self):
        for seconds in (0,-1,1201):
            with self.subTest(seconds=seconds),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);self.fixture(root)
                result,events=self.run_fetch(root,timeout_seconds=seconds)
                self.assertNotEqual(0,result.returncode)
                self.assertEqual([],events)
                self.assertFalse((root/'output').exists())

    def test_multichunk_outer_and_inner_bytes_keep_exact_incremental_hashes(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            _,_,_,_,engine,receipt=self.fixture(root,engine_payload=bytes(range(256))*10000)
            self.assertGreater(len(engine),2*1024*1024)
            result,_=self.run_fetch(root)
            self.assertEqual(0,result.returncode,result.stdout+result.stderr)
            self.assertEqual(engine,(root/'output'/ENGINE).read_bytes())
            self.assertEqual(receipt,(root/'output'/RECEIPT).read_bytes())
            self.assertTrue(json.loads((root/'output/source-engine-download.json').read_text())['passed'])

    def test_fixed_cli_options_reach_token_gate_without_creating_output_or_using_http(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); self.fixture(root)
            env = dict(os.environ); env.pop('GH_TOKEN', None); env.pop('GITHUB_TOKEN', None)
            result = subprocess.run([PWSH, '-NoProfile', '-File', str(ROOT/'suite/scripts/fetch-source-engine.ps1'),
                                     '-SourceLockPath', str(root/'lock.json'), '-Output', str(root/'output')],
                                    capture_output=True, text=True, env=env, timeout=30)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('GH_TOKEN or GITHUB_TOKEN', result.stdout+result.stderr)
            self.assertFalse((root/'output').exists())

    def test_metadata_must_match_external_artifact_run_repo_source_digest_size_and_success(self):
        cases = [('artifact', 'id', 999), ('artifact', 'digest', 'sha256:'+'f'*64),
                 ('artifact', 'size_in_bytes', 1), ('artifact', 'expired', True),
                 ('artifact', 'name', 'evidence'), ('artifact.workflow_run', 'id', 999),
                 ('artifact.workflow_run', 'head_sha', 'f'*40),
                 ('artifact.workflow_run', 'repository_id', 1),
                 ('artifact.workflow_run', 'head_repository_id', 1),
                 ('artifact.workflow_run', 'id', '123'),
                 ('artifact.workflow_run', 'repository_id', '789'),
                 ('artifact.workflow_run', 'head_repository_id', '789'),
                 ('run', 'id', 999), ('run', 'head_sha', 'f'*40), ('run', 'status', 'in_progress'),
                 ('run', 'conclusion', 'failure'), ('run', 'path', '.github/workflows/other.yml'),
                 ('run.repository', 'full_name', 'attacker/OpenGeul'),
                 ('run.head_repository', 'id', '789'),
                 ('run.head_repository', 'full_name', 'attacker/OpenGeul')]
        for target, key, value in cases:
            with self.subTest(target=target, key=key), tempfile.TemporaryDirectory() as folder:
                root = Path(folder); _, artifact, run, _, _, _ = self.fixture(root)
                selected = artifact if target.startswith('artifact') else run
                for part in target.split('.')[1:]: selected = selected[part]
                selected[key] = value
                self.save(root, target.split('.')[0], artifact if target.startswith('artifact') else run)
                result, events = self.run_fetch(root)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('blob', [event['endpoint'] for event in events])
                self.assertFalse((root/'output'/ENGINE).exists())

    def test_download_bounds_hashes_redirect_origin_and_errors_fail_without_secrets(self):
        for mutation in ('outer-hash', 'outer-size', 'outer-stream-cap', 'inner-hash', 'receipt-hash',
                         'redirect', 'insecure', 'userinfo', 'metadata-error', 'http-error'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as folder:
                root = Path(folder); lock, _, _, scenario, _, _ = self.fixture(root)
                if mutation == 'outer-hash': (root/'outer.zip').write_bytes((root/'outer.zip').read_bytes()[:-1]+b'x')
                elif mutation == 'outer-size': (root/'outer.zip').write_bytes((root/'outer.zip').read_bytes()+b'x')
                elif mutation == 'outer-stream-cap':
                    (root/'outer.zip').write_bytes((root/'outer.zip').read_bytes()+b'x')
                    scenario['unknownLength'] = True
                elif mutation == 'inner-hash': lock['runtime']['sha256'] = 'f'*64
                elif mutation == 'receipt-hash': lock['runtime']['sourceBuild']['receiptSha256'] = 'f'*64
                elif mutation == 'redirect': scenario['redirectStatus'] = 200
                elif mutation == 'insecure': scenario['location'] = 'http://blob.example.test/file?sig='+SIGNED_SECRET
                elif mutation == 'userinfo': scenario['location'] = 'https://user:password@blob.example.test/file?sig='+SIGNED_SECRET
                elif mutation == 'metadata-error': (root/'artifact.json').write_text(SIGNED_SECRET)
                else: scenario['throwDownload'] = True
                self.save(root, 'lock', lock); self.save(root, 'scenario', scenario)
                result, _ = self.run_fetch(root)
                self.assertNotEqual(result.returncode, 0)
                audit = json.loads((root/'output/source-engine-download.json').read_text())
                self.assertFalse(audit['passed'])

    def test_outer_zip_only_allows_the_exact_two_regular_root_files(self):
        for name, attributes in (('../'+RECEIPT, 0), ('folder/'+RECEIPT, 0), (RECEIPT.upper(), 0),
                                 (RECEIPT+'\x00hidden', 0), (RECEIPT, 0o120777 << 16), (RECEIPT, 0x400),
                                 (ENGINE, 0)):
            with self.subTest(name=name, attributes=attributes), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                engine = zip_bytes([('program/soffice.bin', b'actual engine fixture', 0)])
                self.fixture(root, [(ENGINE, engine, 0), (name, b'forged', attributes)])
                result, _ = self.run_fetch(root)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((root/'output'/ENGINE).exists())

    def test_optional_outer_size_uses_authenticated_metadata_and_github_token_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); lock, artifact, _, _, _, _ = self.fixture(root)
            del lock['runtime']['sourceBuild']['artifactSize']
            artifact['archive_download_url'] = 'https://blob.example.test/file?sig='+SIGNED_SECRET
            self.save(root, 'lock', lock); self.save(root, 'artifact', artifact)
            result, _ = self.run_fetch(root, token_name='GITHUB_TOKEN')
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)

    def test_archive_member_count_receipt_bound_and_metadata_stream_bound_fail_closed(self):
        for mutation in ('count', 'receipt-bound', 'metadata-bound'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                if mutation == 'count': self.fixture(root, [(ENGINE, b'x', 0), (RECEIPT, b'x', 0), ('extra', b'x', 0)])
                elif mutation == 'receipt-bound':
                    engine = zip_bytes([('program/soffice.bin', b'actual engine fixture', 0)])
                    self.fixture(root, [(ENGINE, engine, 0), (RECEIPT, b'x'*(8388608+1), 0)])
                else:
                    self.fixture(root)
                    (root/'artifact.json').write_text(json.dumps({'oversize': 'x'*1048576}))
                result, _ = self.run_fetch(root)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((root/'output'/ENGINE).exists())

    def test_missing_token_or_existing_output_fails_before_http(self):
        for existing in (False, True):
            with self.subTest(existing=existing), tempfile.TemporaryDirectory() as folder:
                root = Path(folder); self.fixture(root)
                if existing:
                    (root/'output').mkdir(); (root/'output/keep').write_bytes(b'keep')
                result, events = self.run_fetch(root, token=existing)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(events, [])
                if existing: self.assertEqual((root/'output/keep').read_bytes(), b'keep')

    def test_linked_lock_or_output_is_rejected_before_http_and_preserves_target(self):
        for linked in ('lock', 'output'):
            with self.subTest(linked=linked), tempfile.TemporaryDirectory() as folder:
                root = Path(folder); self.fixture(root)
                target = root/'preserved'; target.mkdir(); (target/'keep').write_bytes(b'keep')
                if linked == 'lock':
                    (root/'lock.json').rename(target/'lock.json')
                    path = root/'lock.json'; destination = target/'lock.json'
                else: path = root/'output'; destination = target
                try: path.symlink_to(destination, target_is_directory=linked == 'output')
                except OSError: self.skipTest('Symlink creation unavailable')
                result, events = self.run_fetch(root)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(events, [])
                self.assertEqual((target/'keep').read_bytes(), b'keep')


if __name__ == '__main__': unittest.main()
