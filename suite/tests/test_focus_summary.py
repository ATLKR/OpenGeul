"""Only existing, generation-bound PRE/POST guard snapshots become finite enums."""
import copy
import importlib.util
from pathlib import Path
import unittest

SCRIPT=Path(__file__).resolve().parents[1]/'e2e/focus_summary.py'


def admitted_record():
    binding=dict(shellPid=77,officePid=31,suiteHwnd=11,parentHwnd=12,childHwnd=22,rootHwnd=11,
        shellCreationTime=1000,officeCreationTime=2000,expectedImage='C:/Synthetic Suite/Office/program/soffice.bin')
    def window(hwnd,pid,tid,root=11):
        return dict(hwnd=hwnd,pid=pid,threadId=tid,rootHwnd=root,isWindow=True,className='PRIVATE')
    shell=dict(pid=77,handleValue=201,creationTime=1000,waitResult=258)
    engine=dict(pid=31,handleValue=202,creationTime=2000,waitResult=258)
    edge=dict(suite=window(11,77,71),editor=window(22,31,41),
        foreground=window(11,77,71),editorWithinSuite=True)
    context=dict(schemaVersion=1,kind='ime-semantic-editing-context',module='calc',phase='pre',
        success=False,startedAt=20.,setupDeadline=70.,readerDeadline=32.,expectedNative=copy.deepcopy(binding),
        observations=[],sampleTimings=[],cleanupErrors=[])
    return dict(module='calc',case='ime-calc',kind='calc-save-dispatch-diagnostic',imePolicyVersion=4,
        architecture='arm64',shellPid=77,officePid=31,windowHwnd=11,parentHwnd=12,childHwnd=22,
        editorTid=41,stage='verify-pre-prefix-editing-context',
        readiness=dict(nativeMachine=0xaa64,controllerMachine=0,source=dict(sourceCommit='a'*40,
            sourceRun='123',runAttempt='1',repository='ATLKR/OpenGeul',job='windows-suite',architecture='arm64')),
        imeSetupBudget=dict(startedAt=10.,deadline=70.),
        imeKeyboardSession=dict(schemaVersion=1,kind='owned-first-admission-ime-keyboard',module='calc',
            setupDeadline=70.,expectedNative=binding,originalShell=shell,originalEngine=engine,
            lastGuardObservation=dict(shell=copy.deepcopy(shell),engine=copy.deepcopy(engine),
                keyboardThreadId=41,scope=dict(before=copy.deepcopy(edge),after=copy.deepcopy(edge)))),
        imeSemanticContext=context,imeSemanticContexts=[context])


def implementation():
    assert SCRIPT.is_file(),'Bounded existing-focus projection is required'
    spec=importlib.util.spec_from_file_location('focus_summary_under_test',SCRIPT)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


class FocusSummaryTests(unittest.TestCase):
    def test_last_existing_guard_and_empty_reader_progress_are_observed_without_mutation(self):
        record=admitted_record();before=copy.deepcopy(record)
        self.assertEqual(implementation().project(record),[2,2,0,0,0])
        self.assertEqual(record,before)

    def test_foreground_relations_distinguish_none_dead_owned_and_foreign(self):
        cases=(
            (dict(hwnd=0,isWindow=False,pid=0,threadId=0,rootHwnd=0),0),
            (dict(hwnd=123,isWindow=False,pid=0,threadId=0,rootHwnd=0),1),
            (dict(hwnd=22,isWindow=True,pid=31,threadId=41,rootHwnd=11),3),
            (dict(hwnd=22,isWindow=True,pid=31,threadId=41,rootHwnd=123),4),
            (dict(hwnd=22,isWindow=True,pid=31,threadId=99,rootHwnd=11),4),
            (dict(hwnd=123,isWindow=True,pid=999,threadId=99,rootHwnd=123),5))
        for foreground,expected in cases:
            record=admitted_record()
            record['imeKeyboardSession']['lastGuardObservation']['scope']['after']['foreground']=foreground
            with self.subTest(expected=expected):
                self.assertEqual(implementation().project(record),[2,expected,0,0,0])

    def test_attempted_returned_count_and_cleanup_presence_are_not_success_claims(self):
        record=admitted_record();context=record['imeSemanticContext']
        context.update(readerStartAttempted=True,observations=[dict(private='PRIVATE')],
            cleanup=dict(success=False,error='PRIVATE'))
        self.assertEqual(implementation().project(record),[2,2,2,1,1])
        context['readerStartAttempted']=False
        self.assertEqual(implementation().project(record),[2,2,1,1,1])
        context.update(phase='post');record['stage']='verify-post-prefix-editing-context'
        self.assertEqual(implementation().project(record),[2,2,1,1,1])

    def test_actual_first_guard_before_history_append_is_bound_to_a_fresh_context(self):
        record=admitted_record();context=record['imeSemanticContext']
        record['imeSemanticContexts']=[]
        self.assertEqual(implementation().project(record),[2,2,0,0,0])
        prior=copy.deepcopy(context);context['phase']='post'
        record.update(stage='verify-post-prefix-editing-context',imeSemanticContexts=[prior])
        self.assertEqual(implementation().project(record),[2,2,0,0,0])
        for damage in ('observations','attempted','cleanup','prior-generation'):
            changed=copy.deepcopy(record);current=changed['imeSemanticContext']
            if damage=='observations':current['observations']=[{}]
            elif damage=='attempted':current['readerStartAttempted']=True
            elif damage=='cleanup':current['cleanup']={}
            else:changed['imeSemanticContexts'][0]['expectedNative']['officeCreationTime']+=1
            with self.subTest(damage=damage):self.assertIsNone(implementation().project(changed))

    def test_missing_stale_or_mixed_native_context_is_unknown(self):
        for damage in ('missing','source','source-arch','native-machine','case','kind','stage','history',
                'module','context-generation','keyboard-generation','guard-generation','handle','scope-shell',
                'scope-editor','scope-thread','setup','reader-deadline','started','attempted','observations','cleanup'):
            record=admitted_record();keyboard=record['imeKeyboardSession'];context=record['imeSemanticContext']
            if damage=='missing':keyboard.pop('lastGuardObservation')
            elif damage=='source':record['readiness']['source']['sourceRun']='bad'
            elif damage=='source-arch':record['readiness']['source']['architecture']='x64'
            elif damage=='native-machine':record['readiness']['nativeMachine']=0x8664
            elif damage=='case':record['case']='ime-writer'
            elif damage=='kind':record['kind']='unbound'
            elif damage=='stage':record['stage']='physical-dubeolsik-composition'
            elif damage=='history':record['imeSemanticContexts']=[copy.deepcopy(context)]
            elif damage=='module':context['module']='writer'
            elif damage=='context-generation':context['expectedNative']['officeCreationTime']+=1
            elif damage=='keyboard-generation':keyboard['originalEngine']['creationTime']+=1
            elif damage=='guard-generation':keyboard['lastGuardObservation']['engine']['creationTime']+=1
            elif damage=='handle':keyboard['lastGuardObservation']['engine']['handleValue']+=1
            elif damage=='scope-shell':keyboard['lastGuardObservation']['scope']['before']['suite']['pid']+=1
            elif damage=='scope-editor':keyboard['lastGuardObservation']['scope']['after']['editor']['hwnd']+=1
            elif damage=='scope-thread':keyboard['lastGuardObservation']['scope']['after']['editor']['threadId']+=1
            elif damage=='setup':context['setupDeadline']+=1
            elif damage=='reader-deadline':context['readerDeadline']+=1
            elif damage=='started':context['startedAt']=float('nan')
            elif damage=='attempted':context['readerStartAttempted']=1
            elif damage=='observations':context['observations']=[{}]*121
            else:context['cleanup']=True
            with self.subTest(damage=damage):self.assertIsNone(implementation().project(record))

    def test_inconsistent_foreground_zero_types_and_ranges_remain_unknown(self):
        for change in (dict(hwnd=True),dict(pid=True),dict(threadId='PRIVATE'),dict(rootHwnd=-1),
                dict(isWindow=1),dict(hwnd=0),dict(pid=0),dict(threadId=0),dict(rootHwnd=0),
                dict(hwnd=0,isWindow=False,pid=77,threadId=0,rootHwnd=0),dict(hwnd=2**64)):
            record=admitted_record()
            record['imeKeyboardSession']['lastGuardObservation']['scope']['before']['foreground'].update(change)
            with self.subTest(change=change):self.assertIsNone(implementation().project(record))

    def test_text_paths_keyboard_payload_and_clock_are_not_observed(self):
        class Unreadable:
            def __bool__(self):raise AssertionError('Private value read')
            def __eq__(self,other):raise AssertionError('Private value read')
            def __str__(self):raise AssertionError('Private value read')
        record=admitted_record()
        for key in ('error','traceback','events','keyTokens','asciiPrefix','savedText','file'):record[key]=Unreadable()
        binding=record['imeKeyboardSession']['expectedNative'];binding['expectedImage']=Unreadable()
        record['imeSemanticContext']['expectedNative']['expectedImage']=Unreadable()
        for edge in ('before','after'):
            for value in record['imeKeyboardSession']['lastGuardObservation']['scope'][edge].values():
                if type(value) is dict:value['className']=Unreadable()
        self.assertEqual(implementation().project(record),[2,2,0,0,0])


if __name__=='__main__':unittest.main()
