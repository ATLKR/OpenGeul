"""Typed absence never supplies an original scalar; portable native boundaries."""
import copy
import ctypes
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

E2E=Path(__file__).resolve().parents[1]/'e2e'
sys.path.insert(0,str(E2E));sys.path.insert(0,str(Path(__file__).resolve().parent))
import ime_thread_mode as mode
import korean_ime_smoke as ime
import test_ime_mode_receipts as mode_fixtures
import test_korean_ime_smoke as ime_fixtures
from ime_typed_policy_fixtures import complete_record

HARNESS=r'''
#include <string>
#include "ime_typed_origin.h"
using namespace opengeul_ime;
static_assert(sizeof(ModeReceipt)==184,"old ABI");
struct Fake {
 ModeReceipt* receipt; Value a{1,0,0},b{1,0,0}; int refs=0,enumerated=0,reads=0,writes=0,clients=0,releases=0; bool expired=false,late=false,wrong=false,clear=false;
 bool WithinBudget(){return !expired;}
 int32_t ExistingManager(){++refs;return 0;}bool HasManager(){return true;}
 int32_t CompartmentManager(){++refs;return 0;}bool HasCompartmentManager(){return true;}
 int32_t BeginEnumeration(){++refs;return 0;}bool HasEnumerator(){return true;}
 int32_t Next(int& k){k=++enumerated;return 0;}uint32_t Fetched(){return 1;}
 int32_t Get(int){++refs;return 0;}bool HasCompartment(int){return true;}
 Value Read(int k){++reads;receipt->variantClearHr=clear?-123:0;if(clear)receipt->cleanupStatus=-123;
   if(late){expired=true;}
   if(writes){return {0,3,wrong?9:k==1?1:0};}return k==1?a:b;}
 int32_t ClientInterface(){++refs;++clients;return 0;}bool HasClient(){return true;}
 int32_t ObserverClient(uint32_t& id){id=17;return 0;}
 int32_t Write(int,uint32_t,int32_t){++writes;return 0;}
 ReleaseCounts Release(){++releases;return {uint32_t(refs),uint32_t(refs)};}
};
int main(int argc,char**argv){if(argc!=2)return 90;std::string n=argv[1];ModeReceipt r{};Fake f;f.receipt=&r;TypedPair original{{1,0,0},{1,0,0}};
 if(n=="us-profile")return EmptyOriginUsProfile(0x04090409,2,0x0409,0x04090409,true,true)
  && !EmptyOriginUsProfile(0x04120412,2,0x0409,0x04090409,true,true)
  && !EmptyOriginUsProfile(0x04090409,1,0x0409,0x04090409,true,true)
  && !EmptyOriginUsProfile(0x04090409,2,0x0412,0x04090409,true,true)
  && !EmptyOriginUsProfile(0x04090409,2,0x0409,0x04120412,true,true)
  && !EmptyOriginUsProfile(0x04090409,2,0x0409,0x04090409,false,true)
  && !EmptyOriginUsProfile(0x04090409,2,0x0409,0x04090409,true,false)?0:6;
 if(n=="mixed"){f.b={0,3,33};}
 if(n=="badtag"){f.a={0,0,0};}
 if(n=="error"){f.b={-123,0,0};}
 if(n=="late"){f.late=true;}
 if(n=="clear"){f.clear=true;}
 if(n=="wrong"){f.wrong=true;}
 if(n=="i4"){f.a={0,3,-7};f.b={0,3,0x21};}
 if(n=="initialize"||n=="wrong"){SetEmptyOriginAsciiMode(f,r,original);if(n=="initialize")return r.status==0&&r.requestedOpen==1&&r.requestedConversion==0&&f.writes==2&&f.clients==1&&f.reads==4&&f.releases==1?0:1;return r.status==-35?0:2;}
 if(n=="return-mixed"){f.b={0,3,33};CaptureEmptyOriginReturn(f,r,original);return r.status==0&&f.reads==2&&f.writes==0&&f.clients==0?0:3;}
 CaptureOriginalTypedMode(f,r,original,n!="denied");
 bool ok=n=="empty"||n=="i4";
 if(ok)return r.status==0&&f.reads==2&&f.writes==0&&f.clients==0&&f.releases==1&&(n=="empty"?PairEmpty(original):PairConcrete(original))?0:4;
 return r.status!=0&&f.writes==0&&f.clients==0&&f.releases==1?0:5;
}
'''


class TypedPortablePolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.folder=Path(cls.temp.name)
        cls.source=cls.folder/'typed.cpp';cls.source.write_text(HARNESS);cls.exe=cls.folder/'typed'
        cls.compiler=shutil.which('g++') or shutil.which('clang++');assert cls.compiler
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def test_native_typed_capture_explicit_pair_and_readonly_return_boundaries(self):
        self.assertTrue((E2E/'ime_typed_origin.h').is_file(),'Missing narrow typed-origin policy')
        build=subprocess.run([self.compiler,'-std=c++17','-Wall','-Wextra','-Werror','-I',str(E2E),str(self.source),'-o',str(self.exe)],capture_output=True,timeout=30)
        self.assertEqual(build.returncode,0,build.stdout+build.stderr)
        for case in ('us-profile','empty','i4','mixed','denied','badtag','error','late','clear','initialize','wrong','return-mixed'):
            with self.subTest(case=case):self.assertEqual(subprocess.run([str(self.exe),case],capture_output=True,timeout=5).returncode,0)


def captured(empty=False):
    r=mode_fixtures.ThreadModeReceiptTests().receipt(1)
    if empty:
        r.update(beforeOpenHr=1,beforeConversionHr=1,beforeOpenType=0,beforeConversionType=0)
    return r


class TypedReceiptPolicyTests(unittest.TestCase):
    def policy(self,r,command,*,original=None,allow_empty=False):
        fn=getattr(mode,'require_typed_mode_receipt',None);self.assertTrue(callable(fn),'Missing explicit typed mode validator')
        return fn(r,command,original=original,allow_empty=allow_empty)
    def test_concrete_capture_still_delegates_exact_original_receipt(self):
        r=captured();self.assertEqual(self.policy(r,1),((0,3,1),(0,3,0x20)))
        self.assertEqual(ctypes.sizeof(mode.NativeModeReceipt),184)
    def test_empty_capture_is_an_immutable_tag_pair_without_scalar(self):
        pair=self.policy(captured(True),1,allow_empty=True)
        self.assertEqual(pair,((1,0,None),(1,0,None)));self.assertIsInstance(pair,tuple)
    def test_original_empty_requires_explicit_us_admission(self):
        with self.assertRaises(AssertionError):self.policy(captured(True),1)
    def test_mixed_unknown_hresult_boolean_and_width_are_not_empty(self):
        for changes in (dict(beforeConversionHr=0,beforeConversionType=3),dict(beforeOpenHr=0),dict(beforeOpenHr=-1),dict(beforeOpenType=8),dict(beforeOpenHr=True),dict(beforeOpen=2**32)):
            r=captured(True);r.update(changes)
            with self.subTest(changes=changes),self.assertRaises(AssertionError):self.policy(r,1,allow_empty=True)
    def test_only_empty_origin_empty_current_seeds_explicit_full_ascii_pair(self):
        r=mode_fixtures.ThreadModeReceiptTests().receipt(2);r.update(beforeOpenHr=1,beforeConversionHr=1,beforeOpenType=0,beforeConversionType=0,requestedConversion=0,afterConversion=0)
        origin=((1,0,None),(1,0,None));self.policy(r,2,original=origin)
        with self.assertRaises(AssertionError):self.policy(r,2,original=((0,3,1),(0,3,0x20)))
        for key,value in (('requestedOpen',0),('requestedConversion',0x20),('afterConversion',1),('conversionSetCalls',2),('clientId',0)):
            bad=copy.deepcopy(r);bad[key]=value
            with self.subTest(key=key),self.assertRaises(AssertionError):self.policy(bad,2,original=origin)
    def test_empty_origin_current_i4_preserves_other_conversion_bits(self):
        r=mode_fixtures.ThreadModeReceiptTests().receipt(2);self.policy(r,2,original=((1,0,None),(1,0,None)))
        r['requestedConversion']=r['afterConversion']=0
        with self.assertRaises(AssertionError):self.policy(r,2,original=((1,0,None),(1,0,None)))
    def test_command3_never_initializes_empty_current(self):
        r=mode_fixtures.ThreadModeReceiptTests().receipt(3);r.update(beforeOpenHr=1,beforeConversionHr=1,beforeOpenType=0,beforeConversionType=0)
        with self.assertRaises(AssertionError):self.policy(r,3,original=((1,0,None),(1,0,None)))
    def test_empty_origin_return_accepts_literal_mixed_valid_tags_without_any_writes(self):
        r=captured(True);r.update(beforeConversionHr=0,beforeConversionType=3,beforeConversion=33)
        self.assertEqual(self.policy(r,4,original=((1,0,None),(1,0,None))),((1,0,None),(0,3,33)))
        r['openSetCalls']=1
        with self.assertRaises(AssertionError):self.policy(r,4,original=((1,0,None),(1,0,None)))
    def test_exact_concrete_restore_remains_old_strict_path(self):
        r=mode_fixtures.ThreadModeReceiptTests().receipt(4);self.policy(r,4,original=((0,3,1),(0,3,0x21)))
        with self.assertRaises(AssertionError):self.policy(r,4,original=((0,3,1),(0,3,0x20)))
    def test_original_native_state_prefix_and_semantic_version4_survive_diagnostics(self):
        self.assertEqual(ime.NativeState.diagnosticCount.offset,553720)
        self.assertEqual(ctypes.sizeof(ime.NativeState),566016)
        self.assertIn('shared->version==4',ime.OBSERVER_SOURCE)
        self.assertIn('target->version!=4',ime.OBSERVER_SOURCE)
        self.assertIn('source->version!=4',ime.OBSERVER_SOURCE)


class TypedPublicPipelineTests(unittest.TestCase):
    def record(self,*,empty=False,returned=None):
        return complete_record(ime_fixtures.KoreanImePolicyTests().record(),empty=empty,returned=returned)
    def test_concrete_pipeline_keeps_real_composition_save_and_reopen_gates(self):
        record=self.record();self.assertTrue(ime.validate_ime_evidence(record)['imeVerified'])
        self.assertEqual(ime.require_tsf_pipeline(record)[1]['restorationDisposition'],'concrete-restored')
        record['savedText']='preexisting Korean 한글'
        with self.assertRaises(AssertionError):ime.validate_ime_evidence(record)
    def test_empty_final_mixed_tags_are_truthful_inequality_and_pending_retirement(self):
        record=self.record(empty=True,returned=((1,0,None),(0,3,33)))
        origin,facts=ime.require_tsf_pipeline(record)
        self.assertEqual(origin,'empty');self.assertFalse(facts['typedStateEqual'])
        self.assertEqual(facts['restorationDisposition'],'empty-origin-retirement-required')
        self.assertNotIn('value',record['restoration']['typedValues']['open'])
    def test_empty_equality_never_turns_into_concrete_restoration(self):
        record=self.record(empty=True);self.assertTrue(ime.require_tsf_pipeline(record)[1]['typedStateEqual'])
        record['restoration']['restorationDisposition']='concrete-restored'
        with self.assertRaises(AssertionError):ime.require_tsf_pipeline(record)
    def test_mixed_original_unknown_error_bool_and_forged_scalar_are_fatal(self):
        mutations=(lambda r:r['imeCommands'][0]['threadMode'].update(beforeOpenHr=True),
            lambda r:r['imeCommands'][0]['threadMode'].update(beforeConversionHr=0,beforeConversionType=3),
            lambda r:r['imeCommands'][0]['threadMode'].update(beforeConversionHr=-1),
            lambda r:r['imeCommands'][0]['typedValues']['open'].update(value=0),
            lambda r:r['imeCommands'][0].update(previousLayout=0x04120412),
            lambda r:r['imeCommands'][0].update(previousClsid='{11111111-1111-1111-1111-111111111111}'))
        for mutate in mutations:
            r=self.record(empty=True);mutate(r)
            with self.subTest(mutate=mutate),self.assertRaises(AssertionError):ime.require_tsf_pipeline(r)
    def test_wire_context_ack_budget_and_command_memento_cannot_change(self):
        mutations=(lambda r:r.update(imePolicyVersion=3),lambda r:r['imeCommands'][1]['nativeContext'].update(version=3),
            lambda r:r['imeCommands'][1]['nativeContext'].update(tid=99),lambda r:r['imeCommands'][1]['snapshotEvidence'].update(ackAfter=1),
            lambda r:r['imeCommands'][1]['requestedBudget'].update(counter=123),lambda r:r['imeCommands'][1].update(nativeAttemptedMask=1),
            lambda r:r['imeCommands'][0].update(nativePublicationReturn=True),lambda r:r['imeCommands'][0]['snapshotEvidence'].update(copyReturn=True))
        for mutate in mutations:
            r=self.record();mutate(r)
            with self.subTest(mutate=mutate),self.assertRaises(AssertionError):ime.require_tsf_pipeline(r)
    def test_empty_return_cannot_claim_writes_or_skip_imm_equality(self):
        for mutate in (lambda r:r['restoration']['threadMode'].update(openSetCalls=1),
            lambda r:r['restoration']['immState'].update(conversion=0),
            lambda r:r['restoration']['threadMode'].update(beforeOpenHr=-1)):
            r=self.record(empty=True);mutate(r)
            with self.subTest(mutate=mutate),self.assertRaises(AssertionError):ime.require_tsf_pipeline(r)
    def test_legacy_zero_placeholders_do_not_define_empty_original_state(self):
        r=self.record(empty=True)
        for row in r['imeCommands']:row.update(previousTsfOpen=17,previousTsfConversion=55)
        self.assertEqual(ime.require_tsf_pipeline(r)[0],'empty')
    def test_every_empty_origin_requires_retirement_even_when_typed_equal(self):
        r=self.record(empty=True)
        self.assertTrue(r['restoration']['typedStateEqual'])
        with self.assertRaises((AssertionError,KeyError)):ime.validate_ime_evidence(r)
        r['imeEngineRetirement']={'success':True,'handleClosed':True}
        with self.assertRaises((AssertionError,KeyError)):ime.validate_ime_evidence(r)
    def test_real_retirement_admission_save_gate_and_final_raw_proof_are_distinct(self):
        import os
        from test_ime_engine_retirement import Fixture
        with tempfile.TemporaryDirectory() as directory:
            f=Fixture(directory)
            with patch.dict(os.environ,f.environment,clear=True):
                from ime_typed_policy_fixtures import full_post_semantic_context
                post,metadata=full_post_semantic_context(self,f.binding,70.)
                f.record['imeSemanticContext']=post;f.record['imeKeyboardSession'].update(metadata)
                f.clock.now=max(f.clock.now,metadata['setupFinishedAt']+.1)
                f.archive();lease=f.admit();proof=f.record['imeEngineRetirement']
                record=self.record(empty=True);binding=f.binding
                record.update(windowHwnd=binding['suiteHwnd'],childHwnd=binding['childHwnd'],officePid=binding['officePid'],
                    editorTid=f.keyboard.tid,keyboardFocusHwnd=f.keyboard.focus,case=proof['admission']['case'],
                    imeKeyboardSession={'expectedNative':dict(binding)},imeEngineRetirement=proof,architecture=f.source['architecture'])
                record['imeSemanticContext']=copy.deepcopy(f.record['imeSemanticContext'])
                record['imeSetupBudget']={'deadline':record['imeSemanticContext']['setupDeadline']}
                record['imeKeyboardSession'].update(copy.deepcopy(metadata))
                machine={'x64':0x8664,'arm64':0xaa64}[record['architecture']]
                record['readiness']['source']=dict(f.source);record['readiness']['nativeMachine']=machine
                record['readiness']['profile']['component']['machine']=machine
                for key in ('nativeArchitecture','targetArchitecture'):record[key]=dict(processMachine=0,nativeMachine=machine,processArchitecture=record['architecture'],nativeArchitecture=record['architecture'])
                for row in record['imeCommands']:
                    row['nativeContext'].update(pid=record['officePid'],tid=record['editorTid'],targetHwnd=record['keyboardFocusHwnd'],rootHwnd=record['windowHwnd'])
                    row['startedAt']=proof['admission']['finishedAt']
                for event in record['events']:event.update(pid=record['officePid'],tid=record['editorTid'],hwnd=record['keyboardFocusHwnd'])
                for receipt in record['asciiEditorInputs']:
                    receipt.update(documentHwnd=record['windowHwnd'],childHwnd=record['childHwnd'])
                    for action in receipt['actions']:
                        for side in ('before','after'):action[side].update(focusHwnd=record['keyboardFocusHwnd'],editorThreadId=record['editorTid'])
                self.assertEqual(ime.require_ime_save_disposition(record,record['restoration'])['restorationDisposition'],'empty-origin-retirement-required')
                with self.assertRaises((AssertionError,ValueError,KeyError)):ime.validate_ime_evidence(record)
                record['imeEngineRetirement']=f.verify(lease)
                self.assertTrue(ime.validate_ime_evidence(record)['imeVerified'])
                with self.assertRaises((AssertionError,ValueError,KeyError)):ime.require_ime_save_disposition(record,record['restoration'])
                early=copy.deepcopy(record)
                early['imeEngineRetirement']['admission']['startedAt']=metadata['setupFinishedAt']-.01
                with self.assertRaises(AssertionError):ime.validate_ime_evidence(early)
                record['imeEngineRetirement']['admission']['finishedAt']=record['imeCommands'][0]['startedAt']+.01
                with self.assertRaises(AssertionError):ime.validate_ime_evidence(record)

    def test_original_profile_is_derived_from_the_post_native_witness_not_retirement(self):
        from ime_typed_policy_fixtures import full_post_semantic_context
        from test_ime_engine_retirement import Fixture
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup);f=Fixture(directory.name)
        post,metadata=full_post_semantic_context(self,f.binding,70.)
        record=dict(module='writer',asciiPrefix=' ime-opengeul-writer:',imeKeyboardSession=metadata,
            imeSetupBudget={'deadline':70.},imeSemanticContext=post,
            imeEngineRetirement={'admission':{'originalProfile':{'canonicalPath':'C:/foreign'}}})
        with patch.object(ime.time,'monotonic',side_effect=AssertionError('No fresh clock in historical replay')), \
             patch.object(Path,'read_bytes',side_effect=AssertionError('No file I/O in historical replay')):
            profile=ime.original_ime_profile(record)
        self.assertEqual(profile['canonicalPath'],'c:\\private-profile')
        for mutate in (lambda r:r['imeSemanticContext'].update(phase='pre'),
            lambda r:r['imeSemanticContext']['expectedNative'].update(officePid=99),
            lambda r:r['imeSemanticContext'].update(setupDeadline=61),
            lambda r:r['imeSemanticContext']['observation']['bindingBefore'].update(officeCreationTime=999),
            lambda r:r['imeSemanticContext']['observation']['nativeSnapshots']['controllerBefore']['profileDirectory']['witness'].update(canonicalPath='C:/foreign'),
            lambda r:r['imeSemanticContext'].pop('preContext'),
            lambda r:r['imeSemanticContext']['observation'].update(bodyText='lost prefix'),
            lambda r:r['imeSemanticContext']['cleanup'].update(terminated=True),
            lambda r:r['imeKeyboardSession']['semanticReadiness'][-1].update(readerFinishedAt=99.),
            lambda r:r['imeKeyboardSession'].update(setupFinishedAt=70.)):
            bad=copy.deepcopy(record);mutate(bad)
            with self.subTest(mutate=mutate),self.assertRaises((AssertionError,KeyError)):ime.original_ime_profile(bad)

    def test_post_success_native_profile_slice_cannot_replace_complete_semantic_context(self):
        from ime_typed_policy_fixtures import profile_context
        binding=dict(shellPid=10,officePid=20,suiteHwnd=30,parentHwnd=31,childHwnd=32,rootHwnd=30,
            shellCreationTime=100,officeCreationTime=101,expectedImage='C:/Suite/Office/program/soffice.bin')
        record=dict(module='writer',asciiPrefix=' ime-opengeul-writer:',
            imeKeyboardSession={'expectedNative':binding},imeSetupBudget={'deadline':60},imeSemanticContext=profile_context(binding,60))
        with self.assertRaises((AssertionError,KeyError)):ime.original_ime_profile(record)


class OriginalMementoControllerTests(unittest.TestCase):
    receipt=mode_fixtures.ThreadModeReceiptTests.receipt
    observer=mode_fixtures.ObserverModeJoinTests.observer
    def test_late_command1_ack_never_publishes_a_successful_original_memento(self):
        producer,observer,state,_=self.observer(command=1)
        observer.original_tsf=observer.original_context=None;now=[0.]
        def late(fn,seconds):
            value=fn();now[0]=6.;return value
        with patch.object(producer.time,'monotonic',side_effect=lambda:now[0]),patch.object(producer,'wait_for',side_effect=late):
            with self.assertRaises(AssertionError):observer.command(1,setup_deadline=60.)
        self.assertIsNone(observer.original_tsf);self.assertIsNone(observer.original_context)
        self.assertFalse(observer.commands[0]['success'])
    def test_original_memento_does_not_alias_mutable_json_snapshot(self):
        producer,observer,state,deadline=self.observer(command=1)
        observer.original_tsf=observer.original_context=None
        row=observer.command(1,setup_deadline=deadline)
        self.assertEqual(observer.original_tsf,((0,3,1),(0,3,32)))
        row['threadMode']['beforeConversion']=99;row['nativeContext']['tid']=99
        self.assertEqual(observer.original_tsf,((0,3,1),(0,3,32)))
        self.assertEqual(observer.original_context,(0x4f47494d,4,88,44,33,11))
    def test_final_restore_layout_read_cannot_acknowledge_after_original_deadline(self):
        producer,observer,state,_=self.observer(command=4)
        observer.original_tsf=((0,3,1),(0,3,33));now=[0.];reads=[]
        state.previousTsfConversion=33;state.previousLayout=state.previousProfileLayout=state.activeProfileLayout=0x04090409
        state.previousProfileType=state.activeProfileType=2;state.previousLanguage=state.activeLanguage=0x0409
        state.previousOpen=state.immOpen;state.previousConversion=state.immConversion;state.previousSentence=state.immSentence
        for field in ('previousClsid','previousProfile','activeClsid','activeProfile'):
            for index,char in enumerate('{00000000-0000-0000-0000-000000000000}'):getattr(state,field)[index]=ord(char)
        observer.require_restore_target=lambda:None
        def layout(tid):
            reads.append(tid)
            if len(reads)==2:now[0]=6.
            return 0x04090409
        observer.api.user.GetKeyboardLayout=layout
        with patch.object(producer.time,'monotonic',side_effect=lambda:now[0]):
            with self.assertRaises(AssertionError):observer.command(4)
        self.assertEqual(len(reads),3)  # Existing failure-snapshot retention performs the final read.
        self.assertFalse(observer.restored);self.assertFalse(observer.commands[0]['success'])
