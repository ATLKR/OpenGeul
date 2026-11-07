"""Finite Home UI contracts; synthetic boundaries never constitute Windows proof."""
import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys
import hashlib
import json
sys.path.insert(0,str(Path(__file__).resolve().parent))

SOURCE=Path(__file__).resolve().parents[1]/'e2e/home_routing_smoke.py'


class SourceMenuHomeCliTests(unittest.TestCase):
    def test_source_home_parser_preserves_default_and_requires_architecture(self):
        spec=importlib.util.spec_from_file_location('home_source_cli',SOURCE)
        api=importlib.util.module_from_spec(spec);spec.loader.exec_module(api)
        parser=getattr(api,'argument_parser',None)
        self.assertTrue(callable(parser),'Home CLI parser seam is missing')
        base=['--suite','suite','--features','features','--hwp-fixtures','hwp','--output','output']
        self.assertIsNone(parser().parse_args(base).source_qualified_menu)
        self.assertEqual(parser().parse_args(base+['--source-qualified-menu','x64']).source_qualified_menu,'x64')

    def test_source_home_context_and_replay_authority_are_explicit(self):
        import inspect
        spec=importlib.util.spec_from_file_location('home_source_cli',SOURCE)
        api=importlib.util.module_from_spec(spec);spec.loader.exec_module(api)
        self.assertIn('source_prepared',inspect.signature(api.HomeCase).parameters)
        self.assertIn('stop_if_pending',inspect.signature(api.run_home_cases).parameters)
        self.assertIn('source_admission',inspect.signature(api.require_case_result).parameters)
        self.assertIn('source_menu_cohort',inspect.getsource(api.main))
        from test_native_menu_smoke import assert_source_cli_dispatch
        assert_source_cli_dispatch(self,api,'_run_home_cohort',('features','hwp-fixtures'))


class HomeRoutingContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert SOURCE.is_file(),'Actual physical Home routing harness is required'
        spec=importlib.util.spec_from_file_location('home_routing_contract',SOURCE)
        cls.api=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.api)

    def test_fixed_plan_covers_six_tiles_all_seventeen_routes_cancel_and_shared_open(self):
        plan=self.api.build_plan()
        self.assertEqual(len(plan),25);self.assertEqual(len({r['case'] for r in plan}),25)
        self.assertEqual([r['module'] for r in plan if r['kind']=='tile'],['writer','calc','impress','draw','math','base'])
        routes=[r for r in plan if r['kind']=='open']
        self.assertEqual(len(routes),17)
        self.assertEqual({r['extension'] for r in routes},{'hwp','hwpx','odt','docx','doc','rtf','txt','ods','xlsx','xls','csv','odp','pptx','ppt','odg','odf','odb'})
        self.assertEqual([r['kind'] for r in plan].count('cancel'),1)
        self.assertEqual([r['kind'] for r in plan].count('shared-open'),1)

    def test_home_action_requires_single_live_owned_button_and_foreground(self):
        value=dict(homeHwnd=10,shellPid=7,home=dict(hwnd=10,pid=7,isWindow=True,rootHwnd=10,threadId=9,className='Home'),
            foreground=dict(hwnd=10,pid=7,isWindow=True,rootHwnd=10),
            candidates=[dict(name='OpenGeul Calc',pid=7,runtimeId=[42,10,1],nativeHwnd=11,nativeRoot=10,nativeLive=True,enabled=True,visible=True)],clicks=1)
        self.api.require_home_action(value,'calc')
        for reason in ('duplicate','foreign','hidden','disabled','root','focus','clicks','runtime'):
            changed=copy.deepcopy(value)
            if reason=='duplicate':changed['candidates'].append(copy.deepcopy(changed['candidates'][0]))
            elif reason=='foreign':changed['candidates'][0]['pid']=8
            elif reason=='hidden':changed['candidates'][0]['visible']=False
            elif reason=='disabled':changed['candidates'][0]['enabled']=False
            elif reason=='root':changed['candidates'][0]['nativeRoot']=99
            elif reason=='focus':changed['foreground']['rootHwnd']=99
            elif reason=='clicks':changed['clicks']=2
            else:changed['candidates'][0]['runtimeId']=[]
            with self.subTest(reason=reason),self.assertRaises(AssertionError):self.api.require_home_action(changed,'calc')

    def test_aggregate_never_accepts_missing_duplicate_failed_or_forced_cleanup(self):
        records=[dict(spec,success=True,cleanClose=True,forcedCleanup=False) for spec in self.api.build_plan()]
        self.assertTrue(self.api.summarize(records)['success'])
        for reason in ('missing','duplicate','failure','forced'):
            rows=copy.deepcopy(records)
            if reason=='missing':rows.pop()
            elif reason=='duplicate':rows[-1]=copy.deepcopy(rows[0])
            elif reason=='failure':rows[0]['success']=False
            else:rows[0]['forcedCleanup']=True
            with self.subTest(reason=reason):self.assertFalse(self.api.summarize(rows)['success'])

    def test_owned_route_paths_cannot_link_escape_or_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();owned=root/'owned';owned.mkdir()
            path=self.api.owned_target(owned,'format-writer-docx.docx')
            self.assertEqual(path.parent,owned)
            path.write_bytes(b'owned generated bytes')
            with self.assertRaises(AssertionError):self.api.owned_target(owned,path.name)
            for name in ('../outside.docx','/outside.docx','unknown.exe'):
                with self.subTest(name=name),self.assertRaises(AssertionError):self.api.owned_target(owned,name)

    def test_open_readiness_reuses_raw_native_controls_with_truthful_open_metadata(self):
        spec=importlib.util.spec_from_file_location('home_open_boundary',Path(__file__).with_name('test_base_save_readiness.py'))
        fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)
        boundary=fixtures.NativeBoundary([lambda b:[],lambda b:[b.edit,b.save]])
        boundary.edit.CurrentAutomationId='1148'  # Actual Home2 native Open filename Edit.
        boundary.api.title=lambda hwnd:self.api.OPEN_CAPTION if hwnd==44 else 'OpenGeul Office'
        record={'openTrigger':dict(kind='home-button',clicks=1)}
        with patch.dict(sys.modules,boundary.modules()),patch.object(self.api.native.time,'monotonic',boundary.clock.monotonic),patch.object(self.api.native.time,'sleep',boundary.clock.sleep):
            dialog,window,filename,button=self.api.wait_open_dialog(boundary.api,boundary.process,11,record)
        proof=record['openDialogReadiness']
        self.assertEqual(dialog,44);self.assertEqual(proof['kind'],'owned-open-dialog-readiness')
        self.assertNotIn('saveShortcuts',proof);self.assertNotIn('fileMenuClicks',proof)
        self.assertEqual([r['state'] for r in proof['observations']],['pending','ready'])
        self.api.require_open_dialog_readiness(proof,77,11,before_input=True)
        with self.assertRaises(AssertionError):self.api.require_open_dialog_readiness(proof,77,11)
        proof['actionStartedAt']=proof['finishedAt'];proof['action']='cancel'
        self.api.require_open_dialog_readiness(proof,77,11)
        for reason in ('owner','duplicate','api','late','early-input'):
            value=copy.deepcopy(proof)
            if reason=='owner':value['observations'][-1]['after']['ownerHwnd']=99
            elif reason=='duplicate':value['observations'][-1]['controls'].append(copy.deepcopy(value['observations'][-1]['controls'][0]))
            elif reason=='api':value['observations'][-1]['apiError']={'hresult':-1}
            elif reason=='late':value['finishedAt']=value['deadline']+1
            else:value['actionStartedAt']=value['startedAt']-1
            with self.subTest(reason=reason),self.assertRaises(AssertionError):self.api.require_open_dialog_readiness(value,77,11)

    def test_home_picker_filename_uses_exact_open_caption_and_original_native_transaction(self):
        spec=importlib.util.spec_from_file_location('home_picker_boundary',Path(__file__).with_name('test_lifecycle_smoke.py'))
        fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)
        api,root,field,calls=fixtures.LifecycleSmokeTests().picker_fixture()
        api.title=lambda hwnd:self.api.OPEN_CAPTION;root.element_info.name=self.api.OPEN_CAPTION
        field.element_info.automation_id='1148'
        record={};target='D:\\owned\\입력 경로 & fixture.docx'
        self.api.lifecycle.set_owned_picker_filename(api,31,100,500,root,field,target,record,expected_title=self.api.OPEN_CAPTION)
        receipt,=record['pickerFilenameInputs']
        self.assertEqual(receipt['after'],target);self.assertEqual(receipt['assignmentAttempts'],1)
        self.assertEqual(receipt['dialog']['owner'],100)
        self.assertEqual([name for name,*_ in calls].count('assign'),1)
        with self.assertRaises(AssertionError):self.api.lifecycle.set_owned_picker_filename(api,31,100,500,root,field,target,{},expected_title='foreign dialog')

    def test_home_open_never_substitutes_base_save_filename_edit_1001(self):
        spec=importlib.util.spec_from_file_location('home_wrong_filename_field',Path(__file__).with_name('test_base_save_readiness.py'))
        fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)
        boundary=fixtures.NativeBoundary([lambda b:[b.edit,b.save]])
        boundary.api.title=lambda hwnd:self.api.OPEN_CAPTION if hwnd==44 else 'OpenGeul Office'
        record={'openTrigger':dict(kind='home-button',clicks=1)}
        with patch.dict(sys.modules,boundary.modules()),patch.object(self.api.native.time,'monotonic',boundary.clock.monotonic),patch.object(self.api.native.time,'sleep',boundary.clock.sleep):
            with self.assertRaises(AssertionError):self.api.wait_open_dialog(boundary.api,boundary.process,11,record)
        self.assertFalse(record['openDialogReadiness']['ready'])
        self.assertTrue(all(row.get('candidateCounts',{}).get('filename',0)==0 for row in record['openDialogReadiness']['observations']))

    def test_open_filename_replay_binds_exact1148_native_handle_runtime_and_target(self):
        value=dict(openDialogReadiness=dict(dialogHwnd=44,wrapperBindings=[dict(properties=dict(automationId='1148',nativeHwnd=101,runtimeId=[42,101]))]),
            pickerFilenameInputs=[dict(expected='C:/owned/format-writer-docx.docx',after='C:/owned/format-writer-docx.docx',
                dialog=dict(owner=11,title=self.api.OPEN_CAPTION),field=dict(automationId='1148',controlType='Edit',nativeHandle=101,runtimeId=[42,101]))])
        with patch.object(self.api,'require_open_dialog_readiness'),patch.object(self.api.lifecycle,'require_picker_native_edit_receipt'):
            self.api.require_open_filename_receipt(value,77,11,'C:/owned/format-writer-docx.docx')
            for key,bad in (('automationId','1001'),('nativeHandle',102),('runtimeId',[42,102]),('controlType','ComboBox')):
                changed=copy.deepcopy(value);changed['pickerFilenameInputs'][0]['field'][key]=bad
                with self.subTest(key=key),self.assertRaises(AssertionError):self.api.require_open_filename_receipt(changed,77,11,'C:/owned/format-writer-docx.docx')

    def test_actual_home_tile_click_has_one_exact_raw_button_and_never_inputs_after_bad_query(self):
        spec=importlib.util.spec_from_file_location('home_tile_boundary',Path(__file__).with_name('test_base_save_readiness.py'))
        fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)
        from types import SimpleNamespace
        for mode in ('valid','duplicate','foreign','hidden','api-error'):
            with self.subTest(mode=mode):
                boundary=fixtures.NativeBoundary([lambda b:[b.save,b.save] if mode=='duplicate' else [b.save]])
                boundary.root.CurrentNativeWindowHandle=11;boundary.save.CurrentName='OpenGeul Calc'
                boundary.save.CurrentProcessId=88 if mode=='foreign' else 77
                boundary.save.CurrentIsOffscreen=mode=='hidden'
                if mode=='api-error':boundary.root.FindAll=lambda *args:(_ for _ in ()).throw(fixtures.ProviderError('query failed'))
                boundary.api.user.GetAncestor=lambda hwnd,flag:11
                boundary.api.user.IsChild=lambda parent,child:parent==11 and child==102
                def window(backend):
                    return SimpleNamespace(element_info=SimpleNamespace(_element=boundary.root),set_focus=lambda:None)
                modules=boundary.modules();modules['pywinauto']=SimpleNamespace(Desktop=lambda backend:SimpleNamespace(window=lambda handle:SimpleNamespace(wrapper_object=lambda:window(backend))))
                def wrapper(info):
                    return SimpleNamespace(element_info=info,click_input=lambda:boundary.calls.append(('tile-click',boundary.clock.value)))
                modules['pywinauto.controls.uiawrapper']=SimpleNamespace(UIAWrapper=wrapper)
                record={}
                with patch.dict(sys.modules,modules),patch.object(self.api.time,'monotonic',boundary.clock.monotonic), \
                     patch.object(self.api.native,'activate_owned_suite',side_effect=lambda api,process,hwnd,record:api.require_foreground(hwnd)):
                    if mode=='valid':self.api.click_home_action(boundary.api,boundary.process,11,'calc',record)
                    else:
                        with self.assertRaises(Exception):self.api.click_home_action(boundary.api,boundary.process,11,'calc',record)
                self.assertEqual(sum(name=='tile-click' for name,*_ in boundary.calls),int(mode=='valid'))
                self.assertEqual(len(record['homeActions']),1)
                if mode=='api-error':self.assertEqual(record['homeActions'][0]['apiError']['hresult'],-2147220991)

    def test_feature_admission_requires_exact_source_case_semantics_hash_and_owned_path(self):
        spec=importlib.util.spec_from_file_location('home_feature_fixture',Path(__file__).with_name('test_office_feature_smoke.py'))
        fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();suite=root/'Suite';suite.mkdir();features_root=root/'features';folder=features_root/'fixtures';folder.mkdir(parents=True)
            records=[]
            for case in self.api.features.case_specs():
                path=folder/(case['id']+'.'+case['extension']);data=('synthetic '+case['id']).encode();path.write_bytes(data)
                observed=self.api.features.expected(case)
                if self.api.features.is_pptx(case):
                    for page in observed['pages']:
                        for shape in page:shape['size']=[n-1 for n in shape['size']];shape['shapeType']='com.sun.star.drawing.CustomShape'
                records.append(dict(case=case['id'],module=case['module'],extension=case['extension'],filter=case['filter'],status='passed',guiVerified=False,
                    independentReopenVerified=True,fixture=str(path),sha256=hashlib.sha256(data).hexdigest(),bytes=len(data),observed=observed,
                    engineCleanups=[dict(phase=phase,evidence=fixture.successful_cleanup(suite)) for phase in ('create','independent-reopen')]))
            report=self.api.features.summarize(records,suite);report_path=features_root/'office-features.json';report_path.write_text(json.dumps(report))
            admitted=self.api.load_feature_inputs(suite,features_root)
            self.assertEqual(len(admitted),15);self.assertEqual(admitted[('calc','csv')]['case'],'format-calc-csv')
            alias=root/'alias';alias.symlink_to(features_root,target_is_directory=True)
            with self.assertRaises(AssertionError):self.api.load_feature_inputs(suite,alias)
            for reason in ('missing','hash','path','semantics','cleanup','foreign-engine'):
                changed=copy.deepcopy(report)
                if reason=='missing':changed['cases'].pop()
                elif reason=='hash':changed['cases'][0]['sha256']='0'*64
                elif reason=='path':changed['cases'][0]['fixture']=str(root/'foreign.odt')
                elif reason=='semantics':changed['cases'][0]['observed']['text']='foreign'
                elif reason=='cleanup':changed['cases'][0]['engineCleanups'][0]['evidence']['forcedTermination']=True
                else:changed['cases'][0]['engineCleanups'][0]['evidence']['expectedEngineImage']=str(root/'foreign/Office/program/soffice.bin')
                report_path.write_text(json.dumps(changed))
                with self.subTest(reason=reason),self.assertRaises((ValueError,AssertionError)):self.api.load_feature_inputs(suite,features_root)

    def test_native_archives_join_the_actual_retained_generation_and_strict_product_receipt(self):
        from suite.e2e.native_cleanup_receipt import validate_cleanup_receipt
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();suite=root/'Suite';suite.mkdir();diagnostics=root/'diagnostics';archive=diagnostics/'tile-writer'/'profile';archive.mkdir(parents=True)
            source=json.loads((Path(__file__).parent/'fixtures/owned-office-shutdown.json').read_text())['graceful']
            expected=str(suite/'Office/program/soffice.bin')
            source['expectedEngineImage']=expected
            for collection in ('initialMembers','finalMembers'):
                for row in source[collection]:row['image']=str(suite/'Office/program'/Path(row['image']).name)
            validate_cleanup_receipt(source,expected_engine_image=expected,launcher_pid=10)
            raw=json.dumps(source).encode();(archive/'shutdown.json').write_bytes(raw)
            manifest=dict(schemaVersion=1,kind='owned-office-native-diagnostics',archiveComplete=True,launcherPid=10,
                files=[dict(path='shutdown.json',bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())])
            record=dict(case='tile-writer',attachments=[dict(officePid=20,officeCreationTime=source['finalMembers'][1]['creationTime'],officeImage=expected)])
            manifest_path=archive/'manifest.json'
            for reason in ('valid','incomplete','hash','generation','missing','forced','dump','unlisted'):
                current=copy.deepcopy(manifest);rows=copy.deepcopy([record]);data=raw
                if reason=='incomplete':current['archiveComplete']=False
                elif reason=='hash':current['files'][0]['sha256']='0'*64
                elif reason=='generation':rows[0]['attachments'][0]['officeCreationTime']+=1
                elif reason=='missing':current['files']=[]
                elif reason=='forced':
                    changed=copy.deepcopy(source);changed['forcedTermination']=True;data=json.dumps(changed).encode()
                    current['files'][0].update(bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
                elif reason=='dump':(archive/'crash.dmp').write_bytes(b'MDMP')
                elif reason=='unlisted':(archive/'unlisted.json').write_text('{}')
                (archive/'shutdown.json').write_bytes(data);manifest_path.write_text(json.dumps(current))
                with self.subTest(reason=reason):
                    if reason=='valid':self.assertEqual(self.api.verify_native_archives(suite,diagnostics,rows)['qualifiedShutdowns'],1)
                    else:
                        with self.assertRaises((ValueError,AssertionError)):self.api.verify_native_archives(suite,diagnostics,rows)
                for name in ('crash.dmp','unlisted.json'):(archive/name).unlink(missing_ok=True)

    def test_new_attachment_selects_new_hwnd_and_preserves_existing_document(self):
        from types import SimpleNamespace
        properties={(20,'OpenGeul.Office.ParentHwnd'):21,(20,'OpenGeul.Office.ChildHwnd'):22,
                    (30,'OpenGeul.Office.ParentHwnd'):31,(30,'OpenGeul.Office.ChildHwnd'):32}
        live={10,20,21,22,30,31,32};pid=lambda hwnd:7 if hwnd in (10,20,21,30,31) else 8
        user=SimpleNamespace(GetPropW=lambda h,key:properties.get((h,key),0),IsWindow=lambda h:h in live,
            IsChild=lambda parent,child:(parent,child) in ((20,21),(21,22),(30,31),(31,32)),IsWindowVisible=lambda h:True)
        api=SimpleNamespace(user=user,attached=lambda p:(20,21,22),windows=lambda process:[10,20,30] if process==7 else [],pid=pid,
            title=lambda hwnd:'format-impress-pptx.pptx — OpenGeul Impress' if hwnd==30 else 'OpenGeul Writer')
        process=SimpleNamespace(pid=7,poll=lambda:None)
        row=self.api.new_attachment(api,process,'impress',{20},Path('/owned/format-impress-pptx.pptx'))
        self.assertEqual(row,dict(hwnd=30,parent=31,child=32,officePid=8))
        live.remove(20)
        with self.assertRaises(AssertionError):self.api.new_attachment(api,process,'impress',{20},Path('/owned/format-impress-pptx.pptx'))
        live.add(20);properties[(40,'OpenGeul.Office.ParentHwnd')]=41;properties[(40,'OpenGeul.Office.ChildHwnd')]=42
        api.windows=lambda process:[10,20,30,40] if process==7 else []
        with self.assertRaises(AssertionError):self.api.new_attachment(api,process,'impress',{20},None)

    def test_open_action_checks_native_owner_and_filename_before_one_open_or_cancel(self):
        from types import SimpleNamespace
        for mode in ('open','cancel','foreign','bad-readback'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as directory:
                target=Path(directory).resolve()/'format-writer-docx.docx';target.write_bytes(b'owned');calls=[];live={44}
                api=SimpleNamespace(pid=lambda h:77,user=SimpleNamespace(GetWindow=lambda h,flag:99 if mode=='foreign' else 11,IsWindow=lambda h:h in live),
                    title=lambda h:self.api.OPEN_CAPTION,class_name=lambda h:'#32770',require_foreground=lambda h:calls.append(('foreground',h)))
                window=SimpleNamespace(class_name=lambda:'#32770')
                button=SimpleNamespace(click_input=lambda:(calls.append(('open',44)),live.clear()))
                record={};proof=dict(finishedAt=0.);cancel_waits=[]
                def ready(*args):args[-1]['openDialogReadiness']=proof;return 44,window,object(),button
                def filename(*args,**kwargs):
                    calls.append(('filename',str(args[6])))
                    if mode=='bad-readback':raise AssertionError('readback mismatch')
                    args[7]['pickerFilenameInputs']=[{'expected':str(args[6]),'after':str(args[6])}]
                def escape(*args,**kwargs):calls.append(('cancel',44));live.clear()
                with patch.object(self.api,'wait_open_dialog',side_effect=ready),patch.object(self.api,'click_home_action'), \
                    patch.object(self.api,'wait_cancelled_home',side_effect=lambda *a:cancel_waits.append(a[3]),create=True), \
                    patch.object(self.api,'require_open_dialog_readiness'),patch.object(self.api.lifecycle,'set_owned_picker_filename',side_effect=filename), \
                    patch.object(self.api,'_open_button_recheck',return_value=[]), \
                    patch.object(self.api.native,'send_owned_dialog_escape',side_effect=escape), \
                    patch.object(self.api.native,'click_owned_control',side_effect=lambda *a,**k:button.click_input()), \
                    patch.dict(sys.modules,{'pywinauto':SimpleNamespace(Desktop=lambda **k:SimpleNamespace(window=lambda **k:SimpleNamespace(wrapper_object=lambda:object()))),'pywinauto.keyboard':SimpleNamespace(send_keys=escape)}),patch.object(self.api.native,'wait_for',side_effect=lambda check,seconds=60:check()):
                    if mode in ('foreign','bad-readback'):
                        with self.assertRaises(AssertionError):self.api.open_dialog_action(api,SimpleNamespace(pid=77,poll=lambda:None),11,record,None if mode=='cancel' else target)
                    else:self.api.open_dialog_action(api,SimpleNamespace(pid=77,poll=lambda:None),11,record,None if mode=='cancel' else target)
                self.assertEqual([name for name,*_ in calls].count('open'),int(mode=='open'))
                self.assertEqual([name for name,*_ in calls].count('cancel'),int(mode=='cancel'))
                self.assertEqual(len(record['openDialogs']),1)
                self.assertEqual(cancel_waits,[44] if mode=='cancel' else [])

    def test_actual_home_base_attach_replays_the_returned_native_save_trigger(self):
        from types import SimpleNamespace as NS
        from test_base_save_readiness import NativeBoundary
        boundary=NativeBoundary([lambda b:[b.edit,b.save]])
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();folder=root/'fixtures';folder.mkdir();boundary.menu_root=root
            boundary.target=folder/'New-OpenGeul-base.odb'
            case=object.__new__(self.api.HomeCase);case.suite=root;case.output=root;case.folder=folder
            case.api=boundary.api;case.process=boundary.process;case.frames=[];case.screenshot=lambda *args:None
            case.record=dict(case='tile-base',kind='tile',module='base',attachments=[])
            bound=NS(pid=88,creation=200,handle=888)
            def freeze(original,executable,evidence):
                evidence.update(pid=88,creationTime=200,handleValue=888,waitResult=258,
                    nativeCreation=dict(fileTime=200),nativeImage=str(executable),expectedImage=str(executable))
            with patch.dict(sys.modules,boundary.modules()), \
                 patch.object(self.api,'new_attachment',return_value=dict(hwnd=11,parent=55,child=56,officePid=88)), \
                 patch.object(self.api.lifecycle,'BoundHwpProcess',return_value=bound),patch.object(self.api,'freeze_live_process',side_effect=freeze), \
                 patch.object(self.api.native.time,'monotonic',boundary.clock.monotonic),patch.object(self.api.native.time,'sleep',boundary.clock.sleep), \
                 patch.object(self.api.native,'click_native_menu_action',side_effect=boundary.measured_native_menu), \
                 patch.object(self.api.native,'click_owned_control',side_effect=boundary.measured_click), \
                 patch.object(self.api.lifecycle,'set_owned_picker_filename',side_effect=boundary.assign_filename), \
                 patch.object(self.api.native,'saved_base_evidence',return_value=dict(sha256='a'*64,bytes=19,connection='sdbc:embedded:firebird')):
                frame=case.attach('base',None)
            self.assertEqual(frame['hwnd'],11)
            self.assertEqual(case.record['baseSaveDialogReadiness']['trigger'],'owned-native-menu-pointer')
            self.assertTrue(case.record['baseSaveMenuAction']['success'])
            self.assertEqual([name for name,*_ in boundary.calls].count('save-menu-click'),1)

    def source_base_replay_fixture(self):
        """Real Gate/v4 replay; native UI and unrelated Home exit proofs are synthetic."""
        from types import SimpleNamespace as NS
        from test_base_save_readiness import NativeBoundary
        from test_native_menu_source_selection import SourceMenuSelectionTests
        import owned_native_menu as menu
        selected=SourceMenuSelectionTests();selected.setUp();self.addCleanup(selected.doCleanups)
        prepared=selected.prepared();selection=selected.selected(prepared);admission=prepared.admission
        boundary=NativeBoundary([lambda b:[b.edit,b.save]]);boundary.menu_root=selected.suite
        folder=selected.output/'generated';folder.mkdir();boundary.target=folder/'New-OpenGeul-base.odb'
        case=object.__new__(self.api.HomeCase);case.suite=selected.suite;case.output=selected.output;case.folder=folder
        case.api=boundary.api;case.process=boundary.process;case.frames=[];case.screenshot=lambda *args:None
        case.record=dict(next(r for r in self.api.build_plan() if r['case']=='tile-base'),attachments=[])
        bound=NS(pid=88,creation=200,handle=888)
        def freeze(original,executable,evidence):
            evidence.update(pid=88,creationTime=200,handleValue=888,waitResult=258,
                nativeCreation=dict(fileTime=200),nativeImage=str(executable),expectedImage=str(executable))
        def source_action(api,process,document,record,command,**options):
            action=boundary.measured_native_menu(api,process,document,record,command,**options)
            shell,engine=action['originalProcess'],action['originalEngine']
            action['sourceMenu']=dict(schemaVersion=1,pointProfileVersion=4,
                admission=menu._source_admission_summary(admission),generation=dict(action['binding'],
                    shellPid=shell['pid'],shellCreationTime=shell['creationTime'],shellHandleValue=shell['handleValue'],
                    engineCreationTime=engine['creationTime'],engineHandleValue=action['engineHandleValue']))
            action['pointUses']=[];process.opengeul_source_menu_selection=selection
            menu.require_native_menu_action(action,77,11,'save',source_admission=admission)
            return action
        original=self.api.native.require_base_save_dialog_readiness
        def seed(*args,**options):
            options['source_admission']=admission
            return original(*args,**options)
        with patch.dict(sys.modules,boundary.modules()), \
             patch.object(self.api,'new_attachment',return_value=dict(hwnd=11,parent=55,child=56,officePid=88)), \
             patch.object(self.api.lifecycle,'BoundHwpProcess',return_value=bound),patch.object(self.api,'freeze_live_process',side_effect=freeze), \
             patch.object(self.api.native.time,'monotonic',boundary.clock.monotonic),patch.object(self.api.native.time,'sleep',boundary.clock.sleep), \
             patch.object(self.api.native,'click_native_menu_action',side_effect=source_action), \
             patch.object(self.api.native,'click_owned_control',side_effect=boundary.measured_click), \
             patch.object(self.api.lifecycle,'set_owned_picker_filename',side_effect=boundary.assign_filename), \
             patch.object(self.api.native,'saved_base_evidence',return_value=dict(sha256='a'*64,bytes=19,connection='sdbc:embedded:firebird')), \
             patch.object(self.api.native,'require_base_save_dialog_readiness',side_effect=seed):
            frame=case.attach('base',None)
        with self.assertRaises(AssertionError):
            original(case.record['baseSaveDialogReadiness'],77,11,'OpenGeul Base — 다른 이름으로 저장')
        original(case.record['baseSaveDialogReadiness'],77,11,'OpenGeul Base — 다른 이름으로 저장',source_admission=admission)
        return case,frame,admission,bound,freeze

    def test_actual_source_home_attach_forwards_gate_through_base_readiness(self):
        case,frame,admission,bound,freeze=self.source_base_replay_fixture()
        captured=copy.deepcopy(case.record)
        # Re-enter the actual attach replay without running a second save transaction.
        def saved(*args):
            for key,value in captured.items():
                if key!='attachments':case.record[key]=copy.deepcopy(value)
        case.frames=[];case.record['attachments']=[]
        with patch.object(self.api,'new_attachment',return_value=dict(hwnd=11,parent=55,child=56,officePid=88)), \
             patch.object(self.api.lifecycle,'BoundHwpProcess',return_value=bound), \
             patch.object(self.api,'freeze_live_process',side_effect=freeze), \
             patch.object(self.api.native,'save_new_base',side_effect=saved):
            try:case.attach('base',None)
            except (AssertionError,ValueError):self.fail('Home attach lost the actual Gate before nested v4 replay')

    def test_actual_source_home_case_replay_forwards_gate_through_base_readiness(self):
        import writer_model_barrier
        case,frame,admission,_,_=self.source_base_replay_fixture();record=case.record
        image=str(case.suite/'Office/program/soffice.bin');attachment=record['attachments'][0]
        attachment['closed']=True
        record.update(success=True,cleanClose=True,forcedCleanup=False,shellExitCode=0,
            shellCommand=[str(case.suite/'OpenGeul.Office.exe')],keyboardInputVerified=False,
            homeHwnd=10,shellPid=77,homeOnlyBeforeAction=[10],originalShell=dict(nativeCreation=dict(fileTime=100)),
            homeActions=[dict(success=True,rawElementEquals=True,shellPid=77,homeHwnd=10)],sourceCopies=[],
            retainedHandleClosures=[{}],frameCloses=[dict(hwnd=11,module='base',success=True,
                menuCloseClicks=0,closeMessageCount=1,exit=dict(pid=88,creationTime=200,image=image))])
        with patch.object(writer_model_barrier,'require_original_shell'),patch.object(self.api,'require_home_action'), \
                patch.object(self.api,'_require_exit_and_closure'):
            try:self.api.require_case_result(record,case.suite,source_admission=admission)
            except (AssertionError,ValueError):self.fail('Home case replay lost the actual Gate before nested v4 replay')

    def source_epoch_failure_fixture(self):
        """Keep actual preparation/epoch guards; the fixture owns every changed byte."""
        from test_native_menu_source_selection import SourceMenuSelectionTests
        selected=SourceMenuSelectionTests();selected.setUp();self.addCleanup(selected.doCleanups)
        prepared=selected.prepared()
        target=selected.suite/'worker/session.py'
        ordinal=next(index for index,row in enumerate(prepared.payload_epoch,1) if row.path==str(target))
        target.write_bytes(target.read_bytes()+b'\n')
        return selected,prepared,ordinal

    def test_source_epoch_prelaunch_failure_records_numeric_summary_and_keeps_original_rejection(self):
        selected,prepared,ordinal=self.source_epoch_failure_fixture()
        (selected.output/'fixtures').mkdir();(selected.output/'diagnostics').mkdir()
        spec=next(row for row in self.api.build_plan() if row['case']=='tile-calc')
        case=self.api.HomeCase(selected.suite,selected.output,spec,{}, {},dict(spec),source_prepared=prepared)
        captured=[];written=[];popen=[];stopped=[]
        def failure(output,name,record,exc):
            captured.append(exc);record.update(success=False,errorType=type(exc).__name__)
        def forbidden(*args,**options):
            popen.append(1);self.fail('The actual source rejection crossed the Popen boundary')
        with patch.object(self.api.native,'capture_failure',side_effect=failure), \
                patch.object(self.api.native,'write_result',side_effect=lambda out,name,record:written.append(record)), \
                patch.object(self.api.native.subprocess,'Popen',side_effect=forbidden), \
                patch.object(self.api.native,'stop_owned_test_process',side_effect=lambda *args:stopped.append(1)):
            result=case.run()
        self.assertEqual(len(captured),1);self.assertIs(type(captured[0]),ValueError)
        self.assertEqual(captured[0].args,('Source menu epoch changed; an explicit new preparation is required',))
        self.assertFalse(result['success']);self.assertFalse(result['cleanClose']);self.assertFalse(result['forcedCleanup'])
        self.assertEqual(result['stage'],'launch-owned-home');self.assertIsNone(case.process)
        self.assertEqual((popen,stopped),([],[]));self.assertEqual(len(written),1)
        self.assertIn('sourceEpochFailure',result)
        summary=result['sourceEpochFailure']
        self.assertEqual(summary['schemaVersion'],1);self.assertEqual(summary['branchCode'],1)
        self.assertEqual(summary['countsKnown'],1);self.assertGreaterEqual(summary['changedCount'],1)
        changed=[row for row in summary['rows'] if row['baselineOrdinal']==ordinal]
        self.assertEqual(len(changed),1)
        self.assertEqual((changed[0]['changeCode'],changed[0]['roleCode']),(3,4))
        self.assertEqual(changed[0]['fieldMask']&8,8)

    def test_source_epoch_observation_requires_the_exact_prelaunch_source_failure(self):
        from types import SimpleNamespace
        from test_native_menu_source_selection import SourceMenuSelectionTests
        selected,prepared,_=self.source_epoch_failure_fixture()
        try:selected.implementation()._unchanged_epochs(prepared,self.api.time.monotonic()+30)
        except ValueError as exc:original=exc
        else:self.fail('The actual changed source epoch was accepted')
        other=SourceMenuSelectionTests();other.setUp();self.addCleanup(other.doCleanups)
        other_prepared=other.prepared()
        cases=[('default',None,'launch-owned-home',None,original),
            ('wrong-stage',prepared,'await-original-home',None,original),
            ('postlaunch',prepared,'launch-owned-home',SimpleNamespace(poll=lambda:0),original),
            ('other-prepared',other_prepared,'launch-owned-home',None,original),
            ('unknown-error',prepared,'launch-owned-home',None,ValueError(*original.args))]
        for label,source,stage,process,error in cases:
            with self.subTest(case=label):
                case=object.__new__(self.api.HomeCase);case.output=selected.output
                case.record=dict(case='tile-calc',success=False,cleanClose=False,forcedCleanup=False)
                case.frames=[];case.hwp_bounds=[];case.process=process;case.source_prepared=source
                def start():
                    case.record['stage']=stage
                    raise error
                case.start=start;case.execute=lambda:self.fail('A rejected launch reached execution')
                captured=[]
                def failure(output,name,record,exc):
                    captured.append(exc);record.update(success=False,errorType=type(exc).__name__)
                with patch.object(self.api.native,'capture_failure',side_effect=failure), \
                        patch.object(self.api.native,'write_result'),patch.object(self.api.native,'stop_owned_test_process'):
                    result=case.run()
                self.assertFalse(result['success']);self.assertTrue(captured[0] is error)
                self.assertNotIn('sourceEpochFailure',result)

    def document_picker_fixture(self,root):
        from test_base_save_readiness import NativeBoundary
        from test_writer_model_barrier import original_shell_fixture
        boundary=NativeBoundary([lambda b:[b.edit,b.save]]);boundary.menu_root=root
        boundary.edit.CurrentAutomationId='1148'
        old_title=boundary.api.title;boundary.api.title=lambda hwnd:self.api.OPEN_CAPTION if hwnd==44 else old_title(hwnd)
        boundary.process._handle=8;boundary.process.opengeul_suite_root=root
        boundary.process.opengeul_evidence_output=root;boundary.process.opengeul_evidence_case='document-file-open'
        boundary.api.attachment=lambda hwnd:(55,56,88)
        boundary.api.user.GetPropW=lambda hwnd,name:1
        old_live=boundary.api.user.IsWindow;boundary.api.user.IsWindow=lambda hwnd:hwnd in (10,55,56) or old_live(hwnd)
        old_root=boundary.api.user.GetAncestor;boundary.api.user.GetAncestor=lambda hwnd,flag:10 if hwnd==10 else old_root(hwnd,flag)
        boundary.api.pid=lambda hwnd:88 if hwnd==56 else 77
        shell=original_shell_fixture(dict(shellPid=77,shellCreationTime=100),root);shell['handleValue']=8
        boundary.process.opengeul_activation_binding=(77,8,str(root/'OpenGeul.Office.exe'),100,258)
        image=str(root/'Office/program/soffice.bin')
        live=dict(kind='home-retained-live-process',pid=88,creationTime=200,handleValue=888,
            getProcessIdResult=88,waitResult=258,nativeImage=image,expectedImage=image,
            nativeImageLength=len(image.encode('utf-16-le'))//2,nativeCreation=dict(low=200,high=0,fileTime=200))
        record=dict(case='document-file-open',kind='shared-open',module='writer',extension='docx',
            homeHwnd=10,shellPid=77,originalShell=shell,attachments=[dict(hwnd=11,parent=55,child=56,
                officePid=88,officeCreationTime=200,officeImage=image,module='writer',liveProcessBinding=live)])
        return boundary,record

    def run_document_picker(self,root,*,owner=11,home=10,document=11,mutate=None,path=True,native_image_case=False):
        from test_owned_native_menu import Probe,Clock as MenuClock
        from types import SimpleNamespace as NS
        import owned_native_menu
        boundary,record=self.document_picker_fixture(root)
        if mutate:mutate(record)
        if native_image_case:
            pid,handle,image,creation,wait=boundary.process.opengeul_activation_binding
            boundary.process.opengeul_activation_binding=(pid,handle,image.swapcase(),creation,wait)
        target=root/'format-impress-pptx.pptx';target.write_bytes(b'owned generated fixture')
        boundary.api.user.GetWindow=lambda hwnd,flag:owner if hwnd==44 else 0
        original=owned_native_menu.click_native_menu_action;native_calls=[];owner_calls=[]
        def menu(api,process,hwnd,record,command):
            native_calls.append(command)
            clock=MenuClock();clock.now=boundary.clock.value
            try:return original(api,process,hwnd,record,command,probe=Probe(root,clock),clock=clock)
            finally:boundary.clock.value=clock.now
        def filename(*args,**kwargs):owner_calls.append(('filename',args[2]));boundary.assign_filename(*args,**kwargs)
        def click(*args,**kwargs):
            owner_calls.append(('open-button',args[2]));self.assertEqual(kwargs['readiness']['documentHwnd'],args[2]);boundary.closed=True
        def home_click(*args):boundary.foreground=home
        with patch.dict(sys.modules,boundary.modules()),patch.object(owned_native_menu,'click_native_menu_action',side_effect=menu), \
             patch.object(self.api,'click_home_action',side_effect=home_click), \
             patch.object(self.api.native,'activate_owned_suite',side_effect=lambda api,process,hwnd,record:api.require_foreground(hwnd)), \
             patch.object(self.api.native.time,'monotonic',boundary.clock.monotonic),patch.object(self.api.native.time,'sleep',boundary.clock.sleep), \
             patch.object(self.api.lifecycle,'set_owned_picker_filename',side_effect=filename), \
             patch.object(self.api.lifecycle,'require_dialog_button_ancestry',return_value=[dict(nativeHandle=44)]), \
             patch.object(self.api.native,'click_owned_control',side_effect=click):
            try:self.api.open_dialog_action(boundary.api,boundary.process,home,record,target if path else None,document=document);error=None
            except Exception as exc:error=exc
        return record,boundary,native_calls,owner_calls,error

    def test_document_menu_picker_uses_original_invoking_document_everywhere(self):
        with tempfile.TemporaryDirectory() as directory:
            record,boundary,native_calls,owner_calls,error=self.run_document_picker(Path(directory).resolve())
        self.assertIsNone(error,type(error).__name__ if error else None)
        operation,=record['openDialogs']
        self.assertEqual(record['homeHwnd'],10);self.assertEqual(operation['pickerOwnerHwnd'],11)
        self.assertEqual(operation['openDialogReadiness']['documentHwnd'],11)
        self.assertTrue(operation['success']);self.assertEqual(native_calls,['open'])
        self.assertEqual(owner_calls,[('filename',11),('open-button',11)])
        binding=operation['documentOwnerBinding']
        self.assertEqual((binding['documentHwnd'],binding['officePid'],binding['officeCreationTime']),(11,88,200))

    def test_document_picker_joins_raw_and_resolved_windows_image_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            _,_,native_calls,owner_calls,error=self.run_document_picker(Path(directory).resolve(),native_image_case=True)
        self.assertIsNone(error,type(error).__name__ if error else None)
        self.assertEqual(native_calls,['open']);self.assertEqual(owner_calls,[('filename',11),('open-button',11)])

    def test_document_menu_picker_rejects_foreign_home_other_document_and_generation_before_input(self):
        for mode in ('foreign-home','other-document','shell-generation','shell-generation-consistent','shell-handle','engine-generation','document-cancel'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as directory:
                def mutate(record):
                    if mode=='shell-generation':record['originalShell']['nativeCreation']['fileTime']+=1
                    elif mode=='shell-generation-consistent':
                        record['originalShell']['nativeCreation']['fileTime']+=1;record['originalShell']['nativeCreation']['low']+=1
                    elif mode=='shell-handle':record['originalShell']['handleValue']+=1
                    elif mode=='engine-generation':record['attachments'][0]['officeCreationTime']+=1
                _,boundary,native_calls,owner_calls,error=self.run_document_picker(Path(directory).resolve(),
                    home=99 if mode=='foreign-home' else 10,document=30 if mode=='other-document' else 11,
                    mutate=mutate,path=mode!='document-cancel')
                self.assertIsInstance(error,AssertionError)
                self.assertEqual(native_calls,[]);self.assertEqual(owner_calls,[])
                self.assertEqual(boundary.calls,[])

    def test_document_menu_picker_never_inputs_to_home_or_other_document_owned_dialog(self):
        for owner in (10,30):
            with self.subTest(owner=owner),tempfile.TemporaryDirectory() as directory:
                record,boundary,native_calls,owner_calls,error=self.run_document_picker(Path(directory).resolve(),owner=owner)
                self.assertIsInstance(error,AssertionError);self.assertEqual(native_calls,['open'])
                self.assertEqual(owner_calls,[])
                self.assertFalse(record['openDialogs'][0]['success'])

    def test_shared_open_replay_derives_picker_owner_from_original_frame_and_generations(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve()
            record,_,_,_,error=self.run_document_picker(root)
            self.assertIsNone(error)
            first,_,_,_,error=self.run_document_picker(root,owner=10,document=None)
            self.assertIsNone(error)
            record['openDialogs'].insert(0,first['openDialogs'][0])
            record.update(success=True,cleanClose=True,forcedCleanup=False,shellExitCode=0,keyboardInputVerified=False,
                shellCommand=[str(root/'OpenGeul.Office.exe')],homeOnlyBeforeAction=[10],sourceCopies=[],
                homeActions=[dict(homeHwnd=10,shellPid=77,home=dict(hwnd=10,rootHwnd=10,pid=77,isWindow=True,threadId=90),
                    foreground=dict(hwnd=10,rootHwnd=10,pid=77,isWindow=True),clicks=1,success=True,rawElementEquals=True,
                    candidates=[dict(name='파일 열기…',pid=77,runtimeId=[42,10],nativeHwnd=12,nativeRoot=10,nativeLive=True,enabled=True,visible=True)])])
            inputs={}
            for module,extension in (('writer','docx'),('impress','pptx')):
                path=root/f'format-{module}-{extension}.{extension}';path.write_bytes(b'owned replay fixture')
                digest=hashlib.sha256(path.read_bytes()).hexdigest()
                descriptor=dict(module=module,extension=extension,source=str(path),featuresRoot=str(root),bytes=path.stat().st_size,sha256=digest)
                inputs[(module,extension)]=descriptor
                record['sourceCopies'].append(dict(path=str(path),sourceInput=descriptor,sha256=digest))
            # Stop only after the real owner/readiness replay has admitted the
            # second picker. Existing tests cover the later retained-exit gate.
            class BothOwnersReplayed(Exception):pass
            for mode in ('valid','reported-owner','reported-binding','dialog-owner','engine-generation','shell-handle','menu-engine'):
                with self.subTest(mode=mode):
                    value=copy.deepcopy(record);owners=[]
                    if mode=='reported-owner':value['openDialogs'][1]['pickerOwnerHwnd']=10
                    elif mode=='reported-binding':value['openDialogs'][1]['documentOwnerBinding']['documentHwnd']=30
                    elif mode=='dialog-owner':value['openDialogs'][1]['openDialogReadiness']['documentHwnd']=10
                    elif mode=='engine-generation':value['attachments'][0]['officeCreationTime']+=1
                    elif mode=='shell-handle':value['originalShell']['handleValue']+=1
                    elif mode=='menu-engine':value['nativeDocumentMenuActions'][0]['nativeAction']['originalEngine']['creationTime']+=1
                    def filename(operation,pid,owner,expected):
                        owners.append(owner)
                        if len(owners)==2:raise BothOwnersReplayed()
                    with patch.object(self.api,'load_feature_inputs',return_value=inputs), \
                         patch.object(self.api,'require_open_filename_receipt',side_effect=filename):
                        with self.assertRaises(BothOwnersReplayed if mode=='valid' else AssertionError):self.api.require_case_result(value,root)
                    self.assertEqual(owners,[10,11] if mode=='valid' else [10])

    def test_actual_case_dispatch_uses_physical_home_routes_and_menu_close_once(self):
        from types import SimpleNamespace
        for spec in self.api.build_plan():
            with self.subTest(case=spec['case']):
                calls=[];frames=[]
                def attach(module,path):
                    frame=dict(module=module,source=path,hwnd=len(frames)+20);frames.append(frame);calls.append(('attach',module));return frame
                def copy_input(module,extension):calls.append(('copy',module,extension));return Path('/owned/'+module+'.'+extension)
                case=SimpleNamespace(record=dict(spec),home=10,process=object(),api=SimpleNamespace(document_windows=lambda p:[]),
                    copy_input=copy_input,attach=attach,close_frame=lambda frame,**kw:calls.append(('close',frame['module'],kw.get('menu',False))),
                    hwp=lambda path:calls.append(('hwp',path)),writer_snapshot=lambda frame,phase:calls.append(('writer-read',phase)) or {'same':True},
                    require_shared_unchanged=lambda a,b:calls.append(('unchanged',)),finish=lambda:calls.append(('finish',)))
                with patch.object(self.api,'click_home_action',side_effect=lambda *args:calls.append(('tile',args[3]))), \
                    patch.object(self.api,'open_dialog_action',side_effect=lambda *args,**kwargs:calls.append(('open',args[4] if len(args)>4 else None,kwargs.get('document')))):
                    self.api.HomeCase.execute(case)
                self.assertEqual(calls[-1],('finish',))
                if spec['kind']=='tile':self.assertEqual(calls[0],('tile',spec['module']))
                elif spec['kind']=='cancel':self.assertEqual([r for r in calls if r[0]=='attach'],[])
                elif spec['kind']=='shared-open':
                    self.assertEqual([r[1] for r in calls if r[0]=='attach'],['writer','impress'])
                    self.assertEqual([r for r in calls if r[0]=='close'],[('close','impress',True),('close','writer',False)])
                    self.assertEqual([r for r in calls if r[0]=='writer-read'],[('writer-read','before'),('writer-read','after')])
                elif spec['module']=='hwp':self.assertEqual(sum(r[0]=='hwp' for r in calls),1)

    def test_runner_preserves_failed_case_and_attempts_remaining_plan_once(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory).resolve();calls=[]
            class Case:
                def __init__(self,suite,out,spec,inputs,hwp,record):self.record=record;calls.append(spec['case'])
                def run(self):
                    if self.record['case']=='tile-writer':raise OSError('original failure')
                    self.record.update(success=True,cleanClose=True,forcedCleanup=False);return self.record
            with patch.object(self.api,'HomeCase',Case),patch.object(self.api,'require_case_result'):rows=self.api.run_home_cases(output,output,{}, {})
            self.assertEqual(calls,[r['case'] for r in self.api.build_plan()]);self.assertEqual(len(rows),25)
            self.assertFalse(rows[0]['success']);self.assertIn('original failure',rows[0]['error'])
            self.assertTrue(rows[-1]['success']);self.assertFalse(self.api.summarize(rows)['success'])

    def test_runner_records_evidence_write_failure_and_continues_remaining_cases(self):
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory).resolve()
            class Case:
                def __init__(self,suite,out,spec,inputs,hwp,record):self.record=record
                def run(self):self.record.update(success=True,cleanClose=True,forcedCleanup=False)
            original=self.api.native.write_result;calls=[]
            def write(out,name,record):
                calls.append(name)
                if len(calls)==1:raise OSError('first evidence write failed')
                return original(out,name,record)
            with patch.object(self.api,'HomeCase',Case),patch.object(self.api,'require_case_result'),patch.object(self.api.native,'write_result',side_effect=write):
                rows=self.api.run_home_cases(output,output,{}, {})
            self.assertEqual(len(rows),25);self.assertFalse(rows[0]['success']);self.assertIn('first evidence write failed',rows[0]['recordWriteError'])
            self.assertTrue(rows[-1]['success'])

    def retained_process_boundary(self,mode='normal',expected=None):
        from types import SimpleNamespace
        expected=Path(expected or '/Suite/Office/program/soffice.bin').resolve();calls=[];state={'live':True}
        class Function:
            def __init__(self,name,call):self.name,self.call=name,call
            def __call__(self,*args):
                calls.append((self.name,int(args[0])));assert int(args[0])==888
                return self.call(*args)
        def image(handle,flags,buffer,size):
            if not state['live']:raise OSError(31,'post-exit image query unavailable')
            buffer.value=str(expected);size._obj.value=len(str(expected).encode('utf-16-le'))//2;return True
        def times(handle,*outputs):
            if mode=='times-api' and not state['live']:return False
            values=(223 if mode=='recycled' and not state['live'] else 222,0 if state['live'] else 1000,7,9)
            for output,value in zip(outputs,values):output._obj.dwLowDateTime=value&0xffffffff;output._obj.dwHighDateTime=value>>32
            return True
        def exit_code(handle,code):code._obj.value=259 if state['live'] else 0xc0000005 if mode=='crash' else 0;return mode!='api' or state['live']
        kernel=SimpleNamespace(QueryFullProcessImageNameW=Function('QueryFullProcessImageNameW',image),GetProcessTimes=Function('GetProcessTimes',times),
            WaitForSingleObject=Function('WaitForSingleObject',lambda handle,timeout:258 if state['live'] or mode=='timeout' else 0),
            GetProcessId=Function('GetProcessId',lambda handle:9 if mode=='pid' and not state['live'] else 8),GetExitCodeProcess=Function('GetExitCodeProcess',exit_code))
        bound=SimpleNamespace(pid=8,creation=222,handle=888,kernel=kernel)
        # Producer-shaped original live proof, with actual existing identity API
        # supplying the native image/FILETIME before the signaled-state transition.
        binding=dict(kind='home-retained-live-process',expectedImage=str(expected),handleValue=888,pid=8,creationTime=222,
            getProcessIdResult=int(kernel.GetProcessId(888)),waitResult=int(kernel.WaitForSingleObject(888,0)))
        self.api.lifecycle.process_identity(kernel,888,binding)
        bound.home_binding_json=json.dumps(binding,sort_keys=True)
        return bound,binding,calls,state

    def test_retained_exit_requires_signaled_same_generation_and_actual_exit_zero(self):
        for mode in ('normal','timeout','crash','api','times-api','recycled','pid','handle','bound-pid'):
            with self.subTest(mode=mode):
                bound,binding,calls,state=self.retained_process_boundary(mode);state['live']=False;calls.clear();evidence={}
                if mode=='handle':bound.handle=999
                elif mode=='bound-pid':bound.pid=9
                if mode=='normal':self.api.retained_exit(bound,evidence)
                else:
                    with self.assertRaises((AssertionError,OSError)):self.api.retained_exit(bound,evidence)
                self.assertNotIn('QueryFullProcessImageNameW',[name for name,handle in calls],'No post-exit image lookup is required')
                if mode in ('crash','api'):self.assertIn('exitCode',evidence)
                if mode=='normal':
                    self.assertEqual(evidence['liveBinding'],binding);self.assertEqual(evidence['creationTime'],222)
                    self.assertEqual(evidence['getProcessTimesResult'],True);self.assertEqual(evidence['getProcessIdResult'],8)
                    self.assertEqual(evidence['imageSource'],'retained-live-binding')

    def test_actual_live_binding_freezes_original_handle_native_image_pid_and_creation(self):
        bound,expected,calls,state=self.retained_process_boundary();del bound.home_binding_json;calls.clear()
        actual=self.api.freeze_live_process(bound,Path(expected['expectedImage']))
        self.assertEqual(actual,expected);self.assertEqual(json.loads(bound.home_binding_json),expected)
        self.assertIn(('QueryFullProcessImageNameW',888),calls);self.assertIn(('GetProcessTimes',888),calls)
        actual['pid']=99;self.assertEqual(json.loads(bound.home_binding_json)['pid'],8,'Returned mutable data cannot replace frozen identity')
        for mode in ('pid','creation','image','dead'):
            with self.subTest(mode=mode):
                bound,expected,calls,state=self.retained_process_boundary();del bound.home_binding_json
                executable=Path(expected['expectedImage'])
                if mode=='pid':bound.pid=9
                elif mode=='creation':bound.creation=223
                elif mode=='image':executable=executable.with_name('foreign.bin')
                else:state['live']=False
                with self.assertRaises((AssertionError,OSError)):self.api.freeze_live_process(bound,executable)
                self.assertFalse(hasattr(bound,'home_binding_json'))

    def test_final_case_replay_rejects_forged_flags_missing_close_and_wrong_generations(self):
        from test_writer_model_barrier import original_shell_fixture
        with tempfile.TemporaryDirectory() as directory:
            suite=Path(directory).resolve()/'Suite'
            bound,live,calls,state=self.retained_process_boundary(expected=suite/'Office/program/soffice.bin');state['live']=False;exit={};self.api.retained_exit(bound,exit)
            action=dict(homeHwnd=10,shellPid=7,home=dict(hwnd=10,pid=7,isWindow=True,rootHwnd=10,threadId=9),foreground=dict(hwnd=10,pid=7,isWindow=True,rootHwnd=10),
                candidates=[dict(name='OpenGeul Writer',pid=7,runtimeId=[1],nativeHwnd=11,nativeRoot=10,nativeLive=True,enabled=True,visible=True)],clicks=1,success=True,rawElementEquals=True)
            record=dict(self.api.build_plan()[0],success=True,cleanClose=True,forcedCleanup=False,shellExitCode=0,keyboardInputVerified=False,
                shellCommand=[str(suite/'OpenGeul.Office.exe')],shellPid=7,homeHwnd=10,homeOnlyBeforeAction=[10],homeActions=[action],sourceCopies=[],
                originalShell=original_shell_fixture(dict(shellPid=7,shellCreationTime=111),suite),
                attachments=[dict(module='writer',hwnd=20,officePid=8,officeCreationTime=222,officeImage=str(suite/'Office/program/soffice.bin'),closed=True,liveProcessBinding=live)],
                frameCloses=[dict(hwnd=20,module='writer',success=True,menuCloseClicks=0,closeMessageCount=1,
                    exit=exit)],
                retainedHandleClosures=[dict(pid=8,creationTime=222,handleValue=888,closeHandleResult=True)])
            self.api.require_case_result(record,suite)
            for reason in ('generation','exit','closure','double-close','missing','menu','original-shell','live-binding','raw-pid','native-creation','times-bool','wait-bool'):
                value=copy.deepcopy(record)
                if reason=='generation':value['attachments'][0]['officeCreationTime']+=1
                elif reason=='exit':value['frameCloses'][0]['exit']['exitCode']=0xc0000005
                elif reason=='closure':value['retainedHandleClosures'][0]['closeHandleResult']=False
                elif reason=='double-close':value['frameCloses'][0]['closeMessageCount']=2
                elif reason=='missing':value['frameCloses']=[]
                elif reason=='menu':value['shellMenuActions']=[dict(label='닫기',fileClicks=1,actionClicks=1,success=True)]
                elif reason=='live-binding':value['frameCloses'][0]['exit']['liveBinding']['handleValue']+=1
                elif reason=='raw-pid':value['frameCloses'][0]['exit']['getProcessIdResult']+=1
                elif reason=='native-creation':value['frameCloses'][0]['exit']['processTimes']['creation']['fileTime']+=1
                elif reason=='times-bool':value['frameCloses'][0]['exit']['getProcessTimesResult']=False
                elif reason=='wait-bool':value['frameCloses'][0]['exit']['waitResult']=False
                else:value['originalShell']['nativeCreation']['fileTime']+=1
                with self.subTest(reason=reason),self.assertRaises((AssertionError,ValueError)):self.api.require_case_result(value,suite)

    def test_shared_unchanged_requires_original_body_url_generation_and_profile_file_id(self):
        binding=dict(shellPid=7,shellCreationTime=111,officePid=8,officeCreationTime=222,expectedImage='C:/Suite/Office/program/soffice.bin',suiteHwnd=20,parentHwnd=21,childHwnd=22,documentUrl='file:///C:/owned/format-writer-docx.docx')
        snapshot=dict(officeCommandLine=['owned-private-pipe'],profileUrl='file:///C:/profile',profileDirectory=dict(witness=dict(canonicalPath='C:/profile',openedInfo=dict(volumeSerialNumber=1,fileIndexHigh=0,fileIndexLow=4))))
        value=dict(source='C:/owned/format-writer-docx.docx',sha256='1'*64,context=dict(observation=dict(bodyText='owned body',isModified=False,bindingBefore=binding,nativeSnapshots=dict(controllerBefore=snapshot,helperBefore=copy.deepcopy(snapshot)))))
        self.api.HomeCase.require_shared_unchanged(value,copy.deepcopy(value))
        for reason in ('body','url','generation','file-id','dirty','hash'):
            changed=copy.deepcopy(value);row=changed['context']['observation']
            if reason=='body':row['bodyText']='lost body'
            elif reason=='url':row['bindingBefore']['documentUrl']='file:///C:/foreign.docx'
            elif reason=='generation':row['bindingBefore']['officeCreationTime']+=1
            elif reason=='file-id':row['nativeSnapshots']['helperBefore']['profileDirectory']['witness']['openedInfo']['fileIndexLow']+=1
            elif reason=='dirty':row['isModified']=True
            else:changed['sha256']='2'*64
            with self.subTest(reason=reason),self.assertRaises(AssertionError):self.api.HomeCase.require_shared_unchanged(value,changed)

    def test_actual_case_cleanup_preserves_original_failure_and_failed_handle_close(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory).resolve();case=object.__new__(self.api.HomeCase)
            case.output=output;case.record=dict(case='tile-writer',success=False,forcedCleanup=False);case.hwp_bounds=[]
            bound=SimpleNamespace(pid=8,creation=222,handle=888,live=lambda:True,kernel=SimpleNamespace(CloseHandle=lambda handle:False),
                stop=lambda:(_ for _ in ()).throw(OSError('secondary cleanup failed')))
            case.frames=[dict(bound=bound)];case.process=SimpleNamespace(poll=lambda:0)
            case.start=lambda:None;case.execute=lambda:(_ for _ in ()).throw(OSError('original action failure'))
            with patch.object(self.api.native,'capture_failure',side_effect=lambda out,name,record,exc:record.update(success=False,error=str(exc))),patch.object(self.api.native,'stop_owned_test_process'):
                result=case.run()
            self.assertEqual(result['error'],'original action failure');self.assertFalse(result['success']);self.assertTrue(result['forcedCleanup'])
            self.assertEqual(result['cleanupErrors'],['OSError: secondary cleanup failed'])
            self.assertFalse(result['retainedHandleClosures'][0]['closeHandleResult']);self.assertIsNone(bound.handle)

    def test_actual_close_frame_dispatches_home_calc_token_and_menu_close_without_second_message(self):
        from types import SimpleNamespace
        import home_calc_close
        for module,menu,extension in (('calc',False,None),('calc',False,'csv'),('impress',True,None),('writer',False,None)):
            calls=[];case=object.__new__(self.api.HomeCase);case.record=dict(case='tile-'+module,module=module);case.suite=Path('/Suite');case.output=Path('/output')
            if extension:case.record.update(case='home-open-calc-csv',extension=extension)
            case.csv_post_getter_screenshot=lambda *args:calls.append('post-getter-png')
            case.process=SimpleNamespace(pid=7);live={20,22};bound=SimpleNamespace(live=lambda:False)
            frame=dict(hwnd=20,parent=21,child=22,officePid=8,module=module,source=None,bound=bound,receipt={})
            # A live pre-close check and an exited post-close check are distinct.
            state=[True];bound.live=lambda:state[0]
            def close(*args):calls.append('close-action');live.clear();state[0]=False
            case.api=SimpleNamespace(user=SimpleNamespace(IsWindow=lambda h:h in live),request_close=close,windows=lambda pid:[])
            def menu_action(*args):calls.append('physical-menu-close');close();return dict(actionClicks=1,success=True)
            with patch.object(self.api.native,'wait_for',side_effect=lambda check,seconds=60:check()),patch.object(self.api,'retained_exit',side_effect=lambda *args:calls.append('normal-exit')), \
                patch.object(self.api,'shell_menu_action',side_effect=menu_action),patch.object(home_calc_close,'observe_home_calc',side_effect=lambda *args:calls.append('getter')), \
                patch.object(home_calc_close,'freeze_home_calc_close',side_effect=lambda *args,**kwargs:calls.append('token') or object()),patch.object(home_calc_close,'close_home_calc',side_effect=close):
                case.close_frame(frame,menu=menu)
            self.assertEqual(calls.count('close-action'),1);self.assertTrue(frame['closed'])
            if module=='calc':self.assertEqual(calls,['getter','token',*(['post-getter-png'] if extension else []),'close-action','normal-exit'])
            elif menu:self.assertEqual(calls,['physical-menu-close','close-action','normal-exit']);self.assertEqual(case.record['frameCloses'][0]['closeMessageCount'],0)

    def csv_checkpoint_fixture(self,root):
        from types import SimpleNamespace as NS
        binding=dict(shellPid=77,shellCreationTime=111,officePid=88,officeCreationTime=222,suiteHwnd=11,parentHwnd=12,childHwnd=22)
        context=dict(success=True,finishedAt=4.,deadline=12.,observation=dict(bindingBefore=binding))
        case=object.__new__(self.api.HomeCase);case.output=root
        case.record=dict(case='home-open-calc-csv',module='calc',extension='csv',shellPid=77,officePid=88,
            windowHwnd=11,parentHwnd=12,childHwnd=22,originalShell=dict(handleValue=555),calcReader=context,
            screenshots=['home-open-calc-csv-calc-attached.png'],attachments=[dict(hwnd=11,officePid=88,
                officeCreationTime=222,liveProcessBinding=dict(handleValue=888))])
        case.api=NS(require_foreground=lambda hwnd:None)
        proof=NS(process=NS(pid=77),process_handle=555,bound=NS(pid=88,creation=222),bound_handle=888,hwnd=11,child=22)
        return case,dict(hwnd=11,parent=12,child=22,officePid=88),proof

    @staticmethod
    def capture_geometry_fixture(path,binding):
        import csv_geometry_evidence as geometry
        from test_csv_geometry_evidence import Boundary
        from types import SimpleNamespace as NS
        from PIL import Image
        boundary=Boundary(geometry)
        boundary.work_rect=[0,0,1024,720]
        boundary.rects.update({11:[0,0,1024,720],12:[8,55,1016,690],22:[8,55,1016,690]})
        boundary.client.update({11:[0,0,1008,681],12:[0,0,1008,635],22:[0,0,1008,635]})
        boundary.origins.update({11:[8,31],12:[8,55],22:[8,55]})
        wrapper=NS(handle=11,process_id=lambda:77,is_visible=lambda:True,
            rectangle=lambda:NS(left=0,top=0,right=1024,bottom=720),
            capture_as_image=lambda:Image.new('RGB',(2,2),'white'))
        geometry.capture_with_geometry(wrapper,binding,path,probe=geometry.GeometryProbe(boundary.user,boundary.shell))

    def test_csv_post_getter_png_is_bound_readonly_and_never_claims_grid_readiness(self):
        import home_calc_close
        from types import SimpleNamespace as NS
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();case,frame,proof=self.csv_checkpoint_fixture(root);calls=[]
            def capture(hwnd,pid,path,timeout,*,binding):
                calls.append(('capture',hwnd,pid,timeout));self.capture_geometry_fixture(path,binding)
                return NS(returncode=0,stdout='',stderr='')
            with patch.object(home_calc_close,'verify_home_calc_close',side_effect=lambda *args:calls.append(('guard',))), \
                 patch.object(self.api,'_capture_checkpoint_png',side_effect=capture),patch.object(self.api.time,'monotonic',return_value=5.):
                case.csv_post_getter_screenshot(frame,proof)
            self.assertEqual([r[0] for r in calls],['guard','capture','guard'])
            row=case.record['csvPostGetterScreenshot'];self.assertEqual(row['readerDeadline'],12.)
            self.assertIs(case.record['csvWorkingAreaFit']['passed'],True)
            self.assertEqual([item['edge'] for item in case.record['csvWorkingAreaFit']['observations']],['before','after'])
            self.assertFalse(row['gridVisibleVerified']);self.assertFalse(row['paintCompleteVerified']);self.assertTrue(row['visualReviewRequired'])
            self.assertEqual(case.record['screenshots'],['home-open-calc-csv-calc-attached.png',row['image']])
            self.api.require_csv_post_getter_screenshot(case.record)
            for field,bad in [('startedAt',3.),('readerDeadline',13.),('gridVisibleVerified',True),('captureCount',2),('image','foreign.png')]:
                changed=copy.deepcopy(case.record);changed['csvPostGetterScreenshot'][field]=bad
                with self.subTest(field=field),self.assertRaises(AssertionError):self.api.require_csv_post_getter_screenshot(changed)
            for field,bad in [('officeCreationTime',223),('officeHandleValue',999),('childHwnd',23)]:
                changed=copy.deepcopy(case.record);changed['csvPostGetterScreenshot']['nativeAfter'][field]=bad
                with self.subTest(field=field),self.assertRaises(AssertionError):self.api.require_csv_post_getter_screenshot(changed)

    def test_csv_capture_requires_complete_adjacent_geometry_for_the_same_binding_and_png(self):
        import home_calc_close
        from types import SimpleNamespace as NS
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            case,frame,proof=self.csv_checkpoint_fixture(Path(directory).resolve())
            def capture(hwnd,pid,path,timeout,*,binding):
                Image.new('RGB',(2,2),'white').save(path)
                return NS(returncode=0,stdout='',stderr='')
            with patch.object(home_calc_close,'verify_home_calc_close'),patch.object(self.api,'_capture_checkpoint_png',side_effect=capture), \
                 patch.object(self.api.time,'monotonic',return_value=5.):
                with self.assertRaises((AssertionError,FileNotFoundError)):
                    case.csv_post_getter_screenshot(frame,proof)
            self.assertFalse(case.record['csvPostGetterScreenshot']['passed'])

    def test_live_csv_capture_rejects_incomplete_or_contradictory_nested_geometry(self):
        import csv_geometry_evidence as geometry
        import home_calc_close
        from types import SimpleNamespace as NS
        for reason in ('missing-native','skeleton','wrong-owner','raced-target'):
            with self.subTest(reason=reason),tempfile.TemporaryDirectory() as directory:
                case,frame,proof=self.csv_checkpoint_fixture(Path(directory).resolve())
                def capture(hwnd,pid,path,timeout,*,binding):
                    self.capture_geometry_fixture(path,binding)
                    sidecar=path.with_name(geometry.SIDECAR_NAME);value=json.loads(sidecar.read_bytes())
                    if reason=='missing-native':del value['before']['windows'][1]['clientScreenRect']
                    elif reason=='skeleton':
                        for edge in ('before','after'):
                            value[edge]=dict(complete=True,errors=[],taskbar=dict(complete=True),
                                windows=[dict(hwnd=h,complete=True) for h in (11,12,22)])
                    elif reason=='wrong-owner':value['before']['windows'][2]['pid']=999
                    else:value['after']['windows'][0]['windowRect'][0]-=1
                    sidecar.write_bytes(geometry.receipt_bytes(value))
                    return NS(returncode=0,stdout='',stderr='')
                with patch.object(home_calc_close,'verify_home_calc_close'),patch.object(self.api,'_capture_checkpoint_png',side_effect=capture), \
                     patch.object(self.api.time,'monotonic',return_value=5.):
                    with self.assertRaises(AssertionError):case.csv_post_getter_screenshot(frame,proof)
                self.assertIs(case.record['csvPostGetterScreenshot']['passed'],False)
                self.assertEqual(len(case.record['screenshots']),1)

    def test_live_csv_capture_allows_observed_cursor_and_taskbar_state_changes(self):
        import csv_geometry_evidence as geometry
        import home_calc_close
        from types import SimpleNamespace as NS
        with tempfile.TemporaryDirectory() as directory:
            case,frame,proof=self.csv_checkpoint_fixture(Path(directory).resolve())
            def capture(hwnd,pid,path,timeout,*,binding):
                self.capture_geometry_fixture(path,binding)
                sidecar=path.with_name(geometry.SIDECAR_NAME);value=json.loads(sidecar.read_bytes())
                value['after']['physicalCursor']=[20,100]
                value['after']['taskbar']['appBarState']=dict(raw=0,autoHide=False,alwaysOnTop=False)
                sidecar.write_bytes(geometry.receipt_bytes(value))
                return NS(returncode=0,stdout='',stderr='')
            with patch.object(home_calc_close,'verify_home_calc_close'),patch.object(self.api,'_capture_checkpoint_png',side_effect=capture), \
                 patch.object(self.api.time,'monotonic',return_value=5.):
                case.csv_post_getter_screenshot(frame,proof)
            self.assertIs(case.record['csvPostGetterScreenshot']['passed'],True)
            self.api.require_csv_post_getter_screenshot(case.record)

    def test_live_csv_capture_requires_observed_working_area_fit(self):
        import csv_geometry_evidence as geometry
        import home_calc_close
        from types import SimpleNamespace as NS
        for reason in ('suite-window','suite-client','embedded-client'):
            with self.subTest(reason=reason),tempfile.TemporaryDirectory() as directory:
                case,frame,proof=self.csv_checkpoint_fixture(Path(directory).resolve())
                def capture(hwnd,pid,path,timeout,*,binding):
                    self.capture_geometry_fixture(path,binding)
                    sidecar=path.with_name(geometry.SIDECAR_NAME);value=json.loads(sidecar.read_bytes())
                    for edge in ('before','after'):
                        windows=value[edge]['windows']
                        if reason=='suite-window':windows[0]['windowRect']=[0,0,1044,788]
                        elif reason=='suite-client':windows[0]['clientScreenRect']=[8,31,1036,780]
                        else:
                            for row in windows[1:]:row['clientScreenRect']=[8,55,1036,758]
                    sidecar.write_bytes(geometry.receipt_bytes(value))
                    return NS(returncode=0,stdout='',stderr='')
                with patch.object(home_calc_close,'verify_home_calc_close'),patch.object(self.api,'_capture_checkpoint_png',side_effect=capture), \
                     patch.object(self.api.time,'monotonic',return_value=5.):
                    with self.assertRaises(AssertionError):case.csv_post_getter_screenshot(frame,proof)
                self.assertIs(case.record['csvPostGetterScreenshot']['passed'],False)
                self.assertIs(case.record['csvWorkingAreaFit']['passed'],False)
                self.assertFalse(case.record['csvPostGetterScreenshot']['gridVisibleVerified'])
                self.assertFalse(case.record['csvPostGetterScreenshot']['paintCompleteVerified'])

    def test_csv_post_getter_capture_never_masks_original_guard_or_collector_failure(self):
        import home_calc_close
        from types import SimpleNamespace as NS
        from PIL import Image
        for failure in ('before','after','collector','timeout','late'):
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as directory:
                case,frame,proof=self.csv_checkpoint_fixture(Path(directory).resolve());guards=[];captures=[];clock=[5.]
                def guard(*args):
                    guards.append(True)
                    if failure=='before' or failure=='after' and len(guards)==2:raise OSError('original retained identity failure')
                def capture(hwnd,pid,path,timeout,*,binding):
                    captures.append(True)
                    if failure=='timeout':raise self.api.subprocess.TimeoutExpired(['owned-screenshot'],timeout)
                    if failure=='late':clock[0]=16.
                    self.capture_geometry_fixture(path,binding)
                    return NS(returncode=7 if failure=='collector' else 0,stdout='',stderr='original capture failure')
                with patch.object(home_calc_close,'verify_home_calc_close',side_effect=guard),patch.object(self.api,'_capture_checkpoint_png',side_effect=capture), \
                     patch.object(self.api.time,'monotonic',side_effect=lambda:clock[0]):
                    with self.assertRaises((OSError,AssertionError,self.api.subprocess.TimeoutExpired)):
                        case.csv_post_getter_screenshot(frame,proof)
                self.assertEqual(len(captures),0 if failure=='before' else 1)
                self.assertIsNot(case.record.get('csvPostGetterScreenshot',{}).get('passed'),True)
                self.assertEqual(len(case.record['screenshots']),1)

    def test_actual_screenshot_collector_only_reads_owned_window_without_focus_or_input(self):
        from types import SimpleNamespace as NS
        from PIL import Image
        import importlib.metadata
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory).resolve()/'home-open-calc-csv-calc-post-getter.png';calls=[]
            import csv_geometry_evidence as geometry
            from test_csv_geometry_evidence import Boundary
            boundary=Boundary(geometry);probe=geometry.GeometryProbe(boundary.user,boundary.shell)
            binding=dict(shellPid=77,shellCreationTime=111,shellHandleValue=555,officePid=88,
                officeCreationTime=222,officeHandleValue=888,windowHwnd=11,parentHwnd=12,childHwnd=22)
            wrapper=NS(handle=11,process_id=lambda:77,is_visible=lambda:True,
                rectangle=lambda:NS(left=-10,top=-10,right=1050,bottom=800),
                capture_as_image=lambda:calls.append('capture') or Image.new('RGB',(2,2),'white'))
            desktop=NS(window=lambda handle:NS(wrapper_object=lambda:wrapper))
            def initialized_desktop(backend):
                boundary.context=456  # Dependency DPI initialization happens before saving a token.
                return desktop
            with patch.dict(sys.modules,{'pywinauto':NS(Desktop=initialized_desktop)}), \
                 patch.object(sys,'argv',['collector','11','77',str(target),json.dumps(binding),str(SOURCE.parent)]), \
                 patch.object(geometry,'GeometryProbe',return_value=probe),patch.object(importlib.metadata,'version',return_value='0.6.9'):
                exec(self.api.CSV_CHECKPOINT_CAPTURE,{'__name__':'__main__'})
            self.assertEqual(calls,['capture']);self.assertTrue(target.is_file())
            self.assertTrue(target.with_name('home-open-calc-csv-calc-post-getter-geometry.json').is_file(), 'Required geometry sidecar is missing')
            self.assertFalse(hasattr(wrapper,'set_focus'));self.assertFalse(hasattr(wrapper,'click_input'))
            geometry_row=json.loads(target.with_name(geometry.SIDECAR_NAME).read_bytes())
            self.assertEqual(geometry_row['dpiScope']['previousContext'],456);self.assertEqual(boundary.context,456)

    def test_screenshot_helper_has_one_bounded_hidden_child_and_no_retry(self):
        from types import SimpleNamespace as NS
        with patch.object(self.api.subprocess,'run',return_value=NS(returncode=0,stdout='',stderr='')) as run:
            self.api._capture_checkpoint_png(11,77,Path('/owned/checkpoint.png'),3.25,binding={'windowHwnd':11,'shellPid':77})
        self.assertEqual(run.call_count,1);args,kwargs=run.call_args
        self.assertEqual(args[0][1:3],['-c',self.api.CSV_CHECKPOINT_CAPTURE]);self.assertEqual(kwargs['timeout'],3.25)
        self.assertFalse(kwargs.get('shell',False));self.assertIn('creationflags',kwargs)
        self.assertEqual(json.loads(args[0][-2]),{'windowHwnd':11,'shellPid':77})
        self.assertEqual(args[0][-1],str(SOURCE.parent.resolve()))
        for invalid in (0,10.01):
            with self.subTest(timeout=invalid),self.assertRaises(AssertionError):
                self.api._capture_checkpoint_png(11,77,Path('/owned/checkpoint.png'),invalid,binding={})

    def test_main_keeps_case_failures_and_strict_archive_failure_nonzero(self):
        from types import SimpleNamespace
        import home_fixture_inputs
        for failure in ('none','case','archive','baseline-after'):
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as directory:
                root=Path(directory).resolve();suite=root/'Suite';suite.mkdir();feature=root/'features';feature.mkdir();fixtures=root/'hwp';fixtures.mkdir();(fixtures/'provenance.json').write_text('{}')
                output=root/'output';rows=[dict(spec,success=not(failure=='case' and i==0),cleanClose=True,forcedCleanup=False,attachments=[]) for i,spec in enumerate(self.api.build_plan())]
                # Test only main's exit/report gate: native case/raw receipt admission
                # is exercised separately, not fabricated as Windows execution.
                rows[0]['attachments']=[{} for _ in range(23)]
                def integrity(*args):
                    if failure=='archive':raise AssertionError('unqualified native shutdown')
                    return dict(success=True,qualifiedShutdowns=23)
                argv=['home_routing_smoke.py','--suite',str(suite),'--features',str(feature),'--hwp-fixtures',str(fixtures),'--output',str(output)]
                feature_calls=[]
                def baseline(*args):
                    feature_calls.append(1)
                    if failure=='baseline-after' and len(feature_calls)==2:raise AssertionError('original feature changed')
                    return {}
                with patch.object(self.api,'os',SimpleNamespace(name='nt')),patch.object(sys,'argv',argv),patch.object(self.api,'load_feature_inputs',side_effect=baseline), \
                    patch.object(home_fixture_inputs,'require_hwp_fixture_provenance',return_value={}),patch.object(self.api,'run_home_cases',return_value=rows),patch.object(self.api,'verify_native_archives',side_effect=integrity) as native_gate:
                    code=self.api.main()
                self.assertEqual(native_gate.call_count,1,'Always audit actual owned shutdown archives after a later baseline failure')
                self.assertEqual(code,0 if failure=='none' else 1)
                report=json.loads((output/'home-routing.json').read_text());self.assertEqual(report['success'],failure=='none')
                if failure=='archive':self.assertIn('unqualified native shutdown',report['nativeIntegrity']['error'])

    def run_aggregate_main(self,root,rows):
        from types import SimpleNamespace
        import home_fixture_inputs
        suite=root/'Suite';suite.mkdir();feature=root/'features';feature.mkdir();fixtures=root/'hwp';fixtures.mkdir()
        (fixtures/'provenance.json').write_text('{}');output=root/'output'
        argv=['home_routing_smoke.py','--suite',str(suite),'--features',str(feature),'--hwp-fixtures',str(fixtures),'--output',str(output)]
        def retained_cases(*args):
            for row in rows:
                (output/(row['case']+'-result.json')).write_bytes(json.dumps(row,ensure_ascii=False).encode('utf-8'))
            return rows
        with patch.object(self.api,'os',SimpleNamespace(name='nt')),patch.object(sys,'argv',argv), \
             patch.object(self.api,'load_feature_inputs',return_value={}), \
             patch.object(home_fixture_inputs,'require_hwp_fixture_provenance',return_value={}), \
             patch.object(self.api,'run_home_cases',side_effect=retained_cases), \
             patch.object(self.api,'verify_native_archives',return_value=dict(success=True,qualifiedShutdowns=23)):
            return self.api.main(),output

    def aggregate_rows(self):
        rows=[dict(spec,success=True,cleanClose=True,forcedCleanup=False,attachments=[]) for spec in self.api.build_plan()]
        rows[0]['attachments']=[{} for _ in range(23)]
        inventory=dict(schemaVersion=1,architecture='x64',files=[dict(path='한글/'+str(n),bytes=n,sha256='a'*64) for n in range(100)])
        for row in rows:
            if row['case'] in ('tile-calc','home-open-calc-ods','home-open-calc-xlsx','home-open-calc-xls','home-open-calc-csv'):
                row['calcReader']=dict(inventory=copy.deepcopy(inventory),nativeCreation=134370086799550953,
                    handle=2**40,abovePrecision=2**53+1,value=17.0,flag=True,missing=None)
            elif row['case']=='document-file-open':
                for key in ('sharedWriterBefore','sharedWriterAfter'):
                    row[key]=dict(inventory=copy.deepcopy(inventory),nativeCreation=134370086799550953)
        return rows

    def test_home_aggregate_is_lossless_compact_utf8_with_all_seven_full_inventories(self):
        with tempfile.TemporaryDirectory() as directory:
            rows=self.aggregate_rows();code,output=self.run_aggregate_main(Path(directory).resolve(),rows)
            self.assertEqual(code,0);raw=(output/'home-routing.json').read_bytes();parsed=json.loads(raw)
            compact=json.dumps(parsed,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8')
            self.assertEqual(raw,compact,'The Home aggregate is still pretty printed or translated by platform text I/O')
            self.assertEqual(parsed['cases'],rows)
            def same_types(before,after):
                self.assertIs(type(after),type(before))
                if isinstance(before,dict):
                    self.assertEqual(list(before),list(after))
                    for key in before:same_types(before[key],after[key])
                elif isinstance(before,list):
                    self.assertEqual(len(before),len(after))
                    for left,right in zip(before,after):same_types(left,right)
                else:self.assertEqual(before,after)
            same_types(rows,parsed['cases'])
            contexts=[row['calcReader'] for row in parsed['cases'] if 'calcReader' in row]
            contexts += [parsed['cases'][-1][key] for key in ('sharedWriterBefore','sharedWriterAfter')]
            self.assertEqual(len(contexts),7)
            for context in contexts:
                self.assertEqual(len(context['inventory']['files']),100)
                self.assertIs(type(context['nativeCreation']),int)
                self.assertEqual(context['nativeCreation'],134370086799550953)

    def test_home_aggregate_exact_byte_cap_and_nonfinite_values_fail_closed(self):
        self.assertTrue(hasattr(self.api,'write_home_aggregate'),'A bounded Home aggregate producer is missing')
        self.assertEqual(self.api.MAX_HOME_AGGREGATE_BYTES,32*1024*1024)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);report=dict(success=True,payload='')
            overhead=len(json.dumps(report,separators=(',',':')).encode('utf-8'))
            report['payload']='x'*(self.api.MAX_HOME_AGGREGATE_BYTES-overhead)
            good=root/'good';good.mkdir();self.api.write_home_aggregate(good,report)
            self.assertEqual((good/'home-routing.json').stat().st_size,self.api.MAX_HOME_AGGREGATE_BYTES)
            bad=root/'bad';bad.mkdir();report['payload']+='x'
            with self.assertRaisesRegex(AssertionError,'byte limit'):self.api.write_home_aggregate(bad,report)
            self.assertFalse((bad/'home-routing.json').exists())
            with self.assertRaises(ValueError):self.api.write_home_aggregate(bad,dict(success=True,value=float('nan')))

    def test_oversized_aggregate_keeps_every_written_case_and_truthful_failure(self):
        self.assertTrue(hasattr(self.api,'MAX_HOME_AGGREGATE_BYTES'),'A bounded Home aggregate producer is missing')
        with tempfile.TemporaryDirectory() as directory,patch.object(self.api,'MAX_HOME_AGGREGATE_BYTES',64):
            rows=self.aggregate_rows();code,output=self.run_aggregate_main(Path(directory).resolve(),rows)
            self.assertEqual(code,1);self.assertFalse((output/'home-routing.json').exists())
            failure=json.loads((output/'home-routing-write-failure.json').read_bytes())
            self.assertIs(failure['success'],False);self.assertIn('byte limit',failure['error'])
            for row in rows:
                self.assertEqual(json.loads((output/(row['case']+'-result.json')).read_bytes()),row)


if __name__=='__main__':unittest.main()
