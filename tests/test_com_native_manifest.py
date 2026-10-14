"""Keep exact COM compiler prefix and mandatory four-target suffix boundaries."""
from pathlib import Path
import copy
import hashlib
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import com_source_contract as contract
import prepare_native_tests

NEW_PINS = ('3e5a95c7b4b81b208d56844b252f3d1f50077a4ab28f38ec3746b0b51b8541b0',
            '54781eabb14ad85dbc06d4929b7b6ed00219e4030840e9cfbc8d76aa5ae0e4ca')
OLD_PINS = ('839947cf430e2c3587c235a4ef8980195be1c78f9f8ef68e9f60f9968a1e01c6',
            '8895d687ba3eae0602f2003e0078420b5a844c19f090162b7f4e5315ad262b6c',
            '8fbbc05a985091264101cf14fc4d01563eacef548fd9f7f02e68993e8aebc5e3',
            'db5bb7fa8f838c3597aaed8e4f85ba9acaa5d0f1eca290fe8240d3b045c093a3')

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def materials():
    helpers = {name:sha(ROOT/name) for name in (
        'scripts/com_worker.py','overlay/com-worker/Cargo.toml','overlay/cli-cargo.lock.toml',
        *('overlay/com-worker/src/'+name for name in contract.FILES))}
    config = {'helpers':helpers}
    copied = {'src/opengeul_com_worker/'+name:helpers['overlay/com-worker/src/'+name] for name in contract.FILES}
    ledger = {'formatVersion':1,'fixedClsid':contract.FIXED_CLSID,
        'helperSha256':contract.HELPER_SHA256,
        'originalFiles':copy.deepcopy(contract.REFERENCE['originalFiles']),
        'patchedFiles':copy.deepcopy(contract.REFERENCE['patchedFiles']),
        'copiedFiles':copied,'windowsDependencies':contract._dependencies(config),'qualification':False}
    prepared = {contract.CORE+'/'+name:value for name,value in copied.items()}
    prepared.update({contract.CORE+'/'+name:ledger['patchedFiles'][name] for name in ('src/main.rs','src/mcp_serve.rs')})
    prepared[contract.CORE+'/Cargo.lock']=helpers['overlay/cli-cargo.lock.toml']
    prepared[contract.LEDGER_PATH]=hashlib.sha256(contract.ledger_bytes(ledger,config)).hexdigest()
    return {'ledger':ledger},prepared,{'originalManifestSha256':ledger['patchedFiles']['Cargo.toml']},config

class ComNativeManifestTests(unittest.TestCase):
    def test_current_manifest_only_accepts_exact_four_target_lf_crlf_pins(self):
        self.assertEqual(tuple(contract.REFERENCE['preparedManifestSha256']),NEW_PINS)
        record,prepared,native,config=materials()
        for pin in NEW_PINS:
            prepared[contract.CORE+'/Cargo.toml']=pin
            contract.validate(record,prepared,native,config)
        for pin in (*OLD_PINS,'0'*64):
            prepared[contract.CORE+'/Cargo.toml']=pin
            with self.subTest(pin=pin),self.assertRaisesRegex(ValueError,'compiled native-test manifest'):
                contract.validate(record,prepared,native,config)

    def test_original_and_com_patched_prefix_digests_are_unchanged_and_required(self):
        self.assertEqual(contract.REFERENCE['originalFiles']['Cargo.toml'],'17d3f9d347d3d5c1011e3299ac85f640d9f31e854e442c4696f55da85809700b')
        self.assertEqual(contract.REFERENCE['patchedFiles']['Cargo.toml'],'769745d72376286c03413925eff943af5014db3467e21798d9fc886044d02405')
        record,prepared,native,config=materials();prepared[contract.CORE+'/Cargo.toml']=NEW_PINS[0]
        for key in ('originalFiles','patchedFiles'):
            bad=copy.deepcopy(record);bad['ledger'][key]['Cargo.toml']='0'*64
            with self.subTest(key=key),self.assertRaises(ValueError):contract.validate(bad,prepared,native,config)
        with self.assertRaises(ValueError):contract.validate(record,prepared,{'originalManifestSha256':'0'*64},config)

    def capture_fixture(self, change=None):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        source=Path(temp.name);core=source/contract.CORE;core.mkdir(parents=True)
        prefix='[package]\nname = "rhwp"\nversion = "0.8.7"\nautotests = false\n'
        (core/'Cargo.toml').write_text(prefix)
        prepare_native_tests.prepare(core)
        record,prepared,native,config=materials()
        # This isolated capture fixture probes actual file suffix parsing. The
        # independent validate tests above retain the real immutable COM pins.
        record['ledger']['patchedFiles']['Cargo.toml']=hashlib.sha256(prefix.encode()).hexdigest()
        native['originalManifestSha256']=record['ledger']['patchedFiles']['Cargo.toml']
        manifest=core/'Cargo.toml';body=manifest.read_text()
        if change:body=change(body)
        manifest.write_text(body)
        for name in ('src/main.rs','src/mcp_serve.rs','Cargo.lock'):
            path=core/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('capture fixture\n')
            prepared[contract.CORE+'/'+name]=sha(path)
        prepared[contract.CORE+'/Cargo.toml']=sha(manifest)
        raw=contract.ledger_bytes(record['ledger'],config);(source/contract.LEDGER_PATH).write_bytes(raw)
        prepared[contract.LEDGER_PATH]=hashlib.sha256(raw).hexdigest()
        inventory={name:{'sha256':record['ledger']['copiedFiles']['src/opengeul_com_worker/'+name]} for name in contract.FILES}
        with patch.object(contract,'validate') as validate:
            value=contract.capture(source,prepared,native,config,
                read_json=lambda p:json.loads(p.read_text()),tree=lambda *args:(inventory,[]),sha=sha)
            validate.assert_called_once_with(record,prepared,native,config)
        return value

    def test_capture_accepts_actual_registered_fourth_native_skia_target(self):
        self.capture_fixture()

    def test_capture_rejects_legacy_two_targets_and_missing_required_native_feature(self):
        third='\n[[test]]\nname = "opengeul_stored_lineseg_origin"\npath = "tests/opengeul_stored_lineseg_origin.rs"\nrequired-features = ["native-skia"]\n'
        for change in (lambda body:body.replace(third,''),
                       lambda body:body.replace(third,third.replace('required-features = ["native-skia"]\n','')),
                       lambda body:body+'\n[[test]]\nname = "bypass"\npath = "tests/bypass.rs"\n'):
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,'native-test suffix'):
                self.capture_fixture(change)

    def test_capture_rejects_legacy_three_targets_or_missing_font_native_feature(self):
        fourth='\n[[test]]\nname = "opengeul_pdf_font_resolution"\npath = "tests/opengeul_pdf_font_resolution.rs"\nrequired-features = ["native-skia"]\n'
        for change in (lambda body:body.replace(fourth,''),
                       lambda body:body.replace(fourth,fourth.replace('required-features = ["native-skia"]\n',''))):
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,'native-test suffix'):
                self.capture_fixture(change)

    def test_capture_rejects_coherent_changed_prefix_and_duplicate_marker(self):
        for change in (lambda body:body.replace('version = "0.8.7"','version = "0.8.8"'),
                       lambda body:body+contract.NATIVE_MARKER):
            with self.subTest(change=change),self.assertRaises(ValueError):self.capture_fixture(change)

if __name__=='__main__':unittest.main()
