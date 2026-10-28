"""One fixed native-symbol qualification or first failed owned-capture selection."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'e2e'))
from editor_capture_diagnostic import cohort_cleanup_confirmed


def select(report):
    assert report.get('kind')=='native-focus-diagnostic' and report.get('architecture')=='arm64' and report.get('acceptanceEligible') is False
    assert report.get('pluginFileOrigin',{}).get('verified') is True and report['pluginFileOrigin'].get('released') is True
    assert not report.get('pluginFileOriginCleanupErrorType')
    cases=report.get('tests');assert type(cases) is list and 1<=len(cases)<=3
    result=dict(status='not-reproduced',rvas=[],runtimeCallerProved=False,acceptanceEligible=False)
    for index,case in enumerate(cases,1):
        assert case.get('case')==f'ime-calc-focus-{index:02d}'
        assert cohort_cleanup_confirmed(case),'Original cohort cleanup incomplete'
        error=case.get('error')
        if case.get('success') is not False or type(error) is not str or not error.startswith('AssertionError: Owned capture readiness deadline expired'):continue
        # Once selected, any incomplete evidence is fatal; never select a later case.
        assert case.get('stage')=='focus-editor' and case.get('kind')=='native-focus-diagnostic'
        focus=case['editorFocusReadiness'];session=case['imeKeyboardSession'];ledger=session['captureReadiness'];trace=case['focusCaptureDiagnostic']
        assert focus['ready'] is False and focus['deadline']==ledger['deadline']==trace['deadline'] and ledger['settledAt'] is None and ledger['pollCount']>0
        assert not trace['cleanupErrors'] and not trace.get('snapshotError')
        snapshot=trace['snapshot'];events=snapshot['events'];retrieval=snapshot['retrieval']
        assert snapshot['status']=='complete' and not snapshot['overflow'] and not snapshot['rejected'] and len(events)==snapshot['reservedCount']
        assert retrieval['moduleMapVersion']==2 and retrieval['status']=='complete' and not retrieval['rejected'] and not retrieval['expired'] and not retrieval['pendingBuckets']
        expected=session['expectedNative'];rows=[];unknown=0;capped=False
        assert trace['expectedNative']==expected
        for engine in (session['originalEngine'],trace['originalEngine']):
            assert engine['pid']==expected['officePid'] and engine['creationTime']==expected['officeCreationTime']
        origin_proof=report['pluginFileOrigin']
        result['pluginIdentity']=dict(dllSha256=origin_proof['dllSha256'],identity=origin_proof['matchedIdentity'])
        for guard in (ledger['first'],ledger['last']):
            capture=guard['scope']['capture']
            assert capture['hwnd']==expected['childHwnd'] and capture['pid']==expected['officePid'] and capture['rootHwnd']==expected['suiteHwnd'] and capture['isWindow'] is True
        deadline=snapshot['deadlineCounter'];frequency=snapshot['counterFrequency']
        for row in retrieval['records']:
            if row['bucket']==0:continue
            bucket=row['bucket'];assert bucket in (1,2) and all(previous['bucket']!=bucket for previous in rows)
            sequence=row['captureSequence'];assert type(sequence) is int and 1<=sequence<=len(events)
            capture=events[sequence-1];origin=row['pluginOrigin']
            assert row['sequence']==origin['sequence']==bucket+1 and origin['captureSequence']==sequence and origin['bucket']==bucket and origin['status']==1
            assert capture['sequence']==sequence and capture['origin']==1 and row['message']==0x202 and row['removeFlags']==(1 if bucket==1 else 3)
            assert all(capture[k]==row[k] for k in ('pid','tid','hwnd','engineCreationTime','message','removeFlags','lParam','frequency'))
            assert row['engineCreationTime']==expected['officeCreationTime']
            assert row['pid']==expected['officePid'] and row['hwnd']==expected['childHwnd'] and row['tid']==ledger['last']['scope']['capture']['threadId']
            assert row['frequency']==frequency and 0<capture['counter']<=capture['finishedCounter']<=row['counter']<=origin['counter']<=origin['finishedCounter']<=row['finishedCounter']<deadline
            assert row['flags']==0 and 0<len(row['frames'])==row['frameCount']<=16
            assert row['unknownFrames']==sum(f['moduleId']==0 for f in row['frames']) and row['frameCapReached']==int(row['frameCount']==16)
            unknown+=row['unknownFrames'];capped=capped or bool(row['frameCapReached'])
            for frame in row['frames']:
                assert type(frame['moduleId']) is int and 0<=frame['moduleId']<=14 and type(frame['rva']) is int
                if frame['moduleId']==0:assert frame['rva']==0
                if frame['moduleId']==14:
                    assert 4<=frame['rva']<2**32 and frame['rva']%4==0
                    result['rvas'].append(frame['rva'])
            rows.append(dict(bucket=bucket,captureSequence=sequence,frameCount=row['frameCount']))
        assert 0<len(rows)<=2 and 0<len(result['rvas'])<=32,'No bound plugin frame in original failure'
        coverage=trace.get('terminalCopyCoverage',{});clock_coverage='unknown'
        if not coverage.get('errors') and coverage.get('before') and coverage.get('after'):
            before,after=coverage['before'],coverage['after']
            assert before['counterFrequency']==after['counterFrequency']==frequency
            assert before['nativeDeadlineCounter']==after['nativeDeadlineCounter']==deadline
            assert 0<before['counter']<=after['counter']
            clock_coverage=('covered' if before['counter']>=deadline else 'truncated' if after['counter']<deadline else 'unknown')
            assert coverage.get('clockCoverage')==clock_coverage
        result.update(status='selected',caseIndex=index,stacks=rows,unknownFrames=unknown,
            frameCapReached=capped,terminalClockCoverage=clock_coverage,
            terminalClockTruncated=(clock_coverage=='truncated' if clock_coverage!='unknown' else None),
            producerExpired=bool(snapshot['expired']))
        return result
    if len(cases)!=3 or not all(case.get('success') is True for case in cases):result['status']='inconclusive-cohort'
    return result


def require_failed_engine_retirement(report,case):
    session=case['imeKeyboardSession'];admission=case['imeEngineRetirement']['admission'];native=session['expectedNative']
    assert session.get('engineHandleReleased') is True and admission['native']==native
    binding=report['runBinding'];source=admission['runBinding']
    assert source['sourceRun']==binding['runId']
    assert all(source[k]==binding[k] for k in ('sourceCommit','runAttempt','architecture','repository','job'))
    cleanup=case['imeFailureCleanup']
    assert cleanup['engineExitConfirmed'] is True and cleanup['handleReleased'] is True and cleanup['gracefulShutdownVerified'] is False
    assert case['imeEngineRetirement']['success'] is False
    for key,original in (('shellIdentity','originalShell'),('engineIdentity','extraEngine')):
        assert all(cleanup[key][k]==admission[original][k] for k in ('pid','handleValue','creationTime','image'))
    engine=cleanup['engineIdentity']
    assert (engine['pid'],engine['creationTime'],engine['image'])==(native['officePid'],native['officeCreationTime'],native['expectedImage'])
    assert cleanup['targets']==[cleanup[k]['pid'] for k in ('shellIdentity','engineIdentity') if cleanup[k]['waitResult']==258]
    assert cleanup['commandExitCode']==0 and type(cleanup['shellExitCode']) is int
    start=cleanup['commandBudgetStartedAt'];deadline=cleanup['commandBudgetDeadline']
    assert 0<start<=cleanup['commandReturnedAt']<deadline==start+15
    assert cleanup['commandReturnedAt']<=cleanup['exitWaitStartedAt']<=cleanup['engineWaitReturnedAt']<=cleanup['exitWaitDeadline']==cleanup['exitWaitStartedAt']+5
    wait=cleanup['engineWait'];assert wait['api']=='WaitForSingleObject' and wait['handleValue']==engine['handleValue'] and wait['result']==0 and 0<=wait['timeoutMilliseconds']<=5000
    return native,admission


def select_notification(report):
    from ime_notification_caller import clean,closed
    assert report.get('kind')=='native-ime-mode-diagnostic' and report.get('architecture')=='arm64'
    assert report.get('acceptanceEligible') is False and report.get('notificationCallerEnabled') is True
    assert report.get('expectedCaseCount')==1 and len(report['tests'])==1
    proof=report['pluginFileOrigin']
    assert proof.get('verified') is True and proof.get('released') is True and not report.get('pluginFileOriginCleanupErrorType')
    case=report['tests'][0];assert case.get('case')=='ime-calc' and case.get('kind')=='native-ime-mode-diagnostic'
    result=dict(status='inconclusive-case',evidenceKind='ime-notification-delivery',rvas=[],runtimeCallerProved=False,acceptanceEligible=False)
    if case.get('success') is True:
        result['status']='not-reproduced';return result
    if case.get('stage')!='physical-dubeolsik-composition':return result
    native,admission=require_failed_engine_retirement(report,case)
    mode=case['imeModeDiagnostics'];messages=case['imeMessageDiagnostics'];caller=mode['notificationCaller']
    if caller['status']!='complete':
        result['status']='inconclusive-notification';return result
    assert mode['status']==messages['status']=='complete' and caller['callerAttributionProved'] is False and caller['acceptanceEligible'] is False
    assert not caller['expired'] and not caller['rejected'] and caller['armed'] is True and caller['claimed'] is True
    assert caller['moduleMapVersion']==2 and caller['pluginStatus']==1
    seq=caller['messageSequence'];assert type(seq) is int and 1<=seq<=len(mode['events']) and seq<=len(messages['events'])
    event=mode['events'][seq-1];message=messages['events'][seq-1]
    assert event['messageSequence']==message['sequence']==seq and closed(event)
    assert next(e['messageSequence'] for e in mode['events'] if closed(e))==seq
    assert (caller['pid'],caller['engineCreationTime'])==(native['officePid'],native['officeCreationTime'])
    assert caller['tid']==case['editorTid']==admission['editorTid'] and caller['hwnd']==case['keyboardFocusHwnd']==admission['focusHwnd']
    assert (message['pid'],message['tid'],message['hwnd'])==(caller['pid'],caller['tid'],caller['hwnd'])
    assert message['message']==event['message']==0x282 and message['origin']==event['origin']==1 and message['commandAck']==event['commandAck']==3
    command=next(r for r in case['imeCommands'] if r['command']==3);baseline=command['threadMode']
    assert command['success'] is True and command['nativeAck']==3 and command['status']==0 and clean(baseline)
    assert baseline['afterOpenHr']==baseline['afterConversionHr']==0 and baseline['afterOpenType']==baseline['afterConversionType']==3
    assert baseline['afterOpen']==baseline['afterConversion']==1
    assert caller['counterFrequency']==mode['counterFrequency']>0 and caller['deadlineCounter']==mode['deadlineCounter']
    assert 0<caller['baselineCounter']<=message['counter']==event['messageCounter']<=event['startedCounter']<=event['finishedCounter']<=caller['counter']<=caller['pluginStarted']<=caller['pluginFinished']<=caller['finishedCounter']<caller['deadlineCounter']
    frames=caller['frames'];assert caller['flags']==0 and 0<len(frames)==caller['frameCount']<=16
    assert caller['unknownFrames']==sum(f['moduleId']==0 for f in frames) and caller['frameCapReached']==(len(frames)==16)
    for frame in frames:
        assert type(frame['moduleId']) is int and 0<=frame['moduleId']<=14 and type(frame['rva']) is int and 0<=frame['rva']<2**32
        if frame['moduleId']==0:assert frame['rva']==0
        if frame['moduleId']==14:assert frame['rva']>=4 and frame['rva']%4==0
    assert type(caller['hookSentByCurrentThread']) is bool
    result.update(messageSequence=seq,hookSentByCurrentThread=caller['hookSentByCurrentThread'],unknownFrames=caller['unknownFrames'],frameCapReached=caller['frameCapReached'])
    if not caller['hookSentByCurrentThread']:
        result['status']='inconclusive-other-thread-delivery';return result
    rvas=[f['rva'] for f in frames if f['moduleId']==14]
    if not rvas:
        result['status']='inconclusive-no-product-frame';return result
    result.update(status='selected',rvas=rvas,pluginIdentity=dict(dllSha256=proof['dllSha256'],identity=proof['matchedIdentity']))
    return result


def select_compartment(report):
    from ime_notification_caller import clean
    assert report.get('kind')=='native-ime-mode-diagnostic' and report.get('architecture')=='arm64'
    assert report.get('acceptanceEligible') is False and report.get('compartmentCallbackEnabled') is True
    assert report.get('notificationCallerEnabled') is False and report.get('expectedCaseCount')==1 and len(report['tests'])==1
    proof=report['pluginFileOrigin']
    assert proof.get('verified') is True and proof.get('released') is True and not report.get('pluginFileOriginCleanupErrorType')
    case=report['tests'][0]
    assert case.get('case')=='ime-writer' and case.get('kind')=='native-ime-mode-diagnostic'
    result=dict(status='inconclusive-case',evidenceKind='ime-compartment-callback',rvas=[],runtimeCallerProved=False,acceptanceEligible=False)
    if case.get('success') is True:
        result['status']='not-reproduced';return result
    if case.get('stage')!='physical-dubeolsik-composition':return result
    if (case.get('keyTokens')!=['g'] or case.get('scanCodeInputs')!=[
            {'vk':0,'scan':34,'flags':8},{'vk':0,'scan':34,'flags':10}]
            or case.get('inputMethod')!='SendInput-scancode' or case.get('unicodeInputUsed') is not False
            or case.get('error')!='AssertionError: Native UI condition did not become true: False'):
        return result
    messages=case['imeMessageDiagnostics']
    if messages.get('status')!='complete':
        result['status']='inconclusive-messages';return result
    native,admission=require_failed_engine_retirement(report,case)
    assert case['activeProfile']['tsfOrigin']=='empty'
    caller=case['imeCompartmentDiagnostics']
    if caller['status']!='complete' or caller['cleanupStatus']!='unsubscribed':
        result['status']='inconclusive-callback';return result
    assert caller['callerAttributionProved'] is False and caller['acceptanceEligible'] is False and caller['processRetirementVerified'] is False
    assert not caller['expired'] and not caller['rejected'] and not caller['foreignRejected'] and caller['claimed'] is True
    assert caller['moduleMapVersion']==2 and caller['pluginStatus']==1
    assert (caller['pid'],caller['engineCreationTime'])==(native['officePid'],native['officeCreationTime'])
    assert caller['tid']==case['editorTid']==admission['editorTid'] and caller['hwnd']==case['keyboardFocusHwnd']==admission['focusHwnd']
    command=next(r for r in case['imeCommands'] if r['command']==3);baseline=command['threadMode']
    assert command['success'] is True and command['nativeAck']==3 and command['status']==0 and clean(baseline)
    from korean_ime_smoke import require_mode_context
    assert require_mode_context(command)[2:]==(native['officePid'],caller['tid'],caller['hwnd'],native['suiteHwnd'])
    assert command['requestedBudget']=={'counter':command['modeDeadlineCounter'],'frequency':command['modeCounterFrequency']}
    assert command['modeCounterFrequency']==caller['counterFrequency']
    assert caller['baselineCounter']<command['modeDeadlineCounter']<=caller['deadlineCounter']
    events=messages['events']
    assert messages['capacity']==128 and 0<len(events)==messages['observedCount']<=128
    for index,event in enumerate(events,1):
        assert event['sequence']==index and (event['pid'],event['tid'],event['hwnd'])==(caller['pid'],caller['tid'],caller['hwnd'])
    keys=[event for event in events if event['message']==0x100 and event['origin']==2 and event['commandAck']==3]
    assert len(keys)==1
    key=keys[0]
    assert key['wparam']==71 and (key['lparam']>>16)&0xff==34 and key['focusHwnd']==caller['hwnd']
    assert key['immContextPresent']==key['immConversionSucceeded']==key['immOpen']==1 and key['immConversion']&1
    assert caller['baselineCounter']<=key['counter']<=caller['counter']
    assert baseline['afterOpenHr']==baseline['afterConversionHr']==0 and baseline['afterOpenType']==baseline['afterConversionType']==3
    assert baseline['afterOpen']==baseline['afterConversion']==1
    assert caller['counterFrequency']>0
    assert 0<caller['baselineCounter']<=caller['counter']<=caller['pluginStarted']<=caller['pluginFinished']<=caller['finishedCounter']<caller['deadlineCounter']
    frames=caller['frames'];assert 0<len(frames)==caller['frameCount']<16 and caller['frameCapReached'] is False
    assert caller['unknownFrames']==sum(f['moduleId']==0 for f in frames)
    for frame in frames:
        assert type(frame['moduleId']) is int and 0<=frame['moduleId']<=14 and type(frame['rva']) is int and 0<=frame['rva']<2**32
        if frame['moduleId']==0:assert frame['rva']==0
        if frame['moduleId']==14:assert frame['rva']>=4 and frame['rva']%4==0
    rvas=[f['rva'] for f in frames if f['moduleId']==14]
    if not rvas:
        result['status']='inconclusive-no-product-frame';return result
    result.update(status='selected',rvas=rvas,pluginIdentity=dict(dllSha256=proof['dllSha256'],identity=proof['matchedIdentity']))
    return result


def join_resolution(selection,worker):
    assert worker.get('success') is True
    resolved=worker['resolution'];identity=selection['pluginIdentity']
    assert resolved['dllSha256']==identity['dllSha256'] and resolved['identity']==identity['identity'],'Resolved pair differs from held plugin'
    frames=resolved['frames'];assert len(frames)==len(selection['rvas'])
    assert [f['returnRva'] for f in frames]==selection['rvas']
    tags=('mutex-acquire','mutex-release','mutex-acquire-with-wait','unresolved')
    if selection.get('evidenceKind') in ('ime-notification-delivery','ime-compartment-callback'):
        tags+=('frame-input-context','frame-input-context-dispatch','frame-window-procedure','frame-key-handler')
    assert all(f['tag'] in tags for f in frames)
    return all(f['tag']!='unresolved' for f in frames)


def resolve_compartment_in_memory(report,pair,context,*,worker_run=None):
    """Keep the original selector and file-only worker without a raw trace file."""
    assert type(context) is dict and report['runBinding']==context, 'Trace belongs to another run'
    selection=select_compartment(report)
    if selection['status']!='selected':return selection,None
    if worker_run is None:
        spec=importlib.util.spec_from_file_location('compartment_symbol_worker',Path(__file__).with_name('plugin_symbol_worker.py'))
        worker=importlib.util.module_from_spec(spec);spec.loader.exec_module(worker)
        worker_run=worker.run
    resolution=worker_run(pair,mode='resolve',rvas=selection['rvas'])
    assert join_resolution(selection,resolution), 'Original compartment symbols remain inconclusive'
    return selection,resolution


def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('--mode',choices=('qualify','resolve'),required=True)
    parser.add_argument('--pair',type=Path,required=True);inputs=parser.add_mutually_exclusive_group()
    inputs.add_argument('--focus',type=Path);inputs.add_argument('--notification',type=Path);inputs.add_argument('--compartment',type=Path);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv)
    assert os.name=='nt' and __debug__,'Native Windows with assertions required'
    spec=importlib.util.spec_from_file_location('matched_ci_admission',Path(__file__).resolve().parents[2]/'e2e/native31_suite_prepare.py')
    admission=importlib.util.module_from_spec(spec);spec.loader.exec_module(admission)
    binding=admission.validate_context(os.environ,admission.read_event(),'arm64',os.name)
    import plugin_symbol_worker as worker
    report=dict(schemaVersion=1,kind='matched-plugin-diagnostic',mode=args.mode,acceptanceEligible=False,runtimeCallerProved=False,runBinding=binding,success=False)
    try:
        rvas=None
        if args.mode=='resolve':
            input_path=args.compartment or args.notification or args.focus
            assert input_path is not None
            # Local generated report only, with finite retained size.
            path=worker.shared._absolute(input_path.absolute())
            with path.open('rb') as stream:raw=stream.read(16*1024*1024+1)
            assert len(raw)<=16*1024*1024
            focus=json.loads(raw);assert focus['runBinding']==binding,'Trace belongs to another run'
            report['selection']=(select_compartment(focus) if args.compartment else select_notification(focus) if args.notification else select(focus))
            if report['selection']['status']!='selected':return 2
            rvas=report['selection']['rvas']
        if args.mode=='qualify':assert args.focus is None and args.notification is None and args.compartment is None
        report['worker']=worker.run(args.pair,mode=args.mode,rvas=rvas)
        if args.mode=='resolve' and not join_resolution(report['selection'],report['worker']):
            report['classification']='inconclusive-symbols';return 2
        report['success']=True
        return 0
    except BaseException as exc:
        report['errorType']=type(exc).__name__
        if hasattr(exc,'symbolWorkerReceipt'):report['worker']=exc.symbolWorkerReceipt
        return 1
    finally:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        with args.output.open('x',encoding='utf-8') as stream:json.dump(report,stream,indent=2,allow_nan=False)

if __name__=='__main__':raise SystemExit(main())
