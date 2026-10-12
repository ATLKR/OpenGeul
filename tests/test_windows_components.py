"""Integrity controls for the two same-run Windows build transports."""
from pathlib import Path
import copy
import gzip
import hashlib
import importlib.util
import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import buildkit
import prepare_native_tests
import native_activation
import native_source_contract
import wasm_artifacts
import windows_arch

HELPER = ROOT/'scripts/windows_components.py'
components = None
if HELPER.exists():
    spec = importlib.util.spec_from_file_location('windows_components', HELPER)
    components = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(components)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')


def pe(machine=0x8664):
    data = bytearray(256)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 60, 128)
    data[128:132] = b'PE\0\0'
    struct.pack_into('<H', data, 132, machine)
    return bytes(data)


class WindowsComponentsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = {'GITHUB_REPOSITORY': 'ATLKR/OpenGeul', 'GITHUB_SHA': 'a'*40,
                    'GITHUB_RUN_ID': '38147025695', 'GITHUB_RUN_ATTEMPT': '1'}

    def helper(self):
        self.assertIsNotNone(components, 'Windows component integrity helper is missing')
        return components

    def source(self):
        c = self.helper()
        source = self.root/'hop'
        for name in c.SOURCE_FILES:
            path = source/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('synthetic prepared source: '+name+'\n', encoding='utf-8')
        for directory in ('third_party/rhwp/src', 'third_party/rhwp/vendor/svg2pdf/src'):
            path = source/directory/'owned-synthetic.rs'
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('// owned bounded source fixture\n')
        core = source/'third_party/rhwp'
        lock = json.loads((ROOT/'config/upstream.lock.json').read_text())
        # Controlled detached references exercise real git HEAD verification.
        for folder, name in ((source, 'hop'), (core, 'rhwp')):
            subprocess.run(['git', 'init', '-q', str(folder)], check=True)
            (folder/'.git/HEAD').write_text(lock[name]['commit']+'\n')
        original = '[package]\nname = "rhwp"\nversion = "0.8.7"\nautotests = false\n'
        (core/'Cargo.toml').write_text(original, encoding='utf-8')
        prepare_native_tests.prepare(core)
        for upstream, local in c.COPIED_OVERLAYS.items():
            (source/upstream).write_bytes((ROOT/local).read_bytes())
        self.native_source(source)
        namespace = {'patch': 'HWPX header raw-fragment inherited namespaces',
                     'upstreamHeaderSha256': 'b'*64,
                     'patchedHeaderSha256': digest(core/'src/parser/hwpx/header.rs'),
                     'helperSha256': digest(ROOT/'overlay/hwpx_namespaces.rs')}
        write_json(core/'.opengeul-namespaces.json', namespace)
        vendor = source/'apps/studio-host/vendor/rhwp-core'
        vendor.mkdir(parents=True)
        for name in wasm_artifacts.FILES:
            (vendor/name).write_bytes(b'synthetic owned WASM fixture')
        (vendor/'rhwp_bg.wasm').write_bytes(b'\0asm\1\0\0\0')
        (vendor/'package.json').write_text('{"version":"0.8.7"}')
        wasm_artifacts.capture(vendor)
        wasm = json.loads((vendor/'OPEN_GEUL_WASM.json').read_text())
        write_json(vendor/'PROVENANCE.json', {'originalUpstream': {}, 'opengeulRebuild': wasm})
        engine = source/'third_party/rhwp/rhwp-studio/src/engine'
        ledger = {'version': json.loads((ROOT/'config/product.json').read_text())['version'],
                  'source': 'OpenGeul distribution overlays', 'preservedFiles': {},
                  'baselinePreservedFiles': {}, 'changes': ['synthetic owned source'],
                  'hwpxSaveV1': True, 'extendedFiles': ['commands.rs','state.rs','lib.rs','tauri-bridge.ts','main.ts','file.ts','desktop-events.ts','edit.ts'],
                  'compositionFix': {'beforeSha256': 'c'*64,
                     'afterSha256': digest(engine/'input-handler-text.ts'),
                     'helperSha256': digest(ROOT/'overlay/composition-final.ts'), 'evidence': 'synthetic'},
                  'namespacePatch': namespace, 'wasmRebuild': wasm,
                  'nativeActivation': json.loads((source/native_source_contract.LEDGER_PATH).read_bytes())}
        write_json(source/'.opengeul-overlay.json', ledger)
        return source

    def native_source(self, source):
        """소유한 작은 원본 fixture만 대체하고 실제 source policy는 그대로 실행한다."""
        native = source/'apps/desktop/src-tauri'
        config = self.helper().configured()
        original = '[package]\nname="hop-desktop"\nversion="'+config['product']['version']+'"\n[dependencies]\ntauri = { version = "=2.11.1", features = [] }\nopen = "5"\n[patch.crates-io]\n'
        (native/'Cargo.toml').write_text(native_activation.desktop_manifest(original), encoding='utf-8')
        lock = (ROOT/'overlay/desktop-cargo.lock.toml').read_text(encoding='utf-8')
        lock = buildkit.replace_once(lock, 'name = "hop-desktop"\nversion = "'+config['upstream']['hop']['version']+'"',
                                   'name = "hop-desktop"\nversion = "'+config['product']['version']+'"')
        (native/'Cargo.lock').write_text(lock, encoding='utf-8', newline='\n')
        references = {}
        for directory, actual in native_source_contract.REFERENCE.items():
            changed = ('Cargo.toml', 'src/app.rs', 'src/process.rs') if directory == 'tauri-2.11.1' else ('Cargo.toml', 'src/dialog/windows.rs')
            original_files = {name: ('owned original '+directory+'/'+name+'\n').encode()
                              for name in (*changed, 'LICENSE')}
            prepared_files = {name: (b'owned prepared '+content if name in changed else content)
                              for name, content in original_files.items()}
            for name, content in prepared_files.items():
                path = native/'opengeul-native'/directory/name
                path.parent.mkdir(parents=True, exist_ok=True);path.write_bytes(content)
            references[directory] = {key: actual[key] for key in ('name','version','archiveSha256')}
            references[directory]['originalFiles'] = {name: hashlib.sha256(value).hexdigest() for name,value in original_files.items()}
            references[directory]['patchedFiles'] = {name: hashlib.sha256(prepared_files[name]).hexdigest() for name in changed}
        replacement = patch.object(native_source_contract, 'REFERENCE', references)
        replacement.start();self.addCleanup(replacement.stop)
        self.native_reference_path = self.root/'owned-native-reference.json'
        write_json(self.native_reference_path, references)
        shim = {name: digest(ROOT/'overlay/native-open'/name) for name in native_source_contract.SHIM_FILES}
        ledger = {'formatVersion':1, 'patchInputSha256':digest(ROOT/'overlay/native-activation-patches.json'),
                  'originalManifestSha256':hashlib.sha256(original.encode()).hexdigest(),
                  'preparedManifestSha256':digest(native/'Cargo.toml'),
                  'preparedLockSha256':digest(native/'Cargo.lock'), 'crates':{}, 'shimFiles':shim}
        for directory,item in references.items():
            ledger['crates'][directory] = {key:item[key] for key in ('name','version','archiveSha256','originalFiles')}
            ledger['crates'][directory]['preparedFiles'] = {**item['originalFiles'],**item['patchedFiles']}
        (source/native_source_contract.LEDGER_PATH).write_bytes(native_source_contract.ledger_bytes(ledger))

    def cli_command(self, *arguments):
        # A subprocess cannot inherit a Python fixture constant. Substitute only
        # that immutable test input, then run the unchanged public argparse path.
        return [sys.executable, '-c',
                "import json,runpy,sys,native_source_contract;from pathlib import Path;"
                "native_source_contract.REFERENCE=json.loads(Path(sys.argv[1]).read_text());"
                "sys.argv=sys.argv[2:];runpy.run_path(sys.argv[0],run_name='__main__')",
                str(self.native_reference_path),str(HELPER),*arguments]

    def payload(self, role, architecture='x64'):
        target = self.root/(role+'-payload')
        target.mkdir()
        machine = windows_arch.machine_for(architecture)
        if role == 'cli':
            (target/'Tools').mkdir()
            (target/'Tools/rhwp.exe').write_bytes(pe(machine))
        else:
            (target/'OpenGeul.exe').write_bytes(pe(machine))
            (target/'WebView2Loader.dll').write_bytes(pe(machine))
            (target/'AppxManifest.xml').write_text(buildkit.manifest(buildkit.DEV_IDENTITY, json.loads((ROOT/'config/product.json').read_text())['version'], architecture))
            buildkit.make_assets(target/'Assets')
            (target/'Assets/app.ico').unlink()
            (target/'Assets/app.png').unlink()
            (target/'Notices').mkdir()
            (target/'Notices/OpenGeul-LICENSE.txt').write_text('Owned synthetic fixture notice')
        return target

    def pair(self, architecture='x64'):
        c = self.helper()
        source = self.source()
        folders = {}
        for role in ('editor', 'cli'):
            folders[role] = self.root/(role+'-component')
            options = {} if architecture == 'x64' else {'architecture': architecture}
            c.capture(role, self.payload(role, architecture), source, folders[role], env=self.env, **options)
        return folders

    def combine(self, folders, env=None, architecture='x64'):
        options = {} if architecture == 'x64' else {'architecture': architecture}
        return self.helper().combine(folders['editor'], folders['cli'], self.root/'combined',
                                     self.root/'package-source', env=self.env if env is None else env, **options)

    def assert_rejected_without_outputs(self, folders, match=None, env=None, architecture='x64'):
        with self.assertRaisesRegex(ValueError, match or '.'):
            self.combine(folders, env, architecture)
        self.assertFalse((self.root/'combined').exists())
        self.assertFalse((self.root/'package-source').exists())

    def test_arm64_cli_capture_and_combine_restore_exact_runtime(self):
        source = self.source()
        folders = {role: self.root/(role+'-component') for role in ('editor', 'cli')}
        for role in folders:
            payload = self.payload(role, 'arm64')
            result = subprocess.run(
                self.cli_command('capture', '--architecture', 'arm64', '--role', role,
                 '--payload', str(payload), '--source', str(source), '--out', str(folders[role])),
                env={**os.environ, **self.env, 'PYTHONPATH':str(ROOT/'scripts')}, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run(
            self.cli_command('combine', '--architecture', 'arm64',
             '--editor', str(folders['editor']), '--cli', str(folders['cli']),
             '--payload', str(self.root/'combined'), '--source', str(self.root/'package-source')),
            env={**os.environ, **self.env, 'PYTHONPATH':str(ROOT/'scripts')}, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root/'combined/Tools/rhwp.exe').read_bytes(), pe(0xAA64))

    def test_arm64_components_bind_native_exes_dll_manifest_and_artifact_names(self):
        folders = self.pair('arm64')
        self.combine(folders, architecture='arm64')
        for name in ('OpenGeul.exe', 'WebView2Loader.dll', 'Tools/rhwp.exe'):
            self.assertEqual((self.root/'combined'/name).read_bytes(), pe(0xAA64))
        self.assertIn('ProcessorArchitecture="arm64"', (self.root/'combined/AppxManifest.xml').read_text())
        receipt = json.loads((self.root/'package-source/.opengeul-windows-components.json').read_text())
        for role in folders:
            record = json.loads((folders[role]/'provenance.json').read_text())
            self.assertEqual(record['target'], 'aarch64-pc-windows-msvc')
            self.assertEqual(record['formatVersion'], 2 if role == 'cli' else 1)
            self.assertEqual(record['helpers']['scripts/windows_arch.py'], digest(ROOT/'scripts/windows_arch.py'))
            self.assertEqual(receipt['components'][role]['artifactName'],
                             'opengeul-'+role+'-component-arm64-'+self.env['GITHUB_RUN_ID'])
            self.assertEqual(receipt['components'][role]['provenanceSha256'], digest(folders[role]/'provenance.json'))
        self.assertEqual(json.loads((folders['editor']/'provenance.json').read_text())['source'],
                         json.loads((folders['cli']/'provenance.json').read_text())['source'])

    def test_unsupported_component_architectures_fail_before_local_inputs_or_staging(self):
        c = self.helper()
        for architecture in ('ARM64', 'arm64ec', 'x86', '', None):
            with self.subTest(architecture=architecture), patch.object(c, 'configured', side_effect=AssertionError('Architecture must be validated first')):
                with self.assertRaises(ValueError):
                    c.capture('cli', self.root/'absent', self.root/'absent-source', self.root/'out',
                              architecture=architecture, env=self.env)
                with self.assertRaises(ValueError):
                    c.combine(self.root/'absent-editor', self.root/'absent-cli', self.root/'combined',
                              self.root/'package-source', architecture=architecture, env=self.env)
        self.assertFalse((self.root/'out').exists())
        self.assertFalse((self.root/'combined').exists())

    def test_arm64_capture_rejects_mixed_exe_dll_manifest_and_arm64ec_before_staging(self):
        c = self.helper()
        source = self.source()
        payloads = {role: self.payload(role, 'arm64') for role in ('editor', 'cli')}
        changes = [('editor', 'OpenGeul.exe', pe()), ('editor', 'WebView2Loader.dll', pe()),
                   ('editor', 'WebView2Loader.dll', pe(0xA641)), ('cli', 'Tools/rhwp.exe', pe()),
                   ('cli', 'Tools/rhwp.exe', pe(0xA641)),
                   ('editor', 'AppxManifest.xml', buildkit.manifest(buildkit.DEV_IDENTITY,
                        json.loads((ROOT/'config/product.json').read_text())['version']).encode())]
        for index, (role, name, data) in enumerate(changes):
            path = payloads[role]/name
            original = path.read_bytes()
            path.write_bytes(data)
            out = self.root/f'rejected-architecture-{index}'
            with self.subTest(role=role, name=name, index=index), patch.object(c.tempfile, 'mkdtemp', side_effect=AssertionError('Invalid architecture must precede staging')):
                with self.assertRaisesRegex(ValueError, 'arm64|architecture'):
                    c.capture(role, payloads[role], source, out, architecture='arm64', env=self.env)
            self.assertFalse(out.exists())
            path.write_bytes(original)

    def test_arm64_target_and_role_metadata_cannot_be_forged_before_staging(self):
        folders = self.pair('arm64')
        for role, folder in folders.items():
            path = folder/'provenance.json'
            original = json.loads(path.read_text())
            for key, value in [('target', 'x86_64-pc-windows-msvc'), ('target', 'arm64ec-pc-windows-msvc'),
                               ('role', 'cli' if role == 'editor' else 'editor')]:
                changed = copy.deepcopy(original); changed[key] = value
                write_json(path, changed)
                with self.subTest(role=role, key=key, value=value), patch.object(self.helper().tempfile, 'mkdtemp', side_effect=AssertionError('Identity must precede staging')):
                    self.assert_rejected_without_outputs(folders, 'identity', architecture='arm64')
            write_json(path, original)

    def test_arm64_recomputed_inventory_cannot_authorize_x64_or_arm64ec_runtime(self):
        folders = self.pair('arm64')
        for role, name in [('editor','OpenGeul.exe'), ('editor','WebView2Loader.dll'), ('cli','Tools/rhwp.exe')]:
            path = folders[role]/'payload'/(name+'.gz' if role == 'cli' else name)
            provenance = folders[role]/'provenance.json'
            original_data = path.read_bytes(); original = json.loads(provenance.read_text())
            for machine in (0x8664, 0xA641):
                raw = pe(machine)
                path.write_bytes(gzip.compress(raw, mtime=0) if role == 'cli' else raw)
                changed = copy.deepcopy(original)
                changed['files']['payload/'+name+('.gz' if role == 'cli' else '')] = {'size': path.stat().st_size, 'sha256': digest(path)}
                if role == 'cli':
                    changed['runtime'] = {'path': name, 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
                write_json(provenance, changed)
                with self.subTest(role=role, name=name, machine=machine), patch.object(self.helper().tempfile, 'mkdtemp', side_effect=AssertionError('Native PE validation must precede staging')):
                    self.assert_rejected_without_outputs(folders, 'arm64', architecture='arm64')
            path.write_bytes(original_data); write_json(provenance, original)

    def test_x64_editor_and_arm64_cli_cannot_join_for_either_expected_architecture(self):
        c = self.helper(); source = self.source()
        folders = {role: self.root/(role+'-component') for role in ('editor', 'cli')}
        c.capture('editor', self.payload('editor'), source, folders['editor'], env=self.env)
        c.capture('cli', self.payload('cli', 'arm64'), source, folders['cli'], architecture='arm64', env=self.env)
        for architecture in ('x64', 'arm64'):
            with self.subTest(architecture=architecture), patch.object(c.tempfile, 'mkdtemp', side_effect=AssertionError('Mixed architecture must precede staging')):
                self.assert_rejected_without_outputs(folders, 'identity', architecture=architecture)

    def test_arm64_workers_still_require_complete_core_source_parity(self):
        c = self.helper(); source = self.source()
        folders = {role: self.root/(role+'-component') for role in ('editor', 'cli')}
        c.capture('editor', self.payload('editor', 'arm64'), source, folders['editor'], architecture='arm64', env=self.env)
        (source/'third_party/rhwp/src/owned-synthetic.rs').write_text('// changed after editor build\n')
        c.capture('cli', self.payload('cli', 'arm64'), source, folders['cli'], architecture='arm64', env=self.env)
        self.assert_rejected_without_outputs(folders, 'source parity', architecture='arm64')

    def test_same_run_components_restore_complete_payload_and_exact_ledger(self):
        folders = self.pair()
        self.combine(folders)
        self.assertEqual((self.root/'combined/OpenGeul.exe').read_bytes(), pe())
        self.assertEqual((self.root/'combined/Tools/rhwp.exe').read_bytes(), pe())
        self.assertEqual((self.root/'package-source/.opengeul-overlay.json').read_bytes(),
                         (self.root/'hop/.opengeul-overlay.json').read_bytes())
        self.assertEqual(set(p.name for p in folders['editor'].iterdir()),
                         {'payload', 'provenance.json', 'source-parity.json'})
        self.assertEqual(set(p.name for p in folders['cli'].iterdir()), {'payload', 'provenance.json'})
        receipt_path = self.root/'package-source/.opengeul-windows-components.json'
        self.assertTrue(receipt_path.is_file(), 'Verified producer/runtime receipt must survive transport cleanup')
        receipt = json.loads(receipt_path.read_text())
        self.assertEqual(receipt['repository'], self.env['GITHUB_REPOSITORY'])
        self.assertEqual(receipt['commit'], self.env['GITHUB_SHA'])
        self.assertEqual(receipt['runId'], self.env['GITHUB_RUN_ID'])
        self.assertEqual(receipt['runAttempt'], '1')
        self.assertEqual(receipt['formatVersion'], 1)
        for role, runtime in [('editor','OpenGeul.exe'), ('cli','Tools/rhwp.exe')]:
            record = receipt['components'][role]
            self.assertEqual(record['artifactName'], 'opengeul-'+role+'-component-'+self.env['GITHUB_RUN_ID'])
            self.assertEqual(record['runtime'], runtime)
            self.assertEqual(record['size'], (self.root/'combined'/runtime).stat().st_size)
            self.assertEqual(record['sha256'], digest(self.root/'combined'/runtime))
            self.assertEqual(record['provenanceSha256'], digest(folders[role]/'provenance.json'))
        contract = json.loads((folders['editor']/'provenance.json').read_text())['source']
        self.assertEqual(receipt['sourceContractSha256'], hashlib.sha256((json.dumps(contract,indent=2,sort_keys=True)+'\n').encode()).hexdigest())

    def test_capture_requires_native_activation_ledger_before_creating_transport(self):
        source = self.source()
        (source/'apps/desktop/src-tauri/.opengeul-native-activation.json').unlink(missing_ok=True)
        out = self.root/'unbound-native-component'
        with self.assertRaises(ValueError):
            self.helper().capture('editor', self.payload('editor'), source, out, env=self.env)
        self.assertFalse(out.exists())

    def test_unlisted_native_vendor_source_cannot_enter_a_component(self):
        source = self.source()
        extra = source/'apps/desktop/src-tauri/opengeul-native/tauri-2.11.1/src/unreviewed.rs'
        extra.parent.mkdir(parents=True, exist_ok=True)
        extra.write_text('// unreviewed compiler source\n')
        with self.assertRaises(ValueError):
            self.helper().capture('cli', self.payload('cli'), source, self.root/'extra-native', env=self.env)
        self.assertFalse((self.root/'extra-native').exists())

    def test_both_producers_bind_the_same_required_full_native_activation_proof(self):
        folders = self.pair()
        records = [json.loads((folders[role]/'provenance.json').read_text()) for role in ('editor','cli')]
        for record in records:
            self.assertIn('nativeActivation', record['source'])
            self.assertIn('overlay/native-open/README.md', record['helpers'])
        self.assertEqual(records[0]['source']['nativeActivation'], records[1]['source']['nativeActivation'])
        native = records[0]['source']['nativeActivation']['ledger']
        self.assertEqual(set(native['crates']), {'tauri-2.11.1','tauri-runtime-wry-2.11.1'})
        self.assertEqual(set(native['shimFiles']), {'Cargo.toml','LICENSE.txt','README.md','src/activation.rs','src/lib.rs'})

    def test_consumer_rejects_missing_native_proof_even_when_both_records_agree(self):
        folders = self.pair()
        for folder in folders.values():
            path = folder/'provenance.json'
            record = json.loads(path.read_text())
            record['source'].pop('nativeActivation', None)
            write_json(path, record)
        self.assert_rejected_without_outputs(folders)

    def test_public_distribution_ledger_requires_the_actual_native_activation_proof(self):
        source = self.source();path = source/'.opengeul-overlay.json'
        ledger = json.loads(path.read_bytes());ledger.pop('nativeActivation',None);write_json(path,ledger)
        out = self.root/'missing-public-native-proof'
        with self.assertRaisesRegex(ValueError,'native activation|Native activation'):
            self.helper().capture('editor',self.payload('editor'),source,out,env=self.env)
        self.assertFalse(out.exists())

    def test_consumer_rejects_rehashed_public_native_proof_that_disagrees_with_both_producers(self):
        folders = self.pair();path = folders['editor']/'source-parity.json'
        parity = json.loads(path.read_bytes());parity['nativeActivation'] = {'unbound':'different proof'}
        write_json(path,parity)
        for role,folder in folders.items():
            provenance = folder/'provenance.json';value = json.loads(provenance.read_bytes())
            value['source']['ledgerSha256'] = digest(path)
            if role == 'editor':value['files']['source-parity.json'] = {'size':path.stat().st_size,'sha256':digest(path)}
            write_json(provenance,value)
        self.assert_rejected_without_outputs(folders,'native activation|Native activation')

    def test_actual_vendor_mutation_and_rehashed_ledger_cannot_authorize_new_source(self):
        source = self.source()
        path = source/'apps/desktop/src-tauri/opengeul-native/tauri-2.11.1/src/process.rs'
        path.write_bytes(path.read_bytes()+b'// changed compiler input\n')
        payload = self.payload('editor')
        with self.assertRaisesRegex(ValueError, 'compiler source inventory'):
            self.helper().capture('editor', payload, source, self.root/'tampered-vendor', env=self.env)
        ledger_path = source/native_source_contract.LEDGER_PATH
        ledger = json.loads(ledger_path.read_bytes())
        ledger['crates']['tauri-2.11.1']['preparedFiles']['src/process.rs'] = digest(path)
        ledger_path.write_bytes(native_source_contract.ledger_bytes(ledger))
        with self.assertRaisesRegex(ValueError, 'prepared source inventory'):
            self.helper().capture('editor', payload, source, self.root/'rehash-vendor', env=self.env)
        self.assertFalse((self.root/'tampered-vendor').exists())
        self.assertFalse((self.root/'rehash-vendor').exists())

    def test_mixed_original_inventory_or_crate_identity_cannot_become_source_proof(self):
        source = self.source();payload = self.payload('cli')
        path = source/native_source_contract.LEDGER_PATH
        original = json.loads(path.read_bytes())
        for index, change in enumerate(('archive','version','original','prepared','outside')):
            altered = copy.deepcopy(original);crate = altered['crates']['tauri-2.11.1']
            if change == 'archive':crate['archiveSha256'] = '0'*64
            elif change == 'version':crate['version'] = '2.11.0'
            elif change == 'original':crate['originalFiles']['src/app.rs'] = '0'*64
            elif change == 'prepared':crate['preparedFiles'].pop('src/app.rs')
            else:crate['originalFiles']['../outside.rs'] = '0'*64
            path.write_bytes(native_source_contract.ledger_bytes(altered))
            out = self.root/('invalid-native-origin-'+str(index))
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'native activation|Native activation'):
                self.helper().capture('cli', payload, source, out, env=self.env)
            self.assertFalse(out.exists())

    def test_vendor_symlink_and_unlisted_empty_directory_fail_before_staging(self):
        source = self.source();payload = self.payload('cli')
        directory = source/'apps/desktop/src-tauri/opengeul-native/tauri-2.11.1'
        extra = directory/'unlisted-empty';extra.mkdir()
        with self.assertRaisesRegex(ValueError, 'source directory'):
            self.helper().capture('cli', payload, source, self.root/'extra-directory', env=self.env)
        extra.rmdir()
        path = directory/'LICENSE';data = path.read_bytes();path.unlink()
        outside = self.root/'outside-vendor-license';outside.write_bytes(data)
        try:path.symlink_to(outside)
        except OSError as error:self.skipTest('Owned synthetic symlink fixture unavailable: '+str(error))
        with self.assertRaisesRegex(ValueError, 'symlink|reparse'):
            self.helper().capture('cli', payload, source, self.root/'outside-vendor', env=self.env)
        self.assertFalse((self.root/'extra-directory').exists())
        self.assertFalse((self.root/'outside-vendor').exists())

    def test_rehashed_native_consumer_metadata_still_requires_reviewed_origin_and_patch_bytes(self):
        folders = self.pair()
        originals = {role:json.loads((folder/'provenance.json').read_bytes()) for role,folder in folders.items()}
        for change in ('archive','origin','prepared','shim','manifest','lock','patch','raw-ledger'):
            for role,folder in folders.items():
                record = copy.deepcopy(originals[role]);source = record['source'];ledger = source['nativeActivation']['ledger']
                crate = ledger['crates']['tauri-2.11.1']
                if change == 'archive':crate['archiveSha256'] = '0'*64
                elif change == 'origin':crate['originalFiles']['src/app.rs'] = '0'*64
                elif change == 'prepared':crate['preparedFiles']['src/app.rs'] = '0'*64
                elif change == 'shim':ledger['shimFiles']['src/lib.rs'] = '0'*64
                elif change == 'manifest':ledger['preparedManifestSha256'] = '0'*64
                elif change == 'lock':ledger['preparedLockSha256'] = '0'*64
                elif change == 'patch':ledger['patchInputSha256'] = '0'*64
                source['preparedFiles'][native_source_contract.LEDGER_PATH] = hashlib.sha256(native_source_contract.ledger_bytes(ledger)).hexdigest()
                if change == 'raw-ledger':source['preparedFiles'][native_source_contract.LEDGER_PATH] = '0'*64
                write_json(folder/'provenance.json', record)
            with self.subTest(change=change):self.assert_rejected_without_outputs(folders)

    def test_native_ledger_serialization_is_order_independent_and_raw_lf_bound(self):
        folders = self.pair()
        for folder in folders.values():
            path = folder/'provenance.json';record = json.loads(path.read_bytes())
            ledger = record['source']['nativeActivation']['ledger']
            record['source']['nativeActivation']['ledger'] = {key:ledger[key] for key in reversed(list(ledger))}
            write_json(path, record)
        self.combine(folders)
        self.assertTrue((self.root/'combined/Tools/rhwp.exe').is_file())

    def test_native_lock_binds_product_version_derivation_without_mutating_the_seed(self):
        source = self.source();seed = ROOT/'overlay/desktop-cargo.lock.toml'
        before = seed.read_bytes()
        try:_, contract = self.helper().source_contract(source, self.helper().configured())
        except ValueError as error:self.fail('Correct product-version lock was rejected: '+str(error))
        self.assertNotEqual(contract['nativeActivation']['ledger']['preparedLockSha256'], digest(seed))
        self.assertEqual(contract['nativeActivation']['ledger']['preparedLockSha256'],
                         digest(source/'apps/desktop/src-tauri/Cargo.lock'))
        self.assertEqual(seed.read_bytes(), before)

    def test_rehashed_native_manifest_with_wrong_product_version_is_rejected(self):
        source = self.source();manifest = source/'apps/desktop/src-tauri/Cargo.toml'
        version = self.helper().configured()['product']['version']
        manifest.write_text(buildkit.replace_once(manifest.read_text(), 'version="'+version+'"', 'version="0.0.1"'))
        path = source/native_source_contract.LEDGER_PATH;ledger = json.loads(path.read_bytes())
        ledger['preparedManifestSha256'] = digest(manifest)
        path.write_bytes(native_source_contract.ledger_bytes(ledger))
        out = self.root/'wrong-native-product-version'
        with self.assertRaisesRegex(ValueError, 'product version'):
            self.helper().capture('editor', self.payload('editor'), source, out, env=self.env)
        self.assertFalse(out.exists())

    def test_crlf_or_unbound_shim_helper_cannot_enter_native_source_contract(self):
        source = self.source();payload = self.payload('editor')
        path = source/native_source_contract.LEDGER_PATH
        original = path.read_bytes();path.write_bytes(original.replace(b'\n',b'\r\n'))
        with self.assertRaisesRegex(ValueError, 'raw ledger digest'):
            self.helper().capture('editor', payload, source, self.root/'crlf-native-ledger', env=self.env)
        path.write_bytes(original)
        shim = source/'apps/desktop/src-tauri/opengeul-native/native-open/src/lib.rs'
        shim.write_bytes(shim.read_bytes()+b'// changed helper\n')
        with self.assertRaisesRegex(ValueError, 'overlay helper mismatch'):
            self.helper().capture('editor', payload, source, self.root/'changed-native-shim', env=self.env)
        self.assertFalse((self.root/'crlf-native-ledger').exists())
        self.assertFalse((self.root/'changed-native-shim').exists())

    def test_cli_above_transport_cap_compresses_and_restores_exact_raw_runtime(self):
        c = self.helper()
        source = self.source()
        cli_payload = self.payload('cli')
        executable = cli_payload/'Tools/rhwp.exe'
        with executable.open('ab') as stream:
            for _ in range(33): stream.write(b'\0' * (1024 * 1024))
        expected = {'size': executable.stat().st_size, 'sha256': digest(executable)}
        self.assertGreater(expected['size'], c.CAPS['cli'])
        folders = {role: self.root/(role+'-component') for role in ('editor', 'cli')}
        c.capture('editor', self.payload('editor'), source, folders['editor'], env=self.env)
        try: c.capture('cli', cli_payload, source, folders['cli'], env=self.env)
        except ValueError as error: self.fail('Compressible production-sized CLI was rejected: '+str(error))
        record = json.loads((folders['cli']/'provenance.json').read_text())
        self.assertEqual(record['formatVersion'], 2)
        self.assertEqual(record['runtime'], {'path': 'Tools/rhwp.exe', **expected})
        self.assertEqual(set(record['files']), {'payload/Tools/rhwp.exe.gz'})
        self.assertLessEqual(sum(p.stat().st_size for p in folders['cli'].rglob('*') if p.is_file()), c.CAPS['cli'])
        self.assertFalse((folders['cli']/'payload/Tools/rhwp.exe').exists())
        self.combine(folders)
        restored = self.root/'combined/Tools/rhwp.exe'
        self.assertEqual({'size': restored.stat().st_size, 'sha256': digest(restored)}, expected)
        self.assertFalse((self.root/'combined/Tools/rhwp.exe.gz').exists())
        receipt = json.loads((self.root/'package-source/.opengeul-windows-components.json').read_text())
        self.assertEqual({k: receipt['components']['cli'][k] for k in ('size', 'sha256')}, expected)

    def rewrite_cli_transport(self, folders, data, raw=None):
        path = folders['cli']/'payload/Tools/rhwp.exe.gz'
        path.write_bytes(data)
        provenance = folders['cli']/'provenance.json'
        value = json.loads(provenance.read_text())
        value['files']['payload/Tools/rhwp.exe.gz'] = {'size': len(data), 'sha256': digest(path)}
        if raw is not None:
            value['runtime'] = {'path': 'Tools/rhwp.exe', 'size': len(raw),
                                'sha256': hashlib.sha256(raw).hexdigest()}
        write_json(provenance, value)

    def test_cli_gzip_capture_is_deterministic_and_editor_format_stays_one(self):
        folders = self.pair()
        out = self.root/'second-cli'
        self.helper().capture('cli', self.root/'cli-payload', self.root/'hop', out, env=self.env)
        path = 'payload/Tools/rhwp.exe.gz'
        self.assertEqual((folders['cli']/path).read_bytes(), (out/path).read_bytes())
        self.assertEqual((folders['cli']/'provenance.json').read_bytes(), (out/'provenance.json').read_bytes())
        self.assertEqual((out/path).read_bytes()[3:8], b'\0'*5, 'No filename flag or timestamp may enter transport')
        self.assertEqual(json.loads((folders['editor']/'provenance.json').read_text())['formatVersion'], 1)

    def test_recomputed_transport_cannot_authorize_invalid_gzip_streams(self):
        folders = self.pair()
        original = (folders['cli']/'payload/Tools/rhwp.exe.gz').read_bytes()
        corrupt = bytearray(original); corrupt[-8] ^= 1
        streams = {'truncated': original[:-1], 'CRC': bytes(corrupt),
                   'trailing': original+b'junk', 'concatenated': original+original,
                   'not-gzip': pe()}
        for name, data in streams.items():
            with self.subTest(stream=name):
                self.rewrite_cli_transport(folders, data)
                with patch.object(self.helper().tempfile, 'mkdtemp', side_effect=AssertionError('Validation must precede staging')):
                    self.assert_rejected_without_outputs(folders, '(?i)gzip')

    def test_forged_cli_runtime_path_size_hash_and_format_are_rejected_before_staging(self):
        folders = self.pair()
        path = folders['cli']/'provenance.json'
        original = json.loads(path.read_text())
        changes = [('path', '../rhwp.exe'), ('size', 255), ('size', 257), ('size', True),
                   ('size', 96*1024*1024+1), ('sha256', '0'*64)]
        for key, value in changes:
            with self.subTest(key=key, value=value):
                changed = copy.deepcopy(original)
                changed['runtime'][key] = value
                write_json(path, changed)
                with patch.object(self.helper().tempfile, 'mkdtemp', side_effect=AssertionError('Validation must precede staging')):
                    self.assert_rejected_without_outputs(folders, '(?i)runtime|cap')
        for change in ({'formatVersion': 1}, {'runtime': {'path': 'Tools/rhwp.exe', 'size': 256, 'sha256': '0'*64, 'extra': 0}}):
            with self.subTest(change=change):
                changed = copy.deepcopy(original); changed.update(change)
                write_json(path, changed)
                self.assert_rejected_without_outputs(folders)

    def test_gzip_expansion_is_bounded_by_declared_raw_size(self):
        folders = self.pair()
        self.rewrite_cli_transport(folders, gzip.compress(pe()+b'\0'*(2*1024*1024), mtime=0))
        with patch.object(self.helper().tempfile, 'mkdtemp', side_effect=AssertionError('Expansion must fail before staging')):
            self.assert_rejected_without_outputs(folders, 'runtime size|cap')

    def test_capture_raw_and_combined_restored_payload_budget_are_enforced(self):
        c = self.helper()
        source = self.source()
        payload = self.payload('cli')
        with patch.object(c, 'MAX_PAYLOAD', 255):
            with self.assertRaisesRegex(ValueError, 'cap'):
                c.capture('cli', payload, source, self.root/'over-raw-cap', env=self.env)
        self.assertFalse((self.root/'over-raw-cap').exists())
        payload.rename(self.root/'unused-cli-payload')
        folders = self.pair_from_source(source)
        editor = json.loads((folders['editor']/'provenance.json').read_text())
        editor_size = sum(v['size'] for n, v in editor['files'].items() if n.startswith('payload/'))
        with patch.object(c, 'MAX_PAYLOAD', editor_size+255), patch.object(c.tempfile, 'mkdtemp', side_effect=AssertionError('Combined cap must precede staging')):
            self.assert_rejected_without_outputs(folders, 'combined|cap')

    def test_capture_rechecks_cli_input_size_and_hash_after_inventory(self):
        c = self.helper()
        source = self.source()
        payload = self.payload('cli')
        path = payload/'Tools/rhwp.exe'
        contract = c.source_contract
        changed = bytearray(pe()); changed[200] ^= 1
        for index, data in enumerate((bytes(changed), pe()+b'growth')):
            with self.subTest(size=len(data)):
                path.write_bytes(pe())
                def change_after_inventory(source, config):
                    result = contract(source, config)
                    path.write_bytes(data)
                    return result
                out = self.root/('changed-input-'+str(index))
                with patch.object(c, 'source_contract', side_effect=change_after_inventory), patch.object(c.tempfile, 'mkdtemp', side_effect=AssertionError('Changed input must fail before staging')):
                    with self.assertRaisesRegex(ValueError, 'runtime input'):
                        c.capture('cli', payload, source, out, env=self.env)
                self.assertFalse(out.exists())

    def test_second_decode_rechecks_changed_transport_and_removes_private_staging(self):
        folders = self.pair()
        c = self.helper()
        validate = c.validate_component
        def change_after_validation(folder, role, current, config, *, architecture='x64'):
            result = validate(folder, role, current, config, architecture=architecture)
            if role == 'cli':
                path = folder/'payload/Tools/rhwp.exe.gz'
                path.write_bytes(gzip.compress(pe()+b'changed', mtime=0))
            return result
        with patch.object(c, 'validate_component', side_effect=change_after_validation):
            self.assert_rejected_without_outputs(folders)
        self.assertFalse(any(p.name.startswith(('.opengeul-joined-', '.opengeul-source-')) for p in self.root.iterdir()))

    def test_tampered_cli_is_rejected_before_any_editor_file_is_staged(self):
        folders = self.pair()
        (folders['cli']/'payload/Tools/rhwp.exe.gz').write_bytes(gzip.compress(pe()+b'tamper', mtime=0))
        self.assert_rejected_without_outputs(folders, 'inventory')

    def test_missing_and_extra_files_are_rejected(self):
        folders = self.pair()
        path = folders['editor']/'payload/Notices/OpenGeul-LICENSE.txt'
        original = path.read_bytes()
        path.unlink()
        self.assert_rejected_without_outputs(folders, 'inventory|payload')
        path.write_bytes(original)
        (folders['cli']/'unexpected.json').write_text('{}')
        self.assert_rejected_without_outputs(folders, '(?i)component')

    def test_cross_run_source_repository_attempt_and_role_are_rejected(self):
        folders = self.pair()
        path = folders['cli']/'provenance.json'
        original = json.loads(path.read_text())
        for key, value in [('runId','2'), ('commit','b'*40), ('repository','other/repo'),
                           ('runAttempt','2'), ('role','editor')]:
            with self.subTest(key=key):
                changed = copy.deepcopy(original)
                changed[key] = value
                write_json(path, changed)
                self.assert_rejected_without_outputs(folders)
        write_json(path, original)
        bad_env = dict(self.env, GITHUB_RUN_ATTEMPT='0')
        self.assert_rejected_without_outputs(folders, env=bad_env)

    def test_previous_successful_attempt_can_join_current_retry_same_run_source(self):
        c = self.helper()
        source = self.source()
        folders = {role: self.root/(role+'-component') for role in ('editor', 'cli')}
        c.capture('editor', self.payload('editor'), source, folders['editor'], env=self.env)
        retry = dict(self.env, GITHUB_RUN_ATTEMPT='2')
        c.capture('cli', self.payload('cli'), source, folders['cli'], env=retry)
        self.combine(folders, retry)
        self.assertEqual((self.root/'combined/Tools/rhwp.exe').read_bytes(), pe())
        receipt = json.loads((self.root/'package-source/.opengeul-windows-components.json').read_text())
        self.assertEqual(receipt['runAttempt'], '2')
        self.assertEqual(receipt['components']['editor']['runAttempt'], '1')
        self.assertEqual(receipt['components']['cli']['runAttempt'], '2')

    def test_future_and_invalid_component_attempts_are_rejected(self):
        folders = self.pair()
        path = folders['cli']/'provenance.json'
        original = json.loads(path.read_text())
        for attempt in ('3', '0', '-1', '1.5', 'not-a-number', 1):
            with self.subTest(attempt=attempt):
                value = copy.deepcopy(original)
                value['runAttempt'] = attempt
                write_json(path, value)
                self.assert_rejected_without_outputs(folders, env=dict(self.env, GITHUB_RUN_ATTEMPT='2'))

    def test_unlisted_core_source_changes_break_cross_worker_parity(self):
        c = self.helper()
        source = self.source()
        folders = {role: self.root/(role+'-component') for role in ('editor', 'cli')}
        c.capture('editor', self.payload('editor'), source, folders['editor'], env=self.env)
        path = source/'third_party/rhwp/src/owned-synthetic.rs'
        path.write_text('// different source for the CLI\n')
        c.capture('cli', self.payload('cli'), source, folders['cli'], env=self.env)
        self.assert_rejected_without_outputs(folders, 'source parity')

    def test_recomputed_inventory_cannot_authorize_wrong_machine_exe_or_dll(self):
        folders = self.pair()
        for role, name in [('cli','Tools/rhwp.exe'), ('editor','WebView2Loader.dll')]:
            with self.subTest(name=name):
                path = folders[role]/'payload'/(name+'.gz' if role == 'cli' else name)
                path.write_bytes(gzip.compress(pe(0x14c), mtime=0) if role == 'cli' else pe(0x14c))
                provenance = folders[role]/'provenance.json'
                value = json.loads(provenance.read_text())
                value['files']['payload/'+name+('.gz' if role == 'cli' else '')] = {'size': path.stat().st_size, 'sha256': digest(path)}
                if role == 'cli':
                    value['runtime'] = {'path': name, 'size': 256, 'sha256': hashlib.sha256(pe(0x14c)).hexdigest()}
                write_json(provenance, value)
                self.assert_rejected_without_outputs(folders, 'x64')
                path.write_bytes(gzip.compress(pe(), mtime=0) if role == 'cli' else pe())
                value['files']['payload/'+name+('.gz' if role == 'cli' else '')] = {'size': path.stat().st_size, 'sha256': digest(path)}
                if role == 'cli':
                    value['runtime']['sha256'] = hashlib.sha256(pe()).hexdigest()
                write_json(provenance, value)

    def test_local_helper_and_wasm_bindings_are_enforced_even_if_both_records_match(self):
        folders = self.pair()
        for role in folders:
            path = folders[role]/'provenance.json'
            value = json.loads(path.read_text())
            value['helpers']['overlay/font_policy.rs'] = '0'*64
            write_json(path, value)
        self.assert_rejected_without_outputs(folders, 'helper')

    def test_source_parity_byte_tampering_is_rejected(self):
        folders = self.pair()
        path = folders['editor']/'source-parity.json'
        path.write_bytes(path.read_bytes()+b' ')
        self.assert_rejected_without_outputs(folders, 'inventory')

    def test_capture_rejects_unregistered_native_test_before_output_creation(self):
        c = self.helper()
        source = self.source()
        path = source/'third_party/rhwp/Cargo.toml'
        path.write_text(path.read_text().replace('tests/opengeul_table_height.rs', 'tests/other.rs'))
        out = self.root/'component'
        with self.assertRaisesRegex(ValueError, '(?i)native'):
            c.capture('editor', self.payload('editor'), source, out, env=self.env)
        self.assertFalse(out.exists())

    def test_capture_checks_actual_namespace_test_overlay_and_wasm_bytes(self):
        c = self.helper()
        source = self.source()
        targets = ['third_party/rhwp/src/parser/hwpx/header.rs',
                   'third_party/rhwp/tests/opengeul_pdf_policy.rs',
                   'third_party/rhwp/src/renderer/pdf/opengeul_pdf_guard.rs',
                   'apps/studio-host/vendor/rhwp-core/rhwp_bg.wasm']
        for index, name in enumerate(targets):
            with self.subTest(name=name):
                path = source/name
                original = path.read_bytes()
                path.write_bytes(original+b'tamper')
                out = self.root/f'rejected-{index}'
                with self.assertRaises(ValueError):
                    c.capture('cli', self.payload('cli') if index == 0 else self.root/'cli-payload', source, out, env=self.env)
                self.assertFalse(out.exists())
                path.write_bytes(original)

    def test_required_password_composition_and_wasm_ledger_fields_are_enforced(self):
        c = self.helper()
        source = self.source()
        path = source/'.opengeul-overlay.json'
        original = json.loads(path.read_text())
        payload = self.payload('editor')
        for key in ('hwpxSaveV1', 'compositionFix', 'namespacePatch', 'wasmRebuild'):
            with self.subTest(key=key):
                changed = copy.deepcopy(original)
                del changed[key]
                write_json(path, changed)
                out = self.root/('missing-'+key)
                with self.assertRaises(ValueError):
                    c.capture('editor', payload, source, out, env=self.env)
                self.assertFalse(out.exists())

    def test_cancel_close_source_is_part_of_every_worker_contract(self):
        self.assertIn('apps/studio-host/src/core/desktop-events.ts', self.helper().SOURCE_FILES,
                      'Actual close-cancellation event source must be bound in the receipt contract')

    def test_cut_document_guard_source_is_part_of_every_worker_contract(self):
        self.assertIn('apps/studio-host/src/command/commands/edit.ts', self.helper().SOURCE_FILES,
                      'The actual async Cut document guard must be bound in the receipt contract')

    def test_workers_with_different_host_visibility_css_cannot_join(self):
        c = self.helper()
        source = self.source()
        style = source/'apps/studio-host/src/style.css'
        style.parent.mkdir(parents=True, exist_ok=True)
        style.write_text('.md-item { display: flex; }\n', encoding='utf-8')
        folders = {role: self.root/(role+'-component') for role in ('editor', 'cli')}
        c.capture('editor', self.payload('editor'), source, folders['editor'], env=self.env)
        style.write_text('.md-item { display: flex; }\n.md-item[hidden] { display: none; }\n', encoding='utf-8')
        c.capture('cli', self.payload('cli'), source, folders['cli'], env=self.env)
        self.assert_rejected_without_outputs(folders)

    def test_previous_save_ledger_without_cut_document_guard_is_rejected(self):
        c = self.helper()
        source = self.source()
        path = source/'.opengeul-overlay.json'
        ledger = json.loads(path.read_text())
        ledger['extendedFiles'].remove('edit.ts')
        write_json(path, ledger)
        out = self.root/'old-cut-ledger'
        with self.assertRaisesRegex(ValueError, 'overlay ledger'):
            c.capture('editor', self.payload('editor'), source, out, env=self.env)
        self.assertFalse(out.exists())

    def test_previous_save_ledger_without_close_cancellation_is_rejected(self):
        c = self.helper()
        source = self.source()
        path = source/'.opengeul-overlay.json'
        ledger = json.loads(path.read_text())
        ledger['extendedFiles'].remove('desktop-events.ts')
        write_json(path, ledger)
        out = self.root/'old-ledger'
        with self.assertRaisesRegex(ValueError, 'overlay ledger'):
            c.capture('editor', self.payload('editor'), source, out, env=self.env)
        self.assertFalse(out.exists())

    def test_windows_crlf_composition_retains_logical_ledger_and_raw_source_hash(self):
        c = self.helper()
        source = self.source()
        path = source/'third_party/rhwp/rhwp-studio/src/engine/input-handler-text.ts'
        path.write_bytes(path.read_bytes().replace(b'\n', b'\r\n'))
        out = self.root/'crlf-component'
        c.capture('editor', self.payload('editor'), source, out, env=self.env)
        value = json.loads((out/'provenance.json').read_text())
        ledger = json.loads((out/'source-parity.json').read_text())
        self.assertEqual(value['source']['compositionTextSha256'], ledger['compositionFix']['afterSha256'])
        self.assertEqual(value['source']['preparedFiles'][path.relative_to(source).as_posix()], digest(path))
        self.assertNotEqual(value['source']['compositionTextSha256'], digest(path))

    def test_git_heads_must_be_exact_pinned_upstream_commits(self):
        c = self.helper()
        source = self.source()
        payload = self.payload('cli')
        for folder in (source, source/'third_party/rhwp'):
            with self.subTest(folder=folder):
                head = folder/'.git/HEAD'
                original = head.read_bytes()
                head.write_text('d'*40+'\n')
                with self.assertRaisesRegex(ValueError, 'git HEAD'):
                    c.capture('cli', payload, source, self.root/'wrong-head', env=self.env)
                self.assertFalse((self.root/'wrong-head').exists())
                head.write_bytes(original)

    def test_identically_forged_wasm_records_fail_local_source_binding(self):
        folders = self.pair()
        parity_path = folders['editor']/'source-parity.json'
        parity = json.loads(parity_path.read_text())
        parity['wasmRebuild']['namespacePatcher'] = '0'*64
        write_json(parity_path, parity)
        for role in folders:
            path = folders[role]/'provenance.json'
            value = json.loads(path.read_text())
            value['source']['wasmRebuild'] = parity['wasmRebuild']
            value['source']['ledgerSha256'] = digest(parity_path)
            if role == 'editor':
                value['files']['source-parity.json'] = {'size': parity_path.stat().st_size, 'sha256': digest(parity_path)}
            write_json(path, value)
        self.assert_rejected_without_outputs(folders, 'WASM')

    def test_unsafe_windows_paths_case_collisions_and_symlinks_are_rejected(self):
        c = self.helper()
        source = self.source()
        payload = self.payload('editor')
        for name in ('opengeul.exe', 'CON.dll', 'COM¹.dll', 'COM².dll', 'LPT³.dll',
                     'bad:name.dll', 'bad\\name.dll', 'trailing .dll '):
            with self.subTest(name=name):
                path = payload/name
                path.write_bytes(pe())
                with self.assertRaises(ValueError):
                    c.capture('editor', payload, source, self.root/'bad-path', env=self.env)
                path.unlink()
        link = payload/'Notices/link.txt'
        try:
            link.symlink_to(payload/'Notices/OpenGeul-LICENSE.txt')
        except (OSError, NotImplementedError):
            self.skipTest('Host cannot create symlinks')
        with self.assertRaisesRegex(ValueError, 'symlink|regular'):
            c.capture('editor', payload, source, self.root/'bad-link', env=self.env)

    def test_recomputed_manifest_cannot_authorize_traversal_or_extra_payload(self):
        folders = self.pair()
        path = folders['cli']/'provenance.json'
        value = json.loads(path.read_text())
        value['files']['../escape.exe'] = {'size': 256, 'sha256': '0'*64}
        write_json(path, value)
        self.assert_rejected_without_outputs(folders, 'path|inventory')

    def test_windows_crlf_native_manifest_retains_registration_and_raw_hash(self):
        c = self.helper()
        source = self.source()
        path = source/'third_party/rhwp/Cargo.toml'
        path.write_bytes(path.read_bytes().replace(b'\n', b'\r\n'))
        out = self.root/'crlf-native'
        c.capture('cli', self.payload('cli'), source, out, env=self.env)
        value = json.loads((out/'provenance.json').read_text())
        self.assertEqual(value['source']['preparedFiles']['third_party/rhwp/Cargo.toml'], digest(path))

    def test_caps_are_checked_at_capture_and_join(self):
        c = self.helper()
        source = self.source()
        payload = self.payload('cli')
        with patch.dict(c.CAPS, {'cli': 128}):
            with self.assertRaisesRegex(ValueError, 'cap'):
                c.capture('cli', payload, source, self.root/'too-large', env=self.env)
        payload.rename(self.root/'unused-cli-payload')
        folders = self.pair_from_source(source)
        with patch.dict(c.CAPS, {'cli': 128}):
            self.assert_rejected_without_outputs(folders, 'cap')

    def pair_from_source(self, source):
        folders = {}
        for role in ('editor', 'cli'):
            folders[role] = self.root/(role+'-component')
            self.helper().capture(role, self.payload(role), source, folders[role], env=self.env)
        return folders

    def test_existing_destinations_and_symlink_ancestors_are_never_overwritten(self):
        folders = self.pair()
        output = self.root/'combined'
        output.mkdir()
        (output/'sentinel').write_text('keep')
        with self.assertRaises(ValueError):
            self.combine(folders)
        self.assertEqual((output/'sentinel').read_text(), 'keep')
        self.assertFalse((self.root/'package-source').exists())

    def test_destination_symlink_ancestor_is_rejected_before_any_output(self):
        folders = self.pair()
        actual = self.root/'actual'
        actual.mkdir()
        link = self.root/'alias'
        try:
            link.symlink_to(actual, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('Host cannot create symlinks')
        with self.assertRaisesRegex(ValueError, 'symlink|reparse'):
            self.helper().combine(folders['editor'], folders['cli'], link/'payload',
                                  self.root/'package-source', env=self.env)
        self.assertEqual(list(actual.iterdir()), [])
        self.assertFalse((self.root/'package-source').exists())


if __name__ == '__main__':
    unittest.main()
