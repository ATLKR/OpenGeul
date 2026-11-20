"""Synthetic pack regressions; no runner evidence or document inputs."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock


class EvidenceIndexBudgetTests(unittest.TestCase):
    def setUp(self):
        spec=importlib.util.spec_from_file_location('index_budget_evidence',Path(__file__).resolve().parents[1]/'evidence.py')
        self.p=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.p)
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.src=self.root/'raw';self.src.mkdir();self.dest=self.root/'bounded'

    def put(self,name,data):
        path=self.src/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data);return path

    def packed(self,cap=128*1024):
        with contextlib.redirect_stdout(io.StringIO()):return self.p.pack(self.src,self.dest,'failure',limit=cap)

    def source_hashes(self):
        return {p.relative_to(self.src).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.src.rglob('*') if p.is_file()}

    def assert_bounded(self,report,cap):
        raw=(self.dest/'evidence-index.json').read_bytes()
        self.assertEqual(json.loads(raw),report)
        self.assertNotIn(b'\r\n',raw)
        payload=sum(p.stat().st_size for p in self.dest.rglob('*') if p.is_file() and p.name!='evidence-index.json')
        self.assertEqual(report['copiedBytes'],payload)
        self.assertEqual(report['copiedBytes'],sum(row['bytes'] for row in report['copied']))
        self.assertEqual(self.p.measure([self.dest],cap),payload+len(raw))
        self.assertLessEqual(payload+len(raw),cap)
        self.assertLessEqual(len(report['omitted']),128)
        return raw

    def test_many_utf8_and_escaped_paths_include_final_index_in_cap(self):
        self.put('results.json',b'{"tests":[],"success":false}')
        escaped='"' if os.name!='nt' else '_'
        for n in range(500):self.put(f'{n:04d}-'+('한'*12)+escaped+('a'*150)+'.txt',b'x'*120)
        before=self.source_hashes();report=self.packed();raw=self.assert_bounded(report,128*1024)
        self.assertGreater(len(raw),64*1024)
        self.assertGreater(report['omittedCount'],0)
        self.assertEqual(len(report['omitted']),128)
        self.assertEqual(len(report['copied'])+report['omittedCount'],501)
        self.assertEqual(report['copied'][0]['path'],'results.json')
        self.assertEqual((self.dest/'results.json').read_bytes(),b'{"tests":[],"success":false}')
        self.assertIn('한'.encode('utf-8'),raw)
        if os.name!='nt':self.assertIn(b'\\"',raw)
        self.assertEqual(self.source_hashes(),before)

    def test_metadata_only_exact_limit_and_one_byte_below(self):
        for n in range(8):self.put(f'{n:03d}-'+('한'*15)+'.hwpx',b'owned synthetic excluded bytes')
        initial=self.packed();self.assertEqual(initial['copied'],[])
        cap=4096
        while True:
            value=dict(initial,limitBytes=cap)
            needed=len((json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
            if needed==cap:break
            cap=needed
        self.dest=self.root/'exact';report=self.packed(cap)
        self.assertEqual(len(self.assert_bounded(report,cap)),cap)
        self.dest=self.root/'one-byte-short'
        with self.assertRaises(ValueError):self.packed(cap-1)
        self.assertFalse(self.dest.exists());self.assertEqual(list(self.root.glob('.ci-evidence-*')),[])

    def test_metadata_only_overflow_fails_closed_without_changing_sources(self):
        for n in range(160):self.put(f'{n:03d}-'+('a'*180)+'.hwpx',b'excluded')
        before=self.source_hashes()
        with self.assertRaises(ValueError):self.packed(4096)
        self.assertFalse(self.dest.exists());self.assertEqual(list(self.root.glob('.ci-evidence-*')),[])
        self.assertEqual(self.source_hashes(),before)

    def test_empty_index_only_remains_bounded(self):
        report=self.packed(512);self.assertEqual(report['copied'],[])
        self.assertEqual(report['omittedCount'],0);self.assertEqual(report['sourceBytes'],0)
        self.assert_bounded(report,512)

    def test_many_exclusions_keep_original_omission_bound_and_privacy(self):
        for n in range(240):self.put(f'{n:03d}.hwpx',b'not evidence')
        report=self.packed();self.assertEqual(report['omittedCount'],240)
        self.assertEqual(len(report['omitted']),128);self.assertEqual(report['copied'],[])
        self.assertEqual([p.name for p in self.dest.iterdir()],['evidence-index.json'])
        self.assert_bounded(report,128*1024)

    def test_source_size_change_during_copy_fails_closed(self):
        path=self.put('sample.txt',b'abcd');original=self.p.shutil.copyfile
        for data in (b'abcde',b'abc'):
            with self.subTest(size=len(data)):
                path.write_bytes(b'abcd')
                def changed(source,target):
                    Path(source).write_bytes(data);return original(source,target)
                with mock.patch.object(self.p.shutil,'copyfile',side_effect=changed):
                    with self.assertRaises(ValueError):self.packed()
                self.assertFalse(self.dest.exists());self.assertEqual(list(self.root.glob('.ci-evidence-*')),[])

    def test_destination_size_change_during_copy_fails_closed(self):
        self.put('sample.txt',b'abcd');original=self.p.shutil.copyfile
        def changed(source,target):
            result=original(source,target);Path(target).write_bytes(b'abcde');return result
        with mock.patch.object(self.p.shutil,'copyfile',side_effect=changed):
            with self.assertRaises(ValueError):self.packed()
        self.assertFalse(self.dest.exists());self.assertEqual(list(self.root.glob('.ci-evidence-*')),[])

    def test_nonregular_candidate_rejected_before_open(self):
        path=self.put('pipe.txt',b'');original=Path.lstat;opened=[]
        def special(candidate,*args,**kwargs):
            value=original(candidate,*args,**kwargs)
            if candidate==path:
                fields=list(value);fields[0]=stat.S_IFIFO|0o600;return os.stat_result(fields)
            return value
        def forbidden(candidate,*args,**kwargs):
            if candidate==path:opened.append(True);raise AssertionError('Nonregular file was opened')
            return original_open(candidate,*args,**kwargs)
        original_open=Path.open
        with mock.patch.object(Path,'lstat',special),mock.patch.object(Path,'open',forbidden):
            with self.assertRaises(ValueError):self.packed()
        self.assertEqual(opened,[]);self.assertFalse(self.dest.exists())

    def test_nonregular_root_rejected_without_publishing_empty_report(self):
        path=self.root/'pipe';path.write_bytes(b'');original=Path.lstat;self.src=path
        def special(candidate,*args,**kwargs):
            value=original(candidate,*args,**kwargs)
            if candidate==path:
                fields=list(value);fields[0]=stat.S_IFIFO|0o600;return os.stat_result(fields)
            return value
        with mock.patch.object(Path,'lstat',special):
            with self.assertRaises(ValueError):self.packed()
        self.assertFalse(self.dest.exists())


if __name__=='__main__':unittest.main()
