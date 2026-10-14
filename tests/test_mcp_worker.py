"""실제 subprocess stdio로 MCP 프레임·종료·회복 경계를 검증한다(제품 실행 아님)."""
import importlib.util
import json
import os
from pathlib import Path
from unittest.mock import MagicMock,patch
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
# Unit protocol server: exercising this process never proves native product success.
SESSION_FAKE = r'''
import hashlib,json,sys,zipfile,xml.etree.ElementTree as ET
from pathlib import Path
workspace=Path(sys.argv[1]);mode=sys.argv[2];early=Path(sys.argv[3])
# Match production startup scanning: a later file cannot enter this inventory.
inventory=[{'id':'unit-owned-id','path':str(p),'format':'hwpx','sizeBytes':p.stat().st_size} for p in sorted(workspace.glob('*.hwpx'))]
docs={};journal=[];next_id=0
def text(path):
 with zipfile.ZipFile(path) as z:
  root=ET.fromstring(z.read('Contents/section0.xml'))
  return ''.join(''.join(n.itertext()) for n in root.iter() if n.tag.rsplit('}',1)[-1]=='t')
def digest(value):return hashlib.sha256((value+'\0').encode()).hexdigest()
for line in sys.stdin:
 message=json.loads(line)
 if 'id' not in message:continue
 method=message['method'];body={};error=False
 if method=='initialize':result={'protocolVersion':'2025-06-18','serverInfo':{'name':'rhwp','version':'0.8.7'}}
 elif method=='ping':result={}
 else:
  name=message['params']['name'];args=message['params']['arguments'];doc_id=args.get('docId')
  if name=='hwp_ws_list':
   body={'root':str(workspace),'count':len(inventory),'truncated':False,'entries':inventory}
   if mode=='inventory-id':body['entries'][0]['id']=''
   if mode=='inventory-bytes':body['entries'][0]['sizeBytes']+=1
   if mode=='inventory-truncated':body['truncated']=True
   if mode=='inventory-path':body['entries'][0]['path']=str(workspace/'outside.hwpx')
  elif name in ('hwp_open','hwp_ws_open'):
   path=Path(args['path']) if name=='hwp_open' else Path(next(e['path'] for e in inventory if e['id']==args['id']))
   next_id+=1;doc_id='unit-doc-'+str(next_id);docs[doc_id]={'source':path,'text':text(path)}
   body={'docId':doc_id,'source':str(path),'pageCount':1}
   if mode=='open-id':body['docId']=''
  elif name=='hwp_ws_journal':
   body={'algo':'sha256(전 페이지 본문 텍스트, 페이지 경계 0x00)','count':len(journal),'entries':journal}
   if mode=='journal-missing':body['entries'].pop()
   if mode=='journal-order':body['entries'].reverse()
   if mode=='journal-replace':journal[2]['changed']=False
   if mode=='journal-save':journal[3]['changed']=True
   if mode=='journal-error':journal[3]['isError']=True
   if mode=='journal-doc':journal[3]['docId']='foreign'
   if mode=='journal-seq':journal[3]['seq']=True
   if mode=='journal-digest':journal[2]['digestAfter']=journal[2]['digestBefore']
   if mode=='journal-rehashed-digest':
    journal[2]['digestAfter']=journal[3]['digestBefore']=journal[3]['digestAfter']='f'*64
  elif doc_id not in docs:
   body={'nextCall':{'name':'hwp_open','arguments':{'path':'<열 문서 경로>'}}};error=True
   if mode=='closed-success':error=False
   if mode=='closed-hint':body['nextCall']['name']='hwp_info'
   if mode=='closed-nohint':body={}
  else:
   doc=docs[doc_id];body={'docId':doc_id}
   if name=='hwp_doc_text':
    value=doc['text']
    if mode=='text-duplicate' and 'SESSION' in value:value+=value
    body.update(pages=[{'text':value}],truncated=False,omittedCount=0)
    if mode=='text-id':body['docId']='other'
   elif name=='hwp_doc_replace_text':
    before=digest(doc['text']);count=doc['text'].count(args['find'])
    if mode!='replace-nochange':doc['text']=doc['text'].replace(args['find'],args['replace'])
    body['replacedCount']=True if mode=='replace-bool' else count
    if mode=='replace-source':doc['source'].write_bytes(b'changed original')
    if mode=='early-output':early.write_bytes(b'unexpected write')
    journal.append(dict(seq=len(journal)+1,tool=name,docId=doc_id,digestBefore=before,digestAfter=digest(doc['text']),changed=True,isError=False))
   elif name=='hwp_doc_save':
    output=Path(args['output'])
    with zipfile.ZipFile(doc['source']) as z:
     with zipfile.ZipFile(output,'w') as saved:
      for entry in z.infolist():
       raw=z.read(entry)
       if entry.filename=='Contents/section0.xml':
        root=ET.fromstring(raw)
        for node in root.iter():
         if node.tag.rsplit('}',1)[-1]=='t':node.text='wrong' if mode=='save-xml' else doc['text']
        raw=ET.tostring(root)
       saved.writestr(entry,raw)
    body.update(output=str(output),outputFormat='hwpx',bytes=output.stat().st_size,verify={'identical':True,'diffCount':0})
    if mode=='save-verify':body['verify']['identical']=False
    if mode=='save-noverify':body['verify']=None
    if mode=='save-bytes':body['bytes']+=1
    if mode=='save-path':body['output']=str(output.with_name('foreign.hwpx'))
    if mode=='save-source':doc['source'].write_bytes(b'mutated by save')
    if mode=='save-error':error=True
    journal.append(dict(seq=len(journal)+1,tool=name,docId=doc_id,digestBefore=digest(doc['text']),digestAfter=digest(doc['text']),changed=False,isError=False))
   elif name=='hwp_close':
    body['closed']=mode!='close-false';del docs[doc_id]
    if mode=='close-id':body['docId']='other'
  result={'isError':error,'content':[{'type':'text','text':json.dumps(body)}]}
 print(json.dumps({'jsonrpc':'2.0','id':message['id'],'result':result}),flush=True)
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
    def test_installed_batch_retains_actual_response_count_and_rejects_partial_or_dead_server(self):
        from test_hwpx_oracle import package
        m=self.module();fixtures=self.folder/'fixtures';fixtures.mkdir();(fixtures/'basic.hwpx').write_bytes(package('OpenGeul fixture 한글 가나다 &amp; &lt;xml&gt; Ω 123'))
        encrypted=[]
        for format in ('hwp','hwpx'):
            path=self.folder/('protected.'+format);path.write_bytes(b'owned unit input');encrypted.append((format,path,m.sha(path)))
        diff={'identical':False,'diffCount':1};batch=[{'pageCount':1},{'error':'missing'}]
        for count,alive in ((64,True),(63,True),(64,False)):
            with self.subTest(records=count,serverAlive=alive):
                work=self.folder/(str(count)+'-'+str(alive));work.mkdir();workspace=m.prepare_workspace(work,fixtures)
                script=work/'session-server.py';script.write_text(SESSION_FAKE)
                unit_session=m.McpClient([sys.executable,str(script),str(workspace),'ok',str(work/'session-out.hwpx')],timeout=2)
                self.addCleanup(unit_session.close);client=MagicMock();client.process.poll.return_value=None if alive else 0
                client.frames_sent=30;client.frames_received=29;watch=MagicMock();watch.wait.return_value={'processId':101}
                def response(value,error=False):
                    text='\n'.join(json.dumps(row) for row in value) if isinstance(value,list) else json.dumps(value)
                    return {'id':7,'result':{'isError':error,'content':[{'type':'text','text':text}]}}
                def request(method,params=None):
                    if method=='initialize':return {'result':{'protocolVersion':'2025-06-18','serverInfo':{'name':'rhwp','version':'0.8.7'}}}
                    if method=='ping':return {'result':{}}
                    if method=='tools/list':return {'result':{'tools':[{'name':name} for name in ('hwp_info','hwp_export_text','hwp_replace_text','hwp_batch','hwp_ir_diff',
                        'hwp_open','hwp_doc_text','hwp_doc_replace_text','hwp_doc_save','hwp_close','hwp_ws_list','hwp_ws_open','hwp_ws_journal')]}}
                    name,args=params['name'],params['arguments']
                    if name=='hwp_export_text':
                        protected=Path(args['path']).name.startswith('protected.')
                        return response({'pages':[{'text':'owned encrypted unit text' if protected else m.NORMAL_TEXT}]},protected and args.get('password')!='public-unit-QA')
                    if name=='hwp_replace_text':Path(args['output']).write_bytes(package(m.WRITE_MARKER));return response({'replacedCount':1})
                    if name=='hwp_ir_diff':return response(diff)
                    if name=='hwp_batch':return response(batch,error=args.get('paths') in m.MALFORMED_PATHS)
                    return unit_session.request(method,params)
                client.request.side_effect=request;client.finish.return_value=response([{'pageCount':1}]*count)
                with patch.object(m,'password_inputs',return_value=({'expectedText':'owned encrypted unit text'},encrypted,'public-unit-QA')),patch.object(m,'stress_document',return_value={'scope':'unit'}),patch.object(m,'direct_cli',side_effect=[{'records':[diff]},{'records':batch}]):
                    if count!=64 or not alive:
                        with self.assertRaises(ValueError):m.run_cases(client,self.fake,work,fixtures,password_folder=self.folder,watch=watch,context='installed')
                    else:
                        proof=m.run_cases(client,self.fake,work,fixtures,password_folder=self.folder,watch=watch,context='installed')
                        isolation=proof['workerIsolation'];self.assertEqual(isolation['batchRecords'],64)
                        self.assertEqual(isolation['response']['checks'],{'records':64,'passed':True})
                        self.assertEqual(isolation['response']['name'],'installed-worker-batch64')
                        self.assertEqual(isolation['response'],m.result_receipt('installed-worker-batch64',client.finish.return_value,{'records':64,'passed':True}))
                        self.assertNotIn('content',isolation['response']);self.assertFalse(isolation['forcedTermination'])


    def session_unit(self, mode='ok'):
        from test_hwpx_oracle import package
        m=self.module();work=self.folder/mode;work.mkdir();fixtures=work/'fixtures';fixtures.mkdir()
        (fixtures/'basic.hwpx').write_bytes(package('OpenGeul fixture 한글 가나다 &amp; &lt;xml&gt; Ω 123'))
        self.assertTrue(callable(getattr(m,'prepare_workspace',None)),'startup 전에 소유 workspace를 준비해야 합니다')
        workspace=m.prepare_workspace(work,fixtures)
        (work/'normal.hwpx').write_bytes((fixtures/'basic.hwpx').read_bytes())
        script=work/'session-server.py';script.write_text(SESSION_FAKE)
        client=m.McpClient([sys.executable,str(script),str(workspace),mode,str(work/'session-out.hwpx')],timeout=2)
        self.addCleanup(client.close);client.request('initialize');client.notify('notifications/initialized')
        return m,work,client

    def test_public_session_workspace_stdio_contract_uses_actual_handles_owned_startup_inventory_and_saved_xml(self):
        from test_mcp_qualification import CASE_NAMES,NEW_CHECKS
        m,work,client=self.session_unit();records=[]
        self.assertTrue(callable(getattr(m,'run_session_workspace_cases',None)),'공개 session/workspace 대표 경계가 필요합니다')
        before={p:p.read_bytes() for p in (work/'normal.hwpx',work/'workspace/basic.hwpx')}
        m.run_session_workspace_cases(client,work,
            lambda name,response,checks:records.append(m.result_receipt(name,response,checks)),
            lambda name,args:client.request('tools/call',{'name':name,'arguments':args}))
        self.assertEqual([row['name'] for row in records],CASE_NAMES[17:])
        self.assertEqual([row['requestId'] for row in records],list(range(2,18)))
        self.assertEqual([row['checks'] for row in records],NEW_CHECKS)
        self.assertEqual((client.frames_sent,client.frames_received),(18,17))
        self.assertEqual(len({row['responseSha256'] for row in records}),16)
        for path,raw in before.items():self.assertEqual(path.read_bytes(),raw)
        self.assertTrue((work/'session-out.hwpx').is_file());self.assertTrue((work/'workspace-out.hwpx').is_file())

    def test_full_installed_framing_contract_has_explicit_33_records_39_sent_38_received_and_worker_id_38(self):
        from test_mcp_qualification import CASE_NAMES,CASE_IDS,NEW_CHECKS
        from test_hwpx_oracle import package
        m,work,session_client=self.session_unit('full-suite');fixtures=work/'fixtures';original=fixtures/'basic.hwpx'
        encrypted=[]
        for format in ('hwp','hwpx'):
            path=work/('protected.'+format);path.write_bytes(b'owned contract unit input');encrypted.append((format,path,m.sha(path)))
        diff={'identical':False,'diffCount':1};batch=[{'pageCount':1},{'error':'missing'}]
        # Use a real stdio session server for public lifecycle; the enclosing adapter
        # exists only in this test to exercise the complete producer's framing contract.
        class ContractClient:
            def __init__(inner):
                inner.sequence=0;inner.frames_sent=0;inner.frames_received=0;inner.process=session_client.process
            def begin(inner,method,params=None):
                inner.sequence+=1;inner.frames_sent+=1;inner.pending=(inner.sequence,method,params);return inner.sequence
            def finish(inner,token):
                request_id,method,params=inner.pending;self.assertEqual(token,request_id);inner.frames_received+=1
                def response(value,error=False):
                    raw='\n'.join(json.dumps(row) for row in value) if isinstance(value,list) else json.dumps(value)
                    return {'jsonrpc':'2.0','id':request_id,'result':{'isError':error,'content':[{'type':'text','text':raw}]}}
                if method=='initialize':return {'jsonrpc':'2.0','id':request_id,'result':{'protocolVersion':'2025-06-18','serverInfo':{'name':'rhwp','version':'0.8.7'}}}
                if method=='ping':return {'jsonrpc':'2.0','id':request_id,'result':{}}
                if method=='tools/list':return {'jsonrpc':'2.0','id':request_id,'result':{'tools':[{'name':name} for name in (
                    'hwp_info','hwp_export_text','hwp_replace_text','hwp_batch','hwp_ir_diff','hwp_open','hwp_doc_text',
                    'hwp_doc_replace_text','hwp_doc_save','hwp_close','hwp_ws_list','hwp_ws_open','hwp_ws_journal')]}}
                name,args=params['name'],params['arguments']
                if name=='hwp_export_text':
                    protected=Path(args['path']).name.startswith('protected.')
                    return response({'pages':[{'text':'owned encrypted unit text' if protected else m.NORMAL_TEXT}]},protected and args.get('password')!='public-unit-QA')
                if name=='hwp_replace_text':Path(args['output']).write_bytes(package(m.WRITE_MARKER));return response({'replacedCount':1})
                if name=='hwp_ir_diff':return response(diff)
                if name=='hwp_batch':return response([{'pageCount':1}]*64 if isinstance(args['paths'],list) and len(args['paths'])==64 else batch,args['paths'] in m.MALFORMED_PATHS)
                value=session_client.request(method,params);value['id']=request_id;return value
            def request(inner,method,params=None):return inner.finish(inner.begin(method,params))
            def notify(inner,*args):inner.frames_sent+=1
        client=ContractClient();watch=MagicMock();watch.wait.return_value={'processId':101};progress={}
        with patch.object(m,'password_inputs',return_value=({'expectedText':'owned encrypted unit text'},encrypted,'public-unit-QA')), \
                patch.object(m,'stress_document',return_value={'scope':'unit framing only'}), \
                patch.object(m,'direct_cli',side_effect=[{'records':[diff]},{'records':batch}]):
            proof=m.run_cases(client,self.fake,work,fixtures,password_folder=work,watch=watch,context='installed',progress=progress)
        self.assertEqual(proof['caseCount'],33);self.assertEqual((proof['framesSent'],proof['framesReceived']),(39,38))
        self.assertEqual([row['name'] for row in proof['cases']],CASE_NAMES)
        self.assertEqual([row['requestId'] for row in proof['cases']],CASE_IDS)
        self.assertEqual([row['checks'] for row in proof['cases'][17:]],NEW_CHECKS)
        self.assertEqual(proof['workerIsolation']['response']['requestId'],38)
        self.assertEqual(progress['lastCompletedCase'],'workspace-journal');self.assertEqual(progress['phase'],'hwp_ws_journal')
        self.assertEqual(len({row['responseSha256'] for row in [*proof['cases'],proof['workerIsolation']['response']]}),34)
        self.assertEqual(m.sha(original),m.sha(work/'normal.hwpx'));self.assertEqual(m.sha(original),m.sha(work/'workspace/basic.hwpx'))

    def test_public_session_workspace_rejects_bad_handles_text_early_writes_save_close_inventory_and_journal(self):
        for mode in ('open-id','text-id','text-duplicate','replace-bool','replace-nochange','replace-source','early-output',
                'save-xml','save-verify','save-noverify','save-bytes','save-path','save-source','save-error',
                'close-false','close-id','closed-success','closed-hint','closed-nohint',
                'inventory-id','inventory-bytes','inventory-truncated','inventory-path','journal-missing',
                'journal-order','journal-replace','journal-save','journal-error','journal-doc','journal-seq',
                'journal-digest','journal-rehashed-digest'):
            with self.subTest(mode=mode):
                m,work,client=self.session_unit(mode)
                self.assertTrue(callable(getattr(m,'run_session_workspace_cases',None)),'공개 session/workspace 대표 경계가 필요합니다')
                with self.assertRaises(ValueError):m.run_session_workspace_cases(client,work,lambda *args:None,
                    lambda name,args:client.request('tools/call',{'name':name,'arguments':args}))
                client.close()

    def test_workspace_is_prepared_once_before_server_start_and_cannot_overwrite_owned_existing_input(self):
        from test_hwpx_oracle import package
        m=self.module();fixtures=self.folder/'fixtures';fixtures.mkdir();original=fixtures/'basic.hwpx'
        original.write_bytes(package('OpenGeul fixture 한글 가나다 &amp; &lt;xml&gt; Ω 123'));before=original.read_bytes()
        self.assertTrue(callable(getattr(m,'prepare_workspace',None)),'공개 workspace startup inventory 입력을 준비해야 합니다')
        workspace=m.prepare_workspace(self.folder,fixtures)
        self.assertEqual((workspace/'basic.hwpx').read_bytes(),before);self.assertEqual(original.read_bytes(),before)
        with self.assertRaises(ValueError):m.prepare_workspace(self.folder,fixtures)

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
