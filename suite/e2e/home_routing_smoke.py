"""Physical Home tiles and native Open dialogs on owned generated fixtures only.

This additive finite harness preserves the original thirteen GUI cases. Native
input and fresh owned cleanup are required; engine-only fixtures are not GUI
evidence and no upstream Office feature certification is implied.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes as W
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import sys
import time
import traceback

sys.path.insert(0,str(Path(__file__).resolve().parent))
import windows_smoke as native
import lifecycle_smoke as lifecycle
import office_feature_smoke as features

OPEN_CAPTION='OpenGeul Office에서 문서 열기'
OFFICE_MODULES=('writer','calc','impress','draw','math','base')
OPEN_ROUTES=tuple((module,extension) for module,extension,_ in features.FORMATS)+(('hwp','hwp'),('hwp','hwpx'))


def build_plan():
    return ([dict(case='tile-'+module,kind='tile',module=module) for module in OFFICE_MODULES]+
        [dict(case='home-open-cancel',kind='cancel')]+
        [dict(case='home-open-'+module+'-'+extension,kind='open',module=module,extension=extension) for module,extension in OPEN_ROUTES]+
        [dict(case='document-file-open',kind='shared-open',module='writer',extension='docx')])


def _unlinked(path):
    for item in (path,*path.parents):
        assert not item.is_symlink() and not getattr(item,'is_junction',lambda:False)(), 'Home route paths must not be linked'


def owned_target(folder,name):
    folder=Path(folder);_unlinked(folder)
    assert folder.is_dir() and Path(name).name==name and '/' not in name and '\\' not in name
    names={f'format-{m}-{e}.{e}' for m,e in OPEN_ROUTES if m!='hwp'}|{'route-hwp.hwp','route-hwpx.hwpx'}
    assert name in names, 'Only fixed generated route filenames are allowed'
    target=folder/name;_unlinked(target)
    assert not target.exists(), 'Never overwrite a Home routing fixture'
    target=target.resolve();assert target.parent==folder.resolve()
    return target


def load_feature_inputs(suite,root):
    suite,root=Path(suite),Path(root);_unlinked(suite);_unlinked(root)
    suite,root=suite.resolve(),root.resolve()
    assert root!=suite and suite not in root.parents
    report_path=root/'office-features.json';_unlinked(report_path)
    raw=report_path.read_bytes();assert 0<len(raw)<=16*1024*1024
    report=json.loads(raw)
    assert report.get('schemaVersion')==1 and report.get('kind')=='office-engine-features' and report.get('passed') is True
    assert Path(report['suite']).resolve()==suite, 'Feature baseline belongs to another Suite'
    assert features.summarize(report['cases'],suite)['passed'] is True, 'All canonical21 feature cases must pass'
    specs=features.case_specs();admitted={}
    for row,spec in zip(report['cases'],specs):
        assert (row['case'],row['module'],row['extension'],row['filter'])==(spec['id'],spec['module'],spec['extension'],spec['filter'])
        path=root/'fixtures'/(spec['id']+'.'+spec['extension']);_unlinked(path)
        assert path.is_file() and Path(row['fixture']).resolve()==path.resolve()
        data=path.read_bytes();assert len(data)==row['bytes'] and hashlib.sha256(data).hexdigest()==row['sha256'], 'Feature bytes changed after their passed baseline'
        features.validate_observation(spec,row['observed'],phase='independent-reopen')
        cleanups=row['engineCleanups'];assert [r['phase'] for r in cleanups]==['create','independent-reopen']
        for cleanup in cleanups:
            proof=cleanup['evidence'];assert Path(proof['expectedEngineImage']).resolve()==suite/'Office/program/soffice.bin'
            features.baseline.validate_cleanup_evidence(proof)
        if spec['kind']=='format':
            admitted[(spec['module'],spec['extension'])]=dict(case=spec['id'],module=spec['module'],extension=spec['extension'],
                source=str(path.resolve()),sha256=row['sha256'],bytes=row['bytes'],featuresRoot=str(root),
                featureReportSha256=hashlib.sha256(raw).hexdigest(),featureRecord=row)
    assert set(admitted)==set(OPEN_ROUTES)-{('hwp','hwp'),('hwp','hwpx')}
    return admitted


def require_home_action(evidence,module):
    assert module in OFFICE_MODULES or module=='open'
    shell,home=evidence['shellPid'],evidence['homeHwnd']
    assert type(shell) is int and shell>0 and type(home) is int and home>0
    owner=evidence['home'];foreground=evidence['foreground']
    assert owner['hwnd']==owner['rootHwnd']==home and owner['pid']==shell and owner['isWindow'] is True and owner['threadId']>0
    assert foreground['isWindow'] is True and foreground['pid']==shell and foreground['rootHwnd']==home
    candidates=evidence['candidates'];assert isinstance(candidates,list) and len(candidates)==1
    row=candidates[0];expected='파일 열기…' if module=='open' else 'OpenGeul '+module.title()
    assert row['name']==expected and row['pid']==shell and row['runtimeId']
    assert row['nativeHwnd']>0 and row['nativeLive'] is True and row['nativeRoot']==home
    assert row['enabled'] is True and row['visible'] is True and type(evidence['clicks']) is int and evidence['clicks']==1
    return evidence


def click_home_action(api,process,home,module,record):
    from pywinauto import Desktop
    from pywinauto.uia_defines import IUIA
    from pywinauto.uia_element_info import UIAElementInfo
    from pywinauto.controls.uiawrapper import UIAWrapper
    evidence=dict(homeHwnd=home,shellPid=process.pid,module=module,startedAt=time.monotonic(),clicks=0,candidates=[],apiError=None,success=False)
    record.setdefault('homeActions',[]).append(evidence)
    operation='owned Home focus'
    def call(name,function):
        nonlocal operation
        operation=name;return function()
    try:
        assert process.poll() is None
        Desktop(backend='win32').window(handle=home).wrapper_object().set_focus()
        native.wait_for(lambda:api.user.GetAncestor(api.user.GetForegroundWindow(),2)==home,10)
        api.require_foreground(home)
        evidence.update(home=api._focus_window(home),foreground=api._focus_window(api.user.GetForegroundWindow()))
        accessible=Desktop(backend='uia').window(handle=home).wrapper_object();root=accessible.element_info._element;uia=IUIA()
        raw=call('FindAll owned Home Buttons',lambda:root.FindAll(4,uia.build_condition(control_type='Button')))
        count=int(call('Home Button array Length',lambda:raw.Length));evidence['rawCount']=count
        assert 0<=count<=32, 'Home button census exceeds its bounded surface'
        expected='파일 열기…' if module=='open' else 'OpenGeul '+module.title();elements=[]
        for index in range(count):
            element=call('Home Button GetElement',lambda:raw.GetElement(index))
            name=call('Home Button CurrentName',lambda:str(element.CurrentName))
            if name!=expected:continue
            row=dict(name=name,index=index);evidence['candidates'].append(row)
            native._base_raw_properties(element,call,row)
            handle=row['nativeHwnd'];row.update(visible=not row['offscreen'],nativeRoot=int(api.user.GetAncestor(handle,2) or 0),nativeLive=bool(api.user.IsWindow(handle)))
            assert handle>0 and api.user.IsChild(home,handle) and api.pid(handle)==process.pid
            elements.append(element)
        evidence['clicks']=1
        require_home_action(evidence,module)
        element,=elements
        wrapper=call('Home raw element wrapper',lambda:UIAWrapper(UIAElementInfo(element)))
        properties=native._base_raw_properties(wrapper.element_info._element,call)
        assert properties=={key:evidence['candidates'][0][key] for key in properties}, 'Home wrapper identity changed'
        evidence['rawElementEquals']=bool(call('Home CompareElements',lambda:uia.iuia.CompareElements(wrapper.element_info._element,element)))
        assert evidence['rawElementEquals'] is True
        api.require_foreground(home);require_home_action(evidence,module)
        evidence['clickStartedAt']=time.monotonic();wrapper.click_input();evidence.update(success=True,finishedAt=time.monotonic())
        return evidence
    except Exception as exc:
        evidence.update(apiError=native._base_api_error(operation,exc),finishedAt=time.monotonic())
        raise


def require_open_dialog_readiness(proof,shell_pid,home,*,before_input=False):
    """Raw native/UIA replay; Home remains the owner for document-menu callbacks."""
    assert type(before_input) is bool and type(proof['schemaVersion']) is int and proof['schemaVersion']==1
    assert proof['kind']=='owned-open-dialog-readiness' and proof['caption']==OPEN_CAPTION
    assert (proof['shellPid'],proof['documentHwnd'])==(shell_pid,home)
    assert proof['trigger']['kind'] in ('home-button','document-menu') and proof['trigger']['clicks']==1
    assert 'saveShortcuts' not in proof and 'fileMenuClicks' not in proof
    assert proof['budgetSeconds']==20 and proof['maxObservations']==201 and proof['ready'] is True
    start,deadline,finish=(native._base_time(proof[k]) for k in ('startedAt','deadline','finishedAt'))
    assert deadline==start+20 and start<=finish<=deadline
    dialog=native._base_int(proof['dialogHwnd'],positive=True);root=native._base_runtime_id(proof['uiaRootRuntimeId'])
    focus=proof['focusAction'];assert focus['dialogHwnd']==dialog and focus['count']==1 and start<=focus['at']<=finish
    observations=proof['observations'];assert isinstance(observations,list) and 1<=len(observations)<=201
    previous=start;bound=False
    for index,row in enumerate(observations):
        began,ended=(native._base_time(row[k]) for k in ('startedAt','finishedAt'))
        assert previous<=began<=ended<=finish and row['sequence']==index;previous=ended
        assert row['shellProcessPoll']==dict(pid=shell_pid,exitCode=None)
        native._base_native_continuity(proof['nativeAnchor'],row)
        if row['dialogMatches']:bound=True;assert focus['at']<=began
        state=native._base_save_observation_state(row,shell_pid,home,OPEN_CAPTION,dialog if bound else 0,root)
        assert row['state']==state and (state=='ready') is (index==len(observations)-1)
    bindings=proof['wrapperBindings'];assert len(bindings)==2 and proof['bindingError'] is None
    for binding,key in zip(bindings,(('1001',50004),('1',50000))):
        row=observations[-1]['controls'][native._base_int(binding['sourceIndex'])]
        assert (row['automationId'],row['controlType'])==key and binding['rawElementEquals'] is True
        properties=binding['properties'];assert set(properties)=={'runtimeId','automationId','controlType','pid','nativeHwnd','nativeHwndRaw','enabled','offscreen'}
        assert properties=={key:row[key] for key in properties}
    if not before_input or 'actionStartedAt' in proof:
        assert proof.get('action') in ('open','cancel') and native._base_time(proof.get('actionStartedAt'))>=finish
    return proof


def wait_open_dialog(api,process,home,record):
    return native._wait_base_save_controls(api,process,home,OPEN_CAPTION,record,open_dialog=True)


def new_attachment(api,process,module,previous,source):
    assert process.poll() is None
    assert all(api.user.IsWindow(handle) and api.pid(handle)==process.pid for handle in previous), 'An earlier retained document disappeared during Open'
    api.attached(process)  # Preserve the existing owned startup-error detector.
    candidates=[]
    for hwnd in api.windows(process.pid):
        parent=api.user.GetPropW(hwnd,'OpenGeul.Office.ParentHwnd');child=api.user.GetPropW(hwnd,'OpenGeul.Office.ChildHwnd')
        if hwnd not in previous and parent and child:candidates.append((int(hwnd),int(parent),int(child)))
    assert len(candidates)<=1, 'Open created multiple new document HWNDs'
    if not candidates:return None
    hwnd,parent,child=candidates[0]
    assert all(api.user.IsWindow(h) for h in (hwnd,parent,child)) and api.pid(hwnd)==process.pid
    assert api.user.IsChild(hwnd,parent) and api.user.IsChild(parent,child)
    if not api.user.IsWindowVisible(child):return None
    caption=api.title(hwnd);assert 'OpenGeul '+module.title() in caption
    if source is not None:assert source.name in caption, 'New document title differs from the selected owned fixture'
    pid=api.pid(child);assert pid>0 and pid!=process.pid
    assert not api.windows(pid), 'Office created a visible unowned top-level window'
    return dict(hwnd=hwnd,parent=parent,child=child,officePid=pid)


def shell_menu_action(api,process,document,label,record):
    from pywinauto import Desktop
    assert label in ('열기…','닫기')
    evidence=dict(documentHwnd=document,shellPid=process.pid,label=label,fileClicks=0,actionClicks=0,success=False)
    record.setdefault('shellMenuActions',[]).append(evidence)
    assert process.poll() is None and api.user.IsWindow(document) and api.pid(document)==process.pid
    Desktop(backend='win32').window(handle=document).wrapper_object().set_focus();api.require_foreground(document)
    shell=Desktop(backend='uia').window(handle=document).wrapper_object()
    files=[item for item in shell.descendants(control_type='MenuItem') if item.element_info.name=='파일'
        and item.element_info.process_id==process.pid and item.is_visible() and item.is_enabled()]
    assert len(files)==1
    evidence['fileRuntimeId']=list(files[0].element_info.runtime_id);assert evidence['fileRuntimeId']
    evidence['fileClicks']=1;files[0].click_input();api.require_foreground(document)
    choices=lifecycle.owned_menu_items(Desktop(backend='uia'),process.pid,label);assert len(choices)==1
    choice,=choices;evidence['actionRuntimeId']=list(choice.element_info.runtime_id)
    # The ToolStrip dropdown is a separate same-process window; native foreground
    # must still belong to this exact retained document before the action.
    api.require_foreground(document);evidence['actionClicks']=1;choice.click_input();evidence['success']=True
    return evidence


def _open_button_recheck(api,accessible,button,process,dialog,proof):
    properties=native._base_raw_properties(button.element_info._element,lambda name,call:call())
    assert properties==proof['wrapperBindings'][1]['properties'], 'Open button identity/readiness changed before input'
    return lifecycle.require_dialog_button_ancestry(api,accessible,button,process.pid,dialog)


def open_dialog_action(api,process,home,record,path=None,*,document=None):
    from pywinauto import Desktop
    from pywinauto.keyboard import send_keys
    operation=dict(openButtonClicks=0,cancelEscapeCount=0,success=False)
    record.setdefault('openDialogs',[]).append(operation)
    if document is None:
        click_home_action(api,process,home,'open',record);trigger='home-button'
    else:
        shell_menu_action(api,process,document,'열기…',record);trigger='document-menu'
    operation['openTrigger']=dict(kind=trigger,clicks=1)
    dialog,window,filename,button=wait_open_dialog(api,process,home,operation)
    proof=operation['openDialogReadiness'];require_open_dialog_readiness(proof,process.pid,home,before_input=True)
    def owned():
        assert process.poll() is None
        native.require_dialog_identity(api.pid(dialog),process.pid,api.user.GetWindow(dialog,4),home,api.title(dialog),OPEN_CAPTION,api.class_name(dialog))
        api.require_foreground(dialog)
    owned();proof.update(action='cancel' if path is None else 'open',actionStartedAt=time.monotonic())
    require_open_dialog_readiness(proof,process.pid,home)
    if path is None:
        operation['cancelEscapeCount']=1;send_keys('{ESC}',pause=.1)
    else:
        path=Path(path);_unlinked(path);assert path.is_file()
        accessible=Desktop(backend='uia').window(handle=dialog).wrapper_object()
        lifecycle.set_owned_picker_filename(api,process.pid,home,dialog,accessible,filename,str(path),operation,expected_title=OPEN_CAPTION)
        owned();operation['openButtonAncestry']=_open_button_recheck(api,accessible,button,process,dialog,proof)
        operation['openButtonClicks']=1;button.click_input()
    native.wait_for(lambda:not api.user.IsWindow(dialog),seconds=20)
    operation['success']=True
    return operation


def verify_native_archives(suite,root,records):
    """Replay every product archive, joined to our retained native generation."""
    from native_cleanup_receipt import MAX_RECEIPT_BYTES,load_cleanup_receipt,validate_cleanup_receipt
    root=Path(root);_unlinked(root);assert root.is_dir()
    expected_image=str(Path(suite)/'Office/program/soffice.bin');expected={}
    for record in records:
        for frame in record.get('attachments',[]):
            key=(frame['officePid'],frame['officeCreationTime'])
            assert key not in expected and PureWindowsPath(frame['officeImage'])==PureWindowsPath(expected_image)
            expected[key]=record['case']
    manifests=sorted(root.glob('*/*/manifest.json'));seen_generations=set();verified_files=0;proofs=[]
    for path in root.rglob('*'):
        _unlinked(path)
        if path.is_file():
            with path.open('rb') as stream:signature=stream.read(4)
            assert path.suffix.lower() not in ('.dmp','.mdmp') and signature!=b'MDMP', 'Native crash dump found'
    assert len(manifests)==len(expected), 'Missing or unexpected product native archives'
    for manifest_path in manifests:
        raw=manifest_path.read_bytes();assert 0<len(raw)<=1024*1024
        manifest=json.loads(raw)
        assert type(manifest.get('schemaVersion')) is int and manifest['schemaVersion']==1
        assert manifest.get('kind')=='owned-office-native-diagnostics' and manifest.get('archiveComplete') is True
        assert isinstance(manifest.get('files'),list);seen=set()
        for row in manifest['files']:
            name=row['path'];relative=PurePosixPath(name)
            assert name and '\\' not in name and ':' not in name and not relative.is_absolute() and '..' not in relative.parts
            assert relative.as_posix()==name and name not in seen;seen.add(name)
            path=manifest_path.parent.joinpath(*relative.parts);_unlinked(path)
            assert path.is_file() and path.resolve().is_relative_to(manifest_path.parent.resolve())
            assert type(row['bytes']) is int and path.stat().st_size==row['bytes']
            assert re.fullmatch('[a-f0-9]{64}',row['sha256']) and hashlib.sha256(path.read_bytes()).hexdigest()==row['sha256']
            verified_files+=1
        actual={p.relative_to(manifest_path.parent).as_posix() for p in manifest_path.parent.rglob('*') if p.is_file()}
        # NativeDiagnostics.record writes this raw journal outside files[]. Its
        # shutdown proof remains manifest-hashed; arbitrary extras still fail.
        assert seen|{'manifest.json'}<=actual<=seen|{'manifest.json','events.jsonl'}, 'Unlisted product archive file'
        assert 'shutdown.json' in seen
        path=manifest_path.parent/'shutdown.json';assert 0<path.stat().st_size<=MAX_RECEIPT_BYTES
        cleanup=load_cleanup_receipt(path.read_bytes())
        validate_cleanup_receipt(cleanup,expected_engine_image=expected_image,launcher_pid=manifest['launcherPid'])
        engines=[row for row in cleanup['finalMembers'] if PureWindowsPath(row['image'])==PureWindowsPath(expected_image)]
        assert len(engines)==1
        engine,=engines;key=(engine['pid'],engine['creationTime'])
        assert key in expected and key not in seen_generations and expected[key]==manifest_path.parent.parent.name
        seen_generations.add(key)
        proofs.append(dict(case=expected[key],officePid=key[0],officeCreationTime=key[1],manifest=str(manifest_path),
            manifestSha256=hashlib.sha256(raw).hexdigest(),launcherPid=manifest['launcherPid'],shutdownSha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    assert seen_generations==set(expected)
    return dict(schemaVersion=1,kind='home-native-archive-integrity',success=True,completeArchives=len(manifests),
        qualifiedShutdowns=len(proofs),verifiedFiles=verified_files,crashDumps=0,archives=proofs)


def retained_exit(bound,evidence):
    """GetExit follows a signaled retained HANDLE; no timeout/exit atomicity claim."""
    evidence.update(pid=bound.pid,creationTime=bound.creation,handleValue=int(bound.handle),waitResult=int(bound.kernel.WaitForSingleObject(bound.handle,0)))
    assert evidence['waitResult']==0, 'Owned process is not yet signaled'
    image,created=lifecycle.process_identity(bound.kernel,bound.handle,evidence)
    assert created==bound.creation
    function=bound.kernel.GetExitCodeProcess;function.argtypes=(W.HANDLE,ctypes.POINTER(W.DWORD));function.restype=W.BOOL
    code=W.DWORD();getattr(ctypes,'set_last_error',lambda n:None)(0)
    evidence['getExitCodeProcessResult']=bool(function(bound.handle,ctypes.byref(code)))
    evidence['getExitCodeProcessLastError']=getattr(ctypes,'get_last_error',lambda:0)()
    evidence.update(exitCode=int(code.value),image=str(image))
    assert evidence['getExitCodeProcessResult'] is True and evidence['exitCode']==0, 'Owned process did not exit normally'
    return evidence


class HomeCase:
    def __init__(self,suite,output,spec,inputs,hwp_inputs,record):
        self.suite,self.output,self.record,self.inputs,self.hwp_inputs=suite,output,record,inputs,hwp_inputs
        self.folder=output/'fixtures'/spec['case'];self.folder.mkdir()
        self.diagnostics=output/'diagnostics'/spec['case'];self.diagnostics.mkdir()
        self.frames=[];self.hwp_bounds=[];self.process=None
        self.record.update(success=False,cleanClose=False,forcedCleanup=False,keyboardInputVerified=False,attachments=[],sourceCopies=[])

    def start(self):
        self.record['stage']='launch-owned-home'
        previous=os.environ.get('OPENGEUL_SUITE_DIAGNOSTICS')
        try:
            os.environ['OPENGEUL_SUITE_DIAGNOSTICS']=str(self.diagnostics)
            self.process=native.launch_suite([str(self.suite/'OpenGeul.Office.exe')],self.suite,self.output,self.record['case'])
        finally:
            if previous is None:os.environ.pop('OPENGEUL_SUITE_DIAGNOSTICS',None)
            else:os.environ['OPENGEUL_SUITE_DIAGNOSTICS']=previous
        self.api=lifecycle.LifecycleWindows();self.api.evidence_output=self.output;self.api.evidence_case=self.record['case']
        self.record.update(shellPid=self.process.pid,shellCommand=list(self.process.args),originalShell={})
        self.shell_creation=lifecycle.retained_writer_shell(self.process,self.suite,self.record['originalShell'])
        self.record['stage']='await-original-home'
        self.home=native.wait_for(lambda:self.api.home(self.process),30)
        assert self.api.document_windows(self.process)==[]
        self.record.update(homeHwnd=int(self.home),homeOnlyBeforeAction=list(self.api.windows(self.process.pid)))
        assert self.record['homeOnlyBeforeAction']==[self.home]

    def copy_input(self,module,extension):
        self.record['stage']='copy-owned-route-input'
        if module=='hwp':
            original=self.hwp_inputs[extension];name='route-'+extension+'.'+extension
            descriptor=dict(module=module,extension=extension,source=str(original),sha256=hashlib.sha256(original.read_bytes()).hexdigest(),bytes=original.stat().st_size)
        else:
            descriptor=self.inputs[(module,extension)];original=Path(descriptor['source']);name=f'format-{module}-{extension}.{extension}'
        _unlinked(original);data=original.read_bytes()
        assert len(data)==descriptor['bytes'] and hashlib.sha256(data).hexdigest()==descriptor['sha256']
        source=owned_target(self.folder,name)
        with source.open('xb') as stream:stream.write(data)
        self.record['sourceCopies'].append(dict(path=str(source),sourceInput=descriptor,sha256=descriptor['sha256']))
        if self.record['kind']=='open':self.record['sourceInput']=descriptor
        return source

    def screenshot(self,hwnd,label):
        from pywinauto import Desktop
        window=Desktop(backend='win32').window(handle=hwnd).wrapper_object()
        window.set_focus();self.api.require_foreground(hwnd)
        name=self.record['case']+'-'+label+'.png';window.capture_as_image().save(self.output/name)
        self.record.setdefault('screenshots',[]).append(name)

    def attach(self,module,source):
        self.record['stage']='await-new-'+module+'-attachment'
        previous={frame['hwnd'] for frame in self.frames if not frame.get('closed')}
        attachment=native.wait_for(lambda:new_attachment(self.api,self.process,module,previous,source),150)
        bound=lifecycle.BoundHwpProcess(attachment['officePid'],self.suite/'Office/program/soffice.bin')
        frame=dict(attachment,module=module,source=source,bound=bound,closed=False)
        self.frames.append(frame)
        row=dict(attachment,module=module,file=str(source) if source else None,officeCreationTime=bound.creation,officeImage=str(self.suite/'Office/program/soffice.bin'))
        self.record['attachments'].append(row);frame['receipt']=row
        self.record.update(windowHwnd=attachment['hwnd'],parentHwnd=attachment['parent'],childHwnd=attachment['child'],officePid=attachment['officePid'])
        self.screenshot(attachment['hwnd'],module+'-attached')
        if module=='base' and source is None:
            native.save_new_base(self.api,self.process,attachment['hwnd'],self.folder,self.output,self.record)
            native.require_base_save_dialog_readiness(self.record['baseSaveDialogReadiness'],self.process.pid,attachment['hwnd'],'OpenGeul Base — 다른 이름으로 저장')
        return frame

    def close_frame(self,frame,*,menu=False):
        self.record['stage']='close-owned-'+frame['module']
        row=dict(hwnd=frame['hwnd'],module=frame['module'],menuCloseClicks=0,closeMessageCount=0,success=False)
        self.record.setdefault('frameCloses',[]).append(row)
        assert not self.api.windows(frame['officePid']), 'Office exposed an unowned visible window before close'
        if frame['module']=='calc':
            assert not menu
            from home_calc_close import observe_home_calc,freeze_home_calc_close,close_home_calc
            attachment={key:frame[key] for key in ('hwnd','parent','child','officePid')}
            self.record['stage']='observe-owned-home-calc'
            observe_home_calc(self.suite,self.output/(self.record['case']+'-calc-reader'),self.process,attachment,frame['source'],self.record.get('extension'),self.record)
            proof=freeze_home_calc_close(self.suite,self.process,frame['bound'],self.record,source=frame['source'],extension=self.record.get('extension'))
            close_home_calc(self.api,proof,self.record);row['closeMessageCount']=1
        else:
            assert self.api.user.IsWindow(frame['hwnd']) and frame['bound'].live()
            if menu:
                action=shell_menu_action(self.api,self.process,frame['hwnd'],'닫기',self.record)
                assert action['actionClicks']==1 and action['success'] is True;row['menuCloseClicks']=1
            else:
                row['closeMessageCount']=1;self.api.request_close(frame['hwnd'],self.process.pid)
            native.wait_for(lambda:not self.api.user.IsWindow(frame['hwnd']),20)
            native.wait_for(lambda:not self.api.user.IsWindow(frame['child']),10)
        native.wait_for(lambda:not frame['bound'].live(),20)
        retained_exit(frame['bound'],row.setdefault('exit',{}))
        frame['closed']=True;row['success']=True;frame['receipt']['closed']=True

    def writer_snapshot(self,frame,phase):
        self.record['stage']='observe-retained-writer-'+phase
        from home_calc_close import observe_home_model
        from writer_model_reader import WRITER_MODEL_SERVICE,WRITER_GETTER_CONTRACT
        def clean(value):assert value.get('isModified') is False
        key='sharedWriter'+phase.title()
        attachment={name:frame[name] for name in ('hwnd','parent','child','officePid')}
        context=observe_home_model(self.suite,self.output/(self.record['case']+'-writer-'+phase),self.process,
            attachment,frame['source'],self.record,key,WRITER_MODEL_SERVICE,WRITER_GETTER_CONTRACT,clean)
        assert frame['bound'].live() and frame['bound'].creation==context['observation']['bindingBefore']['officeCreationTime']
        value=dict(source=str(frame['source']),sha256=hashlib.sha256(frame['source'].read_bytes()).hexdigest())
        self.record.setdefault('sharedWriterFiles',{})[phase]=value
        return dict(value,context=context)

    @staticmethod
    def require_shared_unchanged(before,after):
        assert before['source']==after['source'] and before['sha256']==after['sha256']
        a,b=(value['context']['observation'] for value in (before,after))
        assert a['bodyText']==b['bodyText'] and a['isModified'] is b['isModified'] is False
        keys=('shellPid','shellCreationTime','officePid','officeCreationTime','expectedImage','suiteHwnd','parentHwnd','childHwnd','documentUrl')
        assert all(a['bindingBefore'][key]==b['bindingBefore'][key] for key in keys)
        for origin in ('controllerBefore','helperBefore'):
            left,right=(value['nativeSnapshots'][origin] for value in (a,b))
            assert left['officeCommandLine']==right['officeCommandLine'] and left['profileUrl']==right['profileUrl']
            assert left['profileDirectory']['witness']['canonicalPath']==right['profileDirectory']['witness']['canonicalPath']
            li,ri=(value['profileDirectory']['witness']['openedInfo'] for value in (left,right))
            assert all(li[key]==ri[key] for key in ('volumeSerialNumber','fileIndexHigh','fileIndexLow'))

    def hwp(self,path):
        self.record['stage']='await-owned-hwp-route'
        from pywinauto import Desktop
        executable=self.suite/'HWP/OpenGeul.exe';assert executable.is_file()
        def child():
            assert self.process.poll() is None
            censuses=self.record.setdefault('hwpNativeCensus',[]);assert len(censuses)<451
            evidence={};censuses.append(evidence)
            return lifecycle._hwp_child_process(self.process.pid,executable,shell_creation=self.shell_creation,evidence=evidence)
        matched=native.wait_for(child,45)
        bound=lifecycle.BoundHwpProcess(matched['pid'],executable,expected_creation=matched['creationFileTime']);self.hwp_bounds.append(bound)
        trace=self.output/(self.record['case']+'-hwp-readiness.jsonl');signatures=set()
        def ready():
            assert bound.live()
            roots=[h for h in self.api.windows(bound.pid) if self.api.class_name(h) in ('Tauri Window','Chrome_WidgetWin_1')]
            assert len(roots)<=1
            if not roots:return None
            hwnd,=roots
            tree=Desktop(backend='win32').window(handle=hwnd).wrapper_object()
            webviews=[int(item.handle) for item in tree.descendants() if item.class_name() in ('Chrome_WidgetWin_0','Chrome_WidgetWin_1','Chrome_RenderWidgetHostHWND')]
            if not webviews:return None
            rows=lifecycle.hwp_accessibility_snapshot(Desktop(backend='uia').window(handle=hwnd).wrapper_object())
            serialized=json.dumps(rows,ensure_ascii=False,sort_keys=True,allow_nan=False);signature=hashlib.sha256(serialized.encode()).hexdigest()
            if signature not in signatures:
                assert len(signatures)<128;signatures.add(signature)
                with trace.open('a',encoding='utf-8') as stream:stream.write(json.dumps(dict(sequence=len(signatures),hwnd=hwnd,pid=bound.pid,rows=rows),ensure_ascii=False,allow_nan=False)+'\n')
            if not any(path.name in name for name in [self.api.title(hwnd)]+[row['name'] for row in rows]):return None
            controls=lifecycle.hwp_postload_observation(rows)
            if controls is None:return None
            self.record['hwpReadiness']=dict(hwnd=hwnd,pid=bound.pid,creationFileTime=bound.creation,filenameObserved=True,webviewHwnds=webviews,postload=controls,trace=trace.name)
            return hwnd
        hwnd=native.wait_for(ready,75);self.screenshot(hwnd,'hwp-attached')
        assert self.api.document_windows(self.process)==[]
        self.api.request_close(hwnd,bound.pid);self.record['hwpCloseMessageCount']=1
        native.wait_for(lambda:not self.api.user.IsWindow(hwnd),25);native.wait_for(lambda:not bound.live(),25)
        retained_exit(bound,self.record.setdefault('hwpExit',{}))

    def execute(self):
        spec=self.record;kind=spec['kind']
        if kind=='tile':
            click_home_action(self.api,self.process,self.home,spec['module'],spec)
            self.close_frame(self.attach(spec['module'],None))
        elif kind=='cancel':
            open_dialog_action(self.api,self.process,self.home,spec)
            assert self.api.document_windows(self.process)==[]
            spec['cancelPreservedHomeOnly']=True
        elif kind=='open':
            path=self.copy_input(spec['module'],spec['extension'])
            open_dialog_action(self.api,self.process,self.home,spec,path)
            if spec['module']=='hwp':self.hwp(path)
            else:self.close_frame(self.attach(spec['module'],path))
        else:
            assert kind=='shared-open'
            first_path=self.copy_input('writer','docx');open_dialog_action(self.api,self.process,self.home,spec,first_path)
            first=self.attach('writer',first_path);before=self.writer_snapshot(first,'before')
            second_path=self.copy_input('impress','pptx')
            open_dialog_action(self.api,self.process,self.home,spec,second_path,document=first['hwnd'])
            second=self.attach('impress',second_path);after=self.writer_snapshot(first,'after')
            self.require_shared_unchanged(before,after);spec['firstDocumentPreserved']=True
            self.close_frame(second,menu=True);self.close_frame(first)
        self.finish()

    def finish(self):
        for item in self.record['sourceCopies']:
            descriptor=item['sourceInput']
            for path in (Path(item['path']),Path(descriptor['source'])):
                _unlinked(path);data=path.read_bytes()
                assert len(data)==descriptor['bytes'] and hashlib.sha256(data).hexdigest()==item['sha256'], 'A route fixture changed without any content input'
        assert all(frame['closed'] for frame in self.frames)
        assert self.api.document_windows(self.process)==[] and self.process.poll() is None
        self.screenshot(self.home,'home-after');native.close_home(self.api,self.process,self.record)
        self.record.update(shellExitCode=self.process.returncode,cleanClose=True,stage='complete')

    def run(self):
        try:
            self.start();self.execute();self.record['success']=True
        except BaseException as exc:native.capture_failure(self.output,self.record['case'],self.record,exc)
        finally:
            for bound in [frame['bound'] for frame in self.frames]+self.hwp_bounds:
                try:
                    if bound.live():
                        self.record.update(success=False,forcedCleanup=True);bound.stop()
                except BaseException as exc:
                    self.record['success']=False;self.record.setdefault('cleanupErrors',[]).append(type(exc).__name__+': '+str(exc))
                finally:
                    if bound.handle:
                        handle=int(bound.handle);closed=bool(bound.kernel.CloseHandle(bound.handle));bound.handle=None
                        row=dict(pid=bound.pid,creationTime=bound.creation,handleValue=handle,closeHandleResult=closed,lastError=getattr(ctypes,'get_last_error',lambda:0)())
                        self.record.setdefault('retainedHandleClosures',[]).append(row)
                        if not closed:self.record['success']=False
            if self.process is not None:
                if self.process.poll() is None:self.record.update(success=False,forcedCleanup=True)
                native.stop_owned_test_process(self.process,self.record)
            native.write_result(self.output,self.record['case'],self.record)
        return self.record


def summarize(records):
    plan=build_plan();expected=[row['case'] for row in plan]
    actual=[row.get('case') for row in records]
    passed=[row for row in records if row.get('success') is True and row.get('cleanClose') is True and row.get('forcedCleanup') is False]
    success=actual==expected and len(passed)==len(plan)
    return dict(schemaVersion=1,kind='physical-home-routing',success=success,expectedCaseCount=len(plan),
        completedCaseCount=len(records),passedCaseCount=len(passed),cases=records,
        missingCases=[name for name in expected if name not in actual],duplicateCases=sorted({name for name in actual if actual.count(name)>1}),
        nativeOfficeFeatureCertification=False,universalFormatCompatibility=False)


def require_case_result(record,suite):
    """Replay fixed native actions, picker inputs and normal retained exits."""
    from types import SimpleNamespace
    spec,=[row for row in build_plan() if row['case']==record['case']]
    assert all(record.get(key)==value for key,value in spec.items())
    assert record['success'] is record['cleanClose'] is True and record['forcedCleanup'] is False
    assert type(record['shellExitCode']) is int and record['shellExitCode']==0
    assert record['shellCommand']==[str(Path(suite)/'OpenGeul.Office.exe')]
    assert record['keyboardInputVerified'] is False and not record.get('asciiEditorInputs')
    home,pid=record['homeHwnd'],record['shellPid'];assert record['homeOnlyBeforeAction']==[home]
    from writer_model_barrier import require_original_shell
    require_original_shell(record['originalShell'],dict(shellPid=pid,shellCreationTime=record['originalShell']['nativeCreation']['fileTime']),suite)
    actions=record.get('homeActions',[]);assert len(actions)==1
    module=spec['module'] if spec['kind']=='tile' else 'open'
    require_home_action(actions[0],module);assert actions[0]['success'] is actions[0]['rawElementEquals'] is True
    assert actions[0]['shellPid']==pid and actions[0]['homeHwnd']==home
    expected_opens=0 if spec['kind']=='tile' else 2 if spec['kind']=='shared-open' else 1
    operations=record.get('openDialogs',[]);assert len(operations)==expected_opens
    copies=record['sourceCopies'];expected_copies=2 if spec['kind']=='shared-open' else int(spec['kind']=='open')
    assert len(copies)==expected_copies
    formats=[('writer','docx'),('impress','pptx')] if spec['kind']=='shared-open' else [(spec['module'],spec['extension'])] if spec['kind']=='open' else []
    for item,(module,extension) in zip(copies,formats):
        descriptor=item['sourceInput'];assert (descriptor['module'],descriptor['extension'])==(module,extension)
        path=Path(item['path']);_unlinked(path)
        assert path.name==(f'route-{extension}.{extension}' if module=='hwp' else f'format-{module}-{extension}.{extension}')
        assert item['sha256']==descriptor['sha256']
        for location in (path,Path(descriptor['source'])):
            _unlinked(location);data=location.read_bytes()
            assert len(data)==descriptor['bytes'] and hashlib.sha256(data).hexdigest()==item['sha256']
        if module!='hwp':assert descriptor==load_feature_inputs(suite,Path(descriptor['featuresRoot']))[(module,extension)]
    for index,operation in enumerate(operations):
        proof=operation['openDialogReadiness'];require_open_dialog_readiness(proof,pid,home)
        assert proof['trigger']['kind']==('document-menu' if index==1 else 'home-button') and operation['success'] is True
        if spec['kind']=='cancel':
            assert proof['action']=='cancel' and operation['cancelEscapeCount']==1 and operation['openButtonClicks']==0
            assert not operation.get('pickerFilenameInputs') and record['cancelPreservedHomeOnly'] is True
        else:
            assert proof['action']=='open' and operation['openButtonClicks']==1 and operation['cancelEscapeCount']==0
            filename,=operation['pickerFilenameInputs'];assert filename['expected']==filename['after']==copies[index]['path']
            assert filename['dialog']['owner']==home and filename['dialog']['title']==OPEN_CAPTION
            lifecycle.require_picker_native_edit_receipt(filename,pid,proof['dialogHwnd'],filename['field']['nativeHandle'])
            assert operation['openButtonAncestry'][-1]['nativeHandle']==proof['dialogHwnd']
    modules=[] if spec['kind']=='cancel' or spec.get('module')=='hwp' else ['writer','impress'] if spec['kind']=='shared-open' else [spec['module']]
    frames=record['attachments'];assert [row['module'] for row in frames]==modules
    closes=record.get('frameCloses',[]);assert len(closes)==len(frames)
    closures=record.get('retainedHandleClosures',[]);assert len(closures)==len(frames)+int(spec.get('module')=='hwp')
    expected_image=Path(suite)/'Office/program/soffice.bin'
    for frame in frames:
        assert all(type(frame[key]) is int and frame[key]>0 for key in ('hwnd','officePid','officeCreationTime'))
        assert frame['closed'] is True and PureWindowsPath(frame['officeImage'])==PureWindowsPath(str(expected_image))
        close,=[row for row in closes if row['hwnd']==frame['hwnd']]
        assert close['module']==frame['module'] and close['success'] is True
        physical=spec['kind']=='shared-open' and frame['module']=='impress'
        assert (close['menuCloseClicks'],close['closeMessageCount'])==((1,0) if physical else (0,1))
        exit=close['exit'];assert (exit['pid'],exit['creationTime'])==(frame['officePid'],frame['officeCreationTime'])
        assert PureWindowsPath(exit['image'])==PureWindowsPath(str(expected_image))
        _require_exit_and_closure(exit,closures)
    menus=record.get('shellMenuActions',[])
    assert [row['label'] for row in menus]==(['열기…','닫기'] if spec['kind']=='shared-open' else [])
    assert all(row['fileClicks']==row['actionClicks']==1 and row['success'] is True for row in menus)
    if menus:
        assert [row['documentHwnd'] for row in menus]==[frames[0]['hwnd'],frames[1]['hwnd']]
    if spec.get('module')=='calc':
        from home_calc_close import require_calc_reader_context,_home_origin
        source=Path(copies[0]['path']) if copies else None
        binding=require_calc_reader_context(record['calcReader'],suite,source.as_uri() if source else '',spec.get('extension'))
        assert binding['shellCreationTime']==record['originalShell']['nativeCreation']['fileTime']
        frame,=frames;assert (binding['officePid'],binding['officeCreationTime'],binding['suiteHwnd'])==(frame['officePid'],frame['officeCreationTime'],frame['hwnd'])
        _home_origin(suite,SimpleNamespace(pid=pid,args=record['shellCommand']),record,source,spec.get('extension'))
        close=record['homeCalcClose'];assert close['closeMessageCount']==1 and close['frameClosed'] is True
        assert (close['branch'],close['discardClickCount']) in (('closed',0),('prompt',1))
    if spec['kind']=='tile' and spec['module']=='base':
        frame,=frames
        native.require_base_save_dialog_readiness(record['baseSaveDialogReadiness'],pid,frame['hwnd'],'OpenGeul Base — 다른 이름으로 저장')
        assert record['saveAsDialogVerified'] is True
    if spec.get('module')=='hwp':
        ready=record['hwpReadiness'];exit=record['hwpExit']
        assert ready['filenameObserved'] is True and ready['postload']['postLoadEditorVerified'] is ready['postload']['toolbarEnabled'] is True
        assert (exit['pid'],exit['creationTime'])==(ready['pid'],ready['creationFileTime'])
        assert PureWindowsPath(exit['image'])==PureWindowsPath(str(Path(suite)/'HWP/OpenGeul.exe'))
        matches=[lifecycle.require_hwp_census_receipt(row,pid,record['originalShell']['nativeCreation']['fileTime'],Path(suite)/'HWP/OpenGeul.exe') for row in record['hwpNativeCensus']]
        assert matches[-1]['pid']==exit['pid'] and matches[-1]['creationFileTime']==exit['creationTime']
        assert record['hwpCloseMessageCount']==1;_require_exit_and_closure(exit,closures)
    if spec['kind']=='shared-open':
        from home_calc_close import require_reader_context
        from writer_model_reader import WRITER_MODEL_SERVICE,WRITER_GETTER_CONTRACT
        values=[]
        for phase in ('before','after'):
            context=record['sharedWriter'+phase.title()]
            binding=require_reader_context(context,suite,Path(copies[0]['path']).as_uri(),WRITER_MODEL_SERVICE,WRITER_GETTER_CONTRACT)
            assert binding['shellCreationTime']==record['originalShell']['nativeCreation']['fileTime']
            assert context['success'] is True and (binding['suiteHwnd'],binding['officePid'],binding['officeCreationTime'])==(frames[0]['hwnd'],frames[0]['officePid'],frames[0]['officeCreationTime'])
            values.append(dict(record['sharedWriterFiles'][phase],context=context))
        HomeCase.require_shared_unchanged(*values);assert record['firstDocumentPreserved'] is True
        assert frames[0]['hwnd']!=frames[1]['hwnd']
    return record


def _require_exit_and_closure(exit,closures):
    assert exit['waitResult']==0 and exit['getExitCodeProcessResult'] is True and type(exit['exitCode']) is int and exit['exitCode']==0
    closure,=[row for row in closures if row['handleValue']==exit['handleValue']]
    assert (closure['pid'],closure['creationTime'])==(exit['pid'],exit['creationTime']) and closure['closeHandleResult'] is True


def run_home_cases(suite,output,inputs,hwp_inputs):
    records=[]
    for spec in build_plan():
        record=dict(spec,success=False,cleanClose=False,forcedCleanup=False)
        try:
            HomeCase(suite,output,spec,inputs,hwp_inputs,record).run()
            if record['success'] is True:require_case_result(record,suite)
        except BaseException as exc:native.capture_failure(output,spec['case'],record,exc)
        if record.get('success') is not True:record.setdefault('error','Case or strict cleanup failed')
        try:native.write_result(output,spec['case'],record)
        except BaseException as exc:record.update(success=False,recordWriteError=type(exc).__name__+': '+str(exc))
        records.append(record)
        print(spec['case']+': '+('passed' if record['success'] else 'FAILED: '+record.get('error','unknown')),flush=True)
    return records


def main():
    if not __debug__:raise RuntimeError('Home native assertions cannot run under Python -O')
    if os.name!='nt':raise RuntimeError('Actual Windows native GUI execution is required')
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('suite','features','hwp-fixtures','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    for path in (args.suite,args.features,args.hwp_fixtures,args.output):
        _unlinked(path);assert not str(path).startswith(('\\\\','//'))
    suite,feature_root,hwp_root,output=(path.resolve() for path in (args.suite,args.features,args.hwp_fixtures,args.output))
    assert all(output!=root and root not in output.parents and output not in root.parents for root in (suite,feature_root,hwp_root))
    output.mkdir(parents=True,exist_ok=False);(output/'fixtures').mkdir();(output/'diagnostics').mkdir()
    records=[];run_error=None;integrity=dict(schemaVersion=1,kind='home-native-archive-integrity',success=False)
    try:
        inputs=load_feature_inputs(suite,feature_root)
        from home_fixture_inputs import require_hwp_fixture_provenance
        raw=(hwp_root/'provenance.json').read_bytes();assert 0<len(raw)<=2*1024*1024
        proof=json.loads(raw);hwp_inputs=require_hwp_fixture_provenance(proof,suite,hwp_root)
        records=run_home_cases(suite,output,inputs,hwp_inputs)
        assert load_feature_inputs(suite,feature_root)==inputs
        require_hwp_fixture_provenance(proof,suite,hwp_root)
    except BaseException as exc:
        run_error=dict(error=type(exc).__name__+': '+str(exc),traceback=traceback.format_exc())
    try:
        integrity=verify_native_archives(suite,output/'diagnostics',records)
        assert sum(len(row.get('attachments',[])) for row in records)==23, 'All23 owned Office engine generations are required'
    except BaseException as exc:integrity.update(success=False,error=type(exc).__name__+': '+str(exc),traceback=traceback.format_exc())
    (output/'native-integrity.json').write_text(json.dumps(integrity,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    report=summarize(records);report.update(suite=str(suite),features=str(feature_root),hwpFixtures=str(hwp_root),nativeIntegrity=integrity)
    if run_error is not None:report['runError']=run_error
    report['success']=report['success'] and integrity['success'] is True and run_error is None
    (output/'home-routing.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    return 0 if report['success'] else 1


if __name__=='__main__':raise SystemExit(main())
