"""Read native Print hit only: immutable Source87 producer, separate controller.
No compile, Preferences physical input, print output, Store write or qualification.
"""
from __future__ import annotations
import base64
import ctypes
from ctypes import wintypes as W
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
PRODUCER_HEAD='859f676167b258a7a6a57ecdfcb0e224338de01a'
PRODUCER_RUN=38294374822
RELEASE_ID=410953892
ASSETS={
    'OpenGeul_1.1.3_windows-arm64_unsigned-portable.zip':
        (634832500,31341310,'eea23c6e3ae983cf36492a61c6fd82c123d20f035fc5b2201d9e65390b435d3a'),
    'OpenGeul_1.1.3.0_arm64_development-unsigned.msix':(634832499, 30936392, 'fd5af011629f4026a3c276d932d9453c38f1ac6d9d590163b03be81030ed2ace'),
    'provenance-arm64.json':
        (634832579,47591,'02a71988faae0d68bf9d3041cb2f160d94dbae1961fa224e8e4f3f2d621825f3'),
}
EDITOR_SHA='820d587135c550d3b82e8824bafd171eb0d02eac21ecf3d395c04c4a7ca610ff'
CLI_SHA='f2263a768c97749748d9200e350e8f7d2778da0392bdd15f99b60143d12d3d26'
GUARD_SHA='e02dec2a511844bcfee58b64de46602e8518d156e5041b265af80b26fbd11841'
FIXTURE_SHA='cbe6b276d1d6548036b4bfc1660126675cbe68d707a09964c64c7ff1952f0e76'
FIXTURE_B64='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'
OUT=ROOT/'native-hit-evidence'

def require(condition,message):
    if not condition:raise AssertionError(message)

def digest(path):
    value=hashlib.sha256()
    with path.open('rb') as stream:
        for part in iter(lambda:stream.read(1024*1024),b''):value.update(part)
    return value.hexdigest()

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def api_get(path):
    request=urllib.request.Request('https://api.github.com/repos/ATLKR/OpenGeul'+path,
        headers={'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'})
    request.add_unredirected_header('Authorization','Bearer '+os.environ['GH_TOKEN'])
    with urllib.request.build_opener(NoRedirect()).open(request,timeout=20) as response:
        raw=response.read(2*1024*1024+1)
    require(len(raw)<=2*1024*1024,'Official API response exceeds its bound')
    return json.loads(raw),hashlib.sha256(raw).hexdigest()

def prepare_runtime(work,report):
    release,release_sha=api_get('/releases/'+str(RELEASE_ID))
    run,run_sha=api_get('/actions/runs/'+str(PRODUCER_RUN))
    tag,tag_sha=api_get('/git/ref/tags/v1.1.3')
    require(release['id']==RELEASE_ID and release['tag_name']=='v1.1.3'
        and release['target_commitish']==PRODUCER_HEAD and release['draft'] is False
        and release['prerelease'] is False and len(release['assets'])==22,
        'Immutable formal producer release identity changed')
    require(run['id']==PRODUCER_RUN and run['run_attempt']==1 and run['head_sha']==PRODUCER_HEAD
        and run['head_branch']=='v1.1.3' and run['event']=='push'
        and run['status']=='completed' and run['conclusion']=='success','Source87 producer run is not successful')
    require(tag['object']['type']=='commit' and tag['object']['sha']==PRODUCER_HEAD,
        'Immutable producer tag identity changed')
    report['producer']={'head':PRODUCER_HEAD,'runId':PRODUCER_RUN,'attempt':1,
        'tag':'v1.1.3','releaseId':RELEASE_ID,'releaseAPIsha256':release_sha,
        'runAPIsha256':run_sha,'tagAPIsha256':tag_sha}
    package=work/'package';package.mkdir()
    for name,(asset_id,size,sha) in ASSETS.items():
        matches=[a for a in release['assets'] if a['name']==name]
        require(len(matches)==1,'Producer asset is not unique');asset=matches[0]
        require(asset['id']==asset_id and asset['size']==size and asset['digest']=='sha256:'+sha,
            'Producer asset ID, bytes or server digest changed')
        target=package/name
        with target.open('xb') as output:
            result=subprocess.run(['gh','api',f'repos/ATLKR/OpenGeul/releases/assets/{asset_id}',
                '-H','Accept: application/octet-stream'],stdout=output,stderr=subprocess.DEVNULL,timeout=90)
        require(result.returncode==0,'Public producer asset transport failed')
        require(target.stat().st_size==size and digest(target)==sha,'Downloaded producer bytes changed')
    provenance=json.loads((package/'provenance-arm64.json').read_bytes())
    require(provenance['repository']=='ATLKR/OpenGeul' and provenance['commit']==PRODUCER_HEAD
        and provenance['runId']==str(PRODUCER_RUN) and provenance['architecture']=='arm64'
        and provenance['version']=='1.1.3','Producer provenance changed')
    # This manifest belongs to a diagnostic subset, not to formal Source22.
    # The existing complete portable/MSIX byte-parity validator remains intact.
    subset=work/'verified-package-subset';subset.mkdir()
    names=[n for n in ASSETS if n.endswith(('.zip','.msix'))]
    for name in names:shutil.copyfile(package/name,subset/name)
    (subset/'SHA256SUMS.txt').write_text(''.join(ASSETS[n][2]+'  '+n+'\n' for n in sorted(names)),encoding='utf8')
    from prepare_payload import prepare
    runtime=work/'runtime';prepare(subset,runtime,'arm64')
    require(digest(runtime/'OpenGeul.exe')==EDITOR_SHA and digest(runtime/'Tools/rhwp.exe')==CLI_SHA,
        'Producer ARM runtime binary changed')
    report['producer'].update(editorSha256=EDITOR_SHA,cliSha256=CLI_SHA)
    return runtime

def inspect_hit(probe,dialog,button,point,hit):
    user=probe.user
    for name,args,result in [
        ('GetParent',[W.HWND],W.HWND),('IsChild',[W.HWND,W.HWND],W.BOOL),
        ('GetDlgCtrlID',[W.HWND],ctypes.c_int),('GetWindowRect',[W.HWND,ctypes.POINTER(W.RECT)],W.BOOL),
        ('ScreenToClient',[W.HWND,ctypes.POINTER(W.POINT)],W.BOOL),
        ('ClientToScreen',[W.HWND,ctypes.POINTER(W.POINT)],W.BOOL),
        ('GetDpiForWindow',[W.HWND],W.UINT),('GetThreadDpiAwarenessContext',[],W.HANDLE),
        ('GetAwarenessFromDpiAwarenessContext',[W.HANDLE],ctypes.c_int),
        ('LogicalToPhysicalPointForPerMonitorDPI',[W.HWND,ctypes.POINTER(W.POINT)],W.BOOL),
        ('RealChildWindowFromPoint',[W.HWND,W.POINT],W.HWND)]:
        fn=getattr(user,name);fn.argtypes=args;fn.restype=result
    allowed={'#32770','Button','Static','SysListView32','SHELLDLL_DefView','SysTabControl32',
        'Tauri Window','Chrome_WidgetWin_1','ConsoleWindowClass','CASCADIA_HOSTING_WINDOW_CLASS'}
    def window(hwnd):
        row=probe.window(hwnd)
        if row['cls'] not in allowed:
            row['classNameSha256']=hashlib.sha256(row['cls'].encode('utf8')).hexdigest();row['cls']='other'
        row['controlId']=int(user.GetDlgCtrlID(hwnd));rect=W.RECT()
        require(user.GetWindowRect(hwnd,ctypes.byref(rect)),'Native rectangle observation failed')
        row['nativeLTRB']=[rect.left,rect.top,rect.right,rect.bottom]
        row['dpi']=int(user.GetDpiForWindow(hwnd));return row
    parent=int(user.GetParent(button.handle) or 0);require(parent,'Preferences immediate parent is absent')
    chain=[];current=hit;seen=set()
    for _ in range(16):
        if not current:break
        require(current not in seen,'Native hit parent cycle')
        seen.add(current);chain.append(window(current));current=int(user.GetParent(current) or 0)
    else:raise AssertionError('Native hit parent chain exceeds its bound')
    client=W.POINT(*point);require(user.ScreenToClient(parent,ctypes.byref(client)),'Screen-to-parent transform failed')
    child=int(user.RealChildWindowFromPoint(parent,client) or 0)
    back=W.POINT(client.x,client.y);require(user.ClientToScreen(parent,ctypes.byref(back)),'Parent-to-screen transform failed')
    physical=W.POINT(*point)
    converted=bool(user.LogicalToPhysicalPointForPerMonitorDPI(button.handle,ctypes.byref(physical)))
    context=user.GetThreadDpiAwarenessContext();rect=button.rectangle()
    return {'point':list(point),'foreground':probe.foreground(),'hit':window(hit),
        'dialog':window(dialog.handle),'button':window(button.handle),'buttonParent':window(parent),
        'pywinautoButtonLTRB':[rect.left,rect.top,rect.right,rect.bottom],
        'hitParentChain':chain,'isHitChildOfExactButton':bool(user.IsChild(button.handle,hit)),
        'isHitChildOfExactDialog':bool(user.IsChild(dialog.handle,hit)),
        'parentClientPoint':[client.x,client.y],'roundtripScreenPoint':[back.x,back.y],
        'logicalToPhysicalConverted':converted,'physicalScreenPoint':[physical.x,physical.y],
        'threadDpiAwareness':int(user.GetAwarenessFromDpiAwarenessContext(context)),
        'realChildFromButtonParent':window(child) if child else None}

class DiagnosticInputPrevented(AssertionError):pass

class NoInputButton:
    def __init__(self,button):self.button=button
    def __getattr__(self,name):return getattr(self.button,name)
    def click_input(self,*args,**kwargs):
        raise DiagnosticInputPrevented('Physical Preferences input prevented')

class NoInputDialog:
    def __init__(self,dialog):self.dialog=dialog
    def __getattr__(self,name):return getattr(self.dialog,name)
    def descendants(self,**kwargs):
        return [NoInputButton(button) if button.class_name()=='Button' and button.control_id()==1010 else button
                for button in self.dialog.descendants(**kwargs)]

def observe(runtime,work,report):
    from contextlib import ExitStack
    from driver import Session
    from print_queue import VirtualQueue,require_host
    import virtual_print
    from print_focus import WindowsFocusProbe,click_owned_print_preferences
    require_host();require(digest(ROOT/'e2e/print_focus.py')==GUARD_SHA,'Strict controller guard bytes changed')
    fixture=work/'print-table--300.hwpx';fixture.write_bytes(base64.b64decode(FIXTURE_B64,validate=True))
    require(digest(fixture)==FIXTURE_SHA,'Frozen synthetic diagnostic fixture changed')
    folder=work/'table--300';folder.mkdir()
    with ExitStack() as resources:
        queue=resources.enter_context(VirtualQueue())
        session=Session('native',folder/'session',fixture,executable=runtime/'OpenGeul.exe')
        resources.callback(virtual_print.stop_session,session)
        dialog=virtual_print.system_dialog(session,queue,folder)
        inspection=json.loads((folder/'session/runtime.json').read_text(encoding='utf8'))
        report['runtimeInspectionControllerReport']=inspection['nativeArchitecture']['controller']
        button=virtual_print.control(dialog,'Button',1010)
        class DiagnosticProbe(WindowsFocusProbe):
            def hit(self,point):
                hit=super().hit(point);report['nativeHit']=inspect_hit(self,dialog,button,point,hit);return hit
        try:
            click_owned_print_preferences(NoInputDialog(dialog),session.proc.pid,inspection,
                app_handle=int(session.proc._handle),evidence_dir=OUT,probe=DiagnosticProbe())
        except DiagnosticInputPrevented:report['strictGuardOutcome']='allowed-bound-target; physical-input-prevented'
        except AssertionError:
            require('nativeHit' in report,'Strict guard rejected before hit observation')
            report['strictGuardOutcome']='rejected-before-physical-input'
        require('nativeHit' in report,'Native hit observation is absent')
        require(not queue.jobs(),'Observation unexpectedly produced a spool job')
        require(digest(fixture)==FIXTURE_SHA,'Observation modified synthetic input')
        report.update(observed=True,preferencesPhysicalInputs=0,spoolJobs=0)

def main():
    require(sys.argv[1:] in (['--prepare-runtime'],['--observe']),'Exactly one fixed diagnostic phase is required')
    preparing=sys.argv[1]=='--prepare-runtime'
    report={'scope':'native-hit observation only','sourceQualified':False,'wackQualified':False,
        'storeQualified':False,'productTelemetry':False,'observed':False}
    work=ROOT/'.work/native-hit'
    if preparing:
        OUT.mkdir(exist_ok=False);work.mkdir(parents=True,exist_ok=False)
    else:
        report=json.loads((OUT/'producer-preparation.json').read_bytes())
    try:
        require(os.environ.get('GITHUB_REPOSITORY')=='ATLKR/OpenGeul'
            and os.environ.get('GITHUB_EVENT_NAME')=='workflow_dispatch'
            and os.environ.get('GITHUB_REF')=='refs/heads/diagnostic/native-print-hit-113','Diagnostic scope changed')
        head=os.environ['GITHUB_SHA'];require(re.fullmatch('[0-9a-f]{40}',head),'Invalid controller head')
        from native_architecture import WindowsProbe,verify_executable
        probe=WindowsProbe();handle=probe.api.OpenProcess(0x1000,False,os.getpid())
        require(handle,'Controller observation handle unavailable')
        try:controller=probe.inspect(os.getpid(),handle)
        finally:probe.api.CloseHandle(handle)
        report['controller']={'head':head,'runId':os.environ['GITHUB_RUN_ID'],
            'attempt':os.environ['GITHUB_RUN_ATTEMPT'],'executablePE':verify_executable(Path(sys.executable),'x64'),
            'processMachine':controller['processMachine'],'nativeMachine':controller['nativeMachine']}
        if preparing:
            prepare_runtime(work,report)
        else:
            require(report['producer']['head']==PRODUCER_HEAD
                and report['producer']['runId']==PRODUCER_RUN and report['producer']['attempt']==1,
                'Prepared producer identity changed')
            prepared=json.loads((OUT/'producer-preparation.json').read_bytes())['controller']
            require(all(prepared[k]==report['controller'][k] for k in ('head','runId','attempt')),
                'Prepared diagnostic controller identity changed')
            runtime=work/'runtime'
            require(digest(runtime/'OpenGeul.exe')==EDITOR_SHA and digest(runtime/'Tools/rhwp.exe')==CLI_SHA,
                'Prepared runtime bytes changed before observation')
            observe(runtime,work,report)
    except BaseException as error:
        report['errorType']=type(error).__name__[:64];raise
    finally:
        # Keep the exact original bounded first-focus metadata when that stage
        # rejects before the native Preferences hit can be observed.
        focus=work/'table--300/print-initial-focus-diagnostic.json'
        if focus.is_file():
            raw=focus.read_bytes();require(len(raw)<=4096,'First focus diagnostic exceeds its bound')
            (OUT/'print-initial-focus-diagnostic.json').write_bytes(raw)
        payload=json.dumps(report,ensure_ascii=True,separators=(',',':')).encode('ascii')
        require(len(payload)<=32*1024,'Diagnostic metadata exceeds its bound')
        (OUT/('producer-preparation.json' if preparing else 'native-hit-observation.json')).write_bytes(payload)
        print(json.dumps({'observed':report['observed'],'scope':report['scope'],
            'sourceQualified':False,'wackQualified':False,'storeQualified':False}))

if __name__=='__main__':
    sys.path.insert(0,str(ROOT/'scripts'));sys.path.insert(0,str(ROOT/'e2e'));main()
