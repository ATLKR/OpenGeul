"""One read-only tool query inside the caller's original owned diagnostic Job.

Only fixed numeric fields leave RAM. Discovery may return one validated VS path
to the private coordinator file; raw process output is never written or printed.
"""
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time

VERSION_CAP, STDERR_CAP = 4096, 4096
RESULT_KEYS = {'schemaVersion','kindCode','resultCode','exitCode','major','minor','selectedRoot',
               'stdoutBytes','stderrBytes','timedOut','outputCapReached','pid','creationTime',
               'imageMatched','naturalExit','handlesClosed'}

def parse_version(raw,kind):
    assert type(raw) is bytes and len(raw) <= VERSION_CAP and b'\0' not in raw
    assert type(kind) is int and kind in (1,2)
    line = raw.split(b'\n',1)[0].rstrip(b'\r')
    prefix = rb'(?:clang|clang-cl) version ' if kind == 1 else rb'LLD '
    match = re.fullmatch(prefix+rb'([0-9]{1,3})\.([0-9]{1,3})(?:\.[0-9]{1,3})?(?:[ \t]+[^\r\n]{0,1024})?',line)
    assert match is not None, 'Unrecognized fixed version prefix'
    major,minor = map(int,match.group(1,2))
    assert 0 < major <= 999 and 0 <= minor <= 999
    return major,minor

def _identity(process,api=None):
    assert os.name == 'nt' or api is not None, 'Windows-only process witness'
    if api is None:
        worker = str(Path(__file__).resolve().parents[1]/'worker')
        sys.path.insert(0,worker)
        try:
            from native_windows import ProcessDiagnosticsApi
        finally:
            sys.path.remove(worker)
        api=ProcessDiagnosticsApi()
    value = api.identity(int(process._handle))
    assert type(process.pid) is int and process.pid>0
    assert type(value['creationTime']) is int and 0 < value['creationTime'] <= 0xffffffffffffffff
    return dict(value,pid=process.pid)

def capture(argv,deadline,stdout_cap,*,popen=subprocess.Popen,identity=_identity,clock=time.monotonic):
    result = dict(exitCode=None,pid=None,creationTime=None,imageMatched=False,naturalExit=False,
                  handlesClosed=False,timedOut=False,outputCapReached=False,captureError=False)
    out,err = bytearray(),bytearray()
    process = None
    readers = []
    reached = threading.Event()
    failed = threading.Event()
    end = min(deadline,clock()+5.)
    if clock() >= end:
        result['timedOut'] = True
        return result,bytes(out),bytes(err)
    def drain(pipe,target,cap):
        try:
            while len(target) < cap:
                part = pipe.read(min(1024,cap-len(target)))
                if not part:
                    return
                target.extend(part)
            reached.set()
        except BaseException:
            failed.set()
        finally:
            pipe.close()
    try:
        process = popen(argv,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                        bufsize=0,creationflags=0,close_fds=True)
        witness = identity(process)
        result.update(pid=witness['pid'],creationTime=witness['creationTime'],
                      imageMatched=Path(witness['image']) == Path(argv[0]))
        assert result['imageMatched'], 'Queried child image differs'
        for pipe,target,cap in ((process.stdout,out,stdout_cap),(process.stderr,err,STDERR_CAP)):
            reader = threading.Thread(target=drain,args=(pipe,target,cap),daemon=True)
            reader.start()
            readers.append(reader)
        while process.poll() is None:
            if reached.is_set() or failed.is_set():
                break
            remaining = end-clock()
            if remaining <= 0:
                result['timedOut'] = True
                break
            try:
                process.wait(timeout=min(.02,remaining))
            except subprocess.TimeoutExpired:
                pass
        if process.poll() is None:
            process.kill()  # Original Popen HANDLE only; inherited Job is never reclassified.
        else:
            result['naturalExit'] = True
        process.wait(timeout=1.)
        result['exitCode'] = process.returncode
        for reader in readers:
            reader.join(timeout=.2)
        result['outputCapReached'] = reached.is_set()
        result['captureError'] = failed.is_set() or any(r.is_alive() for r in readers)
    except BaseException:
        result['captureError'] = True
    finally:
        if process is not None:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=1.)
            for reader in readers:
                reader.join(timeout=.2)
            try:
                process.stdout.close()
                process.stderr.close()
                process._handle.Close()
                result['handlesClosed'] = True
            except BaseException:
                result['captureError'] = True
    return result,bytes(out),bytes(err)

def query(request,*,capture_call=capture):
    assert type(request) is dict and set(request) == {'schemaVersion','kindCode','tool','deadline'}
    assert type(request['schemaVersion']) is int and request['schemaVersion'] == 1
    kind = request['kindCode']
    assert type(kind) is int and kind in (0,1,2)
    tool = request['tool']
    assert type(tool) is str and Path(tool).is_absolute() and len(tool) <= 4096
    path=Path(tool)
    if kind:
        assert tuple(part.casefold() for part in path.parts[-6:])==('vc','tools','llvm','x64','bin',('clang-cl.exe','lld-link.exe')[kind-1])
    else:
        assert path.name.casefold()=='vswhere.exe'
        assert tuple(part.casefold() for part in path.parts[-3:-1])==('microsoft visual studio','installer')
    assert type(request['deadline']) in (int,float) and math.isfinite(request['deadline'])
    assert request['deadline']-time.monotonic() <= 30.
    argv = [tool,'--version'] if kind else [tool,'-utf8','-latest','-products','*','-requires',
            'Microsoft.VisualStudio.Component.VC.Tools.x86.x64','-property','installationPath']
    observed,out,err = capture_call(argv,request['deadline'],32768 if kind == 0 else VERSION_CAP)
    result = dict(schemaVersion=1,kindCode=kind,resultCode=0,exitCode=observed['exitCode'],major=None,minor=None,
                  selectedRoot=None,stdoutBytes=len(out),stderrBytes=len(err),timedOut=observed['timedOut'],
                  outputCapReached=observed['outputCapReached'],pid=observed['pid'],creationTime=observed['creationTime'],
                  imageMatched=observed['imageMatched'],naturalExit=observed['naturalExit'],handlesClosed=observed['handlesClosed'])
    if observed['timedOut']:result['resultCode'] = 2
    elif observed['outputCapReached']:result['resultCode'] = 3
    elif observed['captureError'] or not all(observed[k] for k in ('imageMatched','naturalExit','handlesClosed')):result['resultCode'] = 7
    elif observed['exitCode'] != 0:result['resultCode'] = 4
    else:
        try:
            if kind:
                result['major'],result['minor'] = parse_version(out,kind)
            else:
                assert 0 < len(out) <= 4096 and b'\0' not in out
                root = out.decode('utf-8-sig').strip()
                assert '\n' not in root and '\r' not in root and Path(root).is_absolute()
                result['selectedRoot'] = root
        except BaseException:
            result['resultCode'] = 5 if kind else 8
    return result

def main(argv=None):
    # No argparse error message can echo an unexpected path or query output.
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 4 or args[0] != '--request' or args[2] != '--result':return 1
    try:
        request_path,result_path = Path(args[1]),Path(args[3])
        assert request_path.is_absolute() and result_path.is_absolute()
        assert request_path.is_file() and 0 < request_path.stat().st_size <= 8192
        with request_path.open('rb') as stream:raw=stream.read(8192)
        assert len(raw)==request_path.stat().st_size<=8192
        request = json.loads(raw)
        result = query(request)
        blob = (json.dumps(result,sort_keys=True,allow_nan=False)+'\n').encode('ascii')
        assert set(result) == RESULT_KEYS and len(blob) <= 8192
        with result_path.open('xb') as stream:stream.write(blob)
        return 0  # Observations, including missing/old versions, carry numeric failure only.
    except BaseException:
        return 1

if __name__ == '__main__':raise SystemExit(main())
