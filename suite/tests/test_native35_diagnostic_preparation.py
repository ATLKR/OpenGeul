"""Diagnostic binding contracts; synthetic checks never prepare a desktop."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
ADAPTER = ROOT / 'e2e/native35_input_witness_prepare.py'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class DiagnosticPreparationTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(ADAPTER.is_file(), 'Explicit diagnostic adapter is missing')
        self.adapter = load('native35_preparation_test', ADAPTER)
        self.core = load('native35_preparation_core_test', ROOT / 'e2e/native31_desktop_control.py')
        self.env = dict(GITHUB_ACTIONS='true', RUNNER_ENVIRONMENT='github-hosted', RUNNER_OS='Windows',
            RUNNER_ARCH='ARM64', GITHUB_REPOSITORY='ATLKR/OpenGeul', GITHUB_EVENT_NAME='push',
            GITHUB_JOB='windows-suite', GITHUB_REF=self.adapter.BRANCH, GITHUB_WORKFLOW_REF=self.adapter.WORKFLOW,
            GITHUB_SHA='a'*40, GITHUB_WORKFLOW_SHA='a'*40, GITHUB_RUN_ID='123', GITHUB_RUN_ATTEMPT='1',
            GITHUB_ACTOR='ATLKR', GITHUB_ACTOR_ID='65988341')
        self.event = dict(repository=dict(full_name='ATLKR/OpenGeul', id=123, private=False),
            sender=dict(login='ATLKR', id=65988341, type='User'), ref=self.adapter.BRANCH, deleted=False, after='a'*40)
        self.native = dict(processId=45, processMachine=0, nativeMachine=0xAA64, sessionId=1)

    def test_fixed_binding_passes_actual_context_without_mutation_or_default_guard_change(self):
        before = copy.deepcopy(self.env)
        binding = self.adapter.control_binding(self.core)
        self.adapter.validate_context(self.env, self.event, 'nt')
        self.core.validate_execution(self.env, self.event, self.native, 'nt', prepare_privacy=True, binding=binding)
        self.assertEqual(self.env, before)
        self.assertEqual(binding.observer_entry, 'e2e/native35_input_witness_prepare.py')
        self.assertEqual(binding.ref, 'refs/heads/work/native35-arm64-input-witness')
        self.assertEqual(binding.job, 'windows-suite')
        self.assertEqual(binding.additional_source_files, (
            'e2e/native35_input_witness_prepare.py', 'suite/scripts/prepare-native35-input-witness.ps1',
            '.github/workflows/suite-native35-input-witness.yml', 'suite/scripts/prepare-native31.ps1'))
        for preparation in (False, True):
            with self.assertRaises(ValueError):
                self.core.validate_execution(self.env, self.event, self.native, 'nt', prepare_privacy=preparation)
        with self.assertRaises(ValueError):
            self.core.validate_execution(self.env, self.event, self.native, 'nt', binding=binding)

    def test_context_rejects_wrong_owner_source_workflow_and_platform_before_loading_core(self):
        bad_fields = [('GITHUB_REF', 'refs/heads/work/opengeul-office-arm64'), ('GITHUB_WORKFLOW_REF', 'other'),
            ('GITHUB_ACTOR', 'other'), ('GITHUB_ACTOR_ID', '1'), ('GITHUB_SHA', '0'*40), ('GITHUB_SHA', None),
            ('GITHUB_WORKFLOW_SHA', 'b'*40), ('GITHUB_EVENT_NAME', 'workflow_dispatch'), ('GITHUB_JOB', 'prepare'),
            ('GITHUB_RUN_ATTEMPT', '2'), ('RUNNER_ARCH', 'X64'), ('RUNNER_ENVIRONMENT', 'self-hosted'),
            ('GITHUB_RUN_ID', '0'), ('GITHUB_RUN_ID', '1'*21)]
        args = SimpleNamespace(observer=False, deadline=None, prepare_privacy=True, output=Path('/unused'))
        for key, value in bad_fields:
            env = {**self.env, key:value} if value is not None else {k:v for k,v in self.env.items() if k != key}
            with self.subTest(key=key, value=value), patch.dict(os.environ, env, clear=True):
                with patch.object(self.adapter, 'read_event', return_value=self.event), patch.object(self.adapter, 'load_control', side_effect=AssertionError('must reject first')):
                    with self.assertRaises(ValueError): self.adapter.entry(args, platform='nt')
        with self.assertRaises(ValueError): self.adapter.validate_context(self.env, self.event, 'posix')

    def test_actual_event_rejects_private_wrong_ref_sender_deleted_and_null_identity(self):
        variants = []
        for path, value in [('ref', 'other'), ('after', 'b'*40), ('deleted', True), ('deleted', 0)]:
            event = copy.deepcopy(self.event); event[path] = value; variants.append(event)
        for section, key, value in [('repository','private',True), ('repository','id',True),
                ('repository','full_name','other/OpenGeul'), ('sender','id',True), ('sender','login','other'),
                ('sender','type','Bot')]:
            event = copy.deepcopy(self.event); event[section][key] = value; variants.append(event)
        for event in [None, [], {}, *variants]:
            with self.subTest(event=event), self.assertRaises(ValueError):
                self.adapter.validate_context(self.env, event, 'nt')

    def test_entry_preserves_original_args_absolute_deadline_and_dispatch_once(self):
        for observer in (False, True):
            seen = []
            fake = SimpleNamespace(ControlBinding=self.core.ControlBinding,
                controller=lambda args, **kw: seen.append(('controller',args,kw)) or 7,
                observer=lambda args, **kw: seen.append(('observer',args,kw)) or 7)
            args = SimpleNamespace(observer=observer, deadline=123.25 if observer else None,
                                   prepare_privacy=True, output=Path('/unused'))
            with patch.dict(os.environ, self.env, clear=True), patch.object(self.adapter,'read_event',return_value=self.event), patch.object(self.adapter,'load_control',return_value=fake):
                self.assertEqual(self.adapter.entry(args, platform='nt'), 7)
            self.assertEqual(seen, [('observer' if observer else 'controller', args, {'binding':self.adapter.control_binding(fake)})])
            self.assertIs(seen[0][1], args)

    def test_missing_explicit_preparation_and_deadline_pair_fail_before_core(self):
        for observer, deadline, preparation in [(False,None,False), (True,None,True), (False,123,True)]:
            args = SimpleNamespace(observer=observer, deadline=deadline, prepare_privacy=preparation, output=Path('/unused'))
            with patch.dict(os.environ,self.env,clear=True), patch.object(self.adapter,'read_event',return_value=self.event), patch.object(self.adapter,'load_control',side_effect=AssertionError('no delegate')):
                with self.assertRaises(ValueError): self.adapter.entry(args, platform='nt')

    def test_event_reader_bounds_and_rejects_aliases_without_any_native_import(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary); event = folder/'event.json'
            event.write_text(json.dumps(self.event))
            with patch.dict(os.environ, {'GITHUB_EVENT_PATH':str(event)}, clear=True):
                self.assertEqual(self.adapter.read_event(), self.event)
                event.write_bytes(b' '*(self.adapter.MAX_JSON+1))
                with self.assertRaises(ValueError): self.adapter.read_event()
                event.write_text('[]')
                with self.assertRaises(ValueError): self.adapter.read_event()
            event.write_text('{}')
            # Synthetic lstat avoids requiring Windows symlink privileges.
            with patch.object(Path, 'lstat', return_value=SimpleNamespace(st_mode=stat.S_IFLNK, st_file_attributes=0)):
                with self.assertRaises(ValueError): self.adapter.plain_path(event)
            with self.assertRaises(ValueError): self.adapter.plain_path(Path('relative.json'))

    def test_binding_keeps_native_and_clean_source_requirements(self):
        binding = self.adapter.control_binding(self.core)
        checkout = dict(head=self.env['GITHUB_SHA'], tree='b'*40, dirty=False)
        self.core.validate_context(self.env, self.event, checkout, self.native, 'nt', prepare_privacy=True, binding=binding)
        for changes in ({'dirty':True}, {'head':'b'*40}, {'tree':'0'*40}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.core.validate_context(self.env, self.event, {**checkout,**changes}, self.native, 'nt', prepare_privacy=True, binding=binding)
        for changes in ({'nativeMachine':0x8664}, {'processMachine':0x8664}, {'sessionId':-1}, {'processId':0}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.core.validate_execution(self.env, self.event, {**self.native,**changes}, 'nt', prepare_privacy=True, binding=binding)


if __name__ == '__main__':
    unittest.main()
