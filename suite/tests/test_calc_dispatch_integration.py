"""Synthetic artifact isolation and original one-save admission; no desktop claim."""
import hashlib
import importlib.util
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile

from suite import payload
from suite.tests.test_payload import PayloadFixture, pe, canonical
from suite.tests.test_branding import make_runtime

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'suite/e2e'))
import korean_ime_smoke as ime
import windows_smoke


def load_stage():
    path = ROOT / 'suite/scripts/stage-calc-dispatch.py'
    if not path.is_file():
        raise AssertionError('Isolated Calc diagnostic consumer is missing')
    spec = importlib.util.spec_from_file_location('calc_dispatch_stage_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.m = load_stage()
        self.f = PayloadFixture(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.f.product = json.loads((ROOT/'suite/config/product.json').read_bytes())
        self.f.product['version'] = self.f.provenance['version']
        self.f.branding['manifestSha256'] = hashlib.sha256(canonical(self.f.product)).hexdigest()
        self.f.provenance['architecture'] = 'arm64'
        self.f.provenance['hwp'] = dict(sha256='4'*64, url='https://example.org/hwp.zip')
        for name in ('OpenGeul.Office.exe', 'Office/program/soffice.exe',
                     'Office/program/soffice.bin', 'Office/program/python.exe', 'hostfxr.dll',
                     'HWP/OpenGeul.exe', 'HWP/Tools/rhwp.exe'):
            self.f.write(name, pe(0xaa64))
        self.f.write('HWP/Notices/OpenGeul-LICENSE.txt', b'original HWP legal terms')
        self.f.source_archive(); self.f.save_metadata()
        self.inventory = payload.create_inventory(self.f.root, architecture='arm64')
        self.f.write_json(payload.INVENTORY, self.inventory)
        self.archive = self.f.root.parent/'OpenGeul-Office-engine-arm64-calc-dispatch.zip'
        self.receipt = self.f.root.parent/'receipt.json'
        self.output = self.f.root.parent/'diagnostic'
        self.marker = dict(schemaVersion=1, kind='calc-save-dispatch-diagnostic',
            acceptanceEligible=False, fullEngineQualified=False,
            sourceCommit='b'*40, sourceLockSha256='c'*64)
        # The established generated upstream fixture has Default toolbar mode;
        # its locale registry excerpt is copied from the pinned installed runtime.
        self.raw_runtime = self.f.root.parent/'raw-runtime'
        make_runtime(self.raw_runtime)
        registry = self.raw_runtime/'share/registry/main.xcd'
        tree = ET.parse(registry)
        namespace = '{http://openoffice.org/2001/registry}'
        toolbar = next(node for node in tree.iter(namespace+'component-data')
                       if node.get(namespace+'name')=='ToolbarMode')
        # Complete the generated fixture with the existing global properties
        # read by both canonical branding and the worker's mode admission.
        for name in ('Writer','Calc','Impress','Draw'):
            prop = ET.SubElement(toolbar,'prop',{namespace+'name':'Active'+name})
            ET.SubElement(prop,'value').text = 'Default'
        tree.write(registry,encoding='utf-8',xml_declaration=True)
        for name in ('soffice.bin','soffice.exe','python.exe'):
            (self.raw_runtime/'program'/name).write_bytes(pe(0xaa64))
        (self.raw_runtime/self.m.MARKER).write_text(json.dumps(self.marker))
        self.entries = {path.relative_to(self.raw_runtime).as_posix():path.read_bytes()
                        for path in self.raw_runtime.rglob('*') if path.is_file()}
        self.write_inputs()

    def write_inputs(self):
        with zipfile.ZipFile(self.archive, 'w') as archive:
            for name, data in self.entries.items(): archive.writestr(name, data)
        self.proof = dict(schemaVersion=1, kind='native-office-engine-calc-dispatch-diagnostic',
            architecture='arm64', status='native-engine-calc-dispatch-diagnostic-built',
            passed=True, fullEngineQualified=False, acceptanceEligible=False,
            sourceCommit='b'*40, sourceLockSha256='c'*64,
            artifact=dict(path=str(self.archive), size=self.archive.stat().st_size, sha256=sha(self.archive)))
        self.receipt.write_text(json.dumps(self.proof))

    def stage(self, **overrides):
        args = dict(baseline=self.f.root, archive=self.archive, receipt=self.receipt,
            output=self.output, expected_engine_source_commit='b'*40, expected_suite_source_commit='a'*40,
            expected_receipt_sha256=sha(self.receipt), expected_archive_sha256=sha(self.archive))
        return self.m.stage(**{**args, **overrides})

    def test_verified_baseline_is_untouched_and_whole_copy_has_explicit_overlay(self):
        before = payload._scan(self.f.root)
        result = self.stage()
        self.assertEqual(payload._scan(self.f.root), before)
        self.assertEqual(self.f.read('suite-provenance.json'), (self.output/'suite-provenance.json').read_bytes())
        for name in before:
            if not name.startswith('Office/'):
                self.assertEqual(before[name], payload._scan(self.output)[name])
        self.assertIs(result['acceptanceEligible'], False)
        self.assertEqual(2, result['schemaVersion'])
        self.assertEqual('b'*40, result['engineSourceCommit'])
        self.assertEqual('a'*40, result['admittedSuiteSourceCommit'])
        self.assertNotIn('sourceCommit', result)
        self.assertEqual(self.marker, json.loads((self.output/'Office'/self.m.MARKER).read_bytes()))
        self.assertEqual(result['inputs']['baselineInventorySha256'], sha(self.f.root/payload.INVENTORY))
        fresh = json.loads((self.output/payload.INVENTORY).read_bytes())
        self.assertEqual(fresh['files'], payload._scan(self.output))
        self.assertEqual(fresh['architecture'], 'arm64')
        with self.assertRaisesRegex(ValueError, 'Diagnostic engine cannot qualify'):
            payload.verify_payload(self.output, fresh)
        self.assertEqual(ime.require_calc_dispatch_suite(self.output, fresh,
            expected_engine_source_commit='b'*40), result)

    def worker_style_contract(self, runtime):
        from suite.tests.test_worker import bootstrap_services
        import importlib
        worker = importlib.import_module('native')
        namespace = '{http://openoffice.org/2001/registry}'
        component = next(node for node in ET.parse(runtime/'share/registry/main.xcd').iter(namespace+'component-data')
                         if node.get(namespace+'package')=='org.openoffice.Office.UI' and node.get(namespace+'name')=='ToolbarMode')
        class Configuration:
            def __init__(self, node): self.node = node
            def getByName(self, name):
                return Configuration(next(node for node in self.node.findall('node') if node.get(namespace+'name')==name))
            def getPropertyValue(self, name):
                node = next(node for node in self.node.findall('prop') if node.get(namespace+'name')==name)
                value = node.find('value').text
                return {'true':True,'false':False}.get(value, value)
        services, _, _, _ = bootstrap_services([])
        services['com.sun.star.configuration.ConfigurationProvider'].createInstanceWithArguments = lambda *args:Configuration(component)
        backend = worker.UnoBackend(runtime)
        backend.uno = SimpleNamespace(createUnoStruct=lambda name:SimpleNamespace())
        return backend._isolate_legacy_style_controls(services.__getitem__, self.f.product['modules']['calc'])

    def test_diagnostic_runtime_applies_real_branding_before_actual_worker_style_gate(self):
        from suite.tests import test_worker  # Establish the worker's existing import boundary.
        from session import WorkerError
        with self.assertRaises(WorkerError) as rejected:
            self.worker_style_contract(self.raw_runtime)
        self.assertEqual('ui_style_isolation_failed', rejected.exception.code)
        baseline = payload._scan(self.f.root)
        inputs = (self.archive.read_bytes(), self.receipt.read_bytes())
        self.stage()
        office = self.output/'Office'
        mode = self.worker_style_contract(office)['mode']
        self.assertEqual(dict(active='notebookbar.ui',globalActive='notebookbar.ui',
                              tabbedCommandArg='notebookbar.ui',hasNotebookbar=True), mode)
        self.assertEqual(baseline, payload._scan(self.f.root))
        self.assertEqual(inputs, (self.archive.read_bytes(),self.receipt.read_bytes()))
        self.assertFalse(any(path.name.startswith('raw-runtime-') for path in self.output.iterdir()))
        for name in ('program/soffice.bin','program/soffice.exe','program/python.exe',self.m.MARKER,'LICENSE','NOTICE'):
            self.assertEqual(self.entries[name], (office/name).read_bytes())
        branding = json.loads((office/'opengeul-branding.json').read_bytes())
        self.assertNotEqual(self.f.branding, branding)
        self.assertEqual(self.f.read('runtime-branding.json'), (self.output/'runtime-branding.json').read_bytes())
        originals = {name:hashlib.sha256(value).hexdigest() for name,value in self.entries.items()}
        self.assertEqual(hashlib.sha256(canonical(originals)).hexdigest(), branding['inputTreeSha256'])
        self.assertIn('share/registry/main.xcd',branding['modifiedFiles'])
        for name, change in branding['modifiedFiles'].items():
            self.assertEqual(originals.get(name),change['beforeSha256'])
            self.assertEqual(sha(office/name),change['sha256'])

    def test_complete_baseline_verification_precedes_any_diagnostic_input(self):
        self.f.write('worker/session.py', b'changed baseline')
        with patch.object(self.m, '_diagnostic_inputs', side_effect=AssertionError('inputs read early')):
            with self.assertRaisesRegex(ValueError, 'complete inventory'):
                self.stage()
        self.assertFalse(self.output.exists())

    def test_external_expected_source_and_both_digests_are_mandatory(self):
        for key, value in (('expected_engine_source_commit', 'd'*40),
                           ('expected_suite_source_commit', 'b'*40),
                           ('expected_engine_source_commit', ''), ('expected_suite_source_commit', ''),
                           ('expected_receipt_sha256', 'd'*64), ('expected_archive_sha256', 'e'*64)):
            with self.subTest(key=key), self.assertRaises(ValueError): self.stage(**{key:value})
        self.assertFalse(self.output.exists())

    def test_receipt_failure_or_normal_qualification_cannot_enter(self):
        for key, value in (('passed', False), ('fullEngineQualified', True),
                           ('acceptanceEligible', True), ('status', 'failed'), ('architecture', 'x64')):
            with self.subTest(key=key):
                original = dict(self.proof); self.proof[key] = value
                self.receipt.write_text(json.dumps(self.proof))
                with self.assertRaises(ValueError): self.stage()
                self.proof = original
        self.assertFalse(self.output.exists())

    def test_marker_generation_must_join_authenticated_receipt(self):
        self.marker['sourceCommit'] = 'd'*40
        self.entries['program/opengeul-calc-dispatch-diagnostic.json'] = json.dumps(self.marker).encode()
        self.write_inputs()
        with self.assertRaises(ValueError): self.stage()
        self.assertFalse(self.output.exists())

    def test_unsafe_archive_members_rejected_before_output_creation(self):
        for bad in ('../escape', 'program/../escape', 'program/SOFFICE.bin', 'Program/other.dll',
                    'program/soffice.bin/nested', 'HWP/OpenGeul.exe', 'program/con.dll'):
            with self.subTest(name=bad):
                self.entries[bad] = b'inert'; self.write_inputs()
                with self.assertRaises(ValueError): self.stage()
                self.entries.pop(bad)
        info = zipfile.ZipInfo('program/link'); info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(self.archive, 'a') as archive: archive.writestr(info, 'outside')
        self.proof['artifact'].update(size=self.archive.stat().st_size, sha256=sha(self.archive))
        self.receipt.write_text(json.dumps(self.proof))
        with self.assertRaises(ValueError): self.stage()
        self.assertFalse(self.output.exists())

    def test_fresh_output_and_bounded_archive_are_required(self):
        self.output.mkdir()
        with self.assertRaises((ValueError, FileExistsError)): self.stage()
        self.output.rmdir()
        with patch.object(self.m, 'MAX_EXTRACTED_BYTES', 1):
            with self.assertRaises(ValueError): self.stage()
        self.assertFalse(self.output.exists())

    def test_dotdot_output_alias_cannot_recurse_into_the_verified_baseline(self):
        alias=self.f.root.parent/'alias';alias.mkdir()
        output=alias/'..'/self.f.root.name/'diagnostic'
        with self.assertRaisesRegex(ValueError,'outside the baseline'): self.stage(output=output)
        self.assertEqual(payload._scan(self.f.root),self.inventory['files'])
        self.assertFalse((self.f.root/'diagnostic').exists())

    def test_interrupted_extraction_already_carries_ordinary_package_rejection_marker(self):
        with patch.object(self.m.shutil,'copyfileobj',side_effect=OSError('synthetic interruption')):
            with self.assertRaisesRegex(OSError,'synthetic interruption'): self.stage()
        self.assertIs(json.loads((self.output/'calc-dispatch-diagnostic.json').read_bytes())['acceptanceEligible'],False)
        self.assertEqual(payload._scan(self.f.root),self.inventory['files'])

    def test_real_branding_failure_keeps_diagnostic_marker_and_cleans_only_fresh_runtime(self):
        self.entries.pop('share/registry/localization.xcd')
        self.write_inputs()
        inputs = (self.archive.read_bytes(),self.receipt.read_bytes())
        with self.assertRaisesRegex(ValueError,'Korean UI language'):
            self.stage()
        self.assertIs(json.loads((self.output/self.m.OVERLAY).read_bytes())['acceptanceEligible'],False)
        self.assertEqual(payload._scan(self.f.root),self.inventory['files'])
        self.assertEqual(inputs,(self.archive.read_bytes(),self.receipt.read_bytes()))
        self.assertFalse((self.output/'Office').exists())
        self.assertFalse(any(path.name.startswith('raw-runtime-') for path in self.output.iterdir()))
        with self.assertRaisesRegex(ValueError,'Missing required Suite payload files'):
            payload.verify_payload(self.output,payload._json(self.output/payload.INVENTORY))

    def test_cli_requires_explicit_dispatch_mode_and_rejects_mixed_modes(self):
        self.stage()
        with patch.object(ime,'os',SimpleNamespace(name='nt',environ={})), \
             patch.object(ime.native_arch,'observe_native_architecture',return_value={}), \
             patch.object(ime.native_arch,'validate_native_architecture',return_value={}):
            with self.assertRaisesRegex(AssertionError,'requires explicit Calc dispatch mode'):
                ime.main(['--suite',str(self.output)])
            with self.assertRaisesRegex(AssertionError,'mutually exclusive'):
                ime.main(['--suite',str(self.output),'--diagnose-calc-dispatch','--diagnose-ime-mode','calc'])
            with self.assertRaisesRegex(AssertionError,'pinned.*engine source'):
                ime.main(['--suite',str(self.output),'--diagnose-calc-dispatch'])
        fresh=json.loads((self.output/payload.INVENTORY).read_bytes());fresh['architecture']='x64'
        with self.assertRaisesRegex(AssertionError,'ARM64'):
            ime.require_calc_dispatch_suite(self.output,fresh,expected_engine_source_commit='b'*40)

    def test_consumer_rejects_unpinned_or_tampered_source_joins_after_inventory_refresh(self):
        self.stage()
        original = (self.output/self.m.OVERLAY).read_bytes()
        for changes, engine in (({}, 'd'*40), ({'engineSourceCommit':'d'*40}, 'd'*40),
                                ({'admittedSuiteSourceCommit':'b'*40}, 'b'*40),
                                ({'schemaVersion':1}, 'b'*40), ({'sourceLockSha256':'d'*64}, 'b'*40)):
            with self.subTest(changes=changes, engine=engine):
                overlay = json.loads(original); overlay.update(changes)
                (self.output/self.m.OVERLAY).write_text(json.dumps(overlay))
                fresh = dict(schemaVersion=1, architecture='arm64', files=payload._scan(self.output))
                with self.assertRaises(AssertionError):
                    ime.require_calc_dispatch_suite(self.output, fresh, expected_engine_source_commit=engine)
        (self.output/self.m.OVERLAY).write_bytes(original)

    def test_same_engine_and_suite_source_is_still_valid_when_both_are_pinned(self):
        self.marker['sourceCommit'] = 'a'*40
        self.entries[self.m.MARKER] = json.dumps(self.marker).encode()
        self.write_inputs(); self.proof['sourceCommit'] = 'a'*40
        self.receipt.write_text(json.dumps(self.proof))
        result = self.stage(expected_engine_source_commit='a'*40)
        self.assertEqual('a'*40, result['engineSourceCommit'])
        self.assertEqual('a'*40, result['admittedSuiteSourceCommit'])

    def test_staging_cli_requires_and_preserves_the_two_explicit_source_pins(self):
        args = ['--baseline',str(self.f.root), '--archive',str(self.archive), '--receipt',str(self.receipt),
                '--output',str(self.output), '--expected-engine-source-commit','b'*40,
                '--expected-suite-source-commit','a'*40, '--expected-receipt-sha256',sha(self.receipt),
                '--expected-archive-sha256',sha(self.archive)]
        printed = io.StringIO()
        with redirect_stdout(printed): self.assertEqual(0, self.m.main(args))
        overlay = json.loads(printed.getvalue())
        self.assertEqual('b'*40, overlay['engineSourceCommit'])
        self.assertEqual('a'*40, overlay['admittedSuiteSourceCommit'])

    def test_main_joins_consumer_ci_source_and_readiness_without_relabeling_engine(self):
        from test_korean_ime_smoke import KoreanImePolicyTests
        self.stage()
        root = self.f.root.parent; fixtures = root/'fixtures'; fixtures.mkdir()
        readiness = KoreanImePolicyTests().readiness()
        readiness['nativeMachine'] = readiness['profile']['component']['machine'] = 0xaa64
        readiness['source']['architecture'] = 'arm64'
        branch = 'refs/heads/work/opengeul-office-arm64'
        env = dict(GITHUB_ACTIONS='true', RUNNER_ENVIRONMENT='github-hosted', RUNNER_OS='Windows',
            RUNNER_ARCH='ARM64', GITHUB_REPOSITORY='ATLKR/OpenGeul', GITHUB_EVENT_NAME='push',
            GITHUB_JOB='windows-suite', GITHUB_REF=branch, GITHUB_WORKFLOW_REF='ATLKR/OpenGeul/.github/workflows/office-suite.yml@'+branch,
            GITHUB_SHA='a'*40, GITHUB_WORKFLOW_SHA='a'*40, GITHUB_RUN_ID='1', GITHUB_RUN_ATTEMPT='1',
            GITHUB_ACTOR='ATLKR', GITHUB_ACTOR_ID='65988341')
        for index, (ci_source, readiness_changes, engine, error) in enumerate((
                ('a'*40, {}, 'b'*40, None), ('a'*40, {}, 'd'*40, 'engine source'),
                ('d'*40, {}, 'b'*40, 'admitted CI source'),
                ('a'*40, {'sourceCommit':'b'*40}, 'b'*40, 'readiness'),
                ('a'*40, {'sourceRun':'2'}, 'b'*40, 'readiness'))):
            output = root/('run-'+str(index)); event = root/'event.json'; ready = root/'readiness.json'
            event.write_text(json.dumps(dict(repository=dict(full_name='ATLKR/OpenGeul', id=123, private=False),
                sender=dict(login='ATLKR', id=65988341, type='User'), ref=branch, deleted=False, after=ci_source)))
            actual_readiness = dict(readiness, source={**readiness['source'], **readiness_changes})
            ready.write_text(json.dumps(actual_readiness))
            actual_env = dict(env, GITHUB_SHA=ci_source, GITHUB_WORKFLOW_SHA=ci_source)
            args = ['--suite',str(self.output), '--fixtures',str(fixtures), '--readiness',str(ready),
                    '--output',str(output), '--diagnose-calc-dispatch', '--expected-engine-source-commit',engine]
            with self.subTest(index=index), patch.object(ime,'os',SimpleNamespace(name='nt',environ=actual_env)), \
                    patch.dict(os.environ, {'GITHUB_EVENT_PATH':str(event)}), \
                    patch.object(ime.native_arch,'observe_native_architecture',return_value={}), \
                    patch.object(ime.native_arch,'validate_native_architecture',return_value={}), \
                    patch.object(ime,'run_calc_dispatch_diagnostic',return_value=0) as run:
                if error is None:
                    self.assertEqual(0, ime.main(args))
                    self.assertEqual('a'*40, run.call_args.args[-1]['sourceCommit'])
                    self.assertEqual(actual_readiness, run.call_args.args[3])
                else:
                    with self.assertRaisesRegex(AssertionError, error): ime.main(args)
                    run.assert_not_called()
                    if error != 'readiness': self.assertFalse(output.exists())


class SaveIntegrationTests(unittest.TestCase):
    def _run_original_case(self, *, fail_marker=False, swallowed_close_failure=False,
                           real_keyboard_close=False, check_persistence=False):
        sys.path.insert(0,str(ROOT/'suite/tests'))
        from test_ime_case_phases import IMECasePhaseTests
        harness=IMECasePhaseTests(methodName='runTest');self.addCleanup(harness.doCleanups)
        calls=[];original_case=ime.case;original_save=ime.save_with_calc_dispatch
        class Transport:
            closed=False
            def child_environment(inner,base): calls.append('child-env');return dict(base)
            def arm(inner,owner,deadline,started_at,**kw):
                calls.append('arm');inner.deadline=deadline;inner.observation_deadline=deadline-5
            def close(inner,dispose=None):
                if not inner.closed:
                    calls.append('transport-close');dispose(inner.deadline);inner.closed=True
                return dict(analysis=dict(processExitProved=1),cleanup=dict(controllerResourcesReleased=1,errors=[]))
        transport=Transport()
        def case(*args,**kw):
            readiness=args[3];readiness['nativeMachine']=0xaa64
            readiness['profile']['component']['machine']=0xaa64
            readiness['source']['architecture']='arm64'
            if not check_persistence:
                return original_case(*args,**kw,calc_dispatch_transport=transport)
            self.persisted_case_root = args[2]
            self.composing_captures = []
            window = sys.modules['pywinauto'].Desktop().window(handle=11).wrapper_object()
            original_capture = window.capture_as_image
            window.capture_as_image = lambda:self.composing_captures.append(True) or original_capture()
            original_keyboard = ime.IMEKeyboardSession
            def keyboard(*args, **kwargs):
                result = original_keyboard(*args, **kwargs)
                self.case_keyboard_retention = result.retain_evidence
                return result
            with patch.object(ime,'write_result',side_effect=windows_smoke.write_result), \
                    patch.object(ime,'IMEKeyboardSession',side_effect=keyboard):
                return original_case(*args,**kw,calc_dispatch_transport=transport)
        def save(active,keyboard,record,source):
            keyboard.handle=909;keyboard.process._handle=808
            keyboard.engine=dict(pid=31,handleValue=909,creationTime=2**55+100,image='original-engine.bin')
            keyboard.shell=dict(pid=77,handleValue=808,creationTime=2**55,image='original-shell.exe')
            keyboard.probe=SimpleNamespace()
            record['imeKeyboardSession'].update(engineHandleReleased=not swallowed_close_failure,cleanupErrors=[])
            record['imeEngineRetirement']=dict(close=dict(result=not swallowed_close_failure),cleanupErrors=[])
            if real_keyboard_close:
                from ime_keyboard_session import IMEKeyboardSession
                begin, close = keyboard.begin_save, keyboard.close
                def begin_with_deadline(restoration, deadline):
                    keyboard.deadline = deadline
                    record['imeKeyboardSession']['saveDeadline'] = deadline
                    return begin(restoration, deadline)
                def close_in_reserve(primary=None):
                    close(primary)
                    keyboard.finished=False; keyboard.failed=None; keyboard.phase='saved'
                    keyboard.clock=lambda:active.observation_deadline+2
                    keyboard.probe.close_engine=lambda handle:True
                    keyboard.receipt=record['imeKeyboardSession']; keyboard.output=keyboard.stem=None
                    IMEKeyboardSession.close(keyboard, primary)
                keyboard.begin_save=begin_with_deadline
                keyboard.close=close_in_reserve
            if fail_marker:
                with patch.object(ime,'wait_saved_ime_marker',side_effect=AssertionError('synthetic marker deadline')):
                    return original_save(active,keyboard,record,source)
            return original_save(active,keyboard,record,source)
        def dispose(process,shell,deadline,**kw):
            calls.append('dispose');self.assertEqual(deadline,transport.deadline)
            self.assertEqual(kw['engine']['handleValue'],909)
            return dict(error=0,shellExitObserved=True,shellHandleReleased=True)
        with patch.object(ime,'case',side_effect=case),patch.object(ime,'save_with_calc_dispatch',side_effect=save), \
             patch.object(ime,'dispose_calc_dispatch_shell',side_effect=dispose):
            phases,record,result,error=harness.run_case('calc',save_cleanup_reserve=5)
        return phases,record,result,error,calls

    def test_real_case_restores_hooks_then_one_save_then_original_budget_disposal(self):
        phases,record,result,error,calls=self._run_original_case()
        self.assertIsNone(error,repr(error));self.assertIs(result,record)
        self.assertEqual(calls,['child-env','arm','transport-close','dispose'])
        self.assertEqual(phases.count('CTRL_S'),1);self.assertEqual(phases.count('ENTER'),1)
        self.assertLess(phases.index(('command',4)),phases.index('observer-close'))
        self.assertLess(phases.index('observer-close'),phases.index('save-budget-started'))
        self.assertLess(phases.index('CTRL_S'),phases.index('keyboard-close'))
        self.assertFalse(any(isinstance(row,tuple) and row[0]=='failure-teardown' for row in phases))
        self.assertNotIn('final-stop',phases);self.assertNotIn('independent-reopen',phases)
        self.assertIs(record['calcDispatchLocalCleanup']['withinDeadline'],True)
        self.assertIs(record['imeVerified'],False)

    def test_calc_case_never_captures_screen_or_persists_raw_record_on_success_or_failure(self):
        for fail in (False, True):
            with self.subTest(fail=fail):
                phases,record,result,error,calls = self._run_original_case(fail_marker=fail, check_persistence=True)
                self.assertEqual([], self.composing_captures)
                self.assertIs(self.case_keyboard_retention, False)
                if fail: self.assertRegex(str(error), 'synthetic marker deadline')
                self.assertEqual(['calc-dispatch-diagnostic.json'],
                                 sorted(path.name for path in self.persisted_case_root.glob('*.json')))
                numeric = json.loads((self.persisted_case_root/'calc-dispatch-diagnostic.json').read_bytes())
                self.assertEqual(record['calcDispatchOracle'], numeric['originalSaveOracle'])
                self.assertEqual(record['calcDispatchLocalCleanup'], numeric['localCleanup'])
                self.assertFalse(any(key in numeric for key in ('keyTokens','asciiPrefix','events','error','traceback')))
                self.assertEqual(1, phases.count('CTRL_S'))

    def test_completed_save_can_close_inside_original_cleanup_reserve(self):
        phases,record,result,error,calls=self._run_original_case(real_keyboard_close=True)
        self.assertIsNone(error,repr(error))
        self.assertEqual(record['calcDispatchLocalCleanup']['errors'], [])
        receipt=record['imeKeyboardSession']
        self.assertIs(receipt['success'], True)
        self.assertGreater(receipt['finishedAt'], receipt['saveDeadline'])
        self.assertLess(receipt['finishedAt'], record['imeSaveBudget']['deadline'])

    def test_original_oracle_failure_cannot_hide_swallowed_native_close_errors(self):
        phases,record,result,error,calls=self._run_original_case(fail_marker=True,swallowed_close_failure=True)
        self.assertRegex(str(error),'synthetic marker deadline')
        self.assertEqual(record['calcDispatchLocalCleanup']['errors'],[1,2])
        self.assertIs(record['calcDispatchOracle']['savedMarkerObserved'],False)
        self.assertEqual(calls,['child-env','arm','transport-close','dispose'])
        self.assertEqual(phases.count('CTRL_S'),1)
        self.assertNotIn('final-stop',phases)
        report=ime.calc_dispatch_report(record)
        self.assertEqual(report['localCleanup']['errors'],[1,2])

    def test_child_environment_is_explicit_and_never_changes_parent(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); environment = {'SYNTHETIC':'unchanged'}
            with patch.object(windows_smoke, 'prepare_launch_pointer'), \
                 patch.object(windows_smoke.subprocess, 'Popen', return_value=SimpleNamespace()) as popen:
                windows_smoke.launch_suite(['owned.exe'], root, root, 'calc', environment=environment)
            self.assertIs(popen.call_args.kwargs['env'], environment)

    def test_original_single_save_shares_exact_deadline_and_reserves_cleanup(self):
        calls = []; record = dict(restoration={'owned':True}); original = object()
        keyboard = SimpleNamespace(engine=dict(pid=12, creationTime=34), handle=56, tid=78, focus=90,
            begin_save=lambda restoration, deadline:calls.append(('begin', restoration, deadline)),
            save=lambda:calls.append(('save',)))
        transport = SimpleNamespace(observation_deadline=35.,
            arm=lambda owner, deadline, started_at, **kw:calls.append(('arm',owner,deadline,started_at,kw)))
        with patch.object(ime.time, 'monotonic', return_value=10.), \
             patch.object(ime, 'wait_saved_ime_marker', side_effect=lambda *args:calls.append(('wait',args))):
            ime.save_with_calc_dispatch(transport, keyboard, record, original)
        self.assertEqual(record['imeSaveBudget'], dict(startedAt=10., deadline=40.))
        self.assertEqual([row[0] for row in calls], ['arm','begin','save','wait'])
        self.assertEqual(calls[0], ('arm',dict(pid=12,creationTime=34,tid=78,hwnd=90,handleValue=56),40.,10.,dict(engine_handle=56)))
        self.assertEqual(calls[1], ('begin', record['restoration'], 35.))
        self.assertEqual(calls[-1][1], (original,'calc',35.,record))
        self.assertIs(record['calcDispatchOracle']['savedMarkerObserved'], True)

    def test_save_failure_retains_admission_without_retry_or_renewal(self):
        record = dict(restoration={}); calls = []
        keyboard = SimpleNamespace(engine=dict(pid=12,creationTime=34),handle=56,tid=78,focus=90,
            begin_save=lambda *args:None, save=lambda:(_ for _ in ()).throw(AssertionError('original failed')))
        transport = SimpleNamespace(observation_deadline=35.,arm=lambda *a,**kw:calls.append(a))
        with patch.object(ime.time,'monotonic',return_value=10.), patch.object(ime,'wait_saved_ime_marker') as wait:
            with self.assertRaisesRegex(AssertionError,'original failed'):
                ime.save_with_calc_dispatch(transport,keyboard,record,Path('/synthetic'))
        self.assertEqual(len(calls),1); wait.assert_not_called()
        self.assertEqual(record['imeSaveBudget']['deadline'],40.)
        self.assertIs(record['calcDispatchOracle']['savedMarkerObserved'],False)

    def test_retained_shell_disposal_uses_original_handle_and_remaining_budget(self):
        calls = []
        class Handle:
            def __int__(self): return 99
            def Close(self): calls.append(('close',))
        process = SimpleNamespace(pid=12,_handle=Handle(),returncode=None,poll=lambda:None,
            kill=lambda:calls.append(('kill',)),wait=lambda **kw:calls.append(('wait',kw)) or -1)
        result = ime.dispose_calc_dispatch_shell(process,dict(pid=12,handleValue=99),40.,clock=lambda:37.)
        self.assertEqual(calls,[('kill',),('wait',dict(timeout=3.)),('close',)])
        self.assertIs(result['shellExitObserved'],True)
        self.assertIs(result['shellHandleReleased'],True)
        calls.clear()
        result = ime.dispose_calc_dispatch_shell(process,dict(pid=12,handleValue=99),40.,clock=lambda:40.)
        self.assertEqual(calls,[('close',)]); self.assertEqual(result['error'],1)
        self.assertIs(result['shellHandleReleased'],True)

    def test_both_original_generations_are_checked_before_one_tree_disposal(self):
        calls=[]
        class Handle:
            def __int__(self): return 99
            def Close(self): calls.append(('close',))
        shell=dict(pid=12,handleValue=99,creationTime=100,image='owned-shell.exe')
        engine=dict(pid=13,handleValue=88,creationTime=101,image='owned-engine.bin')
        process=SimpleNamespace(pid=12,_handle=Handle(),returncode=None,
            wait=lambda **kw:calls.append(('wait',kw)) or -1)
        def live(handle):
            calls.append(('live',handle))
            return dict(shell if handle==99 else engine,waitResult=258)
        def run(*args,**kw): calls.append(('taskkill',args,kw))
        result=ime.dispose_calc_dispatch_shell(process,shell,40.,engine=engine,live=live,run=run,clock=lambda:37.)
        self.assertEqual([row[0] for row in calls],['live','live','taskkill','wait','close'])
        self.assertEqual(calls[2][1][0],['taskkill.exe','/PID','12','/PID','13','/T','/F'])
        self.assertEqual(calls[2][2]['timeout'],3.)
        self.assertEqual(result['targets'],[12,13])
        calls.clear()
        def stale(handle):
            row=live(handle);row['creationTime']+=1;return row
        result=ime.dispose_calc_dispatch_shell(process,shell,40.,engine=engine,live=stale,run=run,clock=lambda:37.)
        self.assertEqual([row[0] for row in calls],['live','close'])
        self.assertFalse(result['killAttempted']);self.assertEqual(result['error'],3)

    def test_diagnostic_runner_invokes_one_calc_case_and_never_qualifies_ime(self):
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)
            record=dict(success=True,imeVerified=False,calcDispatchDiagnostic=dict(analysis=dict(complete=1,processExitProved=1),
                cleanup=dict(controllerResourcesReleased=1,errors=[])),
                calcDispatchOracle=dict(saveAttempted=True,saveReturned=True,savedMarkerObserved=True),
                calcDispatchLocalCleanup=dict(errors=[],withinDeadline=True))
            with patch.object(ime.ascii_input,'prepare_observer',return_value='library'), \
                 patch.object(ime,'case',return_value=record) as case, \
                 patch.dict(sys.modules,{'calc_dispatch_diagnostic':SimpleNamespace(DiagnosticTransport=lambda **kw:SimpleNamespace(close=lambda:None))}):
                code=ime.run_calc_dispatch_diagnostic(Path('/suite'),Path('/fixtures'),output,{},'arm64',{})
            self.assertEqual(code,0); self.assertEqual(case.call_count,1)
            self.assertEqual(case.call_args.args[4:6],('calc','xlsx'))
            report=json.loads((output/'results.json').read_bytes())
            self.assertIs(report['acceptanceEligible'],False);self.assertIs(report['imeVerified'],False)
            self.assertNotIn('tests',report)

    def test_diagnostic_runner_never_uses_raw_collector_even_when_case_raises(self):
        for fail in (False, True):
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as folder:
                output = Path(folder); forbidden = 'SYNTHETIC-PRIVATE-INPUT'
                record = dict(success=not fail, keyTokens=[forbidden], asciiPrefix=forbidden,
                    events=[dict(result=forbidden)], traceback=forbidden,
                    calcDispatchOracle=dict(saveAttempted=True,saveReturned=not fail,savedMarkerObserved=not fail),
                    calcDispatchDiagnostic=dict(analysis=dict(processExitProved=1),cleanup=dict(controllerResourcesReleased=1,errors=[])),
                    calcDispatchLocalCleanup=dict(errors=[],withinDeadline=True))
                def case(*args, **kwargs):
                    if fail:
                        (output/'calc-dispatch-diagnostic.json').write_text(json.dumps(ime.calc_dispatch_report(record)))
                        raise AssertionError(forbidden)
                    return record
                binding = dict(sourceCommit='a'*40,runId='1',runAttempt='1',architecture='arm64')
                printed = io.StringIO()
                with patch.object(ime.ascii_input,'prepare_observer',return_value='library'), \
                        patch.object(ime,'case',side_effect=case), redirect_stdout(printed), \
                        patch.dict(sys.modules, {'calc_dispatch_diagnostic':SimpleNamespace(
                            DiagnosticTransport=lambda **kw:SimpleNamespace(close=lambda:None))}):
                    self.assertEqual(1 if fail else 0,
                        ime.run_calc_dispatch_diagnostic(Path('/suite'),Path('/fixtures'),output,{},'arm64',binding))
                saved = json.loads((output/'results.json').read_bytes())
                self.assertEqual(binding, saved['runBinding'])
                self.assertEqual(record['calcDispatchOracle'], saved['originalSaveOracle'])
                self.assertFalse((output/'ime-calc-result.json').exists())
                self.assertNotIn(forbidden, printed.getvalue())
                self.assertTrue(all(forbidden not in path.read_text() for path in output.glob('*.json')))

    def test_diagnostic_runner_rejects_failure_before_shortcut_returned(self):
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)
            record=dict(success=False,calcDispatchDiagnostic=dict(
                analysis=dict(complete=0,processExitProved=1),
                cleanup=dict(controllerResourcesReleased=1,errors=[])),
                calcDispatchOracle=dict(saveAttempted=True,saveReturned=False,savedMarkerObserved=False),
                calcDispatchLocalCleanup=dict(errors=[],withinDeadline=True))
            with patch.object(ime.ascii_input,'prepare_observer',return_value='library'), \
                 patch.object(ime,'case',return_value=record), \
                 patch.dict(sys.modules,{'calc_dispatch_diagnostic':SimpleNamespace(DiagnosticTransport=lambda **kw:SimpleNamespace(close=lambda:None))}):
                code=ime.run_calc_dispatch_diagnostic(Path('/suite'),Path('/fixtures'),output,{},'arm64',{})
            self.assertEqual(code,1)
            self.assertIs(json.loads((output/'results.json').read_bytes())['success'],False)

    def test_diagnostic_runner_early_failure_writes_only_inconclusive_numeric_report(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder); printed = io.StringIO()
            with patch.object(ime.ascii_input,'prepare_observer',return_value='library'), \
                    patch.object(ime,'case',side_effect=AssertionError('SYNTHETIC-PRIVATE-INPUT')), \
                    redirect_stdout(printed), patch.dict(sys.modules, {'calc_dispatch_diagnostic':SimpleNamespace(
                        DiagnosticTransport=lambda **kw:SimpleNamespace(close=lambda:None))}):
                self.assertEqual(1, ime.run_calc_dispatch_diagnostic(Path('/suite'),Path('/fixtures'),output,{},'arm64',{}))
            self.assertEqual(['results.json'], [path.name for path in output.iterdir()])
            report = json.loads((output/'results.json').read_bytes())
            self.assertEqual(dict(saveAttempted=False,saveReturned=False,savedMarkerObserved=False), report['originalSaveOracle'])
            self.assertEqual(dict(errors=[5],withinDeadline=False), report['localCleanup'])
            self.assertNotIn('SYNTHETIC-PRIVATE-INPUT', printed.getvalue()+(output/'results.json').read_text())


if __name__ == '__main__': unittest.main()
