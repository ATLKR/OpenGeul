"""Contracts for a diagnostic experiment; no test sends Windows input."""
from contextlib import contextmanager
import copy
import ctypes
import hashlib
import importlib
import json
from pathlib import Path
import sys
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
import xml.etree.ElementTree as ET
import zipfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'e2e'))
import physical_ascii_probe as probe
import keyboard_delivery as delivery


def queue(text, *, reserved=None):
    defaults={name:0 for name,_ in delivery.Message._fields_}
    rows = [dict(defaults,sequence=i+1, message=0x102, remove=True, retrievalFlags=1,
                 pid=88, tid=99, hwnd=22, wparam=ord(char), counter=110+i,
                 layout=0x04090409, focus=22, shift=0, control=0, alt=0,unicodeWindow=1)
            for i, char in enumerate(text)]
    return dict(officePid=88, editorTid=99, childHwnd=22, messages=rows,
                overflow=False, publishedMessageCount=len(rows),
                reservedMessageCount=len(rows) if reserved is None else reserved,
                sendInputCalls=[], observer={'stateVersion':2, 'stateBytes':262168,'hook':'WH_GETMESSAGE',
                    'scope':'owned-editor-thread','compileBeforeTrials':True,'sourceSha256':'1'*64,'dllSha256':'2'*64})


def prefix(text, phase, tick, *, reserved=None):
    return dict(phase=phase, qpcBegin={'counter':tick, 'frequency':1000},
                qpcEnd={'counter':tick+1, 'frequency':1000}, queue=queue(text,reserved=reserved))


def observation():
    first, second = probe.lifecycle.ASCII_EDITOR_MARKERS[probe.CASE]
    # Queue timestamps precede the before-getter boundary even for long markers.
    first_prefix=prefix(first,'after-first-edit',200)
    before=prefix(first+second,'before-live-model-read',300)
    after=prefix(first+second,'after-live-model-read',500)
    return dict(officePid=88,editorTid=99,childHwnd=22,prefixes=[first_prefix,before,after],
                liveReadWindow={'begin':{'counter':302,'frequency':1000},'end':{'counter':499,'frequency':1000}},
                model={'bodyText':'baseline\n'+first+second,'getterClock':{
                    'begin':{'counter':350,'frequency':1000},'end':{'counter':400,'frequency':1000}}},
                expectedBodyText='baseline\n'+first+second)


class PlanTests(unittest.TestCase):
    def test_fixed_twenty_alternating_trials_keep_original_case_name(self):
        plan=probe.trial_plan()
        self.assertEqual([x['trial'] for x in plan],list(range(1,21)))
        self.assertEqual([x['instrumented'] for x in plan],[i%2==0 for i in range(20)])
        self.assertEqual({x['case'] for x in plan},{'dirty-writer-cancel-save'})
        self.assertEqual(len({x['trialId'] for x in plan}),20)

    def test_observer_is_exact_existing_protocol_two_abi(self):
        delivery=importlib.import_module('keyboard_delivery')
        self.assertEqual(hashlib.sha256(Path(delivery.__file__).read_bytes()).hexdigest(),
                         '0a08413dce9cccd9c63247f9f92911075318f04e8b4de3eafd32bec67e6c1042')
        self.assertEqual(ctypes.sizeof(delivery.Message),128)
        self.assertEqual(ctypes.sizeof(delivery.State),262168)
        self.assertEqual(delivery.Message.counter.offset,88)
        self.assertEqual(delivery.Message.retrievalFlags.offset,120)
        self.assertEqual(delivery.State.messages.offset,24)

    def test_original_failure_cannot_become_success_after_good_reopen(self):
        rows=[dict(plan,originalActionSuccess=True,postSave={'observationComplete':True,'expectedBodyMatches':True})
              for plan in probe.trial_plan()]
        rows[0]['originalActionSuccess']=False
        result=probe.experiment_report(rows)
        self.assertFalse(result['success'])
        self.assertTrue(result['experimentCompleted'])
        self.assertEqual(result['originalActionPassedTrialCount'],19)
        self.assertEqual(len(result['tests']),20)

    def test_missing_or_duplicate_trial_does_not_count_as_complete(self):
        rows=[dict(plan,originalActionSuccess=True,postSave={'observationComplete':True,'expectedBodyMatches':True})
              for plan in probe.trial_plan()]
        rows[-1]=copy.deepcopy(rows[0])
        self.assertFalse(probe.experiment_report(rows)['experimentCompleted'])

    def test_optimized_cli_fails_before_any_output_is_created(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'must-not-exist'
            result=subprocess.run([sys.executable,'-O',probe.__file__,'--suite',folder,'--output',str(target)],
                                  capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('optimized Python is forbidden',result.stderr)
            self.assertFalse(target.exists())


class QueueClassifierTests(unittest.TestCase):
    def test_before_read_queue_and_model_are_separate_observations(self):
        result=probe.analyze_observation(observation())
        self.assertTrue(result['beforeReadCharactersExact'])
        self.assertTrue(result['modelExact'])
        self.assertFalse(result['applicationConsumptionCertified'])
        self.assertEqual(result['boundary'],'exact-model-observed')

    def test_missing_r_in_model_with_exact_removed_chars_keeps_order_unresolved(self):
        value=observation();value['model']['bodyText']=value['expectedBodyText'].replace('-AFTER-','-AFTE-')
        result=probe.analyze_observation(value)
        self.assertTrue(result['beforeReadCharactersExact'])
        self.assertFalse(result['modelExact'])
        self.assertEqual(result['boundary'],'removed-characters-exact-model-differs-order-unresolved')

    def test_late_after_getter_r_never_backfills_before_getter_prefix(self):
        value=observation()
        value['prefixes'][1]['queue']=queue(''.join(probe.lifecycle.ASCII_EDITOR_MARKERS[probe.CASE]).replace('-AFTER-','-AFTE-'))
        # Independently preserve the later receipt instead of pretending it was
        # a prefix of an earlier snapshot that already contains the missing R.
        value['prefixes'][2]['queue']=copy.deepcopy(value['prefixes'][1]['queue'])
        q=value['prefixes'][2]['queue'];seq=len(q['messages'])+1
        late=queue('R')['messages'][0];late.update(sequence=seq,counter=450)
        q['messages'].append(late)
        q['publishedMessageCount']=q['reservedMessageCount']=seq
        result=probe.analyze_observation(value)
        self.assertFalse(result['beforeReadCharactersExact'])
        self.assertIn('unresolved',result['boundary'])

    def test_peek_without_remove_never_counts_as_delivered_character(self):
        value=observation()
        for p in value['prefixes']:
            for row in p['queue']['messages']:
                if row['wparam']==ord('R'):
                    row.update(remove=False,retrievalFlags=2)
        result=probe.analyze_observation(value)
        self.assertFalse(result['beforeReadCharactersExact'])

    def test_reserved_unpublished_row_is_preserved_and_incomplete(self):
        value=observation();value['prefixes'][1]['queue']['reservedMessageCount']+=1
        result=probe.analyze_observation(value)
        self.assertFalse(result['beforeReadPrefixComplete'])
        self.assertEqual(result['boundary'],'incomplete-prefix-observation-unresolved')

    def test_foreign_pid_or_tid_is_rejected(self):
        for key in ('pid','tid'):
            with self.subTest(key=key):
                value=observation();value['prefixes'][1]['queue']['messages'][0][key]=999
                with self.assertRaisesRegex(AssertionError,'ownership'):
                    probe.analyze_observation(value)

    def test_changed_published_prefix_is_rejected(self):
        value=observation();value['prefixes'][2]['queue']['messages'][0]['wparam']=ord('X')
        with self.assertRaisesRegex(AssertionError,'prefix'):
            probe.analyze_observation(value)

    def test_getter_outside_client_read_window_is_rejected(self):
        value=observation();value['model']['getterClock']['begin']['counter']=250
        with self.assertRaisesRegex(AssertionError,'clock'):
            probe.analyze_observation(value)

    def test_frequency_mismatch_or_boolean_is_rejected(self):
        for frequency in (0,True,999):
            with self.subTest(frequency=frequency):
                value=observation();value['model']['getterClock']['begin']['frequency']=frequency
                with self.assertRaisesRegex(AssertionError,'clock'):
                    probe.analyze_observation(value)

    def test_raw_queue_abi_or_boolean_counter_is_rejected(self):
        for change in ('abi','counter'):
            with self.subTest(change=change):
                value=observation()['prefixes'][0]
                if change=='abi':value['queue']['observer']['stateBytes']=1
                else:value['queue']['messages'][0]['counter']=True
                with self.assertRaises(AssertionError):
                    probe.require_queue_prefix(value,88,99,22,1000)

    def test_overflow_and_unpublished_tail_remain_valid_unresolved_facts(self):
        value=observation()['prefixes'][0]
        value['queue']['overflow']=True
        value['queue']['reservedMessageCount']+=3
        result=probe.require_queue_prefix(value,88,99,22,1000)
        self.assertFalse(result['complete'])
        self.assertEqual(result['reservedMessageCount']-result['publishedMessageCount'],3)


class ModelWitnessTests(unittest.TestCase):
    def value(self):
        image=Path('C:/suite/Office/program/soffice.bin')
        witness=dict(officePid=88,childHwnd=22,officeCreationTime=7,expectedImage=str(image),
            **{k:True for k in ['retainedProcessHandle','imageVerified','creationTimeVerified',
                'hwndVerifiedBefore','hwndVerifiedAfter','generationVerifiedAfter']})
        return image,dict(officePid=88,childHwnd=22,officeCreationTime=7,expectedImage=str(image),
            pipe='OpenGeul_'+'a'*32,privatePipeVerified=True,readOnlyObservation=True,
            liveGetterAttempts=1,success=True,witness=witness)

    def test_model_requires_exact_retained_generation_pipe_and_one_getter(self):
        image,value=self.value()
        self.assertIs(probe.require_model_witness(value,88,22,7,image,value['pipe']),value)
        for key,replacement in [('officePid',999),('officeCreationTime',8),('pipe','OpenGeul_'+'b'*32),
                                ('liveGetterAttempts',2),('readOnlyObservation',False)]:
            with self.subTest(key=key):
                other=copy.deepcopy(value);other[key]=replacement
                with self.assertRaises(AssertionError):probe.require_model_witness(other,88,22,7,image,value['pipe'])

    def test_after_read_generation_loss_cannot_be_accepted(self):
        image,value=self.value();value['witness']['generationVerifiedAfter']=False
        with self.assertRaisesRegex(AssertionError,'witness'):
            probe.require_model_witness(value,88,22,7,image,value['pipe'])

    def test_body_getter_is_called_once_between_native_qpc_samples(self):
        order=[]
        class Text:
            def getString(self):order.append('getString');return 'actual body'
        clock=SimpleNamespace(sample=lambda:(order.append('qpc') or {'counter':len(order),'frequency':1000}))
        result={'liveGetterAttempts':0}
        probe.read_body_once(Text(),clock,result)
        self.assertEqual(order,['qpc','getString','qpc'])
        self.assertEqual(result['bodyText'],'actual body')
        self.assertEqual(result['liveGetterAttempts'],1)
        with self.assertRaisesRegex(AssertionError,'once'):probe.read_body_once(Text(),clock,result)
        self.assertEqual(order,['qpc','getString','qpc'])

    def test_getter_exception_retains_attempt_and_end_clock_without_retry(self):
        order=[]
        class Text:
            def getString(self):order.append('getString');raise ValueError('actual read failed')
        clock=SimpleNamespace(sample=lambda:(order.append('qpc') or {'counter':len(order),'frequency':1000}))
        result={'liveGetterAttempts':0}
        with self.assertRaisesRegex(ValueError,'actual read failed'):probe.read_body_once(Text(),clock,result)
        self.assertEqual(order,['qpc','getString','qpc'])
        self.assertEqual(result['liveGetterAttempts'],1)
        self.assertIn('end',result['getterClock'])


class Function:
    def __init__(self,call): self.call=call
    def __call__(self,*args): return self.call(*args)


class ClockTests(unittest.TestCase):
    def test_native_qpc_preserves_64_bits_and_declares_pointer_abi(self):
        def put(value):
            def call(pointer):
                ctypes.cast(pointer,ctypes.POINTER(ctypes.c_int64))[0]=value
                return 1
            return Function(call)
        kernel=SimpleNamespace(QueryPerformanceFrequency=put(10_000_000),QueryPerformanceCounter=put(1<<54))
        clock=probe.NativeClock(kernel)
        self.assertEqual(clock.sample(),{'counter':1<<54,'frequency':10_000_000})
        self.assertEqual(kernel.QueryPerformanceCounter.argtypes,(ctypes.POINTER(ctypes.c_int64),))
        self.assertEqual(ctypes.sizeof(kernel.QueryPerformanceCounter.argtypes[0]._type_),8)

    def test_native_qpc_failure_is_not_fabricated_as_zero(self):
        kernel=SimpleNamespace(QueryPerformanceFrequency=Function(lambda p:0))
        with self.assertRaisesRegex(OSError,'QueryPerformanceFrequency'):
            probe.NativeClock(kernel)


class PostActionObservationTests(unittest.TestCase):
    def observe(self,folder,*,bad_xml=False):
        root=Path(folder);(root/'fixtures'/probe.CASE).mkdir(parents=True)
        plan=probe.trial_plan_with_body('baseline\n')[0]
        (root/'preregistered-trial.json').write_text(json.dumps(plan))
        source=probe.owned_source(root)
        if bad_xml:source.write_bytes(b'invalid-DOCX-retained-for-observation')
        else:
            ns='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
            document=ET.Element(ns+'document');body=ET.SubElement(document,ns+'body')
            para=ET.SubElement(body,ns+'p');run=ET.SubElement(para,ns+'r')
            ET.SubElement(run,ns+'t').text=plan['expectedBodyText']
            with zipfile.ZipFile(source,'w') as package:package.writestr('word/document.xml',ET.tostring(document))
        calls=[]
        class Document:
            def supportsService(self,name):return name=='com.sun.star.text.TextDocument'
            def isReadonly(self):return True
            def isModified(self):return False
            def getText(self):return self
            def getString(self):calls.append('getString');return plan['expectedBodyText']
            def close(self,ownership):calls.append(('close',ownership))
        class Engine:
            def __init__(self,suite):self.cleanup_errors=[];self.desktop=self
            def start(self):calls.append('engine-start')
            def prop(self,name,value):return (name,value)
            def loadComponentFromURL(self,url,target,flags,props):
                calls.append(('load',dict(props)));return Document()
            def cleanup(self):calls.append('cleanup')
        import engine_smoke,writer_style_smoke
        with patch.object(engine_smoke,'Engine',Engine),\
             patch.object(writer_style_smoke,'observe_packaged_python',lambda:{}),\
             patch.object(writer_style_smoke,'require_packaged_python',lambda *a:{'verified':True}),\
             patch.dict(sys.modules,{'dispatch':SimpleNamespace(make_interaction_handler=lambda:object())}):
            exit_code=probe.verify_saved_readonly(Path('/suite'),root)
        return exit_code,calls,json.loads((root/'saved-readonly-uno.json').read_text())

    def test_readonly_reopen_does_not_clear_modified_or_store_and_hashes_stay_equal(self):
        with tempfile.TemporaryDirectory() as folder:
            code,calls,result=self.observe(folder)
        self.assertEqual(code,0)
        self.assertTrue(result['observationComplete'])
        self.assertEqual(result['beforeSha256'],result['afterCloseSha256'])
        self.assertEqual(result['beforeSha256'],result['afterCleanupSha256'])
        self.assertEqual(calls.count('getString'),1)
        properties=next(x[1] for x in calls if isinstance(x,tuple) and x[0]=='load')
        self.assertTrue(properties['ReadOnly'])
        self.assertEqual(calls[-2:],[('close',False),'cleanup'])

    def test_invalid_xml_still_attempts_independent_uno_and_retains_both_observations(self):
        with tempfile.TemporaryDirectory() as folder:
            code,calls,result=self.observe(folder,bad_xml=True)
        self.assertEqual(code,1)
        self.assertIn('engine-start',calls)
        self.assertIn('getString',calls)
        self.assertFalse(result['observationComplete'])
        self.assertIn('xmlError',result)
        self.assertIn('observedBodyText',result)

    def test_truncated_reader_json_preserves_original_failure_and_next_planned_trial(self):
        original_action=probe.lifecycle.dirty_cancel_save
        class FailedCase:
            def __init__(self,suite,fixtures,output,name):
                self.record={'case':name,'success':False,'error':'original exact-marker failure'}
                source=output/'fixtures'/name/('원본 문서 & '+name+'.docx')
                source.parent.mkdir();source.write_bytes(b'original candidate bytes')
                probe.write_json(output/(name+'-result.json'),self.record)
            def run(self,action):
                if action is not original_action:raise RuntimeError('Original action was replaced')
                raise AssertionError('original exact-marker failure')
        attempts=[]
        payloads=['{"observationComplete":','[]']
        def failed_reader(command,folder,stem,**kwargs):
            attempts.append(str(folder))
            (folder/'saved-readonly-uno.json').write_text(payloads[len(attempts)-1])
            raise subprocess.TimeoutExpired(command,30)
        with tempfile.TemporaryDirectory() as folder,\
             patch.object(probe.lifecycle,'Case',FailedCase),patch.object(probe,'capture_command',failed_reader):
            rows=[]
            for index,plan in enumerate(probe.trial_plan_with_body('baseline\n')[1:4:2]):
                target=Path(folder)/plan['trialId']
                try:row=probe.run_trial(Path('/suite'),Path('/fixtures'),target,plan,None,None)
                except Exception as exc:self.fail('Retained reader output aborted planned continuation: '+repr(exc))
                rows.append(row)
                self.assertFalse(row['originalActionSuccess'])
                self.assertEqual(row['originalRecord']['error'],'original exact-marker failure')
                self.assertIn('TimeoutExpired',row['postSaveProcessError'])
                self.assertIn('postSaveReadError',row)
                self.assertFalse(row['postSave']['observationComplete'])
                self.assertEqual((target/'saved-readonly-uno.json').read_text(),payloads[index])
                self.assertEqual(json.loads((target/'trial-result.json').read_text()),row)
            self.assertEqual(len(attempts),2)
            self.assertEqual(len(rows),2)


class ObservationOrderTests(unittest.TestCase):
    def make_case(self,events,*,read_error=None):
        @contextmanager
        def retained(child,pid,image,witness,**kwargs):
            events.append('retain');witness.update(officePid=pid,childHwnd=child,officeCreationTime=7)
            try: yield SimpleNamespace(creation_time=7)
            finally: events.append('release')
        class Observer:
            def __init__(self,*args): events.append('hook');self.pid=88;self.tid=99
            def receipt(self): events.append('prefix');return queue('')
            def close(self): events.append('unhook')
        def original(case,hwnd,child,marker):events.append('edit:'+marker)
        def model(*args):
            events.append('getter')
            if read_error: raise read_error
            return {'bodyText':'unchanged-observation'}
        def init(case,*args,**kwargs):
            case.record={'attachments':[{'hwnd':11,'child':22,'officePid':88}]}
            case.suite=Path('/suite');case.folder=Path('/trial/fixtures/'+probe.CASE)
            case.source=case.folder/'original.docx'
            case.api=SimpleNamespace(pid=lambda h:88);case.process=SimpleNamespace(pid=77)
        self.enterContext(patch.object(probe.lifecycle.Case,'__init__',init))
        self.enterContext(patch.object(probe.lifecycle.Case,'edit',original))
        self.enterContext(patch.object(probe,'retained_generation',retained))
        self.enterContext(patch.object(probe,'DeliveryObserver',Observer))
        self.enterContext(patch.object(probe,'observe_live_model',model))
        self.enterContext(patch.object(probe.accessible,'_command_line',lambda g:[]))
        self.enterContext(patch.object(probe.accessible,'private_pipe',lambda a:'OpenGeul_'+'a'*32))
        clock=SimpleNamespace(sample=lambda:{'counter':1000+len(events),'frequency':1000})
        return probe.ObservedCase(plan=probe.trial_plan()[0],library=object(),clock=clock)

    def test_one_hook_spans_cancel_and_both_unchanged_edits_then_unhooks_before_save(self):
        events=[];case=self.make_case(events)
        first,second=probe.lifecycle.ASCII_EDITOR_MARKERS[probe.CASE]
        case.edit(11,22,first);events.append('original-cancel')
        case.edit(11,22,second);events.append('original-save')
        self.assertEqual(events,['retain','hook','edit:'+first,'prefix','original-cancel',
                                 'edit:'+second,'prefix','getter','prefix','unhook','release','original-save'])
        self.assertEqual(case.record['physicalObservation']['liveGetterAttempts'],1)

    def test_getter_error_is_retained_and_unhooked_without_retry(self):
        events=[];case=self.make_case(events,read_error=ValueError('actual getter error'))
        first,second=probe.lifecycle.ASCII_EDITOR_MARKERS[probe.CASE]
        case.edit(11,22,first)
        with self.assertRaisesRegex(ValueError,'actual getter error'):case.edit(11,22,second)
        self.assertEqual(events.count('getter'),1)
        self.assertEqual(events[-2:],['unhook','release'])
        self.assertIn('actual getter error',case.record['physicalObservation']['error'])

    def test_foreign_attachment_stops_before_hook_or_editor_input(self):
        events=[];case=self.make_case(events)
        case.record['attachments'][0]['officePid']=999
        with self.assertRaisesRegex(AssertionError,'attachment'):case.edit(11,22,'x')
        self.assertEqual(events,[])


if __name__=='__main__':unittest.main()
