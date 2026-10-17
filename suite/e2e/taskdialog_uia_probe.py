"""Observe our own exact WinForms close-prompt shape; never choose a button."""
import argparse
import ctypes
from ctypes import wintypes as wt
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

CAPTION='OpenGeul Calc'
HEADING='변경 내용을 저장하시겠습니까?'
BUDGET=20.


def write_json(path,value):
    raw=(json.dumps(value,ensure_ascii=False,allow_nan=False,indent=2)+'\n').encode()
    if len(raw)>4*1024*1024:raise ValueError('Diagnostic JSON exceeds its finite bound')
    path.write_bytes(raw)


def stub_sources():
    project='''<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>
<OutputType>WinExe</OutputType><TargetFramework>net8.0-windows</TargetFramework>
<UseWindowsForms>true</UseWindowsForms><RuntimeFrameworkVersion>8.0.32</RuntimeFrameworkVersion>
<TargetLatestRuntimePatch>false</TargetLatestRuntimePatch><RollForward>Disable</RollForward>
<ApplicationHighDpiMode>PerMonitorV2</ApplicationHighDpiMode><ImplicitUsings>enable</ImplicitUsings>
<Nullable>enable</Nullable><AssemblyName>TaskDialogProbe</AssemblyName>
</PropertyGroup></Project>'''
    source='''using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text.Json;
using System.Windows.Forms;
internal static class Program {
 [STAThread] static void Main(string[] args) {
  ApplicationConfiguration.Initialize();
  using var owner = new Form { Text = "OpenGeul Calc", Width = 800, Height = 500, StartPosition = FormStartPosition.CenterScreen };
  owner.Shown += (_,_) => owner.BeginInvoke((Action)(() => {
   using var process = Process.GetCurrentProcess();
   File.WriteAllText(args[0]+".tmp",JsonSerializer.Serialize(new { schemaVersion=1, pid=Environment.ProcessId,
     creationTime=process.StartTime.ToUniversalTime().ToFileTimeUtc(), ownerHwnd=owner.Handle.ToInt64(),
     image=Environment.ProcessPath, framework=RuntimeInformation.FrameworkDescription,
     processArchitecture=RuntimeInformation.ProcessArchitecture.ToString(), caption=owner.Text,
     stage="before-taskdialog", productCloseQualified=false }));
   File.Move(args[0]+".tmp",args[0]);
   var save = new TaskDialogButton("저장");
   var discard = new TaskDialogButton("저장하지 않음");
   var cancel = new TaskDialogButton("취소");
   var page = new TaskDialogPage {
    Caption = "OpenGeul Calc", Heading = "변경 내용을 저장하시겠습니까?",
    Text = "저장하지 않음을 선택하면 변경 내용이 사라집니다.",
    Buttons = { save, discard, cancel }, DefaultButton = save, AllowCancel = true,
    Icon = TaskDialogIcon.Information
   };
   TaskDialog.ShowDialog(owner, page);
   owner.Close();
  }));
  Application.Run(owner);
 }
}'''
    return project,source


def sample_ready(sample,binding):
    root=sample.get('uiaRoot',{})
    return (all(sample.get(key)==binding.get(key) for key in ('pid','creationTime','ownerHwnd'))
        and sample.get('dialogOwner')==binding['ownerHwnd'] and sample.get('caption')==CAPTION
        and type(sample.get('dialogHwnd')) is int and sample['dialogHwnd']>0
        and sample.get('visible') is True and sample.get('enabled') is True
        and root.get('pid')==binding['pid'] and root.get('nativeHwnd')==sample['dialogHwnd']
        and bool(root.get('runtimeId')) and sample.get('queryErrors')==[]
        and any(row.get('name')==HEADING for row in sample.get('controls',[]))
        and any(row.get('controlType')==50000 for row in sample.get('controls',[])))


def stable_pair(rows,*,deadline):
    if len(rows)<2:return None
    first,second=rows[-2:]
    if (first['at']<=second['at']<=deadline and second['at']-first['at']>=.15
            and first['sample']==second['sample']):return second
    return None


class Native:
    def __init__(self):
        self.user=ctypes.WinDLL('user32',use_last_error=True)
        self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        def bind(library,name,args,result):
            fn=getattr(library,name);fn.argtypes=args;fn.restype=result;return fn
        self.wait=bind(self.kernel,'WaitForSingleObject',[wt.HANDLE,wt.DWORD],wt.DWORD)
        self.get_pid=bind(self.kernel,'GetProcessId',[wt.HANDLE],wt.DWORD)
        self.get_times=bind(self.kernel,'GetProcessTimes',[wt.HANDLE]+[ctypes.POINTER(wt.FILETIME)]*4,wt.BOOL)
        self.query_image=bind(self.kernel,'QueryFullProcessImageNameW',[wt.HANDLE,wt.DWORD,wt.LPWSTR,ctypes.POINTER(wt.DWORD)],wt.BOOL)
        self.open=bind(self.kernel,'OpenProcess',[wt.DWORD,wt.BOOL,wt.DWORD],wt.HANDLE)
        self.close=bind(self.kernel,'CloseHandle',[wt.HANDLE],wt.BOOL)
        self.terminate=bind(self.kernel,'TerminateProcess',[wt.HANDLE,wt.UINT],wt.BOOL)
        self.wow=bind(self.kernel,'IsWow64Process2',[wt.HANDLE,ctypes.POINTER(ctypes.c_ushort),ctypes.POINTER(ctypes.c_ushort)],wt.BOOL)
        self.pid=bind(self.user,'GetWindowThreadProcessId',[wt.HWND,ctypes.POINTER(wt.DWORD)],wt.DWORD)
        self.owner=bind(self.user,'GetWindow',[wt.HWND,wt.UINT],wt.HWND)
        self.parent=bind(self.user,'GetParent',[wt.HWND],wt.HWND)
        self.visible=bind(self.user,'IsWindowVisible',[wt.HWND],wt.BOOL)
        self.enabled=bind(self.user,'IsWindowEnabled',[wt.HWND],wt.BOOL)
        self.rect=bind(self.user,'GetWindowRect',[wt.HWND,ctypes.POINTER(wt.RECT)],wt.BOOL)
        self.client=bind(self.user,'GetClientRect',[wt.HWND,ctypes.POINTER(wt.RECT)],wt.BOOL)
        self.control_id=bind(self.user,'GetDlgCtrlID',[wt.HWND],ctypes.c_int)
        self.title=bind(self.user,'GetWindowTextW',[wt.HWND,wt.LPWSTR,ctypes.c_int],ctypes.c_int)
        self.class_name=bind(self.user,'GetClassNameW',[wt.HWND,wt.LPWSTR,ctypes.c_int],ctypes.c_int)
        self.callback=ctypes.WINFUNCTYPE(wt.BOOL,wt.HWND,wt.LPARAM)
        self.enum=bind(self.user,'EnumWindows',[self.callback,wt.LPARAM],wt.BOOL)
        self.enum_child=bind(self.user,'EnumChildWindows',[wt.HWND,self.callback,wt.LPARAM],wt.BOOL)
        self.dpi=bind(self.user,'SetProcessDpiAwarenessContext',[wt.HANDLE],wt.BOOL)
        self.dpi_result=bool(self.dpi(ctypes.c_void_p(-4)))

    def identity(self,handle):
        times=[wt.FILETIME() for _ in range(4)]
        if not self.get_times(handle,*map(ctypes.byref,times)):raise ctypes.WinError(ctypes.get_last_error())
        image=ctypes.create_unicode_buffer(32768);count=wt.DWORD(len(image))
        if not self.query_image(handle,0,image,ctypes.byref(count)):raise ctypes.WinError(ctypes.get_last_error())
        process,native=ctypes.c_ushort(),ctypes.c_ushort()
        if not self.wow(handle,ctypes.byref(process),ctypes.byref(native)):raise ctypes.WinError(ctypes.get_last_error())
        return dict(pid=int(self.get_pid(handle)),creationTime=(times[0].dwHighDateTime<<32)|times[0].dwLowDateTime,
                    image=image.value,processMachine=process.value,nativeMachine=native.value,waitResult=int(self.wait(handle,0)))

    def window(self,hwnd):
        pid=wt.DWORD();thread=self.pid(hwnd,ctypes.byref(pid));title=ctypes.create_unicode_buffer(2048);cls=ctypes.create_unicode_buffer(256)
        self.title(hwnd,title,len(title));self.class_name(hwnd,cls,len(cls));rect,client=wt.RECT(),wt.RECT()
        if not self.rect(hwnd,ctypes.byref(rect)) or not self.client(hwnd,ctypes.byref(client)):raise ctypes.WinError(ctypes.get_last_error())
        return dict(hwnd=int(hwnd),pid=pid.value,threadId=int(thread),name=title.value,className=cls.value,
            owner=int(self.owner(hwnd,4) or 0),parent=int(self.parent(hwnd) or 0),controlId=int(self.control_id(hwnd)),
            rect=[rect.left,rect.top,rect.right,rect.bottom],clientRect=[client.left,client.top,client.right,client.bottom],
            visible=bool(self.visible(hwnd)),enabled=bool(self.enabled(hwnd)))

    def windows(self,expected_pid,parent=None):
        rows=[];errors=[]
        def visit(hwnd,unused):
            try:
                pid=wt.DWORD();self.pid(hwnd,ctypes.byref(pid))
                if pid.value==expected_pid:rows.append(self.window(hwnd))
            except Exception as exc:errors.append(str(exc))
            return True
        callback=self.callback(visit)
        if parent is None:self.enum(callback,0)
        else:self.enum_child(parent,callback,0)
        if errors:raise RuntimeError('Native window census failed: '+repr(errors))
        return rows


def observe(binding_path):
    binding=json.loads(binding_path.read_bytes());out=binding_path.parent;api=Native();handle=None
    report=dict(schemaVersion=1,kind='owned-stub-taskdialog-uia-shape',source=binding['source'],observed=False,
        productCloseQualified=False,selectionPerformed=False,startedAt=binding['startedAt'],deadline=binding['deadline'],samples=[])
    ready=[]
    try:
        from pywinauto.uia_defines import IUIA
        from PIL import ImageGrab
        uia=IUIA().iuia
        handle=api.open(0x1000|0x100000,False,binding['pid'])
        if not handle:raise ctypes.WinError(ctypes.get_last_error())
        expected=binding['identity']
        def owned():
            actual=api.identity(handle)
            if any(actual[k]!=expected[k] for k in ('pid','creationTime','image','processMachine','nativeMachine')) or actual['waitResult']!=258:
                raise RuntimeError('Original stub process generation/image/native identity changed')
        owner_file=out/'owner.json'
        while time.monotonic()<binding['deadline'] and len(report['samples'])<40:
            owned()
            if not owner_file.exists():time.sleep(.1);continue
            owner=json.loads(owner_file.read_bytes())
            if (owner['pid']!=expected['pid'] or owner['creationTime']!=expected['creationTime']
                    or os.path.normcase(owner['image'])!=os.path.normcase(expected['image'])
                    or owner['framework']!='.NET 8.0.32' or owner['processArchitecture']!='X64'):
                raise RuntimeError('Stub owner receipt differs from original retained process/runtime')
            owner_hwnd=owner['ownerHwnd'];native=api.window(owner_hwnd)
            if native['pid']!=binding['pid'] or native['name']!=CAPTION:raise RuntimeError('Stub owner HWND differs')
            candidates=[row for row in api.windows(binding['pid']) if row['owner']==owner_hwnd
                        and row['className']=='#32770' and row['name']==CAPTION]
            if len(candidates)!=1:time.sleep(.1);continue
            dialog=candidates[0];hwnd=dialog['hwnd'];errors=[]
            sample=dict(pid=binding['pid'],creationTime=expected['creationTime'],ownerHwnd=owner_hwnd,
                dialogHwnd=hwnd,dialogOwner=dialog['owner'],caption=dialog['name'],visible=dialog['visible'],enabled=dialog['enabled'],
                nativeOwner=native,nativeDialog=dialog,nativeChildren=api.windows(binding['pid'],hwnd),controls=[],queryErrors=errors)
            def element(node,parents=True):
                result={}
                for key,attribute,convert in [('name','CurrentName',str),('controlType','CurrentControlType',int),
                    ('controlTypeName','CurrentLocalizedControlType',str),('automationId','CurrentAutomationId',str),
                    ('pid','CurrentProcessId',int),('nativeHwnd','CurrentNativeWindowHandle',lambda v:int(v or 0)),
                    ('enabled','CurrentIsEnabled',bool),('offscreen','CurrentIsOffscreen',bool),('className','CurrentClassName',str),
                    ('frameworkId','CurrentFrameworkId',str)]:
                    try:result[key]=convert(getattr(node,attribute))
                    except Exception as exc:errors.append(dict(operation=attribute,type=type(exc).__name__,message=str(exc)[:1024]))
                try:result['runtimeId']=list(node.GetRuntimeId())
                except Exception as exc:errors.append(dict(operation='GetRuntimeId',message=str(exc)[:1024]))
                try:
                    r=node.CurrentBoundingRectangle;result['rect']=[r.left,r.top,r.right,r.bottom]
                except Exception as exc:errors.append(dict(operation='CurrentBoundingRectangle',message=str(exc)[:1024]))
                result['visible']=not result.get('offscreen',True)
                result['controlId']=api.control_id(result['nativeHwnd']) if result.get('nativeHwnd') else None
                if parents:
                    result['parentChain']=[];cursor=node;reached=False
                    for _ in range(16):
                        if uia.CompareElements(cursor,root):reached=True;break
                        cursor=uia.RawViewWalker.GetParentElement(cursor)
                        if not cursor:break
                        result['parentChain'].append(element(cursor,False))
                    result['parentTitleBar']=any(row.get('controlType')==50037 for row in result['parentChain'])
                    result['parentChainReachesDialog']=reached
                    if not reached:errors.append(dict(operation='parent-chain',message='UIA ancestor did not reach exact dialog root'))
                return result
            try:
                root=uia.ElementFromHandle(hwnd);sample['uiaRoot']=element(root,False)
                found=root.FindAll(4,uia.CreateTrueCondition());count=int(found.Length);sample['rawElementCount']=count
                if not 0<=count<=256:raise RuntimeError('Owned UIA tree exceeds finite control bound')
                for index in range(count):sample['controls'].append(element(found.GetElement(index)))
            except Exception as exc:errors.append(dict(operation='raw-UIA-census',type=type(exc).__name__,message=str(exc)[:1024]))
            owned();stamp=time.monotonic();entry=dict(at=stamp,sample=sample)
            report['samples'].append(entry);write_json(out/'observations.json',report)
            check_binding=dict(pid=binding['pid'],creationTime=expected['creationTime'],ownerHwnd=owner_hwnd)
            if stamp<=binding['deadline'] and sample_ready(sample,check_binding):
                if 'firstReadyAt' not in report:
                    report['firstReadyAt']=stamp
                    write_json(out/'first-ready.json',entry)
                    ImageGrab.grab(bbox=tuple(dialog['rect'])).save(out/'first-ready.png')
                ready.append(entry)
                if stable_pair(ready,deadline=binding['deadline']):
                    write_json(out/'stable.json',entry);ImageGrab.grab(bbox=tuple(dialog['rect'])).save(out/'stable.png')
                    report['observed']=True;break
            else:ready=[]
            time.sleep(min(.2,max(0,binding['deadline']-time.monotonic())))
        if not report['observed']:raise RuntimeError('No two complete stable owned TaskDialog observations within original20s')
    except Exception as exc:
        report.update(error=type(exc).__name__+': '+str(exc),traceback=traceback.format_exc());raise
    finally:
        if handle:report['observerHandleClosed']=bool(api.close(handle))
        report['finishedAt']=time.monotonic();write_json(out/'observations.json',report)


def controller(output):
    out=output.resolve()
    if out.exists():raise ValueError('Preserve previous diagnostic output; choose a fresh path')
    for path in (out,*out.parents):
        if path.is_symlink():raise ValueError('Diagnostic output cannot traverse links')
    out.mkdir(parents=True)
    record=dict(schemaVersion=1,kind='controlled-winforms-taskdialog-shape-diagnostic',observed=False,
        productCloseQualified=False,selectionPerformed=False,purpose='Observe owned stub UIA shape only',cleanup={})
    stub=worker=None;api=None
    try:
        if os.name!='nt':raise RuntimeError('Actual Windows UIA is required')
        for package,expected in [('pywinauto','0.6.9'),('Pillow','12.3.0')]:
            if importlib.metadata.version(package)!=expected:raise RuntimeError('Pinned automation package differs: '+package)
        repo=Path(__file__).resolve().parents[2]
        head=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
        if os.environ.get('GITHUB_SHA')!=head:raise RuntimeError('Actual source commit differs from workflow')
        record['source']=dict(sourceCommit=head,runId=os.environ['GITHUB_RUN_ID'],runAttempt=os.environ['GITHUB_RUN_ATTEMPT'],job=os.environ['GITHUB_JOB'])
        project=out/'project';project.mkdir();csproj,cs=stub_sources()
        (project/'TaskDialogProbe.csproj').write_text(csproj);(project/'Program.cs').write_text(cs,encoding='utf-8')
        program=out/'program'
        with (out/'build.stdout.log').open('wb') as stdout,(out/'build.stderr.log').open('wb') as stderr:
            subprocess.run(['dotnet','publish',str(project/'TaskDialogProbe.csproj'),'-c','Release','-r','win-x64',
                '--self-contained','true','-o',str(program),'-p:NuGetAudit=false'],stdout=stdout,stderr=stderr,timeout=180,check=True)
        exe=program/'TaskDialogProbe.exe';record['stubSha256']=hashlib.sha256(exe.read_bytes()).hexdigest()
        record['stubAssemblySha256']=hashlib.sha256((program/'TaskDialogProbe.dll').read_bytes()).hexdigest()
        api=Native()
        record['controllerIdentity']=api.identity(wt.HANDLE(-1))
        if record['controllerIdentity']['processMachine']!=0 or record['controllerIdentity']['nativeMachine']!=0x8664:
            raise RuntimeError('Diagnostic Python controller must run native x64')
        stub=subprocess.Popen([str(exe),str(out/'owner.json')],cwd=program)
        started=time.monotonic();deadline=started+BUDGET;identity=api.identity(int(stub._handle))
        if identity['pid']!=stub.pid or identity['processMachine']!=0 or identity['nativeMachine']!=0x8664:
            raise RuntimeError('Owned stub must run native x64 on Windows2025')
        binding=dict(source=record['source'],pid=stub.pid,identity=identity,startedAt=started,deadline=deadline,budgetSeconds=BUDGET)
        write_json(out/'binding.json',binding);record['binding']=binding
        with (out/'observer.stdout.log').open('wb') as stdout,(out/'observer.stderr.log').open('wb') as stderr:
            worker=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--observe',str(out/'binding.json')],stdout=stdout,stderr=stderr)
            try:code=worker.wait(timeout=max(.001,deadline-time.monotonic()))
            except subprocess.TimeoutExpired:raise RuntimeError('Owned UIA observer exceeded original20s deadline')
        if code!=0:raise RuntimeError('Owned UIA observer failed; inspect original observations and stderr')
        evidence=json.loads((out/'observations.json').read_bytes())
        if evidence.get('observed') is not True or evidence['finishedAt']>deadline:raise RuntimeError('Stable observation missed original deadline')
        record['observed']=True
    except Exception as exc:
        record.update(error=type(exc).__name__+': '+str(exc),traceback=traceback.format_exc());raise
    finally:
        cleanup_errors=[]
        if worker is not None:
            try:
                if worker.poll() is None:worker.terminate()
                try:worker.wait(timeout=5)
                except subprocess.TimeoutExpired:worker.kill();worker.wait(timeout=5)
                record['cleanup']['observerExitCode']=worker.returncode
                worker._handle.Close();record['cleanup']['observerProcessHandleClosed']=True
            except Exception as exc:cleanup_errors.append(dict(stage='observer',type=type(exc).__name__,message=str(exc)))
        if stub is not None and api is not None:
            try:
                handle=int(stub._handle);before=api.identity(handle);record['cleanup']['stubBefore']=before
                if before['waitResult']==258:
                    # Explicit cleanup of our retained stub HANDLE, without dialog input.
                    record['cleanup']['stubTerminateProcessResult']=bool(api.terminate(handle,77))
                    if not record['cleanup']['stubTerminateProcessResult']:raise ctypes.WinError(ctypes.get_last_error())
                record['cleanup']['stubWaitResult']=int(api.wait(handle,5000))
                if record['cleanup']['stubWaitResult']!=0:raise RuntimeError('Owned stub death is unproved')
                record['cleanup']['stubExitCode']=stub.wait(timeout=5)
                stub._handle.Close();record['cleanup']['stubProcessHandleClosed']=True
                record['cleanup']['diagnosticTerminationOnly']=True
            except Exception as exc:cleanup_errors.append(dict(stage='stub',type=type(exc).__name__,message=str(exc)))
        if cleanup_errors:record.update(observed=False,cleanupErrors=cleanup_errors)
        record['finishedAt']=time.monotonic();write_json(out/'diagnostic.json',record)
        if cleanup_errors and 'error' not in record:raise RuntimeError('Owned diagnostic cleanup failed; inspect original receipt')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=Path('.work/taskdialog-uia-probe'));parser.add_argument('--observe',type=Path)
    args=parser.parse_args()
    if args.observe:observe(args.observe)
    else:controller(args.output)

if __name__=='__main__':main()
