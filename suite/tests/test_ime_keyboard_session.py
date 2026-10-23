"""First-admission IME shortcut policy; synthetic native boundaries only."""
import copy
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

E2E = Path(__file__).resolve().parents[1] / 'e2e'
sys.path.insert(0, str(E2E))
import test_counted_editor_shortcuts as fixtures
import test_korean_ime_smoke as ime_fixtures
SOURCE = E2E / 'ime_keyboard_session.py'
if SOURCE.is_file():
    spec = importlib.util.spec_from_file_location('ime_keyboard_tested', SOURCE)
    keyboard = importlib.util.module_from_spec(spec); spec.loader.exec_module(keyboard)
else:
    keyboard = None


class IMEKeyboardSessionTests(unittest.TestCase):
    def setUp(self): self.assertIsNotNone(keyboard, 'Missing first-admission IME keyboard session')
    def fixture(self, directory, module='writer', *, setup_deadline=10.):
        p, b, api, clock, probe, record = fixtures.CountedEditorShortcutsTests().fixture(directory)
        record.update(module=module, windowHwnd=11, parentHwnd=12, childHwnd=22, officePid=88)
        original_scope=probe.scope_snapshot
        def scope(*args):
            result=original_scope(*args)
            if probe.focus==0:result['focusWithinEditor']=False
            return result
        probe.scope_snapshot=scope
        # The actual semantic replay contract is independently exercised by its
        # reader suite. This explicit boundary double records session joins.
        import ime_semantic_context as semantic
        def validate(context, **kw):
            assert context['success'] is True and context['module']==kw['module']==module
            assert context['phase']==kw['phase'] and context['expectedPrefix']==kw['expected_prefix']
            assert context['expectedNative']==kw['expected_native']
            assert context['setupDeadline']==kw['setup_deadline']==setup_deadline
            assert context['finishedAt']<=kw['now']<kw['setup_deadline']
            context['replays']=context.get('replays',0)+1
            return context
        replay=patch.object(semantic,'require_ime_semantic_context',side_effect=validate)
        replay.start();self.addCleanup(replay.stop)
        session = keyboard.IMEKeyboardSession(api, p, 11, 12, 22, 88, module, record, setup_deadline, probe=probe, clock=clock)
        return session, p, b, api, clock, probe, record
    def setup(self, session):
        session.start(); session.focus_editor(6.); self.ready(session); self.navigate(session); self.prefix(session); session.setup_complete()
    def navigate(self, session):
        if session.module=='calc':
            from test_ime_calc_navigation import navigate_session
            navigate_session(session)
        else:session.navigate()
    def semantic(self,session,phase):
        record=session.record;prefix=None if phase=='pre' else ' ime-opengeul-'+session.module+':'
        context=dict(success=True,module=session.module,phase=phase,expectedPrefix=prefix,
            expectedNative=dict(session.binding),setupDeadline=10.,readerDeadline=9.,startedAt=session.clock(),finishedAt=session.clock())
        record.setdefault('imeSemanticContexts',[]).append(context);record['imeSemanticContext']=context
        session.semantic_ready(context,phase=phase)
        return context
    def prefix(self, session):
        self.semantic(session,'pre')
        record=session.record
        record.update(editorTid=44,keyboardFocusHwnd=33,asciiPrefix=' ime-opengeul-'+session.module+':',prefixInputLayout=0x04090409)
        receipt=ime_fixtures.KoreanImePolicyTests().ascii_receipt(session.module)
        for action in receipt['actions']:
            for side in ('before','after'):action[side].update(focusHwnd=33,editorThreadId=44)
        record['asciiEditorInputs']=[receipt]
        if session.module=='calc':
            record['calcSetupContext']=dict(success=True,nativeImeObserved=False,
                expectedNative=dict(session.binding),expectedPrefix=record['asciiPrefix'],
                readerDeadline=9.,finishedAt=1.)
        self.semantic(session,'post')
    def ready(self, session):
        receipt=dict(schemaVersion=1,kind='owned-editor-focus-readiness',ready=True,
            suiteHwnd=11,childHwnd=22,shellPid=77,officePid=88,deadlineSeconds=5.,
            startedAt=1.,deadline=6.,deadlineScope='editor-setup-and-focus',
            clickAttempts=1,controlF6Attempts=1,clickCompleted=True,controlF6Completed=True,
            editorThreadId=44,focusHwnd=33,pollStartedSeconds=0.,elapsedSeconds=0.,snapshots=[])
        for phase in ('before-click','after-click','after-control-f6'):
            row=session.probe.scope_snapshot(session.api,session.binding)
            row.update(phase=phase,elapsedSeconds=0.)
            receipt['snapshots'].append(row)
        session.record['editorFocusReadiness']=receipt
        session.editor_ready(receipt)
    def restore_save(self, session, record):
        record['prefixInputLayout'] = 0x04090409
        record['layoutRestored'] = True
        from ime_typed_policy_fixtures import complete_record
        record.update(readiness=ime_fixtures.KoreanImePolicyTests().readiness(),
            windowHwnd=session.binding['suiteHwnd'],officePid=session.binding['officePid'],
            restoration=ime_fixtures.KoreanImePolicyTests().restoration())
        complete_record(record)
        session.begin_save(record['restoration'], 31.); session.save(); session.close()
    def test_owned_capture_settles_read_only_under_original_setup_deadline(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            s,p,b,api,clock,probe,record=self.fixture(directory)
            original=probe.scope_snapshot;reads=[]
            def scope(*args):
                row=original(*args);reads.append(row)
                if len(reads)==1:row['capture']=copy.deepcopy(row['parent'])
                return row
            probe.scope_snapshot=scope
            with patch('time.sleep',side_effect=lambda seconds:setattr(clock,'now',clock.now+seconds)):
                s.start()
            s.close(RuntimeError('targeted admission slice ends before composition/save'))
            ledger=record['imeKeyboardSession']['captureReadiness']
            self.assertEqual(ledger['pollCount'],1)
            self.assertEqual(ledger['deadline'],10.)
            self.assertEqual(ledger['first']['scope']['capture']['hwnd'],12)
            self.assertEqual(probe.sent,[])
            self.assertEqual(probe.calls.count(('open',88)),1)
    def test_unknown_capture_retains_rejected_fresh_scope_without_input(self):
        with tempfile.TemporaryDirectory() as directory:
            s,p,b,api,clock,probe,record=self.fixture(directory);probe.capture=991
            with self.assertRaises(AssertionError):s.start()
            self.assertEqual(record['imeKeyboardSession']['lastGuardObservation']['scope']['capture']['hwnd'],991)
            self.assertEqual(probe.sent,[])
    def test_capture_wait_rechecks_generation_keyboard_and_focus_without_deadline_renewal(self):
        from unittest.mock import patch
        changes=(lambda probe:probe.engine.update(creationTime=probe.engine['creationTime']+1),
                 lambda probe:setattr(probe,'layout',0x04120412),
                 lambda probe:setattr(probe,'keys_down',[0x11]),
                 lambda probe:setattr(probe,'focus',999))
        for change in changes:
            with self.subTest(change=change),tempfile.TemporaryDirectory() as directory:
                s,p,b,api,clock,probe,record=self.fixture(directory);original=probe.scope_snapshot;pauses=[]
                def scope(*args):
                    row=original(*args);row['capture']=copy.deepcopy(row['parent']);return row
                def pause(seconds):clock.now+=seconds;pauses.append(seconds);change(probe)
                probe.scope_snapshot=scope
                with patch('time.sleep',side_effect=pause),self.assertRaises(AssertionError):s.start()
                self.assertEqual(pauses,[.05])
                self.assertEqual(record['imeKeyboardSession']['captureReadiness']['deadline'],10.)
                self.assertIn('scope',record['imeKeyboardSession']['lastGuardObservation'])
                self.assertEqual(probe.sent,[])
    def test_only_ctrl_f6_may_settle_host_focus_to_exact_child_during_intent(self):
        with tempfile.TemporaryDirectory() as directory:
            s,p,b,api,clock,probe,record=self.fixture(directory);original=probe.scope_snapshot
            def scope(*args):
                row=original(*args)
                if probe.focus==11:
                    row['focus']=copy.deepcopy(row['before']['suite']);row['focusWithinEditor']=False
                return row
            probe.scope_snapshot=scope;probe.focus=11;s.start();retain=s._retain
            def durable(phase):
                retain(phase)
                if phase=='input-intent':probe.focus=22
            s._retain=durable;s.focus_editor(6.);s.close(RuntimeError('targeted focus slice ends before composition/save'))
            action=record['imeKeyboardSession']['actions'][0]
            self.assertEqual(action['focusIntentTransition'],'owned-host-to-exact-original-editor-child')
            self.assertEqual(len(probe.sent),1)
    def test_ctrl_f6_intent_rejects_arbitrary_descendant_and_reverse_focus_change(self):
        for initial,current in ((11,33),(22,11)):
            with self.subTest(initial=initial,current=current),tempfile.TemporaryDirectory() as directory:
                s,p,b,api,clock,probe,record=self.fixture(directory);original=probe.scope_snapshot
                def scope(*args):
                    row=original(*args)
                    if probe.focus==11:
                        row['focus']=copy.deepcopy(row['before']['suite']);row['focusWithinEditor']=False
                    return row
                probe.scope_snapshot=scope;probe.focus=initial;s.start();retain=s._retain
                def durable(phase):
                    retain(phase)
                    if phase=='input-intent':probe.focus=current
                s._retain=durable
                with self.assertRaises(AssertionError):s.focus_editor(6.)
                s.close();self.assertEqual(probe.sent,[])
    def test_semantic_pre_must_be_actual_current_context_before_prefix_target(self):
        with tempfile.TemporaryDirectory() as directory:
            s,p,b,api,clock,probe,record=self.fixture(directory)
            s.start();s.focus_editor(6.);self.ready(s);s.navigate()
            context=dict(success=True,module='writer',phase='pre',expectedPrefix=None,
                expectedNative=dict(s.binding),setupDeadline=10.,readerDeadline=9.,finishedAt=1.)
            record['imeSemanticContexts']=[context];record['imeSemanticContext']=context
            with self.assertRaises(AssertionError):s.semantic_ready(copy.deepcopy(context),phase='pre')
            s.close();self.assertEqual(len(probe.sent),2)
    def test_semantic_context_replacement_after_prefix_blocks_korean_setup(self):
        with tempfile.TemporaryDirectory() as directory:
            s,p,b,api,clock,probe,record=self.fixture(directory)
            s.start();s.focus_editor(6.);self.ready(s);s.navigate();self.prefix(s)
            record['imeSemanticContexts'][0]=copy.deepcopy(record['imeSemanticContexts'][0])
            with self.assertRaises(AssertionError):s.setup_complete()
            s.close();self.assertEqual(len(probe.sent),2)
    def test_pre_and_post_semantic_replay_join_native_generation_and_original_budget(self):
        for phase,field,value in [('pre','expectedNative',{}),('pre','setupDeadline',11.),('post','success',False)]:
            with self.subTest(phase=phase,field=field),tempfile.TemporaryDirectory() as directory:
                s,p,b,api,clock,probe,record=self.fixture(directory)
                s.start();s.focus_editor(6.);self.ready(s);s.navigate()
                if phase=='post':self.semantic(s,'pre')
                context=dict(success=True,module='writer',phase=phase,expectedPrefix=None if phase=='pre' else ' ime-opengeul-writer:',
                    expectedNative=dict(s.binding),setupDeadline=10.,readerDeadline=9.,finishedAt=1.)
                context[field]=value;record.setdefault('imeSemanticContexts',[]).append(context);record['imeSemanticContext']=context
                with self.assertRaises(AssertionError):s.semantic_ready(context,phase=phase)
                s.close();self.assertEqual(len(probe.sent),2)
    def test_reader_capture_wait_expires_at_existing_twelve_second_cap_and_restores_probe(self):
        with tempfile.TemporaryDirectory() as directory:
            s,p,b,api,clock,probe,record=self.fixture(directory,setup_deadline=30.)
            s.start();s.focus_editor(6.);self.ready(s);s.navigate()
            record['imeSemanticContext']=dict(kind='ime-semantic-editing-context',module='writer',phase='pre',
                expectedNative=dict(s.binding),startedAt=1.,readerDeadline=13.,setupDeadline=30.,success=False)
            original=probe.scope_snapshot
            def scope(*args):
                row=original(*args);row['capture']=copy.deepcopy(row['parent']);return row
            probe.scope_snapshot=scope;s.native_probe=True;probe.deadline=30.
            with patch('time.sleep',side_effect=lambda seconds:setattr(clock,'now',clock.now+seconds)):
                with self.assertRaisesRegex(AssertionError,'deadline'):s.require_context_target('imeSemanticContext')
            self.assertEqual(clock.now,13.);self.assertEqual(s.deadline,30.);self.assertEqual(probe.deadline,30.)
            self.assertEqual(record['imeKeyboardSession']['captureReadiness']['deadline'],13.)
            s.close();self.assertEqual(len(probe.sent),2)
    def test_reader_context_key_identity_binding_and_deadline_cannot_change_during_capture_wait(self):
        for change in ('replace','binding','deadline'):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as directory:
                s,p,b,api,clock,probe,record=self.fixture(directory,setup_deadline=30.)
                s.start();s.focus_editor(6.);self.ready(s);s.navigate()
                context=dict(kind='ime-semantic-editing-context',module='writer',phase='pre',
                    expectedNative=dict(s.binding),startedAt=1.,readerDeadline=13.,setupDeadline=30.,success=False)
                record['imeSemanticContext']=context;original=probe.scope_snapshot
                def scope(*args):
                    row=original(*args);row['capture']=copy.deepcopy(row['parent']);return row
                def pause(seconds):
                    clock.now+=seconds
                    if change=='replace':record['imeSemanticContext']=copy.deepcopy(context)
                    elif change=='binding':context['expectedNative']['officeCreationTime']+=1
                    else:context['readerDeadline']+=1
                probe.scope_snapshot=scope
                with patch('time.sleep',side_effect=pause),self.assertRaises(AssertionError):s.require_context_target('imeSemanticContext')
                self.assertEqual(clock.now,1.05);self.assertEqual(s.deadline,30.)
                s.close();self.assertEqual(len(probe.sent),2)
    def test_prefix_gate_rejects_missing_or_mutated_actual_pre_without_more_input(self):
        for altered in (False,True):
            with self.subTest(altered=altered),tempfile.TemporaryDirectory() as directory:
                s,p,b,api,clock,probe,record=self.fixture(directory)
                s.start();s.focus_editor(6.);self.ready(s);s.navigate()
                if altered:self.semantic(s,'pre')['success']=False
                with self.assertRaises(AssertionError):s.require_prefix_ready()
                s.close();self.assertEqual(len(probe.sent),2)
    def test_navigation_focus_drift_during_intent_never_uses_ctrl_f6_allowance(self):
        with tempfile.TemporaryDirectory() as directory:
            s,p,b,api,clock,probe,record=self.fixture(directory)
            s.start();s.focus_editor(6.);self.ready(s);retain=s._retain
            api.require_editor_focus=lambda hwnd,child:probe.focus
            def durable(phase):
                retain(phase)
                if phase=='input-intent':probe.focus=22
            s._retain=durable
            with self.assertRaisesRegex(AssertionError,'focus changed'):s.navigate()
            s.close();self.assertEqual(len(probe.sent),1)
    def test_successful_reader_guard_restores_exact_previous_session_and_probe_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            s,p,b,api,clock,probe,record=self.fixture(directory,setup_deadline=30.)
            s.start();s.focus_editor(6.);self.ready(s);s.navigate();s.native_probe=True;probe.deadline=30.
            record['imeSemanticContext']=dict(kind='ime-semantic-editing-context',module='writer',phase='pre',
                expectedNative=dict(s.binding),startedAt=1.,readerDeadline=13.,setupDeadline=30.,success=False)
            s.require_context_target('imeSemanticContext')
            self.assertEqual(s.deadline,30.);self.assertEqual(probe.deadline,30.);self.assertEqual(len(probe.sent),2)
            s.close(RuntimeError('targeted reader guard ends before composition/save'))
    def test_modules_emit_only_existing_exact_sequence_and_one_retained_engine(self):
        for module, sequence in [('writer', ['CTRL_F6','CTRL_END','CTRL_S']),
                                 ('calc', ['CTRL_F6','CTRL_HOME','F2','CTRL_END','ENTER','CTRL_S']),
                                 ('impress', ['CTRL_F6','TAB','F2','CTRL_END','CTRL_S'])]:
            with self.subTest(module=module), tempfile.TemporaryDirectory() as directory:
                s,p,b,api,clock,probe,record = self.fixture(directory,module)
                self.setup(s); self.restore_save(s,record)
                receipt = record['imeKeyboardSession']
                self.assertEqual([a['shortcut'] for a in receipt['actions']], sequence)
                self.assertEqual(probe.calls.count(('open',88)),1)
                self.assertEqual(probe.calls.count(('close',2**41)),1)
                self.assertIs(receipt['success'],True)
                self.assertEqual(s.binding,b)
                self.assertEqual(receipt['admissionBasis'],'first measured engine generation; no earlier model-reader witness')
                self.assertNotIn('readerBinding',receipt)
                for action, (_,raw,size) in zip(receipt['actions'],probe.sent):
                    self.assertEqual(size,40); self.assertEqual(action['bufferHex'],raw.hex())
                    self.assertEqual(action['requestedInputs'],action['insertedInputs'])
    def test_root_focus_is_allowed_only_for_the_original_ctrl_f6_transition(self):
        with tempfile.TemporaryDirectory() as directory:
            s,p,b,api,clock,probe,record=self.fixture(directory)
            original=probe.scope_snapshot
            def root_scope(*args):
                scope=original(*args)
                if probe.focus==11:
                    scope['focus']=copy.deepcopy(scope['before']['suite'])
                    scope['focusWithinEditor']=False
                return scope
            probe.scope_snapshot=root_scope; probe.focus=11
            probe.after_send=lambda:setattr(probe,'focus',33)
            s.start(); s.focus_editor(6.); self.ready(s); s.navigate(); self.prefix(s); s.setup_complete(); self.restore_save(s,record)
            self.assertEqual(record['imeKeyboardSession']['actions'][0]['before']['keyboardThreadId'],45)
    def test_ctrl_f6_waits_for_existing_readiness_authority_before_navigation(self):
        with tempfile.TemporaryDirectory() as directory:
            s,p,b,api,clock,probe,record=self.fixture(directory)
            s.start();probe.after_send=lambda:setattr(probe,'focus',0)
            s.focus_editor(6.)
            with self.assertRaises(AssertionError):s.navigate()
            s.close();self.assertEqual(len(probe.sent),1)
            self.assertFalse(record['imeKeyboardSession']['success'])
        with tempfile.TemporaryDirectory() as directory:
            s,p,b,api,clock,probe,record=self.fixture(directory)
            s.start();s.focus_editor(6.)
            self.ready(s)
            with self.assertRaises(AssertionError):self.ready(s)
            s.close();self.assertEqual(len(probe.sent),1)
    def test_navigation_save_or_second_admission_cannot_skip_reorder_or_repeat(self):
        for bad in ('navigate','save','setup_complete','begin_save','start'):
            with self.subTest(bad=bad), tempfile.TemporaryDirectory() as directory:
                s,p,b,api,clock,probe,record=self.fixture(directory); s.start()
                with self.assertRaises(AssertionError):
                    if bad=='begin_save': s.begin_save({},31.)
                    else: getattr(s,bad)()
                s.close(); self.assertEqual(probe.sent,[])
    def test_every_nontransition_chord_requires_strict_editor_focus(self):
        with tempfile.TemporaryDirectory() as directory:
            s,p,b,api,clock,probe,record=self.fixture(directory); s.start(); s.focus_editor(6.); self.ready(s)
            probe.focus=0
            with self.assertRaises(AssertionError): s.navigate()
            s.close(); self.assertEqual(len(probe.sent),1)
    def test_first_admission_joins_actual_activation_and_rejects_older_or_foreign_engine(self):
        for bad in ('activation','engineAge','enginePid','engineImage','engineWait','shellWait','parent','capture'):
            with self.subTest(bad=bad), tempfile.TemporaryDirectory() as directory:
                s,p,b,api,clock,probe,record=self.fixture(directory)
                if bad=='activation': del p.opengeul_activation_binding
                elif bad=='engineAge': probe.engine['creationTime']=probe.shell['creationTime']-1
                elif bad=='enginePid': probe.engine['pid']+=1
                elif bad=='engineImage': probe.engine['image']+='foreign'
                elif bad=='engineWait': probe.engine['waitResult']=0
                elif bad=='shellWait': probe.shell['waitResult']=0
                elif bad=='parent': probe.ancestry=False
                else: probe.capture=5
                with self.assertRaises((AssertionError,AttributeError)): s.start()
                s.close(); self.assertEqual(probe.sent,[])
    def test_later_click_generation_is_joined_using_a_separately_owned_handle(self):
        for changed in (False,True):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as directory:
                s,p,b,api,clock,probe,record=self.fixture(directory); s.start()
                p.opengeul_editor_click_generations={(12,22,88):(88,b['expectedImage'],b['officeCreationTime']+changed)}
                if changed:
                    with self.assertRaisesRegex(AssertionError,'click'): s.focus_editor(6.)
                    s.close(); self.assertEqual(probe.sent,[])
                else:
                    s.focus_editor(6.);self.ready(s);s.navigate();self.prefix(s);s.setup_complete();self.restore_save(s,record)
                self.assertEqual(probe.calls.count(('open',88)),1)
    def test_neutral_us_keyboard_and_stable_lock_state_are_required(self):
        for attr,value in [('layout',0x04120412),('current_layout',0x04120412),('keys_down',[0x11]),('caps',True),('scroll',True)]:
            with self.subTest(attr=attr), tempfile.TemporaryDirectory() as directory:
                s,p,b,api,clock,probe,record=self.fixture(directory);setattr(probe,attr,value)
                with self.assertRaises(AssertionError): s.start()
                s.close();self.assertEqual(probe.sent,[])
    def test_generation_or_editor_thread_change_during_composition_blocks_save(self):
        for mutate in (lambda p:p.engine.update(creationTime=p.engine['creationTime']+1),lambda p:setattr(p,'thread',99)):
            with self.subTest(mutate=mutate), tempfile.TemporaryDirectory() as directory:
                s,p,b,api,clock,probe,record=self.fixture(directory);self.setup(s);mutate(probe)
                with self.assertRaises(AssertionError):self.restore_save(s,record)
                s.close();self.assertEqual(len(probe.sent),2)
    def test_save_requires_exact_successful_restoration_and_original_us_layout(self):
        for change in (lambda r:r.update(status=-3),lambda r:r.update(previousLayout=0x04120412),lambda r:r.update(activeLanguage=0x0412)):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                s,p,b,api,clock,probe,record=self.fixture(directory);self.setup(s)
                record.update(prefixInputLayout=0x04090409,layoutRestored=True)
                restoration=ime_fixtures.KoreanImePolicyTests().restoration();change(restoration)
                with self.assertRaises(AssertionError):s.begin_save(restoration,31.)
                s.close();self.assertEqual(len(probe.sent),2)
    def test_partial_input_releases_only_known_prefix_then_latches_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            s,p,b,api,clock,probe,record=self.fixture(directory);s.start();probe.counts=[2]
            with self.assertRaisesRegex(AssertionError,'partial'):s.focus_editor(6.)
            with self.assertRaises(AssertionError):s.navigate()
            s.close();self.assertEqual([n for n,_,_ in probe.sent],[4,2])
            self.assertTrue(all(e['flags']&2 for e in record['imeKeyboardSession']['actions'][0]['ownedKeyUp']['events']))
    def test_unknown_native_return_never_guesses_a_recovery_prefix(self):
        for value in (None,True,OSError('unknown')):
            with self.subTest(value=repr(value)), tempfile.TemporaryDirectory() as directory:
                s,p,b,api,clock,probe,record=self.fixture(directory);s.start();probe.counts=[value]
                with self.assertRaises(BaseException):s.focus_editor(6.)
                s.close();self.assertEqual(len(probe.sent),1)
                self.assertIsNone(record['imeKeyboardSession']['actions'][0]['insertedInputs'])
    def test_setup_parent_focus_and_save_deadlines_are_distinct_and_cannot_widen(self):
        with tempfile.TemporaryDirectory() as directory:
            s,p,b,api,clock,probe,record=self.fixture(directory);s.start()
            with self.assertRaises(AssertionError):s.focus_editor(11.)
            s.close();self.assertEqual(probe.sent,[])
        with tempfile.TemporaryDirectory() as directory:
            s,p,b,api,clock,probe,record=self.fixture(directory);self.setup(s);clock.now=11.
            self.restore_save(s,record)
            self.assertEqual(record['imeKeyboardSession']['setupDeadline'],10.)
            self.assertEqual(record['imeKeyboardSession']['saveDeadline'],31.)
    def test_expired_or_late_admission_always_closes_a_returned_handle(self):
        with tempfile.TemporaryDirectory() as directory:
            s,p,b,api,clock,probe,record=self.fixture(directory);probe.open_after=lambda:setattr(clock,'now',11.)
            with self.assertRaises(AssertionError):s.start()
            s.close();self.assertEqual(probe.calls.count(('close',2**41)),1)
    def test_close_failure_is_retained_and_never_overwrites_a_primary_error(self):
        with tempfile.TemporaryDirectory() as directory:
            s,p,b,api,clock,probe,record=self.fixture(directory);s.start();probe.close_result=False
            primary=RuntimeError('original primary')
            s.close(primary)
            self.assertIn('original primary',record['imeKeyboardSession']['error'])
            self.assertEqual(len(record['imeKeyboardSession']['cleanupErrors']),1)
            self.assertFalse(record['imeKeyboardSession']['success'])
    def test_setup_cannot_authorize_korean_without_actual_prefix_and_calc_context(self):
        for module in ('writer','calc','impress'):
            with self.subTest(module=module),tempfile.TemporaryDirectory() as directory:
                s,p,b,api,clock,probe,record=self.fixture(directory,module)
                s.start();s.focus_editor(6.);self.ready(s);self.navigate(s)
                if module=='calc':self.prefix(s);record['calcSetupContext']['success']=False
                with self.assertRaises(AssertionError):s.setup_complete()
                s.close();self.assertFalse(record['imeKeyboardSession']['success'])
    def test_first_admission_publishes_only_generation_for_later_sessions(self):
        with tempfile.TemporaryDirectory() as directory:
            s,p,b,api,clock,probe,record=self.fixture(directory);self.setup(s);self.restore_save(s,record)
            generation=(88,b['expectedImage'],b['officeCreationTime'])
            self.assertEqual(p.opengeul_editor_shortcut_generations,{(12,22,88):generation})
            witness=record['imeKeyboardSession']['sharedShortcutAdmission']
            self.assertEqual(witness['generation'],list(generation))
            self.assertEqual(witness['firstAdmittedAt'],record['imeKeyboardSession']['engineHandleAdmittedAt'])
            self.assertNotIn('handleValue',witness)
    def test_prior_shared_generation_is_joined_without_backdating_our_handle(self):
        for changed in (False,True):
            with self.subTest(changed=changed),tempfile.TemporaryDirectory() as directory:
                s,p,b,api,clock,probe,record=self.fixture(directory)
                generation=(88,b['expectedImage'],b['officeCreationTime']+changed)
                p.opengeul_editor_shortcut_generations={(12,22,88):generation}
                p.opengeul_editor_shortcut_admissions={(12,22,88):dict(generation=list(generation),firstAdmittedAt=.5,basis='first measured native shortcut HANDLE admission; no earlier reader proof claimed')}
                if changed:
                    with self.assertRaisesRegex(AssertionError,'generation'):s.start()
                    self.assertEqual(probe.sent,[])
                else:
                    self.setup(s);self.restore_save(s,record)
                    witness=record['imeKeyboardSession']['sharedShortcutAdmission']
                    self.assertEqual(witness['firstAdmittedAt'],.5)
                    self.assertEqual(record['imeKeyboardSession']['engineHandleAdmittedAt'],1.)
    def test_shared_generation_change_after_admission_blocks_next_input(self):
        with tempfile.TemporaryDirectory() as directory:
            s,p,b,api,clock,probe,record=self.fixture(directory);s.start()
            generation=(88,b['expectedImage'],b['officeCreationTime']+1)
            p.opengeul_editor_shortcut_generations={(12,22,88):generation}
            p.opengeul_editor_shortcut_admissions={(12,22,88):dict(generation=list(generation),firstAdmittedAt=.5,basis='prior admission')}
            with self.assertRaisesRegex(AssertionError,'generation'):s.focus_editor(6.)
            s.close();self.assertEqual(probe.sent,[])
