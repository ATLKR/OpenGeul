"""Normal package producers observe roles before enforcing the shared budget."""
from pathlib import Path
import shlex
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'ci'))
from policy import load_workflow


class NormalDistributionWorkflowTests(unittest.TestCase):
    def test_both_producers_bind_numeric_sizes_to_architecture_and_keep_native_failures_fatal(self):
        jobs = load_workflow(ROOT / '.github/workflows/msix.yml')['jobs']
        for job_name, architecture in [('build', 'x64'), ('build-arm64', 'arm64')]:
            steps = [step for step in jobs[job_name]['steps']
                     if step.get('name') == '업로드 전 전송 파일 크기 제한 검사']
            self.assertEqual(len(steps), 1)
            step = steps[0]
            self.assertEqual(step['shell'], 'pwsh')
            self.assertFalse(step.get('continue-on-error', False))
            lines = [line.strip() for line in step['run'].splitlines() if line.strip()]
            self.assertEqual(lines[:2], ["$ErrorActionPreference='Stop'",
                                        '$PSNativeCommandUseErrorActionPreference=$true'])
            native = [shlex.split(line) for line in lines[2:]]
            self.assertEqual(native, [
                ['python', 'scripts/release_pair.py', 'sizes', '--package-directory', 'dist',
                 '--architecture', architecture],
                ['python', 'ci/evidence.py', 'size', '--limit-mib', '128', 'dist']])


if __name__ == '__main__':
    unittest.main()
