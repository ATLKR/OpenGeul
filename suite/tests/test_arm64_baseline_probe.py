"""Portable official-baseline selection guards; no Windows/MSI/network execution."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def probe_module():
    spec = importlib.util.spec_from_file_location('arm64_baseline_probe', ROOT/'suite/scripts/arm64-native-probe.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Arm64BaselineProbeTests(unittest.TestCase):
    def setUp(self):
        self.probe = probe_module()
        self.assertTrue(callable(getattr(self.probe,'load_baseline',None)),
                        'Explicit independently authenticated official baseline selector is required')
        self.temporary = tempfile.TemporaryDirectory(prefix='arm64-baseline-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.selector = self.probe.BASELINE_SELECTOR
        self.baseline = self.root/self.selector
        self.baseline.parent.mkdir(parents=True)
        self.raw = (ROOT/self.selector).read_bytes()
        self.baseline.write_bytes(self.raw)

    def load(self, selector=None):
        return self.probe.load_baseline(self.selector if selector is None else selector,self.root)

    def test_selection_ignores_live_production_lock_and_current_directory(self):
        first, identity = self.load()
        live = self.root/'suite/config/runtime.arm64.lock.json'
        live.write_text('{"architecture":"arm64","runtime":{"format":"zip","name":"test sentinel"}}')
        elsewhere = self.root/'unrelated';elsewhere.mkdir()
        old = Path.cwd()
        try:
            os.chdir(elsewhere)
            second, second_identity = self.load()
        finally:
            os.chdir(old)
        self.assertEqual(first,second)
        self.assertEqual(identity,second_identity)
        self.assertEqual('official-arm64-msi-baseline',identity['inputRole'])
        self.assertEqual(self.selector,identity['lockPath'])
        self.assertEqual(first['runtime'],json.loads(self.raw)['runtime'])
        self.assertEqual('msi',identity['format'])
        self.assertEqual(1618,identity['lockBytes'])
        self.assertEqual('f58107858b83e29c7b98aea1dc41141a637caeba1f6e9a8e3b84395968c1b0c1',identity['lockSha256'])

    def test_wrong_live_external_or_aliased_selector_is_rejected(self):
        for selector in ('suite/config/runtime.arm64.lock.json',str(self.baseline),
                         './'+self.selector,self.selector.replace('/','\\'),
                         '../'+self.selector,Path(self.selector)):
            with self.subTest(selector=selector),self.assertRaises(ValueError):
                self.load(selector)

    def test_missing_directory_and_byte_drift_are_rejected(self):
        self.baseline.unlink()
        with self.assertRaises((ValueError,OSError)):self.load()
        self.baseline.mkdir()
        with self.assertRaises((ValueError,OSError)):self.load()
        self.baseline.rmdir()
        self.baseline.write_bytes(self.raw.replace(b'LibreOffice',b'libreOffice',1))
        with self.assertRaisesRegex(ValueError,'pin|SHA256|identity'):self.load()

    def test_reparse_metadata_is_rejected_without_privileged_link_creation(self):
        original = Path.lstat
        def observed(path, *args, **kwargs):
            value=original(path,*args,**kwargs)
            if path != self.baseline:return value
            return types.SimpleNamespace(st_mode=value.st_mode,st_file_attributes=0x400)
        with patch.object(Path,'lstat',observed),self.assertRaises(ValueError):self.load()

    def test_path_and_handle_metadata_models_are_not_conflated(self):
        original=self.probe.os.fstat
        calls=0
        def observed(fd):
            nonlocal calls
            calls+=1
            value=original(fd)
            return types.SimpleNamespace(**{key:getattr(value,key) for key in
                ('st_mode','st_size','st_mtime_ns')},st_dev=value.st_dev+1,
                st_ino=value.st_ino+1,st_ctime_ns=value.st_ctime_ns+100)
        with patch.object(self.probe.os,'fstat',observed):
            self.assertEqual('msi',self.load()[1]['format'])
        self.assertEqual(2,calls)
        calls=0
        def changing(fd):
            value=observed(fd)
            value.st_ctime_ns+=calls
            return value
        with patch.object(self.probe.os,'fstat',changing), \
                self.assertRaisesRegex(ValueError,'changed while reading'):
            self.load()

    def test_schema_architecture_format_and_asset_role_are_explicit(self):
        official=json.loads(self.raw)
        self.probe.validate_baseline(official)
        changes=[('schemaVersion',2),('architecture','x64'),('format','zip'),('asset','other.msi')]
        for key,value in changes:
            changed=json.loads(self.raw)
            if key=='format':changed['runtime']['format']=value
            elif key=='asset':changed['runtime']['url']=value
            else:changed[key]=value
            with self.subTest(field=key),self.assertRaises(ValueError):
                self.probe.validate_baseline(changed)

    def test_source_build_metadata_is_rejected_even_on_msi_shaped_descriptor(self):
        for source_build in (None,{}, {'kind':'source-built'}):
            changed=json.loads(self.raw)
            changed['runtime']['sourceBuild']=source_build
            with self.subTest(sourceBuild=source_build),self.assertRaisesRegex(ValueError,'sourceBuild'):
                self.probe.validate_baseline(changed)

    def test_invalid_input_rejects_before_output_or_native_side_effects(self):
        output=self.root/'must-not-be-created'
        variants=[('suite/config/runtime.arm64.lock.json',self.raw),
                  (self.selector,b'{}')]
        for selector,raw in variants:
            self.baseline.write_bytes(raw)
            with self.subTest(selector=selector),patch.object(self.probe,'ROOT',self.root), \
                    patch('sys.argv',['probe','--baseline-lock',selector,'--output',str(output)]), \
                    patch.object(self.probe,'download_locked') as download, \
                    patch.object(self.probe,'WindowsMsiDatabase') as msi, \
                    patch.object(self.probe.ctypes,'WinDLL',create=True) as native, \
                    patch.object(self.probe.subprocess,'run') as process, \
                    patch.object(Path,'mkdir') as mkdir:
                with self.assertRaises((ValueError,OSError)):self.probe.main()
                for operation in (download,msi,native,process,mkdir):operation.assert_not_called()
            self.assertFalse(output.exists())

    def test_workflow_passes_the_finite_selector_and_retains_both_input_triggers(self):
        import shlex
        text=(ROOT/'.github/workflows/office-arm64-probe.yml').read_text()
        command=next(line.strip() for line in text.splitlines()
                     if line.strip().startswith('python suite/scripts/arm64-native-probe.py '))
        arguments=shlex.split(command)
        selector=arguments[arguments.index('--baseline-lock')+1]
        selected,identity=self.probe.load_baseline(selector,ROOT)
        self.assertEqual('arm64',selected['architecture'])
        self.assertEqual(self.selector,identity['lockPath'])
        paths=text.split('    paths:\n',1)[1].split('  workflow_dispatch:',1)[0]
        self.assertIn('      - '+self.selector+'\n',paths)
        self.assertIn('      - suite/config/runtime.arm64.lock.json\n',paths)


if __name__=='__main__':unittest.main()
