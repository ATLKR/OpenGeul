import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('wasm_artifacts', ROOT/'scripts/wasm_artifacts.py')
wasm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wasm)

class WasmArtifactsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)/'wasm'; self.folder.mkdir()
        for name in wasm.FILES: (self.folder/name).write_bytes(b'content')
        (self.folder/'rhwp_bg.wasm').write_bytes(b'\0asm\1\0\0\0')
        (self.folder/'package.json').write_text(json.dumps({'version':'0.8.4'}))
    def test_capture_rejects_non_wasm_binary(self):
        (self.folder/'rhwp_bg.wasm').write_bytes(b'not wasm')
        with self.assertRaises(ValueError): wasm.capture(self.folder)
    def test_capture_rejects_wrong_upstream_version(self):
        (self.folder/'package.json').write_text('{"version":"9.9.9"}')
        with self.assertRaises(ValueError): wasm.capture(self.folder)
    def test_source_mismatch_fails_before_install(self):
        wasm.capture(self.folder)
        record=json.loads((self.folder/'OPEN_GEUL_WASM.json').read_text());record['namespaceHelper']='0'*64
        (self.folder/'OPEN_GEUL_WASM.json').write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError,'source mismatch'):wasm.install(self.folder,Path(self.temp.name)/'absent')
    def test_all_payload_hashes_checked_before_overwrite(self):
        wasm.capture(self.folder)
        source=Path(self.temp.name)/'hop';target=source/'apps/studio-host/vendor/rhwp-core';target.mkdir(parents=True)
        (target/'PROVENANCE.json').write_text('{}');(target/'rhwp.js').write_text('original')
        (self.folder/'LICENSE').write_text('tampered')
        with self.assertRaisesRegex(ValueError,'artifact mismatch'):wasm.install(self.folder,source)
        self.assertEqual((target/'rhwp.js').read_text(),'original')
    def test_symlink_input_rejected(self):
        path=self.folder/'rhwp.js';path.unlink()
        try:path.symlink_to(self.folder/'LICENSE')
        except (OSError,NotImplementedError):self.skipTest('Host cannot create symlinks')
        with self.assertRaises(ValueError):wasm.capture(self.folder)

if __name__=='__main__':unittest.main()
