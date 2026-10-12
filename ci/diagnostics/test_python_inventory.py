import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('python_inventory', Path(__file__).with_name('python_inventory.py'))
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class PeMachineTests(unittest.TestCase):
    def write_pe(self, root, machine, offset=128):
        data = bytearray(max(offset+6, 64))
        data[:2] = b'MZ'
        struct.pack_into('<I', data, 60, offset)
        data[offset:offset+6] = b'PE\0\0'+struct.pack('<H', machine)
        path = root/'python.exe'; path.write_bytes(data)
        return path

    def test_native_arm_and_x64_controller_are_distinct(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(M.pe_machine(self.write_pe(root, 0xAA64)), 0xAA64)
            self.assertEqual(M.pe_machine(self.write_pe(root, 0x8664)), 0x8664)

    def test_malformed_truncated_or_unbounded_header_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); path=root/'python.exe'
            for raw in (b'not PE', b'MZ'+b'\0'*62):
                path.write_bytes(raw)
                with self.assertRaises(ValueError): M.pe_machine(path)
            raw=bytearray(64); raw[:2]=b'MZ'; struct.pack_into('<I',raw,60,1024*1024+1);path.write_bytes(raw)
            with self.assertRaises(ValueError): M.pe_machine(path)


if __name__ == '__main__': unittest.main()
