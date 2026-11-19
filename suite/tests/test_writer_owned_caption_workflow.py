"""One exact Writer observe-only opt-in; every other T13 byte stays pinned."""
import copy
import hashlib
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest import mock

from ci.policy import load_workflow

BASE=Path(__file__).resolve().parents[2]
SOURCE=BASE/'.github/workflows/office-suite.yml'
PROFILE='one-owned-caption-v1'
OPTION=' --activation-profile '+PROFILE
ANCHOR='--work-root "$private/owned-blank-writer"'+OPTION+' --report'
T13_SHA256='47572931fd2fdc53b8f06a9d889f00b146031e549d68ef9362bca936114fedbd'


def original_run(run):
    if type(run) is not str or run.count('--activation-profile')!=1 or run.count(OPTION)!=1 or run.count(ANCHOR)!=1:
        raise ValueError('Exact single original-owned-caption option required')
    if run.count('-- observe --admission-profile owned-peer-before-first-admission-v1 --output')!=1:
        raise ValueError('Option belongs only to the original observe child')
    return run.replace(OPTION,'',1)


def original_bytes(source):
    marker='\n      id: writer-observe\n'
    if source.count(marker)!=1 or source.count('--activation-profile')!=1 or source.count(OPTION)!=1:
        raise ValueError('Exact one observe-only caption profile required')
    observe=source.split(marker,1)[1].split('\n    - name:',1)[0]
    original_run(observe)
    return source.replace(OPTION,'',1)


class CaptionWorkflow(unittest.TestCase):
    def source(self):
        source=SOURCE.read_text()
        try:original_bytes(source)
        except ValueError:self.fail('Exact observe-only caption profile is absent or malformed')
        return source

    def test_exact_one_optin_restores_all_original_t13_workflow_bytes(self):
        self.assertEqual(hashlib.sha256(original_bytes(self.source()).encode()).hexdigest(),T13_SHA256)

    def test_missing_duplicate_unknown_wrong_phase_or_before_observe_rejected(self):
        source=self.source();missing=source.replace(OPTION,'',1)
        changes=(missing,source.replace(OPTION,OPTION+OPTION,1),source.replace(OPTION,' --activation-profile unknown',1),
            missing.replace(' -- atomic --work',' -- atomic'+OPTION+' --work',1),
            missing.replace(' -- observe',' '+OPTION+' -- observe',1),
            missing.replace(' --prepared-library',OPTION+' --prepared-library',1))
        for index,changed in enumerate(changes):
            with self.subTest(index=index),self.assertRaises(ValueError):original_bytes(changed)

    def test_other_arguments_deadlines_acceptance_and_admission_remain_byte_pinned(self):
        source=self.source()
        changes=(source.replace('timeout-minutes: 22','timeout-minutes: 21',1),
            source.replace('--seconds 45','--seconds 44',1),source.replace('owned-blank-writer','different-peer',1),
            source.replace("throw 'Writer observation is diagnostic only","Write-Output 'Writer observation is diagnostic only",1),
            source.replace(' --admission-profile owned-peer-before-first-admission-v1',' --admission-profile unknown',1))
        for index,changed in enumerate(changes):
            self.assertNotEqual(source,changed)
            try:accepted=hashlib.sha256(original_bytes(changed).encode()).hexdigest()==T13_SHA256
            except ValueError:accepted=False
            with self.subTest(index=index):self.assertFalse(accepted)

    def test_both_legacy_hash_gates_admit_only_the_exact_new_observe_option(self):
        import test_writer_first_owned_peer_workflow as first
        import test_writer_preparation_failure_workflow as failure
        source=self.source()
        self.assertEqual(hashlib.sha256(first.original_bytes(source).encode()).hexdigest(),first.BASELINE_SHA256)
        workflow=load_workflow(SOURCE)
        def checked(value):
            case=failure.PreparationFailureWorkflowTests('test_all_original_normal_and_writer_gates_are_unchanged')
            case.workflow=value;case.test_all_original_normal_and_writer_gates_are_unchanged()
        checked(workflow)
        for kind in ('missing','duplicate','unknown','atomic','deadline','acceptance'):
            value=copy.deepcopy(workflow)
            steps={s['id']:s for s in value['jobs']['writer-server-observer']['steps'] if 'id' in s}
            run=steps['writer-observe']['run']
            if kind in ('missing','atomic'):run=run.replace(OPTION,'',1)
            elif kind=='duplicate':run=run.replace(OPTION,OPTION+OPTION,1)
            elif kind=='unknown':run=run.replace(OPTION,' --activation-profile unknown',1)
            elif kind=='deadline':run=run.replace('--seconds $env:WRITER_OBSERVER_PHASE_SECONDS','--seconds 61',1)
            else:steps['writer-terminal']['run']=steps['writer-terminal']['run'].replace('throw ','Write-Output ',1)
            steps['writer-observe']['run']=run
            if kind=='atomic':steps['atomic-prepare']['run']+=OPTION
            with self.subTest(kind=kind),self.assertRaises(AssertionError):checked(value)

    def test_phase_passes_exact_profile_to_runner_without_consuming_or_repeating(self):
        spec=importlib.util.spec_from_file_location('_caption_phase_forwarding',BASE/'suite/e2e/writer_server_observer_phase.py')
        phase=importlib.util.module_from_spec(spec);sys.modules[spec.name]=phase;spec.loader.exec_module(phase)
        import writer_server_observer_runner as runner
        args=['--admission-profile','owned-peer-before-first-admission-v1','--activation-profile',PROFILE,
            '--output','synthetic','--report','synthetic'];calls=[]
        with mock.patch.object(runner,'main',lambda values:calls.append(values) or 13):code=phase.child(['observe',*args])
        self.assertEqual(code,13);self.assertEqual(calls,[args])


if __name__=='__main__':unittest.main()
