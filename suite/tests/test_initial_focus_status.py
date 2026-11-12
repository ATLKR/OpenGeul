"""Synthetic diagnostic admission only; never Windows focus acceptance."""
import copy
import hashlib
import importlib.util
import inspect
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

SUITE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SUITE / 'e2e'))
from test_initial_focus_final_counters import IDENTITY, prefix_row, final_row
import test_native_menu_smoke as existing

PATH = SUITE / 'e2e/initial_focus_status.py'


def envelope(event, stage, sequence, details):
    return dict(event=event, component='host', stage=stage, sequence=sequence,
        utc='2026-11-12T00:00:00+00:00', processId=101, managedThreadId=1,
        workerProcessId=99, traceId='a'*32, details=details)


def counter(row=None):
    row = prefix_row() if row is None else copy.deepcopy(row)
    sequence = row.pop('sequence')
    return envelope('suite.initialEditorFocusFlow',
        'prefix' if row['snapshotKindCode'] == 1 else 'final', sequence, row)


def status(active=0, **changes):
    details = dict(schemaVersion=1, ownerGeneration=1, prefixSnapshotRevision=1,
        originalFormHwnd=301, originalPanelHwnd=302, originalChildHwnd=303,
        activeFormIsThis=active)
    details.update(changes)
    return envelope('suite.initialEditorFocusStatus', 'status.completed', 1, details)


def encoded(rows):
    return [(json.dumps(row, separators=(',', ':'))+'\n').encode('ascii') for row in rows]


class StatusProjectionTests(unittest.TestCase):
    def setUp(self):
        self.module = None
        if PATH.is_file():
            spec = importlib.util.spec_from_file_location('initial_status_under_test', PATH)
            self.module = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.module)
        self.original = dict(known=True, scope=dict(moduleCode=1,
            **{k:v for k,v in IDENTITY.items() if k!='managedThreadId'}))

    def parse(self, rows, *, lines=None, budget=lambda:None, original=None):
        method = getattr(self.module, 'parse_initial_focus_status', None)
        self.assertTrue(callable(method), 'Missing independent managed-status observer')
        return method(encoded(rows) if lines is None else lines,
            original=self.original if original is None else original,
            trace='a'*32, worker=99, managed=1, budget=budget)

    def unknown(self, value):
        self.assertFalse(value['known']); self.assertEqual(value['rows'], [])
        self.assertFalse(value['acceptanceEligible']); self.assertTrue(value['eventCompletenessUnknown'])

    def test_actual_numeric_wire_projects_false_and_true_without_focus_acceptance(self):
        for active in (0,1):
            with self.subTest(active=active):
                value=self.parse([counter(),status(active)])
                self.assertTrue(value['known']);self.assertEqual(value['rows'][0]['activeFormIsThis'],active)
                self.assertFalse(value['acceptanceEligible']);self.assertTrue(value['eventCompletenessUnknown'])
                self.assertNotIn('zeroCountsUsable',value)

    def test_old_record_without_new_event_stays_unknown(self):
        value=self.parse([counter()]);self.unknown(value);self.assertEqual(value['errorCode'],1)

    def test_exact_seven_numeric_details_required(self):
        for changes in (dict(extra=0),dict(activeFormIsThis=True),dict(activeFormIsThis=1.),
                dict(activeFormIsThis='1'),dict(activeFormIsThis=-1),dict(activeFormIsThis=2),
                dict(schemaVersion=2),dict(ownerGeneration=129),dict(prefixSnapshotRevision=65536)):
            with self.subTest(field=next(iter(changes))):self.unknown(self.parse([counter(),status(**changes)]))
        missing=status();del missing['details']['activeFormIsThis']
        self.unknown(self.parse([counter(),missing]))

    def test_status_envelope_and_original_context_are_exact(self):
        for field,bad in [('processId',102),('managedThreadId',2),('workerProcessId',98),
                ('traceId','b'*32),('stage','other'),('sequence',True),('sequence',129),('utc','private sentinel')]:
            row=status();row[field]=bad
            with self.subTest(field=field):self.unknown(self.parse([counter(),row]))
        self.unknown(self.parse([counter(),status()],original=dict(known=False,scope={})))

    def test_prefix_join_requires_actual_same_generation_revision_and_three_handles(self):
        for key in ('ownerGeneration','prefixSnapshotRevision','originalFormHwnd','originalPanelHwnd','originalChildHwnd'):
            row=status();row['details'][key]+=1
            with self.subTest(key=key):self.unknown(self.parse([counter(),row]))
        self.unknown(self.parse([status()]))
        self.unknown(self.parse([status(),counter()]))
        self.unknown(self.parse([counter(final_row()),status()]))

    def test_prefix_is_validated_by_original_closed_counter_contract(self):
        for changes in (dict(trueMask=16383),dict(cap=65536),dict(extra=1),
                dict(shellCreationTime=999),dict(officePid=303),dict(activatedCount=True),
                dict(ownerChanged=1),dict(identityKnown=0),dict(updateFailed=1),dict(overflowMask=1)):
            with self.subTest(field=next(iter(changes))):self.unknown(self.parse([counter(prefix_row(**changes)),status()]))

    def test_invalid_full_counter_order_cannot_validate_individually_matching_prefix(self):
        first=counter(prefix_row(sequence=4,snapshotRevision=1,activatedCount=2))
        later=counter(prefix_row(sequence=5,snapshotRevision=2,activatedCount=1))
        self.unknown(self.parse([first,status(),later]))

    def test_independent_sequence_and_revision_order_are_strict(self):
        row=status();later=copy.deepcopy(row);later['sequence']=2
        self.unknown(self.parse([counter(),row,later]))
        next_prefix=counter(prefix_row(sequence=5,snapshotRevision=2))
        later['details']['prefixSnapshotRevision']=2
        value=self.parse([counter(),row,next_prefix,later]);self.assertTrue(value['known'])
        self.assertEqual(len(value['rows']),2)
        later['sequence']=1;self.unknown(self.parse([counter(),row,next_prefix,later]))

    def test_gaps_are_diagnostic_and_never_close_event_coverage(self):
        row=status();row['sequence']=3
        value=self.parse([counter(),row]);self.assertTrue(value['known'])
        self.assertTrue(value['gapObserved']);self.assertEqual(value['gapCount'],2)
        self.assertTrue(value['eventCompletenessUnknown'])

    def test_closed_kind2_does_not_turn_status_into_counter_authority(self):
        rows=[counter(),status(1),counter(final_row(sequence=5,snapshotRevision=2))]
        original=self.original|dict(captureModeCode=2,historicalIdentityOnly=True,retirementConfirmed=True)
        value=self.parse(rows,original=original)
        self.assertTrue(value['known']);self.assertTrue(value['historicalIdentityOnly'])
        self.assertTrue(value['retirementConfirmed']);self.assertFalse(value['acceptanceEligible'])
        self.assertNotIn('counterIntervalComplete',value)

    def test_duplicate_key_nonascii_partial_and_nonfinite_are_rejected(self):
        good=encoded([counter(),status()])
        variants=[good[:-1]+[good[-1].replace(b'"activeFormIsThis":0',b'"activeFormIsThis":0,"activeFormIsThis":1')],
            good[:-1]+[good[-1].replace(b'"activeFormIsThis":0',b'"activeFormIsThis":NaN')],
            good[:-1]+[good[-1].replace(b'"utc":"2026',b'"utc":"\xc3\xa92026')],
            good[:-1]+[good[-1].rstrip(b'\n')]]
        for lines in variants:
            with self.subTest(case=len(lines[-1])):self.unknown(self.parse([],lines=lines))

    def test_remaining_deadline_and_original_input_bounds_are_enforced(self):
        def expired():raise TimeoutError()
        value=self.parse([counter(),status()],budget=expired);self.unknown(value)
        self.assertEqual(value['errorCode'],5)
        for lines in ([b'\n']*8193,[b'x'*65536+b'\n'],[b'x'*32768+b'\n']*65):
            self.unknown(self.parse([],lines=lines))


class ProducerAndCaptureTests(unittest.TestCase):
    def setUp(self):
        self.source=(SUITE/'shell/OfficeDocumentForm.cs').read_text()

    def test_status_observer_follows_existing_prefix_and_reads_activeform_only_once(self):
        self.assertTrue('private void WriteInitialFocusStatus(' in self.source,'Missing independent status producer')
        block=self.source.split('private async Task RefreshStatusAsync()',1)[1].split('private void PublishNativeMenuStatus',1)[0]
        self.assertLess(block.index('WriteInitialFocusPrefix(statusFocusCounters);'),block.index('WriteInitialFocusStatus(statusFocusCounters);'))
        self.assertLess(block.index('WriteInitialFocusStatus(statusFocusCounters);'),block.index('catch (Exception e)'))
        body=self.source.split('private void WriteInitialFocusStatus(',1)[1].split('private void ReleaseEditorFocus(',1)[0]
        self.assertEqual(body.count('ReferenceEquals(ActiveForm, this)'),1)
        self.assertEqual(body.count('activeFormIsThis'),2)
        import re
        wire=body.split('initialFocusStatusDiagnostics.Write("status.completed", new',1)[1].split('}, counters.WorkerPid',1)[0]
        fields=set(re.findall(r'\b(\w+)\s*=(?!=)',wire))|{'activeFormIsThis'}
        self.assertEqual(fields,set('schemaVersion ownerGeneration prefixSnapshotRevision originalFormHwnd originalPanelHwnd originalChildHwnd activeFormIsThis'.split()))
        for forbidden in ('EditorFocusAvailable','InitialFocusPending','InitialFocusGate','BeginInvoke','SendAsync',
                'SetFocus','ObserveResult','ObservePending','.Count(','.Handle','CreateInitialFocusFlow','UpdateFailed ='):
            self.assertNotIn(forbidden,body)
        for guard in ('Environment.CurrentManagedThreadId','counters.ManagedThread','initialFocusOwnerGeneration',
                'ReferenceEquals(initialFocusCounters, counters)','ReferenceEquals(editorFocus, counters.Owner)',
                'editorFocusFormHwnd','editorFocusPanelHwnd','counters.Retired','counters.DisposeReturned'):
            self.assertIn(guard,body)
        self.assertIn('new("suite.initialEditorFocusStatus")',self.source)

    def test_old_prefix_core_and_logger_are_unchanged(self):
        # Frozen f912 source contracts; clean checkouts need no scratch originals.
        block=self.source.split('private void WriteInitialFocusPrefix(',1)[1].split('private void WriteInitialFocusFinal(',1)[0]
        self.assertEqual(hashlib.sha256(block.encode()).hexdigest(),'cf2ea079c8334c8253e98ac00657531d74480588e49ded074262db6042b932ac')
        block=self.source.split('private bool EditorFocusAvailable',1)[1].split('private sealed class InitialFocusFlow',1)[0]
        self.assertEqual(hashlib.sha256(block.encode()).hexdigest(),'4944855667ed8e6094cdbcb399d9b8e1f0ac8e27e7f8962c2b750a85fe4ce349')
        self.assertEqual(hashlib.sha256((SUITE/'shell/Core/OwnedEditorFocus.cs').read_bytes()).hexdigest(),'92c782419aa76412327b728df05496ac913aeb2eb2b0d7a7d3a82a6083bd3004')
        self.assertEqual(hashlib.sha256((SUITE/'shell/Core/SaveDiagnosticsTrace.cs').read_bytes()).hexdigest(),'a6260cfe63ca89762dff49237f4d07b1030a92022aff8ce5cc3cf8ce16232af2')
        self.assertEqual(hashlib.sha256((SUITE/'e2e/initial_focus_final_counters.py').read_bytes()).hexdigest(),'6f5a664f0950d974d1e4d5e29b2a94bb7ef10622fc24aebef441670b3eb64e77')

    def fixture(self):
        obj=existing.InitialFocusStderrTests('runTest');obj.setUp();self.addCleanup(obj.doCleanups)
        return obj

    def wire(self,fixture, row):
        row=copy.deepcopy(row);row.update(processId=77)
        details=row['details']
        for key,value in {'shellPid':77,'shellCreationTime':100,'officePid':88,'officeCreationTime':200,
                'originalFormHwnd':11,'originalPanelHwnd':12,'originalChildHwnd':13,
                'shellThreadId':9,'editorThreadId':10}.items():
            if key in details:details[key]=value
        return row

    def test_capture_reuses_one_file_read_and_preserves_original_three_projections(self):
        f=self.fixture();self.assertIn('status_out',inspect.signature(f.smoke.capture_initial_focus_trace).parameters,
            'Missing optional same-read status projection')
        rich=f.event();prefix=self.wire(f,counter());new=self.wire(f,status(1))
        f.write([rich,prefix]);old_flow={};old_counter={}
        old=f.capture(flow_out=old_flow,counter_out=old_counter)
        f.write([rich,prefix,new]);flow={};counts={};managed={}
        with patch.object(f.smoke.os,'open',wraps=f.smoke.os.open) as opened:
            result=f.capture(flow_out=flow,counter_out=counts,status_out=managed)
        self.assertEqual(opened.call_count,1);self.assertTrue(managed['known'])
        self.assertEqual(result,old);self.assertEqual(flow,old_flow);self.assertEqual(counts,old_counter)
        self.assertEqual(counts['zeroCountsUsable'],0)
        new['details']['private']='synthetic must never escape'
        f.write([rich,prefix,new]);managed={}
        self.assertEqual(f.capture(status_out=managed),old);self.assertFalse(managed['known'])
        self.assertNotIn('synthetic must never escape',json.dumps(managed))

    def test_new_observer_exception_cannot_revoke_original_projections(self):
        f=self.fixture();self.assertIn('status_out',inspect.signature(f.smoke.capture_initial_focus_trace).parameters)
        f.write([f.event(),self.wire(f,counter()),self.wire(f,status())])
        flow={};counts={};old=f.capture(flow_out=flow,counter_out=counts)
        for error in (RuntimeError(),TimeoutError()):
            observed={};new_flow={};new_counts={}
            with patch.object(f.smoke,'parse_initial_focus_status',side_effect=error):
                result=f.capture(flow_out=new_flow,counter_out=new_counts,status_out=observed)
            self.assertEqual(result,old);self.assertEqual(new_flow,flow);self.assertEqual(new_counts,counts)
            self.assertFalse(observed['known']);self.assertFalse(observed['acceptanceEligible'])

    def test_retired_status_uses_historical_identity_without_querying_closed_handle(self):
        f=self.fixture();self.assertIn('status_out',inspect.signature(f.smoke.capture_initial_focus_trace).parameters)
        f.write([f.event(),self.wire(f,counter()),self.wire(f,status(1))]);f.retire()
        f.session.engine.exited=lambda *args:self.fail('Closed engine queried')
        managed={};counts={};value=f.capture(retired=True,status_out=managed,counter_out=counts)
        self.assertTrue(value['known']);self.assertTrue(managed['known'])
        self.assertTrue(managed['historicalIdentityOnly']);self.assertTrue(managed['retirementConfirmed'])
        self.assertEqual(counts['zeroCountsUsable'],0);self.assertFalse(managed['acceptanceEligible'])


if __name__=='__main__':unittest.main()
