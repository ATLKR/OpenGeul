"""Finite first-admission keyboard setup/save for the real native IME cases.

One retained engine HANDLE begins here, without an earlier UNO reader witness.
Insertion counts prove native acceptance; real composition and saved/reopened
content remain the independent delivery and edit-mode checks.
"""
from __future__ import annotations
import json
import math
import os
from pathlib import Path
import re
import time

from counted_editor_shortcuts import (NativeShortcutProbe, US_LAYOUT,
    input_buffer, shortcut_events, owned_release_events,
    join_shortcut_generation, admit_shortcut_generation)

SETUP = {'writer': ('CTRL_END',), 'calc': ('CTRL_HOME', 'F2', 'CTRL_END'),
         'impress': ('TAB', 'F2', 'CTRL_END')}
MAX_RECEIPT_BYTES = 256 * 1024


def _error(exc): return type(exc).__name__ + ': ' + str(exc)[:1024]
def _same(left, right): return str(Path(left).resolve()).casefold() == str(Path(right).resolve()).casefold()
def _number(value): return type(value) in (int, float) and math.isfinite(value)


class IMEKeyboardSession:
    def __init__(self, api, process, root, parent, child, pid, module, record,
                 setup_deadline, *, probe=None, clock=time.monotonic, retain_evidence=True):
        assert module in SETUP and _number(setup_deadline)
        assert type(retain_evidence) is bool, 'Keyboard evidence retention requires an explicit boolean'
        self.retain_evidence = retain_evidence
        self.api, self.process, self.module, self.record = api, process, module, record
        self.clock, self.deadline, self.setup_deadline = clock, setup_deadline, setup_deadline
        assert clock() < setup_deadline <= clock() + 60, 'IME setup deadline exceeds its shared bound'
        for value in (root, parent, child, pid): assert type(value) is int and value > 0
        self.binding = dict(shellPid=process.pid, officePid=pid, suiteHwnd=root,
                            parentHwnd=parent, childHwnd=child, rootHwnd=root)
        self.probe = probe
        self.native_probe = probe is None
        self.handle = None
        self.shell = self.engine = None
        self.shared_admission = None
        self.tid = self.focus = self.locks = None
        self.phase = 'new'; self.failed = None; self.finished = False
        self.semantic_pre = self.semantic_post = None
        self.calc_navigation = self.calc_navigation_times = self.calc_navigation_url = None
        self.output = self.stem = None
        self.receipt = dict(schemaVersion=1, kind='owned-first-admission-ime-keyboard',
            success=False, module=module, startedAt=clock(), setupDeadline=setup_deadline,
            admissionBasis='first measured engine generation; no earlier model-reader witness',
            actions=[], cleanupErrors=[], engineHandleReleased=False,
            inputCountBasis='SendInput return counts; composition and saved/reopened markers prove delivery')
        assert 'imeKeyboardSession' not in record, 'IME keyboard admission cannot repeat'
        record['imeKeyboardSession'] = self.receipt

    def _budget(self): assert self.clock() < self.deadline, 'IME keyboard deadline expired'
    def _retain(self, phase):
        raw=(json.dumps(self.receipt,ensure_ascii=False,separators=(',', ':'),allow_nan=False)+'\n').encode()
        assert len(raw)<=MAX_RECEIPT_BYTES, 'IME shortcut receipt exceeds bound'
        if not self.retain_evidence: return
        suffix=phase if phase in ('admission','session-result') else f'{len(self.receipt["actions"])-1:02d}-'+phase
        with (self.output/(self.stem+'-'+suffix+'.json')).open('xb') as stream:
            stream.write(raw);stream.flush();os.fsync(stream.fileno())
    def _run(self, callback):
        if self.failed is not None: raise self.failed
        assert not self.finished, 'IME keyboard session already closed'
        try: return callback()
        except BaseException as exc:
            self.failed=exc
            raise
    def start(self):
        def admit():
            assert self.phase=='new', 'IME engine admission cannot repeat'
            self._budget();p=self.process;b=self.binding
            self.output=Path(p.opengeul_evidence_output);suite=Path(p.opengeul_suite_root)
            assert self.output.is_absolute() and self.output.is_dir() and suite.is_absolute()
            for part in (self.output,*self.output.parents):
                assert not part.is_symlink() and not getattr(part,'is_junction',lambda:False)(), 'Linked IME keyboard evidence'
            assert re.fullmatch(r'[A-Za-z0-9_-]{1,100}',p.opengeul_evidence_case)
            assert isinstance(p.args,(list,tuple)) and _same(p.args[0],suite/'OpenGeul.Office.exe')
            assert type(p.pid) is int and p.pid>0 and int(p._handle)>0
            assert b['officePid'] != p.pid, 'IME engine must differ from original Suite shell'
            self.stem=p.opengeul_evidence_case+'-ime-keyboard'
            self.receipt['receiptStem']=self.stem
            if self.probe is None:self.probe=NativeShortcutProbe(self.deadline,self.clock)
            self._budget();shell=self.probe.process_snapshot(p)
            expected=(p.pid,int(p._handle),str((suite/'OpenGeul.Office.exe').resolve()),shell['creationTime'],258)
            assert type(shell['creationTime']) is int and shell['creationTime']>0
            assert (shell['pid'],shell['handleValue'],shell['image'],shell['creationTime'],shell['waitResult'])==expected, 'Original retained shell identity changed'
            assert p.opengeul_activation_binding==expected, 'Original activation generation differs'
            self.shell=shell
            self._budget();self.handle=self.probe.open_engine(b['officePid'])
            assert type(self.handle) is int and self.handle>0, 'IME engine HANDLE admission failed'
            self.receipt['engineHandleAdmittedAt']=self.clock()
            self._budget();engine=self.probe.engine_snapshot(self.handle)
            assert (engine['pid'],engine['handleValue'],engine['waitResult'])==(b['officePid'],self.handle,258), 'Owned IME engine identity changed'
            assert type(engine['creationTime']) is int and engine['creationTime']>=shell['creationTime'], 'IME engine predates original shell'
            assert _same(engine['image'],suite/'Office/program/soffice.bin'), 'IME engine image changed'
            self.engine=engine
            self.shared_admission=join_shortcut_generation(p,b['parentHwnd'],b['childHwnd'],engine)
            b.update(shellCreationTime=shell['creationTime'],officeCreationTime=engine['creationTime'],expectedImage=engine['image'])
            self.receipt.update(originalShell=shell,originalEngine=engine,expectedNative=dict(b))
            self.receipt['admissionSnapshot']=self._guard(strict=False)
            self.shared_admission=admit_shortcut_generation(p,b['parentHwnd'],b['childHwnd'],engine,
                self.receipt['engineHandleAdmittedAt'])
            self.receipt['sharedShortcutAdmission']=self.shared_admission
            self._retain('admission');self._budget();self.phase='admitted'
            return self
        try:return self._run(admit)
        except BaseException as exc:
            self.close(exc)
            raise
    def _observe_guard(self, strict):
        self._budget();b=self.binding
        row={};self.receipt['lastGuardObservation']=row
        row['shell']=self.probe.process_snapshot(self.process)
        self._budget();row['engine']=self.probe.engine_snapshot(self.handle)
        self._budget();row['scope']=self.probe.scope_snapshot(self.api,b)
        scope=row['scope']
        target=scope['before']['editor'] if strict else (scope['focus'] if scope['focus']['hwnd'] else scope['before']['foreground'])
        thread=target['threadId']
        assert type(thread) is int and thread>0, 'IME guard has no measured keyboard thread'
        row['keyboardThreadId']=thread
        self._budget();row['keyboard']=self.probe.keyboard_snapshot(thread)
        return row
    def _validate_guard(self, row, strict):
        from windows_smoke import _editor_focus_snapshot_ready
        b=self.binding;shell,engine,scope,keyboard=(row[key] for key in ('shell','engine','scope','keyboard'))
        assert shell==self.shell and engine==self.engine, 'Retained IME native generation changed'
        joined=join_shortcut_generation(self.process,b['parentHwnd'],b['childHwnd'],engine)
        assert joined==self.shared_admission, 'Shared IME shortcut generation admission changed'
        prior=getattr(self.process,'opengeul_editor_click_generations',{})
        key=(b['parentHwnd'],b['childHwnd'],b['officePid'])
        if key in prior:
            old=prior[key]
            assert (old[0],old[2])==(engine['pid'],engine['creationTime']) and _same(old[1],engine['image']), 'Owned click generation differs from retained IME engine'
            self.receipt['separateClickGenerationJoined']=True
        tid=scope['before']['editor']['threadId']
        assert type(tid) is int and tid>0
        if self.tid is None:self.tid=tid
        assert tid==self.tid, 'Owned IME editor thread changed'
        _editor_focus_snapshot_ready(scope,b['suiteHwnd'],b['childHwnd'],b['shellPid'],b['officePid'],self.tid)
        parent=scope['parent']
        assert (parent['hwnd'],parent['pid'],parent['rootHwnd'],parent['isWindow'])==(b['parentHwnd'],b['shellPid'],b['suiteHwnd'],True), 'IME owned parent changed'
        assert all(scope[key] is True for key in ('suiteOwnsParent','parentOwnsChild','parentVisible','parentEnabled','childVisible','childEnabled')), 'IME owned ancestry unavailable'
        target=scope['focus'] if scope['focus']['hwnd'] else scope['before']['foreground']
        assert target['pid'] in (b['shellPid'],b['officePid']) and target['rootHwnd']==b['suiteHwnd'] and target['isWindow'], 'IME focus transition has no owned keyboard target'
        if strict:
            assert scope['focusWithinEditor'] is True and scope['focus']['pid']==b['officePid'], 'Strict IME editor focus unavailable'
            assert row['keyboardThreadId']==self.tid
        else:
            assert row['keyboardThreadId']==target['threadId']
        self._budget();self.api.require_foreground(b['suiteHwnd'])
        assert keyboard['targetLayout']==keyboard['currentThreadLayout']==US_LAYOUT, 'IME shortcut requires exact original US layout'
        assert keyboard['keysDown']==[], 'IME shortcut requires neutral keys'
        locks=tuple(keyboard[key] for key in ('capsLockOn','scrollLockOn','numLockOn'))
        assert all(type(value) is bool for value in locks) and not locks[0] and not locks[1], 'IME lock state is not neutral'
        if self.locks is None:self.locks=locks
        assert locks==self.locks, 'IME lock state changed'
        self._budget()
    def _guard(self, *, strict=True, context_check=None):
        from capture_readiness import settle_owned_capture
        diagnostic=None
        def sample(capture):
            # Passive evidence only: never release capture, inject input or extend
            # the shared deadline. The low GetAsyncKeyState bit is not delivery proof.
            diagnostic['sampleAttempts']+=1
            result=dict(status='unavailable',capture=dict(capture),observedAt=self.clock(),buttons=[])
            try:
                for key in (1,2,4,5,6):
                    self._budget()
                    state=int(self.probe.user.GetAsyncKeyState(key))
                    self._budget()
                    result['buttons'].append(dict(virtualKey=key,rawState=state,down=bool(state & 0x8000)))
                result.update(status='observed',finishedAt=self.clock())
            except Exception as exc:result['error']=_error(exc)
            return result
        def validate(row):
            nonlocal diagnostic
            self._validate_guard(row,strict)
            if context_check is not None:context_check()
            scope=row['scope'];capture=scope['capture'];b=self.binding
            expected={b['shellPid']:scope['before']['suite']['threadId'],
                      b['officePid']:scope['before']['editor']['threadId']}
            owned=(type(capture.get('hwnd')) is int and capture['hwnd']>0
                and capture.get('isWindow') is True and capture.get('rootHwnd')==b['suiteHwnd']
                and capture.get('pid') in expected
                and capture.get('threadId')==expected[capture['pid']]>0)
            if not owned:return
            # Repeated metadata is not HWND lifetime proof; handles can be reused.
            identity={key:capture[key] for key in ('hwnd','pid','threadId','rootHwnd','isWindow')}
            if diagnostic is None:
                diagnostic=dict(deadline=self.deadline,sampleAttempts=0)
                self.receipt['captureButtonDiagnostics']=diagnostic
                diagnostic['first']=sample(identity)
            elif ('final' not in diagnostic and identity==diagnostic['first']['capture']
                  and 0<self.deadline-self.clock()<=.05):
                diagnostic['final']=sample(identity)
        try:
            row=settle_owned_capture(lambda:self._observe_guard(strict),validate,
                self.receipt,self.binding,self.deadline,clock=self.clock)
        finally:
            if diagnostic is not None and 'final' not in diagnostic:
                # No stale native query after failure/settlement. Oversleep can
                # leave no final pre-deadline sample; say so rather than infer it.
                diagnostic['final']=dict(status='unavailable',reason=(
                    'original-deadline-exhausted' if self.clock()>=self.deadline
                    else 'no-final-original-capture-observation'))
        if strict:
            from windows_smoke import _editor_focus_snapshot_ready
            b=self.binding
            focus=_editor_focus_snapshot_ready(row['scope'],b['suiteHwnd'],b['childHwnd'],b['shellPid'],b['officePid'],self.tid)
            assert focus and focus==row['scope']['focus']['hwnd'], 'Strict IME editor focus changed before shortcut'
            self.focus=focus
        if context_check is not None:context_check()
        self._budget()
        return row
    def _press(self, preset, *, transition=False):
        self._budget();events=shortcut_events(preset)
        action=dict(shortcut=preset,events=events,bufferHex=bytes(input_buffer(events)).hex(),
            requestedInputs=len(events),insertedInputs=None,inputCallAttempts=0,startedAt=self.clock(),
            inputCountBasis='native shortcut call not attempted',deadline=self.deadline,before=self._guard(strict=not transition))
        action['knownPrefixReleasePlans']={str(n):dict(events=owned_release_events(events,n),bufferHex=bytes(input_buffer(owned_release_events(events,n))).hex()) for n in range(len(events))}
        self.receipt['actions'].append(action);self._retain('input-intent');self._budget()
        action['beforeInsertion']=self._guard(strict=not transition)
        initial,current=action['before']['scope'],action['beforeInsertion']['scope'];b=self.binding
        unchanged=current['focus']['hwnd']==initial['focus']['hwnd']
        entered_exact_child=(transition and preset=='CTRL_F6'
            and initial['focus']['hwnd'] in (b['suiteHwnd'],b['parentHwnd'])
            and initial['focus']['pid']==b['shellPid']
            and initial['focus']['threadId']==initial['before']['suite']['threadId']
            and current['focus']['hwnd']==b['childHwnd'] and current['focusWithinEditor'] is True
            and current['focus']['pid']==b['officePid'] and current['focus']['threadId']==self.tid)
        assert unchanged or entered_exact_child, 'IME focus changed while retaining intent'
        action['focusIntentTransition']='unchanged' if unchanged else 'owned-host-to-exact-original-editor-child'
        self._budget()
        action.update(inputCallAttempts=1,inputCountBasis='native shortcut call attempted; return unavailable')
        value=self.probe.send(input_buffer(events))
        if type(value) is not int or not 0<=value<=len(events):
            action['invalidNativeReturn']=repr(value)[:128]
            raise AssertionError('IME shortcut native insertion count is unknown')
        action.update(insertedInputs=value,inputCountBasis='SendInput return value')
        if value!=len(events):
            releases=owned_release_events(events,value)
            if releases:
                result=action['ownedKeyUp']=dict(events=releases,bufferHex=bytes(input_buffer(releases)).hex(),requestedInputs=len(releases),insertedInputs=None)
                try:
                    count=self.probe.release(input_buffer(releases))
                    assert type(count) is int and 0<=count<=len(releases), 'Unknown owned IME key-up count'
                    result['insertedInputs']=count
                    assert count==len(releases), 'Partial owned IME key-up cleanup'
                except BaseException as exc:result['error']=_error(exc)
            raise AssertionError('IME shortcut had partial native insertion')
        self._budget();action['after']=self._guard(strict=not transition)
        action['finishedAt']=self.clock();self._retain('input-result');self._budget()
    def focus_editor(self, focus_deadline):
        def focus():
            assert self.phase=='admitted', 'IME focus transition cannot repeat or reorder'
            assert _number(focus_deadline) and self.clock()<focus_deadline<=self.setup_deadline, 'IME focus parent deadline exceeds setup bound'
            old=self.deadline;self.deadline=focus_deadline
            if self.native_probe:self.probe.deadline=focus_deadline
            try:self._press('CTRL_F6',transition=True)
            finally:
                self.deadline=old
                if self.native_probe:self.probe.deadline=old
            self.receipt['focusDeadline']=focus_deadline
            self.phase='awaiting-editor-readiness'
        return self._run(focus)
    def editor_ready(self, evidence):
        def acknowledge():
            from windows_smoke import require_editor_focus_readiness
            assert self.phase=='awaiting-editor-readiness', 'IME editor readiness cannot repeat or reorder'
            assert evidence is self.record.get('editorFocusReadiness'), 'IME readiness must be its actual parent receipt'
            b=self.binding
            require_editor_focus_readiness(evidence,b['suiteHwnd'],b['childHwnd'],b['shellPid'],b['officePid'])
            action,=self.receipt['actions']
            assert (evidence['startedAt'] <= action['startedAt'] <= action['finishedAt']
                    <= evidence['deadline'] == self.receipt['focusDeadline'] <= self.setup_deadline), 'IME CtrlF6 differs from parent readiness budget'
            assert evidence['editorThreadId']==self.tid, 'IME readiness editor thread changed'
            self._guard()
            assert evidence['focusHwnd']==self.focus, 'IME readiness final focus changed'
            self.receipt['editorReadinessAcknowledgedAt']=self.clock()
            self.phase='focused'
        return self._run(acknowledge)
    def navigate(self):
        def navigate():
            assert self.phase=='focused', 'IME setup navigation cannot repeat or reorder'
            assert self.module!='calc', 'Calc requires its source-bound pre-F2 navigation barrier'
            for preset in SETUP[self.module]:self._press(preset)
            self.phase='navigated'
        return self._run(navigate)
    def require_calc_navigation_initial_target(self):
        """Read-only admission before evaluating navigate_calc's shell argument."""
        def current():
            assert self.module=='calc' and self.phase=='focused', 'Calc initial navigation shell phase unavailable'
            assert self.deadline==self.setup_deadline==self.receipt['setupDeadline'], 'Calc initial navigation shell budget changed'
            assert self.calc_navigation is self.calc_navigation_times is self.calc_navigation_url is None, 'Calc navigation already admitted'
            assert 'calcNavigationContext' not in self.record and 'calcNavigationReadiness' not in self.receipt, 'Calc navigation context already exists'
            assert len(self.receipt['actions'])==1, 'Calc initial shell requires its single original CtrlF6'
            action=self.receipt['actions'][0]
            assert action['shortcut']=='CTRL_F6' and all(type(action[key]) is int and action[key]==value
                for key,value in (('requestedInputs',4),('insertedInputs',4),('inputCallAttempts',1))), 'Calc initial CtrlF6 is incomplete'
            acknowledged=self.receipt.get('editorReadinessAcknowledgedAt')
            assert _number(acknowledged) and action['finishedAt']<=acknowledged<self.setup_deadline, 'Calc initial editor readiness is not acknowledged'
            return self._guard()
        return self._run(current)
    def require_calc_navigation_target(self):
        def current():
            assert self.module=='calc' and self.phase in ('calc-navigation-initial','calc-navigation-home'), 'Calc navigation reader phase unavailable'
            assert self.deadline==self.setup_deadline, 'Calc navigation guard cannot renew or nest another budget'
            context=self.record.get('calcNavigationContext')
            assert isinstance(context,dict), 'Actual Calc navigation context is missing'
            if self.calc_navigation is None:
                self.calc_navigation=context
                self.calc_navigation_times=(context.get('startedAt'),context.get('readerDeadline'))
            started,deadline=self.calc_navigation_times
            def validate():
                assert self.record.get('calcNavigationContext') is self.calc_navigation is context, 'Actual Calc navigation context changed'
                assert context.get('kind')=='ime-calc-pre-edit-navigation' and context.get('expectedNative')==self.binding
                assert context.get('expectedUrl')==self.calc_navigation_url, 'Original Calc navigation document URL changed'
                assert context.get('setupDeadline')==self.setup_deadline
                assert context.get('startedAt')==started and context.get('readerDeadline')==deadline
                assert _number(started) and _number(deadline) and started<=self.clock()<deadline==min(self.setup_deadline,started+12.), 'Calc navigation reader deadline changed or expired'
            validate();previous=self.deadline
            if self.native_probe:previous_probe=self.probe.deadline
            self.deadline=deadline
            if self.native_probe:self.probe.deadline=deadline
            try:return self._guard(context_check=validate)
            finally:
                self.deadline=previous
                if self.native_probe:self.probe.deadline=previous_probe
        return self._run(current)
    def navigate_calc(self,suite,source,original_bytes,*,original_shell,reader_factory=None):
        def navigate():
            from ime_calc_navigation import observe_calc_navigation,require_calc_navigation
            assert self.module=='calc' and self.phase=='focused', 'Calc navigation cannot repeat or reorder'
            assert self.calc_navigation is None and len(self.receipt['actions'])==1
            assert original_shell['pid']==self.shell['pid'] and original_shell['handleValue']==self.shell['handleValue']
            assert original_shell['nativeCreation']['fileTime']==self.shell['creationTime']
            assert _same(original_shell['nativeImage'],self.shell['image']), 'Calc navigation replaced original Popen identity'
            self.calc_navigation_url=Path(source).as_uri()
            self.phase='calc-navigation-initial'
            def home():
                assert self.phase=='calc-navigation-initial' and len(self.receipt['actions'])==1, 'Calc CtrlHome cannot repeat or reorder'
                self.require_calc_navigation_target()
                assert 'initial' in self.calc_navigation and 'homeCommand' not in self.calc_navigation
                self.phase='calc-navigation-home'
                previous=self.deadline
                if self.native_probe:previous_probe=self.probe.deadline
                self.deadline=self.calc_navigation_times[1]
                if self.native_probe:self.probe.deadline=self.deadline
                try:self._press('CTRL_HOME')
                finally:
                    self.deadline=previous
                    if self.native_probe:self.probe.deadline=previous_probe
                return self.receipt['actions'][-1]
            context=observe_calc_navigation(suite,source,original_bytes,self.record,self.setup_deadline,
                original_shell=original_shell,expected_native=self.binding,
                require_current=self.require_calc_navigation_target,send_home=home,
                reader_factory=reader_factory,clock=self.clock)
            assert context is self.calc_navigation is self.record.get('calcNavigationContext')
            require_calc_navigation(context,suite=suite,expected_native=self.binding,expected_url=self.calc_navigation_url,
                setup_deadline=self.setup_deadline,now=self.clock())
            assert context['homeCommand'] is self.receipt['actions'][1]
            self.phase='calc-navigation-ready'
            self.receipt['calcNavigationReadiness']=dict(finishedAt=context['finishedAt'],
                readerDeadline=context['readerDeadline'],acknowledgedAt=self.clock())
            self._press('F2');self._press('CTRL_END');self.phase='navigated'
        return self._run(navigate)
    def _replay_semantic(self, phase):
        from ime_semantic_context import require_ime_semantic_context
        if self.module=='calc':
            from ime_calc_navigation import require_calc_navigation,_time as _time_navigation
            assert self.calc_navigation is not None and self.record.get('calcNavigationContext') is self.calc_navigation, 'Actual Calc navigation proof changed or is missing'
            require_calc_navigation(self.calc_navigation,suite=self.process.opengeul_suite_root,
                expected_native=self.binding,expected_url=self.calc_navigation_url,setup_deadline=self.setup_deadline,now=self.clock())
            readiness=self.receipt['calcNavigationReadiness'];actions=self.receipt['actions']
            assert [row['shortcut'] for row in actions]==['CTRL_F6','CTRL_HOME','F2','CTRL_END']
            assert self.calc_navigation['homeCommand'] is actions[1]
            assert _time_navigation(readiness['finishedAt'])==self.calc_navigation['finishedAt'] and _time_navigation(readiness['readerDeadline'])==self.calc_navigation['readerDeadline']
            pre=self.record['imeSemanticContexts'][0]
            assert (self.calc_navigation['finishedAt'] <= _time_navigation(readiness['acknowledgedAt'])
                <= _time_navigation(actions[2]['startedAt']) <= _time_navigation(actions[2]['finishedAt'])
                <= _time_navigation(actions[3]['startedAt']) <= _time_navigation(actions[3]['finishedAt'])
                <= _time_navigation(pre['startedAt'])), 'Calc semantic PRE overlaps original source navigation or F2/End'
        self._budget();contexts=self.record.get('imeSemanticContexts')
        assert isinstance(contexts,list) and len(contexts) in (1,2), 'IME requires actual finite semantic contexts'
        assert contexts[0] is self.semantic_pre and self.record.get('imeSemanticContext') is contexts[-1], 'Actual IME semantic context identity changed'
        if phase=='post':
            assert len(contexts)==2 and contexts[1] is self.semantic_post, 'Actual POST semantic context identity changed'
        context=self.semantic_pre if phase=='pre' else self.semantic_post
        result=require_ime_semantic_context(context,module=self.module,expected_native=self.binding,
            setup_deadline=self.setup_deadline,now=self.clock(),phase=phase,
            expected_prefix=None if phase=='pre' else self.record.get('asciiPrefix'))
        self._budget()
        return result
    def semantic_ready(self, context, *, phase):
        def acknowledge():
            assert phase in ('pre','post'), 'Unknown IME semantic acknowledgement phase'
            assert self.phase==('navigated' if phase=='pre' else 'semantic-pre-ready'), 'IME semantic acknowledgement cannot repeat or reorder'
            contexts=self.record.get('imeSemanticContexts')
            count=1 if phase=='pre' else 2
            assert isinstance(contexts,list) and len(contexts)==count and contexts[-1] is context, 'IME acknowledgement requires its actual returned semantic context'
            assert self.record.get('imeSemanticContext') is context, 'IME latest semantic context changed'
            if phase=='pre':self.semantic_pre=context
            else:
                assert contexts[0] is self.semantic_pre, 'Actual PRE semantic context changed before POST'
                self.semantic_post=context
                self._replay_semantic('pre')
            self._replay_semantic(phase);self._guard()
            self.receipt.setdefault('semanticReadiness',[]).append(dict(phase=phase,acknowledgedAt=self.clock(),
                readerFinishedAt=context['finishedAt'],readerDeadline=context['readerDeadline'],setupDeadline=self.setup_deadline))
            self._budget();self.phase='semantic-'+phase+'-ready'
        return self._run(acknowledge)
    def require_prefix_ready(self):
        def current():
            assert self.phase=='semantic-pre-ready', 'Physical IME prefix requires completed PRE semantic cleanup'
            self._replay_semantic('pre')
            return self._guard()
        return self._run(current)
    def require_context_target(self, context_key):
        def current():
            assert context_key in ('imeSemanticContext','calcSetupContext'), 'Unknown IME reader context key'
            assert self.phase in ('navigated','semantic-pre-ready','semantic-post-ready'), 'IME reader target phase unavailable'
            assert self.deadline==self.setup_deadline, 'IME reader guard cannot nest or renew another phase'
            context=self.record.get(context_key)
            assert isinstance(context,dict), 'Actual IME reader context is missing'
            started=context.get('startedAt');deadline=context.get('readerDeadline')
            def validate_context():
                assert self.record.get(context_key) is context, 'Actual IME reader context identity changed'
                assert context.get('expectedNative')==self.binding, 'IME reader context native binding changed'
                assert context.get('setupDeadline')==self.setup_deadline, 'IME reader context setup deadline changed'
                assert _number(started) and _number(deadline) and context.get('startedAt')==started and context.get('readerDeadline')==deadline
                assert started<=self.clock()<deadline==min(self.setup_deadline,started+12.), 'IME reader context deadline/order changed'
                if context_key=='imeSemanticContext':
                    assert context.get('kind')=='ime-semantic-editing-context' and context.get('module')==self.module and context.get('phase') in ('pre','post')
                else:
                    assert self.module=='calc' and context.get('kind')=='ime-calc-single-observation-setup'
            validate_context();previous=self.deadline
            if self.native_probe:previous_probe=self.probe.deadline
            self.deadline=deadline
            if self.native_probe:self.probe.deadline=deadline
            try:return self._guard(context_check=validate_context)
            finally:
                self.deadline=previous
                if self.native_probe:self.probe.deadline=previous_probe
        return self._run(current)
    def require_target(self):
        def current():
            assert self.phase in ('navigated','semantic-pre-ready','semantic-post-ready','composition'), 'IME setup target is unavailable'
            return self._guard()
        return self._run(current)
    def setup_complete(self):
        def complete():
            from korean_ime_smoke import require_ascii_prefix
            assert self.phase=='semantic-post-ready', 'IME setup requires PRE and POST semantic cleanup'
            self._replay_semantic('pre');self._replay_semantic('post')
            require_ascii_prefix(self.record)
            assert (self.record['editorTid'],self.record['keyboardFocusHwnd']) == (self.tid,self.focus), 'IME prefix differs from retained editor'
            if self.module=='calc':
                context=self.record.get('calcSetupContext',{})
                assert context.get('success') is True and context.get('nativeImeObserved') is False, 'Calc context must complete before native IME setup'
                assert context.get('expectedNative')==self.binding and context.get('expectedPrefix')==self.record['asciiPrefix'], 'Calc context differs from first admission or prefix'
                assert (_number(context.get('readerDeadline')) and _number(context.get('finishedAt'))
                    and 0 <= context['finishedAt'] <= self.clock()
                    and context['finishedAt'] <= context['readerDeadline'] <= self.setup_deadline), 'Calc context exceeded original setup deadline'
            self._guard();self.receipt['setupFinishedAt']=self.clock();self.phase='composition'
        return self._run(complete)
    def begin_save(self, restoration, save_deadline):
        def save_phase():
            from korean_ime_smoke import validate_restoration, require_ime_save_disposition
            assert self.phase=='composition', 'IME save requires completed setup and composition'
            validate_restoration(restoration)
            require_ime_save_disposition(self.record, restoration)
            assert self.record.get('layoutRestored') is True and self.record.get('prefixInputLayout')==restoration['previousLayout']==US_LAYOUT, 'IME save requires exact original US restoration'
            assert _number(save_deadline) and self.clock()<save_deadline<=self.clock()+30, 'IME save deadline exceeds original bound'
            self.deadline=save_deadline
            if self.native_probe:self.probe.deadline=save_deadline
            self.receipt.update(saveStartedAt=self.clock(),saveDeadline=save_deadline,restoration=dict(restoration))
            self._guard();self.phase='save'
        return self._run(save_phase)
    def save(self):
        def save_keys():
            assert self.phase=='save', 'IME save cannot repeat or reorder'
            if self.module=='calc':self._press('ENTER')
            self._press('CTRL_S');self.phase='saved'
        return self._run(save_keys)
    def close(self, primary=None):
        if self.finished:return
        self.finished=True
        primary=primary or self.failed
        incoming_primary=primary
        if self.handle is not None:
            try:
                assert self.probe.close_engine(self.handle) is True, 'IME engine HANDLE close failed'
                self.receipt['engineHandleReleased']=True
            except BaseException as exc:
                self.receipt['cleanupErrors'].append(_error(exc))
                if primary is None:primary=exc
        finished=self.clock()
        if primary is None and (self.phase!='saved' or finished>self.deadline):
            primary=AssertionError('IME keyboard session incomplete or beyond deadline')
        if primary is not None:self.receipt['error']=_error(primary)
        self.receipt.update(finishedAt=finished,success=primary is None)
        try:
            if self.output is not None and self.stem is not None:self._retain('session-result')
        except BaseException as exc:
            self.receipt.update(success=False,retentionError=_error(exc))
            if primary is None:primary=exc
        if incoming_primary is None and primary is not None:raise primary
