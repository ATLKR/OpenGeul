"""격리된 cold CLI 컴파일 비교. 제품·Source20·Source22·Store 자격을 부여하지 않는다."""
from __future__ import annotations
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
sys.path.insert(0, str(ROOT/'ci'))
import windows_components as components
from policy import require_public
from build_progress import terminate_owned

BASE = 'f104fd4080214bc072cf39a24e73454685dd4254'
BRANCH = 'diagnostic/cargo-pressure-8-12-16'
WASM_RUN = 38237687615
WASM_ARTIFACT = 11741399358
WASM_SIZE = 4829693
WASM_DIGEST = '943441db925635b074b40abba0f31f91cb5bfdc5cf8aa7da3c5dcd2421bb2c2c'
LEVELS = (8, 12, 16)
COMMAND = ('cargo', 'build', '--release', '--locked', '--target', 'x86_64-pc-windows-msvc',
           '--package', 'rhwp', '--bin', 'rhwp', '--features', 'native-skia')
EDITOR_COMMAND = ('pnpm', 'tauri', 'build', '--no-bundle', '--target', 'x86_64-pc-windows-msvc')
CHANGED_PATHS = ('.github/workflows/msix.yml', 'ci/pressure_benchmark.py', 'ci/tests/test_pressure_benchmark.py')
GIB = 1024**3
LOG_CAP = 8*1024*1024
SAMPLES_CAP = 2*1024*1024
JSON_CAP = 512*1024
MIN_FREE = 3*GIB//2
OUTPUT = ROOT/'pressure-evidence'


class FILETIME(ctypes.Structure):
    _fields_ = [('dwLowDateTime', ctypes.c_uint32), ('dwHighDateTime', ctypes.c_uint32)]
    def ticks(self): return self.dwLowDateTime | (self.dwHighDateTime << 32)


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [('dwLength', ctypes.c_uint32), ('dwMemoryLoad', ctypes.c_uint32),
                *[(name, ctypes.c_uint64) for name in ('ullTotalPhys', 'ullAvailPhys', 'ullTotalPageFile',
                    'ullAvailPageFile', 'ullTotalVirtual', 'ullAvailVirtual', 'ullAvailExtendedVirtual')]]


class WindowsProbe:
    def __init__(self):
        if os.name != 'nt': raise ValueError('실제 Windows runner가 필요합니다')
        self.api = ctypes.WinDLL('kernel32', use_last_error=True)
        self.api.GetSystemTimes.argtypes = [ctypes.POINTER(FILETIME)]*3
        self.api.GetSystemTimes.restype = ctypes.c_int32
        self.api.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(MEMORYSTATUSEX)]
        self.api.GlobalMemoryStatusEx.restype = ctypes.c_int32
    def sample(self):
        idle, kernel, user = FILETIME(), FILETIME(), FILETIME()
        memory = MEMORYSTATUSEX(); memory.dwLength = ctypes.sizeof(memory)
        if not self.api.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
            raise ValueError('GetSystemTimes 관측 실패')
        if not self.api.GlobalMemoryStatusEx(ctypes.byref(memory)):
            raise ValueError('GlobalMemoryStatusEx 관측 실패')
        if not 0 < memory.ullAvailPhys <= memory.ullTotalPhys: raise ValueError('유효하지 않은 실제 RAM 관측')
        return {'monotonicNs': time.monotonic_ns(), 'cpuTimes': (idle.ticks(), kernel.ticks(), user.ticks()),
                'totalPhysicalBytes': memory.ullTotalPhys, 'availablePhysicalBytes': memory.ullAvailPhys}


def cpu_interval(before, after):
    if (len(before) != 3 or len(after) != 3 or any(type(x) is not int or x < 0 for x in (*before,*after))
            or any(y < x for x,y in zip(before,after))): raise ValueError('유효하지 않은 CPU counter')
    idle, kernel, user = (y-x for x,y in zip(before,after))
    total = kernel+user
    if total <= 0 or idle > total: raise ValueError('유효하지 않은 CPU interval')
    return {'totalTicks': total, 'busyTicks': total-idle, 'cpuBusyPercent': 100*(total-idle)/total}


def statistics(samples):
    if not samples: raise ValueError('실제 compile 자원 샘플이 없습니다')
    for sample in samples:
        values = [sample[key] for key in ('availablePhysicalBytes','totalPhysicalBytes','totalTicks','busyTicks')]
        if (any(type(x) is not int for x in values) or not 0 <= values[0] <= values[1]
                or values[1] <= 0 or values[2] <= 0 or not 0 <= values[3] <= values[2]):
            raise ValueError('자원 샘플이 올바르지 않습니다')
    if len({sample['totalPhysicalBytes'] for sample in samples}) != 1: raise ValueError('실행 중 RAM 신원이 다릅니다')
    minimum = min(x['availablePhysicalBytes'] for x in samples)
    return {'sampleCount': len(samples), 'meanCpuBusyPercent': 100*sum(x['busyTicks'] for x in samples)/sum(x['totalTicks'] for x in samples),
            'minimumAvailablePhysicalBytes': minimum, 'peakSystemUsedPhysicalBytes': samples[0]['totalPhysicalBytes']-minimum,
            'totalPhysicalBytes': samples[0]['totalPhysicalBytes']}


def check_changed_paths(paths):
    if sorted(paths) != sorted(CHANGED_PATHS): raise ValueError('진단 branch에 허용되지 않은 제품 변경이 있습니다')
    return list(CHANGED_PATHS)


def write_new(path, raw, cap):
    if path.exists() or path.is_symlink() or len(raw) > cap: raise ValueError('원본 덮어쓰기·크기 제한 위반')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream: stream.write(raw)


def encoded(value): return (json.dumps(value,sort_keys=True,separators=(',',':'))+'\n').encode()
def git(*args): return subprocess.check_output(['git',*args],cwd=ROOT,timeout=30).decode().strip()
def utc(): return datetime.now(timezone.utc).isoformat()


def execution():
    current = components.identity()
    event_path = Path(os.environ['GITHUB_EVENT_PATH'])
    if not 0 < event_path.stat().st_size <= 256*1024: raise ValueError('이벤트 크기 제한 위반')
    event = json.loads(event_path.read_text(encoding='utf-8'), object_pairs_hook=components._pairs)
    require_public(event)
    if (os.environ.get('GITHUB_EVENT_NAME') != 'workflow_dispatch' or os.environ.get('GITHUB_REF') != 'refs/heads/'+BRANCH
            or os.environ.get('GITHUB_JOB') != 'compile-pressure'
            or event.get('repository',{}).get('id') != 1405493151
            or event.get('repository',{}).get('full_name') != 'ATLKR/OpenGeul'
            or current['commit'] != git('rev-parse','HEAD')): raise ValueError('현재 진단 실행 신원이 다릅니다')
    check_changed_paths(git('diff','--name-only',BASE,'HEAD').splitlines())
    if git('status','--porcelain','--untracked-files=no'): raise ValueError('tracked 소스 변경이 있습니다')
    current.update({'job': 'compile-pressure', 'productBaseCommit': BASE, 'sourceQualification': False,
                    'releaseQualification': False, 'storeQualification': False,
                    'helperSha256': components.sha(Path(__file__))})
    return current


def api_raw(path):
    request = urllib.request.Request('https://api.github.com/repos/ATLKR/OpenGeul/'+path,
        headers={'Authorization':'Bearer '+os.environ['GH_TOKEN'],'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'})
    with urllib.request.urlopen(request,timeout=30) as response: raw = response.read(JSON_CAP+1)
    if len(raw) > JSON_CAP: raise ValueError('공식 원본 API 크기 제한 위반')
    return raw, json.loads(raw,object_pairs_hook=components._pairs)


def download_wasm():
    current = execution()
    if OUTPUT.exists(): raise ValueError('기존 진단 원본을 보존합니다')
    OUTPUT.mkdir()
    raw_run, run = api_raw(f'actions/runs/{WASM_RUN}')
    raw_artifact, artifact = api_raw(f'actions/artifacts/{WASM_ARTIFACT}')
    raw_jobs, jobs = api_raw(f'actions/runs/{WASM_RUN}/attempts/1/jobs?per_page=100')
    wasm_jobs = [job for job in jobs.get('jobs',[]) if job.get('name') == 'wasm']
    if (run.get('id') != WASM_RUN or run.get('head_sha') != BASE or run.get('run_attempt') != 1
            or run.get('head_branch') != 'main' or run.get('path') != '.github/workflows/msix.yml'
            or run.get('repository',{}).get('id') != 1405493151
            or run.get('repository',{}).get('private') is not False
            or len(wasm_jobs) != 1 or wasm_jobs[0].get('conclusion') != 'success'
            or artifact.get('id') != WASM_ARTIFACT or artifact.get('name') != f'opengeul-wasm-{WASM_RUN}'
            or artifact.get('size_in_bytes') != WASM_SIZE or artifact.get('digest') != 'sha256:'+WASM_DIGEST
            or artifact.get('expired') is not False or artifact.get('workflow_run',{}).get('head_sha') != BASE
            or artifact.get('workflow_run',{}).get('repository_id') != 1405493151
            or artifact.get('workflow_run',{}).get('head_repository_id') != 1405493151
            or artifact.get('workflow_run',{}).get('id') != WASM_RUN): raise ValueError('실제 Source75 WASM 원본 신원이 다릅니다')
    request = urllib.request.Request('https://api.github.com/repos/ATLKR/OpenGeul/'+f'actions/artifacts/{WASM_ARTIFACT}/zip',
        headers={'Authorization':'Bearer '+os.environ['GH_TOKEN'],'Accept':'application/vnd.github+json'})
    with urllib.request.urlopen(request,timeout=60) as response: raw_zip = response.read(WASM_SIZE+1)
    if len(raw_zip) != WASM_SIZE or hashlib.sha256(raw_zip).hexdigest() != WASM_DIGEST:
        raise ValueError('Source75 WASM 원본 ZIP SHA·size가 다릅니다')
    write_new(OUTPUT/'source75-wasm-original.zip',raw_zip,WASM_SIZE)
    write_new(OUTPUT/'source75-run-original.api.json',raw_run,JSON_CAP)
    write_new(OUTPUT/'source75-wasm-original.api.json',raw_artifact,JSON_CAP)
    write_new(OUTPUT/'source75-attempt1-jobs-original.api.json',raw_jobs,JSON_CAP)
    target = ROOT/'wasm-input'
    if target.exists(): raise ValueError('기존 WASM 입력을 보존합니다')
    target.mkdir()
    expected = {'rhwp.js','rhwp.d.ts','rhwp_bg.wasm','rhwp_bg.wasm.d.ts','package.json','LICENSE','OPEN_GEUL_WASM.json'}
    with zipfile.ZipFile(OUTPUT/'source75-wasm-original.zip') as archive:
        if len(archive.infolist()) != 7 or set(archive.namelist()) != expected or archive.testzip() is not None:
            raise ValueError('원본 WASM ZIP inventory·CRC가 다릅니다')
        if sum(x.file_size for x in archive.infolist()) > 32*1024*1024: raise ValueError('WASM expansion 제한 위반')
        for item in archive.infolist():
            if item.is_dir() or item.external_attr >> 16 & 0o170000 == 0o120000: raise ValueError('정규 WASM 파일이 아닙니다')
            write_new(target/item.filename,archive.read(item),32*1024*1024)
    write_new(OUTPUT/'diagnostic-context.json',encoded(current),JSON_CAP)
    print('Source75 원본 WASM run/head/a1/artifact/ZIP SHA·size/CRC/7파일 확인. 진단 source qualification=false.')


def compile_measure(jobs, workload):
    if jobs not in LEVELS: raise ValueError('진단 jobs는 8/12/16입니다')
    if workload not in ('cli','editor-release'): raise ValueError('알 수 없는 실제 workload입니다')
    current = execution()
    previous = components.read_json(OUTPUT/'diagnostic-context.json')
    if previous != current: raise ValueError('현재 진단 실행 신원이 변경되었습니다')
    source = ROOT/'.work/hop'; cwd = source/'third_party/rhwp' if workload == 'cli' else source
    command = COMMAND if workload == 'cli' else EDITOR_COMMAND
    config = components.configured()
    _, contract = components.source_contract(source,config)
    before_contract = components.encoded(contract,compact=True)
    before_config = components.encoded(config,compact=True)
    write_new(OUTPUT/'source-contract.json',before_contract,JSON_CAP)
    write_new(OUTPUT/'source-config.json',before_config,JSON_CAP)
    production = (ROOT/'scripts/build-msix.ps1').read_text(encoding='utf-8')
    expected_line = 'cargo build --release --locked --target $target --package rhwp --bin rhwp --features native-skia'
    expected_editor = 'pnpm tauri build --no-bundle --target $target'
    if production.count(expected_line) != 1 or production.count(expected_editor) != 1:
        raise ValueError('비교할 원본 제품 compile 명령이 변경되었습니다')
    toolchain = config['upstream']['rust']+'-x86_64-pc-windows-msvc'
    env = os.environ.copy(); env['RUSTUP_TOOLCHAIN'] = toolchain
    version = subprocess.check_output(['rustc','--version'],env=env,cwd=ROOT,timeout=30).decode().strip()
    if not version.startswith('rustc '+config['upstream']['rust']+' '): raise ValueError('실제 고정 Rust toolchain이 다릅니다')
    if any(name in env for name in ('RUSTFLAGS','CARGO_ENCODED_RUSTFLAGS','RUSTC_WRAPPER','RUSTC_WORKSPACE_WRAPPER')):
        raise ValueError('컴파일 semantic override는 비교하지 않습니다')
    target = ROOT/'.work/target-pressure'
    components._ancestors(target)
    components.fresh(target)
    env['CARGO_TARGET_DIR'] = str(target); env['CARGO_BUILD_JOBS'] = str(jobs)
    env['CARGO_PROFILE_DEV_DEBUG'] = '0'; env['CARGO_PROFILE_TEST_DEBUG'] = '0'
    env.pop('GH_TOKEN',None)
    probe = WindowsProbe(); first = probe.sample()
    cpu = os.cpu_count()
    if cpu != 4 or not 14*GIB <= first['totalPhysicalBytes'] <= 18*GIB:
        raise ValueError('동일한 표준 4 logical CPU/16 GiB급 runner 비교가 아닙니다')
    if first['availablePhysicalBytes'] <= MIN_FREE: raise ValueError('cold compiler 시작 전 RAM 부족')
    info = {'formatVersion':1, **current, 'jobs':jobs, 'command':list(command), 'workingDirectory':cwd.relative_to(ROOT).as_posix(),
            'runnerOS':os.getenv('RUNNER_OS'), 'runnerArchitecture':os.getenv('RUNNER_ARCH'), 'runnerImageVersion':os.getenv('ImageVersion'),
            'logicalCpuCount':cpu, 'observedInitialMemory':first, 'rustVersion':version, 'rustupToolchain':toolchain,
            'cargoTargetInitiallyAbsent':True, 'actionsCacheUsed':False, 'workload':workload,
            'timingScope':'Compiler parent process wall time includes Cargo dependency/Skia downloads; excludes checkout/upstream preparation/Rust installation',
            'sampleIntervalSeconds':2, 'abortAvailablePhysicalBytes':MIN_FREE,
            'compilerTimeLimitSeconds':22*60,
            'launcherWrapper':[] if workload == 'cli' else ['cmd.exe','/d','/c'],
            'abortMechanism':'unchanged ci/build_progress.py terminate_owned; taskkill only a still-live owned compiler parent PID and its tree',
            'sourceContractSha256':components.sha(OUTPUT/'source-contract.json'),
            'sourceConfigSha256':components.sha(OUTPUT/'source-config.json'),
            'productionBuildScriptSha256':components.sha(ROOT/'scripts/build-msix.ps1')}
    write_new(OUTPUT/'compile-context.json',encoded(info),JSON_CAP)
    state = {'observedLogBytes':0,'retainedLogBytes':0,'logCapExceeded':False,'readerError':False,'parentExitMonotonicNs':None}
    samples = []; abort = None; process = None; reader = None; code = 1
    started = utc(); start = time.monotonic_ns(); finish = start
    stopped = threading.Event()
    log_path = OUTPUT/'compile.log'; sample_path = OUTPUT/'system-samples.jsonl'
    try:
        with log_path.open('xb') as log, sample_path.open('xb') as raw_samples:
            runner_command = list(command) if workload == 'cli' else ['cmd.exe','/d','/c',*command]
            start = time.monotonic_ns()
            process = subprocess.Popen(runner_command,cwd=cwd,env=env,shell=False,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,bufsize=0)
            def wait_for_parent():
                process.wait()
                state['parentExitMonotonicNs'] = time.monotonic_ns()
                stopped.set()
            waiter = threading.Thread(target=wait_for_parent,daemon=True); waiter.start()
            def drain():
                try:
                    while chunk := process.stdout.read(8192):
                        state['observedLogBytes'] += len(chunk)
                        permitted = chunk[:max(0,LOG_CAP-state['retainedLogBytes'])]
                        log.write(permitted); log.flush(); sys.stdout.buffer.write(permitted); sys.stdout.buffer.flush()
                        state['retainedLogBytes'] += len(permitted)
                        if state['observedLogBytes'] > LOG_CAP:
                            state['logCapExceeded'] = True; stopped.set(); break
                except BaseException:
                    state['readerError'] = True; stopped.set()
            reader = threading.Thread(target=drain,daemon=True); reader.start()
            previous_sample = first
            while True:
                stopped.wait(2)
                observed = probe.sample()
                interval = cpu_interval(previous_sample['cpuTimes'],observed['cpuTimes'])
                sample = {**observed, **interval, 'compileElapsedSeconds':(observed['monotonicNs']-start)/1e9}
                raw = encoded(sample)
                if raw_samples.tell()+len(raw) > SAMPLES_CAP: abort = 'sampleCapExceeded'; break
                raw_samples.write(raw); raw_samples.flush(); samples.append(sample); previous_sample = observed
                if observed['availablePhysicalBytes'] <= MIN_FREE: abort = 'memoryFloorReached'; break
                if state['logCapExceeded']: abort = 'logCapExceeded'; break
                if state['readerError']: abort = 'logReaderFailed'; break
                if time.monotonic_ns()-start > 22*60*1_000_000_000: abort = 'compileTimeLimit'; break
                if process.poll() is not None:
                    code = process.returncode; break
            finish = state['parentExitMonotonicNs'] or time.monotonic_ns()
            if abort is not None and process.poll() is None: terminate_owned(process)
            code = process.wait(timeout=30); waiter.join(timeout=1)
            finish = state['parentExitMonotonicNs'] or finish
            reader.join(timeout=10)
            if reader.is_alive(): raise ValueError('소유 compiler 원본 stdout이 완료되지 않았습니다')
            process.stdout.close()
    except BaseException:
        if abort is None: abort = 'diagnosticException'
        if process is not None and process.poll() is None: terminate_owned(process)
        if reader is not None: reader.join(timeout=10)
        finish = time.monotonic_ns()
        raise
    finally:
        source_unchanged = False
        if abort is None and code == 0:
            _, after_contract = components.source_contract(source,components.configured())
            source_unchanged = (components.encoded(after_contract,compact=True) == before_contract
                                and components.encoded(components.configured(),compact=True) == before_config
                                and execution() == current)
            if not source_unchanged: abort = 'preparedSourceChanged'
        summary = {**info, 'startedUtc':started, 'finishedUtc':utc(), 'cargoWallSeconds':(finish-start)/1e9,
                   'cargoExitCode':code, 'diagnosticAbortReason':abort, 'compileSucceeded':abort is None and code == 0,
                   'preparedSourceUnchangedAfterCompile':source_unchanged,
                   'originalLogSha256':components.sha(log_path), 'originalSamplesSha256':components.sha(sample_path), **state,
                   'resourceStatistics':statistics(samples) if samples else None}
        if summary['compileSucceeded']:
            executable = target/('x86_64-pc-windows-msvc/release/'+('rhwp.exe' if workload == 'cli' else 'hop-desktop.exe'))
            with executable.open('rb') as stream: summary['compiledPeMachine'] = components.pe_machine(stream.read(4096),'x64')
            summary['compiledExecutableBytes'] = executable.stat().st_size
            summary['compiledExecutableSha256'] = components.sha(executable)
        write_new(OUTPUT/'summary.json',encoded(summary),JSON_CAP)
        total = sum(path.stat().st_size for path in OUTPUT.iterdir())
        if total > 16*1024*1024: raise ValueError('진단 원본 전체 16 MiB 제한 위반')
        print('성능 진단 요약:',json.dumps({'jobs':jobs,'cargoWallSeconds':summary['cargoWallSeconds'],'compileSucceeded':summary['compileSucceeded'],
                         'resourceStatistics':summary['resourceStatistics'],'sourceQualification':False},ensure_ascii=False))
    if abort is not None or code != 0: return 1
    return 0


def main():
    parser = argparse.ArgumentParser(); sub = parser.add_subparsers(dest='mode',required=True)
    sub.add_parser('download-wasm')
    measure = sub.add_parser('measure'); measure.add_argument('--jobs',type=int,choices=LEVELS,required=True)
    measure.add_argument('--workload',choices=('cli','editor-release'),required=True)
    args = parser.parse_args()
    if args.mode == 'download-wasm': download_wasm(); return 0
    return compile_measure(args.jobs,args.workload)


if __name__ == '__main__':
    try: sys.exit(main())
    except Exception as error:
        print('성능 진단 실패:',type(error).__name__,file=sys.stderr); sys.exit(1)
