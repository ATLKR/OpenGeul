"""격리된 Windows 진단의 실행 차단·소유권·실패 판정 오프라인 회귀."""
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import windows_update_source as probe
sys.path.insert(0, str(ROOT / 'e2e'))
import windows_update_probe as gui


def filled_pins():
    """실제 릴리스 증거가 아닌 오프라인 검증 전용 합성 값."""
    pins = json.loads((ROOT / 'config/windows-update-probe.json').read_text())
    pins['rootExecutionAuthorized'] = True
    pins['sourceReleaseId'] = 7
    for index, asset in enumerate(pins['sourceAssets'], 1):
        asset.update(id=index, size=100 + index, sha256=f'{index:064x}', digest=f'sha256:{index:064x}')
    pins['assetInventorySha256'] = probe.inventory_digest(pins['sourceAssets'])
    return pins


def context():
    return {'repository': probe.REPOSITORY, 'eventRepository': probe.REPOSITORY, 'private': False, 'actor': 'ATLKR',
            'event': 'workflow_dispatch', 'ref': probe.DIAGNOSTIC_REF, 'attempt': '1',
            'sha': 'd' * 40, 'runId': '9', 'job': 'windows-update-https',
            'actions': 'true', 'runnerEnvironment': 'github-hosted', 'runnerOS': 'Windows',
            'workflowRef': f'{probe.REPOSITORY}/.github/workflows/store-package.yml@{probe.DIAGNOSTIC_REF}',
            'workflowSha': 'd' * 40}


def public_metadata():
    return {'formatVersion': 1, 'appId': '9PJH0T3PHRMF', 'status': 'Published',
            'version': '1.1.1.0', 'storeUrl': probe.STORE_URL,
            'submissionId': '1152921505702042424'}


class GuardTests(unittest.TestCase):
    def test_unapproved_and_unset_contract_refuses_before_any_network(self):
        pins = json.loads((ROOT / 'config/windows-update-probe.json').read_text())
        for candidate in (pins, {**pins, 'rootExecutionAuthorized': True},
                          {**filled_pins(), 'sourceReleaseId': 'UNSET'}):
            with self.subTest(candidate=candidate['sourceReleaseId']), \
                    patch.object(probe, 'github_get', side_effect=AssertionError('network attempted')):
                with self.assertRaises(probe.ProbeFailure):
                    probe.prepare_source(candidate, context(), ROOT / '.work/never-created')
        self.assertFalse((ROOT / '.work/never-created').exists())

    def test_context_and_source_pins_are_fixed(self):
        pins = filled_pins()
        probe.authorize(pins, context())
        for key, value in [('actor', 'another'), ('private', True), ('attempt', '2'),
                           ('ref', 'refs/heads/main'), ('event', 'push'), ('runnerOS', 'Linux'),
                           ('sha', 'malformed'), ('repository', 'another/OpenGeul'),
                           ('eventRepository', 'another/OpenGeul'), ('workflowSha', 'a' * 40),
                           ('workflowRef', 'another/workflow@main')]:
            with self.subTest(key=key), self.assertRaises(probe.ProbeFailure):
                probe.authorize(pins, {**context(), key: value})
        for key, value in [('sourceCommit', 'a' * 40), ('sourceTag', 'v1.1.3'),
                           ('sourceRunAttempt', 2), ('sourceRunId', 1), ('rootExecutionAuthorized', 1)]:
            with self.subTest(key=key), self.assertRaises(probe.ProbeFailure):
                probe.authorize({**pins, key: value}, context())

    def test_inventory_requires_exact_six_ids_sizes_hashes_and_digests(self):
        pins = filled_pins()
        for change in ('duplicate', 'unsafe-name', 'digest', 'size', 'fingerprint', 'extra'):
            bad = copy.deepcopy(pins)
            if change == 'duplicate': bad['sourceAssets'][1]['id'] = bad['sourceAssets'][0]['id']
            elif change == 'unsafe-name': bad['sourceAssets'][0]['name'] = '../OpenGeul.exe'
            elif change == 'digest': bad['sourceAssets'][0]['digest'] = 'sha256:' + 'f' * 64
            elif change == 'size': bad['sourceAssets'][0]['size'] = True
            elif change == 'fingerprint': bad['assetInventorySha256'] = 'f' * 64
            else: bad['sourceAssets'].append(copy.deepcopy(bad['sourceAssets'][0]))
            with self.subTest(change=change), self.assertRaises(probe.ProbeFailure):
                probe.authorize(bad, context())

    def test_fresh_metadata_requires_whole_attempt_and_cleanup(self):
        pins = filled_pins()
        run = {'id': probe.SOURCE_RUN_ID, 'run_number': 68, 'run_attempt': 1,
               'head_sha': probe.SOURCE_COMMIT, 'head_branch': 'main', 'event': 'push',
               'path': '.github/workflows/msix.yml', 'status': 'completed', 'conclusion': 'success',
               'repository': {'full_name': probe.REPOSITORY, 'private': False}}
        jobs = [{'id': index, 'run_id': probe.SOURCE_RUN_ID, 'head_sha': probe.SOURCE_COMMIT,
                 'name': name, 'status': 'completed', 'conclusion': 'success'}
                for index, name in enumerate(sorted(probe.REQUIRED_JOBS), 1)]
        release = {'id': 7, 'tag_name': probe.SOURCE_TAG, 'draft': False, 'prerelease': True,
                   'assets': [{**asset, 'state': 'uploaded'} for asset in pins['sourceAssets']]}
        probe.validate_metadata(pins, run, run, {'sha': probe.SOURCE_COMMIT}, jobs, release)
        for change in ('whole', 'attempt', 'cleanup', 'head', 'digest', 'draft', 'extra-job'):
            r, attempt, j, rel = copy.deepcopy(run), copy.deepcopy(run), copy.deepcopy(jobs), copy.deepcopy(release)
            if change == 'whole': r['conclusion'] = 'failure'
            elif change == 'attempt': attempt['run_attempt'] = 2
            elif change == 'cleanup': next(x for x in j if x['name'] == 'cleanup-transports')['conclusion'] = 'failure'
            elif change == 'head': j[0]['head_sha'] = 'a' * 40
            elif change == 'digest': rel['assets'][0]['digest'] = 'sha256:' + 'f' * 64
            elif change == 'draft': rel['draft'] = True
            else: j.append({**j[0], 'name': 'unexpected', 'id': 99})
            with self.subTest(change=change), self.assertRaises(probe.ProbeFailure):
                probe.validate_metadata(pins, r, attempt, {'sha': probe.SOURCE_COMMIT}, j, rel)

    def test_unqualified_whole_run_prevents_asset_download_and_local_output(self):
        pins = filled_pins()
        bad_run = {'id': probe.SOURCE_RUN_ID, 'conclusion': 'failure'}
        responses = [bad_run, bad_run, {'total_count': 15, 'jobs': []},
                     {'sha': probe.SOURCE_COMMIT}, {}]
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(probe, 'validate_local_helpers'), \
                patch.object(probe, 'github_get', side_effect=responses) as read, \
                patch.object(probe.subprocess, 'run', side_effect=AssertionError('download attempted')):
            output = Path(directory) / 'work'
            with self.assertRaisesRegex(probe.ProbeFailure, 'source_not_whole_qualified'):
                probe.prepare_source(pins, context(), output)
            self.assertFalse(output.exists())
            self.assertEqual([call.args[0] for call in read.call_args_list], [
                f'actions/runs/{probe.SOURCE_RUN_ID}', f'actions/runs/{probe.SOURCE_RUN_ID}/attempts/1',
                f'actions/runs/{probe.SOURCE_RUN_ID}/attempts/1/jobs?per_page=100',
                f'commits/{probe.SOURCE_TAG}', 'releases/7'])


class OriginalRuntimeTests(unittest.TestCase):
    def original_fixture(self, work):
        """실제 helper를 검증하는 ZIP/PE 최소 구조. 제품·Windows 실행 증거가 아니다."""
        from buildkit import DEV_IDENTITY, manifest
        from prepare_payload import prepare
        source = work / 'source'; source.mkdir(parents=True)
        pe = bytearray(256); pe[:2] = b'MZ'; pe[60:64] = (128).to_bytes(4, 'little')
        pe[128:132] = b'PE\0\0'; pe[132:134] = (0x8664).to_bytes(2, 'little')
        files = {'OpenGeul.exe': bytes(pe), 'Tools/rhwp.exe': bytes(pe),
                 'Notices/OpenGeul-LICENSE.txt': b'MIT',
                 'AppxManifest.xml': manifest(DEV_IDENTITY, '1.1.3').encode()}
        msix = source / 'OpenGeul_1.1.3.0_x64_development-unsigned.msix'
        with zipfile.ZipFile(msix, 'w') as archive:
            for name, value in files.items(): archive.writestr(name, value)
            archive.writestr('AppxBlockMap.xml', b'<BlockMap/>')
            archive.writestr('[Content_Types].xml', b'<Types/>')
        with zipfile.ZipFile(source / 'OpenGeul_1.1.3_windows-x64_unsigned-portable.zip', 'w') as archive:
            for name, value in files.items(): archive.writestr(name, value)
        (source / 'AppxManifest.xml').write_bytes(files['AppxManifest.xml'])
        (source / 'rhwp-help.txt').write_text('rhwp usage; offline synthetic fixture')
        (source / 'provenance.json').write_bytes(probe.canonical({
            'version': '1.1.3', 'repository': probe.REPOSITORY, 'commit': probe.SOURCE_COMMIT,
            'runId': str(probe.SOURCE_RUN_ID), 'package': msix.name, 'sha256': probe.sha256(msix)}))
        (source / 'SHA256SUMS.txt').write_text(''.join(
            probe.sha256(path) + '  ' + path.name + '\n' for path in sorted(source.iterdir())))
        pins = filled_pins()
        for asset in pins['sourceAssets']:
            asset.update(size=(source / asset['name']).stat().st_size, sha256=probe.sha256(source / asset['name']))
            asset['digest'] = 'sha256:' + asset['sha256']
        pins['assetInventorySha256'] = probe.inventory_digest(pins['sourceAssets'])
        with patch('sys.stdout'):
            validation = prepare(source, work / 'payload')
        receipt = {'pinsSha256': hashlib.sha256(probe.canonical(pins)).hexdigest(),
                   'diagnosticCommit': context()['sha'], 'diagnosticRunId': context()['runId'],
                   'helperSha256': probe.HELPER_HASHES, 'allSourceJobsSuccessful': True,
                   'runtimeParity': validation,
                   'runtimeSha256': {p.relative_to(work / 'payload').as_posix(): probe.sha256(p)
                                     for p in (work / 'payload').rglob('*') if p.is_file()}}
        (work / 'prepared.json').write_bytes(probe.canonical(receipt))
        return pins, receipt

    def test_six_original_files_are_rechecked_and_byte_change_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            pins, _ = self.original_fixture(work)
            probe.validate_downloads(pins, work / 'source')
            (work / 'source/rhwp-help.txt').write_bytes(b'changed')
            with self.assertRaisesRegex(probe.ProbeFailure, 'download_bytes_changed'):
                probe.validate_downloads(pins, work / 'source')

    def test_forged_cached_manifest_cannot_replace_original_gui_bytes(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(probe, 'validate_local_helpers'):
            work = Path(directory)
            pins, receipt = self.original_fixture(work)
            probe.validate_prepared(pins, context(), work)
            gui = work / 'payload/OpenGeul.exe'
            gui.write_bytes(b'changed GUI')
            receipt['runtimeSha256']['OpenGeul.exe'] = probe.sha256(gui)
            receipt['runtimeParity']['editorSha256'] = probe.sha256(gui)
            (work / 'prepared.json').write_bytes(probe.canonical(receipt))
            with self.assertRaisesRegex(probe.ProbeFailure, 'prepared_runtime_differs_from_original'):
                probe.validate_prepared(pins, context(), work)


class PublicAndNativeTests(unittest.TestCase):
    def test_public_json_strict_types_fields_identity_and_limit(self):
        good = json.dumps(public_metadata()).encode()
        self.assertEqual(probe.parse_public_metadata(good)['version'], '1.1.1.0')
        bad = [b'x' * 8193, b'\xff', b'{"formatVersion":1,"formatVersion":1}',
               json.dumps({**public_metadata(), 'extra': 1}).encode(),
               json.dumps({**public_metadata(), 'formatVersion': True}).encode()]
        for key, value in [('status', 'Release'), ('appId', 'foreign'), ('version', '01.1.1.0'),
                           ('version', '1.1.1.65536'), ('version', '1.1.3.0'),
                           ('storeUrl', 'https://example.com/'), ('submissionId', '01')]:
            bad.append(json.dumps({**public_metadata(), key: value}).encode())
        for raw in bad:
            with self.subTest(raw=raw[:40]), self.assertRaises(probe.ProbeFailure):
                probe.parse_public_metadata(raw)

    def test_redirect_is_rejected_and_body_cap_applies_to_actual_read(self):
        with self.assertRaises(probe.ProbeFailure):
            probe.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.com/')
        class Response:
            status = 200
            headers = {}
            def __enter__(self): return self
            def __exit__(self, *args): return None
            def read(self, size): self.size = size; return b'x' * size
        response = Response()
        with patch.object(probe.urllib.request, 'build_opener') as build:
            build.return_value.open.return_value = response
            with self.assertRaises(probe.ProbeFailure): probe.public_control_get()
        self.assertEqual(response.size, 8193)
        request = build.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url, probe.METADATA_URL)
        self.assertFalse(request.has_header('Authorization'))
        self.assertEqual(build.return_value.open.call_args.kwargs['timeout'], 8)

    def test_native_only_actual_idle_is_success_not_error_available_busy_or_timeout(self):
        self.assertEqual(probe.require_native_idle({'ok': True, 'value': {'status': 'idle'}}), {'status': 'idle'})
        for result in ({'ok': True, 'value': {'status': 'error', 'version': '1.1.3', 'message': 'offline'}},
                       {'ok': True, 'value': {'status': 'available', 'version': '1.1.4.0'}},
                       {'ok': False, 'failure': 'busy'}, {'ok': False, 'failure': 'timeout'},
                       {'ok': True, 'value': {'status': 'idle', 'version': '1.1.1.0'}}):
            with self.subTest(result=result), self.assertRaises(probe.ProbeFailure):
                probe.require_native_idle(result)


class OwnershipTests(unittest.TestCase):
    def test_existing_settings_are_preserved_and_reformatting_owned_false_is_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            owner = probe.OwnedSettings.seed(base)
            owner.path.write_text('{\n  "autoCheck": false\n}\n')
            owner.remove()
            self.assertFalse(owner.path.exists())
            target = base / probe.APP_IDENTIFIER / probe.SETTINGS_FILE
            target.parent.mkdir()
            target.write_text('{"autoCheck":true}')
            with self.assertRaises(probe.ProbeFailure): probe.OwnedSettings.seed(base)
            self.assertEqual(target.read_text(), '{"autoCheck":true}')

    def test_unowned_replacement_symlink_or_changed_preferences_are_not_deleted(self):
        for change in ('replace', 'symlink', 'changed', 'nonbool'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                owner = probe.OwnedSettings.seed(Path(directory))
                if change == 'replace':
                    other = owner.path.with_suffix('.other')
                    other.write_text('{"autoCheck":false}')
                    os.replace(other, owner.path)
                elif change == 'symlink':
                    owner.path.unlink()
                    other = owner.path.with_suffix('.other')
                    other.write_text('{"autoCheck":false}')
                    owner.path.symlink_to(other)
                elif change == 'changed': owner.path.write_text('{"autoCheck":true}')
                else: owner.path.write_text('{"autoCheck":0}')
                with self.assertRaises(probe.ProbeFailure): owner.remove()
                self.assertTrue(owner.path.exists())

    def test_cleanup_keeps_primary_error_and_attempts_all_owned_cleanup(self):
        events = []
        failure = probe.ProbeFailure('native_error')
        def action(): raise failure
        def first(): events.append('session'); raise OSError('private path must not be logged')
        def second(): events.append('settings')
        with self.assertRaises(probe.ProbeFailure) as caught:
            probe.with_cleanup(action, [first, second])
        self.assertIs(caught.exception, failure)
        self.assertEqual(events, ['session', 'settings'])
        self.assertEqual(failure.__notes__, ['정리 실패: OSError'])

    def test_read_token_removed_from_environment_copied_by_original_session(self):
        with patch.dict(os.environ, {'GH_TOKEN': 'never-output', 'GITHUB_TOKEN': 'never-output',
                                     'ACTIONS_RUNTIME_TOKEN': 'never-output', 'STORE_CLIENT_SECRET': 'never-output'}):
            with probe.without_credentials():
                copied_child_environment = dict(os.environ)
                self.assertFalse(probe.credential_keys(copied_child_environment))
            self.assertEqual(os.environ['GH_TOKEN'], 'never-output')


class FakeLocator:
    def __init__(self, page, selector): self.page, self.selector = page, selector
    def click(self): self.page.clicked.append(self.selector)
    def count(self): return 1


class FakePage:
    """오프라인 계약 회귀용 가짜. 실제 Windows/HTTP 성공 증거로 사용하지 않는다."""
    def __init__(self, result=None):
        self.commands, self.clicked = [], []
        self.result = result or {'ok': True, 'value': {'status': 'idle'}}
    def locator(self, selector): return FakeLocator(self, selector)
    def evaluate(self, script, command):
        if 'window.__TAURI_INTERNALS__.invoke(command, {})' not in script:
            raise AssertionError('production invoke path absent')
        self.commands.append(command)
        if command == 'get_update_preferences': return {'ok': True, 'value': {'autoCheck': False}}
        if command == 'check_store_update': return self.result
        return {'ok': True, 'value': {'status': 'idle'}}


class FakeExpectation:
    def __init__(self, locator): self.locator = locator
    def to_be_visible(self): pass
    def to_have_attribute(self, name, value):
        if (name, value) != ('aria-checked', 'false'): raise AssertionError('wrong OFF assertion')
    def to_be_hidden(self):
        if self.locator.selector != '.update-notice': raise AssertionError('notice assertion absent')


class GuiAdapterTests(unittest.TestCase):
    def test_manual_invokes_once_and_records_remote_version_as_unobserved(self):
        page, receipt = FakePage(), {}
        gui.perform_native_check(page, FakeExpectation, receipt)
        self.assertEqual(page.commands, ['get_update_preferences', 'get_update_state',
                                         'check_store_update', 'get_update_state'])
        self.assertNotIn('[data-cmd="file:check-update"]', page.clicked)
        self.assertEqual(receipt['manualRpcCalls'], 1)
        self.assertIsNone(receipt['nativeRemoteVersionObserved'])
        self.assertTrue(receipt['updateNoticeHidden'])
        with self.assertRaises(probe.ProbeFailure): gui.rpc(page, 'start_update_install')

    def test_error_available_busy_timeout_are_failures_without_second_manual_call(self):
        for result in ({'ok': True, 'value': {'status': 'error', 'version': '1.1.3.0', 'message': 'never-output'}},
                       {'ok': True, 'value': {'status': 'available', 'version': '1.1.4.0'}},
                       {'ok': False, 'failure': 'busy'}, {'ok': False, 'failure': 'timeout'}):
            page, receipt = FakePage(result), {}
            with self.subTest(result=result), self.assertRaises(probe.ProbeFailure):
                gui.perform_native_check(page, FakeExpectation, receipt)
            self.assertEqual(page.commands.count('check_store_update'), 1)
            self.assertEqual(receipt['manualNativeResult'], gui.safe_rpc_result(result))
            self.assertNotIn('never-output', json.dumps(receipt))
            self.assertNotIn('updateNoticeHidden', receipt)

    def fake_gui_run(self, base, *, native=None, changed_control=False, close_error=False, changed_gui=False):
        work = base / 'work'
        (work / 'payload').mkdir(parents=True)
        executable = work / 'payload/OpenGeul.exe'
        executable.write_bytes(b'offline synthetic fixture, not a qualified Windows executable')
        app_data = base / 'app-data'; app_data.mkdir()
        child_env = []
        class FakeSession:
            def __init__(self, mode, folder, fixture, *, executable):
                self.page = FakePage(native)
                self.proc = SimpleNamespace(pid=123, poll=lambda: None)
                child_env.append(dict(os.environ))
            def close(self):
                if close_error: raise OSError('never-output private cleanup path')
                self.proc.poll = lambda: -1
                if changed_gui: executable.write_bytes(b'changed')
        prepared = {'runtimeParity': {'editorSha256': probe.sha256(executable)},
                    'sourceQualification': {'offlineSyntheticFixture': True}}
        before = {'version': '1.1.1.0', 'submissionId': '1152921505702042424', 'bytes': 200, 'sha256': 'a' * 64}
        after = {**before, 'sha256': 'b' * 64} if changed_control else before
        with patch.object(probe, 'WORK', work), \
                patch.object(probe, 'validate_prepared', return_value=prepared), \
                patch.object(probe, 'public_control_get', side_effect=[before, after]), \
                patch.object(gui, 'os', SimpleNamespace(name='nt', environ=os.environ)), \
                patch.dict(os.environ, {'APPDATA': str(app_data), 'GH_TOKEN': 'never-output',
                                         'GITHUB_TOKEN': 'never-output', 'STORE_CLIENT_SECRET': 'never-output'}), \
                patch.dict(sys.modules, {'driver': SimpleNamespace(Session=FakeSession),
                                         'playwright.sync_api': SimpleNamespace(expect=FakeExpectation)}):
            failure = None
            try: gui.execute_gui(filled_pins(), context())
            except probe.ProbeFailure as error: failure = error
        receipt = json.loads((work / 'qa/probe.json').read_text())
        return receipt, failure, app_data / probe.APP_IDENTIFIER / probe.SETTINGS_FILE, child_env

    def test_gui_control_mismatch_fails_after_original_process_and_owned_settings_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            receipt, failure, settings, child_env = self.fake_gui_run(Path(directory), changed_control=True)
            self.assertEqual(str(failure), 'public_control_changed_during_native_check')
            self.assertFalse(receipt['passed'])
            self.assertTrue(receipt['processCleaned'] and receipt['settingsRemoved'])
            self.assertFalse(settings.exists())
            self.assertEqual(receipt['guiSha256Before'], receipt['guiSha256After'])
            self.assertFalse(probe.credential_keys(child_env[0]))

    def test_primary_native_failure_preserved_and_settings_not_deleted_while_process_alive(self):
        with tempfile.TemporaryDirectory() as directory:
            receipt, failure, settings, _ = self.fake_gui_run(Path(directory),
                native={'ok': False, 'failure': 'busy'}, close_error=True)
            self.assertEqual(str(failure), 'native_not_idle')
            self.assertEqual(failure.__notes__, ['정리 실패: OSError', '정리 실패: ProbeFailure'])
            self.assertTrue(settings.exists())
            self.assertFalse(receipt['settingsRemoved'])
            self.assertEqual(receipt['manualNativeResult'], {'ok': False, 'failure': 'busy'})
            self.assertNotIn('never-output', json.dumps(receipt))

    def test_gui_byte_change_refuses_pass_and_success_keeps_control_and_native_observation_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            receipt, failure, settings, _ = self.fake_gui_run(Path(directory), changed_gui=True)
            self.assertEqual(str(failure), 'cleanup_failed')
            self.assertFalse(receipt['passed'])
            self.assertFalse(settings.exists())
            self.assertNotEqual(receipt['guiSha256Before'], receipt['guiSha256After'])
        with tempfile.TemporaryDirectory() as directory:
            receipt, failure, _, _ = self.fake_gui_run(Path(directory))
            self.assertIsNone(failure)
            self.assertTrue(receipt['passed'])
            self.assertEqual(receipt['publicVersionObservedByControlGet'], '1.1.1.0')
            self.assertIsNone(receipt['nativeRemoteVersionObserved'])
            self.assertFalse(receipt['qualifiedSourceReplacement'] or receipt['storeCertified'])


if __name__ == '__main__': unittest.main()
