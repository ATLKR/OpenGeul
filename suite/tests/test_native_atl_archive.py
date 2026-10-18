import hashlib
import json
import os
import pathlib
import shutil
import struct
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
DRIVER = ROOT/'suite/scripts/probe-native-atl.ps1'
PWSH = shutil.which('pwsh')


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def make_archive(path, objects=None, special='/<ECSYMBOLS>/', payload_override=None):
    objects = objects or [(0xa641, r'D:\build\arm64ec\atlbase.obj'),
                          (0xaa64, r'D:\build\arm64\atlbase.obj')]
    longnames = b''
    object_entries = []
    for machine, name in objects:
        offset = len(longnames)
        longnames += name.encode('ascii') + b'\0'
        payload = struct.pack('<HHIIIHH', machine, 0, 0, 0, 0, 0, 0)
        if payload_override:
            payload = payload_override(payload)
        object_entries.append(('/'+str(offset), name, payload, machine, 'ordinaryCoffObject'))
    entries = [('/', '/', b'\0'*4, None, 'archiveIndexMetadata'),
               ('/', '/', b'\0'*8, None, 'archiveIndexMetadata'),
               ('//', '//', longnames, None, 'longnamesMetadata'),
               (special, special, b'\0'*4, None, 'ecSymbolIndexMetadata')] + object_entries
    data = b'!<arch>\n'
    members = []
    for raw, name, payload, machine, kind in entries:
        offset = len(data)
        header = (raw.encode('ascii').ljust(16) + b'0'.ljust(12) + b'0'.ljust(6)*2 +
                  b'0'.ljust(8) + str(len(payload)).encode().ljust(10) + b'`\n')
        members.append(dict(ordinal=len(members), headerOffset=offset, payloadOffset=offset+60,
                            rawName=raw, resolvedName=name, payloadBytes=len(payload),
                            payloadSha256=hashlib.sha256(payload).hexdigest(), kind=kind, machine=machine))
        data += header + payload + (b'\n' if len(payload) % 2 else b'')
    path.write_bytes(data)
    return dict(kind='spectre', bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
                aa64ObjectCount=sum(m == 0xaa64 for m, _ in objects),
                arm64EcObjectCount=sum(m == 0xa641 for m, _ in objects), members=members)


@unittest.skipUnless(PWSH, 'PowerShell is required for the diagnostic archive tests')
class NativeAtlArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.library = self.root/'atls.lib'
        self.profile_path = self.root/'profile.json'

    def ps(self, command, success=True, reason=None):
        result = subprocess.run([PWSH, '-NoProfile', '-NonInteractive', '-Command',
                                 "$ErrorActionPreference='Stop'; . " + quote(DRIVER) + '; ' + command],
                                capture_output=True, text=True, timeout=60)
        if success:
            self.assertEqual(0, result.returncode, result.stdout+result.stderr)
        else:
            self.assertNotEqual(0, result.returncode, result.stdout+result.stderr)
            if reason:
                self.assertIn(reason, result.stderr)
        return result.stdout

    def prepare(self, **kwargs):
        profile = make_archive(self.library, **kwargs)
        self.profile_path.write_text(json.dumps(profile))
        return profile

    def read(self, success=True, reason=None):
        return self.ps(f"Read-AtlStaticArchive {quote(self.library)} (Get-Content -Raw {quote(self.profile_path)}|ConvertFrom-Json)|ConvertTo-Json -Depth 14 -Compress",
                       success=success, reason=reason)

    def witness(self, loaded_names, map_names=None, *, library=None):
        log, mapping = self.root/'link.log', self.root/'link.map'
        library = library or self.library
        log.write_text(''.join('    Loaded '+str(library)+'('+name+')\n' for name in loaded_names))
        map_names = loaded_names if map_names is None else map_names
        mapping.write_text(' Address Publics by Value Rva+Base Lib:Object\n'+''.join(
            f' 0001:{i:08x} ?owned{i}@@YAXXZ 0000000140001000 f atls:'+name+'\n'
            for i, name in enumerate(map_names)))
        return log, mapping

    def consume(self, log, mapping, success=True, reason=None):
        command = (f"$library=Read-AtlStaticArchive {quote(self.library)} (Get-Content -Raw {quote(self.profile_path)}|ConvertFrom-Json); "
                   f"Assert-AtlNativeConsumption @({quote(log)}) {quote(mapping)} $library|ConvertTo-Json -Depth 14 -Compress")
        return self.ps(command, success=success, reason=reason)

    def test_metadata_is_not_a_fake_machine_and_variants_stay_explicit(self):
        self.prepare()
        result = json.loads(self.read())
        self.assertTrue(result['readyForNativeLinkMeasurement'])
        self.assertTrue(result['knownMixedVariantInput'])
        self.assertFalse(result['allCodeMembersNativeArm64'])
        self.assertEqual([0xa641, 0xaa64], result['machines'])
        self.assertEqual(1, result['aa64ObjectCount'])
        self.assertEqual(1, result['arm64EcObjectCount'])
        self.assertEqual('ecSymbolIndexMetadata', result['members'][3]['kind'])
        self.assertIsNone(result['members'][3]['machine'])
        self.assertIsNone(result['nativeConsumedOnlyVerified'])

    def test_unknown_metadata_machine_and_structurally_truncated_coff_are_rejected(self):
        for kwargs, reason in [({'special':'/<UNKNOWN>/'}, 'Unsupported ATL archive metadata'),
                               ({'objects':[(0x8664, r'D:\build\foreign.obj')]}, 'Unsupported ATL COFF machine'),
                               ({'payload_override':lambda payload: payload[:2]+struct.pack('<H', 2)+payload[4:]}, 'COFF section headers')]:
            with self.subTest(reason=reason):
                self.prepare(**kwargs)
                self.read(success=False, reason=reason)

    def test_archive_and_member_profile_mismatches_are_rejected(self):
        for field in ('archiveHash', 'memberHash', 'memberOffset'):
            with self.subTest(field=field):
                profile = self.prepare()
                if field == 'archiveHash': profile['sha256'] = '0'*64
                elif field == 'memberHash': profile['members'][-1]['payloadSha256'] = '0'*64
                else: profile['members'][-1]['headerOffset'] += 2
                self.profile_path.write_text(json.dumps(profile))
                self.read(success=False, reason='profile')

    def test_container_truncation_and_invalid_longname_reference_fail_closed(self):
        for malformed in ('truncated', 'longname'):
            with self.subTest(malformed=malformed):
                profile = self.prepare()
                data = bytearray(self.library.read_bytes())
                if malformed == 'truncated': data = data[:-1]
                else:
                    offset = profile['members'][-1]['headerOffset']
                    data[offset:offset+16] = b'/999999'.ljust(16)
                self.library.write_bytes(data)
                profile['bytes'] = len(data); profile['sha256'] = hashlib.sha256(data).hexdigest()
                self.profile_path.write_text(json.dumps(profile))
                self.read(success=False)

    def test_all_full_name_consumption_can_pass_independently_of_load_order(self):
        profile = self.prepare(objects=[(0xa641, r'D:\build\arm64ec\atlbase.obj'),
                                        (0xaa64, r'D:\build\arm64\atlbase.obj'),
                                        (0xaa64, r'D:\build\arm64\qithunk.obj')])
        names = [m['resolvedName'] for m in profile['members'] if m['machine'] == 0xaa64]
        log, mapping = self.witness(list(reversed(names)), names)
        result = json.loads(self.consume(log, mapping))
        self.assertTrue(result['nativeConsumedOnlyVerified'])
        self.assertEqual(2, len(result['consumedMembers']))
        self.assertTrue(all(m['machine'] == 0xaa64 and m['payloadSha256'] for m in result['consumedMembers']))

    def test_any_ec_or_ambiguous_basename_load_fails_even_with_one_native_load(self):
        profile = self.prepare()
        native, ec = profile['members'][-1]['resolvedName'], profile['members'][-2]['resolvedName']
        for names in ([native, ec], ['atlbase.obj'], [native, 'atlbase.obj']):
            with self.subTest(names=names):
                log, mapping = self.witness(names)
                self.consume(log, mapping, success=False)

    def test_unparsed_duplicate_or_wrong_archive_loads_are_not_ignored(self):
        profile = self.prepare(); name = profile['members'][-1]['resolvedName']
        for variant in ('unparsed', 'duplicate', 'wrongArchive', 'empty'):
            with self.subTest(variant=variant):
                log, mapping = self.witness([name])
                if variant == 'unparsed': log.write_text(log.read_text()+' Loaded atls.lib[unparsed member]\n')
                elif variant == 'duplicate': log.write_text(log.read_text()*2)
                elif variant == 'wrongArchive': log, mapping = self.witness([name], library=self.root/'other/atls.lib')
                else: log.write_text('No archive loaded\n')
                self.consume(log, mapping, success=False)

    def test_every_map_member_must_be_unique_native_and_accounted_for(self):
        profile = self.prepare(); native = profile['members'][-1]['resolvedName']; ec = profile['members'][-2]['resolvedName']
        for names in ([native, ec], ['atlbase.obj'], [], [r'D:\unknown\absent.obj']):
            with self.subTest(names=names):
                log, mapping = self.witness([native], names)
                self.consume(log, mapping, success=False)
        log, mapping = self.witness([native]); mapping.write_text(mapping.read_text()+' unparsed atls:member\n')
        self.consume(log, mapping, success=False)

    def test_archive_mutation_after_census_cannot_use_a_stale_consumption_record(self):
        profile = self.prepare(); log, mapping = self.witness([profile['members'][-1]['resolvedName']])
        mutation = self.root/'mutate.ps1'
        mutation.write_text(f"[IO.File]::AppendAllText({quote(self.library)},'changed')")
        command = (f"$library=Read-AtlStaticArchive {quote(self.library)} (Get-Content -Raw {quote(self.profile_path)}|ConvertFrom-Json); "
                   f". {quote(mutation)}; Assert-AtlNativeConsumption @({quote(log)}) {quote(mapping)} $library")
        self.ps(command, success=False, reason='mismatch')

    def test_exact_private_actual_corpus_has_14_members_and_five_variants_each(self):
        required = os.getenv('OPENGEUL_NATIVE_ATL_REQUIRE_CORPUS') == '1'
        source = os.getenv('OPENGEUL_NATIVE_ATL_CORPUS')
        if not required:
            self.skipTest('Private exact actual corpus replay is opt-in; set OPENGEUL_NATIVE_ATL_REQUIRE_CORPUS=1')
        self.assertTrue(source, 'Required exact actual ATL corpus path is missing')
        corpus = pathlib.Path(source)
        profiles = ROOT/'suite/diagnostics/native-atl-source/atl-static-profiles.json'
        for kind in ('regular','spectre'):
            self.assertTrue((corpus/kind/'atls.lib').is_file(), f'Required {kind} exact corpus archive is missing')
        command = (f"$profiles=(Get-Content -Raw {quote(profiles)}|ConvertFrom-Json).profiles; @("+
                   '; '.join(f"Read-AtlStaticArchive {quote(corpus/kind/'atls.lib')} ($profiles|Where-Object kind -eq '{kind}')" for kind in ('regular','spectre'))+
                   ')|ConvertTo-Json -Depth 14 -Compress')
        results = json.loads(self.ps(command))
        self.assertEqual(2, len(results))
        for result in results:
            self.assertEqual(14, len(result['members']))
            self.assertEqual(5, result['aa64ObjectCount'])
            self.assertEqual(5, result['arm64EcObjectCount'])
            self.assertFalse(result['allCodeMembersNativeArm64'])
            self.assertIsNone(result['nativeConsumedOnlyVerified'])
        destination = os.getenv('OPENGEUL_NATIVE_ATL_CORPUS_EVIDENCE')
        if destination:
            target = pathlib.Path(destination)
            self.assertFalse(target.exists(), 'Preserve prior corpus replay evidence')
            target.write_text(json.dumps(results, indent=2)+'\n')


if __name__ == '__main__':
    unittest.main()
