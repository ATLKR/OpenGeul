"""Exact one-argument Writer wiring; all other pinned workflow bytes remain."""
import copy
import hashlib
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest import mock

from ci.policy import load_workflow
import test_writer_preparation_failure_workflow as original_gate

BASE = Path(__file__).resolve().parents[2]
SOURCE = BASE / '.github/workflows/office-suite.yml'
PROFILE = 'owned-peer-before-first-admission-v1'
OPTION = ' --admission-profile ' + PROFILE
BASELINE_SHA256 = '62cc32acf7590ef50bf9aba3cde981df3d8b258f8cbcb6505fd3a6c8eac246d6'


def original_bytes(source):
    marker = '\n      id: writer-observe\n'
    if source.count(marker) != 1 or source.count('--admission-profile') != 1 or source.count(OPTION) != 1:
        raise ValueError('Exact single observed-child profile required')
    observe = source.split(marker, 1)[1].split('\n    - name:', 1)[0]
    if observe.count('-- observe' + OPTION + ' --output') != 1:
        raise ValueError('Profile must belong to the observed child')
    return source.replace(OPTION, '', 1)


class FirstPeerWorkflow(unittest.TestCase):
    def source(self): return SOURCE.read_text()
    def reviewed_source(self):
        source = self.source()
        try: original_bytes(source)
        except ValueError: self.fail('Exact observed-child opt-in is absent or malformed')
        return source

    def test_one_observed_child_option_preserves_all_other_original_bytes(self):
        self.assertEqual(hashlib.sha256(original_bytes(self.reviewed_source()).encode()).hexdigest(), BASELINE_SHA256)

    def test_missing_duplicate_unknown_or_wrong_child_options_cannot_normalize(self):
        source = self.reviewed_source()
        missing = source.replace(OPTION, '', 1)
        mutations = (
            missing,
            source.replace(OPTION, OPTION + OPTION, 1),
            source.replace(OPTION, ' --admission-profile unknown', 1),
            missing.replace(' -- atomic --work', ' -- atomic' + OPTION + ' --work', 1),
            missing.replace(' -- observe --output', OPTION + ' -- observe --output', 1),
        )
        for index, changed in enumerate(mutations):
            with self.subTest(index=index), self.assertRaises(ValueError): original_bytes(changed)

    def test_other_arguments_deadlines_and_acceptance_failure_stay_fixed(self):
        source = self.reviewed_source()
        mutations = (
            source.replace('timeout-minutes: 22', 'timeout-minutes: 21', 1),
            source.replace('--seconds 45', '--seconds 44', 1),
            source.replace('owned-blank-writer', 'changed-blank-writer', 1),
            source.replace("throw 'Writer observation is diagnostic only", "Write-Output 'Writer observation is diagnostic only", 1),
        )
        for index, changed in enumerate(mutations):
            self.assertNotEqual(changed, source)
            with self.subTest(index=index):
                self.assertNotEqual(hashlib.sha256(original_bytes(changed).encode()).hexdigest(), BASELINE_SHA256)

    def test_legacy_hash_gate_accepts_only_the_exact_observe_opt_in(self):
        source = self.reviewed_source()
        workflow = load_workflow(SOURCE)

        def checked(value):
            case = original_gate.PreparationFailureWorkflowTests('test_all_original_normal_and_writer_gates_are_unchanged')
            case.workflow = value
            case.test_all_original_normal_and_writer_gates_are_unchanged()

        checked(workflow)
        for kind in ('missing', 'duplicate', 'unknown', 'atomic'):
            value = copy.deepcopy(workflow)
            steps = {step['id']: step for step in value['jobs']['writer-server-observer']['steps'] if 'id' in step}
            run = steps['writer-observe']['run']
            if kind in ('missing', 'atomic'): run = run.replace(OPTION, '', 1)
            elif kind == 'duplicate': run = run.replace(OPTION, OPTION + OPTION, 1)
            else: run = run.replace(OPTION, ' --admission-profile unknown', 1)
            steps['writer-observe']['run'] = run
            if kind == 'atomic': steps['atomic-prepare']['run'] += OPTION
            with self.subTest(kind=kind), self.assertRaises(AssertionError): checked(value)

    def test_phase_forwards_the_profile_to_the_runner_without_consuming_or_repeating_it(self):
        path = BASE / 'suite/e2e/writer_server_observer_phase.py'
        spec = importlib.util.spec_from_file_location('_first_peer_phase_forwarding', path)
        phase = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = phase
        spec.loader.exec_module(phase)
        import writer_server_observer_runner as runner
        args = ['--admission-profile', PROFILE, '--output', 'synthetic', '--report', 'synthetic']
        calls = []
        with mock.patch.object(runner, 'main', lambda values: calls.append(values) or 13):
            code = phase.child(['observe', *args])
        self.assertEqual(code, 13)
        self.assertEqual(calls, [args])


if __name__ == '__main__': unittest.main()
