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


def join_resolution(selection,worker):
    assert worker.get('success') is True
    resolved=worker['resolution'];identity=selection['pluginIdentity']
    assert resolved['dllSha256']==identity['dllSha256'] and resolved['identity']==identity['identity'],'Resolved pair differs from held plugin'
    frames=resolved['frames'];assert len(frames)==len(selection['rvas'])
    assert [f['returnRva'] for f in frames]==selection['rvas']
    assert all(f['tag'] in ('mutex-acquire','mutex-release','mutex-acquire-with-wait','unresolved') for f in frames)
    return all(f['tag']!='unresolved' for f in frames)


def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('--mode',choices=('qualify','resolve'),required=True)
    parser.add_argument('--pair',type=Path,required=True);parser.add_argument('--focus',type=Path);parser.add_argument('--output',type=Path,required=True)
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
            assert args.focus is not None
            # Local generated report only, with finite retained size.
            path=worker.shared._absolute(args.focus.absolute())
            with path.open('rb') as stream:raw=stream.read(16*1024*1024+1)
            assert len(raw)<=16*1024*1024
            focus=json.loads(raw);assert focus['runBinding']==binding,'Trace belongs to another run'
            report['selection']=select(focus)
            if report['selection']['status']!='selected':return 2
            rvas=report['selection']['rvas']
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
