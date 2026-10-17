"""Physical ordinary-text Calc Ctrl+S while A1 remains uncommitted.

No Enter, AcceptFormula, cell setter or pre-save completion barrier is used.
Async validation/formula correction is outside this bounded case. Only an owned
copy of a generated fixture is edited. Fresh-engine reopen is engine evidence.
"""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import sys
import time
import traceback
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parent))
import calc_model_barrier
from windows_smoke import (Windows, ascii_input, capture_failure, close_document, close_home,
    launch_suite, prepare_editor_focus, require_engine_fixture, stop_owned_test_process,
    verified_attachment, wait_for, write_result)

MARKER='UI-OpenGeul-calc-CtrlS'
CASE='calc-active-cell-save'
NS=calc_model_barrier.NS
MAX_BYTES=16*1024*1024


def read_cells(data):
    """Independent bounded OOXML read; resolve the actual first-sheet relation."""
    assert isinstance(data,bytes) and 0<len(data)<=MAX_BYTES
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names=z.namelist();assert len(names)==len(set(names)),'Duplicate OOXML member'
        assert all(not n.startswith(('/','\\')) and '\\' not in n and '..' not in PurePosixPath(n).parts for n in names)
        def xml(name):
            info=z.getinfo(name);assert info.file_size<=2*1024*1024,'Unbounded worksheet XML'
            return ET.fromstring(z.read(name))
        sheets=xml('xl/workbook.xml').findall('s:sheets/s:sheet',NS)
        assert len(sheets)==1,'Generated Calc sheet count changed'
        relation=sheets[0].get('{'+NS['r']+'}id');assert relation
        rels=[r for r in xml('xl/_rels/workbook.xml.rels').findall('p:Relationship',NS) if r.get('Id')==relation]
        assert len(rels)==1,'Ambiguous worksheet relationship'
        rel=rels[0];target=rel.get('Target','');uri=urlsplit(target)
        assert rel.get('Type')==NS['r']+'/worksheet' and rel.get('TargetMode','Internal')=='Internal'
        assert target and not any((uri.scheme,uri.netloc,uri.query,uri.fragment)) and '\\' not in target and '\x00' not in target
        assert '..' not in PurePosixPath(target).parts
        part=str(PurePosixPath(target.lstrip('/')) if target.startswith('/') else PurePosixPath('xl')/target)
        assert part.startswith('xl/')
        cells=xml(part).findall('s:sheetData/s:row/s:c',NS)
        assert len(cells)==4 and {c.get('r') for c in cells}=={'A1','B1','C1','D1'},'Unexpected persisted cell set'
        cells={c.get('r'):c for c in cells};a1=cells['A1'];kind=a1.get('t')
        assert a1.find('s:f',NS) is None,'A1 changed into a formula'
        if kind=='s':
            shared=xml('xl/sharedStrings.xml').findall('s:si',NS)
            index=int(a1.findtext('s:v',default='',namespaces=NS));assert 0<=index<len(shared)
            text=''.join(n.text or '' for n in shared[index].findall('.//s:t',NS))
        else:
            assert kind=='inlineStr','A1 is not string data'
            text=''.join(n.text or '' for n in a1.findall('s:is//s:t',NS))
        result={'a1Text':text}
        for address,key in (('B1','b1Value'),('C1','c1Value'),('D1','d1Value')):
            c=cells[address];assert c.get('t','n')=='n'
            assert (c.find('s:f',NS) is not None)==(address=='D1'),'Formula moved or disappeared'
            result[key]=float(c.findtext('s:v',default='',namespaces=NS))
        result['d1Formula']='='+cells['D1'].findtext('s:f',default='',namespaces=NS)
        return result


def require_grid(observed,baseline,expected_text):
    assert observed.get('a1Text')==expected_text,'Saved A1 lost, changed or duplicated the physical edit'
    for key in ('b1Value','c1Value','d1Value'):
        value=observed.get(key)
        assert type(value) in (int,float) and value==baseline[key],'Calc neighboring value changed: '+key
    assert observed.get('d1Formula')==baseline['d1Formula']=='=SUM(B1:C1)','Calc formula changed'


def require_uncommitted_cells(observation,baseline):
    require_grid(observation,baseline,baseline['a1Text'])
    assert observation.get('isModified') is False,'Pre-Save model already accepted an edit'


def require_actions(record):
    assert record.get('navigationKeys')==['^{HOME}','{F2}','^{END}'],'Original edit navigation changed'
    assert record.get('commitKeys')==[],'Harness must not commit the active cell'
    assert type(record.get('saveShortcutCount')) is int and record['saveShortcutCount']==1,'Ctrl+S must occur once'
    assert record.get('physicalAsciiMarker')==MARKER
    assert record.get('uncommittedBeforeSaveVerified') is True
    assert record.get('observerClosedBeforeSave') is True


def require_save_trace(rows,trace_id):
    assert isinstance(rows,list) and 5<=len(rows)<=32
    assert all(r.get('traceId')==trace_id for r in rows),'Save trace identifier changed'
    assert len({r.get('workerPid') for r in rows})==1 and type(rows[0].get('workerPid')) is int
    assert rows[0]['workerPid']>0
    sequences=[r.get('sequence') for r in rows]
    assert all(type(n) is int and n>0 for n in sequences) and sequences==sorted(set(sequences)),'Save trace order is invalid'
    selected=[r for r in rows if r.get('event') in ('suite.nativeDispatch','suite.workerSave','suite.calcNativeSave')]
    assert [(r['event'],r.get('stage')) for r in selected]==[
        ('suite.nativeDispatch','received'),('suite.workerSave','request.begin'),('suite.calcNativeSave','begin'),
        ('suite.calcNativeSave','end'),('suite.workerSave','request.end')],'Save recursed, retried, bypassed native CtrlS, or failed'
    native,request,begin,end,reply=selected
    assert native['details']==dict(receiptSequence=1,command='save',nativeCommand='.uno:Save')
    assert begin['details']==dict(nativeCommand='.uno:Save')
    assert end['details'].get('nativeCommand')=='.uno:Save'
    assert type(end['details'].get('dispatchState')) is int and end['details']['dispatchState']==1
    assert end['details'].get('dispatchResult') is True
    assert type(request['details'].get('requestId')) is int and request['details']['requestId']>0
    assert request['details'].get('requestId')==reply['details'].get('requestId') and reply['details'].get('ok') is True
    return dict(workerPid=native['workerPid'],requestId=request['details']['requestId'],singleNativeTransaction=True,
                nativeCommand='.uno:Save',dispatchState=1,dispatchResult=True)


def require_host_trace(rows,shell_pid):
    import re
    assert isinstance(rows,list) and len(rows)==6,'Host Save route is missing, duplicated or failed'
    assert all(r.get('event')=='suite.workerSave' and r.get('component')=='host' and r.get('processId')==shell_pid for r in rows)
    sequences=[r.get('sequence') for r in rows]
    assert all(type(n) is int and n>0 for n in sequences) and sequences==sorted(set(sequences))
    token=rows[0].get('traceId');assert isinstance(token,str) and re.fullmatch('[a-f0-9]{32}',token)
    command=rows[0]['details'].get('commandSequence');assert type(command) is int and command>0
    assert all(r.get('traceId')==token and r['details'].get('commandSequence')==command for r in rows)
    commands=[r for r in rows if r.get('stage','').startswith('command.')]
    requests=[r for r in rows if r.get('stage','').startswith('request.')]
    assert [r['stage'] for r in commands]==['command.received','command.handler.enter','command.handler.return']
    assert all(r['details'].get('command')=='save' for r in commands)
    assert [r['stage'] for r in requests]==['request.begin','request.written','request.reply']
    assert commands[0]['sequence']<commands[1]['sequence']<requests[0]['sequence']
    request=requests[0]['details'].get('requestId');assert type(request) is int and request>0
    assert all(r['details'].get('requestId')==request for r in requests)
    assert requests[-1]['details'].get('ok') is True
    return dict(traceId=token,requestId=request,commandSequence=command)


def require_pending_observation(before,now,baseline,*,suite,inventory,inventory_sha256,original_shell,expected_url,deadline):
    from writer_model_barrier import require_original_shell,require_python_identity
    from writer_model_reader import require_owned_model_observation
    binding=before['bindingBefore'];assert binding['documentUrl']==expected_url
    require_original_shell(original_shell,binding,suite)
    for row in (before,now):
        require_owned_model_observation(row,binding,suite,expected_service=calc_model_barrier.SERVICE,
            getter_contract=calc_model_barrier.GETTERS)
        require_python_identity(row['pythonIdentity'],suite,inventory,inventory_sha256)
        assert row['readStartedAt']<=row['readFinishedAt']<=deadline
        require_uncommitted_cells(row,baseline)
    for key in ('helperLaunch','systemConsoleHost'):
        assert before[key]==now[key],'Original reader launch witness changed'
    for edge in ('before','after'):
        assert now['unoSnapshots'][edge]['proxyIdentity']==before['unoSnapshots']['before']['proxyIdentity']
    for key in ('pid','creationTime','handleValue','jobHandleValue'):
        assert now['readerProcess'][key]==before['readerProcess'][key],'Original reader generation changed'
    for origin in ('controller','helper'):
        anchor=before['nativeSnapshots'][origin+'Before']
        for edge in ('Before','After'):
            row=now['nativeSnapshots'][origin+edge]
            for process in ('shell','office'):
                assert row[process]['handleValue']==anchor[process]['handleValue'],'Retained process HANDLE changed'
            assert row['officeCommandLine']==anchor['officeCommandLine'] and row['profileUrl']==anchor['profileUrl']
            assert row['profileDirectory']['witness']==anchor['profileDirectory']['witness']


def verify_reopen(suite,source,baseline,expected,output):
    from engine_smoke import Engine
    engine=Engine(suite);document=None
    result=dict(success=False,kind='independent-engine-reopen',guiInputProved=False)
    try:
        from writer_style_smoke import observe_packaged_python,require_packaged_python
        result['pythonIdentity']=require_packaged_python(suite,observe_packaged_python())
        before_sha=hashlib.sha256(source.read_bytes()).hexdigest()
        engine.start()
        from dispatch import make_interaction_handler
        props=tuple(engine.prop(n,v) for n,v in (('Hidden',True),('ReadOnly',True),('MacroExecutionMode',0),
            ('UpdateDocMode',0),('PickListEntry',False),('AsTemplate',False),('InteractionHandler',make_interaction_handler())))
        document=engine.desktop.loadComponentFromURL(source.as_uri(),'_blank',0,props)
        assert document is not None and document.isReadonly()
        assert document.supportsService(calc_model_barrier.SERVICE)
        sheet=document.Sheets.getByIndex(0)
        observed=dict(a1Text=sheet.getCellRangeByName('A1').getString(),
            b1Value=sheet.getCellRangeByName('B1').getValue(),c1Value=sheet.getCellRangeByName('C1').getValue(),
            d1Formula=sheet.getCellRangeByName('D1').getFormula(),d1Value=sheet.getCellRangeByName('D1').getValue())
        require_grid(observed,baseline,expected)
        assert document.Sheets.getCount()==1 and document.isModified() is False
        result.update(success=True,cells=observed)
    except BaseException as exc:
        result.update(error=type(exc).__name__+': '+str(exc),traceback=traceback.format_exc());raise
    finally:
        if document is not None:
            try:document.close(False)
            except BaseException as exc:result.update(success=False,closeError=str(exc))
        engine.cleanup();result['cleanupErrors']=list(engine.cleanup_errors)
        if engine.cleanup_errors:result['success']=False
        after_sha=hashlib.sha256(source.read_bytes()).hexdigest()
        result['afterSha256']=after_sha
        if 'before_sha' in locals():
            result['beforeSha256']=before_sha
            if after_sha!=before_sha:result.update(success=False,error='Read-only reopen changed saved bytes')
        output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    assert result['success'],'Independent reopen or cleanup failed'
    return result


def await_reopen_job(helper,probe,record,*,clock=time.monotonic,pause=time.sleep):
    # Python.exe can be a launcher. Its exit alone cannot qualify its child
    # interpreter/engine. The helper is born suspended inside a private job.
    deadline=clock()+90.;record.update(jobHandleValue=int(helper.job),terminated=False,jobSamples=[])
    try:
        for _ in range(1000):
            pids=probe.job_pids(helper.job)
            code=helper.poll();record['jobSamples'].append(dict(pids=pids,launcherExitCode=code))
            if not pids and code is not None:
                record['allOwnedProcessesExited']=True
                return code
            if clock()>=deadline:raise TimeoutError('Independent reopen exceeded its original deadline')
            pause(.1)
        raise TimeoutError('Independent reopen exceeded finite job observations')
    except BaseException:
        record['terminated']=True
        try:
            helper.terminate()  # Only this suspended-before-launch private job.
            for _ in range(50):
                pids=probe.job_pids(helper.job)
                if not pids:
                    record['allOwnedProcessesExitedAfterTermination']=True;break
                pause(.1)
            else:record['cleanupError']='Owned reopen job still has live members'
        except BaseException as later:record['cleanupError']=type(later).__name__+': '+str(later)
        raise


def physical_case(suite,fixtures,output):
    from pywinauto import Desktop
    from pywinauto.keyboard import send_keys
    from lifecycle_smoke import retained_writer_shell
    from writer_model_reader import OwnedModelReader,require_model_reader_cleanup
    from writer_style_smoke import _packaged_identity_file
    original=require_engine_fixture(fixtures,'calc','xlsx')
    source_bytes=original.read_bytes();baseline=calc_model_barrier.baseline_from_ooxml(source_bytes)
    require_uncommitted_cells(dict(read_cells(source_bytes),isModified=False),baseline)
    owned=output/'fixtures';owned.mkdir(exist_ok=False)
    source=owned/'OpenGeul-calc.xlsx'
    with source.open('xb') as f:f.write(source_bytes)
    expected=baseline['a1Text']+MARKER
    process=reader=None
    record=dict(schemaVersion=1,case=CASE,kind='physical-uncommitted-calc-save',success=False,stage='launch',
        module='calc',sourceSha256=hashlib.sha256(source_bytes).hexdigest(),baseline=baseline,
        navigationKeys=[],commitKeys=[],saveShortcutCount=0,asyncValidationQualified=False)
    diagnostics=output/'diagnostics';diagnostics.mkdir()
    prior={key:os.environ.get(key) for key in ('OPENGEUL_SUITE_DIAGNOSTICS',)}
    api=Windows()
    try:
        os.environ['OPENGEUL_SUITE_DIAGNOSTICS']=str(diagnostics)
        try:process=launch_suite([str(suite/'OpenGeul.Office.exe'),'--module','calc','--file',str(source)],suite,output,CASE)
        finally:
            for key,value in prior.items():
                if value is None:os.environ.pop(key,None)
                else:os.environ[key]=value
        record['shellPid']=process.pid
        hwnd,parent,child,office_pid=verified_attachment(api,process,'calc')
        record.update(windowHwnd=hwnd,parentHwnd=parent,childHwnd=child,officePid=office_pid)
        window=Desktop(backend='win32').window(handle=hwnd).wrapper_object()
        window.maximize();window.set_focus()
        wait_for(lambda:api.user.GetAncestor(api.user.GetForegroundWindow(),2)==hwnd,10)
        window.capture_as_image().save(output/(CASE+'-before.png'))
        record['stage']='focus-editor'
        prepare_editor_focus(api,hwnd,child,process.pid,office_pid,record,
            lambda:Desktop(backend='win32').window(handle=child).wrapper_object().click_input(),
            lambda:send_keys('^{F6}',pause=.1))
        record['originalShell']={};creation=retained_writer_shell(process,suite,record['originalShell'])
        identity,data=_packaged_identity_file(suite,'suite-inventory.json')
        inventory=json.loads(data)
        deadline=time.monotonic()+calc_model_barrier.MAX_SECONDS
        reader=OwnedModelReader(suite,output/'active-cell-reader',expected_service=calc_model_barrier.SERVICE,
            getter_contract=calc_model_barrier.GETTERS,shell_pid=process.pid,expected_shell_creation=creation,
            suite_hwnd=hwnd,parent_hwnd=parent,child_hwnd=child,office_pid=office_pid,expected_url=source.as_uri())
        record['stage']='observe-clean-before-input'
        before=reader.start(deadline);record['beforeInput']=before
        require_uncommitted_cells(before,baseline)
        record['stage']='physical-edit-without-enter'
        send_keys('^{HOME}{F2}^{END}',pause=.1);record['navigationKeys']=['^{HOME}','{F2}','^{END}']
        api.require_editor_focus(hwnd,child)
        ascii_input.type_ascii(api,hwnd,child,MARKER,record,pause=.04)
        record['physicalAsciiMarker']=MARKER
        api.require_editor_focus(hwnd,child)
        record['stage']='observe-original-model-still-uncommitted'
        pending=reader.read(deadline);record['beforeSave']=pending
        require_pending_observation(before,pending,baseline,suite=suite,inventory=inventory,
            inventory_sha256=identity['sha256'],original_shell=record['originalShell'],
            expected_url=source.as_uri(),deadline=deadline)
        record['uncommittedBeforeSaveVerified']=True
        try:cleanup=reader.close(deadline)
        finally:reader=None
        record['readerCleanup']=cleanup
        require_model_reader_cleanup(cleanup,before['bindingBefore'],deadline,
            expected_service=calc_model_barrier.SERVICE,getter_contract=calc_model_barrier.GETTERS)
        record['observerClosedBeforeSave']=True
        # No focus action, input acceptance or model setter may occur here.
        api.require_editor_focus(hwnd,child)
        record['stage']='single-physical-ctrl-s'
        record['saveShortcutCount']=1;send_keys('^s',pause=.1)
        require_actions(record)
        def saved():
            raw=source.read_bytes();cells=read_cells(raw)
            if cells['a1Text']==baseline['a1Text']:return False
            require_grid(cells,baseline,expected)
            return dict(sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw),cells=cells)
        record['stage']='wait-exact-durable-workbook'
        record['persisted']=wait_for(saved,30)
        assert record['persisted']['sha256']!=record['sourceSha256']
        assert not api.windows(office_pid),'Office created an unowned visible top-level window'
        window.capture_as_image().save(output/(CASE+'-saved.png'))
        record['stage']='close-original-editor'
        close_document(api,process,hwnd,child,record);close_home(api,process,record)
        process.wait(timeout=15)
        rows=[]
        for path in sorted(diagnostics.glob('worker-save-*.jsonl')):
            assert not path.is_symlink() and path.stat().st_size<=128*1024
            rows.extend(json.loads(line) for line in path.read_text(encoding='utf-8').splitlines())
        host_rows=[]
        assert (output/(CASE+'-stderr.log')).stat().st_size<=16*1024*1024,'Unbounded shell diagnostics'
        for line in (output/(CASE+'-stderr.log')).read_text(encoding='utf-8',errors='replace').splitlines():
            if line.startswith('{'):
                try:row=json.loads(line)
                except ValueError:continue
                if isinstance(row,dict) and row.get('component')=='host' and row.get('event')=='suite.workerSave':host_rows.append(row)
        host=require_host_trace(host_rows,process.pid)
        record['hostSaveTrace']=host_rows
        record['saveTrace']=require_save_trace(rows,host['traceId'])
        assert record['saveTrace']['requestId']==host['requestId']
        record['saveTraceRows']=rows
        require_grid(read_cells(source.read_bytes()),baseline,expected)
        assert original.read_bytes()==source_bytes,'Original generated fixture changed'
        record['stage']='independent-fresh-engine-reopen'
        # The controller does not import UNO. A new packaged Python process runs
        # a separate owned Engine and writes its own result/logs.
        config=output/'reopen-input.json'
        config.write_text(json.dumps(dict(baseline=baseline,expected=expected),ensure_ascii=False),encoding='utf-8')
        command=[str(suite/'Office/program/python.exe'),str(Path(__file__).resolve()),'--verify-reopen',
            '--suite',str(suite),'--output',str(output),'--owned-fixture',str(source)]
        sys.path.insert(0,str(suite/'worker'))
        from native_windows import OwnedOfficeProcess,ProcessDiagnosticsApi
        helper=OwnedOfficeProcess(command,suite/'Office/program')
        record['reopenHelperPid']=helper.pid
        record['reopenJob']={}
        try:
            code=await_reopen_job(helper,ProcessDiagnosticsApi(),record['reopenJob'])
            assert code==0,'Independent packaged-engine reopen failed'
        finally:helper.close()
        record['reopen']=json.loads((output/'reopen-result.json').read_text(encoding='utf-8'))
        assert record['reopen']['success'] is True
        record.update(success=True,stage='complete',ordinaryActiveCellCtrlSVerified=True,
            originalFixtureUnchanged=True,cleanClose=True,imeVerified=False)
        return record
    except BaseException as exc:
        if reader is not None:
            try:record['readerCleanup']=reader.close(deadline)
            except BaseException as later:record['readerCleanupError']=str(later)
        capture_failure(output,CASE,record,exc)
        raise
    finally:
        if process is not None:stop_owned_test_process(process,record)
        write_result(output,CASE,record)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite',type=Path,required=True);parser.add_argument('--fixtures',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--verify-reopen',action='store_true');parser.add_argument('--owned-fixture',type=Path)
    args=parser.parse_args()
    if os.name!='nt' or not __debug__:raise RuntimeError('Physical Calc save qualification requires Windows')
    for path in (args.suite,args.output):
        assert not str(path).startswith(('\\\\','//')) and '..' not in path.parts
        for part in (path,*path.parents):
            assert not part.is_symlink() and not getattr(part,'is_junction',lambda:False)(),'Linked paths are forbidden'
    suite,output=args.suite.resolve(),args.output.resolve()
    assert suite!=output and suite not in output.parents and output not in suite.parents
    if args.verify_reopen:
        source=output/'fixtures/OpenGeul-calc.xlsx'
        assert args.owned_fixture==source and source.is_file() and not source.is_symlink()
        config=json.loads((output/'reopen-input.json').read_text(encoding='utf-8'))
        from contextlib import redirect_stdout,redirect_stderr
        with (output/'reopen-stdout.log').open('x',encoding='utf-8') as stdout,(output/'reopen-stderr.log').open('x',encoding='utf-8') as stderr:
            with redirect_stdout(stdout),redirect_stderr(stderr):
                verify_reopen(suite,source,config['baseline'],config['expected'],output/'reopen-result.json')
        return 0
    assert args.fixtures is not None
    for part in (args.fixtures,*args.fixtures.parents):
        assert not part.is_symlink() and not getattr(part,'is_junction',lambda:False)(),'Linked fixture roots are forbidden'
    fixtures=args.fixtures.resolve()
    assert fixtures!=output and fixtures not in output.parents and output not in fixtures.parents
    output.mkdir(parents=True,exist_ok=False)
    try:
        record=physical_case(suite,fixtures,output)
    except BaseException as exc:
        result=output/(CASE+'-result.json')
        if result.is_file():record=json.loads(result.read_text(encoding='utf-8'))
        else:
            record=dict(case=CASE,success=False,stage='case-setup')
            capture_failure(output,CASE,record,exc);write_result(output,CASE,record)
    report=dict(schemaVersion=1,kind='native-calc-active-cell-save',success=record.get('success') is True,
        asyncValidationQualified=False,tests=[record])
    (output/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(CASE+': '+('passed' if report['success'] else 'FAILED: '+record.get('error','Missing evidence')),flush=True)
    return 0 if report['success'] else 1


if __name__=='__main__':raise SystemExit(main())
