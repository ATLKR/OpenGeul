"""Store 원본과 실제 설치/WACK receipt의 변조·소스/아키텍처 혼합 회귀."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'e2e')]
import release_pair
import store_qualification as qual
from buildkit import manifest, package_version
from store_package import STORE_IDENTITY, REQUIRED_JOBS, authorize_release
from windows_arch import component_artifact_name, machine_for
from wack_result import inspect
import store_screenshot

spec = importlib.util.spec_from_file_location('pair_fixture', ROOT / 'tests/test_release_pair.py')
fixtures = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixtures)


class StoreScreenshotImportTests(unittest.TestCase):
    def test_receipt_helper_import_needs_no_gui_dependencies(self):
        # The policy runners install only the CI parser. A clean interpreter
        # must inspect screenshot provenance without loading the UI driver.
        code = (
            "import sys; sys.path[:0]=['scripts','e2e']; import store_screenshot; "
            "assert 'driver' not in sys.modules and 'playwright' not in sys.modules; "
            "assert store_screenshot.capture_expected_sha({'formatVersion':2,"
            "'architectures':{'x64':{'runtimeSha256':{'OpenGeul.exe':'expected'}}}})=='expected'"
        )
        result = subprocess.run([sys.executable, '-S', '-c', code], cwd=ROOT,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)


class StoreQualificationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ReleasePairTests(); self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.version = self.fixture.version
        self.package_version = self.fixture.package_version
        self.fixture.env['GITHUB_RUN_ID'] = '38181680763'
        for arch in ('x64', 'arm64'):
            def bind_run(provenance):
                provenance['runId'] = '38181680763'
                components = provenance['windowsComponents']; components['runId'] = '38181680763'
                for role, record in components['components'].items():
                    record['artifactName'] = component_artifact_name(role, '38181680763', arch)
            self.fixture.mutate_prov(arch, bind_run)
            installation_path = self.fixture.wacks[arch] / 'install.json'
            installation = json.loads(installation_path.read_bytes())
            cli = self.fixture.runtime[arch]['Tools/rhwp.exe']
            installation['mcp'] = fixtures.installed_proof(arch, hashlib.sha256(cli).hexdigest(),
                installation['packageFullName'], 'a' * 40, '38181680763', '2', len(cli))
            self.fixture.write_json(installation_path, installation)
        self.fixture.rebind_split()
        self.fixture.assemble(); self.source = self.fixture.output
        self.root = self.fixture.root; self.store = self.root / 'store'; self.store.mkdir()
        self.outputs = {a: self.root / ('qualification-' + a) for a in ('x64', 'arm64')}
        self.env = {'GITHUB_REPOSITORY': 'ATLKR/OpenGeul', 'GITHUB_SHA': 'b' * 40,
            'GITHUB_RUN_ID': '9999', 'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_JOB': 'store-wack'}
        self.evidence = {}; entries = {}
        helper = ROOT / 'e2e/native_architecture.py'
        self.helper_sha = hashlib.sha256(helper.read_bytes()).hexdigest() if helper.exists() else '9' * 64
        for arch in ('x64', 'arm64'):
            source_msix = next(p for p in self.fixture.packages[arch].iterdir() if p.suffix == '.msix')
            with zipfile.ZipFile(source_msix) as archive:
                runtime = {n: archive.read(n) for n in archive.namelist()}
            raw_manifest = manifest(STORE_IDENTITY, self.version, arch).encode()
            runtime['AppxManifest.xml'] = raw_manifest
            name = f'OpenGeul_{self.package_version}_{arch}_store-unsigned.msix'; package = self.store / name
            self.fixture.zip(package, runtime); (self.store / ('AppxManifest-' + arch + '.xml')).write_bytes(raw_manifest)
            hashes = {n: hashlib.sha256(raw).hexdigest() for n, raw in runtime.items()
                if n not in {'AppxManifest.xml', 'AppxBlockMap.xml', '[Content_Types].xml'}}
            entries[arch] = {'sourceMsix': source_msix.name, 'sourceMsixSha256': hashlib.sha256(source_msix.read_bytes()).hexdigest(),
                'package': name, 'sha256': hashlib.sha256(package.read_bytes()).hexdigest(),
                'manifest': 'AppxManifest-' + arch + '.xml', 'runtimeSha256': hashes}
            wack = self.root / ('store-evidence-' + arch); wack.mkdir(); self.evidence[arch] = wack
            for p in self.fixture.wacks[arch].iterdir(): (wack / p.name).write_bytes(p.read_bytes())
            xml = (wack / 'wack.xml').read_text().replace('AllenLabs.OpenGeul.Development', STORE_IDENTITY['name']).replace('CN=OpenGeul Development', STORE_IDENTITY['publisher'])
            (wack / 'wack.xml').write_text(xml, encoding='utf-8')
            self.fixture.write_json(wack / 'wack.json', inspect(wack / 'wack.xml', STORE_IDENTITY['name'], self.package_version, 0))
            full_name = f"{STORE_IDENTITY['name']}_{self.package_version}_{arch}__{release_pair._publisher_id(STORE_IDENTITY['publisher'])}"
            install = json.loads((wack / 'install.json').read_bytes()); install.update(originalSha256=entries[arch]['sha256'], publisher=STORE_IDENTITY['publisher'], packageFullName=full_name, fileTypes=['.hwp', '.hwpx'])
            install['mcp'] = fixtures.installed_proof(arch, hashes['Tools/rhwp.exe'], full_name,
                'b' * 40, '9999', '1', len(runtime['Tools/rhwp.exe']))
            self.fixture.write_json(wack / 'install.json', install)
            pid = 100 if arch == 'x64' else 200
            native = {'architecture': arch, 'processId': pid, 'imagePath': f'C:\\Program Files\\WindowsApps\\{full_name}\\OpenGeul.exe',
                'peMachine': machine_for(arch), 'processMachine': 0, 'nativeMachine': machine_for(arch),
                'native': True, 'runningAtInspection': True, 'packageFullName': full_name,
                'sha256': hashes['OpenGeul.exe'], 'bytes': len(runtime['OpenGeul.exe']),
                'helperSha256': self.helper_sha, 'sourceCommit': 'b' * 40, 'sourceRun': '9999', 'runAttempt': '1',
                'controller': {'processId': 10, 'processMachine': 0, 'architecture': arch, 'native': True}}
            native['webview2Native'] = {'rootProcessId': pid, 'architecture': arch, 'helperSha256': self.helper_sha,
                'processes': [{'processId': pid + 1, 'parentProcessId': pid, 'imagePath': 'C:\\Edge\\msedgewebview2.exe',
                    'peMachine': machine_for(arch), 'processMachine': 0, 'nativeMachine': machine_for(arch),
                    'sha256': '8' * 64, 'bytes': 256, 'runningAtInspection': True}]}
            self.fixture.write_json(wack / 'installed-launch.json', {'success': True, 'architecture': arch, 'processId': pid,
                'packageFullName': full_name, 'executable': native['imagePath'], 'windowTitle': 'OpenGeul', 'nativeArchitecture': native})
            cli = dict(native); cli.pop('webview2Native'); cli.update(processId=pid + 2, imagePath=f'C:\\Program Files\\WindowsApps\\{full_name}\\Tools\\rhwp.exe',
                sha256=hashes['Tools/rhwp.exe'], bytes=len(runtime['Tools/rhwp.exe']), runningAtInspection=False)
            self.fixture.write_json(wack / 'installed-cli.json', {'success': True, 'packageFullName': full_name, 'exitCode': 0,
                'helpBytes': 10, 'helpSha256': hashlib.sha256(b'rhwp help\n').hexdigest(), 'nativeArchitecture': cli, 'mcp': install['mcp']})
        (self.store / 'source-provenance.json').write_bytes((self.source / 'provenance.json').read_bytes())
        self.details = {'formatVersion': 2, 'storeAppId': '9PJH0T3PHRMF', 'identity': dict(STORE_IDENTITY), 'version': self.version,
            'sourceRelease': f'https://github.com/ATLKR/OpenGeul/releases/tag/v{self.version}-dev.68.2', 'sourceReleaseId': 200,
            'sourceCommit': 'a' * 40, 'sourceRunId': '38181680763', 'sourceRunAttempt': '2',
            'sourceAssetFingerprintSha256': release_pair.source_fingerprint(self.source),
            'repackageCommit': 'b' * 40, 'repackageRunId': '9999', 'architectures': entries,
            'unsigned': True, 'storeCertified': False}
        self.fixture.write_json(self.store / 'store-provenance.json', self.details); self.fixture.sums(self.store)
        self.rebind_store_split()

    def rebind_store_split(self):
        import native_split_fixture
        import native_wack_transport
        arch='arm64';wack=self.evidence[arch];entry=self.details['architectures'][arch]
        installation=json.loads((wack/'install.json').read_bytes())
        binding={key:self.env[value] for key,value in [('repository','GITHUB_REPOSITORY'),('commit','GITHUB_SHA'),('runId','GITHUB_RUN_ID'),('runAttempt','GITHUB_RUN_ATTEMPT')]}
        split,installation,join,_=native_split_fixture.make_split(self.store/entry['package'],installation,binding,'store',native_wack_transport._files(self.store))
        self.fixture.write_json(wack/'install.json',installation)
        for name,key in [('installed-launch.json','launch'),('installed-cli.json','cli')]:
            import base64
            (wack/name).write_bytes(base64.b64decode(split['native']['originalEvidence'][name]['rawBase64']))
        context=json.loads((wack/'wack-context.json').read_bytes());context.update(inputPackageSha256=installation['signedTestPackageSha256'],nativeSignedJoin=join)
        self.fixture.write_json(wack/'wack-context.json',context)

    def collect(self, arch):
        env=dict(self.env,GITHUB_JOB='store-wack' if arch=='arm64' else 'store-wack-x64')
        return qual.collect(arch, self.store, self.evidence[arch], self.outputs[arch], env=env)

    def verify(self):
        return qual.verify(self.store, self.source, self.outputs['x64'], self.outputs['arm64'], env=dict(self.env, GITHUB_JOB='qualify'))

    def rejected_collect(self, arch='arm64'):
        with self.assertRaises(ValueError): self.collect(arch)
        self.assertFalse(self.outputs[arch].exists())

    def change_json(self, path, change):
        value = json.loads(path.read_bytes()); change(value); self.fixture.write_json(path, value)

    def test_select_preserves_one_actual_store_msix_and_manifest(self):
        out = self.root / 'selected'; qual.select('arm64', self.store, out, env=self.env)
        self.assertTrue(out.is_dir())
        self.assertEqual({p.name for p in out.iterdir()}, {self.details['architectures']['arm64']['package'], 'AppxManifest.xml'})
        self.assertEqual((out / 'AppxManifest.xml').read_bytes(), (self.store / 'AppxManifest-arm64.xml').read_bytes())
        with self.assertRaises(ValueError): qual.select('arm64', self.store, out, env=self.env)

    def test_dev_tag_number_is_independent_of_source_run_id_and_api_authorized(self):
        source = release_pair.verify_pair(self.source)
        self.assertNotEqual(self.details['sourceRunId'], '68')
        run = {'id': 38181680763, 'run_number': 68, 'run_attempt': 2, 'head_sha': 'a' * 40,
            'repository': {'full_name': 'ATLKR/OpenGeul', 'private': False},
            'head_repository': {'full_name': 'ATLKR/OpenGeul', 'private': False}, 'path': '.github/workflows/msix.yml',
            'event': 'push', 'status': 'completed', 'conclusion': 'success'}
        jobs = [{'name': name, 'status': 'completed', 'conclusion': 'success', 'run_attempt': 2,
            'run_id': run['id'], 'head_sha': run['head_sha']} for name in REQUIRED_JOBS]
        tag = self.details['sourceRelease'].rsplit('/', 1)[1]
        authorize_release(tag, source, run, run['head_sha'], jobs)
        qual.select('x64', self.store, self.root / 'dev-selected', env=self.env)
        for changed in (f'v{self.version}-dev.38181680763.2', f'v{self.version}-dev.69.2', f'v{self.version}-dev.68.1'):
            with self.subTest(tag=changed), self.assertRaises(ValueError):
                authorize_release(changed, source, run, run['head_sha'], jobs)

    def test_canonical_stable_source_url_remains_accepted(self):
        self.details['sourceRelease'] = f'https://github.com/ATLKR/OpenGeul/releases/tag/v{self.version}'
        self.fixture.write_json(self.store / 'store-provenance.json', self.details); self.fixture.sums(self.store)
        self.rebind_store_split();self.collect('x64'); self.collect('arm64'); self.verify()

    def test_noncanonical_or_unbound_source_urls_fail_before_selection(self):
        base = 'https://github.com/ATLKR/OpenGeul/releases/tag/v'
        wrong_version = '.'.join([*self.version.split('.')[:2], str(int(self.version.split('.')[2]) + 1)])
        urls = [base + self.version + '-dev.68.1', base + wrong_version + '-dev.68.2', base + self.version + '-dev.068.2',
            base + self.version + '-dev.0.2', base + self.version + '-dev.68.02', base + self.version + '-dev.68.2?draft=true',
            base + '0' + self.version + '-dev.68.2', base.replace('ATLKR/OpenGeul', 'outsider/OpenGeul') + self.version + '-dev.68.2']
        for i, url in enumerate(urls):
            with self.subTest(url=url):
                self.details['sourceRelease'] = url
                self.fixture.write_json(self.store / 'store-provenance.json', self.details); self.fixture.sums(self.store)
                output = self.root / ('rejected-url-' + str(i))
                with self.assertRaises(ValueError): qual.select('arm64', self.store, output, env=self.env)
                self.assertFalse(output.exists())

    def test_both_store_identity_full_wack_proofs_append_without_original_changes(self):
        original = {p.name: p.read_bytes() for p in self.store.iterdir()}
        self.collect('x64'); self.collect('arm64'); self.verify()
        receipt = self.store / 'store-qualification.json'; self.assertTrue(receipt.is_file())
        result = json.loads(receipt.read_bytes()); self.assertEqual(set(result['architectures']), {'x64', 'arm64'})
        for name, raw in original.items():
            if name == 'SHA256SUMS.txt': self.assertTrue((self.store / name).read_bytes().startswith(raw))
            else: self.assertEqual((self.store / name).read_bytes(), raw)
        self.assertEqual(result['sourceCommit'], 'a' * 40); self.assertEqual(result['repackageCommit'], 'b' * 40)
        self.assertFalse(result['storeCertified'])
        self.assertTrue(result['architectures']['arm64']['fullWackPassed'])

    def test_wrong_store_identity_is_rejected(self):
        self.details['identity']['name'] = 'other'; self.fixture.write_json(self.store / 'store-provenance.json', self.details); self.fixture.sums(self.store)
        self.rejected_collect()

    def test_store_full_wack_without_installed_mcp_proof_is_rejected(self):
        self.change_json(self.evidence['arm64']/'install.json',lambda d:d.pop('mcp',None))
        self.rejected_collect()

    def test_store_installed_cli_mcp_is_mandatory_and_equal_to_installation(self):
        path = self.evidence['arm64'] / 'installed-cli.json'
        original = path.read_bytes()
        for mutate in (lambda d:d.pop('mcp'),lambda d:d['mcp']['stressFixture'].update(sha256='0'*64)):
            with self.subTest(mutate=mutate):
                path.write_bytes(original);self.change_json(path,mutate);self.rejected_collect()

    def test_both_store_mcp_proofs_cannot_reuse_source_execution_or_false_case(self):
        paths = [self.evidence['arm64']/name for name in ('install.json','installed-cli.json')]
        original = {p:p.read_bytes() for p in paths}
        for mutate in (lambda p:p.update(sourceCommit='a'*40,sourceRun='38181680763',runAttempt='2'),
                lambda p:next(row for row in p['cases'] if row['name']=='password-hwpx-correct')['checks'].update(ciphertextUnchanged=False),
                lambda p:p['workerIsolation']['worker'].update(sha256='0'*64)):
            with self.subTest(mutate=mutate):
                for path in paths:
                    path.write_bytes(original[path]);self.change_json(path,lambda d:mutate(d['mcp']))
                self.rejected_collect()

    def test_store_collect_requires_session_and_workspace_checks_in_each_actual_mcp_receipt(self):
        paths=[self.evidence['x64']/name for name in ('install.json','installed-cli.json')]
        originals={p:p.read_bytes() for p in paths}
        for target in paths:
            for name,field in (('session-save','independentXmlPassed'),('workspace-journal','saveDigestsMatch')):
                for mutation in ('missing','false'):
                    with self.subTest(receipt=target.name,case=name,mutation=mutation):
                        for path,raw in originals.items():path.write_bytes(raw)
                        def change(value):
                            checks=next(row for row in value['mcp']['cases'] if row['name']==name)['checks']
                            if mutation=='missing':checks.pop(field)
                            else:checks[field]=False
                        self.change_json(target,change)
                        with self.assertRaisesRegex(ValueError,'MCP (판정|필수)'):self.collect('x64')
                        self.assertFalse(self.outputs['x64'].exists())

    def test_store_verify_rechecks_new_checks_even_when_both_raw_mcp_and_receipt_hashes_are_rebuilt(self):
        self.collect('x64');self.collect('arm64');folder=self.outputs['x64']
        paths=[folder/name for name in ('install-x64.json','installed-cli-x64.json')]
        originals={p:p.read_bytes() for p in paths};receipt_path=folder/'qualification.json';receipt_original=receipt_path.read_bytes()
        for name,field in (('session-save','independentXmlPassed'),('workspace-journal','saveDigestsMatch')):
            for mutation in ('missing','false'):
                with self.subTest(case=name,mutation=mutation):
                    receipt=json.loads(receipt_original)
                    for path,raw in originals.items():
                        value=json.loads(raw);checks=next(row for row in value['mcp']['cases'] if row['name']==name)['checks']
                        if mutation=='missing':checks.pop(field)
                        else:checks[field]=False
                        self.fixture.write_json(path,value)
                        receipt['raw'][path.name]={'size':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
                    self.fixture.write_json(receipt_path,receipt)
                    with self.assertRaisesRegex(ValueError,'MCP (판정|필수)'):self.verify()
                    self.assertFalse((self.store/'store-qualification.json').exists())
        for path,raw in originals.items():path.write_bytes(raw)
        receipt_path.write_bytes(receipt_original);self.verify()

    def test_qualified_inspector_rejects_mcp_tampering_even_after_all_hashes_rebuilt(self):
        self.collect('x64'); self.collect('arm64'); self.verify()
        receipt_path = self.store / 'store-qualification.json'
        receipt = json.loads(receipt_path.read_bytes())
        for name in ('install-arm64.json','installed-cli-arm64.json'):
            self.change_json(self.store/name,lambda d:d['mcp']['workerIsolation'].update(forcedTermination=True))
            receipt['architectures']['arm64']['raw'][name] = {'size':(self.store/name).stat().st_size,
                'sha256':hashlib.sha256((self.store/name).read_bytes()).hexdigest()}
        self.fixture.write_json(receipt_path,receipt)
        prefix = (self.store/'SHA256SUMS.txt').read_bytes()[:receipt['originalChecksumsBytes']]
        originals = {line.split('  ',1)[1] for line in prefix.decode().splitlines()}
        (self.store/'SHA256SUMS.txt').write_bytes(prefix + ''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n'
            for p in sorted(self.store.iterdir()) if p.name not in originals | {'SHA256SUMS.txt'}).encode())
        # 원본 prefix/raw hashes/SUMS를 모두 맞춰도 실제 MCP 판정은 재검사되어야 한다.
        qual.verify_checksums(self.store)
        with self.assertRaises(ValueError):qual.inspect_qualified(self.store,self.source,env=self.env)

    def test_wrong_store_architecture_is_rejected(self):
        self.details['architectures']['arm64']['package'] = self.details['architectures']['x64']['package']
        self.fixture.write_json(self.store / 'store-provenance.json', self.details); self.fixture.sums(self.store); self.rejected_collect()

    def test_optional_wack_warning_is_rejected(self):
        w = self.evidence['arm64']; xml = (w / 'wack.xml').read_text().replace('OVERALL_RESULT="PASS"', 'OVERALL_RESULT="WARNING"').replace('<RESULT>PASS</RESULT></TEST></REPORT>', '<RESULT>FAIL</RESULT></TEST></REPORT>')
        (w / 'wack.xml').write_text(xml); self.fixture.write_json(w / 'wack.json', inspect(w / 'wack.xml', STORE_IDENTITY['name'], self.package_version, 0)); self.rejected_collect()

    def test_stale_signed_context_is_rejected(self):
        self.change_json(self.evidence['arm64'] / 'wack-context.json', lambda d: d.update(inputPackageSha256='0' * 64)); self.rejected_collect()

    def test_native_product_under_emulation_is_rejected(self):
        self.change_json(self.evidence['arm64'] / 'installed-launch.json', lambda d: d['nativeArchitecture'].update(processMachine=34404)); self.rejected_collect()

    def test_stale_native_store_execution_is_rejected(self):
        self.change_json(self.evidence['arm64'] / 'installed-cli.json', lambda d: d['nativeArchitecture'].update(sourceRun='8888')); self.rejected_collect()

    def test_webview_must_be_owned_native_descendant(self):
        self.change_json(self.evidence['arm64'] / 'installed-launch.json', lambda d: d['nativeArchitecture']['webview2Native']['processes'][0].update(parentProcessId=999)); self.rejected_collect()

    def test_native_sha_must_match_actual_store_runtime(self):
        self.change_json(self.evidence['arm64'] / 'installed-launch.json', lambda d: d['nativeArchitecture'].update(sha256='0' * 64)); self.rejected_collect()

    def test_missing_other_architecture_proof_cannot_qualify(self):
        self.collect('x64')
        with self.assertRaises(ValueError): self.verify()
        self.assertFalse((self.store / 'store-qualification.json').exists())

    def test_actual_source_pair_fingerprint_is_required(self):
        self.collect('x64'); self.collect('arm64')
        p = self.source / 'rhwp-help-arm64.txt'; p.write_text('modified')
        self.fixture.sums(self.source)
        with self.assertRaises(ValueError): self.verify()
        self.assertFalse((self.store / 'store-qualification.json').exists())

    def test_collected_raw_xml_cannot_be_tampered_after_receipt(self):
        self.collect('x64'); self.collect('arm64')
        p = self.outputs['arm64'] / 'wack-arm64.xml'; self.assertTrue(p.is_file()); p.write_text('tampered')
        with self.assertRaises(ValueError): self.verify()

    def test_screenshot_selects_x64_runtime_from_dual_provenance(self):
        self.assertTrue(hasattr(store_screenshot, 'capture_expected_sha'))
        self.assertEqual(store_screenshot.capture_expected_sha(self.details), self.details['architectures']['x64']['runtimeSha256']['OpenGeul.exe'])

    def test_qualified_reader_rechecks_raw_without_input_mutation(self):
        self.collect('x64'); self.collect('arm64'); expected=self.verify()
        before={p.name:p.read_bytes() for p in self.store.iterdir()}
        actual=qual.inspect_qualified(self.store,self.source,env=dict(self.env,GITHUB_JOB='submit'))
        self.assertEqual(actual,expected)
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.store.iterdir()})

    def test_qualified_reader_rejects_rehashed_raw_partial_report(self):
        self.collect('x64'); self.collect('arm64'); self.verify()
        p=self.store/'wack-arm64.xml';p.write_text(p.read_text().replace('PARTIAL_RUN="FALSE"','PARTIAL_RUN="TRUE"'))
        self.fixture.sums(self.store)
        with self.assertRaises(ValueError):qual.inspect_qualified(self.store,self.source,env=self.env)

    def test_qualified_reader_rejects_original_checksum_prefix_change(self):
        self.collect('x64'); self.collect('arm64'); self.verify()
        p=self.store/'SHA256SUMS.txt';raw=p.read_bytes();p.write_bytes(raw.replace(b'  ',b' \t',1))
        with self.assertRaises(ValueError):qual.inspect_qualified(self.store,self.source,env=self.env)


if __name__ == '__main__': unittest.main()
