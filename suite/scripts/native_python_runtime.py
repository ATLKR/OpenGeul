"""Native controller observes the live candidate without needing its _ctypes extension."""
import ctypes
import ctypes.wintypes as w
import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path

spec=importlib.util.spec_from_file_location('control',Path(__file__).with_name('native_python_control.py'))
c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)
exe,dll,kat,vectors,out=map(Path,sys.argv[1:]); marker=out/'kat-ready.json';release=out/'kat-release.txt'
for p in [marker,release]:
    if p.exists():raise ValueError('Preserve existing runtime evidence')
k=ctypes.WinDLL('kernel32',use_last_error=True)
k.GetProcessTimes.argtypes=[w.HANDLE,ctypes.POINTER(w.FILETIME),ctypes.POINTER(w.FILETIME),ctypes.POINTER(w.FILETIME),ctypes.POINTER(w.FILETIME)]
k.IsWow64Process2.argtypes=[w.HANDLE,ctypes.POINTER(w.USHORT),ctypes.POINTER(w.USHORT)]
k.QueryFullProcessImageNameW.argtypes=[w.HANDLE,w.DWORD,w.LPWSTR,ctypes.POINTER(w.DWORD)]
k.K32GetModuleFileNameExW.argtypes=[w.HANDLE,w.HMODULE,w.LPWSTR,w.DWORD]
argv=[str(exe),'-I',str(kat),str(vectors),str(marker),str(release)]
r={'argv':argv,'exitCode':None,'directProcessDeathVerified':False,'pipeDrainComplete':False,'forcedTermination':False,'descendantCensus':None}
p=subprocess.Popen(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE,cwd=exe.parent)
r['pid']=p.pid;start=time.monotonic()
try:
    while not marker.exists():
        if p.poll() is not None or time.monotonic()-start>90:raise ValueError('KAT not ready before deadline')
        time.sleep(.1)
    proof=json.loads(marker.read_text())
    if proof['pid']!=p.pid:raise ValueError('KAT marker PID differs from owned child')
    # Popen owns this CreateProcess handle for wait/kill; never reopen by numeric PID.
    h=w.HANDLE(int(p._handle))
    created=w.FILETIME();exited=w.FILETIME();kernel=w.FILETIME();user=w.FILETIME()
    if not k.GetProcessTimes(h,ctypes.byref(created),ctypes.byref(exited),ctypes.byref(kernel),ctypes.byref(user)):raise ctypes.WinError(ctypes.get_last_error())
    r['creationFileTime']=created.dwHighDateTime<<32|created.dwLowDateTime
    r['observationHandle']='retained Popen CreateProcess handle'
    process=w.USHORT();native=w.USHORT()
    if not k.IsWow64Process2(h,ctypes.byref(process),ctypes.byref(native)):raise ctypes.WinError(ctypes.get_last_error())
    buf=ctypes.create_unicode_buffer(32768);n=w.DWORD(len(buf))
    if not k.QueryFullProcessImageNameW(h,0,buf,ctypes.byref(n)):raise ctypes.WinError(ctypes.get_last_error())
    proof['executable']=buf.value
    if not k.K32GetModuleFileNameExW(h,w.HMODULE(proof['dllHandle']),buf,len(buf)):raise ctypes.WinError(ctypes.get_last_error())
    proof.update(dll=buf.value,processMachine=process.value,nativeMachine=native.value,creationFileTime=r['creationFileTime'],observationHandle=r['observationHandle'])
    c.admit_runtime(proof,str(exe),str(dll));c.write_json(out/'native-runtime-identity.json',proof)
    release.write_text('observed')
    stdout,stderr=p.communicate(timeout=max(1,120-(time.monotonic()-start)))
    r['pipeDrainComplete']=True
    if p.returncode:raise ValueError('KAT child failed')
finally:
    if p.poll() is None:p.kill();r['forcedTermination']=True
    stdout,stderr=p.communicate(timeout=5)
    (out/'kat.stdout.log').write_bytes(stdout);(out/'kat.stderr.log').write_bytes(stderr)
    r.update(exitCode=p.returncode,directProcessDeathVerified=p.poll() is not None,elapsedSeconds=time.monotonic()-start)
    c.write_json(out/'kat-process.json',r)
