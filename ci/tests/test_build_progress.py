import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    import build_progress as progress
except ImportError:
    progress = None


class BuildProgressTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(progress)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.root_patch = patch.object(progress, 'ROOT', self.root)
        self.root_patch.start(); self.addCleanup(self.root_patch.stop)
        self.context = {'repository': 'ATLKR/OpenGeul', 'commit': 'a' * 40,
                        'runId': '123', 'runAttempt': '1', 'architecture': 'x64',
                        'contextSha256': 'b' * 64}
        self.execution = patch.object(progress, 'execution', side_effect=lambda architecture: {
            k: self.context[k] for k in ('repository','commit','runId','runAttempt')})
        self.execution.start(); self.addCleanup(self.execution.stop)
        self.snapshot = patch.object(progress, 'snapshot', side_effect=lambda architecture: dict(self.context))
        self.snapshot.start(); self.addCleanup(self.snapshot.stop)

    def fake_process(self, raw=b'original cargo output\r\n', code=0):
        class Process:
            stdout = io.BytesIO(raw)
            returncode = code
            pid = 12345
            def wait(inner, timeout=None): return code
        return Process()

    def run_stage(self, stage, raw=b'original cargo output\r\n', code=0, terminate=None):
        process = self.fake_process(raw, code)
        with patch.object(progress, 'ROOT', self.root), patch.object(progress.subprocess, 'Popen', return_value=process) as popen:
            result = progress.run_stage(stage, 'x64', stream=io.BytesIO(), terminate=terminate)
        return result, popen

    def test_jobs_bound_cpu_and_require_total_and_available_memory(self):
        gib = 1024 ** 3
        for cpu, total, available, expected in [(4, 16*gib, 13*gib, 4), (8, 32*gib, 20*gib, 4),
                (3, 16*gib, 13*gib, 2), (1, 16*gib, 13*gib, 1),
                (4, 14*gib, 12*gib, 4), (4, 14*gib-1, 12*gib, 2),
                (4, 16*gib, 12*gib-1, 2), (4, 8*gib, 4*gib, 2)]:
            with self.subTest(cpu=cpu,total=total,available=available):
                self.assertEqual(progress.select_jobs(cpu, total, available), expected)

    def test_jobs_reject_noninteger_and_impossible_host_reports(self):
        for values in [(True, 20, 10), (4, True, 0), (4, 20, 1.0), (0, 20, 10),
                       (4, -1, 0), (4, 10, 11), ('4', 20, 10)]:
            with self.subTest(values=values), self.assertRaises(ValueError): progress.select_jobs(*values)

    def test_native_and_release_require_previous_success_before_process_launch(self):
        for stage in ('NativeTests', 'Release'):
            with self.subTest(stage=stage), patch.object(progress, 'ROOT', self.root), \
                    patch.object(progress.subprocess, 'Popen') as popen:
                with self.assertRaises(ValueError): progress.run_stage(stage, 'x64', stream=io.BytesIO())
                popen.assert_not_called()

    def test_success_keeps_exact_original_log_and_records_unqualified_stage(self):
        raw = b'original\r\n\xffnonUTF8\n'
        result, popen = self.run_stage('Prepare', raw)
        self.assertEqual(result, 0)
        folder = self.root / '.work/build-progress/editor-x64/prepare'
        self.assertEqual((folder/'build.log').read_bytes(), raw)
        receipt = json.loads((folder/'progress.json').read_text())
        self.assertEqual(receipt['exitCode'], 0)
        self.assertTrue(receipt['complete'])
        self.assertFalse(receipt['sourceQualified'])
        self.assertEqual(receipt['logSha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(popen.call_args.args[0], progress.build_command('Prepare', 'x64'))
        self.assertEqual(popen.call_args.kwargs['cwd'], self.root)
        self.assertFalse(popen.call_args.kwargs.get('shell', False))
        self.assertEqual(progress.read_state('x64')['completed'], ['Prepare'])

    def test_native_failure_keeps_exit_code_and_does_not_authorize_release(self):
        self.run_stage('Prepare')
        result, _ = self.run_stage('NativeTests', b'actual native assertion failure\n', 7)
        self.assertEqual(result, 7)
        self.assertEqual(progress.read_state('x64')['completed'], ['Prepare'])
        folder = self.root / '.work/build-progress/editor-x64/native-tests'
        receipt = json.loads((folder/'progress.json').read_text())
        self.assertEqual(receipt['exitCode'], 7)
        self.assertTrue(receipt['complete'])
        with patch.object(progress, 'ROOT', self.root), patch.object(progress.subprocess, 'Popen') as popen:
            with self.assertRaises(ValueError): progress.run_stage('Release', 'x64', stream=io.BytesIO())
            popen.assert_not_called()

    def test_log_cap_fails_without_stage_success_and_terminates_only_owned_child(self):
        calls = []
        with patch.object(progress, 'MAX_LOG', 64):
            result, _ = self.run_stage('Prepare', b'x'*65, terminate=lambda proc: calls.append(proc.pid))
        self.assertNotEqual(result, 0)
        self.assertEqual(calls, [12345])
        folder = self.root / '.work/build-progress/editor-x64/prepare'
        self.assertEqual(len((folder/'build.log').read_bytes()), 64)
        receipt = json.loads((folder/'progress.json').read_text())
        self.assertFalse(receipt['complete'])
        self.assertTrue(receipt['logLimitExceeded'])
        self.assertFalse((self.root/'.work/editor-build-state-x64.json').exists())

    def test_duplicate_phase_cannot_overwrite_original_logs(self):
        self.run_stage('Prepare', b'first original')
        with patch.object(progress, 'ROOT', self.root), patch.object(progress.subprocess, 'Popen') as popen:
            with self.assertRaises(ValueError): progress.run_stage('Prepare', 'x64', stream=io.BytesIO())
            popen.assert_not_called()
        self.assertEqual((self.root/'.work/build-progress/editor-x64/prepare/build.log').read_bytes(), b'first original')

    def test_changed_source_attempt_architecture_or_fingerprint_blocks_next_stage(self):
        self.run_stage('Prepare')
        for key, value in [('commit', 'c'*40), ('runId', '124'), ('runAttempt', '2'),
                           ('contextSha256', 'd'*64), ('architecture', 'arm64')]:
            original = dict(self.context); self.context[key] = value
            with self.subTest(key=key), patch.object(progress, 'ROOT', self.root), patch.object(progress.subprocess, 'Popen') as popen:
                with self.assertRaises(ValueError): progress.run_stage('NativeTests', 'x64', stream=io.BytesIO())
                popen.assert_not_called()
            self.context = original

    def test_log_output_symlink_is_rejected_before_process_launch(self):
        outside = self.root/'outside'; outside.mkdir()
        work = self.root/'.work'; work.mkdir()
        (work/'build-progress').symlink_to(outside, target_is_directory=True)
        with patch.object(progress, 'ROOT', self.root), patch.object(progress.subprocess, 'Popen') as popen:
            with self.assertRaises(ValueError): progress.run_stage('Prepare', 'x64', stream=io.BytesIO())
            popen.assert_not_called()
        self.assertEqual(list(outside.iterdir()), [])

    def test_unknown_stage_or_architecture_cannot_spawn(self):
        for stage, architecture in [('Other','x64'), ('Prepare','x86'), ('Release','../arm64')]:
            with self.subTest(stage=stage,architecture=architecture), self.assertRaises(ValueError):
                progress.build_command(stage, architecture)

    def test_successful_native_fixture_bytes_bind_release_without_skipping_a_stage(self):
        self.run_stage('Prepare')
        fixtures = self.root/'.work/e2e-fixtures'; fixtures.mkdir()
        document = fixtures/'basic.hwpx'; document.write_bytes(b'original generated fixture')
        self.run_stage('NativeTests')
        document.write_bytes(b'changed after native tests')
        with patch.object(progress.subprocess, 'Popen') as popen:
            with self.assertRaises(ValueError): progress.run_stage('Release','x64',stream=io.BytesIO())
            popen.assert_not_called()
        document.write_bytes(b'original generated fixture')
        result, _ = self.run_stage('Release')
        self.assertEqual(result, 0)
        self.assertEqual(progress.read_state('x64')['completed'], ['Prepare','NativeTests','Release'])

    def test_small_live_child_output_reaches_console_before_the_child_finishes(self):
        seen = threading.Event(); failures = []
        class Stream(io.BytesIO):
            def write(inner, data):
                seen.set(); return super().write(data)
        command = [sys.executable, '-c',
                   'import sys,time;sys.stdout.buffer.write(b"small live output\\n");sys.stdout.flush();time.sleep(2)']
        def run():
            try: progress.run_stage('Prepare','x64',stream=Stream())
            except BaseException as error: failures.append(type(error).__name__)
        with patch.object(progress, 'build_command', return_value=command):
            thread = threading.Thread(target=run)
            thread.start()
            received_while_running = seen.wait(timeout=1)
            was_running = thread.is_alive()
            thread.join(timeout=5)
        self.assertTrue(received_while_running)
        self.assertTrue(was_running)
        self.assertFalse(thread.is_alive())
        self.assertEqual(failures, [])

    def test_boolean_or_float_state_version_cannot_authorize_native_compilation(self):
        self.run_stage('Prepare')
        path = progress.state_path('x64')
        original = path.read_bytes()
        for version in (True, 1.0):
            state = json.loads(original); state['formatVersion'] = version
            path.write_text(json.dumps(state))
            with self.subTest(version=version), patch.object(progress.subprocess, 'Popen') as popen:
                with self.assertRaises(ValueError): progress.run_stage('NativeTests','x64',stream=io.BytesIO())
                popen.assert_not_called()
        path.write_bytes(original)


if __name__ == '__main__': unittest.main()
