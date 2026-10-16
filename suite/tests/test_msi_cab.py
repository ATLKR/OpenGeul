"""Exact MSI File-table selection, never flattened architecture collisions."""
import copy
import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

IMPLEMENTATION = Path(__file__).resolve().parents[1] / 'msi_cab.py'
NAMES = ('concrt140.dll', 'msvcp140.dll', 'msvcp140_1.dll', 'msvcp140_2.dll',
         'msvcp140_atomic_wait.dll', 'msvcp140_codecvt_ids.dll', 'vcruntime140.dll',
         'vcruntime140_1.dll', 'vcruntime140_threads.dll')


def module():
    assert IMPLEMENTATION.is_file(), 'MSI cabinet recovery implementation is missing'
    spec = importlib.util.spec_from_file_location('msi_cab_under_test', IMPLEMENTATION)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def files():
    result = []
    for index, name in enumerate(NAMES):
        for arch, delta in (('amd64', 0), ('arm64', 1)):
            result.append({'File': name + '_' + arch + '.DFEFC2FE',
                           'FileName': 'short.dll|' + name, 'Component_': name + '_system_' + arch + '.DFEFC2FE',
                           'Sequence': 100 + 2 * index + delta})
    return result


def media():
    return [{'DiskId': 1, 'LastSequence': 107, 'Cabinet': '#first.cab'},
            {'DiskId': 2, 'LastSequence': 200, 'Cabinet': '#second.cab'}]


def pe(machine=0x8664):
    data = bytearray(128)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 60, 64)
    data[64:68] = b'PE\0\0'
    struct.pack_into('<H', data, 68, machine)
    return bytes(data)


class SelectorTests(unittest.TestCase):
    def test_only_amd64_rows_survive_same_friendly_name_collisions(self):
        selected = module().select_x64_crt(files(), media())
        self.assertEqual(set(NAMES), set(selected))
        for name, metadata in selected.items():
            self.assertEqual(name + '_amd64.DFEFC2FE', metadata['fileId'])
        self.assertEqual('#first.cab', selected['msvcp140_2.dll']['cabinet'])
        self.assertEqual('#second.cab', selected['msvcp140_atomic_wait.dll']['cabinet'])

    def test_component_marker_is_supported_and_non_token_marker_is_not(self):
        table = files()
        table[0]['File'] = 'CRT_payload'
        self.assertEqual('CRT_payload', module().select_x64_crt(table, media())[NAMES[0]]['fileId'])
        table[0]['Component_'] = 'component_amd64evil'
        with self.assertRaisesRegex(ValueError, 'missing'):
            module().select_x64_crt(table, media())

    def test_missing_duplicate_and_conflicting_architecture_are_rejected(self):
        implementation = module()
        missing = [row for row in files() if row['FileName'].split('|')[-1] != NAMES[0]]
        duplicate = files() + [copy.deepcopy(files()[0])]
        mixed = files()
        mixed[0]['Component_'] = 'component_arm64'
        for table in (missing, duplicate, mixed):
            with self.subTest(table=table[:1]), self.assertRaises(ValueError):
                implementation.select_x64_crt(table, media())

    def test_unsafe_file_ids_and_cabinets_are_rejected(self):
        implementation = module()
        for unsafe in ('../evil', r'folder\evil', 'name*', '-switch', 'CON', 'name:stream', 'tail.'):
            table = files()
            table[0]['File'] = unsafe
            with self.subTest(file_id=unsafe), self.assertRaises(ValueError):
                implementation.select_x64_crt(table, media())
        for unsafe in ('external.cab', '#../escape.cab', '#bad\\cab', '#name*', '#'):
            disks = media()
            disks[0]['Cabinet'] = unsafe
            with self.subTest(cabinet=unsafe), self.assertRaises(ValueError):
                implementation.select_x64_crt(files(), disks)

    def test_media_ranges_and_sequences_cannot_be_ambiguous(self):
        implementation = module()
        for disks in ([], [media()[0]], [media()[0], dict(media()[1], DiskId=1)],
                      [media()[0], dict(media()[1], LastSequence=100)]):
            with self.subTest(disks=disks), self.assertRaises(ValueError):
                implementation.select_x64_crt(files(), disks)
        for sequence in (0, -1, True, 'not a number'):
            table = files()
            table[0]['Sequence'] = sequence
            with self.subTest(sequence=sequence), self.assertRaises(ValueError):
                implementation.select_x64_crt(table, media())


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.implementation = module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.msi = self.root / 'source 한글.msi'
        self.msi.write_bytes(b'original signed MSI')
        self.output = self.root / 'recovered'
        self.streams = []
        self.expansions = []
        owner = self

        class Database:
            def __init__(self, path):
                owner.assertEqual(owner.msi.resolve(), path)
            def __enter__(self):
                return self
            def __exit__(self, *args):
                owner.streams.append('closed')
            def file_rows(self):
                return files()
            def media_rows(self):
                return media()
            def extract_stream(self, name, destination, limit):
                owner.streams.append(name)
                destination.write_bytes(b'MSCFfake cabinet')
        self.database = Database

    def expand(self, cabinet, file_id, destination):
        self.expansions.append((cabinet.name, file_id))
        (destination / file_id).write_bytes(pe() + file_id.encode())

    def recover(self, expand=None):
        with patch.object(self.implementation, 'WindowsMsiDatabase', self.database), patch.object(
                self.implementation, 'expand_file', expand or self.expand):
            return self.implementation.recover_x64_crt(self.msi, self.output)

    def test_fresh_recovery_uses_each_embedded_stream_once_and_exact_file_ids(self):
        recovered = self.recover()
        self.assertEqual(set(NAMES), set(recovered))
        self.assertEqual(['first.cab', 'second.cab', 'closed'], self.streams)
        for name, metadata in recovered.items():
            self.assertEqual(self.output / name, metadata['path'])
            self.assertEqual(pe() + metadata['fileId'].encode(), metadata['path'].read_bytes())
            self.assertIn('_amd64.', metadata['fileId'])
            self.assertTrue(metadata['cabinet'].startswith('#'))
        self.assertEqual(9, len(self.expansions))
        self.assertEqual(b'original signed MSI', self.msi.read_bytes())

    def test_existing_output_and_source_are_never_overwritten(self):
        self.output.mkdir()
        (self.output / 'mine').write_bytes(b'keep')
        with self.assertRaises(ValueError):
            self.recover()
        self.assertEqual(b'keep', (self.output / 'mine').read_bytes())
        self.assertEqual([], self.streams)

    def test_arm64_bytes_under_amd64_id_fail_closed_without_partial_output(self):
        def wrong_arch(cabinet, file_id, destination):
            (destination / file_id).write_bytes(pe(0xAA64))
        with self.assertRaisesRegex(ValueError, 'AMD64'):
            self.recover(wrong_arch)
        self.assertFalse(self.output.exists())
        self.assertEqual('closed', self.streams[-1])
        self.assertEqual(b'original signed MSI', self.msi.read_bytes())

    def test_missing_member_and_expansion_failure_preserve_source_and_no_output(self):
        def missing(*args):
            pass
        def failed(*args):
            raise RuntimeError('expand failed')
        for operation in (missing, failed):
            with self.subTest(operation=operation), self.assertRaises((ValueError, RuntimeError)):
                self.recover(operation)
            self.assertFalse(self.output.exists())
            self.assertEqual(b'original signed MSI', self.msi.read_bytes())


    def test_output_created_during_extraction_is_preserved(self):
        def concurrent_output(cabinet, file_id, destination):
            self.expand(cabinet, file_id, destination)
            self.output.mkdir(exist_ok=True)
        with self.assertRaises((ValueError, FileExistsError)):
            self.recover(concurrent_output)
        self.assertTrue(self.output.is_dir())
        self.assertEqual([], list(self.output.iterdir()))

    def test_expansion_uses_windows_tool_exact_filter_and_no_shell(self):
        calls = []
        with patch.object(self.implementation, 'windows_expand_path', return_value=Path('C:/Windows/System32/expand.exe')), patch.object(
                self.implementation.subprocess, 'run', side_effect=lambda *a, **kw: calls.append((a, kw))):
            self.implementation.expand_file(Path('input cab.cab'), 'exact_amd64.Id', Path('target path'))
        args, kwargs = calls[0]
        self.assertEqual(['C:/Windows/System32/expand.exe', '-F:exact_amd64.Id', 'input cab.cab', 'target path'], args[0])
        self.assertFalse(kwargs.get('shell', False))
        self.assertTrue(kwargs['check'])
        self.assertGreater(kwargs['timeout'], 0)


class StreamApiBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.implementation = module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.destination = Path(self.temp.name) / 'cabinet'
        self.database = self.implementation.WindowsMsiDatabase.__new__(self.implementation.WindowsMsiDatabase)

    def test_stream_chunks_are_preserved_and_size_overrun_is_rejected(self):
        import ctypes
        chunks = iter([b'abc', b'def', b''])
        def read(record, field, buffer, size):
            data = next(chunks)
            ctypes.memmove(buffer, data, len(data))
            size._obj.value = len(data)
            return 0
        self.database.read_stream = read
        self.database._copy_stream(31, self.destination, 6)
        self.assertEqual(b'abcdef', self.destination.read_bytes())
        chunks = iter([b'abcd', b'efgh'])
        self.destination.unlink()
        with self.assertRaisesRegex(ValueError, 'bound'):
            self.database._copy_stream(31, self.destination, 6)

    def test_stream_failure_closes_only_owned_record_view_parameters_and_database(self):
        import ctypes
        closed, views = [], []
        self.database.handle = ctypes.c_uint32(8)
        self.database.close_handle = lambda handle: closed.append(getattr(handle, 'value', handle)) or 0
        self.database.close_view = lambda handle: views.append(handle.value) or 0
        def open_view(database, query, output):
            output._obj.value = 21
            return 0
        def fetch(view, output):
            output._obj.value = 31
            return 0
        self.database.open_view = open_view
        self.database.execute_view = lambda view, parameters: 0
        self.database.fetch_view = fetch
        self.database.create_record = lambda count: 41
        self.database.set_string = lambda *args: 0
        self.database.read_stream = lambda *args: 5
        with self.assertRaises(OSError):
            with self.database:
                self.database.extract_stream('cabinet.cab', self.destination, 100)
        self.assertEqual([31, 21, 41, 8], closed)
        self.assertEqual([21], views)
        self.assertEqual(0, self.database.handle.value)

    def test_query_execute_failure_still_closes_view_handle(self):
        import ctypes
        closed = []
        self.database.handle = ctypes.c_uint32(8)
        def open_view(database, query, output):
            output._obj.value = 21
            return 0
        self.database.open_view = open_view
        self.database.execute_view = lambda *args: 1627
        self.database.close_view = lambda handle: 0
        self.database.close_handle = lambda handle: closed.append(handle.value) or 0
        with self.assertRaises(OSError):
            with self.database._view('SELECT a FROM b'):
                self.fail('failed view must never be consumed')
        self.assertEqual([21], closed)


if __name__ == '__main__':
    unittest.main()
