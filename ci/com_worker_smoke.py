"""별도 Windows COM dev 실행 파일의 실제 native 실행 증거만 수집한다.

제품/Store/패키지 활성화 qualification을 선언하지 않는다. 암호·전체 환경은
출력하지 않으며, 소유 subprocess의 출력은 파일별 상한 안에서 보존한다.
"""
from pathlib import Path
import argparse
import hashlib
import json
import ntpath
import os
import platform
import re
import struct
import subprocess
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'overlay/com-worker/Cargo.toml'
ARCHITECTURES = {'x64': ('x86_64-pc-windows-msvc', 0x8664),
                 'arm64': ('aarch64-pc-windows-msvc', 0xaa64)}
FIXED_CLSID = 'c6c4d247-b4f0-563d-a649-4765796e3164'
GUID = re.compile(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z')
UNIT_CASES = {
    'opengeul_com_worker': {
        'windows::tests::temporary_registration_collision_preserves_existing_values',
        'windows::tests::changed_owner_prevents_deleting_a_registration',
        'windows::tests::partial_owned_server_is_cleaned_without_removing_unknown_values',
        'windows::tests::fixed_package_class_is_never_a_temporary_cleanup_target',
        'windows::tests::current_parent_pid_cannot_be_attached_as_a_terminable_worker',
        'windows::tests::owned_activation_only_accepts_exact_creator_registration',
        'windows::tests::pipe_metadata_grant_compares_original_client_open',
        'windows::tests::pipe_metadata_grant_denies_instance_creation_in_access_check',
    },
    'wire': {
        'protected_header_preserves_argv_and_raw_environment',
        'admission_is_single_job_and_rejected_metadata_does_not_consume_it',
        'wrong_nonce_parent_worker_or_version_is_rejected',
        'malformed_duplicate_unknown_and_oversize_headers_are_rejected',
        'embedded_nul_argv_relative_cwd_and_invalid_environment_are_rejected',
        'bootstrap_names_are_local_fixed_namespace_and_guid_checked',
        'same_user_does_not_allow_a_different_logon_integrity_or_elevation',
        'simultaneous_begin_requests_accept_exactly_one_job',
    },
}
TRANSPORT_CASES = [
    'unicode-argv', 'password-stdin-bytes-eof', 'absent-stdin-eof', 'partial-exit-1',
    'difference-exit-3', 'non-json-exit-3', 'empty-stdout-error', 'worker-abort',
    'same-parent-next-job', 'cwd-synthetic-environment', 'owned-native-worker-key-cleanup',
]
IDENTITY_KEYS = {'pid', 'imagePath', 'processMachine', 'nativeMachine', 'elevated',
                 'enableLUA', 'packaged', 'bootstrapClsid', 'temporaryKeyAbsentBeforeDispatch'}
SOURCE_FILES = [
    'ci/com_worker_smoke.py', 'overlay/com-worker/Cargo.toml', 'overlay/com-worker/Cargo.lock',
    'overlay/com-worker/src/mod.rs', 'overlay/com-worker/src/wire.rs',
    'overlay/com-worker/src/windows.rs', 'overlay/com-worker/tests/wire.rs',
    'overlay/com-worker/tests/transport_windows.rs', 'scripts/com_worker.py',
]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, 'JSON의 중복 키를 허용하지 않습니다')
        value[key] = item
    return value


def decode_json(raw, limit):
    require(0 < len(raw) <= limit, 'JSON 크기가 허용 범위를 벗어났습니다')
    return json.loads(raw.decode('utf-8'), object_pairs_hook=unique_object,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('유한 JSON 값만 허용합니다')))


def sha_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(65536), b''):
            digest.update(chunk)
    return digest.hexdigest()


def pe_machine(path):
    require(path.is_file() and not path.is_symlink(), '실행 파일은 소유한 일반 파일이어야 합니다')
    require(64 <= path.stat().st_size <= 64 * 1024 * 1024, '실행 파일 크기 상한을 초과했습니다')
    with path.open('rb') as handle:
        dos = handle.read(64)
        require(dos[:2] == b'MZ', '실행 파일의 DOS 서명이 없습니다')
        offset = struct.unpack_from('<I', dos, 60)[0]
        require(64 <= offset <= 1024 * 1024, 'PE 헤더 위치가 허용 범위를 벗어났습니다')
        handle.seek(offset)
        header = handle.read(26)
    require(len(header) == 26 and header[:4] == b'PE\0\0', 'PE 서명이 없습니다')
    require(struct.unpack_from('<H', header, 24)[0] == 0x20b, '64비트 native PE만 허용합니다')
    return struct.unpack_from('<H', header, 4)[0]


def parse_build(raw, manifest, target_directory, architecture):
    require(len(raw) <= 8 * 1024 * 1024, 'Cargo JSON 출력 상한을 초과했습니다')
    manifest = manifest.resolve(strict=True)
    allowed = target_directory.resolve(strict=True)
    found = {}
    expected = set(UNIT_CASES) | {'transport_windows'}
    finished = []
    for line in raw.splitlines():
        require(len(line) <= 256 * 1024, 'Cargo JSON 한 줄의 상한을 초과했습니다')
        if not line.strip():
            continue
        item = decode_json(line, 256 * 1024)
        require(type(item) is dict, 'Cargo JSON 항목은 객체여야 합니다')
        if item.get('reason') == 'build-finished':
            finished.append(item.get('success') is True)
        if item.get('reason') != 'compiler-artifact':
            continue
        profile = item.get('profile')
        require(type(profile) is dict and type(profile.get('test')) is bool, 'Cargo profile.test 형식이 잘못됐습니다')
        if not profile['test'] or item.get('executable') is None:
            continue
        require(type(item.get('manifest_path')) is str, 'Cargo manifest 경로가 없습니다')
        if Path(item['manifest_path']).resolve(strict=True) != manifest:
            continue
        target = item.get('target')
        require(type(target) is dict and target.get('name') in expected, '예상하지 않은 자체 test executable입니다')
        name = target['name']
        require(name not in found, '동일 test executable이 중복되었습니다')
        require(target.get('kind') == (['lib'] if name == 'opengeul_com_worker' else ['test']), 'test target 종류가 달라졌습니다')
        require(type(item['executable']) is str, 'test executable 경로 형식이 잘못됐습니다')
        original = Path(item['executable'])
        require(not original.is_symlink(), 'test executable symlink는 허용하지 않습니다')
        path = original.resolve(strict=True)
        require(path.is_relative_to(allowed) and path.suffix.lower() == '.exe', 'test executable이 소유 target 폴더 밖에 있습니다')
        require(pe_machine(path) == ARCHITECTURES[architecture][1], 'test executable PE 아키텍처가 다릅니다')
        found[name] = path
    require(finished == [True], '정확히 한 번 성공한 Cargo build-finished가 필요합니다')
    require(set(found) == expected, '정확한 native test executable 세 개가 필요합니다')
    return found


def verify_unit_result(raw, name):
    require(len(raw) <= 1024 * 1024, 'native unit 출력 상한을 초과했습니다')
    text = raw.decode('utf-8')
    summaries = re.findall(r'^test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored; '
                           r'(\d+) measured; (\d+) filtered out; finished in [^\r\n]+\r?$', text, re.MULTILINE)
    require(len(summaries) == 1, 'native unit 성공 summary 하나가 필요합니다')
    require(tuple(map(int, summaries[0])) == (len(UNIT_CASES[name]), 0, 0, 0, 0), 'native unit 수·실패·skip가 다릅니다')
    cases = re.findall(r'^test ([A-Za-z0-9_:]+) \.\.\. ok\r?$', text, re.MULTILINE)
    require(len(cases) == len(UNIT_CASES[name]) and set(cases) == UNIT_CASES[name], 'native unit case ID가 다릅니다')
    return {'passed': len(cases), 'failed': 0, 'ignored': 0, 'filteredOut': 0, 'cases': sorted(cases)}


def verify_transport(raw, executable, architecture):
    value = decode_json(raw.strip(), 256 * 1024)
    keys = {'formatVersion', 'probe', 'casesPassed', 'parent', 'worker', 'abortExitCode',
            'qualification', 'actualMcpProductTests', 'installedPackageActivationTested'}
    require(type(value) is dict and set(value) == keys, 'COM 영수증 필드가 다릅니다')
    require(type(value['formatVersion']) is int and value['formatVersion'] == 1, 'COM 영수증 버전이 다릅니다')
    require(value['probe'] == 'COM SCM dev-only transport', 'COM probe 종류가 다릅니다')
    require(value['casesPassed'] == TRANSPORT_CASES, '실제 COM 시나리오 11개가 정확히 필요합니다')
    for field in ('qualification', 'actualMcpProductTests', 'installedPackageActivationTested'):
        require(value[field] is False, '이 probe의 제한된 qualification 범위를 변경할 수 없습니다')
    code = value['abortExitCode']
    require(type(code) is int and -(2 ** 31) <= code < 2 ** 31 and code != 0, 'worker abort의 실제 실패 종료 코드가 필요합니다')
    parent, worker = value['parent'], value['worker']
    for identity in (parent, worker):
        require(type(identity) is dict and set(identity) == IDENTITY_KEYS, 'COM process identity 필드가 다릅니다')
        require(type(identity['pid']) is int and 0 < identity['pid'] <= 0xffffffff, '실제 process PID가 필요합니다')
        require(type(identity['imagePath']) is str and 0 < len(identity['imagePath']) <= 32768
                and '\0' not in identity['imagePath'], 'process image 경로가 잘못됐습니다')
        require(ntpath.normcase(ntpath.normpath(identity['imagePath'])) == ntpath.normcase(ntpath.normpath(str(executable))),
                'COM process image는 실제 빌드한 동일 실행 파일이어야 합니다')
        require(type(identity['processMachine']) is int and identity['processMachine'] == 0,
                '에뮬레이션이 아닌 native process가 필요합니다')
        require(type(identity['nativeMachine']) is int and identity['nativeMachine'] == ARCHITECTURES[architecture][1],
                '실제 native machine이 target과 다릅니다')
        require(type(identity['elevated']) is bool, '실제 token elevation 값이 필요합니다')
        require(type(identity['enableLUA']) is int and identity['enableLUA'] in (0, 1), '실제 EnableLUA 값을 읽어야 합니다')
        require(identity['packaged'] is False, '독립 probe를 MSIX 활성화 검사로 사용할 수 없습니다')
    require(parent['pid'] != worker['pid'], 'COM worker는 별도 프로세스여야 합니다')
    require(parent['bootstrapClsid'] is None and parent['temporaryKeyAbsentBeforeDispatch'] is None, '부모는 worker bootstrap이 아니어야 합니다')
    require(type(worker['bootstrapClsid']) is str and GUID.fullmatch(worker['bootstrapClsid'])
            and worker['bootstrapClsid'] != FIXED_CLSID, 'fresh portable CLSID가 필요합니다')
    require(worker['temporaryKeyAbsentBeforeDispatch'] is True, '작업 시작 전 소유 임시 등록 삭제가 필요합니다')
    for field in ('elevated', 'enableLUA', 'imagePath', 'processMachine', 'nativeMachine', 'packaged'):
        require(parent[field] == worker[field], 'COM parent/worker의 image·권한·native 맥락이 다릅니다')
    return value


def bounded_process(command, stdout_path, stderr_path, timeout, limit, environment=None):
    # 정확히 우리가 실행한 subprocess handle만 중단한다. image-name kill은 하지 않는다.
    process = subprocess.Popen(command, cwd=ROOT, env=environment,
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    overflow = threading.Event()
    errors = []

    def drain(stream, path):
        count = 0
        try:
            with path.open('xb') as handle:
                while chunk := stream.read(65536):
                    remaining = limit - count
                    if remaining > 0:
                        handle.write(chunk[:remaining])
                    count += len(chunk)
                    if count > limit:
                        overflow.set()
                        process.kill()
                        break
        except Exception as error:
            errors.append(type(error).__name__)
            process.kill()
        finally:
            stream.close()

    threads = [threading.Thread(target=drain, args=(process.stdout, stdout_path), daemon=True),
               threading.Thread(target=drain, args=(process.stderr, stderr_path), daemon=True)]
    for thread in threads:
        thread.start()
    timed_out = False
    try:
        code = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        code = process.wait(timeout=10)
    for thread in threads:
        thread.join(timeout=10)
    require(not any(thread.is_alive() for thread in threads), '소유 subprocess 출력 회수가 끝나지 않았습니다')
    require(not timed_out, '소유 subprocess 실행 제한 시간을 초과했습니다')
    require(not overflow.is_set() and not errors, 'subprocess 출력 상한 또는 파일 회수 오류입니다')
    return code


def save_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')


def github_stamp():
    fields = {key: os.environ.get(key, '') for key in
              ('GITHUB_SHA', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'GITHUB_JOB', 'GITHUB_REPOSITORY',
               'GITHUB_REF', 'GITHUB_EVENT_NAME')}
    require(re.fullmatch(r'[0-9a-f]{40}', fields['GITHUB_SHA']), '실제 source commit이 필요합니다')
    require(re.fullmatch(r'[1-9][0-9]{0,19}', fields['GITHUB_RUN_ID']), '실제 source run ID가 필요합니다')
    require(fields['GITHUB_RUN_ATTEMPT'] == '1', '승인한 첫 실행만 관측합니다')
    require(re.fullmatch(r'[A-Za-z0-9_-]{1,100}', fields['GITHUB_JOB']), '실제 job ID가 필요합니다')
    require(fields['GITHUB_REPOSITORY'] == 'ATLKR/OpenGeul', '고정 저장소만 관측합니다')
    require(fields['GITHUB_REF'] == 'refs/heads/diagnostic/native-com-113'
            and fields['GITHUB_EVENT_NAME'] == 'workflow_dispatch', '고정 진단 dispatch만 관측합니다')
    return fields


def controller_architecture():
    # Python controller의 에뮬레이션 여부는 제품/worker의 native 조건과 분리한다.
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.IsWow64Process2.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.USHORT), ctypes.POINTER(wintypes.USHORT)]
    kernel.IsWow64Process2.restype = wintypes.BOOL
    process, native = wintypes.USHORT(), wintypes.USHORT()
    require(kernel.IsWow64Process2(kernel.GetCurrentProcess(), ctypes.byref(process), ctypes.byref(native)),
            'Python controller의 실제 Windows 아키텍처를 읽지 못했습니다')
    return {'processMachine': process.value, 'nativeMachine': native.value,
            'platformMachineReported': platform.machine()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--architecture', choices=ARCHITECTURES, required=True)
    parser.add_argument('--target', required=True)
    parser.add_argument('--toolchain', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    require(not any(output.iterdir()) and not args.output.is_symlink(), '증거 폴더는 빈 소유 디렉터리여야 합니다')
    receipt = {'formatVersion': 1, 'status': 'started', 'diagnosticOnly': True, 'qualification': False,
               'architecture': args.architecture, 'target': args.target, 'toolchain': args.toolchain}
    save_json(output / 'result.json', receipt)
    phase = 'preflight'
    try:
        require(os.name == 'nt', '실제 Windows에서만 실행합니다')
        require(args.target == ARCHITECTURES[args.architecture][0], 'target과 architecture가 다릅니다')
        require(args.toolchain == '1.93.1-' + args.target, '고정 Rust native toolchain만 사용합니다')
        receipt['controller'] = controller_architecture()
        require(receipt['controller']['nativeMachine'] == ARCHITECTURES[args.architecture][1], '실제 Windows host 아키텍처가 다릅니다')
        require(receipt['controller']['processMachine'] in ({0} if args.architecture == 'x64' else {0, 0x8664}),
                'Python controller 아키텍처가 지원 범위를 벗어났습니다')
        receipt['github'] = github_stamp()
        head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, check=True, timeout=10).stdout.decode().strip()
        require(head == receipt['github']['GITHUB_SHA'], 'checkout commit이 실제 dispatch source와 다릅니다')
        receipt['sourceFiles'] = {name: {'sha256': sha_file(ROOT / name), 'bytes': (ROOT / name).stat().st_size} for name in SOURCE_FILES}
        code = bounded_process(['rustup', 'run', args.toolchain, 'rustc', '-vV'],
                               output / 'rustc.stdout.txt', output / 'rustc.stderr.txt', 20, 65536)
        require(code == 0, 'native Rust toolchain 검사가 실패했습니다')
        compiler = (output / 'rustc.stdout.txt').read_text(encoding='utf-8')
        require('release: 1.93.1\n' in compiler and 'host: ' + args.target + '\n' in compiler, '실제 Rust release/host가 다릅니다')
        target_root = ROOT / '.work/com-worker-smoke-target'
        environment = os.environ.copy()
        environment['CARGO_TARGET_DIR'] = str(target_root)
        environment['CARGO_INCREMENTAL'] = '0'
        phase = 'build'
        command = ['rustup', 'run', args.toolchain, 'cargo', 'test', '--manifest-path', str(MANIFEST),
                   '--no-run', '--message-format=json', '--locked', '--target', args.target]
        code = bounded_process(command, output / 'build.jsonl', output / 'build.stderr.txt', 420, 8 * 1024 * 1024, environment)
        require(code == 0, '실제 Windows test executable 빌드가 실패했습니다')
        executables = parse_build((output / 'build.jsonl').read_bytes(), MANIFEST, target_root / args.target, args.architecture)
        receipt['executables'] = {name: {'path': str(path), 'sha256': sha_file(path), 'bytes': path.stat().st_size,
                                       'peMachine': pe_machine(path)} for name, path in executables.items()}
        phase = 'native-execution'
        deadline = time.monotonic() + 240
        results = {}
        for name in ('opengeul_com_worker', 'wire', 'transport_windows'):
            remaining = deadline - time.monotonic()
            require(remaining > 0, 'native 실행 전체 240초 상한을 초과했습니다')
            path = executables[name]
            require(sha_file(path) == receipt['executables'][name]['sha256'], '실행 전에 native EXE가 바뀌었습니다')
            code = bounded_process([str(path)], output / (name + '.stdout.txt'), output / (name + '.stderr.txt'),
                                   remaining, 1024 * 1024)
            require(code == 0, 'native dev 검사 실행이 실패했습니다: ' + name)
            require(sha_file(path) == receipt['executables'][name]['sha256'], '실행 뒤 native EXE가 바뀌었습니다')
            raw = (output / (name + '.stdout.txt')).read_bytes()
            if name in UNIT_CASES:
                results[name] = verify_unit_result(raw, name)
            else:
                results[name] = verify_transport(raw, path, args.architecture)
                save_json(output / 'native-transport.json', results[name])
        receipt['results'] = results
        require(all(sha_file(ROOT / name) == binding['sha256'] for name, binding in receipt['sourceFiles'].items()),
                '실행 중 검토한 COM 원문 또는 잠금 파일이 바뀌었습니다')
        receipt['sourceFilesUnchanged'] = True
        receipt['transportImageBinding'] = {
            'parentImagePath': results['transport_windows']['parent']['imagePath'],
            'workerImagePath': results['transport_windows']['worker']['imagePath'],
            'sameCompiledExecutableSha256': receipt['executables']['transport_windows']['sha256'],
            'compiledExecutableUnchangedBeforeAfter': True,
            'livePidRequeryAfterExit': False,
        }
        receipt['scope'] = {'portableComTransport': True, 'installedMsixActivation': False,
                            'actualMcpProductTools': False, 'wholeWack': False,
                            'forcedParentAbortCleanup': False, 'otherTokenRejectionExecuted': False}
        receipt['registrationContext'] = {'hive': 'HKLM' if results['transport_windows']['parent']['elevated'] else 'HKCU',
                                          'elevated': results['transport_windows']['parent']['elevated'],
                                          'enableLUA': results['transport_windows']['parent']['enableLUA']}
        receipt['status'] = 'passed'
    except Exception as error:
        receipt['status'] = 'failed'
        receipt['failurePhase'] = phase
        # exception에 stdout/환경/암호를 붙이지 않는다. 원본 bounded 출력은 별도 파일이다.
        receipt['error'] = str(error)[:512]
        save_json(output / 'result.json', receipt)
        raise
    receipt['evidence'] = {path.name: {'sha256': sha_file(path), 'bytes': path.stat().st_size}
                           for path in sorted(output.iterdir()) if path.is_file() and path.name != 'result.json'}
    save_json(output / 'result.json', receipt)
    print('실제 Windows COM dev 실행 증거를 보존했습니다. 제품·MSIX·WACK 판정은 별도입니다.')


if __name__ == '__main__':
    main()
