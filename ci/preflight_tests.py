"""Run the two required preflight suites concurrently with original bounded logs."""
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
LOG_CAP = 4*1024*1024
TIMEOUT = 480


def commands():
    return {name:[sys.executable,'-m','unittest','discover','-s',folder,'-v']
            for name,folder in (('ci','ci/tests'),('product','tests'))}


def terminate_owned(process):
    try:
        if os.name == 'posix': os.killpg(process.pid, signal.SIGTERM)
        else: process.terminate()
    except ProcessLookupError: pass
    try: process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        try:
            if os.name == 'posix': os.killpg(process.pid, signal.SIGKILL)
            else: process.kill()
        except ProcessLookupError: pass
        process.wait(timeout=2)
    if os.name == 'posix':
        # The root may have exited while an owned descendant still holds stdout.
        # Finishing root.wait() therefore does not prove this session is empty.
        try: os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError: pass


def execute(suites, output, cwd, *, timeout=TIMEOUT, cap=LOG_CAP):
    if set(suites) != {'ci','product'} or timeout <= 0 or cap < 1:
        raise ValueError('Two fixed suites and positive bounds are required.')
    output = Path(output)
    if output.exists() or any(p.is_symlink() for p in (output,*output.parents)):
        raise ValueError('Existing or linked preflight output must be preserved.')
    output.mkdir(parents=True)
    states = {}; children = {}; readers = {}; frozen = {}; locks = {}
    deadline = time.monotonic()+timeout
    started = time.monotonic()
    startup_error = False

    def drain(name, process, log):
        state = states[name]
        try:
            with log.open('xb',buffering=0) as stream:
                while chunk := process.stdout.read(64*1024):
                    with locks[name]:
                        if frozen[name].is_set(): break
                        remaining = cap-state['bytesRetained']
                        retained = chunk[:remaining]
                        written = stream.write(retained)
                        state['bytesRetained'] += written or 0
                        if written != len(retained):
                            raise OSError('Preflight log write was incomplete.')
                    if len(chunk)>remaining:
                        state['logCapExceeded'] = True
                        terminate_owned(process)
                        break
        except Exception:
            state['readError'] = True
            terminate_owned(process)
        finally:
            process.stdout.close()

    try:
        for name in ('ci','product'):
            states[name] = {'exitCode':None,'timedOut':False,'logCapExceeded':False,
                            'readError':False,'bytesRetained':0}
            frozen[name] = threading.Event(); locks[name] = threading.Lock()
            child = subprocess.Popen(suites[name], cwd=cwd, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     start_new_session=os.name == 'posix')
            children[name] = child
            readers[name] = threading.Thread(target=drain,args=(name,child,output/(name+'.log')),daemon=True)
            readers[name].start()
        next_progress = started
        while any(p.poll() is None for p in children.values()) or any(t.is_alive() for t in readers.values()):
            if time.monotonic() >= deadline:
                for name,child in children.items():
                    if child.poll() is None or readers[name].is_alive():
                        states[name]['timedOut'] = True
                        terminate_owned(child)
                break
            if time.monotonic() >= next_progress:
                print('필수 사전 검사 두 묶음을 실행 중입니다. 원본 로그: ci.log, product.log.', flush=True)
                next_progress = time.monotonic()+15
            time.sleep(0.02)
    except Exception:
        startup_error = True
        for child in children.values(): terminate_owned(child)
    finally:
        for name,child in children.items():
            child.wait(timeout=3)
            readers[name].join(timeout=3)
            states[name]['exitCode'] = child.returncode
            states[name]['readError'] |= readers[name].is_alive()
            with locks[name]: frozen[name].set()
    # Check after every pipe drainer has finished, including buffered output
    # produced just before a child exited successfully.
    for name in ('ci','product'):
        state = states.setdefault(name,{'exitCode':None,'timedOut':False,'logCapExceeded':False,
                                       'readError':True,'bytesRetained':0})
        log = output/(name+'.log')
        state['logComplete'] = not any(state[k] for k in ('timedOut','logCapExceeded','readError')) and log.exists()
        state['logSha256'] = hashlib.sha256(log.read_bytes()).hexdigest() if log.exists() else None
    passed = not startup_error and all(s['exitCode']==0 and s['logComplete'] for s in states.values())
    receipt = {'scope':'two required preflight suites only','maximumConcurrentSuites':2,
               'suiteStates':states,'elapsedSeconds':time.monotonic()-started,
               'startupError':startup_error,'passed':passed,'sourceQualified':False,
               'wackQualified':False,'storeQualified':False}
    (output/'summary.json').write_text(json.dumps(receipt,sort_keys=True,indent=2)+'\n',encoding='utf-8')
    return receipt


if __name__ == '__main__':
    report = execute(commands(), ROOT/'.work/preflight-tests', ROOT)
    print(json.dumps({'preflightPassed':report['passed'],'suites':report['suiteStates']},sort_keys=True))
    raise SystemExit(0 if report['passed'] else 1)
