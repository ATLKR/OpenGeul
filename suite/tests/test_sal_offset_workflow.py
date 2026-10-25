"""Static SAL analysis preserves admission and cannot qualify native delivery."""
import unittest
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch
from types import SimpleNamespace
import stat
from suite.tests.test_calc_matrix_workflow import workflow_steps, field, run_code, WORKFLOW
from suite.tests.test_navigation_diagnostic_workflow import condition

STATIC = "env.OPENGEUL_SUITE_RUN_MODE == 'sal-offset-mapping'"

class SalOffsetWorkflowTests(unittest.TestCase):
    def test_source_guard_original_deadline_expires_before_any_git_call(self):
        guard=next(s for s in workflow_steps() if field(s,'id')=='sal-offset-admission')
        code=run_code(guard).split("$proof = @'\n",1)[1].split("\n'@",1)[0]
        with patch('time.monotonic',side_effect=(0.,31.)), patch('subprocess.run') as run:
            with self.assertRaises(TimeoutError):exec(code,{})
            run.assert_not_called()
    def test_source_guard_rejects_parent_reparse_point_before_file_read(self):
        guard=next(s for s in workflow_steps() if field(s,'id')=='sal-offset-admission')
        code=run_code(guard).split("$proof = @'\n",1)[1].split("\n'@",1)[0]
        namespace={};exec(code.split("assert git('rev-parse'",1)[0],namespace)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);target=root/'file';target.write_text('fixture')
            original=Path.lstat
            def observe(path):
                if path==root:return SimpleNamespace(st_mode=stat.S_IFDIR,st_file_attributes=1024)
                return original(path)
            with patch.object(Path,'lstat',autospec=True,side_effect=observe):
                with self.assertRaisesRegex(AssertionError,'aliased'):namespace['regular_ancestors'](target)
    def test_actual_inline_source_proof_rejects_wrong_head_or_modified_raw_bytes(self):
        guard=next(s for s in workflow_steps() if field(s,'id')=='sal-offset-admission')
        code=run_code(guard).split("$proof = @'\n",1)[1].split("\n'@",1)[0]
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            def git(*args):
                return subprocess.check_output(['git','-c','core.hooksPath=/dev/null',*args],cwd=root,stderr=subprocess.DEVNULL)
            git('init','--template=')
            path=root/'tracked.txt';path.write_bytes(b'original\n')
            git('add','tracked.txt');git('-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-m','fixture')
            initial=git('rev-parse','HEAD').decode().strip()
            git('update-index','--add','--cacheinfo','160000,'+initial+',upstream/hop')
            git('-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-m','uninitialized gitlink')
            head=git('rev-parse','HEAD').decode().strip()
            def check(sha):
                return subprocess.run([sys.executable,'-c',code],cwd=root,env=dict(os.environ,GITHUB_SHA=sha),capture_output=True).returncode
            self.assertEqual(check(head),0)
            self.assertNotEqual(check('1'*40),0)
            git('update-index','--assume-unchanged','tracked.txt')
            path.write_bytes(b'original\r\n')
            self.assertNotEqual(check(head),0)  # Raw bytes, even if Git stat/filter shortcuts hide them.
            path.write_bytes(b'original\n');(root/'generated-receipt.json').write_text('{}')
            self.assertEqual(check(head),0)
            submodule=root/'upstream/hop';submodule.mkdir(parents=True)
            self.assertEqual(check(head),0)
            (submodule/'unexpected.py').write_text('pass')
            self.assertNotEqual(check(head),0)

    def test_admission_and_exact_bytes_precede_authenticated_fetch(self):
        steps=workflow_steps()
        guard=next(s for s in steps if field(s,'id')=='sal-offset-admission')
        fetch=next(s for s in steps if 'fetch-source-engine.ps1' in run_code(s))
        self.assertLess(steps.index(guard),steps.index(fetch))
        self.assertEqual(condition(guard),STATIC+" || env.OPENGEUL_SUITE_RUN_MODE == 'com-wait-diagnostic' || env.OPENGEUL_SUITE_RUN_MODE == 'mutex-function-mapping' || env.OPENGEUL_SUITE_RUN_MODE == 'matched-plugin-caller'")
        code=run_code(guard)
        self.assertIn('. ./suite/scripts/prepare-native31.ps1',code)
        self.assertIn("Assert-Native31Context '${{ matrix.architecture }}'",code)
        self.assertNotIn('Invoke-Native31Suite',code)
        self.assertIn("'rev-parse', 'HEAD'",code)
        self.assertIn("'ls-tree', '-rz', '--full-tree', 'HEAD'",code)
        self.assertIn('hashlib.sha1',code)
        self.assertIn('GITHUB_SHA',code)
        self.assertIn("steps.sal-offset-admission.outcome == 'success'",condition(fetch))
    def test_only_static_mode_skips_build_and_missing_desktop_originals(self):
        steps=workflow_steps()
        build=next(s for s in steps if field(s,'id')=='build')
        self.assertEqual(condition(build),"env.OPENGEUL_SUITE_RUN_MODE != 'sal-offset-mapping' && env.OPENGEUL_SUITE_RUN_MODE != 'com-wait-diagnostic' && env.OPENGEUL_SUITE_RUN_MODE != 'mutex-function-mapping' && (env.OPENGEUL_SUITE_RUN_MODE != 'matched-plugin-caller' || (matrix.architecture == 'arm64' && steps.matched-symbol-qualification.outcome == 'success'))")
        upload=next(s for s in steps if 'Suite native31 setup and control originals' in s)
        self.assertEqual(condition(upload),"always() && github.ref == 'refs/heads/work/opengeul-office-arm64' && env.OPENGEUL_SUITE_RUN_MODE != 'sal-offset-mapping' && env.OPENGEUL_SUITE_RUN_MODE != 'com-wait-diagnostic' && env.OPENGEUL_SUITE_RUN_MODE != 'mutex-function-mapping' && (env.OPENGEUL_SUITE_RUN_MODE != 'matched-plugin-caller' || steps.native31-privacy-prepare.outcome != 'skipped')")
        units=next(s for s in steps if 'unittest discover' in run_code(s))
        self.assertIsNone(condition(units))
        self.assertIn('dotnet run --project suite/shell-tests',run_code(units))
    def test_mapping_requires_arm_fetch_and_admission_and_uploads_only_receipt(self):
        steps=workflow_steps()
        step=next(s for s in steps if field(s,'id')=='sal-offset-mapping')
        self.assertEqual(condition(step),STATIC+" && matrix.architecture == 'arm64' && steps.sal-offset-admission.outcome == 'success' && steps.source-engine.outcome == 'success'")
        self.assertIn('python suite/scripts/map-sal-offset.py --archive .work/source-engine-input/OpenGeul-Office-engine-arm64.zip --lock suite/config/runtime.arm64.lock.json --output .work/suite-sal-offset-mapping/receipt.json',run_code(step))
        upload=next(s for s in steps if field(s,'id')=='sal-offset-evidence')
        self.assertEqual(condition(upload),'always() && '+STATIC+" && matrix.architecture == 'arm64' && steps.sal-offset-mapping.outcome != 'skipped'")
        self.assertIn('path: .work/suite-sal-offset-mapping/receipt.json',upload)
        terminal=next(s for s in steps if field(s,'id')=='sal-offset-not-acceptance')
        self.assertEqual(condition(terminal),'always() && '+STATIC)
        self.assertLess(steps.index(upload),steps.index(terminal))
        self.assertIn('package delivery is prohibited',run_code(terminal))
        self.assertIn('OPENGEUL_SUITE_RUN_MODE: matched-plugin-caller',WORKFLOW.read_text())
