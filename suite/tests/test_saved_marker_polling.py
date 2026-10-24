"""A live save may briefly deny reads; persistence evidence keeps one deadline."""
import hashlib
import io
from pathlib import Path
import unittest
from unittest.mock import patch
import zipfile

from suite.tests.test_native_smoke import smoke


class SavedMarkerPollingTests(unittest.TestCase):
    marker = 'UI-OpenGeul-calc'

    def test_shared_byte_boundary_retries_only_read_errors_and_preserves_empty_bytes(self):
        receipt={};source=unittest.mock.Mock()
        source.read_bytes.side_effect=[PermissionError(13,'denied'),FileNotFoundError(2,'missing'),b'']
        with patch.object(smoke.time,'monotonic',return_value=1.):
            self.assertIsNone(smoke.read_saving_document(source,2.,receipt))
            self.assertIsNone(smoke.read_saving_document(source,2.,receipt))
            self.assertEqual(smoke.read_saving_document(source,2.,receipt),b'')
            source.read_bytes.side_effect=IsADirectoryError(21,'not a file')
            with self.assertRaises(IsADirectoryError):smoke.read_saving_document(source,2.,receipt)
        self.assertEqual(receipt['transientCount'],2)
        self.assertEqual(receipt['attempts'],4)
        with patch.object(smoke.time,'monotonic',return_value=2.):
            with self.assertRaisesRegex(AssertionError,'save deadline'):smoke.read_saving_document(source,2.,receipt)
        self.assertEqual(source.read_bytes.call_count,4)

    def package(self, text=None):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr('xl/worksheets/sheet1.xml', '<s><t>' + (self.marker if text is None else text) + '</t></s>')
        return stream.getvalue()

    def run_poll(self, reader, *, before='different', deadline=.3):
        clock = [0.]
        record = {}
        def read(path):return reader(clock)
        with patch.object(Path, 'read_bytes', read), \
                patch.object(smoke.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(smoke.time, 'sleep', side_effect=lambda seconds: clock.__setitem__(0, clock[0]+seconds)):
            try:
                value = smoke.wait_saved_marker(Path('owned.xlsx'), self.marker, before, deadline, record)
                error = None
            except Exception as exc:
                value, error = None, exc
        return value, error, record, clock[0]

    def test_transient_denial_then_valid_snapshot_uses_same_bytes_for_hash(self):
        payload = self.package();calls=[]
        denied = PermissionError(13, 'sensitive path must not enter receipt')
        denied.winerror = 32
        def read(clock):
            calls.append(clock[0])
            if len(calls)==1:raise denied
            return payload
        value,error,record,_=self.run_poll(read)
        self.assertIsNone(error);self.assertEqual(value,hashlib.sha256(payload).hexdigest())
        self.assertEqual(len(calls),2)
        receipt=record['savedMarkerRead']
        self.assertEqual(receipt['transientCount'],1)
        self.assertEqual(receipt['firstTransient']['errno'],13)
        self.assertEqual(receipt['lastTransient']['winerror'],32)
        self.assertNotIn('sensitive',str(receipt))

    def test_persistent_denial_fails_original_deadline_with_bounded_diagnostics(self):
        calls=[]
        def read(clock):calls.append(clock[0]);raise PermissionError(13,'denied')
        value,error,record,finished=self.run_poll(read)
        self.assertIsNone(value);self.assertIsInstance(error,AssertionError)
        self.assertGreaterEqual(finished,.3);self.assertTrue(all(t<.3 for t in calls))
        self.assertEqual(record['savedMarkerRead']['transientCount'],len(calls))
        self.assertNotIn('errors',record['savedMarkerRead'])

    def test_bad_zip_and_nonexact_marker_cannot_pass(self):
        for payload in (b'partial zip',self.package('UI-OpenGeul-cal'),self.package('unrelated')):
            with self.subTest(payload=payload[:12]):
                value,error,_,_=self.run_poll(lambda clock:payload)
                self.assertIsNone(value);self.assertIsInstance(error,AssertionError)

    def test_late_valid_snapshot_cannot_pass(self):
        def read(clock):clock[0]=.31;return self.package()
        value,error,_,_=self.run_poll(read)
        self.assertIsNone(value);self.assertIsInstance(error,AssertionError)
        self.assertIn('save deadline',str(error))
        current=[]
        def read_on_time(clock):current.append(clock);return self.package()
        original=smoke.package_text
        def late_parse(stream):
            text=original(stream);current[0][0]=.31;return text
        with patch.object(smoke,'package_text',side_effect=late_parse):
            value,error,_,_=self.run_poll(read_on_time)
        self.assertIsNone(value);self.assertIsInstance(error,AssertionError)
        self.assertIn('save deadline',str(error))

    def test_already_expired_budget_never_reads_and_incomplete_zip_can_recover(self):
        calls=[]
        def read(clock):calls.append(clock[0]);return self.package()
        _,error,_,_=self.run_poll(read,deadline=0.)
        self.assertIsInstance(error,AssertionError);self.assertEqual(calls,[])
        payload=self.package()
        sequence=iter((FileNotFoundError(2,'unavailable'),b'incomplete',payload))
        def incomplete(clock):
            value=next(sequence)
            if isinstance(value,Exception):raise value
            return value
        value,error,record,_=self.run_poll(incomplete)
        self.assertIsNone(error);self.assertEqual(value,hashlib.sha256(payload).hexdigest())
        self.assertEqual(record['savedMarkerRead']['transientCount'],2)
        self.assertEqual(record['savedMarkerRead']['firstTransient']['kind'],'FileNotFoundError')
        self.assertEqual(record['savedMarkerRead']['lastTransient']['kind'],'BadZipFile')

    def test_unchanged_snapshot_and_nonfile_exceptions_remain_fatal(self):
        payload=self.package()
        _,error,_,_=self.run_poll(lambda clock:payload,before=hashlib.sha256(payload).hexdigest())
        self.assertIn('bytes did not change',str(error))
        failure=RuntimeError('input failed')
        def read(clock):raise failure
        _,error,_,_=self.run_poll(read)
        self.assertIs(error,failure)
        with patch.object(smoke,'package_text',side_effect=PermissionError(13,'parser failed')):
            _,error,record,_=self.run_poll(lambda clock:payload)
        self.assertIsInstance(error,PermissionError)
        self.assertEqual(record['savedMarkerRead']['transientCount'],0)
