"""같은 Editor 작업의 단계·원본 로그를 제한하여 보존한다. 제품 검증을 대체하지 않는다."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import windows_components as components

STAGES = {'Prepare': 'prepare', 'NativeTests': 'native-tests', 'Release': 'release'}
MAX_TOTAL = 16 * 1024 * 1024
MAX_LOG = MAX_TOTAL - 4096
GIB = 1024 ** 3


def resource_decision(cpu, total, available, cpu_busy=None):
    if (any(type(v) is not int for v in (cpu, total, available)) or cpu < 1
            or total < 0 or not 0 <= available <= total
            or cpu_busy is not None and (type(cpu_busy) is not int or not 0 <= cpu_busy <= 100)):
        raise ValueError('잘못된 CPU·메모리 관측입니다')
    if cpu == 1: return {'jobs': 1, 'reason': 'singleCore'}
    if cpu_busy is None: return {'jobs': min(cpu, 2), 'reason': 'cpuUnavailable'}
    if cpu_busy >= 75: return {'jobs': 1, 'reason': 'cpuBusy'}
    if cpu_busy > 25 or cpu < 4: return {'jobs': min(cpu, 2), 'reason': 'cpuLimited'}
    if total < 14*GIB or available < 12*GIB: return {'jobs': 2, 'reason': 'memoryLimited'}
    return {'jobs': 4, 'reason': 'headroom'}


def select_jobs(cpu, total, available, cpu_busy=None):
    return resource_decision(cpu, total, available, cpu_busy)['jobs']


def build_command(stage, architecture):
    if stage not in STAGES or architecture not in ('x64', 'arm64'):
        raise ValueError('알 수 없는 빌드 단계 또는 아키텍처입니다')
    return ['pwsh', '-NoLogo', '-NoProfile', '-File', 'scripts/build-msix.ps1', '-Phase', 'Editor',
            '-EditorStage', stage, '-WasmDirectory', 'wasm-input', '-Architecture', architecture]


def execution(architecture):
    build_command('Prepare', architecture)
    source = components.identity()
    expected_job = 'windows-editor' + ('-arm64' if architecture == 'arm64' else '')
    if os.getenv('GITHUB_JOB') != expected_job:
        raise ValueError('해당 아키텍처의 Editor 작업이 아닙니다')
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, timeout=15).decode().strip()
    if head != source['commit']:
        raise ValueError('현재 checkout과 실행 소스가 다릅니다')
    return source


def snapshot(architecture):
    source = execution(architecture)
    config = components.configured()
    _, contract = components.source_contract(ROOT/'.work/hop', config)
    fixtures, _ = components.tree(ROOT/'.work/table-fixtures', MAX_TOTAL)
    value = {'config': config, 'source': contract, 'tableFixtures': fixtures,
             'progressHelperSha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    return {**source, 'architecture': architecture,
            'contextSha256': hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()}


def state_path(architecture):
    build_command('Prepare', architecture)
    return ROOT/f'.work/editor-build-state-{architecture}.json'


def read_state(architecture):
    try:
        return components.read_json(state_path(architecture))
    except OSError:
        raise ValueError('필수 이전 단계의 상태가 없습니다') from None


def verify_stage(stage, architecture):
    build_command(stage, architecture)
    current = snapshot(architecture)
    if stage == 'Prepare':
        if state_path(architecture).exists():
            raise ValueError('완료한 준비 단계는 덮어쓰지 않습니다')
        return current
    state = read_state(architecture)
    previous = ['Prepare'] if stage == 'NativeTests' else ['Prepare', 'NativeTests']
    if type(state.get('formatVersion')) is not int or state != {'formatVersion': 1, **current, 'completed': previous}:
        raise ValueError('이전 단계 성공 또는 현재 소스·시험 입력이 일치하지 않습니다')
    if stage == 'Release':
        files, _ = components.tree(ROOT/'.work/e2e-fixtures', MAX_TOTAL)
        digest = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        original = components.read_json(ROOT/f'.work/editor-fixtures-{architecture}.json')
        if original != {'sha256': digest}:
            raise ValueError('네이티브 시험으로 만든 fixture가 변경되었습니다')
    return current


def complete_stage(stage, architecture):
    current = snapshot(architecture)
    if stage == 'Prepare':
        components.fresh(state_path(architecture))
        completed = []
    else:
        verify_stage(stage, architecture)
        completed = read_state(architecture)['completed']
    if stage == 'NativeTests':
        files, _ = components.tree(ROOT/'.work/e2e-fixtures', MAX_TOTAL)
        digest = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        path = ROOT/f'.work/editor-fixtures-{architecture}.json'
        components.fresh(path)
        path.write_bytes(components.encoded({'sha256': digest}))
    state_path(architecture).write_bytes(components.encoded({'formatVersion': 1, **current, 'completed': completed+[stage]}))


def terminate_owned(process):
    if process.poll() is None:
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                           capture_output=True, timeout=15, check=True)
        else:
            process.kill()
    process.wait(timeout=30)


def run_stage(stage, architecture, *, stream=None, terminate=None):
    command = build_command(stage, architecture)
    if stage != 'Prepare': verify_stage(stage, architecture)
    elif state_path(architecture).exists(): raise ValueError('기존 준비 상태를 보존합니다')
    folder = ROOT/f'.work/build-progress/editor-{architecture}/{STAGES[stage]}'
    components.fresh(folder)
    folder.mkdir(parents=True)
    current = execution(architecture) if stage == 'Prepare' else snapshot(architecture)
    stream = sys.stdout.buffer if stream is None else stream
    terminate = terminate_owned if terminate is None else terminate
    started = datetime.now(timezone.utc).isoformat()
    process = None; retained = 0; observed = 0; exceeded = False; code = 1; complete = False; succeeded = False
    try:
        with (folder/'build.log').open('xb') as log:
            process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       shell=False, bufsize=0)
            while chunk := process.stdout.read(8192):
                observed += len(chunk)
                permitted = chunk[:MAX_LOG-retained]
                log.write(permitted); stream.write(permitted); stream.flush(); retained += len(permitted)
                if observed > MAX_LOG:
                    exceeded = True; terminate(process); break
            if not exceeded:
                code = process.wait(); complete = True
            process.stdout.close()
        if complete and code == 0:
            complete_stage(stage, architecture)
            succeeded = True
    except BaseException:
        if code == 0: code = 1
        if process is not None: terminate(process)
        raise
    finally:
        receipt = {'formatVersion': 1, **current, 'job': os.getenv('GITHUB_JOB'), 'architecture': architecture,
                   'phase': stage, 'purpose': 'build-progress', 'startedUtc': started,
                   'finishedUtc': datetime.now(timezone.utc).isoformat(), 'exitCode': code,
                   'complete': complete, 'stageSucceeded': succeeded,
                   'logLimitExceeded': exceeded, 'observedBytes': observed,
                   'retainedBytes': retained, 'logSha256': hashlib.sha256((folder/'build.log').read_bytes()).hexdigest(),
                   'sourceQualified': False}
        raw = components.encoded(receipt)
        if len(raw) > 4096 or retained+len(raw) > MAX_TOTAL:
            raise ValueError('단계 로그·영수증 제한을 초과했습니다')
        (folder/'progress.json').write_bytes(raw)
    return code if not exceeded else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    jobs = commands.add_parser('jobs')
    for key in ('cpu', 'total-memory', 'available-memory'): jobs.add_argument('--'+key, type=int, required=True)
    jobs.add_argument('--cpu-busy', type=int)
    jobs.add_argument('--json', action='store_true')
    for mode in ('run', 'verify'):
        item = commands.add_parser(mode); item.add_argument('--stage', choices=STAGES, required=True)
        item.add_argument('--architecture', choices=('x64', 'arm64'), required=True)
    args = parser.parse_args()
    if args.command == 'jobs':
        decision = resource_decision(args.cpu, args.total_memory, args.available_memory, args.cpu_busy)
        print(json.dumps(decision, separators=(',', ':')) if args.json else decision['jobs'])
    elif args.command == 'verify': verify_stage(args.stage, args.architecture)
    else:
        if os.name != 'nt': raise ValueError('실제 빌드 실행은 Windows 전용입니다')
        raise SystemExit(run_stage(args.stage, args.architecture))


if __name__ == '__main__':
    try: main()
    except (ValueError, OSError, subprocess.SubprocessError):
        print('::error::빌드 단계 또는 제한된 로그 보존이 실패했습니다. 원래 실패를 통과로 바꾸지 않습니다.')
        raise SystemExit(1) from None
