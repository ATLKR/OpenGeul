"""Real retirement policy with inert native doubles and real bounded archive files."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import copy
import ctypes as C
import importlib.util
import hashlib
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'e2e'))
try:
    import ime_engine_retirement as retirement
except ModuleNotFoundError:
    retirement = None

SHA = 'a' * 40
RUN = dict(sourceCommit=SHA, sourceRun='123456', runAttempt='1', job='windows-suite',
           repository='ATLKR/OpenGeul', architecture='x64')
ENV = dict(GITHUB_ACTIONS='true', RUNNER_OS='Windows', GITHUB_SHA=SHA,
           GITHUB_RUN_ID='123456', GITHUB_RUN_ATTEMPT='1', GITHUB_JOB='windows-suite',
           GITHUB_REPOSITORY='ATLKR/OpenGeul')


class Clock:
    def __init__(self): self.now = 10.0
    def __call__(self): return self.now


def raw_times(creation):
    return {name:dict(low=value&0xffffffff,high=value>>32) for name,value in
            (('creation',creation),('exit',0),('kernel',1),('user',2))}


class Provider:
    def __init__(self, fixture):
        self.f = fixture; self.actions = []; self.wait = 0; self.exit = 0; self.closed = True
        self.creation = fixture.engine['creationTime']; self.pid = fixture.engine['pid']
    def open(self, pid): self.actions.append('open'); return dict(handleValue=222, access=0x101000, inherit=False, pid=pid)
    def live(self, handle):
        self.actions.append('live')
        return dict(self.f.engine, handleValue=handle, pid=self.pid, creationTime=self.creation,
                    processTimes=raw_times(self.creation))
    def wait_zero(self, handle):
        self.actions.append('post-close-wait')
        return dict(api='WaitForSingleObject', handleValue=handle, timeoutMilliseconds=0, result=self.wait, lastError=0)
    def exited(self, handle):
        self.actions.append('exited')
        return dict(pid=self.pid, handleValue=handle, creationTime=self.creation,
                    processTimes=raw_times(self.creation),
                    getProcessIdResult=self.pid, getProcessTimesResult=True,
                    getExitCodeProcessResult=True, exitCode=self.exit, lastError=0)
    def close(self, handle):
        self.actions.append('close')
        return dict(api='CloseHandle', handleValue=handle, result=self.closed, lastError=0)


class Fixture:
    def __init__(self, folder):
        self.folder=Path(folder).resolve(); self.suite=self.folder/'suite';self.suite.mkdir()
        self.root=self.folder/'diagnostics';self.root.mkdir()
        self.clock=Clock();self.source=copy.deepcopy(RUN)
        self.provenance=dict(schemaVersion=1, productName='OpenGeul Office', sourceCommit=SHA,
            architecture='x64', sourceArchiveSha256='b'*64)
        (self.suite/'suite-provenance.json').write_text(json.dumps(self.provenance))
        self.engine=dict(pid=20,handleValue=1112,creationTime=134366967797539307,
                         image=str(self.suite/'Office/program/soffice.bin'),waitResult=258)
        self.shell=dict(pid=101,handleValue=111,creationTime=134366967797539297,
                        image=str(self.suite/'OpenGeul.Office.exe'),waitResult=258)
        self.binding=dict(shellPid=101,officePid=20,suiteHwnd=40,parentHwnd=41,childHwnd=42,rootHwnd=40,
            shellCreationTime=self.shell['creationTime'],officeCreationTime=self.engine['creationTime'],expectedImage=self.engine['image'])
        self.record=dict(module='writer',architecture='x64',windowHwnd=40,parentHwnd=41,childHwnd=42,
                         officePid=20,editorTid=303,keyboardFocusHwnd=43,readiness={'source':self.source})
        self.process=SimpleNamespace(pid=101,_handle=111,args=[self.shell['image']],returncode=None,
                                     opengeul_suite_root=self.suite,opengeul_evidence_case='ime-writer')
        receipt=dict(originalEngine=self.engine,originalShell=self.shell,expectedNative=self.binding,
                     setupDeadline=70.0,engineHandleReleased=False)
        self.record['imeKeyboardSession']=receipt
        info=dict(fileAttributes=16,creationTime=101,lastAccessTime=102,lastWriteTime=103,volumeSerialNumber=104,
            size=4096,numberOfLinks=1,fileIndexHigh=0,fileIndexLow=105,fileType=1,finalPath='\\\\?\\C:\\private-profile')
        witness=dict(schemaVersion=1,kind='native-owned-profile-directory',profileUrl='file:///C:/private-profile',
            decodedPath='C:\\private-profile',canonicalPath='C:\\private-profile',handleValue=601,
            desiredAccess=128,shareMode=7,openFlags=0x02000000,openedInfo=info)
        raw=dict(profileDirectory=dict(witness=witness,recheck=copy.deepcopy(info)),profileUrl=witness['profileUrl'])
        from writer_model_reader import canonical_profile_projection
        self.original_profile=canonical_profile_projection(witness,witness['profileUrl'])
        self.record['imeSemanticContext']=dict(kind='ime-semantic-editing-context',phase='post',module='writer',success=True,
            expectedNative=copy.deepcopy(self.binding),setupDeadline=70.,readerDeadline=12.,finishedAt=9.,
            observation=dict(bindingBefore=copy.deepcopy(self.binding),nativeSnapshots={'controllerBefore':raw}))
        self.record['imeSetupBudget']=dict(deadline=70.)
        self.keyboard=SimpleNamespace(process=self.process,record=self.record,receipt=receipt,binding=self.binding,
            shell=self.shell,engine=self.engine,handle=1112,tid=303,focus=43,phase='composition',setup_deadline=70.0)
        self.keyboard.require_target=lambda: dict(shell=copy.deepcopy(self.shell),engine=copy.deepcopy(self.engine))
        self.provider=Provider(self)
        self.environment=dict(ENV,OPENGEUL_SUITE_DIAGNOSTICS=str(self.root))
    def admit(self):
        return retirement.admit_ime_retirement(keyboard=self.keyboard,original_shell=self.process,
            suite=self.suite,case_name='ime-writer',record=self.record,setup_deadline=70.0,
            run_binding=self.source,diagnostics_root=self.root,original_profile=self.original_profile,clock=self.clock,provider=self.provider)
    def archive(self, name='1'*32):
        folder=self.root/name;folder.mkdir()
        proof=json.loads((Path(__file__).parent/'fixtures/owned-office-shutdown.json').read_bytes())['graceful']
        proof['expectedEngineImage']=self.engine['image']
        for group in ('initialMembers','finalMembers'):
            for member in proof[group]:
                member['image']=str(self.suite/'Office/program'/Path(member['image']).name)
        raw=(json.dumps(proof,ensure_ascii=False)+'\n').encode();(folder/'shutdown.json').write_bytes(raw)
        manifest=dict(schemaVersion=1,kind='owned-office-native-diagnostics',archiveComplete=True,
            launcherPid=proof['launcherPid'],workerPid=555,ownedProfile=str(self.folder/'private-profile'),
            files=[dict(path='shutdown.json',bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())])
        (folder/'manifest.json').write_text(json.dumps(manifest));return folder,manifest,proof
    def verify(self, lease):
        self.process.returncode=0;self.clock.now=80
        return lease.verify_after_close_home(close_returned_at=80.0)
    def require(self, proof):
        return retirement.require_ime_engine_retirement(proof,expected_native=self.binding,
            expected_run=self.source,expected_case='ime-writer',expected_source=SHA,expected_original_profile=self.original_profile)


class RetirementTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(retirement,'The separate owned retirement mechanism is missing')
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.f=Fixture(self.tmp.name)
        self.environment=patch.dict(os.environ,self.f.environment,clear=True);self.environment.start();self.addCleanup(self.environment.stop)
    def test_real_archive_zero_exit_and_release_form_a_complete_replayable_proof(self):
        self.f.archive();lease=self.f.admit();proof=self.f.verify(lease)
        self.assertIs(proof,self.f.record['imeEngineRetirement']);self.assertIs(self.f.require(proof),proof)
        self.assertEqual(self.f.provider.actions,['open','live','post-close-wait','exited','close'])
    def test_admission_is_replayable_before_profile_mutation_without_claiming_retirement(self):
        lease=self.f.admit();r=self.f.record['imeEngineRetirement']
        retirement.require_ime_retirement_admission(r,expected_native=self.f.binding,expected_run=RUN,
            expected_case='ime-writer',expected_source=SHA,expected_original_profile=self.f.original_profile)
        self.assertFalse(r['success']);lease.close();self.assertEqual(self.f.provider.actions.count('close'),1)
    def test_source_and_run_cannot_be_supplied_by_a_receipt_or_wrong_environment(self):
        for key in ('GITHUB_SHA','GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT','GITHUB_JOB','GITHUB_REPOSITORY'):
            with self.subTest(key=key),patch.dict(os.environ,{key:'wrong'}):
                with self.assertRaises((AssertionError,ValueError)):self.f.admit()
            self.f.record.pop('imeEngineRetirement',None)
    def test_package_source_and_architecture_must_join_readiness(self):
        self.f.provenance['sourceCommit']='c'*40
        (self.f.suite/'suite-provenance.json').write_text(json.dumps(self.f.provenance))
        with self.assertRaises((AssertionError,ValueError)):self.f.admit()
        self.assertNotIn('open',self.f.provider.actions)
    def test_diagnostic_root_cannot_be_replaced_by_an_output_guessed_path(self):
        os.environ['OPENGEUL_SUITE_DIAGNOSTICS']=str(self.f.folder/'elsewhere')
        with self.assertRaises((AssertionError,ValueError,OSError)):self.f.admit()
    def test_same_live_generation_is_mandatory_and_failed_admission_releases(self):
        self.f.provider.creation+=1
        with self.assertRaises((AssertionError,ValueError)):self.f.admit()
        self.assertEqual(self.f.provider.actions.count('close'),1)
    def test_original_keyboard_handle_and_original_popen_must_still_be_live(self):
        self.f.keyboard.receipt['engineHandleReleased']=True
        with self.assertRaises((AssertionError,ValueError)):self.f.admit()
        self.assertNotIn('open',self.f.provider.actions)
    def test_expired_setup_has_no_new_handle_admission(self):
        self.f.clock.now=70
        with self.assertRaises((AssertionError,ValueError)):self.f.admit()
        self.assertNotIn('open',self.f.provider.actions)
    def test_first_wait258_is_fatal_before_any_archive_io_and_never_retried(self):
        lease=self.f.admit();self.f.provider.wait=258
        with patch.object(Path,'iterdir',side_effect=AssertionError('archive touched before zero wait')):
            with self.assertRaises((AssertionError,ValueError)):self.f.verify(lease)
        self.assertEqual(self.f.provider.actions[-2:],['post-close-wait','close'])
        lease.close();self.assertEqual(self.f.provider.actions.count('post-close-wait'),1)
    def test_failed_wait_and_nonzero_engine_exit_never_qualify(self):
        lease=self.f.admit();self.f.provider.exit=7
        with self.assertRaises((AssertionError,ValueError)):self.f.verify(lease)
        self.assertEqual(self.f.provider.actions.count('close'),1)
    def test_post_exit_generation_tamper_fails_without_reopening(self):
        lease=self.f.admit();self.f.provider.creation+=1
        with self.assertRaises((AssertionError,ValueError)):self.f.verify(lease)
        self.assertEqual(self.f.provider.actions.count('open'),1)
    def test_original_shell_must_have_returned_zero_from_existing_close(self):
        lease=self.f.admit();self.f.process.returncode=4;self.f.clock.now=80
        with self.assertRaises((AssertionError,ValueError)):lease.verify_after_close_home(close_returned_at=80)
        self.assertEqual(self.f.provider.actions.count('close'),1)
    def test_known_save_trace_sidecar_is_stat_only_and_not_archive_authority(self):
        self.f.archive();(self.f.root/('worker-save-123-'+'a'*32+'.jsonl')).write_text('not parsed')
        proof=self.f.verify(self.f.admit());self.f.require(proof)
    def test_foreign_sidecar_shape_is_not_silently_skipped(self):
        self.f.archive();(self.f.root/'other.jsonl').write_text('x')
        with self.assertRaises((AssertionError,ValueError)):self.f.verify(self.f.admit())
    def test_symlink_and_empty_save_trace_are_rejected(self):
        (self.f.root/('worker-save-123-'+'a'*32+'.jsonl')).touch()
        with self.assertRaises((AssertionError,ValueError)):self.f.verify(self.f.admit())
    def test_missing_irrelevant_shutdown_is_fatal_complete_selection_unknown(self):
        self.f.archive();bad=self.f.root/('2'*32);bad.mkdir();(bad/'manifest.json').write_text('{}')
        with self.assertRaises((AssertionError,ValueError,OSError)):self.f.verify(self.f.admit())
    def test_duplicate_matching_engine_generations_are_not_first_match_wins(self):
        self.f.archive();self.f.archive('2'*32)
        with self.assertRaises((AssertionError,ValueError)):self.f.verify(self.f.admit())
    def test_raw_manifest_and_shutdown_hash_and_native_ids_are_replayed(self):
        self.f.archive();proof=self.f.verify(self.f.admit())
        for mutate in (lambda p:p['exit'].update(pid=20.0),lambda p:p['archive']['manifest'].update(sha256='0'*64),
                       lambda p:p['admission']['native'].update(officePid=True)):
            changed=copy.deepcopy(proof);mutate(changed)
            with self.assertRaises((AssertionError,ValueError)):self.f.require(changed)
    def test_forced_job_cleanup_cannot_supply_selected_retirement(self):
        folder,manifest,proof=self.f.archive();proof['forcedTermination']=True
        raw=json.dumps(proof).encode();(folder/'shutdown.json').write_bytes(raw)
        manifest['files'][0].update(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest());(folder/'manifest.json').write_text(json.dumps(manifest))
        with self.assertRaises((AssertionError,ValueError)):self.f.verify(self.f.admit())
    def test_archive_member_bytes_are_checked_not_only_manifest_flags(self):
        folder,_,_=self.f.archive();(folder/'shutdown.json').write_text('{}')
        with self.assertRaises((AssertionError,ValueError)):self.f.verify(self.f.admit())
    def test_empty_selected_member_cannot_change_after_initial_stat_without_a_read(self):
        folder,_,_=self.f.archive();events=folder/'events.jsonl';events.touch()
        original=Path.stat;changed=False
        def stat_then_change(path,*args,**kwargs):
            nonlocal changed
            result=original(path,*args,**kwargs)
            if path==events and kwargs.get('follow_symlinks',True) and not changed:
                changed=True;events.write_bytes(b'changed')
            return result
        with patch.object(Path,'stat',stat_then_change):
            with self.assertRaises((AssertionError,ValueError)):self.f.verify(self.f.admit())
        self.assertTrue(changed)
    def test_close_failure_is_fatal_but_primary_exit_error_is_preserved(self):
        lease=self.f.admit();self.f.provider.wait=258;self.f.provider.closed=False
        with self.assertRaisesRegex((AssertionError,ValueError),'[Ww]ait|signaled'):self.f.verify(lease)
        self.assertEqual(self.f.provider.actions.count('close'),1)
    def test_close_and_positive_finish_consume_the_same_fifteen_second_budget(self):
        self.f.archive();lease=self.f.admit();close=self.f.provider.close
        def late(handle):self.f.clock.now=95;return close(handle)
        self.f.provider.close=late
        with self.assertRaises((AssertionError,ValueError)):self.f.verify(lease)
        self.assertFalse(self.f.record['imeEngineRetirement']['success'])
    def test_preexisting_keyboard_receipt_and_deadlines_remain_unchanged(self):
        self.f.archive();before=copy.deepcopy(self.f.keyboard.receipt);lease=self.f.admit();self.f.verify(lease)
        self.assertEqual(before,self.f.keyboard.receipt);self.assertEqual(self.f.keyboard.setup_deadline,70)

    def test_final_pure_replay_cannot_overrun_fifteen_seconds_then_return_success(self):
        self.f.archive();lease=self.f.admit();original=retirement.require_ime_engine_retirement
        def late(*args,**kwargs):
            result=original(*args,**kwargs);self.f.clock.now=95;return result
        with patch.object(retirement,'require_ime_engine_retirement',side_effect=late):
            with self.assertRaises((AssertionError,ValueError)):self.f.verify(lease)
        self.assertFalse(self.f.record['imeEngineRetirement']['success'])
    def test_new_open_and_projection_fields_reject_float_or_bool_native_ids(self):
        self.f.archive();proof=self.f.verify(self.f.admit())
        for mutate in (lambda p:p['admission']['open'].update(pid=20.0),
                       lambda p:p['admission']['open'].update(access=float(0x101000)),
                       lambda p:p['admission']['open'].update(inherit=0),
                       lambda p:p['scan']['candidates'][0]['engine'].update(pid=20.0),
                       lambda p:p['proofPhase']['wait'].update(lastError=False),
                       lambda p:p['exit'].update(lastError=0.0),
                       lambda p:p['close'].update(lastError=0.0)):
            with self.subTest(mutate=mutate):
                changed=copy.deepcopy(proof);mutate(changed)
                with self.assertRaises((AssertionError,ValueError)):self.f.require(changed)
    def test_all_archive_candidates_are_bounded_even_before_any_descriptor_read(self):
        for i in range(257):(self.f.root/f'{i:032x}').mkdir()
        with self.assertRaisesRegex((AssertionError,ValueError),'cap'):self.f.verify(self.f.admit())
    def test_known_sidecar_pid_size_and_count_are_strictly_bounded(self):
        p=self.f.root/('worker-save-123-'+'a'*32+'.jsonl')
        with p.open('wb') as f:f.truncate(1048577)
        with self.assertRaises((AssertionError,ValueError)):self.f.verify(self.f.admit())
    def test_sidecar_link_observation_is_fatal_without_windows_symlink_privilege(self):
        p=self.f.root/('worker-save-123-'+'a'*32+'.jsonl');p.write_text('x');original=Path.lstat
        def linked(path):
            st=original(path)
            if path==p:return SimpleNamespace(st_mode=0o120777,st_file_attributes=0)
            return st
        lease=self.f.admit()
        with patch.object(Path,'lstat',linked):
            with self.assertRaises((AssertionError,ValueError)):self.f.verify(lease)
    def test_selected_archive_content_cap_does_not_allow_giant_journal_read(self):
        folder,_,_=self.f.archive()
        with (folder/'events.jsonl').open('wb') as f:f.truncate(16777217)
        with self.assertRaisesRegex((AssertionError,ValueError),'byte cap'):self.f.verify(self.f.admit())
    def test_incomplete_nonmatching_manifest_is_not_skipped(self):
        folder,manifest,_=self.f.archive();manifest['archiveComplete']=False
        (folder/'manifest.json').write_text(json.dumps(manifest))
        with self.assertRaises((AssertionError,ValueError)):self.f.verify(self.f.admit())
    def test_post_close_wait_failure_and_out_of_range_native_codes_are_fatal(self):
        lease=self.f.admit();self.f.provider.wait=0xffffffff
        with self.assertRaises((AssertionError,ValueError)):self.f.verify(lease)
        self.assertEqual(self.f.provider.actions[-2:],['post-close-wait','close'])

    def test_native_provider_owns_fixed_width_structures_across_two_module_loads(self):
        class FileTime(C.Structure):_fields_=[('low',C.c_uint32),('high',C.c_uint32)]
        def dll():
            obj=SimpleNamespace(events=[]);obj.wait=258;obj.image=self.f.engine['image']
            H,D,B=C.c_void_p,C.c_uint32,C.c_int32
            def bind(name,result,args,callback):setattr(obj,name,C.CFUNCTYPE(result,*args)(callback))
            bind('OpenProcess',H,(D,B,D),lambda access,inherit,pid:222)
            bind('GetProcessId',D,(H,),lambda handle:20)
            def wait(handle,timeout):obj.events.append(('wait',handle,timeout));return obj.wait
            bind('WaitForSingleObject',D,(H,D),wait)
            def times(handle,*pointers):
                obj.events.append(('times',handle))
                for i,ptr in enumerate(pointers):
                    value=self.f.engine['creationTime'] if i==0 else 0
                    target=C.cast(ptr,C.POINTER(FileTime)).contents;target.low=value&0xffffffff;target.high=value>>32
                return 1
            bind('GetProcessTimes',B,(H,C.c_void_p,C.c_void_p,C.c_void_p,C.c_void_p),times)
            def image(handle,flags,ptr,length):
                obj.events.append(('image',handle));value=obj.image;buffer=C.create_unicode_buffer(value)
                C.memmove(ptr,buffer,C.sizeof(buffer));C.cast(length,C.POINTER(D)).contents.value=len(value);return 1
            bind('QueryFullProcessImageNameW',B,(H,D,C.c_void_p,C.c_void_p),image)
            def exit_code(handle,ptr):C.cast(ptr,C.POINTER(D)).contents.value=0;return 1
            bind('GetExitCodeProcess',B,(H,C.c_void_p),exit_code)
            bind('CloseHandle',B,(H,),lambda handle:1)
            return obj
        spec=importlib.util.spec_from_file_location('_retirement_duplicate_load',retirement.__file__)
        other=importlib.util.module_from_spec(spec);spec.loader.exec_module(other)
        one,two=dll(),dll();bridge=self.f.folder/'bridge';bridge.mkdir();one.image=str(bridge/'..'/'suite/Office/program/soffice.bin');a=retirement.NativeRetirementProvider(kernel=one,deadline=70,clock=self.f.clock);b=other.NativeRetirementProvider(kernel=two,deadline=70,clock=self.f.clock)
        self.assertIsNot(one.GetProcessTimes,two.GetProcessTimes)
        self.assertIsNot(one.GetProcessTimes.argtypes[1],two.GetProcessTimes.argtypes[1])
        for provider,kernel in ((a,one),(b,two)):
            live=provider.live(222);self.assertEqual(live['creationTime'],self.f.engine['creationTime']);self.assertEqual(live['image'],self.f.engine['image']);kernel.wait=0
            before=len([x for x in kernel.events if x[0]=='image'])
            self.assertEqual(provider.exited(222)['exitCode'],0)
            self.assertEqual(len([x for x in kernel.events if x[0]=='image']),before)
    def test_descriptor_aggregate_limit_prevents_multiplying_per_file_caps(self):
        for i in range(9):
            folder,manifest,proof=self.f.archive(f'{i:032x}')
            for group in ('initialMembers','finalMembers'):
                for member in proof[group]:
                    if member['pid']==20:member['pid']=20+i
            raw=json.dumps(proof).encode();(folder/'shutdown.json').write_bytes(raw)
            manifest['files'][0].update(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
            manifest['padding']='x'*(1048576-len(json.dumps(manifest))-20)
            (folder/'manifest.json').write_text(json.dumps(manifest))
        with self.assertRaisesRegex((AssertionError,ValueError),'cap'):self.f.verify(self.f.admit())
    def test_total_root_entries_and_sidecar_counts_are_independently_bounded(self):
        for i in range(257):(self.f.root/f'worker-save-{i+1}-{i:032x}.jsonl').write_text('x')
        with self.assertRaisesRegex((AssertionError,ValueError),'cap'):self.f.verify(self.f.admit())
    def test_complete_valid_other_generation_is_not_borrowed_or_global_counted(self):
        self.f.archive();folder,manifest,proof=self.f.archive('2'*32)
        for group in ('initialMembers','finalMembers'):
            for member in proof[group]:
                if member['pid']==20:member['pid']=21
        raw=json.dumps(proof).encode();(folder/'shutdown.json').write_bytes(raw)
        manifest['files'][0].update(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
        (folder/'manifest.json').write_text(json.dumps(manifest))
        proof=self.f.verify(self.f.admit());self.f.require(proof)
        self.assertEqual(len(proof['scan']['candidates']),2)
    def test_duplicate_json_descriptor_key_and_unsafe_archive_name_are_fatal(self):
        folder,_,_=self.f.archive();(folder/'manifest.json').write_text('{"schemaVersion":1,"schemaVersion":1}')
        with self.assertRaises((AssertionError,ValueError)):self.f.verify(self.f.admit())
    def test_filetime_word_and_raw_success_operand_types_cannot_be_forged(self):
        self.f.archive();proof=self.f.verify(self.f.admit())
        for mutate in (lambda p:p['exit']['processTimes']['creation'].update(low=0.0),
                       lambda p:p['exit'].update(getProcessIdResult=20.0),
                       lambda p:p['close'].update(result=1)):
            with self.subTest(mutate=mutate):
                changed=copy.deepcopy(proof);mutate(changed)
                with self.assertRaises((AssertionError,ValueError)):self.f.require(changed)

    def test_replay_cannot_replace_all_original_shell_images_with_a_different_executable(self):
        self.f.archive();proof=self.f.verify(self.f.admit())
        changed=copy.deepcopy(proof)
        for key in ('originalShell','beforeShell','afterShell'):
            changed['admission'][key]['image']=str(self.f.suite/'other.exe')
        with self.assertRaises((AssertionError,ValueError)):self.f.require(changed)
    def test_fixture_uses_one_canonical_root_even_for_windows_style_temp_aliases(self):
        bridge=self.f.folder/'bridge';bridge.mkdir();target=self.f.folder/'alias-case';target.mkdir()
        other=Fixture(bridge/'..'/'alias-case')
        with patch.dict(os.environ,other.environment,clear=True):
            other.archive();proof=other.verify(other.admit());other.require(proof)
        self.assertEqual(other.folder,target.resolve())

    def test_real_provider_checks_original_budget_between_native_read_calls(self):
        events=[]
        class Function:
            def __init__(self,name):self.name=name
            def __call__(inner,*args):
                events.append(inner.name)
                if inner.name=='GetProcessId':self.f.clock.now=70;return 20
                return 1
        kernel=SimpleNamespace(**{name:Function(name) for name in ('OpenProcess','GetProcessId','WaitForSingleObject',
            'GetProcessTimes','QueryFullProcessImageNameW','GetExitCodeProcess','CloseHandle')})
        provider=retirement.NativeRetirementProvider(kernel=kernel);provider.clock=self.f.clock;provider.deadline=70
        with self.assertRaisesRegex((AssertionError,ValueError),'deadline'):provider.live(222)
        self.assertEqual(events,['GetProcessId'])
    def test_open_returning_after_setup_deadline_still_releases_newly_owned_handle(self):
        original=self.f.provider.open
        def late(pid):result=original(pid);self.f.clock.now=70;return result
        self.f.provider.open=late
        with self.assertRaises((AssertionError,ValueError)):self.f.admit()
        self.assertEqual(self.f.provider.actions,['open','close'])

    def test_before_save_admission_requires_the_extra_handle_still_held(self):
        lease=self.f.admit();lease.close()
        with self.assertRaises((AssertionError,ValueError)):
            retirement.require_ime_retirement_admission(self.f.record['imeEngineRetirement'],expected_native=self.f.binding,
                expected_run=RUN,expected_case='ime-writer',expected_source=SHA,expected_original_profile=self.f.original_profile)
    def test_native_first_wait_result_is_retained_before_lease_deadline_rejection(self):
        class Function:
            def __init__(self,name):self.name=name
            def __call__(inner,*args):
                if inner.name=='WaitForSingleObject':self.f.clock.now=95;return 0
                return 1
        kernel=SimpleNamespace(**{name:Function(name) for name in ('OpenProcess','GetProcessId','WaitForSingleObject',
            'GetProcessTimes','QueryFullProcessImageNameW','GetExitCodeProcess','CloseHandle')})
        self.f.clock.now=80
        provider=retirement.NativeRetirementProvider(kernel=kernel,deadline=95,clock=self.f.clock)
        raw=provider.wait_zero(222)
        self.assertEqual(raw['result'],0);self.assertEqual(raw['timeoutMilliseconds'],0)

    def test_a_recorded_primary_error_cannot_be_overridden_by_success_flags(self):
        self.f.archive();proof=self.f.verify(self.f.admit());changed=copy.deepcopy(proof)
        changed['error']='original failure'
        with self.assertRaises((AssertionError,ValueError)):self.f.require(changed)

    def test_total_actual_selected_members_include_manifest_and_optional_events(self):
        folder,manifest,_=self.f.archive()
        for index in range(127):
            name=f'member-{index}.txt';(folder/name).write_bytes(b'x')
            manifest['files'].append(dict(path=name,bytes=1,sha256=hashlib.sha256(b'x').hexdigest()))
        (folder/'manifest.json').write_text(json.dumps(manifest))
        with self.assertRaises((AssertionError,ValueError)):self.f.verify(self.f.admit())

    def test_all_four_raw_filetime_groups_are_exact_uint32_words(self):
        self.f.archive();proof=self.f.verify(self.f.admit())
        changes=[lambda p:p['exit']['processTimes']['exit'].update(low=False),
                 lambda p:p['exit']['processTimes']['kernel'].update(high=1.5),
                 lambda p:p['exit']['processTimes']['user'].update(low=2**32),
                 lambda p:p['exit']['processTimes'].pop('user'),
                 lambda p:p['exit']['processTimes'].update(extra=dict(low=0,high=0)),
                 lambda p:p['admission']['extraEngine']['processTimes']['creation'].update(low=0,high=0)]
        for index,mutate in enumerate(changes):
            with self.subTest(index=index):
                changed=copy.deepcopy(proof);mutate(changed)
                with self.assertRaises((AssertionError,ValueError)):self.f.require(changed)

    def test_cached_diagnostics_root_must_be_outside_original_profile(self):
        self.f.archive();proof=self.f.verify(self.f.admit());changed=copy.deepcopy(proof)
        changed['admission']['originalProfile']=dict(profileUrl='file:///C:/private-profile',
            canonicalPath='c:\\private-profile',volumeSerialNumber=104,fileIndexHigh=0,fileIndexLow=105)
        changed['admission']['diagnosticsRoot']='C:\\private-profile\\diagnostics'
        with self.assertRaises((AssertionError,ValueError)):self.f.require(changed)

    def test_profile_root_equal_nested_and_sibling_replay_are_distinct(self):
        self.f.archive();proof=self.f.verify(self.f.admit())
        for root in ('C:\\PRIVATE-PROFILE','C:\\private-profile\\diagnostics'):
            with self.subTest(root=root):
                changed=copy.deepcopy(proof);changed['admission']['diagnosticsRoot']=root
                with self.assertRaises((AssertionError,ValueError)):self.f.require(changed)
        sibling=copy.deepcopy(proof);sibling['admission']['diagnosticsRoot']='C:\\private-profile-other\\diagnostics'
        self.assertIs(self.f.require(sibling),sibling)
        profile=dict(self.f.original_profile,canonicalPath='c:\\strasse')
        with self.assertRaises((AssertionError,ValueError)):retirement._outside_profile('C:\\Straße\\diagnostics',profile)

    def test_original_profile_source_argument_and_independent_expected_projection_are_joined(self):
        self.f.original_profile['fileIndexLow']+=1
        with self.assertRaises((AssertionError,ValueError)):self.f.admit()
        self.assertNotIn('open',self.f.provider.actions)
        self.f.original_profile['fileIndexLow']-=1;self.f.record.pop('imeEngineRetirement')
        self.f.archive();proof=self.f.verify(self.f.admit());changed=copy.deepcopy(proof)
        changed['admission']['originalProfile']['fileIndexLow']+=1
        with self.assertRaises((AssertionError,ValueError)):self.f.require(changed)

    def test_original_profile_context_is_typed_and_completed_before_admission(self):
        context=self.f.record['imeSemanticContext']
        for name,mutate in (('floatNative',lambda:context['expectedNative'].update(officePid=20.0)),
                            ('futureCompletion',lambda:context.update(finishedAt=11.))):
            with self.subTest(name=name):
                saved=copy.deepcopy(context);mutate()
                try:
                    with self.assertRaises((AssertionError,ValueError)):self.f.admit()
                finally:
                    self.f.record.pop('imeEngineRetirement',None);context.clear();context.update(saved)

    def test_exactly_128_actual_files_including_named_events_is_the_positive_boundary(self):
        folder,manifest,_=self.f.archive()
        for index in range(125):
            name=f'member-{index}.txt';(folder/name).write_bytes(b'x')
            manifest['files'].append(dict(path=name,bytes=1,sha256=hashlib.sha256(b'x').hexdigest()))
        (folder/'events.jsonl').write_bytes(b'event\n');(folder/'manifest.json').write_text(json.dumps(manifest))
        proof=self.f.verify(self.f.admit());self.assertEqual(len(proof['archive']['members']),128)
        changed=copy.deepcopy(proof);changed['archive']['members'].append(dict(path='extra',bytes=0,sha256=hashlib.sha256(b'').hexdigest()))
        with self.assertRaises((AssertionError,ValueError)):self.f.require(changed)


if __name__=='__main__':unittest.main()
