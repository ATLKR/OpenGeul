"""Source menu admission must join external Full evidence to both actual providers."""
from __future__ import annotations

import copy
from dataclasses import FrozenInstanceError
import importlib
import io
import json
import os
from pathlib import Path
import stat
import struct
import subprocess
import sys
import tempfile
import time
import unittest
import warnings
from unittest.mock import patch
import zipfile

# The fixture is also imported by E2E helper tests run from suite/tests.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from suite import payload, prepare
from suite.tests.test_payload import PayloadFixture, canonical, digest, pe
from suite.tests.test_prepare import (source_build_fixture, pin_source_receipt, SOURCE_CORE,
    x64_source_build_fixture, synthetic_source_template_pins)


PROVIDERS = ('program/UAccCOM.dll', 'program/winaccessibility.dll')
PATCH = dict(schemaVersion=1, kind='winacc-focus-order-source-patch', passed=True,
    coreCommit=SOURCE_CORE, path='winaccessibility/source/service/AccObjectWinManager.cxx',
    beforeSha256='ab5ed31cac9b262461b1d7e45fbe4a5758fef852a0f51c08c0c6f8e25d1c9be0',
    afterSha256='5e5f42a6b448c0d9c70a05bf762e86951565b5a96decaf050399f577dd38332b',
    patchSha256='968379ba427ac952c5c7df7f0c37ceabb495310acc224ee5380d51f523fb3ed7',
    nativeBuildVerified=False, guiVerified=False, currentCiRootCauseConfirmed=False,
    sourceFiles=[
        dict(path='winaccessibility/source/service/AccObjectWinManager.cxx',
            beforeBytes=33670, afterBytes=33670,
            beforeSha256='ab5ed31cac9b262461b1d7e45fbe4a5758fef852a0f51c08c0c6f8e25d1c9be0',
            afterSha256='5e5f42a6b448c0d9c70a05bf762e86951565b5a96decaf050399f577dd38332b'),
        dict(path='winaccessibility/source/service/AccObject.cxx', beforeBytes=26374, afterBytes=26374,
            beforeSha256='e0e27e04a32b28eb3883e3020a037baa858c5014d5b769e86f05417b32d66e8e',
            afterSha256='e0e27e04a32b28eb3883e3020a037baa858c5014d5b769e86f05417b32d66e8e'),
        dict(path='winaccessibility/source/UAccCOM/MAccessible.cxx', beforeBytes=90847, afterBytes=90847,
            beforeSha256='98cb71a8b4c65683ad5ab891bff83a2fc6702bbff39c79d27b74d3a405a9ffad',
            afterSha256='98cb71a8b4c65683ad5ab891bff83a2fc6702bbff39c79d27b74d3a405a9ffad')])


class SourceMenuImportTests(unittest.TestCase):
    def test_bare_e2e_import_from_external_cwd_uses_anchored_suite_dependencies(self):
        e2e = Path(__file__).resolve().parents[1]/'e2e'
        script = '''
import sys
from pathlib import Path
e2e = Path(sys.argv[1])
sys.path.insert(0, str(e2e))
import native_menu_source_admission as gate
assert gate.prepare.__name__ == 'suite.prepare'
assert gate.payload.__name__ == 'suite.payload'
assert Path(gate.prepare.__file__).resolve() == e2e.parent/'prepare.py'
assert Path(gate.payload.__file__).resolve() == e2e.parent/'payload.py'
assert 'prepare' not in sys.modules and 'payload' not in sys.modules
'''
        child_env = {'PATH': '/workspace/toolcache/opengeul-validation/powershell:/usr/bin:/bin',
            'XDG_CACHE_HOME': '/workspace/toolcache/opengeul-validation/cache',
            'XDG_CONFIG_HOME': '/workspace/toolcache/opengeul-validation/config',
            'XDG_DATA_HOME': '/workspace/toolcache/opengeul-validation/data', 'PYTHONUTF8': '1'}
        with tempfile.TemporaryDirectory() as outside:
            result = subprocess.run([sys.executable, '-I', '-c', script, str(e2e)],
                cwd=outside, env=child_env, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)


class SourceMenuAdmissionTests(PayloadFixture):
    def setUp(self):
        super().setUp()
        self.inputs = Path(self.temp.name)/'inputs'
        self.inputs.mkdir()
        self.archive, self.runtime, self.receipt, self.proof = source_build_fixture(self.inputs)
        with zipfile.ZipFile(self.archive) as source:
            self.entries = {item.filename: source.read(item) for item in source.infolist()}
        self.provider_bytes = (pe(0xaa64, dll=True)+b'provider-one', pe(0xaa64, dll=True)+b'provider-two')
        self.entries.update(zip(PROVIDERS, self.provider_bytes))
        self.proof['crtImportClosure']['checkedPeCount'] = 17
        self.proof['winAccFocusOrderSourcePatch'] = copy.deepcopy(PATCH)
        self.provenance['architecture'] = 'arm64'
        self.branding['source']['buildId'] = SOURCE_CORE
        self.branding['source']['sourceUrl'] = 'https://example.org/core/'+SOURCE_CORE
        for name in ('OpenGeul.Office.exe', 'hostfxr.dll'):
            self.write(name, pe(0xaa64))
        self.trusted = Path(self.temp.name)/'reviewed-harness'
        (self.trusted/'suite/config').mkdir(parents=True)
        self.seal(copy_runtime=True)

    def implementation(self):
        try:
            return importlib.import_module('suite.e2e.native_menu_source_admission')
        except ModuleNotFoundError:
            self.fail('Source-qualified menu admission is not implemented')

    def seal(self, *, copy_runtime=False, inventory=True):
        with zipfile.ZipFile(self.archive, 'w', compression=zipfile.ZIP_DEFLATED) as source:
            for name, data in self.entries.items():
                source.writestr(name, data)
        self.runtime.update(size=self.archive.stat().st_size, sha256=digest(self.archive.read_bytes()))
        self.proof['artifact'].update(size=self.runtime['size'], sha256=self.runtime['sha256'])
        pin_source_receipt(self.runtime, self.receipt, self.proof)
        if copy_runtime:
            for name, data in self.entries.items():
                self.write('Office/'+name, data)
        self.write('Office/opengeul-source-build.json', self.receipt.read_bytes())
        metadata_hash = digest(self.read('Office/program/version.ini'))
        self.branding['modifiedFiles']['program/version.ini'] = dict(
            beforeSha256=self.proof['runtimeBuildIdentity']['files']['program/version.ini']['sha256'],
            sha256=metadata_hash)
        self.provenance['runtime'] = copy.deepcopy(self.runtime)
        self.source_archive()
        self.save_metadata()
        self.write_external_lock()
        if inventory:
            self.write_json('suite-inventory.json', payload.create_inventory(self.root, architecture='arm64'))

    def write_external_lock(self):
        self.external_lock = self.trusted/'suite/config/runtime.arm64.lock.json'
        self.external_lock.write_bytes(canonical(dict(schemaVersion=1, architecture='arm64',
            version=self.product['version'], runtime=self.runtime)))

    def admit(self, *, deadline=None, architecture='arm64'):
        module = self.implementation()
        with patch.object(module, '_HARNESS_ROOT', self.trusted):
            return module.admit_source_menu_runtime(self.root, architecture=architecture,
                engine_zip=self.archive, receipt=self.receipt,
                deadline=time.monotonic()+30 if deadline is None else deadline)

    def test_admits_real_validators_and_freezes_closed_binary_summary(self):
        admitted = self.admit()
        summary = admitted.summary()
        self.assertEqual(set(summary), {'schemaVersion', 'architecture', 'admissionSha256',
            'lockSha256', 'receiptSha256', 'engineZipSha256', 'inventorySha256',
            'sourceCoreCommit', 'sourceRecipeSha256', 'providers'})
        self.assertEqual((summary['schemaVersion'], summary['architecture']), (1, 0xaa64))
        self.assertEqual(summary['sourceCoreCommit'], SOURCE_CORE)
        self.assertEqual(summary['admissionSha256'], admitted.admission_sha256)
        self.assertEqual(summary['lockSha256'], digest(self.external_lock.read_bytes()))
        self.assertEqual(summary['receiptSha256'], digest(self.receipt.read_bytes()))
        self.assertEqual(summary['engineZipSha256'], digest(self.archive.read_bytes()))
        self.assertEqual(summary['inventorySha256'], digest(self.read('suite-inventory.json')))
        self.assertEqual([dict(item) for item in summary['providers']], [
            dict(role=1, size=1036, sha256=digest(self.provider_bytes[0])),
            dict(role=2, size=1036, sha256=digest(self.provider_bytes[1]))])
        wire = dict(summary)
        wire['providers'] = [dict(item) for item in summary['providers']]
        body = dict(wire)
        del body['admissionSha256']
        self.assertEqual(admitted.admission_sha256,
            digest(canonical(dict(suiteRoot=str(self.root.absolute()), summary=body)) ))
        with self.assertRaises((FrozenInstanceError, AttributeError)):
            admitted.architecture = 'x64'
        with self.assertRaises(TypeError):
            summary['architecture'] = 0x8664
        with self.assertRaises(TypeError):
            summary['providers'][0]['role'] = 2
        admitted.verify_provider_files(time.monotonic()+1)

    def test_rejects_current_tracked_x64_msi_without_source_fallback(self):
        module = self.implementation()
        with self.assertRaises(ValueError):
            module.admit_source_menu_runtime(self.root, architecture='x64',
                engine_zip=self.archive, receipt=self.receipt, deadline=time.monotonic()+2)

    def test_public_constructor_cannot_forge_admission_without_two_verified_providers(self):
        module = self.implementation()
        with self.assertRaises(TypeError):
            module.SourceMenuAdmission(self.root, 'arm64', '0'*64, (), {})

    def test_rejects_unsupported_architecture(self):
        with self.assertRaises(ValueError):
            self.admit(architecture='x86')

    def test_rejects_packaged_self_consistency_without_external_equality(self):
        self.provenance['runtime']['sourceBuild']['artifactId'] = 789
        self.source_archive()
        self.save_metadata()
        self.write_json('suite-inventory.json', payload.create_inventory(self.root, architecture='arm64'))
        with self.assertRaises(ValueError):
            self.admit()

    def test_rejects_consistent_other_core_accepted_by_generic_source_validators(self):
        other = 'e'*40
        self.proof = json.loads(json.dumps(self.proof).replace(SOURCE_CORE, other))
        self.runtime['sourceCoreCommit'] = other
        for name in ('program/version.ini', 'program/setup.ini'):
            raw = self.entries[name].replace(SOURCE_CORE.encode(), other.encode())
            self.entries[name] = raw
            self.proof['runtimeBuildIdentity']['files'][name]['sha256'] = digest(raw)
            self.proof['runtimeBuildIdentity']['finalVerification']['files'][name]['sha256'] = digest(raw)
        self.branding['source']['buildId'] = other
        self.seal(copy_runtime=True)
        prepare.validate_source_build_receipt(self.runtime, self.receipt, architecture='arm64')
        with self.assertRaises(ValueError):
            self.admit()

    def test_rejects_full_receipt_and_source_patch_changes_even_if_re_pinned(self):
        for mutate in (lambda proof: proof.update(phase='Assemble'),
                       lambda proof: proof['winAccFocusOrderSourcePatch'].update(afterSha256='0'*64),
                       lambda proof: proof['winAccFocusOrderSourcePatch']['sourceFiles'].pop(),
                       lambda proof: proof['winAccFocusOrderSourcePatch'].update(passed=1)):
            with self.subTest(mutation='receipt-or-recipe'):
                original = copy.deepcopy(self.proof)
                mutate(self.proof)
                self.seal(inventory=False)
                with self.assertRaises(ValueError):
                    self.admit()
                self.proof = original

    def test_rejects_unpinned_receipt_or_archive_bytes(self):
        for path in (self.receipt, self.archive):
            with self.subTest(input='receipt' if path == self.receipt else 'archive'):
                original = path.read_bytes()
                path.write_bytes(original+b'changed')
                with self.assertRaises(ValueError):
                    self.admit()
                path.write_bytes(original)

    def test_rejects_changed_provider_even_with_new_consistent_bundle_inventory(self):
        self.write('Office/'+PROVIDERS[0], self.provider_bytes[0]+b'changed')
        self.write_json('suite-inventory.json', payload.create_inventory(self.root, architecture='arm64'))
        with self.assertRaises(ValueError):
            self.admit()

    def test_rejects_changed_or_missing_authenticated_zip_provider(self):
        for missing in (False, True):
            with self.subTest(missing=missing):
                original = dict(self.entries)
                if missing:
                    del self.entries[PROVIDERS[1]]
                else:
                    self.entries[PROVIDERS[1]] += b'changed'
                self.seal()
                with self.assertRaises(ValueError):
                    self.admit()
                self.entries = original

    def test_rejects_exact_name_substitution_without_alias_fallback(self):
        self.entries['program/uacccom.dll'] = self.entries.pop(PROVIDERS[0])
        self.seal()
        with self.assertRaises(ValueError):
            self.admit()

    def test_rejects_provider_absent_from_verified_inventory(self):
        receipt = json.loads(self.read('suite-inventory.json'))
        del receipt['files']['Office/'+PROVIDERS[0]]
        self.write_json('suite-inventory.json', receipt)
        with self.assertRaises(ValueError):
            self.admit()

    def test_recheck_rejects_changed_bytes_replacement_and_linked_ancestor(self):
        admitted = self.admit()
        path = self.root/'Office'/PROVIDERS[0]
        path.write_bytes(self.provider_bytes[0]+b'changed')
        with self.assertRaises(ValueError):
            admitted.verify_provider_files(time.monotonic()+1)
        path.write_bytes(self.provider_bytes[0])
        admitted = self.admit()
        replacement = path.with_name('replacement.dll')
        replacement.write_bytes(path.read_bytes())
        replacement.replace(path)
        with self.assertRaises(ValueError):
            admitted.verify_provider_files(time.monotonic()+1)
        admitted = self.admit()
        office = self.root/'Office'
        office.rename(self.root/'real-office')
        office.symlink_to(self.root/'real-office', target_is_directory=True)
        with self.assertRaises(ValueError):
            admitted.verify_provider_files(time.monotonic()+1)

    def test_deadline_is_original_and_recheck_never_renews_it(self):
        with self.assertRaises(ValueError):
            self.admit(deadline=time.monotonic()-1)
        admitted = self.admit()
        with self.assertRaises(ValueError):
            admitted.verify_provider_files(time.monotonic()-1)
        for invalid in (True, float('nan'), float('inf')):
            with self.subTest(deadline='invalid'):
                with self.assertRaises(ValueError):
                    self.admit(deadline=invalid)

    def test_rejects_archive_identity_drift_during_existing_hash(self):
        real_hash = prepare.sha256
        def drift(path):
            value = real_hash(path)
            if path == self.archive:
                info = path.stat()
                os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns+1_000_000))
            return value
        with patch.object(prepare, 'sha256', drift), self.assertRaises(ValueError):
            self.admit()

    def test_rejects_metadata_drift_after_actual_payload_verification(self):
        real_verify = payload.verify_payload
        def verify(root, inventory):
            real_verify(root, inventory)
            target = root/'runtime-branding.json'
            info = target.stat()
            os.utime(target, ns=(info.st_atime_ns, info.st_mtime_ns+1_000_000))
        with patch.object(payload, 'verify_payload', verify), self.assertRaises(ValueError):
            self.admit()

    def test_rejects_linked_external_input_ancestor(self):
        self.inputs.rename(self.inputs.with_name('real-inputs'))
        self.inputs.symlink_to(self.inputs.with_name('real-inputs'), target_is_directory=True)
        with self.assertRaises(ValueError):
            self.admit()

    def test_rejects_provider_identity_drift_during_recheck_read(self):
        admitted = self.admit()
        target = self.root/'Office'/PROVIDERS[0]
        real_open = Path.open
        class DriftingReader:
            def __init__(self, reader): self.reader = reader
            def __enter__(self): return self
            def __exit__(self, *args): self.reader.close()
            def fileno(self): return self.reader.fileno()
            def read(self, size=-1):
                raw = self.reader.read(size)
                info = target.stat()
                os.utime(target, ns=(info.st_atime_ns, info.st_mtime_ns+1_000_000))
                return raw
        def open_file(path, *args, **kwargs):
            reader = real_open(path, *args, **kwargs)
            return DriftingReader(reader) if path == target else reader
        with patch.object(Path, 'open', open_file), self.assertRaises(ValueError):
            admitted.verify_provider_files(time.monotonic()+1)

    def test_readonly_member_hasher_rejects_alias_traversal_kind_and_size_bombs(self):
        module = self.implementation()
        for name, mode in ((PROVIDERS[0], 0), ('Program/extra', 0), ('../extra', 0),
                           ('program/link', stat.S_IFLNK | 0o777)):
            with self.subTest(member='unsafe'):
                archive = self.inputs/'unsafe.zip'
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore', UserWarning)  # Intentional duplicate ZIP fixture.
                    with zipfile.ZipFile(archive, 'w') as source:
                        for member, data in zip(PROVIDERS, self.provider_bytes): source.writestr(member, data)
                        item = zipfile.ZipInfo(name)
                        item.external_attr = mode << 16
                        source.writestr(item, b'bad')
                with self.assertRaises(ValueError):
                    module._hash_provider_members(archive, deadline=time.monotonic()+2)
        with patch.object(module, '_MAX_FILE_BYTES', 1000), self.assertRaises(ValueError):
            module._hash_provider_members(self.archive, deadline=time.monotonic()+2)
        with patch.object(module, '_MAX_MEMBERS', 1), self.assertRaises(ValueError):
            module._hash_provider_members(self.archive, deadline=time.monotonic()+2)

    def test_readonly_member_hasher_rejects_encrypted_member_before_open(self):
        module = self.implementation()
        raw = bytearray(self.archive.read_bytes())
        with zipfile.ZipFile(io.BytesIO(raw)) as source:
            member = source.getinfo(PROVIDERS[0])
            offset = source.start_dir
        while raw[offset:offset+4] == b'PK\x01\x02':
            name_size, extra_size, comment_size = struct.unpack_from('<HHH', raw, offset+28)
            if raw[offset+46:offset+46+name_size] == PROVIDERS[0].encode():
                struct.pack_into('<H', raw, offset+8, 1)
                struct.pack_into('<H', raw, member.header_offset+6, 1)
                break
            offset += 46+name_size+extra_size+comment_size
        else:
            self.fail('Synthetic provider central-directory entry is missing')
        encrypted = self.inputs/'encrypted.zip'
        encrypted.write_bytes(raw)
        with self.assertRaises(ValueError):
            module._hash_provider_members(encrypted, deadline=time.monotonic()+2)

    def test_member_stream_checks_original_deadline_after_read(self):
        module = self.implementation()
        now = [0.0]
        real_read = zipfile.ZipExtFile.read
        def read(reader, *args):
            result = real_read(reader, *args)
            now[0] = 2.0
            return result
        with patch.object(module.time, 'monotonic', lambda: now[0]), \
                patch.object(zipfile.ZipExtFile, 'read', read), self.assertRaises(ValueError):
            module._hash_provider_members(self.archive, deadline=1.0)


class X64SourceMenuAdmissionTests(PayloadFixture):
    def test_admits_two_x64_providers_with_existing_complete_producer_inventory(self):
        # Exercise the real v2 recipe/inventory validators; only the upstream
        # launcher-template pins are replaced by their explicit synthetic bytes.
        inputs = Path(self.temp.name)/'inputs'
        inputs.mkdir()
        archive, runtime, receipt, proof = x64_source_build_fixture(inputs, runtime_templates=True)
        with zipfile.ZipFile(archive) as source:
            entries = {item.filename: source.read(item) for item in source.infolist()}
        raw = pe(0x8664, dll=True)+b'uacc-provider'
        entries[PROVIDERS[0]] = raw
        proof['productInventory'].append(dict(path='C:\\build\\instdir\\program\\UAccCOM.dll',
            role='nativeX64', machine=0x8664, size=len(raw), sha256=digest(raw)))
        proof['productPeCount'] += 1
        proof['nativePeCount'] += 1
        proof['crtImportClosure']['checkedPeCount'] += 1
        with zipfile.ZipFile(archive, 'w') as source:
            for name, data in entries.items():
                source.writestr(name, data)
                self.write('Office/'+name, data)
        runtime.update(size=archive.stat().st_size, sha256=digest(archive.read_bytes()))
        proof['artifact'].update(size=runtime['size'], sha256=runtime['sha256'])
        pin_source_receipt(runtime, receipt, proof)
        self.write('Office/opengeul-source-build.json', receipt.read_bytes())
        self.branding['source'].update(buildId=SOURCE_CORE, sourceUrl='https://example.org/core/'+SOURCE_CORE)
        metadata_hash = digest(entries['program/version.ini'])
        self.branding['modifiedFiles']['program/version.ini'] = dict(
            beforeSha256=metadata_hash, sha256=metadata_hash)
        self.provenance['runtime'] = runtime
        self.source_archive()
        self.save_metadata()
        trusted = Path(self.temp.name)/'reviewed-harness'
        lock = trusted/'suite/config/runtime.lock.json'
        lock.parent.mkdir(parents=True)
        lock.write_bytes(canonical(dict(schemaVersion=1, architecture='x64',
            version=self.product['version'], runtime=runtime)))
        synthetic = {'Office/'+name: pin for name, pin in synthetic_source_template_pins(proof).items()}
        module = importlib.import_module('suite.e2e.native_menu_source_admission')
        with patch.dict(payload.COMPANION_PE_ADMISSIONS, synthetic), patch.object(module, '_HARNESS_ROOT', trusted):
            self.write_json('suite-inventory.json', payload.create_inventory(self.root, architecture='x64'))
            admitted = module.admit_source_menu_runtime(self.root, architecture='x64',
                engine_zip=archive, receipt=receipt, deadline=time.monotonic()+30)
            admitted.verify_provider_files(time.monotonic()+1)
        self.assertEqual(admitted.summary()['architecture'], 0x8664)
        self.assertEqual([item['role'] for item in admitted.summary()['providers']], [1, 2])


if __name__ == '__main__':
    import unittest
    unittest.main()
