"""원본 Windows GUI의 실제 Store 확인 IPC를 한 번 관측하는 별도 진단."""
from __future__ import annotations
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import windows_update_source as source

RPC = """async (command) => {
  if (typeof window.__TAURI_INTERNALS__?.invoke !== 'function')
    return {ok: false, failure: 'missing_production_bridge'};
  let timer;
  try {
    return await Promise.race([
      window.__TAURI_INTERNALS__.invoke(command, {}).then(value => ({ok: true, value})).catch(error => ({
        ok: false,
        failure: error === '업데이트 정보를 확인 중입니다. 잠시 후 다시 시도해 주세요.' ? 'busy' : 'ipc_rejected'
      })),
      new Promise(resolve => { timer = setTimeout(() => resolve({ok: false, failure: 'timeout'}), 12000); })
    ]);
  } finally { clearTimeout(timer); }
}"""
COMMANDS = frozenset({'get_update_preferences', 'check_store_update', 'get_update_state'})


def rpc(page, command):
    source.require(command in COMMANDS, 'forbidden_native_command')
    return page.evaluate(RPC, command)


def safe_rpc_result(value):
    """제품 오류 원문/스택을 출력하지 않고 실제 상태·숫자 버전만 남긴다."""
    if not isinstance(value, dict): return {'ok': False, 'failure': 'invalid_rpc_result'}
    if value.get('ok') is not True:
        failure = value.get('failure')
        return {'ok': False, 'failure': failure if failure in
                {'busy', 'timeout', 'ipc_rejected', 'missing_production_bridge'} else 'invalid_rpc_result'}
    state = value.get('value')
    if not isinstance(state, dict): return {'ok': False, 'failure': 'invalid_rpc_state'}
    status = state.get('status')
    result = {'status': status if status in {'idle', 'available', 'error'} else 'unexpected'}
    version = state.get('version')
    if isinstance(version, str) and source.re.fullmatch(r'(?:0|[1-9][0-9]{0,4})(?:\.(?:0|[1-9][0-9]{0,4})){3}', version):
        if all(int(p) <= 65535 for p in version.split('.')): result['version'] = version
    return {'ok': True, 'value': result}


def perform_native_check(page, expect, receipt):
    prefs = rpc(page, 'get_update_preferences')
    source.require(type(prefs) is dict and set(prefs) == {'ok', 'value'} and prefs['ok'] is True
                   and type(prefs['value']) is dict and set(prefs['value']) == {'autoCheck'}
                   and prefs['value']['autoCheck'] is False, 'native_settings_not_off')
    receipt['nativeAutoCheck'] = False
    initial = rpc(page, 'get_update_state')
    receipt['initialNativeState'] = safe_rpc_result(initial)
    source.require_native_idle(initial)
    file_title = page.locator('[data-menu="file"] > .menu-title')
    file_title.click()
    expect(page.locator('[data-cmd="file:check-update"]')).to_be_visible()
    auto = page.locator('[data-cmd="file:auto-check-update"]')
    expect(auto).to_be_visible()
    expect(auto).to_have_attribute('aria-checked', 'false')
    file_title.click()
    # 실제 수동 IPC 한 번만 실행한다. 메뉴 확인 항목은 클릭하지 않아 중복 GET을 만들지 않는다.
    receipt['manualRpcCalls'] = 1
    native = rpc(page, 'check_store_update')
    receipt['manualNativeResult'] = safe_rpc_result(native)
    source.require_native_idle(native)
    final = rpc(page, 'get_update_state')
    receipt['finalNativeState'] = safe_rpc_result(final)
    source.require_native_idle(final)
    notice = page.locator('.update-notice')
    source.require(notice.count() == 1, 'update_notice_missing_or_duplicate')
    expect(notice).to_be_hidden()
    receipt['updateNoticeHidden'] = True
    # Idle 계약은 remote version을 노출하지 않는다. 대조 GET과 직접 네이티브 관측을 구분한다.
    receipt['nativeRemoteVersionObserved'] = None


def execute_gui(pins, context):
    source.require(os.name == 'nt', 'windows_required')
    prepared = source.validate_prepared(pins, context)
    from driver import Session
    from playwright.sync_api import expect
    executable = source.WORK / 'payload/OpenGeul.exe'
    gui_hash = source.sha256(executable)
    folder = source.WORK / 'qa'
    source.require(not folder.exists() and not folder.is_symlink(), 'existing_gui_evidence')
    folder.mkdir()
    receipt = {'formatVersion': 1, 'qualifiedSourceReplacement': False, 'storeCertified': False,
               'sourceCommit': source.SOURCE_COMMIT, 'sourceRunId': source.SOURCE_RUN_ID,
               'sourceRunAttempt': 1, 'sourceTag': source.SOURCE_TAG,
               'sourceReleaseId': pins['sourceReleaseId'], 'assetInventorySha256': pins['assetInventorySha256'],
               'diagnosticCommit': context['sha'], 'diagnosticRunId': context['runId'],
               'diagnosticRunAttempt': '1', 'diagnosticJob': context['job'],
               'guiSha256Before': gui_hash, 'originalRuntimeParity': prepared['runtimeParity'],
               'sourceQualification': prepared['sourceQualification'],
               'fixedEndpoint': source.METADATA_URL, 'nativeRemoteVersionObserved': None,
               'manualRpcCalls': 0, 'storeWritesAttempted': False, 'guiCredentialsRemoved': False,
               'settingsOwned': False, 'settingsRemoved': False, 'processCleaned': False,
               'passed': False, 'stage': 'control_before'}
    session, owner = None, None

    def action():
        nonlocal session, owner
        before = source.public_control_get()
        receipt['publicControlBefore'] = before
        receipt['stage'] = 'owned_settings'
        app_data = os.environ.get('APPDATA')
        source.require(bool(app_data), 'missing_app_data')
        owner = source.OwnedSettings.seed(Path(app_data))
        receipt['settingsOwned'] = True
        receipt['stage'] = 'native_start'
        # 기존 Session이 dict(os.environ)를 복사하기 전에 토큰을 제거한 부모 환경을 확인한다.
        source.require(not source.credential_keys(os.environ), 'gui_credentials_present')
        receipt['guiCredentialsRemoved'] = True
        # __init__ 실패 때도 기존 Session.close를 다시 호출할 수 있도록 부분 객체를 보존한다.
        session = Session.__new__(Session)
        Session.__init__(session, 'native', folder / 'session', None, executable=executable)
        source.require(session.proc is not None and session.proc.poll() is None, 'gui_not_running')
        receipt['processPid'] = session.proc.pid
        receipt['stage'] = 'native_manual_check'
        perform_native_check(session.page, expect, receipt)
        receipt['stage'] = 'control_after'
        after = source.public_control_get()
        receipt['publicControlAfter'] = after
        source.require(before == after, 'public_control_changed_during_native_check')
        receipt['publicVersionObservedByControlGet'] = after['version']
        receipt['stage'] = 'cleanup'

    def close_session():
        if session is not None:
            session.close()
            process = getattr(session, 'proc', None)
            source.require(process is None or process.poll() is not None, 'gui_process_not_closed')
            receipt['processExitCode'] = process.poll() if process is not None else None
            receipt['processCleaned'] = True

    def remove_settings():
        if owner is not None:
            process = getattr(session, 'proc', None) if session is not None else None
            source.require(process is None or process.poll() is not None, 'settings_cleanup_requires_closed_gui')
            owner.remove()
            receipt['settingsRemoved'] = True

    def unchanged_gui():
        receipt['guiSha256After'] = source.sha256(executable)
        source.require(receipt['guiSha256After'] == gui_hash, 'gui_bytes_changed')

    failure = None
    try:
        with source.without_credentials():
            source.with_cleanup(action, [close_session, remove_settings, unchanged_gui])
        receipt['passed'] = True
        receipt['stage'] = 'completed'
    except BaseException as error:
        failure = error
        receipt['failure'] = str(error) if isinstance(error, source.ProbeFailure) else type(error).__name__
        receipt['cleanupNotes'] = getattr(error, '__notes__', [])
        raise
    finally:
        try: (folder / 'probe.json').write_bytes(source.canonical(receipt) + b'\n')
        except BaseException as error:
            if failure is not None: failure.add_note(f'증거 저장 실패: {type(error).__name__}')
            else: raise source.ProbeFailure('receipt_write_failed') from error
    return receipt


def main():
    source.require(len(sys.argv) == 1, 'arguments_forbidden')
    pins = source.read_pins()
    source.require(pins.get('rootExecutionAuthorized') is True, 'root_execution_not_authorized')
    context = source.read_context()
    source.authorize(pins, context)
    return execute_gui(pins, context)


if __name__ == '__main__':
    try:
        main()
        print(json.dumps({'passed': True, 'nativeRemoteVersionObserved': None,
                          'publicVersionObservedByControlGet': '1.1.1.0'}))
    except BaseException as error:
        print(json.dumps({'passed': False, 'failure': str(error) if isinstance(error, source.ProbeFailure) else type(error).__name__}))
        sys.exit(2)
