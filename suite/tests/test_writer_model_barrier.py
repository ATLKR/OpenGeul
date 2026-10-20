"""Read-only completion contracts and actual Case.edit regressions.

Synthetic receipts test policy and unavoidable OS boundaries only. They are
never evidence that an actual Windows editor accepted physical input.
"""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch


E2E = Path(__file__).resolve().parents[1] / 'e2e'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lifecycle = load('model_barrier_original_lifecycle', E2E / 'lifecycle_smoke.py')
style = load('model_barrier_original_style', E2E / 'writer_style_smoke.py')
reader_fixtures = load('model_barrier_native_fixtures', E2E.parent / 'tests/test_writer_model_reader.py')


def retime_native_cleanup_fixture(cleanup):
    """Keep synthetic native call times consistent with the test controller clock."""
    at=cleanup['startedAt']
    for row in cleanup['readerMembers']:
        row['sampleStartedAt']=row['sampleFinishedAt']=at
        row['membershipCall']['observedAt']=at
        for call in row['stateCalls']:call['observedAt']=at
    cleanup.update(reader_fixtures.state_receipt_fixture(cleanup['readerMembers']))
    cleanup['lastJobCensus']=reader_fixtures.census_fixture([],at=at,sequence=1,phase='release-final')


def synthetic_frame(suite, baseline):
    paths = {'launcher': 'Office/program/python.exe',
        'executable': 'Office/program/python-core-3.13.15/bin/python.exe',
        'pythonDll': 'Office/program/python313.dll', 'uno': 'Office/program/uno.py',
        'pyuno': 'Office/program/pyuno.pyd',
        'encodings': 'Office/program/python-core-3.13.15/lib/encodings/__init__.py',
        'os': 'Office/program/python-core-3.13.15/lib/os.py'}
    inventory = {'schemaVersion': 1, 'architecture': 'x64', 'files': {}}
    for role, relative in paths.items():
        path = suite / relative; path.parent.mkdir(parents=True, exist_ok=True)
        data = ('synthetic identity fixture ' + role).encode(); path.write_bytes(data)
        inventory['files'][relative] = {'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    (suite / 'suite-inventory.json').write_text(json.dumps(inventory))
    core = str(suite / 'Office/program/python-core-3.13.15')
    observed = dict(implementation='cpython', version=[3, 13, 15], executable=core,
        processImage=str(suite / paths['executable']), prefix=core, basePrefix=core,
        pythonDll=str(suite / paths['pythonDll']),
        moduleFiles={k: str(suite / paths[k]) for k in ('uno','pyuno','encodings','os')},
        moduleOrigins={k: str(suite / paths[k]) for k in ('uno','pyuno','encodings')})
    binding = dict(reader_fixtures.binding_fixture(),
        expectedImage=str(suite / 'Office/program/soffice.bin'), documentUrl=(suite / 'owned.docx').as_uri())
    (suite / 'owned.docx').write_bytes(b'unchanged synthetic owned document bytes')
    return SimpleNamespace(suite=suite, baseline=baseline, binding=binding,
                           identity=style.require_packaged_python(suite, observed), inventory=inventory,
                           inventory_sha256=hashlib.sha256((suite/'suite-inventory.json').read_bytes()).hexdigest())


def model_observation(frame, body, started=0.0, finished=0.0):
    observation = dict(kind='existing-owned-writer-body', bodyText=body,
        bindingBefore=copy.deepcopy(frame.binding), bindingAfter=copy.deepcopy(frame.binding),
        pythonIdentity=copy.deepcopy(frame.identity), retainedProcessHandle=True,
        handleSignaled=False, readOnlyObservation=True, sameFrameControllerModelVerified=True,
        readCallCleanupSucceeded=True, readerStillRetained=True, readStartedAt=started, readFinishedAt=finished,
        operations=['resolve-existing-owned-frame','Text.getString','isModified','verify-retained-generation'])
    observation.update(reader_fixtures.native_fixture(frame.binding,str(frame.suite)))
    return observation


def replace_console_host_identity(raw, field):
    """Substitute an internally consistent witness for a different OS file."""
    witness=raw['systemConsoleHost']
    infos=[witness['fileInfoBefore'],witness['fileInfoAfterHash'],raw['systemConsoleHostRecheck']]
    if field=='osPath':
        directory='D:/Windows/System32';path=directory+'/conhost.exe'
        witness['systemDirectoryQuery'].update(path=directory,returnedLength=len(directory.encode('utf-16-le'))//2)
        witness['path']=path
        for info in infos:info['finalPath']=path
    elif field=='fileId':
        for info in infos:info['fileIndexLow']+=1
    elif field=='sha256':witness['sha256']='f'*64
    elif field=='retainedFileHandle':
        original=witness['handleValue'];witness['handleValue']+=1
        for row in raw.get('handleClosures',[]):
            if row['kind']=='system-console-file' and row['handleValue']==original:row['handleValue']=witness['handleValue']
    elif field=='fileGeneration':
        for info in infos:info['creationTime']+=1
    else:raise AssertionError('Unknown witness substitution')


def replace_profile_directory_identity(raw, field, origin=None):
    """Keep a replacement DIRECTORY proof locally consistent, including closure."""
    if 'nativeSnapshots' in raw:
        profiles=[(name,raw['nativeSnapshots'][name+edge]['profileDirectory'],[])
            for name in ('controller','helper') for edge in ('Before','After')]
    else:
        profiles=[('controller',raw[edge]['profileDirectory'],raw['handleClosures']) for edge in ('nativeBefore','nativeAfter')]
        ack=raw['releaseAcknowledgement']
        profiles.append(('helper',ack['profileDirectory'],ack['observerHandleClosures']))
    for name,profile,closures in profiles:
        witness=profile['witness'];infos=[witness['openedInfo'],profile['recheck']]
        if field=='canonicalPath':
            witness['canonicalPath']='C:\\other-owned-profile'
            for info in infos:info['finalPath']='\\\\?\\'+witness['canonicalPath']
        elif field=='fileId':
            for info in infos:info['fileIndexLow']+=1
        elif field=='handle' and name==origin:
            original=witness['handleValue'];witness['handleValue']+=1000
            for closure in closures:
                if closure['kind']=='profile-directory' and closure['handleValue']==original:closure['handleValue']=witness['handleValue']


def original_shell_fixture(binding,suite_root):
    image=str(suite_root)+'/OpenGeul.Office.exe'
    created=binding['shellCreationTime']
    return dict(kind='retained-suite-popen-process',pid=binding['shellPid'],handleValue=901,
        nativeImage=image,nativeImageLength=len(image.encode('utf-16-le'))//2,
        nativeCreation=dict(low=created&0xffffffff,high=created>>32,fileTime=created),
        waitResult=258,exitCode=259)


def case_fixture(frame,case_name='dirty-writer-cancel-save'):
    """Exercise actual pure policy + original readiness/input receipt producers."""
    api=load('synthetic_whole_case_policy',E2E/'writer_model_barrier.py')
    ascii_fixtures=load('synthetic_whole_case_ascii',E2E.parent/'tests/test_ascii_editor_input.py')
    clock=FakeClock();binding=frame.binding
    record=dict(case=case_name,shellPid=binding['shellPid'],attachments=[dict(hwnd=binding['suiteHwnd'],
        parent=binding['parentHwnd'],child=binding['childHwnd'],officePid=binding['officePid'])],writerModelCompletions=[])
    completed=[]
    for marker in lifecycle.ASCII_EDITOR_MARKERS[case_name]:
        prior=frame.baseline+''.join(completed);now=clock()
        plan=api.freeze_expectation(binding,frame.baseline,completed,marker,model_observation(frame,prior,now,now),
            suite_root=frame.suite,original_shell=original_shell_fixture(binding,frame.suite),
            inventory=frame.inventory,inventory_sha256=frame.inventory_sha256,started_at=now)
        boundary=ascii_fixtures.FakeWindows()
        with patch.object(lifecycle.native.time,'sleep'):
            lifecycle.native.prepare_editor_focus(boundary,11,22,77,88,record,lambda:None,lambda:None)
        with patch.object(lifecycle.native.ascii_input.time,'sleep'):
            lifecycle.native.ascii_input.type_ascii(boundary,11,22,marker,record,pause=.025)
        clock.pause(len(marker)*.025)
        receipt={}
        reader=ReadOnlySequence([model_observation(frame,prior+marker)],clock)
        api.await_completion(plan,reader,clock=clock,pause=clock.pause,record=receipt)
        cleanup=reader_fixtures.cleanup_fixture(binding,str(frame.suite))
        cleanup.update(startedAt=clock(),finishedAt=clock()+.01,deadline=plan.deadline)
        retime_native_cleanup_fixture(cleanup)
        clock.pause(.01);api.finalize_completion(plan,receipt,cleanup,clock())
        record['writerModelCompletions'].append(receipt);completed.append(marker);clock.pause(.1)
    return api,record


class RealBarrierContextAdapter:
    """Future Case factory seam. Invoke real proposed functions, never fake success."""
    def __init__(self, harness, frame):
        self.harness, self.frame, self.completed_markers = harness, frame, []
        self.records = []

    def begin(self, marker):
        source = E2E / 'writer_model_barrier.py'
        assert source.is_file(), 'RED: real Writer completion module is required'
        self.api = load('actual_barrier_integration_contract', source)
        self.marker = marker; self.record = {}; self.records.append(self.record)
        now = self.harness.clock()
        return self.api.freeze_expectation(self.frame.binding, self.frame.baseline,
            self.completed_markers, marker, model_observation(self.frame,self.harness.body,now,now),
            suite_root=self.frame.suite, original_shell=original_shell_fixture(self.frame.binding,self.frame.suite), inventory=self.frame.inventory, inventory_sha256=self.frame.inventory_sha256, started_at=now, timeout_seconds=12.0)

    def complete(self, plan):
        def reader(deadline):
            started = self.harness.clock(); self.harness.clock.pause(0.01)
            return model_observation(self.frame,self.harness.body,started,self.harness.clock())
        result = self.api.await_completion(plan,reader,clock=self.harness.clock,
            pause=self.harness.clock.pause,record=self.record,max_reads=120)
        cleanup = reader_fixtures.cleanup_fixture(plan.binding,str(self.frame.suite))
        cleanup.update(startedAt=self.harness.clock(),finishedAt=self.harness.clock()+0.01,deadline=plan.deadline)
        retime_native_cleanup_fixture(cleanup)
        self.harness.clock.pause(0.01)
        self.api.finalize_completion(plan,self.record,cleanup,self.harness.clock())
        self.completed_markers.append(self.marker)  # Only actual validator success advances the ledger.
        return result

    def abort(self, exc):
        # This adapter owns no process or model capability to clean up.
        self.record.setdefault('error', type(exc).__name__ + ': ' + str(exc))


class OriginalEditHarness:
    """Replace only unavoidable OS/input boundaries; run actual Case.edit."""
    def __init__(self, bodies):
        self.bodies = iter(bodies)
        self.body = 'known baseline\n'
        self.temp = tempfile.TemporaryDirectory()
        self.frame = synthetic_frame(Path(self.temp.name).resolve(),self.body)
        self.clock = FakeClock()
        self.completion = RealBarrierContextAdapter(self,self.frame)
        self.events = []
        self.title_checks = 0
        self.case = object.__new__(lifecycle.Case)
        self.case.record = {'attachments': [{'hwnd': 11, 'child': 22, 'officePid': 88}]}
        self.case.process = SimpleNamespace(pid=77)
        self.case.suite = self.frame.suite
        self.case._writer_model_context = lambda hwnd,child:self.completion
        self.case.api = SimpleNamespace(require_foreground=lambda hwnd: None,
            require_editor_focus=lambda hwnd, child: 22, title=self.title)
        window = SimpleNamespace(set_focus=lambda: self.events.append(('focus',)),
                                 click_input=lambda: self.events.append(('click',)))
        desktop = SimpleNamespace(window=lambda **kw: SimpleNamespace(wrapper_object=lambda: window))
        self.modules = {'pywinauto': SimpleNamespace(Desktop=lambda **kw: desktop),
                        'pywinauto.keyboard': SimpleNamespace(send_keys=self.keys)}

    def title(self, hwnd):
        self.title_checks += 1
        return '* OpenGeul Writer'  # Already dirty before either edit.

    def keys(self, keys, **options):
        self.events.append(('keys', keys, options))

    def prepare(self, api, hwnd, child, shell_pid, office_pid, record, click, enter):
        click(); enter()

    def inject(self, api, hwnd, child, marker, record, *, pause):
        self.events.append(('physical', marker, pause))
        self.body = next(self.bodies)
        self.clock.pause(len(marker)*pause)

    def close(self): self.temp.cleanup()

    def edit(self, marker):
        with patch.dict('sys.modules', self.modules), \
             patch.object(lifecycle.native, 'activate_owned_suite',
                 side_effect=lambda api, process, hwnd, record: api.require_foreground(hwnd)) as activated, \
             patch.object(lifecycle.native, 'prepare_editor_focus', self.prepare), \
             patch.object(lifecycle.native.ascii_input, 'type_ascii', self.inject):
            try:
                lifecycle.Case.edit(self.case, 11, 22, marker)
            finally:
                activated.assert_called_once_with(self.case.api, self.case.process, 11, self.case.record)


class ExistingStalePredicateRedTests(unittest.TestCase):
    def actual_context(self,harness):
        """Use real production context with only the native reader boundary fake."""
        case=harness.case
        case.name='dirty-writer-cancel-save';case.output=harness.frame.suite/'evidence'
        case.source=harness.frame.suite/'owned.docx'
        case.writer_model_baseline={'bodyText':harness.frame.baseline}
        case.record['attachments'][0]['parent']=12
        context=lifecycle.WriterModelContext(case,case.record['attachments'][0])
        case._writer_model_context=lambda hwnd,child:context
        class Reader:
            def __init__(self,suite,output,**kw):
                assert kw['expected_shell_creation']==111
                self.output=output;output.mkdir(parents=True,exist_ok=False);self.binding=harness.frame.binding
            def observe(self,deadline):
                start=harness.clock();harness.clock.pause(.01)
                return model_observation(harness.frame,harness.body,start,harness.clock())
            start=read=observe
            def close(self,deadline):
                harness.events.append(('reader-close',))
                cleanup=reader_fixtures.cleanup_fixture(self.binding,str(harness.frame.suite))
                cleanup.update(startedAt=harness.clock(),finishedAt=harness.clock()+.01,deadline=deadline)
                retime_native_cleanup_fixture(cleanup)
                harness.clock.pause(.01);return cleanup
        def original(process,suite,evidence):
            evidence.update(original_shell_fixture(harness.frame.binding,suite));return 111
        import writer_model_reader
        self.enterContext(patch.object(writer_model_reader,'OwnedWriterReader',Reader))
        self.enterContext(patch.object(lifecycle,'retained_writer_shell',original))
        self.enterContext(patch.object(lifecycle.time,'monotonic',harness.clock))
        self.enterContext(patch.object(lifecycle.time,'sleep',harness.clock.pause))
        return context

    def test_production_context_freezes_baseline_and_releases_each_reader_before_return(self):
        first,second=lifecycle.ASCII_EDITOR_MARKERS['dirty-writer-cancel-save']
        harness=OriginalEditHarness(['known baseline\n'+first,'known baseline\n'+first+second]);self.addCleanup(harness.close)
        context=self.actual_context(harness)
        harness.edit(first);harness.edit(second)
        self.assertEqual(context.completed_markers,[first,second]);self.assertIsNone(context.reader)
        receipts=harness.case.record['writerModelCompletions']
        self.assertEqual([row['state'] for row in receipts],['complete','complete'])
        self.assertEqual([event[0] for event in harness.events if event[0] in ('physical','reader-close')],
            ['physical','reader-close','physical','reader-close'])
        self.assertTrue(all(Path(row['readerOutput'],'completion.json').is_file() for row in receipts))

    def test_production_context_rejects_permanent_loss_without_retry_and_preserves_raw_cleanup(self):
        first=lifecycle.ASCII_EDITOR_MARKERS['dirty-writer-cancel-save'][0]
        harness=OriginalEditHarness(['known baseline\n'+first.replace('CANCEL','CANCE')]);self.addCleanup(harness.close)
        context=self.actual_context(harness)
        with self.assertRaises(AssertionError):harness.edit(first)
        self.assertEqual(context.completed_markers,[]);self.assertTrue(context.failed);self.assertIsNone(context.reader)
        receipt=harness.case.record['writerModelCompletions'][0]
        self.assertFalse(receipt['success']);self.assertEqual(receipt['state'],'failed')
        self.assertTrue(receipt['cleanup']['cleanupSucceeded'])
        with self.assertRaises(AssertionError):context.begin(first)
        self.assertEqual(len([event for event in harness.events if event[0]=='physical']),1)

    def test_second_edit_must_not_complete_on_the_first_edits_dirty_title(self):
        first, second = lifecycle.ASCII_EDITOR_MARKERS['dirty-writer-cancel-save']
        harness = OriginalEditHarness(['known baseline\n' + first] * 2)
        self.addCleanup(harness.close)
        harness.edit(first)
        self.assertEqual(harness.body, 'known baseline\n' + first)
        with self.assertRaises(AssertionError, msg='Incomplete second body must fail before Case.edit returns'):
            harness.edit(second)  # Current source returns immediately, with no second body mutation.
        self.assertEqual(harness.body,'known baseline\n'+first, 'Read-only rejection must not repair text')

    def test_first_edit_must_not_complete_when_only_an_initial_prefix_modified_writer(self):
        marker = lifecycle.ASCII_EDITOR_MARKERS['dirty-writer-cancel-save'][0]
        harness = OriginalEditHarness(['known baseline\n' + marker[:2]])
        self.addCleanup(harness.close)
        with self.assertRaises(AssertionError, msg='Partial first body must fail before Case.edit returns'):
            harness.edit(marker)
        self.assertEqual(harness.body,'known baseline\n'+marker[:2], 'Read-only rejection must not repair a prefix')

    def test_original_dirty_cancel_save_must_not_reach_save_before_second_body_completion(self):
        first, second = lifecycle.ASCII_EDITOR_MARKERS['dirty-writer-cancel-save']
        harness = OriginalEditHarness(['known baseline\n' + first] * 2)
        self.addCleanup(harness.close)
        class SaveReached(Exception): pass
        with tempfile.TemporaryDirectory() as folder:
            case = harness.case
            case.source = harness.frame.suite / 'owned.docx'; case.source.write_bytes(b'unchanged independent fixture bytes')
            case.attach = lambda: (11, 12, 22)
            case.process.poll = lambda: None
            case.api.user = SimpleNamespace(IsWindow=lambda hwnd: True)
            case.edit = lambda hwnd,child,marker:harness.edit(marker)
            choices = []
            def close_choice(hwnd, choice):
                choices.append(choice)
                if choice == '저장': raise SaveReached()
            case.close_choice = close_choice
            with self.assertRaises(AssertionError, msg='Original action must reject incomplete body before Save'):
                try: lifecycle.dirty_cancel_save(case)  # Actual original action through its Save boundary.
                except SaveReached: pass
            self.assertEqual(harness.body, 'known baseline\n' + first)
            self.assertNotIn('저장', choices,
                             'Original dirty_cancel_save reached Save while second marker had not reached the model')

    def test_original_physical_calls_and_character_pause_are_fixed(self):
        first, second = lifecycle.ASCII_EDITOR_MARKERS['dirty-writer-cancel-save']
        harness = OriginalEditHarness(['known baseline\n' + first, 'known baseline\n' + first + second])
        self.addCleanup(harness.close)
        harness.edit(first); harness.edit(second)
        self.assertEqual([e for e in harness.events if e[0] == 'physical'],
                         [('physical', first, 0.025), ('physical', second, 0.025)])
        self.assertEqual([e[1] for e in harness.events if e[0] == 'keys'],
                         ['^{F6}', '^{END}', '^{F6}', '^{END}'])
        self.assertEqual(len([e for e in harness.events if e[0] == 'click']), 2)

    def test_original_scan_buffers_are_replayed_exactly_and_altered_or_extra_input_is_rejected(self):
        fixtures = load('model_barrier_ascii_fixtures', E2E.parent / 'tests/test_ascii_editor_input.py')
        keyboard = lifecycle.native.ascii_input
        for marker in lifecycle.ASCII_EDITOR_MARKERS['dirty-writer-cancel-save']:
            api, record = fixtures.FakeWindows(), {}
            with patch.object(keyboard.time, 'sleep'):
                keyboard.type_ascii(api, 11, 22, marker, record, pause=0.025)
            receipt = record['asciiEditorInputs'][0]
            self.assertEqual(receipt['pauseSeconds'], 0.025)
            keyboard.require_ascii_receipt(receipt, marker, 11, 22)
            self.assertEqual(len(api.sent), len(marker))
            changed = copy.deepcopy(receipt); changed['actions'][-1]['bufferHex'] = '00' * 40
            with self.assertRaises(AssertionError): keyboard.require_ascii_receipt(changed, marker, 11, 22)
            changed = copy.deepcopy(receipt); changed['actions'].append(copy.deepcopy(changed['actions'][-1]))
            with self.assertRaises(AssertionError): keyboard.require_ascii_receipt(changed, marker, 11, 22)


class FakeClock:
    def __init__(self): self.now = 0.0
    def __call__(self): return self.now
    def pause(self, seconds): self.now += seconds


class ReadOnlySequence:
    """One reader capability; no typing, model mutation or document lifecycle API."""
    def __init__(self, observations, clock, duration=0.01):
        self.observations = list(observations)
        self.clock, self.duration, self.deadlines = clock, duration, []
    def __call__(self, deadline):
        self.deadlines.append(deadline)
        self.clock.now += self.duration
        value = self.observations.pop(0) if len(self.observations) > 1 else self.observations[0]
        if isinstance(value, BaseException): raise value
        result = copy.deepcopy(value)
        result['readStartedAt'] = self.clock.now - self.duration
        result['readFinishedAt'] = self.clock.now
        return result


class ProposedCompletionContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.suite = Path(self.temp.name).resolve()
        paths = {'launcher': 'Office/program/python.exe',
            'executable': 'Office/program/python-core-3.13.15/bin/python.exe',
            'pythonDll': 'Office/program/python313.dll', 'uno': 'Office/program/uno.py',
            'pyuno': 'Office/program/pyuno.pyd',
            'encodings': 'Office/program/python-core-3.13.15/lib/encodings/__init__.py',
            'os': 'Office/program/python-core-3.13.15/lib/os.py'}
        inventory = {'schemaVersion': 1, 'architecture': 'x64', 'files': {}}
        for role, relative in paths.items():
            path = self.suite / relative; path.parent.mkdir(parents=True, exist_ok=True)
            data = ('synthetic identity fixture ' + role).encode(); path.write_bytes(data)
            inventory['files'][relative] = {'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        (self.suite / 'suite-inventory.json').write_text(json.dumps(inventory))
        self.inventory = inventory
        self.inventory_sha256 = hashlib.sha256((self.suite/'suite-inventory.json').read_bytes()).hexdigest()
        core = str(self.suite / 'Office/program/python-core-3.13.15')
        observed = dict(implementation='cpython', version=[3, 13, 15], executable=core,
            processImage=str(self.suite / paths['executable']), prefix=core, basePrefix=core,
            pythonDll=str(self.suite / paths['pythonDll']),
            moduleFiles={k: str(self.suite / paths[k]) for k in ('uno','pyuno','encodings','os')},
            moduleOrigins={k: str(self.suite / paths[k]) for k in ('uno','pyuno','encodings')})
        self.identity = style.require_packaged_python(self.suite, observed)
        self.binding = dict(reader_fixtures.binding_fixture(),
            expectedImage=str(self.suite / 'Office/program/soffice.bin'), documentUrl=(self.suite / 'owned.docx').as_uri())
        self.baseline = 'Engine-OpenGeul-writer 한글\n'
        (self.suite / 'owned.docx').write_bytes(b'unchanged synthetic owned document bytes')
        self.first, self.second = lifecycle.ASCII_EDITOR_MARKERS['dirty-writer-cancel-save']
        self.clock = FakeClock()

    def api(self):
        source = E2E / 'writer_model_barrier.py'
        self.assertTrue(source.is_file(), 'RED: read-only Writer model completion barrier is not implemented (tests/design only)')
        return load('proposed_writer_model_barrier', source)

    def observation(self, body, *, binding=None):
        binding = copy.deepcopy(self.binding if binding is None else binding)
        return model_observation(SimpleNamespace(binding=binding,identity=self.identity,suite=self.suite),body)

    def plan(self, completed=()):
        api = self.api(); previous = self.baseline + ''.join(completed)
        marker = self.second if completed else self.first
        return api, api.freeze_expectation(self.binding, self.baseline, completed, marker,
            self.observation(previous), suite_root=self.suite, original_shell=original_shell_fixture(self.binding,self.suite), inventory=self.inventory, inventory_sha256=self.inventory_sha256, started_at=0.0, timeout_seconds=12.0)

    def run_read(self, api, plan, bodies, *, duration=0.01, pause=None, record=None):
        reader = ReadOnlySequence([self.observation(body) if isinstance(body,str) else body for body in bodies], self.clock, duration)
        record = {} if record is None else record
        result = api.await_completion(plan, reader, clock=self.clock,
            pause=self.clock.pause if pause is None else pause, record=record, max_reads=120)
        return result, reader, record

    def test_exact_monotonic_append_prefixes_wait_for_full_body_before_allowing_close(self):
        api, plan = self.plan(); expected = self.baseline + self.first
        result, reader, record = self.run_read(api, plan, [self.baseline, self.baseline+'-', self.baseline+'-LIFE', expected])
        self.assertEqual(result['bodyText'], expected)
        self.assertEqual(reader.deadlines, [12.0] * 4)
        self.assertTrue(record['success']); self.assertEqual(len(record['observations']), 4)

    def test_cumulative_second_edit_includes_first_marker_and_cannot_use_old_complete_receipt(self):
        api, plan = self.plan((self.first,)); prior = self.baseline+self.first
        self.assertEqual(plan.prior_body, prior); self.assertEqual(plan.expected_body, prior+self.second)
        self.assertEqual(api.validate_observation(plan, self.observation(prior), prior), 'pending')
        self.assertEqual(api.validate_observation(plan, self.observation(prior+self.second), prior), 'complete')

    def test_only_crlf_and_cr_normalization_is_permitted(self):
        api, plan = self.plan()
        self.assertEqual(api.validate_observation(plan, self.observation((self.baseline+self.first).replace('\n','\r\n')), self.baseline), 'complete')
        with self.assertRaises(AssertionError): api.validate_observation(plan, self.observation((self.baseline+self.first).replace(' ','  ')), self.baseline)

    def test_permanent_prior_body_times_out_without_extending_one_deadline(self):
        api, plan = self.plan(); record = {}
        with self.assertRaises(AssertionError): self.run_read(api, plan, [self.baseline], record=record)
        self.assertFalse(record['success']); self.assertEqual(record['deadline'],12.0)
        self.assertLessEqual(self.clock.now,12.01)

    def test_permanent_middle_r_loss_is_invalid_not_a_pending_prefix(self):
        api, plan = self.plan((self.first,)); prior=self.baseline+self.first
        with self.assertRaises(AssertionError): api.validate_observation(plan,self.observation(prior+'-AFTE-CANCEL-'),prior)

    def test_reordered_duplicated_extra_text_or_changed_baseline_fail_immediately(self):
        api, plan = self.plan(); expected=self.baseline+self.first
        for body in (self.baseline+self.first[::-1],expected+self.first,expected+'x','changed\n'+self.first):
            with self.subTest(body=body),self.assertRaises(AssertionError):api.validate_observation(plan,self.observation(body),self.baseline)

    def test_pending_prefix_must_never_regress(self):
        api,plan=self.plan()
        with self.assertRaises(AssertionError):api.validate_observation(plan,self.observation(self.baseline+'-L'),self.baseline+'-LIFE')

    def test_reader_must_return_before_same_absolute_deadline_even_when_body_exact(self):
        api,plan=self.plan();record={}
        with self.assertRaises(AssertionError):self.run_read(api,plan,[self.baseline+self.first],duration=12.01,record=record)
        self.assertFalse(record['success'])

    def test_time_spent_before_completion_does_not_create_a_fresh_budget(self):
        api,plan=self.plan();self.clock.now=11.95;record={}
        with self.assertRaises(AssertionError):self.run_read(api,plan,[self.baseline],duration=0.04,record=record)
        self.assertEqual(record['deadline'],12.0);self.assertLessEqual(self.clock.now,12.01)

    def test_unadvancing_clock_cannot_cause_unbounded_pending_reads(self):
        api,plan=self.plan();reader=ReadOnlySequence([self.observation(self.baseline)],self.clock,duration=0)
        with self.assertRaises(AssertionError):api.await_completion(plan,reader,clock=self.clock,pause=lambda seconds:None,record={},max_reads=120)
        self.assertLessEqual(len(reader.deadlines),120)

    def test_getter_exception_timeout_and_cleanup_error_never_become_pending(self):
        api,plan=self.plan()
        for error in (OSError('getter failed'),TimeoutError('reader budget exhausted')):
            record={}
            with self.subTest(error=error),self.assertRaises(type(error)):self.run_read(api,plan,[error],record=record)
            self.assertFalse(record['success']);self.assertIn(str(error),record['error'])
        invalid=self.observation(self.baseline+self.first);invalid['readCallCleanupSucceeded']=False
        with self.assertRaises(AssertionError):api.validate_observation(plan,invalid,self.baseline)

    def test_wrong_or_recycled_process_and_changed_owned_frame_bindings_fail(self):
        api,plan=self.plan()
        for key,value in [('officePid',89),('officeCreationTime',223),('shellCreationTime',112),
            ('expectedImage','C:/foreign/soffice.bin'),('childHwnd',23),('rootHwnd',99),
            ('privatePipe','OpenGeul_'+'b'*32),('frameIdentity',self.binding['frameIdentity']+'0'),
            ('controllerIdentity',self.binding['controllerIdentity']+'0'),
            ('modelIdentity',self.binding['modelIdentity']+'0'),('documentUrl','file:///C:/foreign.docx')]:
            changed=copy.deepcopy(self.binding);changed[key]=value
            with self.subTest(key=key),self.assertRaises(AssertionError):api.validate_observation(plan,self.observation(self.baseline+self.first,binding=changed),self.baseline)

    def test_native_generation_change_after_getter_is_rejected(self):
        api,plan=self.plan();observation=self.observation(self.baseline+self.first)
        observation['bindingAfter']['officeCreationTime']+=1
        with self.assertRaises(AssertionError):api.validate_observation(plan,observation,self.baseline)

    def test_dead_or_unretained_process_and_ambiguous_model_are_rejected(self):
        api,plan=self.plan()
        for key,value in [('retainedProcessHandle',False),('handleSignaled',True),('sameFrameControllerModelVerified',False)]:
            observation=self.observation(self.baseline+self.first);observation[key]=value
            with self.subTest(key=key),self.assertRaises(AssertionError):api.validate_observation(plan,observation,self.baseline)

    def test_foreign_packaged_python_process_image_and_missing_identity_roles_fail(self):
        api,plan=self.plan()
        observation=self.observation(self.baseline+self.first)
        observation['pythonIdentity']['observed']['processImage']='C:/foreign/python.exe'
        with self.assertRaises(AssertionError):api.validate_observation(plan,observation,self.baseline)
        observation=self.observation(self.baseline+self.first);observation['pythonIdentity']['files'].pop('pyuno')
        with self.assertRaises(AssertionError):api.validate_observation(plan,observation,self.baseline)

    def test_stale_or_tampered_inventory_receipt_cannot_trust_verified_flag(self):
        api,plan=self.plan();observation=self.observation(self.baseline+self.first)
        observation['pythonIdentity']['files']['pyuno']['sha256']='f'*64
        with self.assertRaises(AssertionError):api.validate_observation(plan,observation,self.baseline)

    def test_other_owned_document_cannot_satisfy_this_frames_completion(self):
        api,plan=self.plan();other=copy.deepcopy(self.binding)
        other.update(childHwnd=24,**{key:other[key]+'0' for key in ('frameIdentity','controllerIdentity','modelIdentity')})
        with self.assertRaises(AssertionError):api.validate_observation(plan,self.observation(self.baseline+self.first,binding=other),self.baseline)

    def test_unsaved_empty_model_still_requires_exact_owned_frame(self):
        api=self.api();binding=copy.deepcopy(self.binding);binding['documentUrl']=''
        plan=api.freeze_expectation(binding,'',(),self.first,self.observation('',binding=binding),suite_root=self.suite,original_shell=original_shell_fixture(binding,self.suite),inventory=self.inventory,inventory_sha256=self.inventory_sha256,started_at=0.0,timeout_seconds=12.0)
        self.assertEqual(api.validate_observation(plan,self.observation(self.first,binding=binding),''),'complete')
        foreign=copy.deepcopy(binding);foreign['frameIdentity']+='0'
        with self.assertRaises(AssertionError):api.validate_observation(plan,self.observation(self.first,binding=foreign),'')

    def test_before_input_body_and_identity_must_match_frozen_expected_prior_state(self):
        api=self.api()
        with self.assertRaises(AssertionError):api.freeze_expectation(self.binding,self.baseline,(),self.first,self.observation('changed baseline'),suite_root=self.suite,original_shell=original_shell_fixture(self.binding,self.suite),inventory=self.inventory,inventory_sha256=self.inventory_sha256,started_at=0.0,timeout_seconds=12.0)

    def test_invalid_or_unbounded_budget_is_rejected_before_any_reader_call(self):
        api=self.api()
        for budget in (0,-1,float('inf'),float('nan'),True):
            with self.subTest(budget=budget),self.assertRaises(AssertionError):api.freeze_expectation(self.binding,self.baseline,(),self.first,self.observation(self.baseline),suite_root=self.suite,original_shell=original_shell_fixture(self.binding,self.suite),inventory=self.inventory,inventory_sha256=self.inventory_sha256,started_at=0.0,timeout_seconds=budget)

    def test_invalid_body_clock_and_readonly_state_are_errors_not_pending(self):
        api,plan=self.plan()
        for key,value in [('bodyText',None),('bodyText',1),('readFinishedAt','later'),('readOnlyObservation',False)]:
            observation=self.observation(self.baseline+self.first);observation[key]=value
            with self.subTest(key=key,value=value),self.assertRaises(AssertionError):api.validate_observation(plan,observation,self.baseline)

    def test_readonly_completion_preserves_the_owned_fixture_bytes(self):
        api,plan=self.plan();source=self.suite/'owned.docx';before=source.read_bytes()
        self.run_read(api,plan,[self.baseline,self.baseline+self.first])
        self.assertEqual(source.read_bytes(),before)

    def test_model_read_mutation_or_document_lifecycle_operations_are_rejected(self):
        api,plan=self.plan()
        for operation in ('loadComponentFromURL','store','dispatch','setString','insertText','setSelection','activate','close'):
            observation=self.observation(self.baseline+self.first);observation['operations'].append(operation)
            with self.subTest(operation=operation),self.assertRaises(AssertionError):api.validate_observation(plan,observation,self.baseline)

    def test_failed_completion_cannot_be_rescued_by_later_read_or_reopen(self):
        api,plan=self.plan();record={}
        with self.assertRaises(AssertionError):self.run_read(api,plan,['changed baseline'],record=record)
        original_error=record['error'];reader=ReadOnlySequence([self.observation(self.baseline+self.first)],self.clock)
        with self.assertRaises(AssertionError):api.await_completion(plan,reader,clock=self.clock,pause=self.clock.pause,record=record,max_reads=120)
        self.assertFalse(record['success']);self.assertEqual(record['error'],original_error)
        self.assertEqual(reader.deadlines,[])

    def completed_model(self):
        api,plan=self.plan()
        _,_,record=self.run_read(api,plan,[self.baseline+self.first])
        cleanup=reader_fixtures.cleanup_fixture(plan.binding,str(self.suite))
        cleanup.update(startedAt=self.clock.now,finishedAt=self.clock.now+.01,deadline=plan.deadline)
        retime_native_cleanup_fixture(cleanup)
        self.clock.pause(.01)
        return api,plan,record,cleanup

    def test_cleanup_cannot_certify_another_reader_generation_handle_or_job(self):
        for field,value in [('pid',100),('creationTime',444),('handleValue',999),('jobHandleValue',888)]:
            with self.subTest(field=field):
                self.clock=FakeClock();api,plan,record,cleanup=self.completed_model()
                member=cleanup['readerMembers'][0];old=member[field];member[field]=value
                if field=='pid':cleanup['releaseAcknowledgement']['readerPid']=value
                if field=='handleValue':
                    for row in cleanup['handleClosures']:
                        if row['kind']=='member' and row['handleValue']==old:row['handleValue']=value
                if field=='jobHandleValue':
                    cleanup['jobHandleValue']=value
                    for row in cleanup['handleClosures']:
                        if row['kind']=='job':row['handleValue']=value
                with self.assertRaises(AssertionError):api.finalize_completion(plan,record,cleanup,self.clock.now)

    def test_cleanup_cannot_precede_model_equality_or_finish_after_its_receipt(self):
        for begin,end,receipt_end in [(0,0,.02),(.01,.02,.015)]:
            with self.subTest(begin=begin,end=end):
                self.clock=FakeClock();api,plan,record,cleanup=self.completed_model()
                cleanup.update(startedAt=begin,finishedAt=end)
                with self.assertRaises(AssertionError):api.finalize_completion(plan,record,cleanup,receipt_end)

    def test_frozen_controller_or_helper_handle_and_reader_identity_cannot_be_replaced_between_reads(self):
        api,plan=self.plan()
        for origin in ('controller','helper'):
            observation=self.observation(self.baseline+self.first)
            for suffix in ('Before','After'):observation['nativeSnapshots'][origin+suffix]['office']['handleValue']+=1000
            with self.subTest(origin=origin),self.assertRaises(AssertionError):api.validate_observation(plan,observation,self.baseline)
        observation=self.observation(self.baseline+self.first);observation['readerProcess']['creationTime']+=1
        with self.assertRaises(AssertionError):api.validate_observation(plan,observation,self.baseline)

    def test_cleanup_must_close_the_frozen_controller_handles(self):
        api,plan,record,cleanup=self.completed_model()
        original=cleanup['nativeBefore']['office']['handleValue']
        for key in ('nativeBefore','nativeAfter'):cleanup[key]['office']['handleValue']+=1000
        for row in cleanup['handleClosures']:
            if row['kind']=='office' and row['handleValue']==original:row['handleValue']+=1000
        with self.assertRaises(AssertionError):api.finalize_completion(plan,record,cleanup,self.clock.now)

    def case_data(self,*,windows=False,case_name='dirty-writer-cancel-save'):
        frame=SimpleNamespace(suite=self.suite,baseline=self.baseline,binding=copy.deepcopy(self.binding),
            identity=copy.deepcopy(self.identity),inventory=self.inventory,inventory_sha256=self.inventory_sha256)
        if windows:
            target='C:/actions/한글 Suite'
            def rewrite(value):
                if isinstance(value,dict):return {key:rewrite(item) for key,item in value.items()}
                if isinstance(value,list):return [rewrite(item) for item in value]
                if isinstance(value,str):return value.replace(str(self.suite),target)
                return value
            frame.identity=rewrite(frame.identity);frame.binding=rewrite(frame.binding);frame.suite=target
            frame.binding['documentUrl']=PureWindowsPath(target+'/owned.docx').as_uri()
        if case_name=='home-two-documents-cancel':
            frame.baseline='';frame.binding['documentUrl']=''
        api,record=case_fixture(frame,case_name)
        urls={(11,22):frame.binding['documentUrl']}
        return api,frame,record,urls

    def replay_case(self,api,frame,record,urls):
        return api.replay_case_completions(record,suite_root=frame.suite,inventory=frame.inventory,
            inventory_sha256=frame.inventory_sha256,baseline_body=frame.baseline,expected_urls=urls)

    def test_raw_windows_whole_case_replay_requires_no_filesystem_or_windows_api(self):
        api,frame,record,urls=self.case_data(windows=True)
        with patch.object(Path,'resolve',side_effect=AssertionError('Portable replay may not resolve paths')), \
             patch.object(Path,'read_bytes',side_effect=AssertionError('Portable replay may not read files')):
            replayed=self.replay_case(api,frame,record,urls)
        self.assertEqual(replayed['editCount'],2)
        self.assertEqual(replayed['frameGenerations'][0]['officeCommandLine'],record['writerModelCompletions'][0]['expectation']['beforeInput']['nativeSnapshots']['controllerBefore']['officeCommandLine'])
        self.assertFalse(replayed['originalPhysicalAsciiLossCauseEstablished'])

    def test_whole_case_rejects_missing_reordered_or_foreign_attachment_receipts(self):
        api,frame,record,urls=self.case_data()
        for change in ('missing','reordered','foreign'):
            bad=copy.deepcopy(record)
            if change=='missing':bad['writerModelCompletions'].pop()
            elif change=='reordered':bad['writerModelCompletions'].reverse()
            else:bad['attachments'][0]['child']=999
            with self.subTest(change=change),self.assertRaises(AssertionError):self.replay_case(api,frame,bad,urls)

    def test_whole_case_independent_body_url_and_edited_frame_set_are_required(self):
        api,frame,record,urls=self.case_data()
        with self.assertRaises(AssertionError):self.replay_case(api,frame,record,{(11,22):'file:///foreign.docx'})
        with self.assertRaises(AssertionError):self.replay_case(api,frame,record,{**urls,(55,66):''})
        frame.baseline='changed baseline'
        with self.assertRaises(AssertionError):self.replay_case(api,frame,record,urls)

    def test_home_blank_frame_uses_empty_url_and_separate_exact_attachment(self):
        api,frame,record,urls=self.case_data(case_name='home-two-documents-cancel')
        record['attachments'].insert(0,dict(hwnd=55,parent=56,child=66,officePid=89))
        self.assertEqual(self.replay_case(api,frame,record,urls)['editCount'],2)
        with self.assertRaises(AssertionError):self.replay_case(api,frame,record,{(55,66):''})

    def test_replay_rejects_cleanup_from_another_observer_and_late_or_reordered_time(self):
        api,frame,record,urls=self.case_data()
        for change in ('cleanup','time','overlap'):
            bad=copy.deepcopy(record);receipt=bad['writerModelCompletions'][-1]
            if change=='cleanup':receipt['cleanup']['releaseAcknowledgement']['readerPid']=100
            elif change=='time':receipt['observations'][-1]['finishedAt']=receipt['deadline']+1
            else:
                def earlier(value):
                    if isinstance(value,dict):return {key:(item-.64 if key in {'startedAt','finishedAt','deadline','readStartedAt','readFinishedAt','modelEqualityAt'} else earlier(item)) for key,item in value.items()}
                    if isinstance(value,list):return [earlier(item) for item in value]
                    return value
                bad['writerModelCompletions'][-1]=earlier(receipt)
            with self.subTest(change=change),self.assertRaises(AssertionError):self.replay_case(api,frame,bad,urls)

    def test_original_shell_generation_must_match_before_input_reader_binding(self):
        api=self.api();original=original_shell_fixture(self.binding,self.suite)
        original['nativeCreation'].update(low=112,fileTime=112)
        with self.assertRaises(AssertionError):api.freeze_expectation(self.binding,self.baseline,(),self.first,
            self.observation(self.baseline),suite_root=self.suite,original_shell=original,
            inventory=self.inventory,inventory_sha256=self.inventory_sha256,started_at=0)

    def test_actual_launch_receipt_is_frozen_across_reads_and_final_cleanup(self):
        api,plan=self.plan();observation=self.observation(self.baseline+self.first)
        observation['helperLaunch']['steps'][1]['command']+=' changed-command'
        with self.subTest(stage='read'),self.assertRaises(AssertionError):api.validate_observation(plan,observation,self.baseline)
        api,plan,record,cleanup=self.completed_model()
        cleanup['helperLaunch']['steps'][1]['command']+=' changed-command'
        with self.subTest(stage='cleanup'),self.assertRaises(AssertionError):api.finalize_completion(plan,record,cleanup,self.clock.now)

    def test_valid_but_replaced_console_host_witness_fails_on_every_read(self):
        import writer_model_reader
        for field in ('osPath','fileId','sha256','retainedFileHandle','fileGeneration'):
            for read_index in (0,1):
                with self.subTest(field=field,read_index=read_index):
                    self.clock=FakeClock();api,plan=self.plan();record={}
                    observations=[self.observation(self.baseline+'-LIFE'),self.observation(self.baseline+self.first)]
                    replacement=observations[read_index];replace_console_host_identity(replacement,field)
                    # Each replacement is valid by itself. Only its continuity
                    # with the frozen pre-input OS witness must reject it.
                    writer_model_reader.require_owned_observation(replacement,self.binding,str(self.suite))
                    with self.assertRaisesRegex(AssertionError,'Frozen system console host witness changed'):
                        self.run_read(api,plan,observations,record=record)
                    self.assertFalse(record['success']);self.assertEqual(record['state'],'failed')
                    self.assertEqual(len(record['observations']),read_index+1)
                    self.assertEqual(record['deadline'],12.0)

    def test_valid_but_replaced_console_host_witness_cannot_certify_cleanup(self):
        import writer_model_reader
        for field in ('osPath','fileId','sha256','retainedFileHandle','fileGeneration'):
            with self.subTest(field=field):
                self.clock=FakeClock();api,plan,record,cleanup=self.completed_model()
                replace_console_host_identity(cleanup,field)
                writer_model_reader.require_reader_cleanup(cleanup,self.binding,plan.deadline)
                with self.assertRaisesRegex(AssertionError,'Cleanup changed the frozen system console host witness'):
                    api.finalize_completion(plan,record,cleanup,self.clock.now)
                self.assertFalse(record['success']);self.assertEqual(record['state'],'failed')

    def test_retained_proxy_context_and_type_cannot_change_between_reads(self):
        import writer_model_reader
        for field in ('localContextId','proxyTypeId'):
            with self.subTest(field=field):
                api,plan=self.plan();observation=self.observation(self.baseline+self.first)
                for suffix in ('before','after'):observation['unoSnapshots'][suffix]['proxyIdentity'][field]+=1
                writer_model_reader.require_owned_observation(observation,self.binding,str(self.suite))
                with self.assertRaisesRegex(AssertionError,'Frozen retained PyUNO proxy context or type changed'):
                    api.validate_observation(plan,observation,self.baseline)

    def test_valid_profile_directory_replacements_fail_on_every_read(self):
        import writer_model_reader
        for field,origin in (('canonicalPath',None),('fileId',None),('handle','controller'),('handle','helper')):
            for read_index in (0,1):
                with self.subTest(field=field,origin=origin,read_index=read_index):
                    self.clock=FakeClock();api,plan=self.plan();record={}
                    observations=[self.observation(self.baseline+'-LIFE'),self.observation(self.baseline+self.first)]
                    changed=observations[read_index];replace_profile_directory_identity(changed,field,origin)
                    writer_model_reader.require_owned_observation(changed,self.binding,str(self.suite))
                    with self.assertRaisesRegex(AssertionError,'Frozen native profile directory witness changed'):
                        self.run_read(api,plan,observations,record=record)
                    self.assertFalse(record['success']);self.assertEqual(len(record['observations']),read_index+1)
                    self.assertEqual(record['deadline'],12.0)

    def test_valid_profile_directory_replacements_cannot_certify_cleanup(self):
        import writer_model_reader
        for field,origin in (('canonicalPath',None),('fileId',None),('handle','controller'),('handle','helper')):
            with self.subTest(field=field,origin=origin):
                self.clock=FakeClock();api,plan,record,cleanup=self.completed_model()
                replace_profile_directory_identity(cleanup,field,origin)
                writer_model_reader.require_reader_cleanup(cleanup,self.binding,plan.deadline)
                with self.assertRaisesRegex(AssertionError,'Cleanup changed the frozen .* profile directory witness'):
                    api.finalize_completion(plan,record,cleanup,self.clock.now)
                self.assertFalse(record['success']);self.assertEqual(record['state'],'failed')

    def test_cleanup_rejects_otherwise_valid_helper_process_handle_closures(self):
        import writer_model_reader
        for kind in ('shell','office'):
            with self.subTest(kind=kind):
                self.clock=FakeClock();api,plan,record,cleanup=self.completed_model()
                frozen=json.loads(plan.before_input_json)
                closure=next(row for row in cleanup['releaseAcknowledgement']['observerHandleClosures'] if row['kind']==kind)
                # The controller holds a valid HANDLE for the same process, but
                # it cannot certify closure of the helper's retained HANDLE.
                closure['handleValue']=frozen['nativeSnapshots']['controllerBefore'][kind]['handleValue']
                writer_model_reader.require_reader_cleanup(cleanup,self.binding,plan.deadline)
                with self.assertRaisesRegex(AssertionError,'Cleanup closed different retained helper handles'):
                    api.finalize_completion(plan,record,cleanup,self.clock.now)
                self.assertFalse(record['success']);self.assertEqual(record['state'],'failed')

    def test_whole_case_exports_native_canonical_profile_without_changing_original_short_uri(self):
        api,frame,record,urls=self.case_data(windows=True)
        short='file:///C:/Users/RUNNER~1/Temp/OpenGeul-office-owned'
        canonical='C:/Users/runneradmin/Temp/OpenGeul-office-owned'
        def native_alias(value):
            if isinstance(value,dict):
                if 'profileDirectory' in value:
                    handle=value['profileDirectory']['witness']['handleValue']
                    value['profileDirectory']=reader_fixtures.profile_directory_fixture(short,handle,canonical)
                if 'officeCommandLine' in value:
                    value['officeCommandLine']=[('-env:UserInstallation='+short if part.startswith('-env:UserInstallation=') else part) for part in value['officeCommandLine']]
                    value['profileUrl']=short
                for item in value.values():native_alias(item)
            elif isinstance(value,list):
                for item in value:native_alias(item)
        native_alias(record);before=copy.deepcopy(record)
        with patch.object(Path,'resolve',side_effect=AssertionError('Profile replay may not resolve paths')), \
             patch.object(Path,'read_bytes',side_effect=AssertionError('Profile replay may not read files')):
            replayed=self.replay_case(api,frame,record,urls)
        generation=replayed['frameGenerations'][0]
        self.assertEqual(generation.get('canonicalProfile'),dict(profileUrl=short,
            canonicalPath=str(PureWindowsPath(canonical)).casefold(),volumeSerialNumber=104,fileIndexHigh=0,fileIndexLow=105))
        self.assertEqual(generation['profileUrl'],short);self.assertEqual(record,before)

    def test_whole_case_rejects_an_individually_valid_changed_profile_directory_between_edits(self):
        for field in ('canonicalPath','fileId'):
            with self.subTest(field=field):
                api,frame,record,urls=self.case_data(windows=True);receipt=record['writerModelCompletions'][-1]
                replace_profile_directory_identity(receipt['expectation']['beforeInput'],field)
                for row in receipt['observations']:replace_profile_directory_identity(row['observation'],field)
                replace_profile_directory_identity(receipt['cleanup'],field)
                api.replay_completion(receipt,suite_root=frame.suite,inventory=frame.inventory,
                    inventory_sha256=frame.inventory_sha256,binding=frame.binding,baseline_body=frame.baseline,
                    completed_markers=(self.first,),next_marker=self.second)
                with self.assertRaisesRegex(AssertionError,'Canonical profile directory changed between edits'):
                    self.replay_case(api,frame,record,urls)

    def test_whole_case_allows_fresh_directory_handles_for_the_same_native_profile(self):
        api,frame,record,urls=self.case_data(windows=True);receipt=record['writerModelCompletions'][-1]
        for origin in ('controller','helper'):
            replace_profile_directory_identity(receipt['expectation']['beforeInput'],'handle',origin)
            for row in receipt['observations']:replace_profile_directory_identity(row['observation'],'handle',origin)
            replace_profile_directory_identity(receipt['cleanup'],'handle',origin)
        self.assertEqual(self.replay_case(api,frame,record,urls)['editCount'],2)


if __name__=='__main__':unittest.main()
