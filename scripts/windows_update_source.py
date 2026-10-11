"""고정 원본 릴리스의 읽기 전용 Windows HTTPS 진단 준비. 기본 상태는 실행 거부."""
from __future__ import annotations
from contextlib import contextmanager, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = 'ATLKR/OpenGeul'
DIAGNOSTIC_REF = 'refs/heads/codex/diag-windows-store-update-68'
SOURCE_COMMIT = 'b3c8b61d01731dc1e39357034d9c489a3ea829a9'
SOURCE_RUN_ID = 38181680763
SOURCE_TAG = 'v1.1.3-dev.68.1'
STORE_URL = 'https://apps.microsoft.com/detail/9PJH0T3PHRMF'
METADATA_URL = 'https://opengeul.allenlim.net/api/store-release.json'
APP_IDENTIFIER = 'org.allenlabs.opengeul'
SETTINGS_FILE = 'opengeul-updates.json'
WORK = ROOT / '.work/windows-update-probe'
MAX_ASSETS = 96 * 1024 * 1024
ASSET_NAMES = frozenset({'AppxManifest.xml', 'OpenGeul_1.1.3.0_x64_development-unsigned.msix',
                       'OpenGeul_1.1.3_windows-x64_unsigned-portable.zip', 'SHA256SUMS.txt',
                       'provenance.json', 'rhwp-help.txt'})
REQUIRED_JOBS = frozenset({'preflight', 'wasm', 'windows-editor', 'windows-cli', 'build', 'release',
                         'msix-install', 'native-e2e (windows-2022)', 'native-e2e (windows-2025)',
                         'virtual-print (windows-2022)', 'virtual-print (windows-2025)',
                         'browser-e2e (chromium)', 'browser-e2e (firefox)', 'browser-e2e (webkit)',
                         'cleanup-transports'})
HELPER_HASHES = {
    'config/product.json': 'e861dd540271bcd7f212cefddd6d81699c5030e5f7fab8ab4cea85961b317f24',
    'scripts/buildkit.py': '9df65acb14819386242861f8af7571261ccd1e8cf7ab78925e8a45d869340151',
    'scripts/releasekit.py': '244e0d2bc1a8a72487d8838197435489e4ef90ad29e57265ed5c0a4f7217632d',
    'scripts/store_package.py': 'bd27878ae81f598e0ca26c61fa533905ed455263a5de81fd9ad409b42a952663',
    'e2e/prepare_payload.py': '74abced513f5447f94a45817f5d895b8b9dc9f621588d7de56dedbbaca8bc62c',
    'e2e/driver.py': '2421a78683c8e445cb6b915db8d3c94c35c7fa027267597b052adb4d11347025',
    'e2e/native_controls.py': 'c972fb0acbcd30b6fa9c703bd5c236be4d69f95dab6dcf9d08d0030b2acbe705',
    'e2e/webview_debug.py': '854cda2d89c6c32035137d24c0b1aa9148cf8d4dd4cf54f846291f083ec5112b',
    'e2e/requirements.txt': 'a1da0450c176004ce49c1bd4c92ffdde46870d7bad11c2c168a1a19ea54cd9c2',
    'e2e/ensure-webview2.ps1': '16e7a22dc7254c985a51f9e38965030d95b783ea4675281aa114884f488504bb',
}


class ProbeFailure(ValueError):
    """외부 원문·토큰·로컬 경로를 포함하지 않는 고정 실패 코드."""


def require(condition, code):
    if not condition: raise ProbeFailure(code)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''): digest.update(block)
    return digest.hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')


def no_duplicate_keys(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, 'duplicate_json_key')
        value[key] = item
    return value


def strict_json(raw, limit):
    require(len(raw) <= limit, 'json_too_large')
    try:
        return json.loads(raw.decode('utf-8', errors='strict'), object_pairs_hook=no_duplicate_keys,
                          parse_constant=lambda _: (_ for _ in ()).throw(ProbeFailure('invalid_json_number')))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ProbeFailure('invalid_json') from error


def inventory_digest(assets):
    return hashlib.sha256(canonical(sorted(assets, key=lambda asset: asset['name']))).hexdigest()


def read_pins():
    return strict_json((ROOT / 'config/windows-update-probe.json').read_bytes(), 16 * 1024)


def read_context():
    event_path = Path(os.environ.get('GITHUB_EVENT_PATH', ''))
    require(event_path.is_file() and event_path.stat().st_size <= 128 * 1024, 'missing_event_context')
    event = strict_json(event_path.read_bytes(), 128 * 1024)
    repo = event.get('repository', {})
    return {'repository': os.environ.get('GITHUB_REPOSITORY'), 'eventRepository': repo.get('full_name'), 'private': repo.get('private'),
            'actor': os.environ.get('GITHUB_ACTOR'), 'event': os.environ.get('GITHUB_EVENT_NAME'),
            'ref': os.environ.get('GITHUB_REF'), 'attempt': os.environ.get('GITHUB_RUN_ATTEMPT'),
            'sha': os.environ.get('GITHUB_SHA'), 'runId': os.environ.get('GITHUB_RUN_ID'),
            'job': os.environ.get('GITHUB_JOB'), 'actions': os.environ.get('GITHUB_ACTIONS'),
            'runnerEnvironment': os.environ.get('RUNNER_ENVIRONMENT'), 'runnerOS': os.environ.get('RUNNER_OS'),
            'workflowRef': os.environ.get('GITHUB_WORKFLOW_REF'), 'workflowSha': os.environ.get('GITHUB_WORKFLOW_SHA')}


def authorize(pins, context):
    # 이 순서가 중요하다. 승인/미정 계약은 gh 실행·HTTP·GUI 시작 전에 거부한다.
    require(pins.get('rootExecutionAuthorized') is True, 'root_execution_not_authorized')
    keys = {'formatVersion', 'rootExecutionAuthorized', 'sourceCommit', 'sourceRunId',
            'sourceRunNumber', 'sourceRunAttempt', 'sourceTag', 'sourceReleaseId',
            'assetInventorySha256', 'sourceAssets'}
    require(set(pins) == keys and type(pins['formatVersion']) is int and pins['formatVersion'] == 1,
            'invalid_pin_schema')
    for key, value in {'sourceCommit': SOURCE_COMMIT, 'sourceRunId': SOURCE_RUN_ID,
                       'sourceRunNumber': 68, 'sourceRunAttempt': 1, 'sourceTag': SOURCE_TAG}.items():
        require(type(pins[key]) is type(value) and pins[key] == value, 'wrong_source_pin')
    require(type(pins['sourceReleaseId']) is int and pins['sourceReleaseId'] > 0, 'release_id_unset')
    assets = pins['sourceAssets']
    require(type(assets) is list and len(assets) == 6, 'invalid_asset_inventory')
    for asset in assets:
        require(type(asset) is dict and set(asset) == {'id', 'name', 'size', 'sha256', 'digest'},
                'invalid_asset_schema')
        require(asset['name'] in ASSET_NAMES and type(asset['id']) is int and asset['id'] > 0
                and type(asset['size']) is int and 0 < asset['size'] <= MAX_ASSETS,
                'asset_pin_unset')
        require(isinstance(asset['sha256'], str) and re.fullmatch(r'[0-9a-f]{64}', asset['sha256'])
                and asset['digest'] == 'sha256:' + asset['sha256'], 'asset_digest_unset')
    require({a['name'] for a in assets} == ASSET_NAMES and len({a['id'] for a in assets}) == 6
            and sum(a['size'] for a in assets) <= MAX_ASSETS
            and pins['assetInventorySha256'] == inventory_digest(assets), 'asset_inventory_mismatch')
    expected = {'repository': REPOSITORY, 'eventRepository': REPOSITORY, 'private': False, 'actor': 'ATLKR',
                'event': 'workflow_dispatch', 'ref': DIAGNOSTIC_REF, 'attempt': '1',
                'job': 'windows-update-https', 'actions': 'true',
                'runnerEnvironment': 'github-hosted', 'runnerOS': 'Windows',
                'workflowRef': f'{REPOSITORY}/.github/workflows/store-package.yml@{DIAGNOSTIC_REF}'}
    require(all(type(context.get(k)) is type(v) and context.get(k) == v for k, v in expected.items())
            and isinstance(context.get('sha'), str) and re.fullmatch(r'[0-9a-f]{40}', context['sha'])
            and context.get('workflowSha') == context['sha']
            and isinstance(context.get('runId'), str) and re.fullmatch(r'[1-9][0-9]{0,19}', context['runId']),
            'wrong_execution_context')


def validate_local_helpers(context):
    require(all(sha256(ROOT / name) == digest for name, digest in HELPER_HASHES.items()), 'source_helpers_changed')
    result = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, check=True, capture_output=True, timeout=5)
    require(result.stdout.decode('ascii').strip() == context['sha'], 'checkout_commit_mismatch')


def github_get(path):
    # 경로는 호출자가 아래 고정 GET 목록에서만 만든다. 쓰기 명령·pagination·인수 입력은 없다.
    with tempfile.TemporaryFile() as output:
        process = subprocess.Popen(['gh', 'api', '--method', 'GET', f'repos/{REPOSITORY}/{path}'],
                                   stdout=output, stderr=subprocess.DEVNULL)
        started = time.monotonic()
        try:
            while process.poll() is None:
                require(time.monotonic() - started < 30 and os.fstat(output.fileno()).st_size <= 2 * 1024 * 1024,
                        'github_read_limit')
                time.sleep(.1)
            require(process.returncode == 0, 'github_read_failed')
            output.seek(0)
            return strict_json(output.read(2 * 1024 * 1024 + 1), 2 * 1024 * 1024)
        finally:
            if process.poll() is None:
                process.kill(); process.wait(timeout=5)


def validate_metadata(pins, latest, attempt, tag, jobs, release):
    for run in (latest, attempt):
        require(run.get('id') == SOURCE_RUN_ID and run.get('run_number') == 68
                and run.get('run_attempt') == 1 and run.get('head_sha') == SOURCE_COMMIT
                and run.get('head_branch') == 'main' and run.get('event') == 'push'
                and run.get('path') == '.github/workflows/msix.yml'
                and run.get('status') == 'completed' and run.get('conclusion') == 'success'
                and run.get('repository', {}).get('full_name') == REPOSITORY
                and run.get('repository', {}).get('private') is False, 'source_not_whole_qualified')
    require(tag.get('sha') == SOURCE_COMMIT, 'source_tag_changed')
    require(type(jobs) is list and len(jobs) == len(REQUIRED_JOBS)
            and {j.get('name') for j in jobs} == REQUIRED_JOBS
            and len({j.get('id') for j in jobs}) == len(jobs)
            and all(type(j.get('id')) is int and j['id'] > 0 and j.get('run_id') == SOURCE_RUN_ID
                    and j.get('head_sha') == SOURCE_COMMIT and j.get('status') == 'completed'
                    and j.get('conclusion') == 'success' for j in jobs), 'source_job_gate_failed')
    require(release.get('id') == pins['sourceReleaseId'] and release.get('tag_name') == SOURCE_TAG
            and release.get('draft') is False and release.get('prerelease') is True,
            'source_release_changed')
    assets = release.get('assets', [])
    require(type(assets) is list and len(assets) == 6
            and all(a.get('state') == 'uploaded' for a in assets), 'release_assets_not_uploaded')
    records = [{key: a.get(key) for key in ('id', 'name', 'size', 'digest')} for a in assets]
    expected = [{key: a[key] for key in ('id', 'name', 'size', 'digest')} for a in pins['sourceAssets']]
    require(sorted(records, key=lambda a: a.get('name', '')) == sorted(expected, key=lambda a: a['name']),
            'release_inventory_changed')


def validate_downloads(pins, source):
    require(source.is_dir() and not source.is_symlink()
            and {p.name for p in source.iterdir()} == ASSET_NAMES, 'download_file_set_changed')
    for asset in pins['sourceAssets']:
        path = source / asset['name']
        require(path.is_file() and not path.is_symlink() and path.stat().st_size == asset['size']
                and sha256(path) == asset['sha256'], 'download_bytes_changed')


def prepare_source(pins, context, work=WORK):
    authorize(pins, context)
    validate_local_helpers(context)
    require(not work.exists() and not work.is_symlink(), 'existing_probe_output')
    latest = github_get(f'actions/runs/{SOURCE_RUN_ID}')
    attempt = github_get(f'actions/runs/{SOURCE_RUN_ID}/attempts/1')
    jobs_response = github_get(f'actions/runs/{SOURCE_RUN_ID}/attempts/1/jobs?per_page=100')
    require(type(jobs_response.get('total_count')) is int
            and jobs_response['total_count'] == len(REQUIRED_JOBS), 'source_jobs_incomplete')
    tag = github_get(f'commits/{SOURCE_TAG}')
    release = github_get(f'releases/{pins["sourceReleaseId"]}')
    validate_metadata(pins, latest, attempt, tag, jobs_response.get('jobs'), release)
    work.mkdir(parents=True)
    source, payload = work / 'source', work / 'payload'
    command = ['gh', 'release', 'download', SOURCE_TAG, '--repo', REPOSITORY, '--dir', str(source)]
    for name in sorted(ASSET_NAMES): command += ['--pattern', name]
    try:
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180)
    except (subprocess.SubprocessError, OSError) as error:
        raise ProbeFailure('source_download_failed') from error
    validate_downloads(pins, source)
    sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'e2e')]
    from prepare_payload import prepare, verify_checksums
    from releasekit import verify_msix
    from store_package import authorize_release
    verify_checksums(source)
    provenance = strict_json((source / 'provenance.json').read_bytes(), 2 * 1024 * 1024)
    require(provenance.get('version') == '1.1.3', 'source_product_version_changed')
    authorize_release(SOURCE_TAG, provenance, latest, tag['sha'], jobs_response['jobs'])
    with redirect_stdout(io.StringIO()): validation = prepare(source, payload)
    require(provenance.get('package') == validation['msix']
            and provenance.get('sha256') == verify_msix(source / validation['msix'])['sha256'],
            'source_provenance_changed')
    receipt = {'formatVersion': 1, 'sourceCommit': SOURCE_COMMIT, 'sourceRunId': SOURCE_RUN_ID,
               'sourceRunAttempt': 1, 'sourceTag': SOURCE_TAG, 'sourceReleaseId': pins['sourceReleaseId'],
               'assetInventorySha256': pins['assetInventorySha256'],
               'pinsSha256': hashlib.sha256(canonical(pins)).hexdigest(),
               'diagnosticCommit': context['sha'], 'diagnosticRunId': context['runId'],
               'diagnosticRunAttempt': '1', 'allSourceJobsSuccessful': True,
               'sourceQualification': {
                   'latestStatus': latest['status'], 'latestConclusion': latest['conclusion'],
                   'latestRunAttempt': latest['run_attempt'], 'observedHead': latest['head_sha'],
                   'attemptStatus': attempt['status'], 'attemptConclusion': attempt['conclusion'],
                   'tagCommit': tag['sha'], 'releaseId': release['id'],
                   'releaseDraft': release['draft'], 'releasePrerelease': release['prerelease'],
                   'jobs': [{'id': job['id'], 'name': job['name'], 'runId': job['run_id'],
                             'head': job['head_sha'], 'status': job['status'], 'conclusion': job['conclusion']}
                            for job in sorted(jobs_response['jobs'], key=lambda j: j['name'])]},
               'helperSha256': HELPER_HASHES, 'runtimeParity': validation,
               'runtimeSha256': {p.relative_to(payload).as_posix(): sha256(p)
                                 for p in sorted(payload.rglob('*')) if p.is_file()}}
    (work / 'prepared.json').write_bytes(canonical(receipt) + b'\n')
    return receipt


def validate_prepared(pins, context, work=WORK):
    authorize(pins, context)
    validate_local_helpers(context)
    receipt = strict_json((work / 'prepared.json').read_bytes(), 2 * 1024 * 1024)
    require(receipt.get('pinsSha256') == hashlib.sha256(canonical(pins)).hexdigest()
            and receipt.get('diagnosticCommit') == context['sha']
            and receipt.get('diagnosticRunId') == context['runId']
            and receipt.get('helperSha256') == HELPER_HASHES
            and receipt.get('allSourceJobsSuccessful') is True, 'prepared_receipt_mismatch')
    validate_downloads(pins, work / 'source')
    payload = work / 'payload'
    expected = receipt.get('runtimeSha256', {})
    actual = {p.relative_to(payload).as_posix(): sha256(p)
              for p in payload.rglob('*') if p.is_file() and not p.is_symlink()}
    require(expected and actual == expected and not any(p.is_symlink() for p in payload.rglob('*'))
            and actual.get('OpenGeul.exe') == receipt['runtimeParity']['editorSha256'],
            'prepared_runtime_changed')
    # 캐시 receipt와 payload가 함께 바뀌어도 원본 portable의 바이트로 다시 판정한다.
    sys.path.insert(0, str(ROOT / 'e2e'))
    from prepare_payload import inventory, stream_hash
    with zipfile.ZipFile(work / 'source/OpenGeul_1.1.3_windows-x64_unsigned-portable.zip') as archive:
        original = {}
        for name, entry in inventory(archive).items():
            with archive.open(entry) as stream: original[name] = stream_hash(stream)
    require(actual == original, 'prepared_runtime_differs_from_original')
    return receipt


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProbeFailure('public_control_redirect')


def parse_public_metadata(raw):
    value = strict_json(raw, 8192)
    require(type(value) is dict and set(value) == {'formatVersion', 'appId', 'status', 'version', 'storeUrl', 'submissionId'},
            'public_control_schema')
    require(type(value['formatVersion']) is int and value['formatVersion'] == 1
            and value['appId'] == '9PJH0T3PHRMF' and value['status'] == 'Published'
            and value['storeUrl'] == STORE_URL and isinstance(value['submissionId'], str)
            and re.fullmatch(r'[1-9][0-9]{0,24}', value['submissionId']), 'public_control_identity')
    version = value['version']
    require(isinstance(version, str) and re.fullmatch(r'(?:0|[1-9][0-9]{0,4})(?:\.(?:0|[1-9][0-9]{0,4})){3}', version)
            and all(int(p) <= 65535 for p in version.split('.')), 'public_control_version')
    require(version == '1.1.1.0' and value['submissionId'] == '1152921505702042424', 'public_control_baseline_changed')
    return value


def public_control_get():
    request = urllib.request.Request(METADATA_URL,
        headers={'User-Agent': 'OpenGeul-Windows-Update-Verification/1.1.3', 'Accept': 'application/json'}, method='GET')
    # HTTPSHandler의 기본 SSL context를 그대로 사용한다. redirect·TLS 예외·URL 인수가 없다.
    opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPSHandler())
    try:
        with opener.open(request, timeout=8) as response:
            require(response.status == 200, 'public_control_http_status')
            raw = response.read(8193)
    except ProbeFailure: raise
    except (OSError, ValueError) as error: raise ProbeFailure('public_control_network') from error
    value = parse_public_metadata(raw)
    return {'version': value['version'], 'submissionId': value['submissionId'],
            'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def require_native_idle(result):
    require(type(result) is dict and set(result) == {'ok', 'value'} and result['ok'] is True
            and result['value'] == {'status': 'idle'}, 'native_not_idle')
    return result['value']


def credential_keys(environment):
    exact = {'GH_TOKEN', 'GITHUB_TOKEN', 'GH_ENTERPRISE_TOKEN', 'GITHUB_ENTERPRISE_TOKEN',
             'ACTIONS_RUNTIME_TOKEN', 'ACTIONS_ID_TOKEN_REQUEST_TOKEN'}
    return [key for key in environment if key.upper() in exact or key.upper().startswith('STORE_')]


@contextmanager
def without_credentials():
    removed = {key: os.environ.pop(key) for key in credential_keys(os.environ)}
    try:
        require(not credential_keys(os.environ), 'gui_credentials_present')
        yield
    finally: os.environ.update(removed)


def reparse_path(path):
    return path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction())


class OwnedSettings:
    def __init__(self, path, identity, owned_parent, parent_identity):
        self.path, self.identity, self.owned_parent, self.parent_identity = path, identity, owned_parent, parent_identity

    @classmethod
    def seed(cls, app_data):
        app_data = Path(app_data)
        require(app_data.is_absolute() and app_data.is_dir()
                and not any(reparse_path(p) for p in (app_data, *app_data.parents)), 'unsafe_app_data')
        parent = app_data / APP_IDENTIFIER
        owned_parent = False
        if not parent.exists():
            try: parent.mkdir(); owned_parent = True
            except FileExistsError: pass
        require(parent.is_dir() and not reparse_path(parent), 'unsafe_settings_parent')
        path = parent / SETTINGS_FILE
        require(not path.exists() and not reparse_path(path), 'existing_settings')
        try:
            with path.open('xb') as stream:
                stream.write(b'{"autoCheck":false}\n')
                identity = (os.fstat(stream.fileno()).st_dev, os.fstat(stream.fileno()).st_ino)
        except FileExistsError as error: raise ProbeFailure('existing_settings') from error
        parent_stat = parent.lstat()
        return cls(path, identity, owned_parent, (parent_stat.st_dev, parent_stat.st_ino))

    def remove(self):
        parent_stat = self.path.parent.lstat()
        require(not reparse_path(self.path.parent)
                and (parent_stat.st_dev, parent_stat.st_ino) == self.parent_identity, 'settings_parent_ownership_lost')
        require(self.path.is_file() and not reparse_path(self.path), 'settings_ownership_lost')
        with self.path.open('rb') as stream:
            current = os.fstat(stream.fileno())
            require((current.st_dev, current.st_ino) == self.identity
                    and stat.S_ISREG(current.st_mode), 'settings_ownership_lost')
            contents = strict_json(stream.read(8193), 8192)
            require(type(contents) is dict and set(contents) == {'autoCheck'}
                    and contents['autoCheck'] is False, 'settings_content_changed')
        current = self.path.lstat()
        require((current.st_dev, current.st_ino) == self.identity and not reparse_path(self.path), 'settings_ownership_lost')
        self.path.unlink()
        if self.owned_parent:
            try: self.path.parent.rmdir()
            except OSError: pass  # 다른 앱 파일이 생겼다면 디렉터리를 보존한다.


def with_cleanup(action, callbacks):
    failure = None
    try:
        return action()
    except BaseException as error:
        failure = error
        raise
    finally:
        cleanup_errors = []
        for callback in callbacks:
            try: callback()
            except BaseException as error: cleanup_errors.append(error)
        if cleanup_errors:
            if failure is not None:
                for error in cleanup_errors: failure.add_note(f'정리 실패: {type(error).__name__}')
            else: raise ProbeFailure('cleanup_failed') from cleanup_errors[0]


def main():
    require(len(sys.argv) == 1, 'arguments_forbidden')
    pins = read_pins()
    # 미승인 설정은 CI context 파일이 없어도 가장 먼저 거부한다.
    require(pins.get('rootExecutionAuthorized') is True, 'root_execution_not_authorized')
    return prepare_source(pins, read_context())


if __name__ == '__main__':
    try:
        main()
        print(json.dumps({'prepared': True, 'networkMode': 'github_read_only'}))
    except BaseException as error:
        print(json.dumps({'prepared': False, 'failure': str(error) if isinstance(error, ProbeFailure) else type(error).__name__}))
        sys.exit(2)
