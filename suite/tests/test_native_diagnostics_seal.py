"""Final event-byte seals preserve the existing owned worker cleanup proof."""
import copy
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'worker'))
from suite.tests.test_native_cleanup_receipt import receipt


class NativeDiagnosticsSealTests(unittest.TestCase):
    def setUp(self):
        self.m=importlib.import_module('native_diagnostics')
        self.root=Path(self.enterContext(tempfile.TemporaryDirectory())).resolve(strict=True)
        self.profile=self.root/'profile';self.profile.mkdir()
        self.evidence=self.root/'evidence';self.evidence.mkdir()
        self.snapshots=0
        owner=self
        class Witness:
            def snapshot(self):owner.snapshots+=1;return [dict(pid=20,creationTime=123)]
            def close(self):pass
        process=SimpleNamespace(pid=10,open_diagnostic_witnesses=Witness)
        self.collector=self.m.NativeDiagnostics(self.evidence,self.profile,process)
        self.events=self.collector.directory/'events.jsonl'

    def manifest(self):
        return json.loads((self.collector.directory/'manifest.json').read_text(encoding='utf-8'))

    def prepare(self):
        self.collector.record('before-owned-shutdown')
        self.collector.record('after-owned-shutdown')
        self.collector.archive_crash();self.collector.close()

    def assert_seal(self):
        manifest=self.manifest()
        event=next(item for item in manifest['files'] if item['path']=='events.jsonl')
        data=self.events.read_bytes()
        self.assertEqual(event,dict(path='events.jsonl',bytes=len(data),sha256=hashlib.sha256(data).hexdigest()))
        self.assertTrue(manifest['archiveComplete'])
        return manifest

    def test_final_shutdown_seals_exact_events_without_changing_proof_or_query_count(self):
        self.prepare();proof=receipt();before=copy.deepcopy(proof)
        self.collector.record_shutdown(proof)
        manifest=self.manifest()
        self.assertEqual({item['path'] for item in manifest['files']},{'events.jsonl','shutdown.json'})
        self.assert_seal()
        self.assertEqual(proof,before)
        raw=(json.dumps(proof,ensure_ascii=False,allow_nan=False,indent=2)+'\n').encode()
        self.assertEqual((self.collector.directory/'shutdown.json').read_bytes(),raw)
        self.assertEqual(self.snapshots,2,'Sealing must not add process or model observations')

    def test_failed_cleanup_retry_invalidates_before_append_and_reseals_all_phases(self):
        self.prepare();proof=receipt();proof.update(success=False,gracefulQualified=False)
        self.collector.record_shutdown(proof)
        original=self.events.read_bytes();opened=[];actual_open=Path.open
        def observe(path,mode='r',*args,**kwargs):
            if path==self.events and mode=='a':
                opened.append(self.manifest())
            return actual_open(path,mode,*args,**kwargs)
        with patch.object(Path,'open',observe):self.collector.record('shutdown-unconfirmed')
        self.assertEqual(len(opened),1)
        self.assertFalse(opened[0]['archiveComplete'])
        self.assertNotIn('events.jsonl',{item['path'] for item in opened[0]['files']})
        self.assertTrue(self.events.read_bytes().startswith(original))
        self.collector.record_shutdown(proof)
        self.assert_seal()
        lines=self.events.read_text().splitlines()
        self.assertEqual([json.loads(line)['phase'] for line in lines],
            ['before-owned-shutdown','after-owned-shutdown','shutdown-unconfirmed'])
        self.assertEqual(sum(item['path']=='events.jsonl' for item in self.manifest()['files']),1)
        self.assertEqual(self.snapshots,3)

    def test_missing_empty_and_oversized_events_cannot_reuse_an_old_complete_seal(self):
        self.prepare();self.collector.record_shutdown(receipt());original=self.events.read_bytes()
        for failure in ('missing','empty','oversized'):
            with self.subTest(failure=failure):
                self.events.write_bytes(original)
                if failure=='missing':self.events.unlink()
                elif failure=='empty':self.events.write_bytes(b'')
                else:
                    with self.events.open('wb') as stream:stream.truncate(16*1024*1024+1)
                with self.assertRaises(ValueError):self.collector.record_shutdown(receipt())
                self.assertFalse(self.manifest()['archiveComplete'])
                self.assertNotIn('events.jsonl',{item['path'] for item in self.manifest()['files']})

    def test_linked_event_stream_is_rejected_without_reading_its_target(self):
        self.prepare();self.collector.record_shutdown(receipt())
        outside=self.root/'synthetic-private-document';outside.write_bytes(b'synthetic unrelated bytes')
        self.events.unlink()
        try:self.events.symlink_to(outside)
        except OSError:self.skipTest('Owned synthetic symlink creation unavailable')
        opened=[];actual_open=Path.open
        def observe(path,mode='r',*args,**kwargs):
            if path==self.events and mode=='rb':opened.append(path)
            return actual_open(path,mode,*args,**kwargs)
        with patch.object(Path,'open',observe),self.assertRaises(ValueError):
            self.collector.record_shutdown(receipt())
        self.assertEqual(opened,[])
        self.assertFalse(self.manifest()['archiveComplete'])

    def test_hard_linked_event_stream_is_rejected_before_hashing(self):
        self.prepare()
        try:os.link(self.events,self.root/'synthetic-event-alias')
        except OSError:self.skipTest('Owned synthetic hard-link creation unavailable')
        with self.assertRaises(ValueError):self.collector.record_shutdown(receipt())
        self.assertFalse(self.manifest()['archiveComplete'])

    def test_changed_open_event_identity_cannot_be_sealed(self):
        self.prepare();actual=os.fstat;calls=[]
        def changing(fd):
            value=actual(fd);calls.append(fd)
            return SimpleNamespace(st_mode=value.st_mode,st_dev=value.st_dev,st_ino=value.st_ino,
                st_size=value.st_size,st_nlink=value.st_nlink,st_mtime_ns=value.st_mtime_ns+(1 if len(calls)>1 else 0))
        with patch.object(self.m.os,'fstat',side_effect=changing),self.assertRaises(ValueError):
            self.collector.record_shutdown(receipt())
        self.assertFalse(self.manifest()['archiveComplete'])

    def test_partial_failed_append_is_sticky_and_cannot_be_blessed_by_a_later_hash(self):
        self.prepare();self.collector.record_shutdown(receipt())
        actual_open=Path.open;primary=OSError('synthetic original append failure')
        class Partial:
            def __enter__(self):self.stream=actual_open(owner.events,'a',encoding='utf-8');return self
            def write(self,value):self.stream.write(value[:7]);self.stream.flush();raise primary
            def __exit__(self,*args):self.stream.close()
        owner=self
        def partially(path,mode='r',*args,**kwargs):
            return Partial() if path==self.events and mode=='a' else actual_open(path,mode,*args,**kwargs)
        with patch.object(Path,'open',partially),self.assertRaises(OSError) as caught:
            self.collector.record('shutdown-unconfirmed')
        self.assertIs(caught.exception,primary)
        self.assertFalse(self.manifest()['archiveComplete'])
        self.collector.record('after-owned-shutdown')
        with self.assertRaises(ValueError):self.collector.record_shutdown(receipt())
        self.assertFalse(self.manifest()['archiveComplete'])

    def test_short_append_is_sticky_without_retrying_the_phase_write(self):
        self.prepare();self.collector.record_shutdown(receipt())
        actual_open=Path.open;calls=[];owner=self
        class Short:
            def __enter__(self):self.stream=actual_open(owner.events,'a',encoding='utf-8');return self
            def write(self,value):calls.append(len(value));self.stream.write(value[:7]);return 7
            def __exit__(self,*args):self.stream.close()
        def short(path,mode='r',*args,**kwargs):
            return Short() if path==self.events and mode=='a' else actual_open(path,mode,*args,**kwargs)
        with patch.object(Path,'open',short),self.assertRaises(ValueError):
            self.collector.record('shutdown-unconfirmed')
        self.assertEqual(len(calls),1)
        with self.assertRaises(ValueError):self.collector.record_shutdown(receipt())
        self.assertFalse(self.manifest()['archiveComplete'])

    def test_final_partial_line_cannot_be_sealed_without_parsing_events(self):
        self.prepare()
        self.events.write_bytes(self.events.read_bytes().rstrip(b'\n'))
        with self.assertRaises(ValueError):self.collector.record_shutdown(receipt())
        self.assertFalse(self.manifest()['archiveComplete'])


if __name__=='__main__':unittest.main()
