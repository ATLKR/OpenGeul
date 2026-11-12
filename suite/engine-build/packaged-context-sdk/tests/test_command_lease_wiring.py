import ast
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
import test_ci_wiring as fixtures
import test_protected_command_lease as lease_fixtures


def binding():
    return {'systemDirectoryKnown':True,'wrpProtected':True,'protectionClassificationOnly':True,
      'signatureVerified':False,'linkCount':2,'handleIdentityStable':True,'freshPathStable':True,
      'bytesPeHashStable':True,'rechecks':2,'closed':True}


class Lease:
    path=r'C:\Windows\System32\cmd.exe'
    system_root=r'C:\Windows'
    record={'machine':0x8664,'bytes':512,'sha256':'4'*64}
    def __init__(self,events):
        self.events=events;self.close_count=0;self.close_ok=True
    def verify(self,*,deadline=None):
        self.events.append(('verify',deadline));return dict(self.record)
    def close(self):
        self.close_count+=1;self.events.append(('close',None));return self.close_ok
    def observation(self):
        value=binding();value['closed']=bool(self.close_count and self.close_ok);return value


class CommandLeaseWiringTests(unittest.TestCase):
    def test_unknown_raw_binding_cannot_claim_success_or_signature(self):
        import toolchain as tools
        self.assertTrue(hasattr(tools,'validate_command_observation'),'closed binding validator required')
        self.assertTrue(tools.validate_command_observation(binding(),require_closed=True)==binding())
        for key,value in (('signatureVerified',True),('protectionClassificationOnly',False),('linkCount',True),
                ('closed',False),('handleIdentityStable',False),('rawPath','SYNTHETIC')):
            bad={**binding(),key:value}
            with self.assertRaises(tools.GateFailure):
                tools.validate_command_observation(bad,require_closed=True)
    def test_private_success_requires_a_closed_bound_command(self):
        import ci_entry
        value=fixtures.success_fixture();value['commandProcessorBinding']=binding()
        self.assertTrue(ci_entry.validate_sdk_report(value,'x64','1'*64,180.,value['compileInputs']) is value)
        for replacement in (None,{**binding(),'closed':False},{**binding(),'signatureVerified':True}):
            bad=copy.deepcopy(value);bad['commandProcessorBinding']=replacement
            with self.assertRaises(ci_entry.CiFailure):
                ci_entry.validate_sdk_report(bad,'x64','1'*64,180.,value['compileInputs'])
    def test_public_schema_is_explicit_and_binding_remains_numeric_only(self):
        import ci_entry
        raw=fixtures.success_fixture();raw['commandProcessorBinding']=binding()
        outer={'completed':True,'cleanupProved':True,'forcedCleanup':False,'exitCode':0}
        report=ci_entry.public_report(ci_entry.require_context(fixtures.environment(),'x64'),outer,raw,command_binding=binding())
        self.assertEqual(report['schemaVersion'],3);self.assertEqual(report['commandProcessorBinding'],binding())
        self.assertTrue(report['sdkGatePassed']);self.assertFalse(report['qualification']);self.assertFalse(report['canService'])
        unknown=ci_entry.public_report(report['binding'],None,None)
        self.assertIsNone(unknown['commandProcessorBinding']);self.assertFalse(unknown['sdkGatePassed'])
        for key,value in (('systemDirectoryKnown',False),('closed',False),('linkCount',None),('rechecks',0)):
            result=ci_entry.public_report(report['binding'],outer,raw,command_binding={**binding(),key:value})
            self.assertFalse(result['sdkGatePassed'])
    def helper(self,*,cancel=False,close_ok=True):
        import contextlib
        import run_sdk_gate as gate
        import toolchain as tools
        import approved_launch,owned_job_win32
        events=[];lease=Lease(events);lease.close_ok=close_ok
        native_pe={'machine':0x8664,'bytes':512,'sha256':'4'*64}
        class Admission:
            manifest_sha256='1'*64
            def read_approved(self,name):return (ROOT/name).read_bytes()
            def require_root(self,root):return True
        locations={'system':r'C:\Windows','programFiles':r'C:\Program Files','programFilesX86':r'C:\Program Files (x86)',
          'sdk':r'C:\SDK','vswhere':r'C:\VS\vswhere.exe','command':lease.path,'commandRecord':lease.record,
          'controller':native_pe,'vswhereSha256':'2'*64,'commandLease':lease}
        vs={'cl':r'C:\VS\cl.exe','link':r'C:\VS\link.exe','devcmd':r'C:\VS\VsDevCmd.bat',
          'records':{'cl':native_pe,'link':native_pe},'devcmdSha256':hashlib.sha256(b'fixed').hexdigest(),
          'version':'14.44.35207','installationVersion':'17.14.19'}
        sdk={'root':r'C:\SDK','version':'10.0.26100.0','files':[]}
        original_read=tools.read;original_pe=tools.pe
        with tempfile.TemporaryDirectory() as td,contextlib.ExitStack() as stack:
            root=Path(td)
            class Runner:
                def __init__(self,api):self.calls=0
                def run(self,argv,cwd,environment,deadline):
                    events.append(('run',deadline));self.calls+=1
                    if cancel:raise KeyboardInterrupt()
                    if self.calls==1:(root/'vswhere.json').write_bytes(b'[]')
                    if self.calls in (2,3):
                        b=bytearray(60);b[:4]=b'\x64\x86\x01\x00'
                        (root/('observer.obj' if self.calls==2 else 'smoke.obj')).write_bytes(b)
                    if self.calls==4:(root/'sdk-smoke.exe').write_bytes(lease_fixtures.pe_bytes())
                    return {'completed':True,'failureCode':0}
            def read(path,*args):
                return b'fixed' if str(path)==vs['devcmd'] else original_read(path,*args)
            def pe(path,machine):
                if str(path)==lease.path:raise AssertionError('generic command PE path forbidden')
                return native_pe if str(path) in (vs['cl'],vs['link']) else original_pe(path,machine)
            def locations_for(arch,*,deadline):
                events.append(('locations',deadline));return locations
            pairs=((approved_launch,'require_admission',lambda a,r:Admission()),(gate,'sys',types.SimpleNamespace(platform='win32')),
              (gate,'_owned_root',lambda p:root),(tools,'system_locations',locations_for),(owned_job_win32,'NativeApi',lambda:object()),
              (gate,'Runner',Runner),(gate,'child_environment',lambda *a:{}),(tools,'vs_metadata',lambda b:{}),
              (tools,'installed_vs',lambda *a:vs),(tools,'installed_sdk',lambda *a:sdk),(tools,'cmd_path',lambda v:v),
              (gate,'compile_batch',lambda *a:'fixed'),(tools,'read',read),(tools,'pe',pe))
            for module,name,value in pairs:stack.enter_context(mock.patch.object(module,name,value))
            result=gate.execute('x64',ROOT/'frozen-v2',root)
        return events,lease,result
    def test_helper_revalidates_before_and_after_every_launch_then_closes_once(self):
        events,lease,result=self.helper()
        self.assertTrue(result['sdkGatePassed']);self.assertEqual(lease.close_count,1)
        runs=[i for i,e in enumerate(events) if e[0]=='run'];self.assertEqual(len(runs),5)
        for index in runs:
            self.assertEqual(events[index-1][0],'verify');self.assertEqual(events[index+1][0],'verify')
            self.assertEqual(events[index-1][1],events[index][1]);self.assertEqual(events[index+1][1],events[index][1])
        self.assertEqual(events[-1][0],'close');self.assertTrue(result['commandProcessorBinding']['closed'])
    def test_helper_cancellation_and_uncertain_close_never_pass(self):
        events,lease,result=self.helper(cancel=True)
        self.assertFalse(result['sdkGatePassed']);self.assertTrue(result['cancelled']);self.assertEqual(lease.close_count,1)
        events,lease,result=self.helper(close_ok=False)
        self.assertFalse(result['sdkGatePassed']);self.assertFalse(result['commandProcessorBinding']['closed']);self.assertEqual(lease.close_count,1)
    def test_outer_source_owns_a_separate_lease_and_closes_before_projection(self):
        tree=ast.parse((ROOT/'ci_entry.py').read_bytes());main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
        calls=[n for n in ast.walk(main) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)]
        self.assertTrue(any(n.func.attr=='close' and isinstance(n.func.value,ast.Name) and n.func.value.id=='command_lease' for n in calls))
        verifies=[n for n in calls if n.func.attr=='verify' and isinstance(n.func.value,ast.Name) and n.func.value.id=='command_lease']
        self.assertEqual(len(verifies),2)
        report=next(n for n in ast.walk(main) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='public_report')
        self.assertTrue(any(k.arg=='command_binding' for k in report.keywords))
    def outer(self,*,cancel=False,close_ok=True):
        import ci_entry as entry
        import toolchain,owned_job_win32,supervisor,contextlib
        events=[];lease=Lease(events);lease.close_ok=close_ok
        locations={'system':r'C:\Windows','programFiles':r'C:\Program Files','programFilesX86':r'C:\Program Files (x86)',
          'commandLease':lease}
        class Context:
            def require_root(self,root):return True
            def read_approved(self,name):return (ROOT/name).read_bytes()
        class Envelope:
            def run(self,*args):
                events.append(('outer-run',args[-1]))
                if cancel:raise KeyboardInterrupt()
                return {'completed':False,'cleanupProved':True,'forcedCleanup':False,'exitCode':1}
        with tempfile.TemporaryDirectory() as td,contextlib.ExitStack() as stack:
            temp=Path(td);public=temp/'public';public.mkdir()
            env={**fixtures.environment(),'GITHUB_WORKSPACE':str(ROOT.parents[2]),'RUNNER_TEMP':str(temp)}
            fake_sys=types.SimpleNamespace(flags=types.SimpleNamespace(isolated=True),dont_write_bytecode=True,
              platform='win32',version_info=(3,12),executable='synthetic-python',modules=sys.modules,path=sys.path)
            pairs=((entry,'sys',fake_sys),(entry.os,'environ',env),(entry,'check_checkout',lambda *a:True),
              (entry,'create_public_directory',lambda *a:public),(entry,'_code',lambda *a:Context()),
              (toolchain,'system_locations',lambda *a,**kw:locations),(owned_job_win32,'NativeApi',lambda:object()),
              (supervisor,'child_environment',lambda *a:{}),(entry,'EnvelopeRunner',lambda api:Envelope()))
            for module,name,value in pairs:stack.enter_context(mock.patch.object(module,name,value))
            pin=hashlib.sha256((ROOT/'ci_entry.py').read_bytes()).hexdigest()
            code=entry.main(['--architecture','x64','--expected-entry-sha256',pin,
              '--expected-bootstrap-sha256','1'*64,'--expected-approved-manifest-sha256','2'*64])
            report=json.loads((public/'report.numeric.json').read_bytes())
        return events,lease,code,report
    def test_outer_runtime_close_occurs_once_after_missing_private_result(self):
        events,lease,code,report=self.outer()
        self.assertEqual(code,1);self.assertEqual(lease.close_count,1)
        self.assertEqual([e[0] for e in events],['verify','outer-run','verify','close'])
        self.assertTrue(report['commandProcessorBinding']['closed']);self.assertFalse(report['sdkGatePassed'])
    def test_outer_runtime_cancel_or_uncertain_close_refuses_success(self):
        for options in ({'cancel':True},{'close_ok':False}):
            events,lease,code,report=self.outer(**options)
            self.assertEqual(code,1);self.assertEqual(lease.close_count,1);self.assertFalse(report['sdkGatePassed'])
            self.assertFalse(report['qualification']);self.assertFalse(report['canService'])


if __name__=='__main__':unittest.main()
