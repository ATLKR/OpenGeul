"""One preregistered 20-trial physical-ASCII experiment, never qualification.

Ten observed trials alternate with ten pristine controls. Every trial calls the
original dirty_cancel_save action and original Case.edit/physical INPUT buffers.
Only observed trials add a thread-scoped protocol-2 WH_GETMESSAGE observer and
one read-only existing Writer Text.String observation before the original Save.
Neither queue removal nor SendInput insertion certifies VCL model consumption.
The observer and UNO getter can change scheduling; a pass cannot explain an
earlier failure. There are no input/model retries, pacing changes or mutations.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import ctypes
from ctypes import wintypes as W
import hashlib
import inspect
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import traceback

import lifecycle_smoke as lifecycle
import native_accessibility as accessible
from keyboard_delivery import DeliveryObserver, ObserverLibrary, Message as DeliveryMessage, State as DeliveryState
from startup_smoke import EngineProcessWitness

CASE = 'dirty-writer-cancel-save'
DELIVERY_SHA256 = '0a08413dce9cccd9c63247f9f92911075318f04e8b4de3eafd32bec67e6c1042'
PHASES = ('after-first-edit', 'before-live-model-read', 'after-live-model-read')
SOURCE_FILES = ('physical_ascii_probe.py', 'keyboard_delivery.py', 'lifecycle_smoke.py',
                'ascii_editor_input.py', 'windows_smoke.py', 'startup_smoke.py',
                'native_accessibility.py', 'writer_style_smoke.py')


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def trial_plan():
    return [dict(trial=index+1, trialId=f'trial-{index+1:02d}-'+('observed' if index%2==0 else 'control'),
                 case=CASE, instrumented=index%2==0) for index in range(20)]


class NativeClock:
    """Raw cross-process QPC ticks; never compare perf_counter_ns to QPC ticks."""
    def __init__(self, kernel=None):
        kernel = ctypes.WinDLL('kernel32', use_last_error=True) if kernel is None else kernel
        self.query = kernel.QueryPerformanceCounter if hasattr(kernel, 'QueryPerformanceCounter') else None
        frequency = kernel.QueryPerformanceFrequency
        frequency.argtypes, frequency.restype = (ctypes.POINTER(ctypes.c_int64),), W.BOOL
        value = ctypes.c_int64()
        if not frequency(ctypes.byref(value)):
            raise OSError('QueryPerformanceFrequency failed')
        assert value.value > 0, 'Native QPC frequency is invalid'
        self.frequency = int(value.value)
        assert self.query is not None, 'QueryPerformanceCounter is unavailable'
        self.query.argtypes, self.query.restype = (ctypes.POINTER(ctypes.c_int64),), W.BOOL

    def sample(self):
        value = ctypes.c_int64()
        if not self.query(ctypes.byref(value)):
            raise OSError('QueryPerformanceCounter failed')
        assert value.value > 0, 'Native QPC counter is invalid'
        return dict(counter=int(value.value), frequency=self.frequency)


def _clock(value, frequency=None):
    assert isinstance(value, dict) and type(value.get('counter')) is int and value['counter'] > 0, 'Invalid native clock counter'
    assert type(value.get('frequency')) is int and value['frequency'] > 0, 'Invalid native clock frequency'
    assert frequency is None or value['frequency'] == frequency, 'Native clock frequencies differ'
    return value['counter']


def require_queue_prefix(prefix, office_pid, editor_tid, child_hwnd, frequency, previous_rows=None):
    """Validate protocol-2 facts; partial publication/overflow stay unresolved."""
    begin,end = (_clock(prefix[key],frequency) for key in ('qpcBegin','qpcEnd'))
    assert begin <= end, 'Native queue-prefix clock order differs'
    queue=prefix['queue']
    assert (queue['officePid'],queue['editorTid'],queue['childHwnd']) == (office_pid,editor_tid,child_hwnd), 'Queue observer ownership differs'
    assert all(type(v) is int and v>0 for v in (office_pid,editor_tid,child_hwnd)), 'Queue observer ownership is missing'
    identity=queue['observer']
    assert type(identity['stateVersion']) is int and identity['stateVersion']==2, 'Queue observer protocol differs'
    assert type(identity['stateBytes']) is int and identity['stateBytes']==ctypes.sizeof(DeliveryState)==262168, 'Queue observer state ABI differs'
    assert ctypes.sizeof(DeliveryMessage)==128 and DeliveryMessage.counter.offset==88 and DeliveryMessage.retrievalFlags.offset==120, 'Queue observer message ABI differs'
    assert identity['hook']=='WH_GETMESSAGE' and identity['scope']=='owned-editor-thread' and identity['compileBeforeTrials'] is True, 'Queue observer scope differs'
    assert all(isinstance(identity.get(k),str) and re.fullmatch('[a-f0-9]{64}',identity[k]) for k in ('sourceSha256','dllSha256')), 'Queue observer build hashes are missing'
    assert queue['sendInputCalls']==[], 'Physical input must not use the old pywinauto SendInput wrapper'
    rows=queue['messages']
    assert isinstance(rows,list) and type(queue['publishedMessageCount']) is int and 0<=queue['publishedMessageCount']==len(rows)<=2048, 'Published queue prefix count differs'
    assert type(queue['reservedMessageCount']) is int and len(rows)<=queue['reservedMessageCount']<=0x7fffffff, 'Reserved queue prefix count differs'
    assert type(queue['overflow']) is bool, 'Queue overflow fact is missing'
    fields={name:ctypes.sizeof(kind)*8 for name,kind in DeliveryMessage._fields_}
    for index,row in enumerate(rows,1):
        assert set(row)==set(fields), 'Raw protocol-2 message fields differ'
        assert type(row['remove']) is bool and row['remove'] is bool(row['retrievalFlags']&1), 'Raw queue removal flags differ'
        for name,bits in fields.items():
            if name=='remove':continue
            assert type(row[name]) is int and 0<=row[name]<(1<<bits), 'Raw queue integer differs: '+name
        assert row['sequence']==index, 'Published queue sequence differs'
        assert (row['pid'],row['tid'])==(office_pid,editor_tid), 'Queue message ownership differs'
        assert row['hwnd']>0 and 0<row['counter']<=end, 'Queue message clock or HWND differs'
        assert row['unicodeWindow'] in (0,1) and all(row[k]<=0xffff for k in ('shift','control','alt')), 'Raw queue state width differs'
    if previous_rows is not None: assert rows[:len(previous_rows)]==previous_rows, 'Published queue prefix changed between observations'
    return dict(complete=queue['overflow'] is False and len(rows)==queue['reservedMessageCount'],
                publishedMessageCount=len(rows),reservedMessageCount=queue['reservedMessageCount'],
                overflow=queue['overflow'],characters=[r['wparam'] for r in rows if r['remove'] is True and r['message']==0x102])


def analyze_observation(observation):
    """Conservative queue/model boundaries; no inference from post-read messages."""
    prefixes = observation['prefixes']
    assert [p['phase'] for p in prefixes] == list(PHASES), 'Queue prefix phases differ'
    frequency = prefixes[0]['qpcBegin']['frequency']
    previous = []
    complete = []
    chars = []
    last_clock = 0
    for prefix in prefixes:
        begin, end = (_clock(prefix[key], frequency) for key in ('qpcBegin', 'qpcEnd'))
        assert last_clock <= begin <= end, 'Native queue-prefix clock order differs'
        last_clock = end
        facts=require_queue_prefix(prefix,observation['officePid'],observation['editorTid'],observation['childHwnd'],frequency,previous)
        previous=prefix['queue']['messages']
        complete.append(facts['complete'])
        chars.append(facts['characters'])
    window = observation['liveReadWindow']
    read_begin, read_end = (_clock(window[key], frequency) for key in ('begin', 'end'))
    getter = observation['model']['getterClock']
    getter_begin, getter_end = (_clock(getter[key], frequency) for key in ('begin', 'end'))
    assert prefixes[1]['qpcEnd']['counter'] <= read_begin <= getter_begin <= getter_end <= read_end <= prefixes[2]['qpcBegin']['counter'], 'Live getter clock is outside its original read window'
    first, second = lifecycle.ASCII_EDITOR_MARKERS[CASE]
    exact_first = chars[0] == list(map(ord, first))
    exact_before = chars[1] == list(map(ord, first+second))
    exact_after = chars[2] == list(map(ord, first+second))
    model_exact = observation['model']['bodyText'].replace('\r\n','\n').replace('\r','\n') == observation['expectedBodyText']
    boundary = ('incomplete-prefix-observation-unresolved' if not all(complete) else
                'exact-model-observed' if model_exact and exact_before else
                'exact-model-observed-queue-order-unresolved' if model_exact else
                'removed-characters-exact-model-differs-order-unresolved' if exact_before else
                'character-queue-retrieval-or-earlier-unresolved')
    return dict(validationCompleted=True,firstMarkerCharactersExact=exact_first, beforeReadCharactersExact=exact_before,
                afterReadCharactersExact=exact_after, beforeReadPrefixComplete=complete[1],
                allPrefixesComplete=all(complete), modelExact=model_exact,
                beforeReadCodeUnits=chars[1], afterReadCodeUnits=chars[2], boundary=boundary,
                applicationConsumptionCertified=False,
                limitation='PM_REMOVE is queue retrieval, not completed VCL handling. After-read messages never establish pre-getter delivery; the hook/getter may affect scheduling.')


@contextmanager
def retained_generation(child, pid, expected_image, witness, *, expected_creation=None):
    """Retain the original handle while rechecking exact image/HWND generation."""
    original = EngineProcessWitness(pid)
    checked = after = None
    primary = None
    try:
        creation = original.creation_time if expected_creation is None else expected_creation
        assert original.creation_time == creation and not original.exited(0), 'Owned process generation changed before observation'
        api, checked = accessible._owned_process(child, pid, creation, expected_image)
        witness.update(officePid=pid, officeCreationTime=creation, childHwnd=child,
                       expectedImage=str(expected_image), retainedProcessHandle=bool(original.handle),
                       imageVerified=True, creationTimeVerified=True, hwndVerifiedBefore=True)
        yield original
    except BaseException as exc:
        primary = exc
        raise
    finally:
        secondary = None
        if checked is not None:
            try:
                assert not original.exited(0), 'Owned process generation exited during observation'
                _, after = accessible._owned_process(child, pid, original.creation_time, expected_image)
                assert api.user.IsWindow(child) and api.pid(child) == pid, 'Owned HWND generation changed during observation'
                witness.update(hwndVerifiedAfter=True, generationVerifiedAfter=True)
            except Exception as exc:
                witness['verificationAfterError'] = type(exc).__name__+': '+str(exc)
                secondary = exc
        for process in (after, checked, original):
            if process is None: continue
            try: process.close()
            except Exception as exc:
                witness.setdefault('cleanupErrors', []).append(type(exc).__name__+': '+str(exc))
                if secondary is None: secondary = exc
        if primary is None and secondary is not None: raise secondary


def require_model_witness(result, pid, child, creation, expected_image, pipe):
    assert (result.get('officePid'),result.get('childHwnd'),result.get('officeCreationTime')) == (pid,child,creation), 'Live model generation differs'
    assert Path(result.get('expectedImage','')).resolve() == expected_image.resolve(), 'Live model image differs'
    assert result.get('pipe') == pipe and result.get('privatePipeVerified') is True, 'Live model private pipe differs'
    assert result.get('readOnlyObservation') is True and result.get('liveGetterAttempts') == 1 and result.get('success') is True, 'One read-only live getter did not complete'
    witness = result.get('witness',{})
    assert (witness.get('officePid'),witness.get('childHwnd'),witness.get('officeCreationTime')) == (pid,child,creation), 'Live model witness generation differs'
    assert all(witness.get(k) is True for k in ('retainedProcessHandle','imageVerified','creationTimeVerified','hwndVerifiedBefore','hwndVerifiedAfter','generationVerifiedAfter')), 'Live model retained witness is incomplete'
    return result


def capture_command(command, folder, stem, *, cwd, timeout):
    write_json(folder/(stem+'-command.json'), command)
    try:
        result = subprocess.run(command, cwd=cwd, capture_output=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError) as exc:
        (folder/(stem+'-stdout.log')).write_bytes(getattr(exc,'stdout',None) or b'')
        (folder/(stem+'-stderr.log')).write_bytes(getattr(exc,'stderr',None) or b'')
        raise
    (folder/(stem+'-stdout.log')).write_bytes(result.stdout)
    (folder/(stem+'-stderr.log')).write_bytes(result.stderr)
    result.check_returncode()
    return result


def observe_live_model(suite, child, pid, folder, generation, pipe, source):
    target = folder/'model-before-close-save.json'
    expected_image = suite/'Office/program/soffice.bin'
    capture_command([str(suite/'Office/program/python.exe'),str(Path(__file__).resolve()),
        '--suite',str(suite),'--output',str(target),'--observe-model','--pipe',pipe,
        '--office-pid',str(pid),'--child-hwnd',str(child),'--creation-time',str(generation.creation_time),
        '--expected-image',str(expected_image),'--expected-file',str(source)],
        folder,'model-before-close-save',cwd=suite,timeout=25)
    result = json.loads(target.read_text(encoding='utf-8'))
    return require_model_witness(result,pid,child,generation.creation_time,expected_image,pipe)


def read_body_once(text,clock,result):
    assert result['liveGetterAttempts']==0, 'Live body getter must run exactly once'
    result['liveGetterAttempts']=1
    result['getterClock']={'scope':'packaged-python-getString-RPC','begin':clock.sample()}
    try:result['bodyText']=text.getString()
    finally:result['getterClock']['end']=clock.sample()


def read_existing_model(suite, pipe, pid, child, creation, expected_image, source, output):
    """Packaged Python: resolve once, then read ONE existing exact Writer body."""
    import uno
    from writer_style_smoke import observe_packaged_python, require_packaged_python
    result = dict(schemaVersion=1,kind='physical-ascii-live-model',success=False,
                  readOnlyObservation=True,liveGetterAttempts=0,officePid=pid,childHwnd=child,
                  officeCreationTime=creation,expectedImage=str(expected_image),pipe=pipe,witness={})
    try:
        result['pythonIdentity'] = require_packaged_python(suite,observe_packaged_python())
        clock = NativeClock()
        with retained_generation(child,pid,expected_image,result['witness'],expected_creation=creation) as generation:
            assert accessible.private_pipe(accessible._command_line(generation)) == pipe, 'UNO pipe differs from retained command line'
            result['privatePipeVerified'] = True
            local = uno.getComponentContext()
            resolver = local.ServiceManager.createInstanceWithContext('com.sun.star.bridge.UnoUrlResolver',local)
            context = resolver.resolve('uno:pipe,name='+pipe+';urp;StarOffice.ComponentContext')
            desktop = context.ServiceManager.createInstanceWithContext('com.sun.star.frame.Desktop',context)
            frames = desktop.getFrames()
            assert 0 < frames.getCount() <= 8, 'Owned engine frame count differs'
            matches = []
            for index in range(frames.getCount()):
                frame = frames.getByIndex(index)
                peer = frame.getContainerWindow()
                if peer is not None and int(peer.getWindowHandle((),1)) == child: matches.append(frame)
            assert len(matches) == 1, 'Live getter did not find one exact owned embedded frame'
            frame = matches[0]
            controller = frame.getController()
            assert controller is not None and controller.getFrame() == frame, 'Live controller belongs to another frame'
            model = controller.getModel()
            assert model.supportsService('com.sun.star.text.TextDocument'), 'Live model is not Writer'
            result['documentUrl'] = model.getURL()
            assert Path(uno.fileUrlToSystemPath(result['documentUrl'])).resolve() == source.resolve(), 'Live model file differs from exact case copy'
            text=model.getText()
            read_body_once(text,clock,result)
            result['modified'] = bool(model.isModified())
            assert controller.getFrame() == frame and int(frame.getContainerWindow().getWindowHandle((),1)) == child, 'Owned frame changed during live getter'
        result['success'] = True
    except Exception as exc:
        result.update(error=type(exc).__name__+': '+str(exc),traceback=traceback.format_exc())
    finally: write_json(output,result)
    # No dispatch, activate, cursor move, store, mutation, or document close.
    return 0 if result['success'] else 1


class ObservedCase(lifecycle.Case):
    def __init__(self,*args,plan,library,clock,expected_body='',**kwargs):
        self.plan,self.library,self.clock = plan,library,clock
        self._edits,self._observer,self._generation_context,self._generation = 0,None,None,None
        self._expected_body = expected_body
        super().__init__(*args,**kwargs)
        self.record['physicalObservation'] = dict(schemaVersion=1,instrumented=True,prefixes=[],
            liveGetterAttempts=0,expectedBodyText=expected_body+''.join(lifecycle.ASCII_EDITOR_MARKERS[CASE]))

    def _begin(self,hwnd,child):
        matches = [a for a in self.record['attachments'] if a['hwnd']==hwnd and a['child']==child]
        assert len(matches)==1 and matches[0]['officePid']==self.api.pid(child), 'Observed attachment identity differs'
        observation = self.record['physicalObservation']
        pid = matches[0]['officePid']
        observation.update(officePid=pid,childHwnd=child,processWitness={})
        self._generation_context = retained_generation(child,pid,self.suite/'Office/program/soffice.bin',observation['processWitness'])
        self._generation = self._generation_context.__enter__()
        observation['officeCreationTime'] = self._generation.creation_time
        observation['pipe'] = accessible.private_pipe(accessible._command_line(self._generation))
        observation['hookWindow']={'begin':self.clock.sample()}
        self._observer = DeliveryObserver(self.library,self.api,hwnd,child,pid)
        observation['hookWindow']['end']=self.clock.sample()
        observation['editorTid'] = self._observer.tid
        observation['hookInstalledBeforeFirstEdit'] = True

    def _prefix(self,phase):
        observation = self.record['physicalObservation']
        entry = dict(phase=phase,qpcBegin=self.clock.sample())
        observation['prefixes'].append(entry)  # Retain partial failures as well.
        try: entry['queue'] = self._observer.receipt()
        except Exception as exc:
            entry['error'] = type(exc).__name__+': '+str(exc)
            raise
        finally: entry['qpcEnd'] = self.clock.sample()

    def _close_observation(self,primary=None):
        observation = self.record['physicalObservation']
        secondary = None
        observer,self._observer = self._observer,None
        if observer is not None:
            try:
                observation['unhookWindow']={'begin':self.clock.sample()}
                observer.close()
                observation['unhookWindow']['end']=self.clock.sample()
                observation['hookUninstalledBeforeOriginalSave'] = True
            except Exception as exc:
                observation['observerCleanupError'] = type(exc).__name__+': '+str(exc)
                secondary = exc
        scope,self._generation_context = self._generation_context,None
        if scope is not None:
            try:
                assert accessible.private_pipe(accessible._command_line(self._generation))==observation['pipe'], 'Retained private pipe changed during observation'
                observation['privatePipeVerifiedAfter']=True
            except Exception as exc:
                observation['privatePipeAfterError']=type(exc).__name__+': '+str(exc)
                if secondary is None: secondary = exc
            try: scope.__exit__(type(primary) if primary else None,primary,primary.__traceback__ if primary else None)
            except Exception as exc:
                observation['generationCleanupError'] = type(exc).__name__+': '+str(exc)
                if secondary is None: secondary = exc
        if primary is None and secondary is not None: raise secondary

    def edit(self,hwnd,child,marker):
        self._edits += 1
        observation = self.record['physicalObservation']
        try:
            if self._edits == 1: self._begin(hwnd,child)
            assert self._edits <= 2 and marker == lifecycle.ASCII_EDITOR_MARKERS[CASE][self._edits-1], 'Original physical marker order differs'
            edit=dict(marker=marker,ordinal=self._edits,begin=self.clock.sample())
            observation.setdefault('originalEditWindows',[]).append(edit)
            try: super().edit(hwnd,child,marker)  # Exact original method, buffers and pause.
            finally: edit['end']=self.clock.sample()
            if self._edits == 1:
                self._prefix(PHASES[0])
                return
            self._prefix(PHASES[1])
            observation['liveGetterAttempts'] += 1
            observation['liveReadWindow'] = {'begin':self.clock.sample()}
            try:
                observation['model'] = observe_live_model(self.suite,child,observation['officePid'],self.folder,
                    self._generation,observation['pipe'],self.source)
            finally:
                primary = sys.exc_info()[1]
                observation['liveReadWindow']['end'] = self.clock.sample()
                try: self._prefix(PHASES[2])
                except Exception as exc:
                    observation['afterReadPrefixError'] = type(exc).__name__+': '+str(exc)
                    if primary is None: raise
            self._close_observation()
            # Wrong text remains an observation. Do not stop or repair the
            # original Save/assert path; that original result remains decisive.
        except BaseException as exc:
            observation['error'] = type(exc).__name__+': '+str(exc)
            self._close_observation(exc)
            raise

    def run(self,action):
        def observed_action(case):
            try: return action(case)
            finally: self._close_observation(sys.exc_info()[1])
        return super().run(observed_action)

    def close_choice(self,hwnd,choice):
        observation=self.record['physicalObservation']
        if choice=='저장':
            assert self._observer is None and self._generation_context is None and self._edits==2, 'Original Save reached before observation was closed'
        window=dict(choice=choice,begin=self.clock.sample())
        observation.setdefault('originalCloseChoiceWindows',[]).append(window)
        try:return super().close_choice(hwnd,choice)
        finally:window['end']=self.clock.sample()


def owned_source(trial_root):
    path = trial_root/'fixtures'/CASE/('원본 문서 & '+CASE+'.docx')
    for part in (trial_root,path.parent.parent,path.parent,path): lifecycle.unlinked(part)
    assert path.resolve().parent == (trial_root/'fixtures'/CASE).resolve(), 'Post-action source escaped owned trial'
    return path.resolve()


def verify_saved_readonly(suite,trial_root):
    """Observe failed trials too; never replace the original action's result."""
    from engine_smoke import Engine
    from writer_style_smoke import observe_packaged_python, require_packaged_python
    result = dict(schemaVersion=1,kind='physical-ascii-saved-observation',observationComplete=False,
                  candidateFileRole='Owned case file after the original action; existence alone does not prove Save.')
    engine,document = Engine(suite),None
    source = owned_source(trial_root)
    try:
        metadata = json.loads((trial_root/'preregistered-trial.json').read_text(encoding='utf-8'))
        assert metadata['case']==CASE and metadata in trial_plan_with_body(metadata['baselineBodyText'])
        assert source.is_file(), 'Original trial did not leave an owned DOCX file'
        result['expectedBodyText'] = metadata['expectedBodyText']
        before = lifecycle.digest(source)
        result['beforeSha256'] = before
        try:result['xml'] = lifecycle.writer_evidence(source)
        except Exception as exc:
            result['xmlError']=type(exc).__name__+': '+str(exc)
            result['xmlTraceback']=traceback.format_exc()
        # A direct XML failure must not suppress the independent read-only
        # attempt. Both original observations are retained, even for failures.
        result['pythonIdentity'] = require_packaged_python(suite,observe_packaged_python())
        engine.start()
        from dispatch import make_interaction_handler
        props = tuple(engine.prop(name,value) for name,value in (
            ('Hidden',True),('ReadOnly',True),('MacroExecutionMode',0),('UpdateDocMode',0),
            ('PickListEntry',False),('AsTemplate',False),('InteractionHandler',make_interaction_handler())))
        document = engine.desktop.loadComponentFromURL(source.as_uri(),'_blank',0,props)
        assert document is not None and document.supportsService('com.sun.star.text.TextDocument'), 'Independent reopen is not Writer'
        result['readOnlyModel'] = bool(document.isReadonly())
        result['modifiedBefore'] = bool(document.isModified())
        assert result['readOnlyModel'] is True and result['modifiedBefore'] is False, 'Independent Writer is not read-only and unchanged'
        result['observedBodyText'] = document.getText().getString()
        result['modifiedAfter'] = bool(document.isModified())
        assert result['modifiedAfter'] is False, 'Independent read modified Writer'
        document.close(False)
        document = None
        result['afterCloseSha256'] = lifecycle.digest(source)
        assert 'xml' in result, 'Direct OOXML observation is unavailable; independent UNO observation retained'
        lifecycle.require_uno_observation(result['xml'],result['observedBodyText'],before,result['afterCloseSha256'])
        result['expectedBodyMatches'] = result['xml']['bodyText'] == result['expectedBodyText']
        result['observationComplete'] = True
    except Exception as exc:
        result.update(error=type(exc).__name__+': '+str(exc),traceback=traceback.format_exc())
    finally:
        if document is not None:
            try: document.close(False)
            except Exception as exc: result.update(observationComplete=False,closeError=type(exc).__name__+': '+str(exc))
        engine.cleanup()
        if engine.cleanup_errors: result.update(observationComplete=False,cleanupErrors=engine.cleanup_errors)
        if source.is_file():
            result['afterCleanupSha256'] = lifecycle.digest(source)
            if 'beforeSha256' in result and result['afterCleanupSha256'] != result['beforeSha256']:
                result.update(observationComplete=False,hashChangedDuringRead=True)
        write_json(trial_root/'saved-readonly-uno.json',result)
    return 0 if result['observationComplete'] else 1


def trial_plan_with_body(body):
    return [dict(p,baselineBodyText=body,expectedBodyText=body+''.join(lifecycle.ASCII_EDITOR_MARKERS[CASE])) for p in trial_plan()]


def experiment_report(records):
    plan = trial_plan()
    expected = [(p['trial'],p['trialId'],p['case'],p['instrumented']) for p in plan]
    actual = [(r.get('trial'),r.get('trialId'),r.get('case'),r.get('instrumented')) for r in records]
    complete = actual == expected and all(type(r.get('instrumented')) is bool for r in records)
    original_passed = sum(r.get('originalActionSuccess') is True for r in records)
    observed = sum(r.get('postSave',{}).get('observationComplete') is True for r in records)
    exact = sum(r.get('postSave',{}).get('expectedBodyMatches') is True for r in records)
    analyzed=sum(r.get('instrumented') is True and r.get('boundaryAnalysis',{}).get('validationCompleted') is True for r in records)
    return dict(schemaVersion=1,kind='physical-ascii-queue-model-experiment',diagnosticOnly=True,
        deliverable=False,acceptanceGateReplaced=False,expectedTrialCount=20,completedTrialCount=len(records),
        experimentCompleted=complete,observedTrialCount=sum(r.get('instrumented') is True for r in records),
        controlTrialCount=sum(r.get('instrumented') is False for r in records),
        originalActionPassedTrialCount=original_passed,postSaveObservedTrialCount=observed,
        postSaveExactBodyTrialCount=exact,tests=records,
        observedBoundaryAnalyzedTrialCount=analyzed,
        completeObservedPrefixTrialCount=sum(r.get('instrumented') is True and r.get('boundaryAnalysis',{}).get('allPrefixesComplete') is True for r in records),
        success=complete and original_passed==observed==exact==20 and analyzed==10)


def require_experiment_coverage(report):
    recomputed = experiment_report(report['tests'])
    for key,value in recomputed.items():
        if key!='tests': assert report[key]==value, 'Experiment aggregate differs: '+key
    assert recomputed['experimentCompleted'], 'Fixed twenty-trial coverage is incomplete'
    assert recomputed['observedTrialCount']==recomputed['controlTrialCount']==10, 'Alternating groups differ'
    return recomputed


def run_trial(suite,fixtures,trial_root,plan,library,clock):
    trial_root.mkdir()
    (trial_root/'fixtures').mkdir()
    write_json(trial_root/'preregistered-trial.json',plan)
    row = dict(plan,originalActionSuccess=False)
    case = None
    try:
        if plan['instrumented']:
            case = ObservedCase(suite,fixtures,trial_root,CASE,plan=plan,library=library,clock=clock,
                                expected_body=plan['baselineBodyText'])
        else:
            case = lifecycle.Case(suite,fixtures,trial_root,CASE)  # Pristine original control.
        case.run(lifecycle.dirty_cancel_save)
        row['originalActionSuccess'] = case.record['success'] is True
    except Exception as exc:
        row.update(originalError=type(exc).__name__+': '+str(exc),originalTraceback=traceback.format_exc())
    finally:
        if case is not None:
            row['originalRecord'] = case.record
            row['originalResult'] = CASE+'-result.json'
            row['originalSaveAssertionPassed']=case.record.get('closeSavePersisted') is True
        source = owned_source(trial_root)
        if source.is_file():
            try:
                capture_command([str(suite/'Office/program/python.exe'),str(Path(__file__).resolve()),
                    '--suite',str(suite),'--output',str(trial_root),'--verify-saved'],
                    trial_root,'saved-readonly-uno',cwd=suite,timeout=30)
            except Exception as exc: row['postSaveProcessError'] = type(exc).__name__+': '+str(exc)
            result = trial_root/'saved-readonly-uno.json'
            row['postSave']=dict(observationComplete=False,sourceExists=True,resultFilePresent=result.is_file())
            if result.is_file():
                try:
                    observed=json.loads(result.read_text(encoding='utf-8'))
                    assert isinstance(observed,dict), 'Post-action observation must be a JSON object'
                    row['postSave']=observed
                except Exception as exc:
                    # A killed reader can leave a truncated original file.
                    # Preserve it and the original action failure, then execute
                    # the remaining preregistered trials without any retry.
                    row.update(postSaveReadError=type(exc).__name__+': '+str(exc),
                               postSaveReadTraceback=traceback.format_exc())
        else: row['postSave'] = dict(observationComplete=False,sourceExists=False)
        if case is not None and plan['instrumented']:
            observation = case.record.get('physicalObservation',{})
            try: row['boundaryAnalysis'] = analyze_observation(observation)
            except Exception as exc: row['boundaryAnalysis'] = dict(complete=False,error=type(exc).__name__+': '+str(exc))
        write_json(trial_root/'trial-result.json',row)
    return row


def main(argv=None):
    if not __debug__: raise RuntimeError('Assertion-enabled execution is required; optimized Python is forbidden')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite',required=True,type=Path)
    parser.add_argument('--fixtures',type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--trials',type=int,choices=(20,),default=20)
    parser.add_argument('--observe-model',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--verify-saved',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--pipe',help=argparse.SUPPRESS)
    parser.add_argument('--office-pid',type=int,help=argparse.SUPPRESS)
    parser.add_argument('--child-hwnd',type=int,help=argparse.SUPPRESS)
    parser.add_argument('--creation-time',type=int,help=argparse.SUPPRESS)
    parser.add_argument('--expected-image',type=Path,help=argparse.SUPPRESS)
    parser.add_argument('--expected-file',type=Path,help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if os.name!='nt': raise RuntimeError('Actual Windows execution is required')
    suite = args.suite.resolve()
    if args.observe_model:
        assert args.expected_image.resolve()==(suite/'Office/program/soffice.bin').resolve(), 'Live model expected image differs'
        return read_existing_model(suite,args.pipe,args.office_pid,args.child_hwnd,args.creation_time,
                                   args.expected_image,args.expected_file,args.output)
    if args.verify_saved: return verify_saved_readonly(suite,args.output.resolve())
    assert args.fixtures is not None, 'Fresh generated engine fixtures are required'
    for path in (args.suite,args.fixtures,args.output): lifecycle.unlinked(path)
    fixtures,output = args.fixtures.resolve(),args.output.resolve()
    assert suite.is_dir() and fixtures.is_dir() and suite not in output.parents and fixtures not in output.parents and suite!=output and fixtures!=output, 'Diagnostic output must be outside payload and fixtures'
    original = lifecycle.native.require_engine_fixture(fixtures,'writer','docx')
    baseline = lifecycle.writer_evidence(original)
    output.mkdir(parents=True,exist_ok=False)
    (output/'trials').mkdir()
    (output/'observer').mkdir()
    assert hashlib.sha256(Path(__file__).with_name('keyboard_delivery.py').read_bytes()).hexdigest()==DELIVERY_SHA256, 'Protocol-2 observer source differs'
    provenance = dict(schemaVersion=1,diagnosticOnly=True,deliverable=False,acceptanceGateReplaced=False,
        sourceCommit=os.environ.get('GITHUB_SHA'),expectedTrials=20,plan=trial_plan_with_body(baseline['bodyText']),
        baseline=baseline,inputPath='unchanged Case.edit + SendInput-scancode; original .025s character pause',
        observerEffect='Observed hook and one read-only UNO getter can affect scheduling. Controls have neither during the original action. Passing observations do not establish a previous cause or fix.',
        originalActionSha256=hashlib.sha256(inspect.getsource(lifecycle.dirty_cancel_save).encode()).hexdigest(),
        originalEditSha256=hashlib.sha256(inspect.getsource(lifecycle.Case.edit).encode()).hexdigest(),
        sources={name:hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in SOURCE_FILES},
        workers={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((suite/'worker').glob('*.py'))})
    write_json(output/'preregistration.json',provenance)  # Before compilation or any trial launch.
    records=[]
    result=experiment_report(records)
    try:
        library,clock = ObserverLibrary(output/'observer'),NativeClock()
        for plan in provenance['plan']:
            records.append(run_trial(suite,fixtures,output/'trials'/plan['trialId'],plan,library,clock))
            result=experiment_report(records)
            write_json(output/'results.json',result)
        result['originalFixtureUnchanged'] = lifecycle.digest(original)==baseline['sha256']
        if not result['originalFixtureUnchanged']: result['success']=False
    except Exception as exc:
        result.update(success=False,error=type(exc).__name__+': '+str(exc),traceback=traceback.format_exc())
    finally: write_json(output/'results.json',result)
    return 0 if result['success'] else 1


if __name__=='__main__': raise SystemExit(main())
