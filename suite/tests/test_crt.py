"""Architecture-specific CRT family and native import closure."""
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from suite.tests.test_payload import pe

class CrtFamilyTests(unittest.TestCase):
    def test_default_x64_nine_and_arm64_eight_are_exact(self):
        from suite.crt import crt_names
        self.assertEqual(crt_names(),crt_names('x64'))
        self.assertEqual(9,len(crt_names()))
        self.assertEqual(8,len(crt_names('arm64')))
        self.assertEqual(set(crt_names())-{'vcruntime140_1.dll'},set(crt_names('arm64')))
        for architecture in ('x86','ARM64','',None,[],True):
            with self.subTest(architecture=architecture),self.assertRaises(ValueError):crt_names(architecture)

def import_image(*,normal=(),delay=(),machine=0xaa64):
    data=bytearray(pe(machine));data.extend(b'\0'*4096)
    optional=152;section=optional+240
    struct.pack_into('<I',data,optional+56,0x3000)
    struct.pack_into('<IIII',data,section+8,len(data)-512,0x1000,len(data)-512,512)
    def offset(rva):return rva-0x1000+512
    cursor=0x1200
    for directory,names,rva,width in ((1,normal,0x1000,20),(13,delay,0x1100,32)):
        if not names:continue
        struct.pack_into('<II',data,optional+112+8*directory,rva,(len(names)+1)*width)
        for i,name in enumerate(names):
            raw=name.encode('ascii')+b'\0';data[offset(cursor):offset(cursor)+len(raw)]=raw
            if directory==1:struct.pack_into('<IIIII',data,offset(rva)+i*width,0x1400,0,0,cursor,0x1450)
            else:struct.pack_into('<IIIIIIII',data,offset(rva)+i*width,1,cursor,0x1480,0x1500,0x1580,0,0,0)
            cursor+=len(raw)
    return bytes(data)


class CrtImportClosureTests(unittest.TestCase):
    def fixture(self,root,architecture='arm64'):
        from suite.crt import crt_names
        program=root/'program';program.mkdir()
        machine=0xaa64 if architecture=='arm64' else 0x8664
        for name in crt_names(architecture):(program/name).write_bytes(pe(machine,dll=True))
        return program

    def test_normal_and_delay_native_imports_require_exact_private_eight(self):
        from suite.crt import validate_crt_imports
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);program=self.fixture(root)
            (program/'office.bin').write_bytes(import_image(normal=('MSVCP140.dll','KERNEL32.dll','WINSPOOL.DRV'),delay=('vcruntime140_threads.dll',)))
            proof=validate_crt_imports(root,architecture='arm64')
            self.assertTrue(proof['passed']);self.assertEqual(9,proof['checkedPeCount'])
            self.assertEqual([dict(path='program/office.bin',normal=['msvcp140.dll'],delay=['vcruntime140_threads.dll'])],proof['imports'])

    def test_normal_and_delay_omitted_one_are_rejected_without_removal(self):
        from suite.crt import validate_crt_imports
        for kind in ('normal','delay'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);program=self.fixture(root)
                raw=import_image(**{kind:('vcruntime140_1.dll',)})
                image=program/'office.bin';image.write_bytes(raw)
                with self.assertRaisesRegex(ValueError,'vcruntime140_1.dll'):
                    validate_crt_imports(root,architecture='arm64')
                self.assertEqual(raw,image.read_bytes())

    def test_noncanonical_vc_names_do_not_hide_an_omitted_dependency(self):
        from suite.crt import validate_crt_imports
        for name in ('vcruntime140_1','vcruntime140_1.DRV','msvcp140d.dll','vccorlib140.dll'):
            with self.subTest(name=name),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);program=self.fixture(root)
                (program/'office.bin').write_bytes(import_image(normal=(name,)))
                with self.assertRaisesRegex(ValueError,'CRT import'):
                    validate_crt_imports(root,architecture='arm64')

    def test_legacy_versioned_microsoft_crt_cannot_escape_normal_or_delay_closure(self):
        from suite.crt import validate_crt_imports
        for name in ('msvcr120.dll','msvcm90.dll'):
            for kind in ('normal','delay'):
                with self.subTest(name=name,kind=kind),tempfile.TemporaryDirectory() as folder:
                    root=Path(folder);program=self.fixture(root)
                    (program/'office.bin').write_bytes(import_image(**{kind:(name,)}))
                    with self.assertRaisesRegex(ValueError,'CRT import'):
                        validate_crt_imports(root,architecture='arm64')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);program=self.fixture(root)
            (program/'msvcr120.dll').write_bytes(pe(0xaa64,dll=True))
            with self.assertRaisesRegex(ValueError,'CRT family'):
                validate_crt_imports(root,architecture='arm64')

    def test_receipt_order_does_not_follow_host_path_case_sorting(self):
        from suite.crt import validate_crt_imports
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);program=self.fixture(root)
            for name in ('Z-native.dll','a-native.dll'):
                (program/name).write_bytes(import_image(normal=('vcruntime140.dll',)))
            # WindowsPath comparison folds case; the receipt must still use
            # portable ordinal relative spellings when replayed on another OS.
            with patch.object(Path,'__lt__',lambda left,right:str(left).casefold()<str(right).casefold()):
                proof=validate_crt_imports(root,architecture='arm64')
            self.assertEqual(['program/Z-native.dll','program/a-native.dll'],[item['path'] for item in proof['imports']])

    def test_x64_retains_its_normal_and_delayed_one_dependency(self):
        from suite.crt import validate_crt_imports
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);program=self.fixture(root,'x64')
            (program/'office.bin').write_bytes(import_image(normal=('vcruntime140_1.dll',),delay=('vcruntime140_1.dll',),machine=0x8664))
            self.assertTrue(validate_crt_imports(root)['passed'])

    def test_missing_private_crt_extra_native_one_and_malformed_imports_fail(self):
        from suite.crt import validate_crt_imports
        for damage in ('missing','extra','malformed'):
            with self.subTest(damage=damage),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);program=self.fixture(root)
                if damage=='missing':(program/'msvcp140.dll').unlink()
                elif damage=='extra':(program/'vcruntime140_1.dll').write_bytes(pe(0xaa64,dll=True))
                else:
                    data=bytearray(import_image(normal=('msvcp140.dll',)))
                    struct.pack_into('<I',data,512+12,0xdeadbeef)
                    (program/'office.bin').write_bytes(data)
                with self.assertRaisesRegex(ValueError,'CRT|import|RVA'):
                    validate_crt_imports(root,architecture='arm64')

if __name__=='__main__':unittest.main()
