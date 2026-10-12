"""실제 ZIP/PE/체크섬/WACK XML을 사용하는 두 아키텍처 릴리스 회귀 검증."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'e2e'), str(ROOT / 'tests')]
from test_mcp_qualification import installed_proof
from buildkit import DEV_IDENTITY, manifest
from windows_arch import component_artifact_name, machine_for
from wack_result import inspect
import release_pair as pair


class ReleasePairTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.output = self.root / 'output'
        self.env = {'GITHUB_REPOSITORY': 'ATLKR/OpenGeul', 'GITHUB_SHA': 'a' * 40,
                    'GITHUB_RUN_ID': '1234', 'GITHUB_RUN_ATTEMPT': '2'}
        self.packages = {}; self.wacks = {}; self.runtime = {}
        self.upstream = json.loads((ROOT / 'config/upstream.lock.json').read_text())
        for arch in ('x64', 'arm64'):
            self.make_arch(arch)

    def write_json(self, path, value):
        path.write_text(json.dumps(value, sort_keys=True) + '\n', encoding='utf-8')

    def sums(self, folder):
        (folder / 'SHA256SUMS.txt').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + p.name + '\n'
            for p in sorted(folder.iterdir()) if p.name != 'SHA256SUMS.txt'), encoding='utf-8')

    def zip(self, path, files):
        with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for name, raw in files.items(): archive.writestr(name, raw)

    def make_arch(self, arch):
        folder = self.root / arch; folder.mkdir(); self.packages[arch] = folder
        raw_pe = bytearray(256); raw_pe[:2] = b'MZ'; raw_pe[60:64] = (128).to_bytes(4, 'little')
        raw_pe[128:132] = b'PE\0\0'; raw_pe[132:134] = machine_for(arch).to_bytes(2, 'little')
        self.runtime[arch] = {'AppxManifest.xml': manifest(DEV_IDENTITY, '1.1.3', arch).encode(),
            'OpenGeul.exe': bytes(raw_pe), 'Tools/rhwp.exe': bytes(raw_pe) + b'cli',
            'Notices/OpenGeul-LICENSE.txt': b'MIT', 'Assets/StoreLogo.png': b'PNG'}
        msix = folder / f'OpenGeul_1.1.3.0_{arch}_development-unsigned.msix'
        self.zip(msix, {**self.runtime[arch], 'AppxBlockMap.xml': b'<BlockMap/>', '[Content_Types].xml': b'<Types/>'})
        self.zip(folder / f'OpenGeul-1.1.3-{arch}-portable.zip', self.runtime[arch])
        (folder / 'AppxManifest.xml').write_bytes(self.runtime[arch]['AppxManifest.xml'])
        (folder / 'rhwp-help.txt').write_text('rhwp help\n')
        components = {'formatVersion': 1, 'repository': 'ATLKR/OpenGeul', 'commit': 'a' * 40,
            'runId': '1234', 'runAttempt': '2', 'sourceContractSha256': 'b' * 64, 'components': {}}
        for role, name in [('editor', 'OpenGeul.exe'), ('cli', 'Tools/rhwp.exe')]:
            raw = self.runtime[arch][name]
            components['components'][role] = {'artifactName': component_artifact_name(role, '1234', arch),
                'runAttempt': '1', 'provenanceSha256': ('c' if role == 'editor' else 'd') * 64,
                'runtime': name, 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
        self.write_json(folder / 'provenance.json', {'unsigned': True, 'architecture': arch, 'members': 7,
            'sha256': hashlib.sha256(msix.read_bytes()).hexdigest(), 'repository': 'ATLKR/OpenGeul',
            'commit': 'a' * 40, 'runId': '1234', 'version': '1.1.3', 'package': msix.name,
            'upstream': self.upstream, 'sourceParity': {'version': '1.1.3', 'source': 'OpenGeul distribution overlays'},
            'manualWindowsUx': 'not-verified', 'storeCertified': False, 'windowsComponents': components})
        self.sums(folder)
        wack = self.root / ('wack-' + arch); wack.mkdir(); self.wacks[arch] = wack
        signed = ('e' if arch == 'x64' else 'f') * 64
        install = {'success': True, 'originalSha256': hashlib.sha256(msix.read_bytes()).hexdigest().upper(),
            'signedTestPackageSha256': signed.upper(), 'publisher': DEV_IDENTITY['publisher'],
            'packageFullName': f"{DEV_IDENTITY['name']}_1.1.3.0_{arch}__9za217j1njc2t"}
        install['mcp'] = installed_proof(arch, components['components']['cli']['sha256'], install['packageFullName'],
            'a' * 40, '1234', '2', components['components']['cli']['size'])
        self.write_json(wack / 'install.json', install)
        self.write_json(wack / 'wack-context.json', {'invocationMode': 'documented-appxpackagepath',
            'inputPackageSha256': signed.upper(), 'runnerSessionId': 1, 'wackSessionId': 1})
        xml = f'''<REPORT OVERALL_RESULT="PASS" PARTIAL_RUN="FALSE" APP_NAME="{DEV_IDENTITY['name']}" APP_VERSION="1.1.3.0" VALIDATION_TYPE="CommandLine" APP_TYPE="Centennial" VERSION="10.0.26100.8249">
        <APPLICATIONS><Installed_Programs><Program Source="AppxPackage" Name="{DEV_IDENTITY['name']}" Version="1.1.3.0"><Indicators><WindowsStoreAppManifestIndicators><PackageManifest><Package><Identity Name="{DEV_IDENTITY['name']}" Publisher="{DEV_IDENTITY['publisher']}" Version="1.1.3.0" ProcessorArchitecture="{arch}"/></Package></PackageManifest></WindowsStoreAppManifestIndicators></Indicators></Program></Installed_Programs></APPLICATIONS>
        <TEST NAME="Required"><RESULT>PASS</RESULT></TEST><TEST NAME="Blocked executables" OPTIONAL="TRUE"><RESULT>PASS</RESULT></TEST></REPORT>'''
        (wack / 'wack.xml').write_text(xml, encoding='utf-8'); self.summary(arch)

    def summary(self, arch):
        w = self.wacks[arch]
        self.write_json(w / 'wack.json', inspect(w / 'wack.xml', DEV_IDENTITY['name'], '1.1.3.0', 0))

    def assemble(self):
        return pair.assemble(self.packages['x64'], self.packages['arm64'], self.wacks['x64'], self.wacks['arm64'], self.output, env=self.env)

    def mutate_prov(self, arch, change):
        p = self.packages[arch] / 'provenance.json'; d = json.loads(p.read_bytes()); change(d); self.write_json(p, d); self.sums(self.packages[arch])

    def rejected(self):
        with self.assertRaises((ValueError, zipfile.BadZipFile)):
            self.assemble()
        self.assertFalse(self.output.exists(), '검증 실패가 부분 릴리스를 남겼다')

    def test_valid_pair_preserves_original_bytes_and_exact_22_assets(self):
        self.assemble()
        self.assertTrue(self.output.exists())
        d = pair.verify_pair(self.output)
        self.assertEqual(d['formatVersion'], 2); self.assertEqual(set(d['architectures']), {'x64', 'arm64'})
        self.assertEqual(d['runAttempt'], '2'); self.assertEqual(len(list(self.output.iterdir())), 22)
        for arch in ('x64', 'arm64'):
            for original, flattened in d['architectures'][arch]['assets'].items():
                self.assertEqual((self.output / flattened).read_bytes(), (self.packages[arch] / original).read_bytes())
        fingerprint = hashlib.sha256(json.dumps([{'name': p.name, 'size': p.stat().st_size,
            'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(self.output.iterdir())], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        self.assertEqual(pair.source_fingerprint(self.output), fingerprint)

    def test_copy_architecture_restores_original_six_with_no_overwrite(self):
        self.assemble(); restored = self.root / 'restored'
        pair.copy_architecture(self.output, 'arm64', restored)
        self.assertTrue(restored.is_dir())
        self.assertEqual({p.name for p in restored.iterdir()}, {p.name for p in self.packages['arm64'].iterdir()})
        for p in restored.iterdir(): self.assertEqual(p.read_bytes(), (self.packages['arm64'] / p.name).read_bytes())
        with self.assertRaises(ValueError): pair.copy_architecture(self.output, 'arm64', restored)

    def test_original_checksum_tampering_rejected(self):
        (self.packages['arm64'] / 'rhwp-help.txt').write_text('tampered'); self.rejected()

    def test_full_source_wack_without_installed_mcp_proof_is_rejected(self):
        installation = self.wacks['arm64']/'install.json'
        value = json.loads(installation.read_bytes());value.pop('mcp',None);self.write_json(installation,value)
        self.rejected()

    def test_rehashed_source_mcp_stale_binding_or_false_case_is_rejected(self):
        self.assemble()
        path = self.output / 'install-arm64.json'; original = path.read_bytes()
        for mutate in (lambda p:p.update(sourceRun='999'), lambda p:p.update(helperSha256='0'*64),
                lambda p:p['cases'][3]['checks'].update(sourceTextMatched=False),
                lambda p:p['serverNativeArchitecture'].update(bytes=1)):
            with self.subTest(mutate=mutate):
                value = json.loads(original); mutate(value['mcp']); self.write_json(path,value); self.sums(self.output)
                with self.assertRaises(ValueError): pair.verify_pair(self.output)

    def test_wrong_architecture_declaration_rejected(self):
        self.mutate_prov('arm64', lambda d: d.update(architecture='x64')); self.rejected()

    def test_wrong_native_machine_is_rejected_even_with_matching_checksums(self):
        payload = dict(self.runtime['arm64']); payload['Tools/rhwp.exe'] = self.runtime['x64']['Tools/rhwp.exe']
        self.zip(self.packages['arm64'] / 'OpenGeul-1.1.3-arm64-portable.zip', payload)
        msix = self.packages['arm64'] / 'OpenGeul_1.1.3.0_arm64_development-unsigned.msix'
        self.zip(msix, {**payload, 'AppxBlockMap.xml': b'<BlockMap/>', '[Content_Types].xml': b'<Types/>'})
        self.mutate_prov('arm64', lambda d: d.update(sha256=hashlib.sha256(msix.read_bytes()).hexdigest())); self.rejected()

    def test_mixed_source_contract_and_ledger_are_rejected(self):
        self.mutate_prov('arm64', lambda d: d['windowsComponents'].update(sourceContractSha256='0' * 64)); self.rejected()

    def test_mixed_overlay_source_is_rejected(self):
        self.mutate_prov('arm64', lambda d: d['sourceParity'].update(extra='changed')); self.rejected()

    def test_stale_same_run_packages_are_rejected_against_current_ci(self):
        self.env['GITHUB_RUN_ID'] = '9999'; self.rejected()

    def test_component_runtime_hash_and_attempt_are_checked(self):
        self.mutate_prov('arm64', lambda d: d['windowsComponents']['components']['cli'].update(sha256='0' * 64)); self.rejected()

    def test_component_retry_cannot_exceed_release_attempt(self):
        self.mutate_prov('arm64', lambda d: d['windowsComponents']['components']['editor'].update(runAttempt='3')); self.rejected()

    def test_optional_warning_is_not_full_wack_pass(self):
        w = self.wacks['arm64']; raw = (w / 'wack.xml').read_text().replace('OVERALL_RESULT="PASS"', 'OVERALL_RESULT="WARNING"').replace('<RESULT>PASS</RESULT></TEST></REPORT>', '<RESULT>FAIL</RESULT></TEST></REPORT>')
        (w / 'wack.xml').write_text(raw); self.summary('arm64'); self.rejected()

    def test_partial_wack_run_is_rejected(self):
        w = self.wacks['x64']; (w / 'wack.xml').write_text((w / 'wack.xml').read_text().replace('PARTIAL_RUN="FALSE"', 'PARTIAL_RUN="TRUE"')); self.summary('x64'); self.rejected()

    def test_forged_pass_summary_cannot_replace_raw_xml(self):
        w = self.wacks['x64']; (w / 'wack.xml').write_text((w / 'wack.xml').read_text().replace('PARTIAL_RUN="FALSE"', 'PARTIAL_RUN="TRUE"')); self.rejected()

    def test_stale_install_original_hash_is_rejected(self):
        p = self.wacks['arm64'] / 'install.json'; d = json.loads(p.read_bytes()); d['originalSha256'] = '0' * 64; self.write_json(p, d); self.rejected()

    def test_signed_wack_context_hash_is_exactly_linked(self):
        p = self.wacks['arm64'] / 'wack-context.json'; d = json.loads(p.read_bytes()); d['inputPackageSha256'] = '0' * 64; self.write_json(p, d); self.rejected()

    def test_install_identity_version_and_architecture_must_match(self):
        p = self.wacks['arm64'] / 'install.json'; d = json.loads(p.read_bytes()); d['packageFullName'] = d['packageFullName'].replace('_arm64_', '_x64_'); self.write_json(p, d); self.rejected()

    def test_outer_manifest_cannot_differ_from_actual_msix(self):
        p = self.packages['x64'] / 'AppxManifest.xml'; p.write_text(p.read_text().replace('OpenGeul Development', 'other')); self.sums(self.packages['x64']); self.rejected()

    def test_global_reader_rejects_post_assembly_raw_wack_tampering(self):
        self.assemble()
        p = self.output / 'wack-arm64.xml'; self.assertTrue(p.is_file())
        p.write_text('tampered')
        with self.assertRaises(ValueError): pair.verify_pair(self.output)

    def test_extra_arch_and_unknown_asset_are_rejected(self):
        self.assemble()
        p = self.output / 'provenance.json'; self.assertTrue(p.is_file())
        d = json.loads(p.read_bytes()); d['architectures']['x86'] = d['architectures']['x64']; self.write_json(p, d); self.sums(self.output)
        with self.assertRaises(ValueError): pair.verify_pair(self.output)

    def test_pair_and_arch_byte_caps_precede_output(self):
        with (self.packages['x64'] / 'rhwp-help.txt').open('wb') as f: f.truncate(96 * 1024 * 1024 + 1)
        self.rejected()

    def test_file_changed_after_validation_cannot_be_released(self):
        original = pair._architecture
        def changed(*args, **kwargs):
            result = original(*args, **kwargs)
            if args[2] == 'arm64':
                target = self.wacks['arm64'] / 'wack-context.json'
                target.write_text('{"inputPackageSha256":"changed"}')
            return result
        with patch.object(pair, '_architecture', side_effect=changed):
            self.rejected()

    def test_full_resource_parity_is_checked_beyond_editor_and_cli(self):
        payload = dict(self.runtime['arm64']); payload['Assets/StoreLogo.png'] = b'different'
        self.zip(self.packages['arm64'] / 'OpenGeul-1.1.3-arm64-portable.zip', payload)
        self.sums(self.packages['arm64']); self.rejected()

    def test_reader_reinspects_raw_xml_even_after_global_checksums_recomputed(self):
        self.assemble(); p = self.output / 'wack-arm64.xml'
        p.write_text(p.read_text().replace('PARTIAL_RUN="FALSE"', 'PARTIAL_RUN="TRUE"'))
        self.sums(self.output)
        with self.assertRaises(ValueError): pair.verify_pair(self.output)

    def test_output_cannot_be_inside_original_package(self):
        self.output = self.packages['x64'] / 'nested-output'; self.rejected()

    def test_restore_cannot_mutate_pair_directory(self):
        self.assemble(); target = self.output / 'nested-restored'
        with self.assertRaises(ValueError): pair.copy_architecture(self.output, 'x64', target)
        self.assertFalse(target.exists())


if __name__ == '__main__': unittest.main()
