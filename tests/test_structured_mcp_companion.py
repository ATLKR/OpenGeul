"""Portable companion contract units; no native product success is simulated."""
import importlib.util
import io,json,sys,tempfile,unittest,zipfile
from pathlib import Path
FOLDER=Path(__file__).resolve().parents[1]/'e2e/structured_cli_mcp'
sys.path.insert(0,str(FOLDER))

def module(name):
    path=FOLDER/(name+'.py')
    if not path.is_file():return None
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m

class DraftTests(unittest.TestCase):
    def setUp(self):
        self.runner=module('valid_companion');self.oracle=module('structured_oracle')
        self.assertIsNotNone(self.runner,'Separate structured companion producer/validator is required')
        self.assertIsNotNone(self.oracle,'Independent bounded structure/render oracle is required')
        self.expected=json.loads((FOLDER/'expected.json').read_bytes())
    def test_partial_receipt_never_carries_internal_schema_or_success(self):
        proof={'passed':True,'cases':[],'_evidenceRoot':'PRIVATE-PATH','_toolDefinitions':['PRIVATE-BODY']}
        self.assertTrue(hasattr(self.runner,'partial_receipt'),'Fail-closed bounded partial receipt projection is required')
        value=self.runner.partial_receipt(proof)
        self.assertEqual(value,{'passed':False,'cases':[]})
        self.assertTrue(proof['passed'])
    def test_failure_record_never_serializes_exception_text_or_class_names(self):
        self.assertTrue(hasattr(self.runner,'failure_record'),'Static failure code is required')
        class PrivateException(Exception):
            def __str__(self):raise AssertionError('Exception text must not be read')
        self.assertEqual(self.runner.failure_record(PrivateException()),{'failureClass':'unexpected'})
        self.assertEqual(self.runner.failure_record(ValueError('PRIVATE-TOKEN')),{'failureClass':'validation'})
    def test_only_declared_empty_query_can_cross_public_minimum_length(self):
        schema={'type':'object','properties':{'docId':{'type':'string'},'query':{'type':'string','minLength':1}},'required':['docId','query']}
        self.assertTrue(hasattr(self.runner,'validate_tool_arguments'),'Selected negative must reach the actual public handler')
        self.runner.validate_tool_arguments('empty-query','hwp_doc_search',{'docId':'owned-handle','query':''},schema)
        for name,operation,args in (('search','hwp_doc_search',{'docId':'owned-handle','query':''}),('empty-query','hwp_doc_search',{'query':''}),('empty-query','hwp_doc_search',{'docId':'owned-handle','query':False}),('empty-query','hwp_doc_search',{'docId':'owned-handle','query':'','verify':True}),('empty-query','hwp_search',{'docId':'owned-handle','query':''})):
            with self.subTest(name=name,args=args),self.assertRaises(ValueError):self.runner.validate_tool_arguments(name,operation,args,schema)
    def test_transport_is_bound_to_external_editor_provenance_and_exact_inputs(self):
        stage=module('stage_structured')
        self.assertTrue(hasattr(stage,'verify_transport'),'Independent same-editor fixture binding is required')
        with tempfile.TemporaryDirectory() as t:
            folder=Path(t)
            for name in ('structured.hwp','structured.hwpx','checkerboard.png','generation.json'):(folder/name).write_bytes(b'owned-unit-input-'+name.encode())
            hashes={p.name:self.runner.digest(p) for p in folder.iterdir()}
            binding={'sourceCommit':'a'*40,'sourceRun':'123','runAttempt':'1'}
            helper_map=self.runner.helpers()
            value={'formatVersion':1,'repository':'ATLKR/OpenGeul',**binding,'architecture':'x64','editorProvenanceSha256':'b'*64,'sourceContractSha256':'c'*64,'generatorSha256':'d'*64,'inputSha256':hashes,'helperSha256':helper_map}
            package={'repository':'ATLKR/OpenGeul','commit':'a'*40,'runId':'123','architecture':'x64','windowsComponents':{'repository':'ATLKR/OpenGeul','commit':'a'*40,'runId':'123','runAttempt':'1','sourceContractSha256':'c'*64,'components':{'editor':{'provenanceSha256':'b'*64},'cli':{'sha256':'e'*64}}}}
            self.assertEqual(stage.verify_transport(value,package,binding,'x64',folder,helper_map),'d'*64)
            import copy
            for key in ('sourceCommit','sourceRun','runAttempt','architecture','editorProvenanceSha256','sourceContractSha256','generatorSha256','helperSha256','inputSha256'):
                bad=copy.deepcopy(value);bad[key]=None
                with self.subTest(key=key),self.assertRaises(ValueError):stage.verify_transport(bad,package,binding,'x64',folder,helper_map)
            (folder/'unowned.txt').write_bytes(b'unowned')
            with self.assertRaises(ValueError):stage.verify_transport(value,package,binding,'x64',folder,helper_map)
    def test_exact_fixture_inventory_rejects_symlinked_ancestor(self):
        stage=module('stage_structured')
        self.assertTrue(hasattr(stage,'input_hashes'),'Exact no-reparse input boundary is required')
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);folder=root/'real';folder.mkdir()
            for name in ('structured.hwp','structured.hwpx','checkerboard.png','generation.json'):(folder/name).write_bytes(b'owned')
            self.assertEqual(len(stage.input_hashes(folder)),4)
            (root/'alias').symlink_to(folder,target_is_directory=True)
            with self.assertRaises(ValueError):stage.input_hashes(root/'alias')
    def test_cleanup_failure_still_retains_partial_receipt_and_actual_counters(self):
        self.assertTrue(hasattr(self.runner,'retain_partial'),'Cleanup must not erase failed execution evidence')
        class Process:
            def poll(self):return 1
        class Client:
            frames_sent=7;frames_received=6;process=Process()
            def close(self):raise ValueError('PRIVATE-EXCEPTION')
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);proof={'passed':True,'framesSent':0,'framesReceived':0,'serverExited':False,'_toolDefinitions':['PRIVATE-SCHEMA']}
            with self.assertRaises(ValueError):self.runner.retain_partial(Client(),proof,root)
            value=json.loads((root/'structured-result.json').read_bytes())
            self.assertFalse(value['passed']);self.assertTrue(value['serverExited'])
            self.assertEqual((value['framesSent'],value['framesReceived']),(7,6))
            self.assertNotIn('PRIVATE',json.dumps(value))
    def test_completed_stateless_response_does_not_observe_an_exited_worker(self):
        # Only the framing/call adapter is controlled; this is no native proof.
        from types import SimpleNamespace
        value={'schemaVersion':'1.0','source':'owned-unit-input'}
        class Client:
            process=SimpleNamespace(pid=9)
            def request(self,*args):return {'jsonrpc':'2.0','id':1,'result':{'isError':False,'content':[{'type':'text','text':json.dumps(value)}]}}
        class Watch:
            def wait(self,*args):raise AssertionError('One-shot worker has already exited before response')
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);exe=root/'unit.exe';exe.write_bytes(b'owned framing fixture')
            proof={'worker':None,'_evidenceRoot':str(root),'_toolDefinitions':[{'name':'hwp_info','inputSchema':{'type':'object','properties':{'path':{'type':'string'}},'required':['path']}}]}
            suite=self.runner.Suite(exe,'x64',{},root,{},Client(),Watch(),proof);suite.case={'id':'hwp-read','calls':[]}
            self.assertEqual(suite.tool('stateless-info','hwp_info',{'path':'owned-unit-input'}),value)
            self.assertIsNone(proof['worker'])
    def test_explicit_inventory_is_eight_categories_for_both_formats(self):
        self.assertEqual(self.runner.CASE_IDS,tuple(fmt+'-'+name for fmt in ('hwp','hwpx') for name in ('read','search','fields','table','text','session','render','roundtrip')))
        self.assertEqual(len(self.runner.CASE_IDS),16)
        self.assertNotIn('hwp_export_png',self.runner.REQUIRED_TOOLS)
    def test_missing_failed_skipped_reordered_or_partial_receipts_fail_closed(self):
        for value in ({},{'passed':True},{'formatVersion':1,'passed':True,'cases':[]},
                      {'formatVersion':1,'passed':True,'cases':[{'name':'hwp-read','status':'skipped'}]}):
            with self.subTest(value=value),self.assertRaises(ValueError):self.runner.verify_receipt(value,{}, {})
    def test_save_verify_requires_real_boolean_and_zero_integer_diff(self):
        for value in (None,{}, {'identical':False,'diffCount':0},{'identical':1,'diffCount':0},{'identical':True,'diffCount':True},{'identical':True,'diffCount':1}):
            with self.subTest(value=value),self.assertRaises(ValueError):self.runner.verify_ir(value)
        self.runner.verify_ir({'identical':True,'diffCount':0})
    def test_last_search_window_uses_next_offset_presence_not_truncated_false(self):
        wanted=self.expected['search']['offsets'][1]
        value={'schemaVersion':'1.0','source':'doc-owned','query':'FIND-OWNED','caseSensitive':True,
               'matchCount':1,'totalMatchCount':2,'truncated':True,'omittedCount':1,'offset':1,
               'matches':[{'section':0,'paragraph':0,'charOffset':wanted,'length':10,'text':'FIND-OWNED','context':self.expected['body'],'page':0}]}
        self.runner.verify_search(value,'doc-owned',self.expected,[wanted],last=True)
        for change in ({'nextOffset':2},{'totalMatchCount':True},{'source':'other-doc'}):
            with self.subTest(change=change),self.assertRaises(ValueError):self.runner.verify_search({**value,**change},'doc-owned',self.expected,[wanted],last=True)
    def test_style_and_field_mutations_are_independently_compared(self):
        base={'body':[self.expected['body'],self.expected['tail'],'CUSTOMER:C-INIT','ITEM:I-BODY','',''],
              'cells':dict(self.expected['cells']),'fields':[dict(v) for v in self.expected['fields']],
              'styles':{'0,1':{'italic':True,'textColor':'#123456'}},'pictures':[{'sha256':'a'*64,'width':32,'height':16}], 'pageHu':[59528,84189]}
        changed=json.loads(json.dumps(base));changed['cells']['0,1']='SESSION-CELL';changed['fields'][0]['value']='SESSION-FIELD';changed['body'][2]='CUSTOMER:SESSION-FIELD'
        self.oracle.compare_structure(base,changed,cells={'0,1':'SESSION-CELL'},fields={0:'SESSION-FIELD'},keep_style=True)
        changed['styles']['0,1']['italic']=False
        with self.assertRaises(ValueError):self.oracle.compare_structure(base,changed,cells={'0,1':'SESSION-CELL'},fields={0:'SESSION-FIELD'},keep_style=True)
    def test_unrelated_cell_picture_or_body_change_is_not_accepted_as_target_mutation(self):
        base={'body':['BODY'], 'cells':{'0,0':'A','0,1':'B'}, 'fields':[], 'styles':{}, 'pictures':[{'sha256':'a'*64}], 'pageHu':[59528,84189]}
        for change in ({'cells':{'0,0':'EDIT','0,1':'WRONG'}},{'pictures':[]},{'body':['EDIT']}):
            with self.subTest(change=change),self.assertRaises(ValueError):self.oracle.compare_structure(base,{**base,**change},cells={'0,0':'EDIT'})
    def test_empty_svg_and_wrong_namespace_are_not_renderer_evidence(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'output.svg'
            for raw in ('<svg/>','<svg xmlns="http://www.w3.org/2000/svg" width="0" height="0"/>','<svg xmlns="http://www.w3.org/2000/svg" width="794" height="1123" viewBox="0 0 794 1123"/>'):
                p.write_text(raw)
                with self.subTest(raw=raw),self.assertRaises(ValueError):self.oracle.inspect_svg(p,self.expected)
    def test_required_case_contract_rejects_skip_number_checks_missing_calls_or_artifacts(self):
        case={'id':'hwpx-table','status':'passed','checks':{k:True for k in self.runner.CASE_CHECKS['table']},'calls':[{'name':n} for n in ('inventory','set-cell','cli-set-cell','invalid-cell','negative-ping')],'sourceBeforeSha256':'a'*64,'sourceAfterSha256':'a'*64,'artifacts':[{'kind':'hwpx-structure'},{'kind':'hwpx-structure'}],'elapsedMs':1}
        inputs={'structured.hwpx':'a'*64};self.runner.verify_case_inventory(case,inputs)
        import copy
        changes=[]
        for status in ('skipped','failed'):bad=copy.deepcopy(case);bad['status']=status;changes.append(bad)
        bad=copy.deepcopy(case);bad['checks']['cliVerify']=1;changes.append(bad)
        bad=copy.deepcopy(case);bad['checks'].pop('invalidCellRejected');changes.append(bad)
        bad=copy.deepcopy(case);bad['calls'].reverse();changes.append(bad)
        bad=copy.deepcopy(case);bad['calls'].pop();changes.append(bad)
        bad=copy.deepcopy(case);bad['artifacts'].pop();changes.append(bad)
        bad=copy.deepcopy(case);bad['sourceAfterSha256']='b'*64;changes.append(bad)
        for bad in changes:
            with self.subTest(bad=bad),self.assertRaises(ValueError):self.runner.verify_case_inventory(bad,inputs)
    def test_argument_contract_rejects_undeclared_verify_and_boolean_integer(self):
        schema={'type':'object','properties':{'path':{'type':'string'},'data':{'type':'object','additionalProperties':{'type':'string'}},'output':{'type':'string'},'dryRun':{'type':'boolean'}},'required':['path','data']}
        self.runner.validate_arguments({'path':'owned.hwpx','data':{'CUSTOMER':'한글'}},schema)
        for args in ({'path':'owned.hwpx','data':{'CUSTOMER':'한글'},'verify':True},{'path':'owned.hwpx','data':{'CUSTOMER':1}},{'path':'owned.hwpx','data':{},'dryRun':1}):
            with self.subTest(args=args),self.assertRaises(ValueError):self.runner.validate_arguments(args,schema)
        with self.assertRaises(ValueError):self.runner.validate_arguments(True,{'type':'integer','minimum':0},root=False)
    def test_public_channels_and_render_inventory_match_the_actual_surface(self):
        self.assertEqual(self.runner.expected_channel('cli-png'),'cli');self.assertEqual(self.runner.expected_operation('cli-png'),'export-png')
        self.assertEqual(self.runner.expected_channel('stateless-info'),'mcp');self.assertEqual(self.runner.expected_operation('set-cell','session'),'hwp_doc_set_cell')
        self.assertEqual(self.runner.artifact_inventory('hwpx','render'),('svg','svg','svg','pdf','pdf','png'))
    def test_plain_public_handler_error_is_supported_only_for_selected_negative(self):
        value={'result':{'isError':True,'content':[{'type':'text','text':'query 는 빈 문자열일 수 없습니다'}]}}
        self.runner.negative_result(value)
        for bad in ({'result':{'isError':False,'content':value['result']['content']}},{'result':{'isError':True,'content':[{'type':'text','text':''}]}},{'result':{'isError':1,'content':value['result']['content']}}):
            with self.subTest(bad=bad),self.assertRaises(ValueError):self.runner.negative_result(bad)
    def test_checkerboard_pixels_are_predeclared_and_reject_one_pixel_change(self):
        from PIL import Image
        raw=self.oracle.checkerboard();self.oracle.image_pattern(raw,self.expected)
        image=Image.open(io.BytesIO(raw));image.putpixel((0,0),(0,0,0));out=io.BytesIO();image.save(out,format='PNG')
        with self.assertRaises(ValueError):self.oracle.image_pattern(out.getvalue(),self.expected)
    def test_evidence_paths_cannot_escape_or_follow_symlink(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);(root/'calls').mkdir();(root/'calls/ok').write_bytes(b'original')
            self.assertEqual(self.runner.evidence_file(root,'calls/ok'),root/'calls/ok')
            for relative in ('../outside','/outside','calls/../ok','C:/outside','calls\\ok','missing'):
                with self.subTest(relative=relative),self.assertRaises(ValueError):self.runner.evidence_file(root,relative)
            (root/'calls/link').symlink_to(root/'calls/ok')
            with self.assertRaises(ValueError):self.runner.evidence_file(root,'calls/link')
    def test_svg_manifest_relative_path_is_resolved_in_real_caller_cwd(self):
        with tempfile.TemporaryDirectory() as t:
            cwd=Path(t);(cwd/'output').mkdir();owned=cwd/'output/owned.svg';owned.write_bytes(b'original-svg')
            value={'schemaVersion':'1.0','source':'owned.hwpx','format':'svg','backend':'layer','outputDir':'output','pageCount':1,'renderedCount':1,'overflowCellLines':0,'pages':[{'page':0,'path':'output/owned.svg','bytes':owned.stat().st_size,'overflowCellLines':0}]}
            self.assertEqual(self.runner.svg_output(value,'owned.hwpx',cwd,owned),owned)
            import copy
            for mutation in ('escape','boolean-page','wrong-bytes'):
                bad=copy.deepcopy(value)
                if mutation=='escape':bad['pages'][0]['path']='../outside.svg'
                elif mutation=='boolean-page':bad['pages'][0]['page']=False
                else:bad['pages'][0]['bytes']+=1
                with self.subTest(mutation=mutation),self.assertRaises(ValueError):self.runner.svg_output(bad,'owned.hwpx',cwd,owned)
    def test_svg_mcp_schema_does_not_invent_output_argument(self):
        schema={'type':'object','properties':{'path':{'type':'string'}},'required':['path']}
        self.runner.validate_arguments({'path':'owned.hwpx'},schema)
        with self.assertRaises(ValueError):self.runner.validate_arguments({'path':'owned.hwpx','output':'owned-svg'},schema)
    def test_production_runner_still_refuses_non_windows_execution(self):
        if sys.platform!='win32':
            with self.assertRaises(ValueError):self.runner.native_binding()

if __name__=='__main__':unittest.main()
