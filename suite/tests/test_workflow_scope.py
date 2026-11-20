"""Normal Suite readers cannot interpret another job's acceptance steps."""
import hashlib
import importlib
import json
from pathlib import Path
import unittest


HEADER="name: synthetic\n'on':\n  workflow_dispatch: null\nenv:\n  OPENGEUL_SUITE_RUN_MODE: acceptance\n"
NORMAL='''  windows-suite:
    strategy:
      matrix:
        include:
        - architecture: x64
        - architecture: arm64
    steps:
    - name: original normal gate
      id: normal-only
      if: env.OPENGEUL_SUITE_RUN_MODE == 'acceptance'
      run: |
        original_normal_gate
'''
WRITER='''  writer-server-observer:
    steps:
    - name: same-looking diagnostic gate
      id: normal-only
      if: always()
      run: |
        distinct_writer_diagnostic
'''


class WorkflowScopeTests(unittest.TestCase):
    def scope(self):
        try:return importlib.import_module('suite.tests.workflow_scope')
        except ModuleNotFoundError:self.fail('normal Suite job scope helper absent')

    def test_writer_steps_never_change_normal_conditions_or_original_bytes(self):
        m=self.scope();text=HEADER+'jobs:\n'+NORMAL+WRITER
        header,normal=m.suite_workflow_sections(text)
        self.assertEqual(header,HEADER);self.assertEqual(normal,NORMAL)
        self.assertEqual(m.normal_suite_source(text),HEADER+'jobs:\n'+NORMAL)
        self.assertNotIn('distinct_writer_diagnostic',m.normal_suite_source(text))
        self.assertEqual(hashlib.sha256(normal.encode()).hexdigest(),hashlib.sha256(NORMAL.encode()).hexdigest())

    def test_job_selection_uses_name_when_writer_comes_first(self):
        m=self.scope();header,normal=m.suite_workflow_sections(HEADER+'jobs:\n'+WRITER+NORMAL)
        self.assertEqual((header,normal),(HEADER,NORMAL))

    def test_legacy_single_normal_job_keeps_original_source(self):
        m=self.scope();text=HEADER+'jobs:\n'+NORMAL
        self.assertEqual(m.normal_suite_source(text),text)

    def test_legacy_eof_and_crlf_bytes_are_never_normalized(self):
        m=self.scope()
        for body in (NORMAL+'\n',NORMAL+'\n\n',NORMAL.rstrip('\n'),NORMAL.replace('\n','\r\n')):
            with self.subTest(body_bytes=len(body)):
                text=HEADER+'jobs:\n'+body
                self.assertEqual(m.suite_workflow_sections(text)[1],body)
                self.assertEqual(m.normal_suite_source(text),text)
        text=(HEADER+'jobs:\n'+NORMAL).replace('\n','\r\n')
        self.assertEqual(m.normal_suite_source(text),text)

    def test_one_inter_job_separator_does_not_remove_normal_existing_eof_blanks(self):
        m=self.scope();normal=NORMAL+'\n'
        self.assertEqual(m.suite_workflow_sections(HEADER+'jobs:\n'+normal+'\n'+WRITER)[1],normal)

    def test_unknown_duplicate_or_missing_job_is_rejected_instead_of_hidden(self):
        m=self.scope()
        for body in (NORMAL+WRITER+'  foreign-job:\n    steps: []\n',NORMAL+NORMAL,
                     NORMAL+WRITER+WRITER,WRITER,NORMAL+"  'foreign-job':\n    steps: []\n",
                     NORMAL+'  <<: *unknown\n'):
            with self.subTest(job_header_count=body.count('  windows-suite:')):
                with self.assertRaises(ValueError):m.suite_workflow_sections(HEADER+'jobs:\n'+body)

    def test_a_job_like_string_inside_literal_normal_command_is_untouched(self):
        m=self.scope();normal=NORMAL+'        echo "  foreign-job:"\n'
        self.assertEqual(m.suite_workflow_sections(HEADER+'jobs:\n'+normal+WRITER)[1],normal)

    def test_real_normal_canonical_hash_matches_independent_pinned_oracle(self):
        m=self.scope();root=Path(__file__).resolve().parents[2]
        text=(root/'.github/workflows/office-suite.yml').read_text()
        raw=(root/'suite/tests/fixtures/writer-server-observer-normal-workflow.json').read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),'191eb38642ecdc5d885815cea9567c70cdd49c7950d325403e143db113b62e2c')
        fixture=json.loads(raw);normal=m.suite_workflow_sections(text)[1]
        from suite.tests.reviewed_normal_workflow import original_normal_oracle_text
        normal=original_normal_oracle_text(normal)
        self.assertEqual(hashlib.sha256(normal.encode()).hexdigest(),fixture['normalJobTextSha256'])


    def test_historical_oracle_preserves_actual_new_source_bytes(self):
        from suite.tests.reviewed_normal_workflow import original_normal_oracle_text
        root=Path(__file__).resolve().parents[2]
        source=(root/'.github/workflows/office-suite.yml').read_text()
        m=self.scope();header,normal=m.suite_workflow_sections(source)
        expected=json.loads((root/'suite/tests/fixtures/writer-server-observer-normal-workflow.json').read_bytes())['normalJobTextSha256']
        raw_hash=hashlib.sha256(normal.encode()).hexdigest()
        self.assertNotEqual(raw_hash,expected)
        self.assertEqual(hashlib.sha256(original_normal_oracle_text(normal).encode()).hexdigest(),expected)
        self.assertEqual(m.normal_suite_source(source),header+'jobs:\n'+normal)
        self.assertEqual(hashlib.sha256(m.suite_workflow_sections(source)[1].encode()).hexdigest(),raw_hash)

    def test_historical_oracle_rejects_changed_or_duplicate_reviewed_dependencies(self):
        from suite.tests.reviewed_normal_workflow import original_normal_oracle_text, EXACT_SDK_SETUP, EXACT_YAML_SETUP
        root=Path(__file__).resolve().parents[2]
        normal=self.scope().suite_workflow_sections((root/'.github/workflows/office-suite.yml').read_text())[1]
        for changed in (normal.replace("dotnet-version: '10.0.404'", "dotnet-version: '10.0.405'"),
                        normal.replace('architecture: ${{ matrix.architecture }}', 'architecture: x64'),
                        normal.replace('Pillow==13.0.0', 'Pillow==14.0.0'),
                        normal.replace('PyYAML==6.0.3', 'PyYAML==6.0.4'),
                        normal.replace("github.ref != 'refs/heads/work/opengeul-office-native-writer-observer'",'true'),
                        normal+EXACT_SDK_SETUP, normal+EXACT_YAML_SETUP,
                        normal.replace("throw 'Pinned YAML workflow tooling installation failed.'", 'exit 0')):
            with self.subTest(),self.assertRaises(ValueError):original_normal_oracle_text(changed)

    def test_unknown_normal_workflow_edits_still_fail_the_immutable_oracle(self):
        from suite.tests.reviewed_normal_workflow import original_normal_oracle_text
        root=Path(__file__).resolve().parents[2]
        normal=self.scope().suite_workflow_sections((root/'.github/workflows/office-suite.yml').read_text())[1]
        expected=json.loads((root/'suite/tests/fixtures/writer-server-observer-normal-workflow.json').read_bytes())['normalJobTextSha256']
        for changed in (normal.replace('timeout-minutes: 150','timeout-minutes: 151'),
                        normal.replace('run_unit_checks -s suite/tests','run_unit_checks -s another/tests')):
            with self.subTest():
                self.assertNotEqual(changed,normal)
                self.assertNotEqual(hashlib.sha256(original_normal_oracle_text(changed).encode()).hexdigest(),expected)
        # The exact probe tail is sealed; appended steps fail before hashing.
        with self.assertRaisesRegex(ValueError, 'Reviewed bundled Clang observation delta differs'):
            original_normal_oracle_text(normal+'    - run: unreviewed_gate\n')

    def test_both_original_ui_install_routes_pin_the_observed_comtypes_version(self):
        from suite.tests.test_calc_matrix_workflow import workflow_steps,field,run_code
        root=Path(__file__).resolve().parents[2]
        text=(root/'.github/workflows/office-suite.yml').read_text()
        expected='python -m pip install pywinauto==0.6.9 comtypes==1.5.0'
        steps={field(step,'id'):step for step in workflow_steps() if field(step,'id')}
        for name in ('readiness','native31-privacy-prepare'):
            with self.subTest(route=name):
                installs=[line.strip() for line in run_code(steps[name]).splitlines()
                    if line.strip().startswith('python -m pip install')]
                self.assertEqual(installs,[expected])
                self.assertIn("if ($LASTEXITCODE -ne 0) { throw 'Native UI test prerequisites failed.' }",run_code(steps[name]))
        self.assertEqual(text.count(expected),2)

    def test_historical_oracle_requires_the_two_exact_comtypes_pin_seams(self):
        from suite.tests.reviewed_normal_workflow import original_normal_oracle_text
        root=Path(__file__).resolve().parents[2]
        normal=self.scope().suite_workflow_sections((root/'.github/workflows/office-suite.yml').read_text())[1]
        first='        python -m pip install pywinauto==0.6.9 comtypes==1.5.0\n'
        second='          python -m pip install pywinauto==0.6.9 comtypes==1.5.0\n'
        variants=(
            normal.replace(first,first.replace(' comtypes==1.5.0',''),1),
            normal.replace(second,second.replace(' comtypes==1.5.0',''),1),
            normal.replace('comtypes==1.5.0','comtypes==1.4.17',1),
            normal.replace('comtypes==1.5.0','comtypes==1.5.0 comtypes==1.5.0',1),
            normal.replace('comtypes==1.5.0\n','comtypes==1.5.0 --pre\n',1),
            normal.replace("if ($env:OPENGEUL_SUITE_RUN_MODE -ceq 'reader-console-diagnostic') {\n"+second,
                "if ($env:OPENGEUL_SUITE_RUN_MODE -ceq 'acceptance') {\n"+second,1),
            normal.replace('    - name: 실제 한국어 IME와 네이티브 UI 검사 준비\n',
                '    - name: other dependency route\n',1),
        )
        for index,changed in enumerate(variants):
            with self.subTest(mutation=index),self.assertRaises(ValueError):
                original_normal_oracle_text(changed)

    def test_extra_comtypes_route_remains_visible_to_the_original_immutable_oracle(self):
        from suite.tests.reviewed_normal_workflow import original_normal_oracle_text
        root=Path(__file__).resolve().parents[2]
        normal=self.scope().suite_workflow_sections((root/'.github/workflows/office-suite.yml').read_text())[1]
        expected=json.loads((root/'suite/tests/fixtures/writer-server-observer-normal-workflow.json').read_bytes())['normalJobTextSha256']
        extra=('    - name: unreviewed extra dependency\n      shell: pwsh\n      run: |\n'
            '        python -m pip install pywinauto==0.6.9 comtypes==1.5.0\n')
        changed=normal.replace('    - name: 실제 한국어 IME와 네이티브 UI 검사 준비\n',
            extra+'    - name: 실제 한국어 IME와 네이티브 UI 검사 준비\n',1)
        normalized=original_normal_oracle_text(changed)
        self.assertIn(extra,normalized)
        self.assertEqual(normalized.count(' comtypes==1.5.0'),1)
        self.assertNotEqual(hashlib.sha256(normalized.encode()).hexdigest(),expected)



class OriginalAcceptanceViewTests(unittest.TestCase):
    def setUp(self):
        self.scope=importlib.import_module('suite.tests.workflow_scope')
        self.view=getattr(self.scope,'original_acceptance_source',None)
        self.assertTrue(callable(self.view),'Closed original-acceptance test view is absent')
        root=Path(__file__).resolve().parents[2]
        self.source=(root/'.github/workflows/office-suite.yml').read_text()

    def test_exact_tail_view_restores_original_delivery_without_changing_full_view(self):
        from suite.tests.reviewed_normal_workflow import BUNDLED_CLANG_PROBE_START
        header,normal=self.scope.suite_workflow_sections(self.source)
        original=normal[:normal.index(BUNDLED_CLANG_PROBE_START)]
        self.assertEqual(self.view(self.source),header+'jobs:\n'+original)
        self.assertEqual(self.scope.normal_suite_source(self.source),header+'jobs:\n'+normal)
        self.assertEqual(normal.count('    - name:' )-original.count('    - name:'),3)
        self.assertTrue(original.rstrip().endswith('compression-level: 0'))
        from suite.tests.test_calc_matrix_workflow import workflow_source
        from suite.tests.test_home_routes_workflow import steps,MATRIX
        self.assertEqual(workflow_source(),self.view(self.source))
        self.assertIn('path: ${{ env.SUITE_ARCHIVE }}',steps(MATRIX)[-1])

    def test_unknown_missing_modified_duplicate_or_moved_tail_is_rejected(self):
        from suite.tests.reviewed_normal_workflow import BUNDLED_CLANG_PROBE_START
        header,normal=self.scope.suite_workflow_sections(self.source)
        start=normal.index(BUNDLED_CLANG_PROBE_START);tail=normal[start:]
        prefix=normal[:start]
        for changed in (
                header+'jobs:\n'+prefix,
                self.source.replace(BUNDLED_CLANG_PROBE_START,BUNDLED_CLANG_PROBE_START.replace('selected','unknown'),1),
                self.source.replace('path: .work/suite-bundled-clang-probe-public/report.numeric.json','path: .work/unknown-private',1),
                self.source.replace(BUNDLED_CLANG_PROBE_START,BUNDLED_CLANG_PROBE_START+tail,1),
                header+'jobs:\n'+prefix.replace('    - name: Enter 없이 실제 Calc Ctrl+S·저장·독립 재열기\n',tail+'    - name: Enter 없이 실제 Calc Ctrl+S·저장·독립 재열기\n',1),
                self.source.replace(BUNDLED_CLANG_PROBE_START,BUNDLED_CLANG_PROBE_START+'      continue-on-error: true\n',1),
                header+'jobs:\n'+normal+'    - name: unknown extra step\n      run: exit 0\n',
                self.source+'  unknown-job:\n    steps: []\n',
                self.source.replace('  windows-suite:\n','  windows-suite:\n  windows-suite:\n',1)):
            with self.subTest(),self.assertRaises(ValueError):self.view(changed)

    def test_original_acceptance_mutations_cannot_be_hidden_by_tail_removal(self):
        for before,after in (
                ('runner: windows-2025','runner: synthetic-runner'),
                ('timeout-minutes: 150','timeout-minutes: 151'),
                ('      id: calc-save\n','      id: calc-save\n      continue-on-error: true\n'),
                ('--output .work/suite-calc-save @sourceReaderArgs','--output .work/suite-calc-save --skip @sourceReaderArgs'),
                ("success() && steps.home-routes.outcome == 'success'","success() || steps.home-routes.outcome == 'success'"),
                ('path: ${{ env.SUITE_ARCHIVE }}','path: .work/foreign.zip')):
            with self.subTest(mutation=before):
                changed=self.source.replace(before,after,1);self.assertNotEqual(changed,self.source)
                with self.assertRaises(ValueError):self.view(changed)

if __name__=='__main__':unittest.main()
