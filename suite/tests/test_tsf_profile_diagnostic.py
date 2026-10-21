"""Finite portable boundaries for a disposable profile-only observation."""
import copy
import ctypes
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

E2E = Path(__file__).resolve().parents[1]/'e2e'
sys.path.insert(0, str(E2E))
import tsf_profile_diagnostic as diag

HARNESS = r'''
#include <string>
#include "tsf_profile_diagnostic.h"
using namespace opengeul_ime;
static_assert(sizeof(ModeReceipt)==184,"fixed ABI");
struct Fake {
    ModeReceipt* receipt; int refs=0, reads=0, gets=0, n=0, fetched=0, released=0;
    bool expired=false, missing=false, clearFail=false, expireRead=false, expireRelease=false, unbalanced=false;
    Value a{1,0,0}, b{0,3,33};
    bool WithinBudget(){return !expired;}
    int32_t ExistingManager(){++refs;return 0;} bool HasManager(){return true;}
    int32_t CompartmentManager(){++refs;return 0;} bool HasCompartmentManager(){return true;}
    int32_t BeginEnumeration(){++refs;return 0;} bool HasEnumerator(){return true;}
    int32_t Next(int&key){++n;if(n<=2 && !(missing && n==2)){key=n;fetched=1;return 0;}fetched=0;return 1;}
    uint32_t Fetched(){return fetched;}
    int32_t Get(int){++gets;++refs;return 0;} bool HasCompartment(int){return true;}
    Value Read(int k){++reads;if(clearFail && k==1){receipt->cleanupStatus=-122;receipt->variantClearHr=-122;}else if(receipt->variantClearHr==NotAttempted)receipt->variantClearHr=0;
        if(expireRead){expired=true;}return k==1?a:b;}
    ReleaseCounts Release(){++released;if(expireRelease)expired=true;return {uint32_t(refs),uint32_t(refs-(unbalanced?1:0))};}
    // Deliberately no Write, client interface or manager activation methods.
};
int main(int argc,char**argv){if(argc!=2)return 90;std::string name=argv[1];ModeReceipt r{};Fake f;f.receipt=&r;
    if(name=="both-empty")f.b={1,0,0};
    if(name=="both-i4"){f.a={0,3,-17};f.b={0,3,0x21};}
    if(name=="bad-open-tag")f.a={0,0,0};
    if(name=="bad-conversion-tag")f.b={1,3,33};
    if(name=="read-error")f.a={-123,0,0};
    if(name=="missing")f.missing=true;
    if(name=="clear-failure")f.clearFail=true;
    if(name=="expired-read")f.expireRead=true;
    if(name=="expired-release")f.expireRelease=true;
    if(name=="unbalanced")f.unbalanced=true;
    if(name.rfind("profile-",0)==0){
        uint64_t layout=0x04090409,profileLayout=layout;uint32_t type=2,language=0x0409;bool clsid=true,profile=true;
        if(name=="profile-layout")layout=0xe0010412;
        if(name=="profile-type")type=1;
        if(name=="profile-language")language=0x0412;
        if(name=="profile-hkl")profileLayout=0x409;
        if(name=="profile-clsid")clsid=false;
        if(name=="profile-guid")profile=false;
        return OriginalUsProfile(layout,type,language,profileLayout,clsid,profile)==(name=="profile-us")?0:8;
    }
    CaptureTypedBoth(f,r);
    bool ok=name=="empty-open"||name=="both-empty"||name=="both-i4";
    int expected=ok?0:name=="bad-open-tag"||name=="read-error"?-29:name=="bad-conversion-tag"?-30:name=="missing"?-26:name=="clear-failure"?-37:name=="unbalanced"?-21:-20;
    if(r.status!=expected || f.released!=1 || r.releaseCalls!=1)return 1;
    if(ok && (f.reads!=2 || f.gets!=2 || r.beforeConversionHr!=f.b.hr || r.beforeConversionType!=f.b.type))return 2;
    if((name=="bad-open-tag"||name=="read-error"||name=="clear-failure"||name=="expired-read")&&f.reads!=1)return 3;
    if(name=="missing" && (f.gets||f.reads))return 4;
    if(r.openSetCalls||r.conversionSetCalls||r.clientIdCalls||r.clientId)return 5;
    return 0;
}
'''


class TypedNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.folder = Path(cls.temp.name)
        compiler = shutil.which('g++') or shutil.which('clang++')
        assert compiler, 'Portable policy compiler is required'
        source = cls.folder/'policy.cpp'
        source.write_text(HARNESS)
        cls.exe = cls.folder/'policy'
        result = subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror', '-I', str(E2E), str(source), '-o', str(cls.exe)], capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stdout+result.stderr

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def run_case(self, name):
        result = subprocess.run([str(self.exe), name], capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, (name, result.stdout, result.stderr))

    def test_empty_open_still_reads_concrete_conversion(self): self.run_case('empty-open')
    def test_both_typed_empty_remain_observations(self): self.run_case('both-empty')
    def test_concrete_values_remain_exact(self): self.run_case('both-i4')
    def test_unknown_open_tag_is_fatal(self): self.run_case('bad-open-tag')
    def test_unknown_conversion_tag_is_fatal(self): self.run_case('bad-conversion-tag')
    def test_getvalue_error_is_fatal(self): self.run_case('read-error')
    def test_missing_compartment_is_not_created(self): self.run_case('missing')
    def test_variant_cleanup_blocks_further_read(self): self.run_case('clear-failure')
    def test_original_budget_expiry_after_read_is_fatal(self): self.run_case('expired-read')
    def test_release_expiry_stays_failure(self): self.run_case('expired-release')
    def test_unbalanced_references_stay_failure(self): self.run_case('unbalanced')
    def test_original_us_profile_is_admitted(self): self.run_case('profile-us')
    def test_non_us_layout_is_rejected(self): self.run_case('profile-layout')
    def test_non_keyboard_profile_is_rejected(self): self.run_case('profile-type')
    def test_non_us_language_is_rejected(self): self.run_case('profile-language')
    def test_different_original_profile_hkl_is_rejected(self): self.run_case('profile-hkl')
    def test_nonnull_original_clsid_is_rejected(self): self.run_case('profile-clsid')
    def test_nonnull_original_profile_guid_is_rejected(self): self.run_case('profile-guid')


def receipt():
    r = diag.native_mode.receipt_dict(diag.native_mode.NativeModeReceipt())
    for name in ('status','cleanupStatus','managerHr','compartmentManagerHr','enumerationHr','enumerationNextHr','openGetHr','conversionGetHr','variantClearHr'): r[name]=0
    for name in ('managerPresent','compartmentManagerPresent','enumeratorPresent','openPresent','conversionPresent','modulePresent','lookupPresent','managerCallAttempts','releaseCalls','nextFetched'):r[name]=1
    for name in ('clientQueryHr','clientHr','openSetHr','conversionSetHr','afterOpenHr','afterConversionHr'):r[name]=diag.native_mode.NOT_ATTEMPTED
    r.update(installedMask=3,enumerationCount=3,referencesAcquired=5,referencesReleased=5,beforeOpenHr=1,beforeOpenType=0,beforeConversionHr=0,beforeConversionType=3,beforeConversion=33)
    return r


class TypedReceiptTests(unittest.TestCase):
    def test_absence_has_no_scalar_and_concrete_zero_is_distinct(self):
        r=receipt();v=diag.typed_values(r)
        self.assertEqual(v['open'],dict(hresult=1,variantType=0,kind='empty'))
        r.update(beforeOpenHr=0,beforeOpenType=3,beforeOpen=0)
        self.assertEqual(diag.typed_values(r)['open']['value'],0)
        self.assertNotEqual(v,diag.typed_values(r))

    def test_incomplete_unread_conversion_is_not_absence(self):
        r=receipt();r.update(beforeConversionHr=diag.native_mode.NOT_ATTEMPTED,beforeConversionType=0)
        with self.assertRaises(AssertionError):diag.typed_values(r)

    def test_any_write_client_or_cleanup_failure_is_rejected(self):
        for key,value in (('openSetCalls',1),('clientIdCalls',1),('openSetHr',0),('cleanupStatus',-1),('referencesReleased',4),('beforeOpenHr',True)):
            with self.subTest(key=key):
                r=receipt();r[key]=value
                with self.assertRaises(AssertionError):diag.typed_values(r)

    def test_distinct_rendered_protocol_preserves_fixed_substrate(self):
        rendered=diag.render_source('Local\\diagnostic',{'providerClsid':'{11111111-1111-1111-1111-111111111111}','profileGuid':'{22222222-2222-2222-2222-222222222222}'})
        self.assertNotIn('0x4f47494d',rendered)
        self.assertEqual(rendered.count('0x4f475044'),3)
        self.assertNotIn('SetThreadMode(',rendered)
        self.assertNotIn('CaptureThreadMode(',rendered)
        for token in ('SetValue(', 'ClearCompartment(', 'TF_CreateThreadMgr', 'SendInput('):self.assertNotIn(token,rendered)
        # Whole unchanged original source is independently pinned by the renderer.
        for name,digest in diag.ORIGINAL_PINS.items():self.assertEqual(hashlib.sha256((E2E/name).read_bytes()).hexdigest(),digest)
        for marker in ('struct State {','static bool original_target','static void observe(','extern "C" __declspec(dllexport) unsigned int ReadSnapshot'):
            self.assertIn(marker,rendered)

    def test_unknown_substrate_or_protocol_preimage_is_rejected(self):
        with patch.dict(diag.ORIGINAL_PINS,{'korean_ime_smoke.py':'0'*64}):
            with self.assertRaises(AssertionError):diag.render_source('Local\\test',{})
        with patch.object(diag.ime,'OBSERVER_SOURCE',diag.ime.OBSERVER_SOURCE.replace('source->version!=3','source->version!=8')):
            with self.assertRaises(AssertionError):diag.render_source('Local\\test',{})


class FakeObserver:
    def __init__(self,fail=None,restore_fail=False,close_fail=False,changed=True):
        self.fail,self.restore_fail,self.close_fail=fail,restore_fail,close_fail
        self.commands=[];self.activation_attempted=False;self.restoration_required=False
        self.profile_restored=False;self.closed=False;self.changed=changed
    def command(self,n,**kwargs):
        self.commands.append(n)
        if n==1:self.activation_attempted=self.restoration_required=True
        if self.fail==n:raise ValueError('primary-'+str(n))
        if n==4:
            self.restoration_required=False
            if self.restore_fail:raise RuntimeError('restore')
            self.profile_restored=True
        original=dict(open=dict(kind='empty',hresult=1,variantType=0),conversion=dict(kind='i4',hresult=0,variantType=3,value=33))
        later=copy.deepcopy(original)
        if self.changed:later['open']=dict(kind='i4',hresult=0,variantType=3,value=0)
        return dict(typedValues=original if n==1 else later,previousImmState=dict(open=0,conversion=1,sentence=8),immState=dict(open=0,conversion=1,sentence=8))
    def close(self):
        self.closed=True
        if self.close_fail:raise OSError('hook-close')


class RoundtripTests(unittest.TestCase):
    def run_roundtrip(self,observer):
        r={};diag.run_roundtrip(observer,lambda *a:None,r,100);return r
    def test_typed_difference_is_successful_observation_without_restoration_claim(self):
        f=FakeObserver();r=self.run_roundtrip(f)
        self.assertEqual(f.commands,[1,2,4]);self.assertTrue(f.closed)
        self.assertFalse(r['typedStateEqual']);self.assertTrue(r['profileAndHklRestored'])
        self.assertFalse(r['modeRestorationClaim']);self.assertFalse(r['nativeImeAcceptance'])
    def test_failed_activation_and_failed_postread_each_restore_once(self):
        for n in (1,2):
            f=FakeObserver(fail=n);r={}
            with self.assertRaisesRegex(ValueError,'primary-'+str(n)):diag.run_roundtrip(f,lambda *a:None,r,100)
            self.assertEqual(f.commands,[1,4] if n==1 else [1,2,4]);self.assertTrue(f.closed)
    def test_primary_is_preserved_with_restoration_and_hook_errors(self):
        f=FakeObserver(fail=2,restore_fail=True,close_fail=True);r={}
        with self.assertRaisesRegex(ValueError,'primary-2'):diag.run_roundtrip(f,lambda *a:None,r,100)
        self.assertIn('restore',r['restorationError']);self.assertIn('hook-close',r['hookCleanupError'])
    def test_restore_failure_invalidates_otherwise_successful_observation(self):
        f=FakeObserver(restore_fail=True)
        with self.assertRaisesRegex(RuntimeError,'restore'):self.run_roundtrip(f)
        self.assertTrue(f.closed)
    def test_hook_failure_invalidates_otherwise_successful_observation(self):
        f=FakeObserver(close_fail=True)
        with self.assertRaisesRegex(OSError,'hook-close'):self.run_roundtrip(f)
    def test_original_receipt_is_retained_when_later_phase_fails(self):
        f=FakeObserver(fail=2);r={}
        with self.assertRaises(ValueError):diag.run_roundtrip(f,lambda *a:None,r,100)
        self.assertEqual(r['originalAndActivation']['typedValues']['open']['kind'],'empty')
    def test_original_command_three_is_not_admitted(self):
        f=diag.ProfileObserver.__new__(diag.ProfileObserver)
        with self.assertRaises(AssertionError):f.command(3)
    def test_json_cap_and_exclusive_creation(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'r.json';diag.write_original(p,{'a':1})
            with self.assertRaises(FileExistsError):diag.write_original(p,{'a':2})
            with self.assertRaises(AssertionError):diag.write_original(Path(folder)/'large.json',{'x':'x'*diag.MAX_JSON})


class DiagnosticLeaseTests(unittest.TestCase):
    def lease(self):
        f=diag.EngineLease.__new__(diag.EngineLease)
        f.deadline=10**20;f.handle=80;f.rows=[];f.initial_layout=0x04090409;f.focus=40;f.tid=7
        f.shell=dict(pid=1,handleValue=70,creationTime=10,image='/suite/OpenGeul.Office.exe',waitResult=258)
        f.engine=dict(pid=2,handleValue=80,creationTime=11,image='/suite/Office/program/soffice.bin',waitResult=258)
        f.binding=dict(suiteHwnd=10,parentHwnd=20,childHwnd=30,shellPid=1,officePid=2,rootHwnd=10)
        f.process=SimpleNamespace(opengeul_editor_click_generations={(20,30,2):(2,f.engine['image'],11)})
        f.admission=None
        f.probe=SimpleNamespace(process_snapshot=lambda p:dict(f.shell),engine_snapshot=lambda h:dict(f.engine),
            keyboard_snapshot=lambda t:dict(targetLayout=f.initial_layout,keysDown=[]),close_engine=lambda h:True)
        user=SimpleNamespace(IsWindow=lambda h:True,GetAncestor=lambda h,n:10,IsChild=lambda p,c:True,GetWindowThreadProcessId=lambda h,p:7)
        f.api=SimpleNamespace(user=user,pid=lambda h:1 if h in (10,20) else 2,require_editor_focus=lambda r,c:40,
            editor_focus_snapshot=lambda *a:dict(raw='measured'))
        return f
    def test_explicit_korean_phase_guard_rejects_us_layout(self):
        f=self.lease()
        with patch.object(diag.native,'_editor_focus_snapshot_ready',return_value=40):
            f.guard(1,False)
            with self.assertRaisesRegex(AssertionError,'Korean'):f.guard(2,False)
            f.probe.keyboard_snapshot=lambda t:dict(targetLayout=0xe0010412,keysDown=[])
            f.guard(2,False)
    def test_restore_guard_allows_lost_foreground_but_requires_original_layout_after(self):
        f=self.lease();f.api.require_editor_focus=lambda *a:(_ for _ in ()).throw(AssertionError('foreign foreground'))
        f.probe.keyboard_snapshot=lambda t:dict(targetLayout=0xe0010412,keysDown=[17])
        f.guard(4,False)
        with self.assertRaisesRegex(AssertionError,'did not return'):f.guard(4,True)
        f.probe.keyboard_snapshot=lambda t:dict(targetLayout=f.initial_layout,keysDown=[])
        f.guard(4,True)
    def test_generation_replacement_and_foreign_ancestry_are_fatal(self):
        f=self.lease();f.probe.engine_snapshot=lambda h:dict(f.engine,creationTime=12)
        with self.assertRaisesRegex(AssertionError,'generation changed'):f.guard(4,False)
        f=self.lease();f.api.user.GetAncestor=lambda *a:99
        with self.assertRaisesRegex(AssertionError,'ancestry'):f.guard(4,False)
    def test_expiry_and_observation_cap_prevent_further_queries(self):
        f=self.lease();f.deadline=0
        with self.assertRaisesRegex(AssertionError,'deadline'):f.guard(4,False)
        self.assertEqual(f.rows,[])
        f=self.lease();f.rows=[{}]*12
        with self.assertRaisesRegex(AssertionError,'exceed bound'):f.guard(4,False)
    def test_handle_close_is_once_and_failure_never_claims_closed(self):
        f=self.lease();f.record={'handleClosed':False};calls=[]
        f.probe.close_engine=lambda h:calls.append(h) or False
        with self.assertRaisesRegex(AssertionError,'close failed'):f.close()
        self.assertFalse(f.record['handleClosed']);f.close();self.assertEqual(calls,[80])
    def test_bad_generation_blocks_publication_and_retry(self):
        f=diag.ProfileObserver.__new__(diag.ProfileObserver)
        f.command_attempts=set();f.commands=[]
        f.generation_guard=lambda *a:(_ for _ in ()).throw(ValueError('wrong generation'))
        f.state=lambda:(_ for _ in ()).throw(RuntimeError('no native call'))
        with self.assertRaisesRegex(ValueError,'wrong generation'):f.command(1)
        self.assertEqual(f.commands[0]['nativeCallAttempts'],0)
        with self.assertRaisesRegex(AssertionError,'cannot retry'):f.command(1)
        self.assertEqual(len(f.commands),1)


class DiagnosticCompilationTests(unittest.TestCase):
    def compile(self,root,*,fail=False,mutate=False):
        import ascii_message_preparation as prep
        from contextlib import ExitStack
        folder=root/'output';folder.mkdir()
        vs=root/'pf86/Microsoft Visual Studio/Installer/vswhere.exe';vs.parent.mkdir(parents=True);vs.write_bytes(b'vs')
        install=root/'VS';vcvars=install/'VC/Auxiliary/Build/vcvarsall.bat';vcvars.parent.mkdir(parents=True);vcvars.write_bytes(b'vcvars')
        llvm=root/'pf/LLVM/bin';llvm.mkdir(parents=True)
        for name in ('clang-cl.exe','lld-link.exe'):(llvm/name).write_bytes(b'exe')
        calls=[];pin_calls=[]
        def stage(runtime,out,name,script,budget,receipt,args):
            calls.append((name,script.read_text(),list(args)))
            receipt['stages'].append(dict(stage=name,natural=not(fail and name=='compile'),handlesClosed=True))
            if name=='discovery':(out/'discovery.stdout').write_text(str(install))
            else:
                if fail:raise AssertionError('original Job did not empty')
                (out/'ime-observer.dll').write_bytes(b'native-dll')
        def pin(tool,architecture,**kwargs):
            pin_calls.append(tool.name);kwargs['check']()
            return dict(path=str(tool),bytes=3,sha256=('f' if mutate and len(pin_calls)>2 else 'a')*64,machine=0xaa64)
        with ExitStack() as stack:
            stack.enter_context(patch.dict(diag.os.environ,{'ProgramFiles(x86)':str(root/'pf86'),'ProgramFiles':str(root/'pf')}))
            stack.enter_context(patch.object(prep,'_Runtime',return_value=object()))
            stack.enter_context(patch.object(prep,'_run_stage',side_effect=stage))
            stack.enter_context(patch.object(diag.native_arch,'observe_native_architecture',return_value={}))
            stack.enter_context(patch.object(diag.native_arch,'validate_native_architecture',return_value={'native':True}))
            stack.enter_context(patch.object(diag.native_arch,'require_native_pe',side_effect=lambda p,a:p))
            stack.enter_context(patch('native_compiler_tools.pin_native_tool',side_effect=pin))
            value=diag.compile_diagnostic(folder,'Local\\test',{'providerClsid':'{11111111-1111-1111-1111-111111111111}','profileGuid':'{22222222-2222-2222-2222-222222222222}'})
        return value,calls,pin_calls
    def test_native_direct_tools_original_jobs_and_prepost_pins(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);value,calls,pins=self.compile(root)
            self.assertEqual(value.name,'ime-observer.dll');self.assertEqual([c[0] for c in calls],['discovery','compile'])
            self.assertEqual(pins,['clang-cl.exe','lld-link.exe']*2)
            self.assertIn('"%~7" --target=aarch64-pc-windows-msvc',calls[1][1])
            self.assertIn('"%~8" /NOLOGO /DLL /MACHINE:ARM64',calls[1][1])
            self.assertEqual([p.name for p in calls[1][2][-2:]],['clang-cl.exe','lld-link.exe'])
            proof=json.loads((root/'output/compilation.json').read_text())
            self.assertTrue(proof['success']);self.assertEqual(proof['deadline']-proof['startedAt'],30)
            self.assertEqual(proof['workDeadline']-proof['startedAt'],27)
    def test_compiler_job_failure_stays_failure_with_raw_receipt(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with self.assertRaisesRegex(AssertionError,'Job did not empty'):self.compile(root,fail=True)
            proof=json.loads((root/'output/compilation.json').read_text())
            self.assertFalse(proof['success']);self.assertFalse(proof['stages'][-1]['natural'])
    def test_changed_compiler_pin_is_fatal(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(AssertionError,'tools changed'):self.compile(Path(folder),mutate=True)


class PrerequisiteBindingTests(unittest.TestCase):
    def test_korean_prerequisite_is_exact_two_fixed_job_bindings(self):
        scripts=E2E.parent/'scripts'
        old=(scripts/'ensure-korean-ime.ps1').read_bytes()
        new=(scripts/'ensure-tsf-profile-korean-ime.ps1').read_bytes()
        expected=old
        for prefix in (b"$env:GITHUB_JOB", b"$record.source.job"):
            before=prefix+b" -cne 'windows-suite'"
            after=prefix+b" -cne 'windows-tsf-profile-diagnostic'"
            self.assertEqual(old.count(before),1);self.assertEqual(new.count(after),1)
            expected=expected.replace(before,after)
        self.assertEqual(expected,new)
        self.assertIn(b"{ 1800 } else { 600 }",new)
    def test_diagnostic_workflow_has_genuine_fixed_job_and_separate_branch(self):
        import yaml
        workflow=E2E.parents[1]/'.github/workflows/office-suite-native35-tsf-diagnostic.yml'
        data=yaml.safe_load(workflow.read_text())
        self.assertEqual(data['on']['push']['branches'],['work/opengeul-office-native35-tsf-diagnostic'])
        self.assertEqual(set(data['jobs']),{'windows-tsf-profile-diagnostic'})
        job=data['jobs']['windows-tsf-profile-diagnostic'];self.assertEqual(job['runs-on'],'windows-11-arm')
        steps=job['steps'];text='\n'.join(step.get('run','') for step in steps)
        self.assertIn('./suite/scripts/ensure-tsf-profile-korean-ime.ps1',text)
        self.assertIn('./suite/scripts/prepare-native35-tsf-profile.ps1',text)
        self.assertNotIn('$env:GITHUB_JOB=',text);self.assertNotIn('unittest discover',text)
        self.assertEqual(steps[-1]['if'],'always()');self.assertTrue(steps[-1]['with']['include-hidden-files'])


class PrimaryPreservationTests(unittest.TestCase):
    def test_failed_admission_preserves_primary_when_handle_close_fails(self):
        suite=Path('/suite')
        shell=dict(pid=1,handleValue=70,waitResult=258,creationTime=10,image=str(suite/'OpenGeul.Office.exe'))
        process=SimpleNamespace(pid=1,_handle=70,opengeul_activation_binding=(1,70,shell['image'],10,258))
        probe=SimpleNamespace(process_snapshot=lambda p:shell,open_engine=lambda p:80,
            engine_snapshot=lambda h:(_ for _ in ()).throw(ValueError('original admission')),
            close_engine=lambda h:False)
        with patch.object(diag,'NativeShortcutProbe',return_value=probe):
            with self.assertRaisesRegex(ValueError,'original admission') as raised:
                diag.EngineLease(SimpleNamespace(),process,suite,10,20,30,2,100)
        self.assertIn('close failed',raised.exception.diagnosticEngineCloseError)
        self.assertFalse(raised.exception.diagnosticEngineLease['handleClosed'])
        self.assertEqual(raised.exception.diagnosticEngineLease['handleValue'],80)
    def test_result_retention_error_is_secondary_to_primary(self):
        error=ValueError('original command')
        with patch.object(diag,'write_original',side_effect=OSError('disk')):
            diag.retain_result(Path('/unused'),{},error)
        self.assertIn('disk',error.diagnosticResultReceiptError)
        self.assertIn('original command',str(error))
    def test_result_retention_error_is_fatal_without_primary(self):
        with patch.object(diag,'write_original',side_effect=OSError('disk')):
            with self.assertRaisesRegex(OSError,'disk'):diag.retain_result(Path('/unused'),{},None)


class OriginalUsAdmissionTests(unittest.TestCase):
    def test_wrong_initial_layout_is_retained_and_never_repaired(self):
        suite=Path('/suite');shell=dict(pid=1,handleValue=70,waitResult=258,creationTime=10,image=str(suite/'OpenGeul.Office.exe'))
        engine=dict(pid=2,handleValue=80,waitResult=258,creationTime=11,image=str(suite/'Office/program/soffice.bin'))
        process=SimpleNamespace(pid=1,_handle=70,opengeul_activation_binding=(1,70,shell['image'],10,258))
        class Function:
            def __call__(self,*args):return 0xe0010412
        api=SimpleNamespace(user=SimpleNamespace(GetWindowThreadProcessId=lambda *a:7,GetKeyboardLayout=Function()))
        closed=[]
        probe=SimpleNamespace(process_snapshot=lambda p:shell,open_engine=lambda p:80,engine_snapshot=lambda h:engine,
            close_engine=lambda h:closed.append(h) or True,_call=lambda fn,*a:fn(*a))
        with patch.object(diag,'NativeShortcutProbe',return_value=probe):
            with self.assertRaisesRegex(AssertionError,'original English-US HKL') as raised:
                diag.EngineLease(api,process,suite,10,20,30,2,100)
        self.assertEqual(raised.exception.diagnosticEngineLease['initialLayout'],0xe0010412)
        self.assertTrue(raised.exception.diagnosticEngineLease['handleClosed']);self.assertEqual(closed,[80])
    def test_native_profile_gate_is_before_any_activation_and_preserves_raw(self):
        code=diag.DIAGNOSTIC_COMMAND
        gate=code.index('!opengeul_ime::OriginalUsProfile(')
        self.assertLess(code.index('shared->previousProfileType=oldProfile.dwProfileType'),gate)
        self.assertLess(gate,code.index('shared->profileChangeAttempted=1'))
        self.assertIn('oldProfile.dwProfileType,oldProfile.langid,uint64_t(UINT_PTR(oldProfile.hkl))',code)
        self.assertIn('IsEqualGUID(oldProfile.clsid,GUID_NULL)',code)
        self.assertIn('IsEqualGUID(oldProfile.guidProfile,GUID_NULL)',code)


class CoherentDiagnosticFocusTests(unittest.TestCase):
    def test_ready_snapshot_uses_pure_replay_without_second_query(self):
        row={'before':{'editor':{'threadId':7}}};record={}
        api=SimpleNamespace(editor_focus_snapshot=lambda *a:row,
            require_editor_focus=lambda *a:(_ for _ in ()).throw(AssertionError('unjoined query')))
        with patch.object(diag.native,'_editor_focus_snapshot_ready',return_value=40) as replay:
            self.assertEqual(diag.wait_click_focus(api,10,30,1,2,record,10**20),40)
        self.assertEqual(replay.call_count,2)
        self.assertIs(replay.call_args_list[0].args[0],replay.call_args_list[1].args[0])
        self.assertEqual(record['diagnosticFocusReadiness']['keyboardInputs'],0)
    def test_phase_guard_replays_one_scope_without_unjoined_query(self):
        lease=DiagnosticLeaseTests().lease()
        lease.api.require_editor_focus=lambda *a:(_ for _ in ()).throw(AssertionError('unjoined query'))
        with patch.object(diag.native,'_editor_focus_snapshot_ready',return_value=40):lease.guard(1,False)
        self.assertEqual(lease.rows[-1]['scope'],{'raw':'measured'})


class ProfileResultGateTests(unittest.TestCase):
    def restored(self):
        r=dict(command=4,status=0,profileManagerHresult=0,previousProfileHresult=0,activateProfileHresult=0,activeProfileHresult=0,activateLayoutError=0,
            previousLayout=0x04090409,layout=0x04090409,previousProfileType=2,activeProfileType=2,previousLanguage=0x0409,activeLanguage=0x0409,
            previousProfileLayout=0x04090409,activeProfileLayout=0x04090409)
        r.update({key:'{00000000-0000-0000-0000-000000000000}' for key in ('previousClsid','previousProfile','activeClsid','activeProfile')})
        return r
    def test_exact_profile_return_does_not_require_numeric_mode(self):
        r=self.restored();r['typedValues']=diag.typed_values(receipt())
        self.assertEqual(diag.require_original_profile_return(r),r)
        self.assertEqual(r['typedValues']['open']['kind'],'empty')
    def test_nonzero_api_hresult_or_layout_error_is_fatal(self):
        for key in ('profileManagerHresult','previousProfileHresult','activateProfileHresult','activeProfileHresult','activateLayoutError'):
            r=self.restored();r[key]=1
            with self.subTest(key=key):
                with self.assertRaisesRegex(AssertionError,'API failed'):diag.require_original_profile_return(r)
    def test_wrong_original_or_returned_identity_is_fatal(self):
        for key,value in (('previousLayout',0x409),('activeProfileType',1),('previousLanguage',0x0412),('activeClsid','{11111111-1111-1111-1111-111111111111}')):
            r=self.restored();r[key]=value
            with self.subTest(key=key):
                with self.assertRaises(AssertionError):diag.require_original_profile_return(r)


class CommandGuardJoinTests(unittest.TestCase):
    def row(self):
        return dict(command=1,after=False,sourceCall='EngineLease.guard',observationIndex=0,shell={'pid':1},engine={'pid':2},scope={'focus':{'pid':2,'threadId':7}})
    def test_command_before_row_is_replayed_without_native_query(self):
        row=self.row()
        with patch.object(diag.native,'_editor_focus_snapshot_ready',return_value=40) as replay:
            self.assertIs(diag.require_command_guard(row,1,10,30,2,7,40),row)
        self.assertIs(replay.call_args.args[0],row['scope'])
    def test_stale_wrong_command_after_or_source_rows_fail(self):
        for key,value in (('command',2),('after',True),('sourceCall','other'),('observationIndex',12)):
            r=self.row();r[key]=value
            with self.subTest(key=key):
                with self.assertRaises(AssertionError):diag.require_command_guard(r,1,10,30,2,7,40)
    def test_wrong_focus_identity_fails_even_when_replay_returns_expected_hwnd(self):
        row=self.row();row['scope']['focus']['pid']=3
        with patch.object(diag.native,'_editor_focus_snapshot_ready',return_value=40):
            with self.assertRaises(AssertionError):diag.require_command_guard(row,1,10,30,2,7,40)


class ControllerCommandBoundaryTests(unittest.TestCase):
    def observer(self,command=1):
        f=diag.ProfileObserver.__new__(diag.ProfileObserver)
        f.root,f.child,f.pid,f.tid,f.focus=10,30,2,7,40
        f.expected_profile=dict(providerClsid='{11111111-1111-1111-1111-111111111111}',profileGuid='{22222222-2222-2222-2222-222222222222}')
        f.command_attempts=set();f.commands=[];f.activation_attempted=False;f.profile_restored=False
        f.mapping=bytearray(ctypes.sizeof(diag.NativeState))
        calls=[]
        f.dll=SimpleNamespace(PublishCommand=lambda *a:calls.append('publish') or 1)
        f.api=SimpleNamespace(user=SimpleNamespace(SendMessageTimeoutW=lambda *a:calls.append('send') or 1))
        f.require_target=lambda:(_ for _ in ()).throw(AssertionError('unjoined inherited query'))
        f.require_restore_target=lambda:None
        before=CommandGuardJoinTests().row();before['command']=command
        f.generation_guard=lambda n,after:before if not after else {'after':True}
        state=SimpleNamespace(ack=command,status=0,tsfCaptured=1,immContextPresent=1,immConversionSucceeded=1,activeProfileType=1,
            activeLanguage=0x0412,activeClsid=(f.expected_profile['providerClsid']+'\0').encode('utf-16-le'),
            activeProfile=(f.expected_profile['profileGuid']+'\0').encode('utf-16-le'),
            snapshotEvidence=dict(stable=True,ackBefore=command,ackAfter=command))
        f.state=lambda:state
        row=dict(threadMode=receipt(),commandRejection={'count':0},modeDeadlineCounter=77,modeCounterFrequency=1000,layout=0xe0010412,
            profileManagerHresult=0,previousProfileHresult=0,activateProfileHresult=0,activeProfileHresult=0,activateLayoutError=0)
        f._command_snapshot=lambda state,n:copy.deepcopy(row)
        return f,calls,before,row
    def test_coherent_guard_reaches_one_command_without_inherited_gui_query(self):
        f,calls,before,row=self.observer()
        with patch.object(diag.native,'_editor_focus_snapshot_ready',return_value=40),patch.object(diag.native_mode,'counter_budget',return_value=(77,1000)):
            result=f.command(1)
        self.assertEqual(calls,['publish','send']);self.assertTrue(result['success'])
        self.assertIs(result['guardBefore'],before)
    def test_wrong_guard_row_prevents_publication(self):
        f,calls,before,row=self.observer();before['command']=2
        with self.assertRaisesRegex(AssertionError,'fresh before-guard'):f.command(1)
        self.assertEqual(calls,[]);self.assertEqual(f.commands[0]['nativeCallAttempts'],0)
    def test_bad_profile_hresult_does_not_set_restored(self):
        f,calls,before,row=self.observer(4);row['activateProfileHresult']=1
        with patch.object(diag.native_mode,'counter_budget',return_value=(77,1000)):
            with self.assertRaisesRegex(AssertionError,'profile API failed'):f.command(4)
        self.assertEqual(calls,['publish','send']);self.assertFalse(f.profile_restored)
        self.assertFalse(f.commands[0]['success'])


class DiagnosticCleanCloseTests(unittest.TestCase):
    def context(self,mode='clean'):
        clock=[0.0];state={'requested':False};calls=[]
        process=SimpleNamespace(pid=1);record=dict(windowHwnd=10,childHwnd=30,shellPid=1,officePid=2)
        def live(hwnd):return not state['requested'] or mode!='clean'
        def request(hwnd,pid):calls.append((hwnd,pid));state['requested']=True
        user=SimpleNamespace(IsWindow=live,GetAncestor=lambda h,n:10,IsChild=lambda *a:True,GetWindow=lambda h,n:10 if h==50 else 0)
        api=SimpleNamespace(user=user,pid=lambda h:2 if h==30 else 1,request_close=request,
            windows=lambda p:[50] if mode=='modal' else [],title=lambda h:'OpenGeul Calc',class_name=lambda h:'#32770')
        shell,engine={'pid':1},{'pid':2}
        lease=SimpleNamespace(handle=80,shell=shell,engine=engine,
            probe=SimpleNamespace(process_snapshot=lambda p:shell,engine_snapshot=lambda h:engine))
        return api,process,record,lease,calls,lambda:clock[0],lambda t:clock.__setitem__(0,clock[0]+t)
    def test_clean_copy_closes_once_without_waiting_for_prompt(self):
        api,process,record,lease,calls,clock,pause=self.context()
        with patch('generated_calc_close.verify_saved_calc_copy') as verify:
            value=diag.close_clean_diagnostic_copy(api,process,10,30,record,object(),lease,clock=clock,pause=pause)
        self.assertEqual(calls,[(10,1)]);self.assertTrue(value['frameClosed']);self.assertEqual(value['cleanupClickCount'],0)
        self.assertEqual(verify.call_count,2)
    def test_unexpected_modal_is_retained_without_click_or_second_close(self):
        api,process,record,lease,calls,clock,pause=self.context('modal')
        with patch('generated_calc_close.verify_saved_calc_copy'):
            with self.assertRaisesRegex(AssertionError,'Unexpected modal'):diag.close_clean_diagnostic_copy(api,process,10,30,record,object(),lease,clock=clock,pause=pause)
        value=record['diagnosticDocumentClose'];self.assertEqual(calls,[(10,1)]);self.assertEqual(value['cleanupClickCount'],0)
        self.assertEqual(value['observations'][0]['modals'][0]['hwnd'],50);self.assertFalse(value['frameClosed'])
    def test_persistent_live_window_uses_one_original_deadline(self):
        api,process,record,lease,calls,clock,pause=self.context('live')
        with patch('generated_calc_close.verify_saved_calc_copy'):
            with self.assertRaisesRegex(AssertionError,'original deadline|observation bound'):diag.close_clean_diagnostic_copy(api,process,10,30,record,object(),lease,clock=clock,pause=pause)
        self.assertEqual(calls,[(10,1)]);self.assertLessEqual(len(record['diagnosticDocumentClose']['observations']),201)
        self.assertFalse(record['diagnosticDocumentClose']['frameClosed'])
    def test_final_close_timestamp_cannot_qualify_at_deadline(self):
        api,process,record,lease,calls,clock,pause=self.context()
        ticks=iter([0.0]*7+[20.0])
        with patch('generated_calc_close.verify_saved_calc_copy'):
            with self.assertRaisesRegex(AssertionError,'original deadline'):
                diag.close_clean_diagnostic_copy(api,process,10,30,record,object(),lease,clock=lambda:next(ticks),pause=pause)
        self.assertEqual(calls,[(10,1)]);self.assertFalse(record['diagnosticDocumentClose']['frameClosed'])
    def test_bad_generation_or_token_prevents_close(self):
        for bad in ('generation','token'):
            api,process,record,lease,calls,clock,pause=self.context()
            if bad=='generation':lease.probe.engine_snapshot=lambda h:{'pid':3}
            with patch('generated_calc_close.verify_saved_calc_copy',side_effect=ValueError('bad token') if bad=='token' else None):
                with self.assertRaises((AssertionError,ValueError)):diag.close_clean_diagnostic_copy(api,process,10,30,record,object(),lease,clock=clock,pause=pause)
            self.assertEqual(calls,[])
    def test_foreign_child_prevents_close(self):
        api,process,record,lease,calls,clock,pause=self.context();api.pid=lambda h:3 if h==30 else 1
        with patch('generated_calc_close.verify_saved_calc_copy'):
            with self.assertRaises(AssertionError):diag.close_clean_diagnostic_copy(api,process,10,30,record,object(),lease,clock=clock,pause=pause)
        self.assertEqual(calls,[])


class OriginalThreadAdmissionTests(unittest.TestCase):
    def test_zero_tid_never_queries_current_thread_layout(self):
        suite=Path('/suite');shell=dict(pid=1,handleValue=70,waitResult=258,creationTime=10,image=str(suite/'OpenGeul.Office.exe'))
        engine=dict(pid=2,handleValue=80,waitResult=258,creationTime=11,image=str(suite/'Office/program/soffice.bin'))
        process=SimpleNamespace(pid=1,_handle=70,opengeul_activation_binding=(1,70,shell['image'],10,258))
        keyboard=[];closed=[]
        api=SimpleNamespace(user=SimpleNamespace(GetWindowThreadProcessId=lambda *a:0,GetKeyboardLayout=lambda tid:keyboard.append(tid)))
        probe=SimpleNamespace(process_snapshot=lambda p:shell,open_engine=lambda p:80,engine_snapshot=lambda h:engine,close_engine=lambda h:closed.append(h) or True)
        with patch.object(diag,'NativeShortcutProbe',return_value=probe):
            with self.assertRaisesRegex(AssertionError,'positive native thread') as raised:diag.EngineLease(api,process,suite,10,20,30,2,100)
        self.assertEqual(keyboard,[]);self.assertEqual(closed,[80])
        self.assertEqual(raised.exception.diagnosticEngineLease['initialThreadId'],0)
        self.assertNotIn('initialLayout',raised.exception.diagnosticEngineLease)


class ReturnedPrerequisiteGateTests(unittest.TestCase):
    def returned_gate(self,job,*,change=None):
        # Execute the actual isolated readback predicate, not the installer/worker.
        # Scalars mirror the source-bound 39586057796 ARM readiness boundary.
        script=(E2E.parent/'scripts/ensure-tsf-profile-korean-ime.ps1').read_text()
        begin="        if ($record.source.sourceCommit -cne $head[0] -or"
        self.assertEqual(script.count(begin),1)
        gate=script[script.index(begin):].split('\n    } catch {',1)[0]
        helper_begin='function Get-SuiteKoreanUtcTicks('
        helper=script[script.index(helper_begin):].split('\nfunction Test-SuiteKoreanLegacyCollectorWindow',1)[0]
        context=dict(sourceCommit='b2a5c44aa693efc6bf6697d9411989e9223a0166',architecture='arm64',nativeMachine=0xaa64,
            preparationDeadline=dict(budgetSeconds=1800,startedUtc='2026-10-21T10:42:37.3920755Z',expiresUtc='2026-10-21T11:12:37.3920755Z'))
        record=dict(source=dict(sourceCommit=context['sourceCommit'],job=job,architecture='arm64'),
            preparationDeadline=copy.deepcopy(context['preparationDeadline']),nativeMachine=0xaa64,controllerMachine=0,
            profile=dict(registered=True,component=dict(machine=0xaa64)),suiteOnly=True,productInputVerified=False,
            storeQualified=False,capabilityAfter='Installed',restartNeeded=False,userLanguageConfigured=True)
        if change is not None:change(record)
        harness="""param([string]$Fixture)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$fixtureValue=Get-Content -LiteralPath $Fixture -Raw | ConvertFrom-Json
$record=$fixtureValue.record
$head=@($fixtureValue.context.sourceCommit)
$Architecture=$fixtureValue.context.architecture
$deadline=$fixtureValue.context.preparationDeadline
$controllerHost=[pscustomobject]@{nativeMachine=$fixtureValue.context.nativeMachine}
"""+helper+"\ntry {\n"+gate+"\nWrite-Output 'accepted'; exit 0\n} catch { Write-Output 'rejected'; exit 17 }\n"
        parser=shutil.which('pwsh')
        self.assertIsNotNone(parser,'Existing PowerShell capability is required; no silent skip')
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder);(path/'gate.ps1').write_text(harness)
            (path/'fixture.json').write_text(__import__('json').dumps(dict(record=record,context=context)))
            result=subprocess.run([parser,'-NoProfile','-NonInteractive','-File',str(path/'gate.ps1'),'-Fixture',str(path/'fixture.json')],capture_output=True,text=True,timeout=10)
        self.assertIn(result.returncode,(0,17),result.stdout+result.stderr)
        self.assertEqual(result.stderr,'')
        return result.returncode,result.stdout.strip()
    def test_actual_shaped_diagnostic_job_is_accepted(self):
        self.assertEqual(self.returned_gate('windows-tsf-profile-diagnostic'),(0,'accepted'))
    def test_original_suite_job_is_rejected(self):
        self.assertEqual(self.returned_gate('windows-suite'),(17,'rejected'))
    def test_arbitrary_job_is_rejected(self):
        self.assertEqual(self.returned_gate('unrelated-job'),(17,'rejected'))
    def test_other_original_readback_predicates_still_reject_mismatch(self):
        mutations=(lambda r:r['source'].__setitem__('sourceCommit','0'*40),
            lambda r:r['preparationDeadline'].__setitem__('budgetSeconds',1801),
            lambda r:r.__setitem__('controllerMachine',0x8664),lambda r:r.__setitem__('capabilityAfter','NotPresent'),
            lambda r:r.__setitem__('restartNeeded',True),lambda r:r['profile'].__setitem__('registered',False))
        for change in mutations:
            with self.subTest(change=mutations.index(change)):
                self.assertEqual(self.returned_gate('windows-tsf-profile-diagnostic',change=change),(17,'rejected'))


if __name__=='__main__':unittest.main()
