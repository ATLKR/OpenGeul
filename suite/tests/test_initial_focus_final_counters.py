"""Synthetic numeric evidence checks; these do not establish Windows focus acceptance."""
from pathlib import Path
import copy
import hashlib
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'e2e'))
from initial_focus_final_counters import parse_initial_focus_final_counters

IDENTITY = dict(shellPid=101, shellCreationTime=1000, officePid=202,
    officeCreationTime=1100, formHwnd=301, panelHwnd=302, childHwnd=303,
    shellThreadId=401, editorThreadId=402, managedThreadId=1)
COUNTS = ('preOwnerActivated preOwnerAppActive preOwnerAppInactive activatedCount '
    'appActiveCount appInactiveCount queueEntryCount queueGuardCount coreQueueCount '
    'coreQueueTrueCount coreQueueFalseCount postAttemptCount postReturnCount '
    'callbackEntryCount callbackExitCount availabilityCount').split()


def final_row(**changes):
    value = dict(sequence=4, schemaVersion=2, ownerGeneration=1, identityKnown=1,
        ownerChanged=0, retired=1, disposeReturned=1, updateFailed=0, cap=65535,
        overflowMask=0, snapshotRevision=1, pendingKnown=1, pending=1,
        availabilityKnown=1, availabilityValue=0, availabilityMaskKnown=1,
        availabilitySourceCode=0, evaluatedMask=16383, trueMask=8191,
        firstRejectId=14, evaluationComplete=1, postUncertain=0, callbackOutstanding=0,
        **{name: 0 for name in COUNTS})
    value.update(IDENTITY)
    for short, wire in (('formHwnd', 'originalFormHwnd'), ('panelHwnd', 'originalPanelHwnd'),
                        ('childHwnd', 'originalChildHwnd')):
        value[wire] = value.pop(short)
    value['availabilityCount'] = 1
    value.update(changes)
    return value


class InitialFocusFinalCountersTests(unittest.TestCase):
    def parse(self, rows, *, retired=True, identity=None):
        return parse_initial_focus_final_counters(rows, retained_identity=IDENTITY if identity is None else identity,
            retirement_confirmed=retired)

    def test_closed_retired_owner_interval_preserves_first_reject_and_zero_counts(self):
        row = final_row()
        result = self.parse([row])
        self.assertEqual((result['known'], result['counterIntervalComplete'], result['zeroCountsUsable']), (1, 1, 1))
        self.assertEqual(result['latest']['firstRejectId'], 14)
        self.assertEqual(result['latest']['activatedCount'], 0)
        self.assertEqual((result['eventCompletenessUnknown'], result['acceptanceEligible']), (1, 0))
        row['activatedCount'] = 99
        self.assertEqual(result['latest']['activatedCount'], 0)

    def test_missing_final_never_proves_nonexecution(self):
        self.assertEqual(self.parse([])['zeroCountsUsable'], 0)

    def test_actual_retirement_required_even_for_all_zero_counts(self):
        result = self.parse([final_row()], retired=False)
        self.assertEqual((result['known'], result['counterIntervalComplete'], result['zeroCountsUsable']), (0, 0, 0))
        self.assertEqual(result['latest']['activatedCount'], 0)

    def test_incomplete_or_uncertain_owner_stays_unknown(self):
        for change in (dict(retired=0), dict(disposeReturned=0), dict(identityKnown=0),
                       dict(ownerChanged=1), dict(updateFailed=1), dict(pendingKnown=0, pending=0),
                       dict(availabilityKnown=0, availabilityValue=0, availabilityMaskKnown=0,
                            evaluatedMask=0, trueMask=0, firstRejectId=0, evaluationComplete=0),
                       dict(postUncertain=1), dict(callbackOutstanding=1)):
            with self.subTest(field=next(iter(change))):
                self.assertEqual(self.parse([final_row(**change)])['zeroCountsUsable'], 0)

    def test_overflow_cannot_be_interpreted_as_zero(self):
        self.assertEqual(self.parse([final_row(overflowMask=1)])['known'], 0)

    def test_exact_retained_generation_and_thread_identity_required(self):
        for name in IDENTITY:
            row = final_row()
            wire = {'formHwnd':'originalFormHwnd','panelHwnd':'originalPanelHwnd','childHwnd':'originalChildHwnd'}.get(name, name)
            row[wire] += 1
            with self.subTest(field=name):
                self.assertEqual(self.parse([row])['known'], 0)

    def test_closed_integer_schema_rejects_partial_bool_extra_and_bad_bounds(self):
        bad = []
        row=final_row();del row['postReturnCount'];bad.append(row)
        bad.extend((final_row(activatedCount=True), final_row(extra=1), final_row(cap=65536),
                    final_row(callbackExitCount=-1), final_row(ownerGeneration=129),
                    final_row(sequence=129), final_row(snapshotRevision=0)))
        for row in bad:
            with self.subTest(shape=len(row)):
                self.assertEqual(self.parse([row])['known'], 0)

    def test_existing_short_circuit_masks_must_be_consistent(self):
        for change in (dict(evaluatedMask=16382), dict(trueMask=16383), dict(firstRejectId=13),
                       dict(evaluatedMask=7, trueMask=7, firstRejectId=0),
                       dict(availabilityValue=1)):
            with self.subTest(change=tuple(change)):
                self.assertEqual(self.parse([final_row(**change)])['known'], 0)

    def test_later_callback_uses_its_own_last_availability_without_replacing_ingress(self):
        row=final_row(activatedCount=2, appActiveCount=1, queueEntryCount=1,
            coreQueueCount=1, coreQueueTrueCount=1, postAttemptCount=1, postReturnCount=1,
            callbackEntryCount=1, callbackExitCount=1, availabilityCount=2,
            availabilitySourceCode=4, evaluatedMask=7, trueMask=3, firstRejectId=3)
        result=self.parse([row])
        self.assertEqual(result['known'], 1)
        self.assertEqual((result['latest']['availabilitySourceCode'], result['latest']['firstRejectId']), (4,3))
        self.assertEqual(result['latest']['activatedCount'], 2)

    def test_capped_observer_masks_are_unknown_while_existing_boolean_is_preserved(self):
        result=self.parse([final_row(availabilityMaskKnown=0, evaluatedMask=0, trueMask=0,
            firstRejectId=0, evaluationComplete=0)])
        self.assertEqual(result['known'], 0)
        self.assertEqual(result['latest']['availabilityValue'], 0)

    def test_queue_coalescing_and_enqueue_then_throw_are_distinct(self):
        row=final_row(queueEntryCount=4, queueGuardCount=1, coreQueueCount=3,
            coreQueueTrueCount=1, coreQueueFalseCount=2, postAttemptCount=1, postReturnCount=1,
            callbackEntryCount=1, callbackExitCount=1)
        self.assertEqual(self.parse([row])['known'], 1)
        row.update(postReturnCount=0, postUncertain=1)
        self.assertEqual(self.parse([row])['zeroCountsUsable'], 0)

    def test_inconsistent_callback_and_post_arithmetic_rejected(self):
        for change in (dict(callbackExitCount=1), dict(postReturnCount=1),
                       dict(coreQueueTrueCount=1), dict(queueGuardCount=1),
                       dict(postAttemptCount=1, postReturnCount=1),
                       dict(callbackEntryCount=1, callbackOutstanding=0)):
            with self.subTest(change=tuple(change)):
                self.assertEqual(self.parse([final_row(**change)])['known'], 0)

    def test_core_true_and_successful_post_return_must_match(self):
        # The actual post delegate increments postReturn after BeginInvoke;
        # Core returns true only after that delegate returns normally.
        for changes in (dict(coreQueueTrueCount=1),
                        dict(coreQueueFalseCount=1, postAttemptCount=1, postReturnCount=1,
                             callbackEntryCount=1, callbackExitCount=1)):
            row=final_row(queueEntryCount=1, coreQueueCount=1, **changes)
            with self.subTest(coreTrue=row['coreQueueTrueCount']):
                result=self.parse([row])
                self.assertEqual((result['known'],result['zeroCountsUsable']),(0,0))

    def test_late_existing_callback_can_close_same_retired_owner(self):
        first=final_row(queueEntryCount=1, coreQueueCount=1, coreQueueTrueCount=1,
            postAttemptCount=1, postReturnCount=1, callbackOutstanding=1)
        last=copy.deepcopy(first);last.update(sequence=5, snapshotRevision=2,
            callbackEntryCount=1, callbackExitCount=1, callbackOutstanding=0)
        self.assertEqual(self.parse([first])['known'], 0)
        self.assertEqual(self.parse([first,last])['known'], 1)

    def test_snapshot_generation_order_and_counter_monotonicity(self):
        first=final_row()
        for changes in (dict(sequence=4, snapshotRevision=2), dict(sequence=5, snapshotRevision=1),
                        dict(sequence=5, snapshotRevision=2, ownerGeneration=2),
                        dict(sequence=5, snapshotRevision=2, availabilityCount=0)):
            with self.subTest(change=tuple(changes)):
                self.assertEqual(self.parse([first,final_row(**changes)])['known'], 0)

    def test_input_contract_boundaries_and_retained_shape_fail_closed(self):
        for rows in (None, {}, [final_row()]*129):
            self.assertEqual(self.parse(rows)['known'], 0)
        self.assertEqual(self.parse([final_row()], retired=1)['known'], 0)
        identity=dict(IDENTITY, extra=1)
        self.assertEqual(self.parse([final_row()], identity=identity)['known'], 0)


class FormCounterSeamTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(__file__).resolve().parents[1]
        self.source=(self.root/'shell/OfficeDocumentForm.cs').read_text()

    def test_core_focus_and_logger_remain_byte_identical(self):
        for name,digest in (('OwnedEditorFocus.cs','92c782419aa76412327b728df05496ac913aeb2eb2b0d7a7d3a82a6083bd3004'),
                            ('SaveDiagnosticsTrace.cs','a6260cfe63ca89762dff49237f4d07b1030a92022aff8ce5cc3cf8ce16232af2')):
            self.assertEqual(hashlib.sha256((self.root/'shell/Core'/name).read_bytes()).hexdigest(),digest)

    def test_ingress_precedes_existing_pending_filters(self):
        activated=self.source.split('protected override void OnActivated',1)[1].split('protected override void OnHandleDestroyed',1)[0]
        self.assertLess(activated.index('CountInitialFocusIngress(0)'),activated.index('var pendingBefore'))
        wnd=self.source.split('protected override void WndProc',1)[1].split('protected override bool ProcessCmdKey',1)[0]
        self.assertLess(wnd.index('CountInitialFocusIngress(appActivated ? 1 : 2)'),wnd.index('var pendingBefore'))
        self.assertEqual(activated.count('base.OnActivated(e);'),1)
        self.assertEqual(wnd.count('base.WndProc(ref m);'),1)

    def test_exact_original_boolean_operands_and_single_post_are_preserved(self):
        block=self.source.split('private bool EditorFocusAvailable',1)[1].split('private void TryInitialEditorFocus',1)[0]
        expected=('Environment.CurrentManagedThreadId == uiThreadId','attached','worker is not null','!loading','!busy',
                  '!closing','!closeApproved','!IsDisposed','!Disposing','IsHandleCreated','Enabled','Visible','!Modal','ActiveForm == this')
        import re
        self.assertEqual(re.findall(r'InitialFocusGate\(flow, \d+, (.*?)\)',block),list(expected))
        queue=self.source.split('private void QueueInitialEditorFocus',1)[1].split('private sealed class InitialFocusFlow',1)[0]
        self.assertEqual(queue.count('BeginInvoke('),1)
        self.assertEqual(queue.count('owned!.QueueInitialFocus('),1)
        self.assertEqual(re.findall(r'InitialFocusQueueGate\(flow, \d+, (.*?)\)',queue),
            ['!attached','loading','owned is null','!owned!.InitialFocusPending','IsDisposed','Disposing','!IsHandleCreated'])

    def test_release_keeps_clear_then_dispose_then_final_and_cached_envelope(self):
        release=self.source.split('private void ReleaseEditorFocus()',1)[1].split('protected override void Dispose',1)[0]
        self.assertLess(release.index('editorFocus = null'),release.index('owned?.Dispose()'))
        self.assertLess(release.index('owned?.Dispose()'),release.index('WriteInitialFocusFinal(counters)'))
        self.assertIn('counters.WorkerPid, counters.TraceId',self.source)
        self.assertIn('schemaVersion = 2',self.source)

    def test_actual_final_wire_matches_numeric_parser_fixture_exactly(self):
        import re
        wire=self.source.split('initialFocusFlowDiagnostics.Write("final", new',1)[1].split('}, counters.WorkerPid',1)[0]
        fields=set(re.findall(r'\b(\w+)\s*=(?!=)',wire))
        self.assertEqual(fields,set(final_row())-{'sequence'})
        self.assertNotIn('Handle',wire)

    def test_pre_owner_events_and_late_callback_keep_distinct_cached_owner_context(self):
        self.assertIn('counters.Count(index + 3)',self.source)
        self.assertIn('Array.Copy(initialFocusPreOwnerCounts, counters.Counts, 3)',self.source)
        self.assertIn('ReferenceEquals(counters.Owner, owner)',self.source)
        self.assertIn('if (initialFocusOwnerGeneration >= 128) return;',self.source)
        self.assertIn('if (counters?.Retired == 1) WriteInitialFocusFinal(counters);',self.source)
        self.assertIn('else OverflowMask |= 1 << index;',self.source)


if __name__=='__main__':
    unittest.main()
