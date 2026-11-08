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
        normal=normal.replace("if: github.event.repository.private == false && github.ref != 'refs/heads/work/opengeul-office-native-writer-observer'",'if: '+fixture['originalNormalIf'],1)
        self.assertEqual(hashlib.sha256(normal.encode()).hexdigest(),fixture['normalJobTextSha256'])


if __name__=='__main__':unittest.main()
