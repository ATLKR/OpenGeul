"""File-backed import tables expose missing runtime DLLs without executing PEs."""
from pathlib import Path
import struct
import tempfile
import unittest

try:
    from suite.pe_imports import read_pe_imports
except ModuleNotFoundError as error:
    if error.name != 'suite.pe_imports':
        raise
    read_pe_imports = None

from suite.tests.test_payload import pe


def imports_pe(normal=(), delay=(), *, pe32=False):
    """Two real PE sections with independent descriptor, name, and thunk RVAs."""
    data = bytearray(0xe00)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 60, 0x80)
    data[0x80:0x84] = b'PE\0\0'
    optional_size = 224 if pe32 else 240
    struct.pack_into('<HHIIIHH', data, 0x84, 0x14c if pe32 else 0xaa64,
                     2, 0, 0, 0, optional_size, 0x2002)
    optional = 0x98
    struct.pack_into('<H', data, optional, 0x10b if pe32 else 0x20b)
    struct.pack_into('<II', data, optional + 32, 0x1000, 0x200)
    struct.pack_into('<II', data, optional + 56, 0x3000, 0x200)
    directory = optional + (96 if pe32 else 112)
    struct.pack_into('<I', data, directory - 4, 16)
    section = optional + optional_size
    for index, (name, rva, raw) in enumerate(((b'.idata', 0x1000, 0x200),
                                             (b'.didat', 0x2000, 0x800))):
        row = section + index * 40
        data[row:row + len(name)] = name
        struct.pack_into('<IIII', data, row + 8, 0x600, rva, 0x600, raw)
    if normal:
        struct.pack_into('<II', data, directory + 8, 0x1000, (len(normal) + 1) * 20)
        for index, name in enumerate(normal):
            rva = 0x1180 + index * 0x80
            struct.pack_into('<IIIII', data, 0x200 + index * 20,
                             0, 0, 0, rva, 0x1500)
            encoded = name.encode('ascii') + b'\0'
            data[0x200 + rva - 0x1000:0x200 + rva - 0x1000 + len(encoded)] = encoded
    if delay:
        struct.pack_into('<II', data, directory + 13 * 8, 0x2000, (len(delay) + 1) * 32)
        for index, name in enumerate(delay):
            rva = 0x2180 + index * 0x80
            struct.pack_into('<IIIIIIII', data, 0x800 + index * 32,
                             1, rva, 0x2500, 0x2510, 0x2520, 0, 0, 0)
            encoded = name.encode('ascii') + b'\0'
            data[0x800 + rva - 0x2000:0x800 + rva - 0x2000 + len(encoded)] = encoded
    return data


def directory_offset(index, *, pe32=False):
    return 0x98 + (96 if pe32 else 112) + index * 8


class PeImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'native.dll'

    def parse(self, data):
        self.assertTrue(callable(read_pe_imports), 'The PE import reader is missing')
        self.path.write_bytes(data)
        result = read_pe_imports(self.path)
        self.assertEqual(self.path.read_bytes(), data, 'Import inspection changed the supplied PE')
        return result

    def rejects(self, data, message=None):
        self.assertTrue(callable(read_pe_imports), 'The PE import reader is missing')
        self.path.write_bytes(data)
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, message or '.'):
            read_pe_imports(self.path)
        self.assertEqual(self.path.read_bytes(), before)

    def test_empty_directory_tables_accept_existing_arm64_x64_and_pe32_fixtures(self):
        for machine in (0xaa64, 0x8664, 0x14c):
            with self.subTest(machine=machine):
                self.assertEqual({'normal': (), 'delay': ()}, self.parse(pe(machine)))

    def test_normal_imports_are_normalized_unique_module_basenames(self):
        result = self.parse(imports_pe(('VCRUNTIME140.DLL', 'KERNEL32.dll', 'vcruntime140.dll', 'WINSPOOL.DRV')))
        self.assertEqual({'normal': ('kernel32.dll', 'vcruntime140.dll', 'winspool.drv'), 'delay': ()}, result)

    def test_delay_import_exposes_an_omitted_vcruntime_dependency(self):
        result = self.parse(imports_pe(('KERNEL32.dll',), ('VCRUNTIME140_1.DLL', 'USER32.dll')))
        supplied = {'kernel32.dll', 'user32.dll'}
        imported = set(result['normal']) | set(result['delay'])
        self.assertEqual({'vcruntime140_1.dll'}, imported - supplied)
        self.assertEqual(('user32.dll', 'vcruntime140_1.dll'), result['delay'])

    def test_pe32_normal_and_rva_delay_tables_are_supported(self):
        result = self.parse(imports_pe(('MSVCP140.dll',), ('VCRUNTIME140_1.dll',), pe32=True))
        self.assertEqual({'normal': ('msvcp140.dll',), 'delay': ('vcruntime140_1.dll',)}, result)

    def test_directory_size_can_include_nonzero_names_thunks_and_partial_padding(self):
        data = imports_pe(('kernel32.dll',), ('vcruntime140_1.dll',))
        struct.pack_into('<I', data, directory_offset(1) + 4, 0x5f3)
        struct.pack_into('<I', data, directory_offset(13) + 4, 0x5f5)
        data[0x700:0x707] = b'thunks!'
        self.assertEqual(('kernel32.dll',), self.parse(data)['normal'])

    def test_declared_directory_ranges_may_overlap_when_descriptor_arrays_do_not(self):
        data = imports_pe(('kernel32.dll',), ('vcruntime140_1.dll',))
        struct.pack_into('<I', data, directory_offset(1) + 4, 0x1600)
        self.assertEqual(('vcruntime140_1.dll',), self.parse(data)['delay'])

    def test_descriptor_and_name_reads_can_cross_adjacent_section_mappings(self):
        for descriptor_rva, name_rva in ((0x1ff0, 0x21fc), (0x1000, 0x1ffc)):
            data = imports_pe()
            data.extend(b'\0' * (0x1800 - len(data)))
            section = 0x98 + 240
            struct.pack_into('<IIII', data, section + 8, 0x1000, 0x1000, 0x1000, 0x200)
            struct.pack_into('<I', data, section + 40 + 20, 0x1200)
            struct.pack_into('<II', data, directory_offset(1), descriptor_rva, 40)
            descriptor_raw = 0x200 + descriptor_rva - 0x1000
            struct.pack_into('<IIIII', data, descriptor_raw, 0, 0, 0, name_rva, 0x1800)
            name = b'VCRUNTIME140_1.DLL\0'
            name_raw = 0x200 + name_rva - 0x1000
            data[name_raw:name_raw + len(name)] = name
            with self.subTest(descriptor=descriptor_rva, name=name_rva):
                self.assertEqual(('vcruntime140_1.dll',), self.parse(data)['normal'])

    def test_header_backed_name_rva_is_accepted(self):
        data = imports_pe(('kernel32.dll',))
        data[0x40:0x4d] = b'kernel32.dll\0'
        struct.pack_into('<I', data, 0x200 + 12, 0x40)
        self.assertEqual(('kernel32.dll',), self.parse(data)['normal'])

    def test_missing_dos_pe_or_optional_headers_are_rejected(self):
        original = imports_pe(('kernel32.dll',))
        variants = [b'', original[:63], original[:0x84], original[:0x98 + 100]]
        for offset, replacement in ((0, b'NO'), (0x80, b'BAD!'), (0x98, b'\x07\x01')):
            data = bytearray(original);data[offset:offset + len(replacement)] = replacement
            variants.append(data)
        data = bytearray(original);struct.pack_into('<I', data, 60, 0xfffffff0);variants.append(data)
        for index, data in enumerate(variants):
            with self.subTest(case=index):self.rejects(data)

    def test_optional_directory_count_and_section_table_must_fit_headers(self):
        original = imports_pe(('kernel32.dll',))
        for offset, value, fmt in ((0x84 + 2, 97, '<H'), (0x84 + 16, 120, '<H'),
                                   (0x98 + 108, 17, '<I'), (0x84 + 2, 0, '<H')):
            data = bytearray(original);struct.pack_into(fmt, data, offset, value)
            with self.subTest(offset=offset, value=value):self.rejects(data)

    def test_file_and_section_alignment_require_supported_nonambiguous_layouts(self):
        # PE/COFF: FileAlignment is a power of two from512 through65536;
        # SectionAlignment>=FileAlignment. This reader deliberately excludes
        # low-alignment images rather than applying standard RVA mapping to them.
        cases = [(0x1000, value) for value in (0, 1, 0x100, 0x1ff, 0x201, 0x20000)]
        cases += [(value, 0x200) for value in (0, 0x200, 0x800, 0x1800)]
        cases += [(0x1000, 0x2000)]
        for section_alignment, file_alignment in cases:
            data = imports_pe()
            struct.pack_into('<II', data, 0x98 + 32, section_alignment, file_alignment)
            with self.subTest(section=section_alignment, file=file_alignment):
                self.rejects(data, 'alignment|Alignment')

    def test_raw_section_pointer_size_and_rva_must_follow_declared_alignments(self):
        section = 0x98 + 240
        variants = []
        data = imports_pe();struct.pack_into('<I', data, section + 12, 0x1001);variants.append(data)
        data = imports_pe();struct.pack_into('<I', data, section + 16, 0x5ff);variants.append(data)
        data = imports_pe();struct.pack_into('<II', data, section + 16, 0x400, 0x201);variants.append(data)
        for index, data in enumerate(variants):
            with self.subTest(case=index):self.rejects(data, 'align')

    def test_header_and_image_sizes_follow_alignment_and_cover_loaded_sections(self):
        for headers in (0, 0x1ff, 0x201):
            data = imports_pe();struct.pack_into('<I', data, 0x98 + 60, headers)
            with self.subTest(headers=headers):self.rejects(data, 'header|Header')
        for image_size in (0, 0x3001, 0x2000):
            data = imports_pe();struct.pack_into('<I', data, 0x98 + 56, image_size)
            with self.subTest(image_size=image_size):self.rejects(data, 'image|Image')

    def test_undeclared_later_directory_is_absent(self):
        data = imports_pe(('kernel32.dll',))
        struct.pack_into('<I', data, 0x98 + 108, 2)
        self.assertEqual({'normal': ('kernel32.dll',), 'delay': ()}, self.parse(data))

    def test_import_directory_requires_both_rva_and_size_and_a_bounded_extent(self):
        for index in (1, 13):
            for rva, size in ((0, 40), (0x1000, 0), (0xfffffff0, 64), (0x1000, 1048577)):
                data = imports_pe();struct.pack_into('<II', data, directory_offset(index), rva, size)
                with self.subTest(index=index, rva=rva, size=size):self.rejects(data)

    def test_directories_require_a_complete_zero_descriptor_terminator(self):
        for index, width in ((1, 20), (13, 32)):
            for size in (width - 1, width, width + 1):
                data = imports_pe(('kernel32.dll',), ('vcruntime140_1.dll',))
                struct.pack_into('<I', data, directory_offset(index) + 4, size)
                with self.subTest(index=index, size=size):self.rejects(data)

    def test_nonzero_descriptor_without_a_name_is_rejected(self):
        for index, offset in ((1, 0x200 + 12), (13, 0x800 + 4)):
            data = imports_pe(('kernel32.dll',), ('vcruntime140_1.dll',))
            struct.pack_into('<I', data, offset, 0)
            with self.subTest(index=index):self.rejects(data)

    def test_rva_mapping_rejects_missing_virtual_only_or_truncated_raw_bytes(self):
        original = imports_pe(('kernel32.dll',))
        for rva in (0x1800, 0x2600, 0xfffffff0):
            data = bytearray(original);struct.pack_into('<I', data, 0x200 + 12, rva)
            with self.subTest(rva=rva):self.rejects(data)
        data = bytearray(original)
        struct.pack_into('<I', data, 0x98 + 240 + 8, 0x800)
        struct.pack_into('<I', data, 0x200 + 12, 0x1700)
        self.rejects(data)
        self.rejects(original[:-1])

    def test_overlapping_virtual_or_raw_sections_are_ambiguous(self):
        for field_offset, value in ((12, 0x1200), (20, 0x400)):
            data = imports_pe(('kernel32.dll',))
            struct.pack_into('<I', data, 0x98 + 240 + 40 + field_offset, value)
            with self.subTest(field=field_offset):self.rejects(data)

    def test_normal_and_delay_descriptor_arrays_must_not_overlap(self):
        data = imports_pe()
        struct.pack_into('<II', data, directory_offset(1), 0x1000, 20)
        struct.pack_into('<II', data, directory_offset(13), 0x1000, 32)
        self.rejects(data, 'overlap|ambiguous')

    def test_import_names_are_bounded_ascii_basenames(self):
        for name in (b'', b'../bad.dll', b'C:evil.dll', b'bad\\evil.dll', b'white space.dll',
                     b'bad\xff.dll', b'.', b'bad.dll.', b'x' * 256):
            data = imports_pe(('kernel32.dll',))
            data[0x380:0x580] = b'X' * 0x200
            if len(name) <= 255:
                data[0x380:0x380 + len(name) + 1] = name + b'\0'
            with self.subTest(name=name[:32]):self.rejects(data)

    def test_delay_legacy_va_and_unknown_attribute_bits_are_explicitly_rejected(self):
        for attrs in (0, 2, 3, 0xffffffff):
            data = imports_pe(delay=('vcruntime140_1.dll',))
            struct.pack_into('<I', data, 0x800, attrs)
            with self.subTest(attrs=attrs):self.rejects(data, 'attribute|legacy')

    def test_descriptor_count_is_bounded_even_when_every_name_is_valid(self):
        data = imports_pe()
        data.extend(b'\0' * (0x20200 - len(data)))
        struct.pack_into('<H', data, 0x84 + 2, 1)
        struct.pack_into('<IIII', data, 0x98 + 240 + 8, 0x20000, 0x1000, 0x20000, 0x200)
        struct.pack_into('<I', data, 0x98 + 56, 0x21000)
        struct.pack_into('<II', data, directory_offset(1), 0x1000, 4098 * 20)
        for index in range(4097):
            struct.pack_into('<IIIII', data, 0x200 + index * 20, 0, 0, 0, 0x1f000, 0x1f100)
        data[0x1e200:0x1e20d] = b'kernel32.dll\0'
        self.rejects(data, 'count|bound|many')


if __name__ == '__main__':
    unittest.main()
