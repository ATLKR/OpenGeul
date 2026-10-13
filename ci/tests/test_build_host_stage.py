"""단계별 host 증거는 각각 새 파일이며 같은 단계 재실행은 기존 증거를 보존한다."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


class BuildHostStageTests(unittest.TestCase):
    def setUp(self):
        self.script = (ROOT/'scripts/build-msix.ps1').read_text()
        spec = importlib.util.spec_from_file_location('build_host_stage_native', ROOT/'e2e/native_architecture.py')
        self.native = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.native)

    def output(self, root, phase, stage, architecture):
        self.assertIn("$Phase -eq 'Editor' -and $EditorStage -ne 'All'", self.script)
        self.assertIn("--output $hostArchitectureOutput", self.script)
        match = re.search(r"Join-Path \$root \('([^']+)' -f \$Architecture,\$EditorStage\)", self.script)
        self.assertIsNotNone(match, '실제 writer가 고정 단계별 새 증거 경로를 선택해야 한다')
        if phase == 'Editor' and stage != 'All':
            return root/match.group(1).format(architecture,stage)
        self.assertIn("Join-Path $root '.work/host-architecture.json'", self.script)
        return root/'.work/host-architecture.json'

    def host(self, output, architecture):
        class Probe:
            def inspect(self, pid):
                return {'processId':os.getpid(), 'nativeMachine':0x8664 if architecture=='x64' else 0xAA64,
                        'processMachine':0 if architecture=='x64' else 0x8664}
        args=['native_architecture.py','host','--architecture',architecture,'--output',str(output)]
        with patch.object(self.native,'WindowsProbe',return_value=Probe()), patch.object(sys,'argv',args), contextlib.redirect_stdout(io.StringIO()):
            self.native.main()

    def test_actual_host_writer_preserves_all_three_stage_proofs_and_refuses_repeat(self):
        for architecture in ('x64','arm64'):
            with self.subTest(architecture=architecture), tempfile.TemporaryDirectory() as folder:
                root=Path(folder);paths=[self.output(root,'Editor',stage,architecture) for stage in ('Prepare','NativeTests','Release')]
                self.assertEqual(len(set(paths)),3)
                for path in paths:self.host(path,architecture)
                originals={path:path.read_bytes() for path in paths}
                for path in paths:
                    with self.assertRaises(ValueError):self.host(path,architecture)
                    self.assertEqual(path.read_bytes(),originals[path])
                    self.assertEqual(json.loads(originals[path])['architecture'],architecture)

    def test_default_all_editor_all_cli_and_package_retain_original_path_and_fresh_guard(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for phase in ('All','Editor','Cli','Package'):
                self.assertEqual(self.output(root,phase,'All','x64'),root/'.work/host-architecture.json')
            path=self.output(root,'All','All','x64');self.host(path,'x64');original=path.read_bytes()
            with self.assertRaises(ValueError):self.host(path,'x64')
            self.assertEqual(path.read_bytes(),original)

    def test_foreign_host_still_fails_without_writing_any_new_stage_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            output=self.output(Path(folder),'Editor','Prepare','arm64')
            class Probe:
                def inspect(self,pid):return {'processId':pid,'nativeMachine':0x8664,'processMachine':0}
            with patch.object(self.native,'WindowsProbe',return_value=Probe()), patch.object(sys,'argv',['native_architecture.py','host','--architecture','arm64','--output',str(output)]):
                with self.assertRaises(ValueError):self.native.main()
            self.assertFalse(output.exists())


if __name__=='__main__':unittest.main()
