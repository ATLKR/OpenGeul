"""실제 subprocess stdio로 MCP 프레임·종료·회복 경계를 검증한다(제품 실행 아님)."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
ROOT=Path(__file__).resolve().parents[1]
FAKE=r'''
import json,sys,time,os,subprocess
from pathlib import Path
mode=sys.argv[1]
for line in sys.stdin:
 message=json.loads(line)
 if 'id' not in message:continue
 if mode=='eof':break
 if mode=='stall':time.sleep(5);continue
 if mode=='invalid':print('not-json',flush=True);continue
 if mode=='duplicate':print('{"jsonrpc":"2.0","id":1,"id":2,"result":{}}',flush=True);continue
 if mode=='large':print('x'*4096,flush=True);continue
 if mode=='stderr':sys.stderr.write('x'*262144);sys.stderr.flush()
 result={} if message['method']=='ping' else {'ok':True,'sequence':message['id']}
 if message['method']=='initialize':result={'protocolVersion':'2025-06-18','serverInfo':{'name':'rhwp','version':'0.8.7'},'capabilities':{'tools':{}}}
 if message['method']=='tools/call':result={'isError':False,'content':[{'type':'text','text':'{"pageCount":1,"format":"HWPX"}'}]}
 if mode=='fault' and message['method']=='tools/call' and message.get('params',{}).get('name')=='hwp_batch':
  child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(15)'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  Path(sys.argv[2]).write_text(json.dumps({'workerPid':child.pid,'ownerPid':os.getpid()}))
  child.wait(timeout=20)
  result={'isError':True,'content':[{'type':'text','text':'owned worker intentionally terminated'}]}
 print(json.dumps({'jsonrpc':'2.0','id':message['id']+1 if mode=='wrong-id' else message['id'],'result':result}),flush=True)
'''
class McpWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name);self.fake=self.folder/'fake.py';self.fake.write_text(FAKE)
    def module(self):
        path=ROOT/'e2e/mcp_worker.py';self.assertTrue(path.is_file(),'실제 MCP qualification harness가 필요합니다')
        spec=importlib.util.spec_from_file_location('mcp_worker_tested',path)
        m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m);return m
    def client(self,mode='ok',**kwargs):
        client=self.module().McpClient([sys.executable,str(self.fake),mode],timeout=.35,**kwargs)
        self.addCleanup(client.close);return client
    def test_real_subprocess_initialize_notification_ping_and_sequential_ids(self):
        client=self.client();response=client.request('initialize',{'protocolVersion':'2025-06-18'})
        self.assertEqual(response['result']['serverInfo']['name'],'rhwp')
        client.notify('notifications/initialized')
        self.assertEqual(client.request('ping')['id'],2)
        self.assertEqual(client.request('ping')['id'],3)
        self.assertEqual(client.frames_received,3)
        self.assertIsNone(client.process.poll())
    def test_wrong_id_duplicate_keys_malformed_json_and_eof_reject_without_deadlock(self):
        for mode in ('wrong-id','duplicate','invalid','eof'):
            with self.subTest(mode=mode):
                client=self.client(mode)
                with self.assertRaises(ValueError):client.request('ping')
                client.close();self.assertIsNotNone(client.process.poll())
    def test_timeout_closes_only_its_server_and_does_not_block(self):
        client=self.client('stall');started=time.monotonic()
        with self.assertRaises(TimeoutError):client.request('ping')
        client.close();self.assertLess(time.monotonic()-started,2)
        self.assertIsNotNone(client.process.poll())
    def test_response_frame_cap_is_checked_before_json_parse(self):
        client=self.client('large',max_frame=1024)
        with self.assertRaises(ValueError):client.request('ping')
    def test_stderr_burst_cannot_fill_pipe_or_deadlock_jsonrpc(self):
        client=self.client('stderr');self.assertEqual(client.request('ping')['id'],1)
    def test_pending_request_cannot_be_replaced_by_another(self):
        client=self.client();token=client.begin('ping')
        with self.assertRaises(ValueError):client.begin('ping')
        self.assertEqual(client.finish(token)['id'],1)
        self.assertEqual(client.request('ping')['id'],2)
    def test_request_frame_bound_blocks_write_and_password_remains_stdin_only(self):
        client=self.client(max_frame=1024)
        with self.assertRaises(ValueError):client.begin('tools/call',{'password':'x'*2048})
        secret='synthetic-QA-password'
        result=client.request('tools/call',{'name':'hwp_info','arguments':{'password':secret}})
        self.assertNotIn(secret,' '.join(client.command));self.assertFalse(result['result']['isError'])
    def test_tool_json_and_ndjson_are_preserved_without_changing_nonzero_semantics(self):
        m=self.module()
        def response(text):return {'result':{'isError':False,'content':[{'type':'text','text':text}]}}
        self.assertEqual(m.tool_records(response('{"identical":false,"diffCount":1}')),[{'identical':False,'diffCount':1}])
        self.assertEqual(m.tool_records(response('{\n  "identical": false,\n  "diffCount": 1\n}')),[{'identical':False,'diffCount':1}])
        rows=m.tool_records(response('{"source":"a"}\n{"source":"b","error":"missing","exitClass":"runtime"}'))
        self.assertEqual(len(rows),2);self.assertIn('error',rows[1])
        self.assertFalse(response('{}')['result']['isError'])
    def test_tool_data_requires_usable_pure_json_and_consistent_structured_content(self):
        m=self.module()
        for result in ({'isError':True,'content':[{'type':'text','text':'failed'}]},
                       {'isError':False,'content':[{'type':'text','text':'debug\n{}'}]},
                       {'isError':False,'content':[{'type':'image','data':'ignored'}]},
                       {'isError':False,'content':[{'type':'text','text':'{}'}],'structuredContent':{'changed':True}}):
            with self.subTest(result=result),self.assertRaises(ValueError):m.tool_records({'result':result})
    def test_summary_hashes_frames_and_never_records_password_or_raw_environment(self):
        m=self.module();secret='synthetic-QA-password'
        summary=m.result_receipt('password-info',{'id':1,'result':{'content':[{'type':'text','text':secret}],'isError':False}}, {'passed':True})
        self.assertNotIn(secret,json.dumps(summary));self.assertEqual(summary['checks'],{'passed':True})
        self.assertRegex(summary['responseSha256'],r'^[0-9a-f]{64}$')
    def test_malformed_paths_are_exercised_as_server_errors_not_silently_filtered(self):
        m=self.module();self.assertEqual(m.MALFORMED_PATHS,[None,[],[1],'a.hwpx'])


    def worker(self):
        path=self.folder/'private'/'Tools'/'rhwp.exe';path.parent.mkdir(parents=True);path.write_bytes(b'private byte identity')
        server={'processId':100,'createdFileTime':1000,'sourceCommit':'a'*40,'sourceRun':'12','runAttempt':'1'}
        record={'processId':101,'createdFileTime':1001,'imagePath':str(path.resolve()),'sha256':'b'*64,
                'architecture':'arm64','peMachine':0xAA64,'processMachine':0,'nativeMachine':0xAA64,'native':True,
                'runningAtInspection':True,'packageFullName':None,
                'argv':[str(path.resolve()),'--opengeul-com-worker','--clsid','12345678-1234-1234-1234-123456789abc'],
                'sourceCommit':'a'*40,'sourceRun':'12','runAttempt':'1'}
        return path,server,record
    def test_private_worker_binding_accepts_broker_parent_without_using_ancestry(self):
        m=self.module();path,server,record=self.worker();record['parentProcessId']=999
        proof=m.qualify_worker(record,server,path,'b'*64,'arm64',context='portable')
        self.assertEqual(proof['processId'],101);self.assertEqual(proof['classId'],'12345678-1234-1234-1234-123456789abc')
    def test_wrong_path_hash_pid_birth_native_machine_or_run_blocks_worker_termination(self):
        m=self.module();path,server,record=self.worker()
        changes=[{'processId':100},{'processId':True},{'createdFileTime':999},{'sha256':'c'*64},
                 {'imagePath':str(self.folder/'other.exe')},{'processMachine':0x8664},{'nativeMachine':0x8664},
                 {'nativeMachine':True},{'peMachine':0x8664},{'sourceRun':'13'},{'runAttempt':'2'},
                 {'sourceCommit':'c'*40},{'runningAtInspection':False}]
        for change in changes:
            with self.subTest(change=change),self.assertRaises(ValueError):
                m.qualify_worker({**record,**change},server,path,'b'*64,'arm64',context='portable')
    def test_bootstrap_argv_rejects_document_password_options_and_packaged_class_in_private_scope(self):
        m=self.module();path,server,record=self.worker()
        for arguments in ([str(path),'info','document.hwpx'], record['argv']+['--password','secret'],
                          record['argv'][:-1]+[m.FIXED_CLSID], record['argv'][:-1]+['foreign-guid']):
            with self.subTest(arguments=arguments),self.assertRaises(ValueError):
                m.qualify_worker({**record,'argv':arguments},server,path,'b'*64,'arm64',context='portable')
    def test_installed_worker_requires_actual_fixed_class_and_same_package_identity(self):
        m=self.module();path,server,record=self.worker();record.update(packageFullName='own-package',argv=record['argv'][:-1]+[m.FIXED_CLSID])
        self.assertEqual(m.qualify_worker(record,server,path,'b'*64,'arm64',context='installed',package_full_name='own-package')['packageFullName'],'own-package')
        for change in ({'packageFullName':'foreign-package'},{'argv':record['argv'][:-1]+['12345678-1234-1234-1234-123456789abc']}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                m.qualify_worker({**record,**change},server,path,'b'*64,'arm64',context='installed',package_full_name='own-package')


    def test_direct_cli_nonzero_json_results_are_preserved_and_never_put_password_in_argv(self):
        m=self.module();script=self.folder/'direct.py'
        script.write_text("import sys,json;print(json.dumps({'stdinBytes':len(sys.stdin.buffer.read()),'identical':False}));sys.exit(3)")
        result=m.direct_cli([sys.executable,str(script)],cwd=self.folder,stdin=b'synthetic-password\n',expected_code=3)
        self.assertEqual(result['exitCode'],3);self.assertEqual(result['records'][0]['stdinBytes'],19)
        self.assertNotIn('synthetic-password',json.dumps(result))
    def test_direct_cli_empty_invalid_or_unexpected_exit_is_rejected(self):
        m=self.module();script=self.folder/'direct.py'
        for program in ("import sys;sys.exit(1)","print('debug')","print('{}')"):
            script.write_text(program)
            with self.subTest(program=program),self.assertRaises(ValueError):
                m.direct_cli([sys.executable,str(script)],cwd=self.folder,expected_code=3)
    def test_fault_recovery_keeps_same_server_and_next_tool_call_usable(self):
        m=self.module();client=self.client();actions=[]
        class Watch:
            def wait(inner,owner):self.assertIs(owner,client);return {'processId':456}
            def terminate(inner,record):actions.append(record['processId'])
        proof=m.fault_recovery(client,Watch(),'owned.hwpx')
        self.assertEqual(actions,[456]);self.assertTrue(proof['sameServerAlive'])
        self.assertTrue(proof['nextToolCallPassed']);self.assertEqual(client.process.pid,proof['serverProcessId'])
    def test_fault_recovery_never_terminates_unbound_worker(self):
        m=self.module();client=self.client()
        class Watch:
            def wait(inner,owner):raise ValueError('foreign worker')
            def terminate(inner,record):self.fail('검증하지 않은 작업자를 종료하면 안 됩니다')
        with self.assertRaises(ValueError):m.fault_recovery(client,Watch(),'owned.hwpx')
    def test_worker_fault_premature_server_eof_is_not_recovery(self):
        m=self.module();client=self.client('eof')
        class Watch:
            def wait(inner,owner):return {'processId':456}
            def terminate(inner,record):pass
        with self.assertRaises(ValueError):m.fault_recovery(client,Watch(),'owned.hwpx')


    def test_actual_fake_worker_subprocess_crash_keeps_real_fake_server_usable(self):
        import signal
        m=self.module();pid_file=self.folder/'owned-worker.json'
        client=m.McpClient([sys.executable,str(self.fake),'fault',str(pid_file)],timeout=2)
        self.addCleanup(client.close)
        class Watch:
            def wait(inner,owner):
                deadline=time.monotonic()+2
                while not pid_file.exists() and time.monotonic()<deadline:time.sleep(.01)
                value=json.loads(pid_file.read_text());self.assertEqual(value['ownerPid'],client.process.pid)
                return {'processId':value['workerPid']}
            def terminate(inner,record):
                self.assertEqual(record['processId'],json.loads(pid_file.read_text())['workerPid'])
                self.assertNotEqual(record['processId'],client.process.pid)
                os.kill(record['processId'],signal.SIGKILL)
        proof=m.fault_recovery(client,Watch(),'owned.hwpx')
        self.assertTrue(proof['sameServerAlive']);self.assertTrue(proof['nextToolCallPassed'])
        self.assertEqual(client.process.pid,proof['serverProcessId']);self.assertIsNone(client.process.poll())
    def test_stress_fixture_keeps_original_mimetype_and_bytes_separate_from_print_baseline(self):
        import zipfile
        m=self.module();original=self.folder/'basic.hwpx'
        with zipfile.ZipFile(original,'w') as archive:
            archive.writestr('mimetype','application/hwp+zip',compress_type=zipfile.ZIP_STORED)
            archive.writestr('Contents/header.xml','<header/>')
            archive.writestr('Contents/content.hpf','<package/>')
            archive.writestr('Contents/section0.xml','<sec xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"><hp:p id="1"><hp:run><hp:t>OpenGeul fixture</hp:t></hp:run></hp:p></sec>')
        before=original.read_bytes();output=self.folder/'stress.hwpx'
        proof=m.stress_document(original,output)
        self.assertEqual(original.read_bytes(),before);self.assertEqual(proof['addedSyntheticParagraphs'],1500)
        with zipfile.ZipFile(output) as archive:
            self.assertEqual(archive.infolist()[0].filename,'mimetype')
            self.assertEqual(archive.infolist()[0].compress_type,zipfile.ZIP_STORED)

if __name__=='__main__':unittest.main()
