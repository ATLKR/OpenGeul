"""Closed numeric failure evidence must never include exception/path/identity values."""
from pathlib import Path
import contextlib
import importlib.util
import io
import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

PACKAGE=Path(__file__).resolve().parents[1]/'engine-build/writer-server-observer-diagnostic'


def load():
    spec=importlib.util.spec_from_file_location('writer_failure_installer',PACKAGE/'install.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def tree(root):
    target=Path(root)/'source';shutil.copytree(PACKAGE/'tests/upstream',target);(target/'include').mkdir();return target


class FailureDiagnostics(unittest.TestCase):
    def test_rejected_source_has_only_numeric_stage_file_error_and_identity_mask(self):
        module=load()
        with tempfile.TemporaryDirectory() as temporary:
            source=tree(temporary);target=source/module.SOURCES[1];target.write_bytes(target.read_bytes()+b'private-synthetic-sentinel')
            output=io.StringIO()
            with contextlib.redirect_stdout(output):code=module.main(['--source-root',str(source),'--target','windows-arm64','--core-commit',module.CORE])
            payload=json.loads(output.getvalue());self.assertEqual(code,1);self.assertFalse(payload['passed'])
            self.assertIn('diagnostic',payload,'Numeric failure boundary has not been implemented')
            self.assertEqual(payload['diagnostic'],{'version':1,'stage':8,'file':2,'detail':8,'errorClass':1,'winerrorKnown':0,'winerror':0,'identityMask':0})
            self.assertNotIn('private-synthetic-sentinel',output.getvalue());self.assertNotIn(str(source),output.getvalue())


if __name__=='__main__':unittest.main()

class IdentityDiagnostics(unittest.TestCase):
    def run_failure(self,module,source):
        output=io.StringIO()
        with contextlib.redirect_stdout(output):code=module.main(['--source-root',str(source),'--target','windows-arm64','--core-commit',module.CORE])
        self.assertEqual(code,1);payload=json.loads(output.getvalue());self.assertNotIn(str(source),output.getvalue());return payload['diagnostic']

    def test_each_identity_field_difference_is_a_bit_without_exporting_values(self):
        from types import SimpleNamespace
        names=('st_dev','st_ino','st_mode','st_size','st_mtime_ns','st_nlink')
        for ordinal,name in enumerate(names):
            with self.subTest(field=ordinal),tempfile.TemporaryDirectory() as temporary:
                module=load();source=tree(temporary);original=module.os.fstat
                def changed(fd):
                    info=original(fd);values={key:getattr(info,key) for key in names};values[name]^=1;return SimpleNamespace(**values)
                with patch.object(module.os,'fstat',changed):diag=self.run_failure(module,source)
                self.assertEqual(diag,{'version':1,'stage':3,'file':10,'detail':4,'errorClass':1,'winerrorKnown':0,'winerror':0,'identityMask':1<<ordinal})

    def test_locked_path_stat_fallback_is_reported_before_any_source_write(self):
        from types import SimpleNamespace
        module=load()
        with tempfile.TemporaryDirectory() as temporary:
            source=tree(temporary);target=source/module.SOURCES[0];before=target.read_bytes();opened=[]
            original_open=Path.open;original_lstat=Path.lstat
            def opening(path,mode='r',*args,**kwargs):
                result=original_open(path,mode,*args,**kwargs)
                if path==target and mode=='r+b':opened.append(path)
                return result
            def fallback(path,*args,**kwargs):
                info=original_lstat(path,*args,**kwargs)
                if path!=target or not opened:return info
                fields={key:getattr(info,key) for key in ('st_dev','st_ino','st_mode','st_size','st_mtime_ns','st_nlink')};fields['st_dev']^=1;fields['st_ino']^=1;fields['st_nlink']=0;return SimpleNamespace(**fields)
            with patch.object(Path,'open',opening),patch.object(Path,'lstat',fallback):diag=self.run_failure(module,source)
            self.assertEqual(diag,{'version':1,'stage':14,'file':1,'detail':10,'errorClass':1,'winerrorKnown':0,'winerror':0,'identityMask':35})
            self.assertEqual(target.read_bytes(),before);self.assertFalse((source/'include/opengeul_writer_observer').exists())

    def test_windows_error_is_numeric_and_raw_error_is_not_printed(self):
        module=load()
        with tempfile.TemporaryDirectory() as temporary:
            source=tree(temporary);original_open=Path.open
            def denied(path,mode='r',*args,**kwargs):
                if path.name=='source-lock.json' and mode=='rb':
                    error=PermissionError(13,'private-synthetic-error');error.winerror=32;raise error
                return original_open(path,mode,*args,**kwargs)
            with patch.object(Path,'open',denied):diag=self.run_failure(module,source)
            self.assertEqual(diag,{'version':1,'stage':3,'file':10,'detail':3,'errorClass':3,'winerrorKnown':1,'winerror':32,'identityMask':0})

class ExceptionCompatibility(unittest.TestCase):
    def test_os_error_family_is_preserved_for_non_cli_callers(self):
        module=load()
        with tempfile.TemporaryDirectory() as temporary:
            source=tree(temporary);original_open=Path.open
            def denied(path,mode='r',*args,**kwargs):
                if path.name=='source-lock.json' and mode=='rb':raise PermissionError(13,'private-synthetic-error')
                return original_open(path,mode,*args,**kwargs)
            code=0
            with patch.object(Path,'open',denied):
                try:module.install(source,'windows-arm64')
                except BaseException as error:code=3 if type(error) is PermissionError else 1
            self.assertEqual(code,3)

class SuccessCompatibility(unittest.TestCase):
    def test_success_receipt_and_authenticated_outputs_match_frozen_installer(self):
        baseline=Path(__file__).parent/'fixtures/writer-installer-auth-before.py'
        spec=importlib.util.spec_from_file_location('writer_frozen_installer',baseline)
        frozen=importlib.util.module_from_spec(spec);spec.loader.exec_module(frozen);changed=load()
        with tempfile.TemporaryDirectory() as a,tempfile.TemporaryDirectory() as b:
            first,second=tree(a),tree(b)
            expected=frozen.install(first,'windows-arm64',package=PACKAGE);actual=changed.install(second,'windows-arm64')
            self.assertEqual(actual,expected);self.assertNotIn('diagnostic',actual)
            lock=json.loads((PACKAGE/'source-lock.json').read_text())
            for item in lock['sources']+lock['payloads']:
                self.assertEqual((first/item['path']).read_bytes(),(second/item['path']).read_bytes())
