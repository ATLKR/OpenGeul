"""Opt-in Discard cleanup for an already verified generated/saved Calc copy.

This helper never handles arbitrary documents or an unexpected prompt. It is
separate from the three-choice pending-input probe and posts exactly one close.
"""
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import time


@dataclass(frozen=True)
class SavedCalcCopy:
    suite: Path
    root: Path
    path: Path
    sha256: str
    cells: tuple


@dataclass(frozen=True)
class GeneratedBlankCalc:
    suite: Path
    process: object
    hwnd: int
    child: int
    shell: object
    engine: object
    shell_creation: int
    engine_creation: int
    command: tuple


def _unlinked(path):
    for part in (path,*path.parents):
        assert not part.is_symlink() and not getattr(part,'is_junction',lambda:False)(), 'Generated copy path is linked'


def freeze_saved_calc_copy(suite,owned_root,path,expected_sha256,expected_cells,*,role='engine-fixture'):
    """Call only after the harness verifies its generated copy's saved semantics."""
    suite,owned_root,path=map(Path,(suite,owned_root,path))
    for value in (suite,owned_root,path): _unlinked(value)
    suite,owned_root,path=(p.resolve() for p in (suite,owned_root,path))
    assert suite.is_dir() and owned_root.is_dir() and path.is_file()
    names={'engine-fixture':'OpenGeul-calc.xlsx','korean-ui-copy':'korean-ui-calc-fixture.xlsx'}
    assert role in names and path==owned_root/names[role], 'Only a fixed generated Calc fixture is eligible'
    assert owned_root!=suite and suite not in owned_root.parents, 'Discard authorization must be outside the payload'
    assert isinstance(expected_sha256,str) and re.fullmatch('[0-9a-f]{64}',expected_sha256)
    assert set(expected_cells)=={'a1Text','b1Value','c1Value','d1Formula','d1Value'}
    assert expected_cells['a1Text'].startswith('Engine-OpenGeul-calc 한글'), 'Expected generated Calc marker is missing'
    assert [expected_cells[k] for k in ('b1Value','c1Value','d1Value')]==[17,25,42]
    assert expected_cells['d1Formula']=='=SUM(B1:C1)'
    proof=SavedCalcCopy(suite,owned_root,path,expected_sha256,tuple(sorted(expected_cells.items())))
    verify_saved_calc_copy(proof)
    return proof


def verify_saved_calc_copy(proof):
    from calc_save_smoke import read_cells
    assert isinstance(proof,SavedCalcCopy), 'Explicit verified generated-copy authorization is required'
    _unlinked(proof.path)
    assert proof.path.resolve().parent==proof.root and proof.path.name in ('OpenGeul-calc.xlsx','korean-ui-calc-fixture.xlsx') and proof.path.is_file()
    data=proof.path.read_bytes()
    assert hashlib.sha256(data).hexdigest()==proof.sha256, 'Verified saved copy bytes changed'
    assert read_cells(data)==dict(proof.cells), 'Verified saved copy cells changed'


def freeze_saved_calc_from_baseline(suite,owned_root,path,baseline,*,suffix='',expected_sha256=None,role='engine-fixture'):
    """Require the caller's frozen baseline plus its already verified edit."""
    cells={key:baseline[key] for key in ('a1Text','b1Value','c1Value','d1Formula','d1Value')}
    cells['a1Text']+=suffix
    digest=expected_sha256 if expected_sha256 is not None else hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return freeze_saved_calc_copy(suite,owned_root,path,digest,cells,role=role)


def _blank_command_and_case(suite,process,record):
    command=tuple(map(str,process.args)) if isinstance(process.args,(list,tuple)) else ()
    assert len(command)==3 and Path(command[0]).resolve()==suite/'OpenGeul.Office.exe' and command[1:]==('--module','calc'), 'Blank authorization requires the exact fileless Calc factory launch'
    assert record.get('module')=='calc'
    if record.get('kind')=='new-document':
        assert process.opengeul_evidence_case=='new-calc'
        assert record.get('keyboardInputVerified') is False and record.get('contentMutationVerified') is False
    else:
        attempt=record.get('attempt')
        assert type(attempt) is int and 1<=attempt<=40 and attempt%4==2
        assert record.get('mode')=='new' and record.get('case')==f'attempt-{attempt:03d}-new-calc'
        assert process.opengeul_evidence_case==record['case']
    return command


def freeze_generated_blank_calc(suite,api,process,hwnd,child,record):
    """Bind the exact fresh factory launch and retained shell/engine generations."""
    import lifecycle_smoke as lifecycle
    suite=Path(suite).resolve();command=_blank_command_and_case(suite,process,record)
    shell=engine=None
    try:
        shell=lifecycle.BoundHwpProcess(process.pid,suite/'OpenGeul.Office.exe')
        engine=lifecycle.BoundHwpProcess(api.pid(child),suite/'Office/program/soffice.bin')
        proof=GeneratedBlankCalc(suite,process,hwnd,child,shell,engine,shell.creation,engine.creation,command)
        verify_generated_blank_calc(api,process,hwnd,child,record,proof)
        return proof
    except BaseException:
        if engine is not None:engine.close()
        if shell is not None:shell.close()
        raise


def verify_generated_blank_calc(api,process,hwnd,child,record,proof):
    import lifecycle_smoke as lifecycle
    assert isinstance(proof,GeneratedBlankCalc) and proof.process is process
    assert record.get('shellPid')==process.pid and record.get('windowHwnd')==hwnd and record.get('childHwnd')==child
    assert api.user.IsWindow(hwnd) and api.user.IsWindow(child) and api.user.IsChild(hwnd,child)
    assert (hwnd,child)==(proof.hwnd,proof.child) and api.pid(hwnd)==proof.shell.pid and api.pid(child)==proof.engine.pid
    assert _blank_command_and_case(proof.suite,process,record)==proof.command
    assert process.poll() is None and proof.shell.live() and proof.engine.live()
    assert proof.engine_creation>=proof.shell_creation>0
    for bound,image,creation in ((proof.shell,proof.suite/'OpenGeul.Office.exe',proof.shell_creation),
                                 (proof.engine,proof.suite/'Office/program/soffice.bin',proof.engine_creation)):
        assert lifecycle.process_identity(bound.kernel,bound.handle)==(image.resolve(),creation), 'Blank native generation changed'
    assert lifecycle.process_identity(proof.shell.kernel,int(process._handle))==(proof.suite/'OpenGeul.Office.exe',proof.shell_creation), 'Blank launch Popen HANDLE changed'


def close_saved_calc_copy(api,process,hwnd,child,record,proof):
    evidence=dict(path=str(proof.path),ownedRoot=str(proof.root),savedSha256=proof.sha256,expectedCells=dict(proof.cells))
    check=lambda:verify_saved_calc_copy(proof)
    _close_calc_prompt(api,process,hwnd,child,record,check,evidence,'verifiedSavedCalcDiscard')
    verify_saved_calc_copy(proof);evidence['diskBytesUnchanged']=True


def close_generated_blank_calc(api,process,hwnd,child,record,proof):
    import windows_smoke as native
    assert isinstance(proof,GeneratedBlankCalc)
    evidence=dict(command=list(proof.command),shellCreationTime=proof.shell_creation,
                  engineCreationTime=proof.engine_creation,sourceDocument=None,kind='fresh-generated-blank-calc')
    try:
        check=lambda:verify_generated_blank_calc(api,process,hwnd,child,record,proof)
        _close_calc_prompt(api,process,hwnd,child,record,check,evidence,'verifiedGeneratedBlankCalcDiscard')
        native.wait_for(lambda:not proof.engine.live(),seconds=10)
        evidence['originalEngineExited']=True
    finally:
        proof.engine.close();proof.shell.close()


def _require_native_titlebar_close(button,path,dialog):
    """Recognize only the observed Win32 nonclient Close provider and ancestry."""
    info=button.element_info
    assert len(path)==3, 'Expected exact three-choice Calc prompt: unexpected button ancestry'
    control,titlebar,root=path
    assert [row['controlType'] for row in path]==['Button','TitleBar','Window'], 'Expected exact three-choice Calc prompt: unexpected button role'
    assert info.name=='Close' and info.automation_id=='' and info.class_name=='', 'Expected exact three-choice Calc prompt: unexpected nonclient identity'
    assert control['nativeHandle']==titlebar['nativeHandle']==0 and root['nativeHandle']==dialog
    # These IDs identify the native nonclient provider, independently of the
    # localized caption. A client button named Close cannot match this shape.
    prefix=[42,dialog,3,-2147483647,dialog,-2]
    assert control['runtimeId']==prefix+[5] and titlebar['runtimeId']==prefix+[0]
    assert root['runtimeId']==[42,dialog]


def _raw_titlebar_path(button,accessible,shell_pid,dialog):
    """Verify RawView separately when ControlView omits the titlebar node."""
    node=getattr(button.element_info,'element',None)
    assert node is not None, 'Expected exact three-choice Calc prompt: no raw element proof'
    from pywinauto.uia_defines import IUIA
    uia=IUIA().iuia;root=accessible.element_info.element;path=[]
    types={50000:'Button',50037:'TitleBar',50032:'Window'}
    for _ in range(3):
        assert node, 'Calc nonclient RawView ancestry ended before the owned root'
        row=dict(nativeHandle=int(node.CurrentNativeWindowHandle or 0),processId=int(node.CurrentProcessId),
                 runtimeId=list(node.GetRuntimeId()),name=str(node.CurrentName)[:256],
                 controlType=types.get(int(node.CurrentControlType),'unexpected'))
        path.append(row)
        assert row['processId']==shell_pid and row['runtimeId'], 'Calc nonclient RawView ancestry is foreign'
        if row['controlType']=='Window':
            assert row['nativeHandle']==dialog and uia.CompareElements(node,root), 'Calc nonclient RawView root is not the exact selected dialog'
            assert path[0]['runtimeId']==list(button.element_info.runtime_id)
            return path
        node=uia.RawViewWalker.GetParentElement(node)
    raise AssertionError('Calc nonclient RawView ancestry does not reach its owned dialog')


def require_calc_prompt_buttons(api,accessible,shell_pid,dialog,evidence):
    """Read only; callers retain their original owner/launch and action guards."""
    import lifecycle_smoke as lifecycle
    labels=[item.element_info.name for item in accessible.descendants()]
    all_buttons=accessible.descendants(control_type='Button')
    rows=[]
    for item in all_buttons[:64]:
        row=dict(name=str(item.element_info.name)[:256],visible=bool(item.is_visible()),enabled=bool(item.is_enabled()))
        for key,attribute in (('automationId','automation_id'),('controlId','control_id'),
                ('processId','process_id'),('runtimeId','runtime_id'),('controlType','control_type')):
            try:
                value=getattr(item.element_info,attribute,None)
                if isinstance(value,(tuple,list)):value=list(value)[:32]
                elif isinstance(value,str):value=value[:256]
                if value is None or isinstance(value,(str,int,bool,list)):row[key]=value
            except Exception as exc:row.setdefault('fieldErrors',[]).append(key+': '+type(exc).__name__)
        rows.append(row)
    evidence.update(dialogHwnd=int(dialog),ownerHwnd=int(api.user.GetWindow(dialog,4) or 0),shellPid=shell_pid,title=api.title(dialog),
        className=api.class_name(dialog),labels=[str(name)[:256] for name in labels[:128]],
        labelCount=len(labels),buttons=rows,buttonCount=len(all_buttons),ready=False,readiness='unverified')
    assert len(labels)<=128 and len(all_buttons)<=64, 'Calc close prompt exceeds observation bounds'
    uia=lifecycle.dialog_uia_identity(accessible,dialog,shell_pid)
    assert shell_pid>0 and api.pid(dialog)==shell_pid and api.user.IsWindow(dialog)
    assert api.title(dialog)=='OpenGeul Calc' and api.class_name(dialog)=='#32770', 'Unexpected Calc prompt identity'
    if '변경 내용을 저장하시겠습니까?' not in labels:
        evidence['readiness']='heading-not-ready'
        return None
    expected=('저장','저장하지 않음','취소')
    buttons=[];nonclient=[]
    for item,row in zip(all_buttons,rows):
        if not(row['visible'] and row['enabled']):continue
        path=lifecycle.require_dialog_button_ancestry(api,accessible,item,shell_pid,dialog)
        row['ancestry']=path
        if item.element_info.name in expected:
            assert path and path[0]['nativeHandle']>0 and not any(p['controlType']=='TitleBar' for p in path), 'Calc choice is not an owned client button'
            row['role']='client-choice';buttons.append(item)
        else:
            evidence['readiness']='unexpected-or-duplicate-button'
            role_path=path
            if [p['controlType'] for p in path]==['Button','Window']:
                role_path=_raw_titlebar_path(item,accessible,shell_pid,dialog)
                row['rawAncestry']=role_path
            _require_native_titlebar_close(item,role_path,dialog)
            row['role']='native-titlebar-close';nonclient.append(item)
            assert len(nonclient)==1, 'Duplicate Calc nonclient Close controls'
    names=[item.element_info.name for item in buttons]
    if len(names)!=len(set(names)):
        evidence['readiness']='unexpected-or-duplicate-button'
        raise AssertionError('Expected exact three-choice Calc prompt')
    if sorted(names)!=sorted(expected):
        evidence['readiness']='choices-not-ready'
        return None
    evidence.update(ready=True,readiness="ready",uia=uia,nonclientCloseCount=len(nonclient))
    return buttons


def _close_calc_prompt(api,process,hwnd,child,record,verify_authorization,evidence,evidence_key):
    """One owned WM_CLOSE, exact Suite prompt, one explicit physical Discard."""
    from pywinauto import Desktop
    import lifecycle_smoke as lifecycle
    import windows_smoke as native

    def owned_editor():
        assert process.poll() is None and type(process.pid) is int and process.pid>0
        assert record.get('module')=='calc' and record.get('shellPid')==process.pid
        assert record.get('windowHwnd')==hwnd and record.get('childHwnd')==child
        assert api.user.IsWindow(hwnd) and api.user.IsWindow(child)
        assert api.pid(hwnd)==process.pid and api.pid(child)>0 and api.pid(child)!=process.pid
        assert api.user.IsChild(hwnd,child), 'Calc editor is outside the tested Suite form'

    verify_authorization();owned_editor()
    prompt_deadline=time.monotonic()+20
    def remaining():
        seconds=prompt_deadline-time.monotonic()
        assert seconds>0, 'Original Calc close-prompt deadline expired'
        return seconds
    record['stage']='close-verified-generated-calc'
    api.request_close(hwnd,process.pid)
    evidence.update(closeMessageCount=1,discardClickCount=0)
    record[evidence_key]=evidence

    def find_prompt():
        owned_editor()
        matches=[handle for handle in api.windows(process.pid) if api.user.GetWindow(handle,4)==hwnd]
        assert len(matches)<=1, 'Calc close prompt is ambiguous'
        if not matches:return None
        dialog=matches[0]
        native.require_dialog_identity(api.pid(dialog),process.pid,api.user.GetWindow(dialog,4),hwnd,
                                       api.title(dialog),'OpenGeul Calc',api.class_name(dialog))
        return dialog

    dialog=native.wait_for(find_prompt,seconds=remaining())
    accessible=Desktop(backend='uia').window(handle=dialog).wrapper_object()

    def verify_prompt():
        owned_editor();verify_authorization()
        native.require_dialog_identity(api.pid(dialog),process.pid,api.user.GetWindow(dialog,4),hwnd,
                                       api.title(dialog),'OpenGeul Calc',api.class_name(dialog))
        observed={}
        evidence['promptObservationCount']=evidence.get('promptObservationCount',0)+1
        observations=evidence.setdefault('promptObservations',[])
        if len(observations)<24:observations.append(observed)
        evidence['lastPromptObservation']=observed
        buttons=require_calc_prompt_buttons(api,accessible,process.pid,dialog,observed)
        if buttons is None:return None
        button=next(item for item in buttons if item.element_info.name=='저장하지 않음')
        ancestry=[]
        lifecycle.require_dialog_button_ancestry(api,accessible,button,process.pid,dialog,ancestry)
        evidence.update(dialogHwnd=int(dialog),ownerHwnd=int(hwnd),shellPid=process.pid,
                        title=api.title(dialog),button='저장하지 않음',buttonAncestry=ancestry,
                        uia=observed['uia'],nonclientCloseCount=observed['nonclientCloseCount'])
        return button

    native.wait_for(verify_prompt,seconds=remaining())
    Desktop(backend='win32').window(handle=dialog).wrapper_object().set_focus()
    api.require_foreground(dialog)
    button=native.wait_for(verify_prompt,seconds=remaining())
    remaining()  # A slow UIA read must not authorize a late physical click.
    button.click_input();evidence['discardClickCount']=1
    native.wait_for(lambda:not api.user.IsWindow(dialog),seconds=20)
    native.wait_for(lambda:not api.user.IsWindow(hwnd),seconds=20)
    native.wait_for(lambda:not api.user.IsWindow(child),seconds=10)
