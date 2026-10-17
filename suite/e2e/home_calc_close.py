"""Home-only Calc close provenance; existing CLI/XLSX authorizations stay separate."""
from __future__ import annotations

import math
from pathlib import Path
import sys
import json
import time
import hashlib
from collections import namedtuple

sys.path.insert(0,str(Path(__file__).resolve().parent))

from writer_model_reader import (CALC_MODEL_SERVICE,CALC_GETTER_CONTRACT,_finite,
    require_owned_model_observation,require_model_reader_cleanup)
from writer_model_barrier import require_original_shell,require_python_identity

HomeCalcClose=namedtuple('HomeCalcClose','suite process process_handle bound bound_handle hwnd child origin_json context_json source extension descriptor_json source_sha')


def _json(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,allow_nan=False)


def require_calc_source(suite,owned_root,source,descriptor):
    from home_routing_smoke import _unlinked,load_feature_inputs
    suite,owned_root,source=map(Path,(suite,owned_root,source))
    for path in (suite,owned_root,source):_unlinked(path)
    suite,owned_root,source=(p.resolve() for p in (suite,owned_root,source))
    extension=descriptor['extension'];assert descriptor['module']=='calc' and extension in ('ods','xlsx','xls','csv')
    assert descriptor['case']=='format-calc-'+extension
    assert source.parent==owned_root and source.name==f'format-calc-{extension}.{extension}'
    assert owned_root!=suite and suite not in owned_root.parents
    original=Path(descriptor['source']);_unlinked(original)
    assert source!=original.resolve() and original.is_file()
    root=Path(descriptor['featuresRoot']);_unlinked(root)
    assert hashlib.sha256((root/'office-features.json').read_bytes()).hexdigest()==descriptor['featureReportSha256']
    assert descriptor==load_feature_inputs(suite,root)[('calc',extension)], 'Source feature case differs from its passed baseline'
    for path in (source,original):
        data=path.read_bytes();assert len(data)==descriptor['bytes'] and hashlib.sha256(data).hexdigest()==descriptor['sha256']
    return descriptor['sha256']


def _home_origin(suite,process,record,source,extension):
    from home_routing_smoke import require_home_action,require_open_dialog_readiness,require_open_filename_receipt
    import lifecycle_smoke
    assert tuple(map(str,process.args))==(str(Path(suite)/'OpenGeul.Office.exe'),), 'Home authorization cannot substitute a CLI module/file launch'
    assert record['module']=='calc' and record['shellPid']==process.pid and record['keyboardInputVerified'] is False
    assert not record.get('asciiEditorInputs') and not record.get('documentInputActions')
    home=record['homeHwnd'];assert record['homeOnlyBeforeAction']==[home]
    actions=record['homeActions'];assert len(actions)==1
    module='calc' if source is None else 'open'
    require_home_action(actions[0],module)
    assert actions[0]['success'] is True and actions[0]['rawElementEquals'] is True
    assert actions[0]['homeHwnd']==home and actions[0]['shellPid']==process.pid
    if source is None:
        assert extension is None and (record['case'],record['kind'])==('tile-calc','tile')
        assert not record.get('openDialogs')
    else:
        assert (record['case'],record['kind'])==('home-open-calc-'+extension,'open')
        operations=record['openDialogs'];assert len(operations)==1
        operation=operations[0];proof=operation['openDialogReadiness']
        require_open_dialog_readiness(proof,process.pid,home)
        assert proof['action']=='open' and operation['openButtonClicks']==1
        require_open_filename_receipt(operation,process.pid,home,source)
    keys=('case','kind','module','shellPid','homeHwnd','homeOnlyBeforeAction','homeActions','openDialogs',
          'windowHwnd','parentHwnd','childHwnd','officePid','keyboardInputVerified')
    return {key:record[key] for key in keys if key in record}


def freeze_home_calc_close(suite,process,bound,record,*,source=None,extension=None):
    from home_routing_smoke import _unlinked
    _unlinked(Path(suite))
    if source is not None:_unlinked(Path(source))
    suite=Path(suite).resolve();source=Path(source).resolve() if source is not None else None
    context=record['calcReader'];assert context.get('success') is True and not context.get('error')
    binding=require_calc_reader_context(context,suite,source.as_uri() if source else '',extension)
    assert record['windowHwnd']==binding['suiteHwnd'] and record['childHwnd']==binding['childHwnd']
    assert record['officePid']==binding['officePid'] and record['parentHwnd']==binding['parentHwnd']
    origin=_home_origin(suite,process,record,source,extension)
    descriptor=record['sourceInput'] if source else None
    digest=require_calc_source(suite,source.parent,source,descriptor) if source else None
    return HomeCalcClose(suite,process,int(process._handle),bound,int(bound.handle),record['windowHwnd'],record['childHwnd'],
        _json(origin),_json(context),source,extension,_json(descriptor),digest)


def verify_home_calc_close(api,proof,record):
    import lifecycle_smoke
    assert isinstance(proof,HomeCalcClose) and record['calcReader']==json.loads(proof.context_json)
    context=json.loads(proof.context_json);binding=context['observation']['bindingBefore']
    assert proof.process.poll() is None and int(proof.process._handle)==proof.process_handle
    assert proof.bound.live() and proof.bound.pid==binding['officePid'] and proof.bound.creation==binding['officeCreationTime'] and int(proof.bound.handle)==proof.bound_handle
    assert lifecycle_smoke.process_identity(proof.bound.kernel,proof.bound_handle)==((proof.suite/'Office/program/soffice.bin').resolve(),binding['officeCreationTime'])
    assert lifecycle_smoke.process_identity(proof.bound.kernel,proof.process_handle)==((proof.suite/'OpenGeul.Office.exe').resolve(),binding['shellCreationTime'])
    assert record['windowHwnd']==proof.hwnd and record['childHwnd']==proof.child
    assert api.user.IsWindow(proof.hwnd) and api.user.IsWindow(proof.child) and api.user.IsChild(proof.hwnd,proof.child)
    assert api.pid(proof.hwnd)==proof.process.pid and api.pid(proof.child)==proof.bound.pid
    assert _json(_home_origin(proof.suite,proof.process,record,proof.source,proof.extension))==proof.origin_json
    if proof.source:
        assert record['sourceInput']==json.loads(proof.descriptor_json)
        assert require_calc_source(proof.suite,proof.source.parent,proof.source,record['sourceInput'])==proof.source_sha
    return proof


def require_home_calc_cells(value,extension):
    assert extension in (None,'ods','xlsx','xls','csv')
    assert type(value.get('sheetIndex')) is int and value['sheetIndex']==0
    assert value.get('isModified') is False, 'Home Calc source is dirty before any authorized content input'
    assert value.get('a1Text')==('' if extension is None else 'Engine-OpenGeul-calc 한글')
    for name,expected in zip(('b1Value','c1Value','d1Value'),(0,0,0) if extension is None else (17,25,42)):
        assert type(value.get(name)) in (int,float) and math.isfinite(value[name]) and value[name]==expected
    assert value.get('d1Formula')==('' if extension is None else '42' if extension=='csv' else '=SUM(B1:C1)')
    return value


def require_reader_context(context,suite,expected_url,expected_service,getter_contract):
    observation=context['observation'];binding=observation['bindingBefore'];cleanup=context['cleanup']
    assert binding['documentUrl']==expected_url
    require_owned_model_observation(observation,binding,suite,expected_service=expected_service,getter_contract=getter_contract)
    require_original_shell(context['originalShell'],binding,suite)
    require_python_identity(observation['pythonIdentity'],suite,context['inventory'],context['inventorySha256'])
    start,deadline,finish=(_finite(context[key]) for key in ('startedAt','deadline','finishedAt'))
    assert deadline==start+12
    assert start<=observation['readStartedAt']<=observation['readFinishedAt']<=cleanup['startedAt']<=cleanup['finishedAt']<=finish<=deadline
    require_model_reader_cleanup(cleanup,binding,deadline,expected_service=expected_service,getter_contract=getter_contract)
    for key in ('helperLaunch','systemConsoleHost'):assert cleanup[key]==observation[key]
    original=observation['readerProcess'];members=[row for row in cleanup['readerMembers'] if row['pid']==original['pid']]
    assert len(members)==1 and cleanup['releaseAcknowledgement']['readerPid']==original['pid']
    assert all(members[0][key]==original[key] for key in ('pid','creationTime','image','handleValue','jobHandleValue'))
    assert cleanup['jobHandleValue']==original['jobHandleValue']
    controller=observation['nativeSnapshots']['controllerBefore']
    for edge in ('nativeBefore','nativeAfter'):
        row=cleanup[edge]
        assert all(row[key]['handleValue']==controller[key]['handleValue'] for key in ('shell','office'))
        assert row['officeCommandLine']==controller['officeCommandLine'] and row['profileUrl']==controller['profileUrl']
        assert row['profileDirectory']['witness']==controller['profileDirectory']['witness']
    helper=observation['nativeSnapshots']['helperBefore'];ack=cleanup['releaseAcknowledgement']
    assert ack['profileDirectory']['witness']==helper['profileDirectory']['witness']
    assert {(r['kind'],r['handleValue']) for r in ack['observerHandleClosures']}=={
        ('shell',helper['shell']['handleValue']),('office',helper['office']['handleValue']),
        ('profile-directory',helper['profileDirectory']['witness']['handleValue'])}
    return binding


def require_calc_reader_context(context,suite,expected_url,extension):
    binding=require_reader_context(context,suite,expected_url,CALC_MODEL_SERVICE,CALC_GETTER_CONTRACT)
    require_home_calc_cells(context['observation'],extension)
    return binding


def observe_home_calc(suite,output,process,attachment,source,extension,record):
    return observe_home_model(suite,output,process,attachment,source,record,'calcReader',
        CALC_MODEL_SERVICE,CALC_GETTER_CONTRACT,lambda value:require_home_calc_cells(value,extension))


def observe_home_model(suite,output,process,attachment,source,record,key,service,getters,check):
    """One existing-frame getter, with no navigation, mutation or retry."""
    import lifecycle_smoke
    from writer_model_reader import OwnedModelReader
    from writer_style_smoke import _packaged_identity_file
    started=time.monotonic();deadline=started+12;reader=None;failure=None
    context=dict(startedAt=started,deadline=deadline,originalShell={},success=False)
    record[key]=context
    try:
        creation=lifecycle_smoke.retained_writer_shell(process,suite,context['originalShell'])
        identity,data=_packaged_identity_file(suite,'suite-inventory.json')
        context.update(inventory=json.loads(data),inventorySha256=identity['sha256'])
        reader=OwnedModelReader(suite,output,expected_service=service,getter_contract=getters,
            shell_pid=process.pid,expected_shell_creation=creation,suite_hwnd=attachment['hwnd'],parent_hwnd=attachment['parent'],
            child_hwnd=attachment['child'],office_pid=attachment['officePid'],expected_url=source.as_uri() if source else '')
        context['observation']=reader.start(deadline)
        check(context['observation'])
    except BaseException as exc:
        failure=exc;context['error']=type(exc).__name__+': '+str(exc)
    finally:
        if reader is not None:
            try:context['cleanup']=reader.close(deadline)
            except BaseException as later:
                context['cleanupError']=type(later).__name__+': '+str(later)
                if failure is None:failure=later
        context['finishedAt']=time.monotonic()
    if failure is not None:raise failure
    require_reader_context(context,suite,source.as_uri() if source else '',service,getters)
    context['success']=True
    return context


def close_home_calc(api,proof,record):
    """One native close, then clean exit or one exact owned Discard choice."""
    import windows_smoke as native
    import lifecycle_smoke
    from generated_calc_close import require_calc_prompt_buttons
    from pywinauto import Desktop
    verify_home_calc_close(api,proof,record)
    started=time.monotonic();deadline=started+20
    evidence=dict(startedAt=started,deadline=deadline,closeMessageCount=1,discardClickCount=0,promptObservations=[])
    record['homeCalcClose']=evidence
    def remaining():
        value=deadline-time.monotonic();assert value>0, 'Home Calc close exceeded its original deadline';return value
    api.request_close(proof.hwnd,proof.process.pid)
    def closed_or_prompt():
        if not api.user.IsWindow(proof.hwnd):return ('closed',0)
        verify_home_calc_close(api,proof,record)
        matches=[handle for handle in api.windows(proof.process.pid) if api.user.GetWindow(handle,4)==proof.hwnd
            or (api.title(handle)=='OpenGeul Calc' and api.class_name(handle)=='#32770')]
        assert len(matches)<=1, 'Home Calc prompt is ambiguous'
        if not matches:return None
        dialog,=matches
        native.require_dialog_identity(api.pid(dialog),proof.process.pid,api.user.GetWindow(dialog,4),proof.hwnd,
            api.title(dialog),'OpenGeul Calc',api.class_name(dialog))
        return ('prompt',dialog)
    branch,dialog=native.wait_for(closed_or_prompt,seconds=remaining());evidence.update(branch=branch,dialogHwnd=dialog)
    if branch=='prompt':
        accessible=Desktop(backend='uia').window(handle=dialog).wrapper_object()
        def choice():
            remaining();verify_home_calc_close(api,proof,record)
            native.require_dialog_identity(api.pid(dialog),proof.process.pid,api.user.GetWindow(dialog,4),proof.hwnd,
                api.title(dialog),'OpenGeul Calc',api.class_name(dialog))
            observation={};evidence['promptObservations'].append(observation)
            assert len(evidence['promptObservations'])<=201, 'Home Calc prompt observation bound exceeded'
            buttons=require_calc_prompt_buttons(api,accessible,proof.process.pid,dialog,observation)
            if buttons is None:return None
            selected=[button for button in buttons if button.element_info.name=='저장하지 않음'];assert len(selected)==1
            evidence['buttonAncestry']=lifecycle_smoke.require_dialog_button_ancestry(api,accessible,selected[0],proof.process.pid,dialog)
            return selected[0]
        native.wait_for(choice,seconds=remaining())
        Desktop(backend='win32').window(handle=dialog).wrapper_object().set_focus();api.require_foreground(dialog)
        button=native.wait_for(choice,seconds=remaining());remaining()
        evidence['discardClickCount']=1;button.click_input()
        native.wait_for(lambda:not api.user.IsWindow(dialog),seconds=20)
    native.wait_for(lambda:not api.user.IsWindow(proof.hwnd),seconds=20)
    native.wait_for(lambda:not api.user.IsWindow(proof.child),seconds=10)
    if proof.source:require_calc_source(proof.suite,proof.source.parent,proof.source,json.loads(proof.descriptor_json))
    evidence['frameClosed']=True
    return evidence
