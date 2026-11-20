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
        self.assertEqual(1615,identity['lockBytes'])
        self.assertEqual('69d813eba379f78d20d61becebd995050441fad22665950ee39cb0de4b0227f4',identity['lockSha256'])

    def test_wrong_live_external_or_aliased_selector_is_rejected(self):
        for selector in ('suite/config/runtime.arm64.lock.json',str(self.baseline),
                         './'+self.selector,self.selector.replace('/','\\'),
                         '../'+self.selector,Path(self.selector)):
            with self.subTest(selector=selector),self.assertRaises(ValueError):
                self.load(selector)

    def test_refreshed_baseline_keeps_the_publisher_asset_and_source_identity(self):
        runtime = json.loads(self.raw)['runtime']
        self.assertEqual(runtime['version'], '26.8.2.2')
        self.assertEqual(runtime['size'], 361771008)
        self.assertEqual(runtime['sha256'], '73e6a15f5b2b9e6a87ffad7fdaacd6e992a597b08c911ee7e3baddd15e29bcc7')
        self.assertEqual(runtime['url'], 'https://mirrors.iu13.net/tdf/libreoffice/stable/26.8.2/win/aarch64/LibreOffice_26.8.2_Win_aarch64.msi')
        self.assertEqual(runtime['sourceUrl'], 'https://download.documentfoundation.org/libreoffice/src/26.8.2/libreoffice-26.8.2.2.tar.xz')
        self.assertEqual(runtime['sourceSha256'], 'f0012302d9cc70955bd55890d3aaccf6c55677c4a6a46e1003f996b1b0dae8e7')
        changed = json.loads(self.raw)
        changed['runtime'].update(version='26.8.1.1', size=360910848,
            sha256='97c2173752325af1da3d8731f41c8e09a7c4ad491cf55d9b1069fadb5668e6d7')
        with self.assertRaises(ValueError):
            self.probe.validate_baseline(changed)

    def test_actual_msi_version_query_is_readonly_exact_and_precedes_inventory(self):
        inspect = getattr(self.probe, 'inspect_baseline_msi', None)
        self.assertTrue(callable(inspect), 'Actual MSI ProductVersion guard is required before extraction')
        expected_query = "SELECT `Value` FROM `Property` WHERE `Property` = 'ProductVersion'"
        calls = []
        class Database:
            def __enter__(self): calls.append('enter'); return self
            def __exit__(self, *args): calls.append('exit')
            def _rows(self, query, fields):
                calls.append('query')
                self_outer.assertEqual(query, expected_query)
                self_outer.assertEqual(fields, (('Value', False),))
                if isinstance(self.rows, Exception): raise self.rows
                return self.rows
            def file_rows(self):
                calls.append('files')
                return [{'FileName': 'msvcp140.dll'}, {'FileName': 'unrelated.dat'}]
            def media_rows(self): calls.append('media'); return [{'DiskId': 1}]
        self_outer = self
        database = Database()
        database.rows = [{'Value': '26.8.2.2'}]
        with patch.object(self.probe, 'WindowsMsiDatabase', return_value=database) as factory:
            version, inventory = inspect(Path('public-vendor.msi'), '26.8.2.2')
        factory.assert_called_once_with(Path('public-vendor.msi'))
        self.assertEqual(calls, ['enter', 'query', 'files', 'media', 'exit'])
        self.assertEqual(version, {'productVersion': '26.8.2.2', 'versionVerified': True,
            'baselineOnly': True, 'suiteE2eVerified': False})
        self.assertEqual(inventory, {'files': [{'FileName': 'msvcp140.dll'}], 'media': [{'DiskId': 1}]})
        variants = ([], [{'Value': '26.8.1.1'}], [{'Value': '26.8.2'}],
            [{'Value': '26.8.2.2'}, {'Value': '26.8.2.2'}], [{'Value': b'26.8.2.2'}],
            [{'Value': '26.8.2.2', 'unexpected': 'synthetic'}], OSError(5, 'synthetic'))
        for index, rows in enumerate(variants):
            calls.clear(); database.rows = rows
            with self.subTest(case=index), patch.object(self.probe, 'WindowsMsiDatabase', return_value=database):
                with self.assertRaises((ValueError, OSError)):
                    inspect(Path('public-vendor.msi'), '26.8.2.2')
            self.assertEqual(calls, ['enter', 'query', 'exit'])

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
