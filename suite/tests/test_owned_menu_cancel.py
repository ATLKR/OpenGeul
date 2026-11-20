"""Actual menu-cancel policy with synthetic Windows/UIA boundaries."""
import copy
import importlib.util
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS,MethodType
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'e2e'))
SOURCE=Path(__file__).resolve().parents[1]/'e2e/owned_menu_cancel.py'
CAPTION='OpenGeul Calc'


class PromptProbe:
    def __init__(self,origin,clock):
        self.clock=clock;self.deadline=clock()+5;self.bad=None;self.calls=[];self.observations=0
        self.shell=copy.deepcopy(origin['originalProcess']);self.engine=copy.deepcopy(origin['originalEngine'])
        self.binding=copy.deepcopy(origin['binding']);self.current_control=object()
    def process_snapshot(self,process):
        value=copy.deepcopy(self.shell)
        if self.bad=='shell':value['creationTime']+=1
        return value
    def open_engine(self,pid):self.calls.append(('open',pid));return 10
    def engine_snapshot(self,handle):
        value=copy.deepcopy(self.engine);value['handleValue']=handle
        if self.bad=='engine':value['creationTime']+=1
        return value
    def close_engine(self,handle):self.calls.append(('close',handle));return self.bad!='close'
    def close_provider(self):self.calls.append('provider-close');return self.bad!='provider-close'
    def enter_dpi(self,value):self.calls.append('dpi-enter');value.update(previousContext=1,verified=True)
    def restore_dpi(self,value):self.calls.append('dpi-restore');value['restored']=True
    def snapshot(self,api,document,dialog,caption):
        self.observations+=1
        doc=dict(hwnd=11,pid=77,threadId=7,rootHwnd=11,visible=True,enabled=False,rectangle=[0,0,600,400])
        modal=dict(hwnd=44,pid=77,threadId=7,rootHwnd=44,ownerHwnd=11,visible=True,enabled=True,
            className='#32770',title=CAPTION,rectangle=[10,20,300,200])
        control=dict(runtimeId=[42,4321],pid=77,nativeHwnd=4321,controlType='Button',
            visible=True,enabled=True,rectangle=[20,100,100,130])
        root=dict(runtimeId=[42,44],pid=77,nativeHwnd=44,controlType='Window',
            visible=True,enabled=True,rectangle=modal['rectangle'])
        row=dict(document=doc,dialog=modal,root=root,control=control,ancestry=[control,root],
            rootElementEquals=True,headingMatches=True,cancelMatches=True,headingCount=1,cancelCount=1,
            promptSchemaVerified=True,noticeMatches=True,noticeCount=1,promptButtonCount=3,
            promptTotalButtonCount=3,nonclientCloseCount=0,nonclientCloseProof=None,
            clientChoicesVerified=True,
            binding=dict(self.binding),attachmentValid=True,
            gui=dict(threadId=7,activeHwnd=44,focusHwnd=999,focusPid=77,focusRootHwnd=44,
                     captureHwnd=0,menuOwnerHwnd=0,flags=0),foreground=dict(hwnd=44,pid=77,rootHwnd=44))
        if self.bad=='owner':modal['ownerHwnd']=999
        if self.bad=='heading':row['headingMatches']=False
        if self.bad=='schema':row['promptSchemaVerified']=False
        if self.bad=='notice':row['noticeMatches']=False
        if self.bad=='buttons':row['promptButtonCount']=4
        if self.bad=='stale' and self.observations>1:control['runtimeId']=[42,9999]
        if self.bad=='capture':row['gui']['captureHwnd']=99
        if self.bad=='late':self.clock.now=self.deadline
        return row
    def point_snapshot(self,scope,point,control):
        return dict(point=list(point),hitHwnd=4321,pid=77,rootHwnd=44,
            withinControl=True,uiaMatches=self.bad!='hit')
    def move(self,point,value):self.clock.now+=.01;value['pointerReadback']=list(point)
    def click(self,value):
        self.clock.now+=.01;self.calls.append('click')
        value.update(inputCallAttempts=1,requestedInputs=2,insertedInputs=2,
            beforeClickCursorReadback=list(value['chosenPhysicalPoint']))
        if self.bad=='partial':
            value.update(insertedInputs=1,ownedButtonRelease={'requested':1,'inserted':1})
            raise AssertionError('partial cancel')
    def transition_snapshot(self,api,process,document,dialog,caption,purpose,control,*,context,evidence):
        self.calls.append(('transition',purpose));self.clock.now+=.01
        assert purpose=='MENU_CANCEL' and context['originalProcess']==self.shell
        return dict(accepted=True,transition='original-owned-dialog-destroyed',
            originalDialogAlive=False,originalDocumentAlive=True,dialogObservationCount=1)


class OwnedMenuCancelTests(unittest.TestCase):
    def feature(self):
        self.assertTrue(SOURCE.is_file(),'Native-menu TaskDialog cancel requires its own measured policy')
        spec=importlib.util.spec_from_file_location('tested_menu_cancel',SOURCE)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
    def fixture(self,command='exit',*,suite_root=None):
        module=self.feature()
        from test_owned_native_menu import Clock,Probe
        from owned_native_menu import click_native_menu_action
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);temporary=Path(tmp.name)
        root=temporary if suite_root is None else suite_root
        out=temporary/'evidence';out.mkdir();clock=Clock();clock.now=1.
        process=NS(pid=77,_handle=8,args=[str(root/'OpenGeul.Office.exe')],poll=lambda:None,
            opengeul_suite_root=root,opengeul_evidence_output=out,opengeul_evidence_case='blank-calc')
        api=NS(attachment=lambda hwnd:(55,56,88),user=NS(GetPropW=lambda hwnd,name:1))
        record=dict(windowHwnd=11,parentHwnd=55,childHwnd=56,officePid=88)
        origin=click_native_menu_action(api,process,11,record,command,probe=Probe(root,clock),clock=clock)
        clock.now+=.1;probe=PromptProbe(origin,clock)
        return module,api,process,record,clock,probe
    def run_cancel(self,fixture):
        m,a,p,r,c,probe=fixture
        return m.cancel_native_menu_prompt(a,p,11,r,44,CAPTION,probe=probe,clock=c)
    def test_native_exit_cancel_clicks_exact_custom_button_once_and_retires_only_its_handle(self):
        f=self.fixture();value=self.run_cancel(f);probe=f[-1]
        self.assertTrue(value['success']);self.assertEqual(value['kind'],'owned-shell-menu-cancel')
        self.assertEqual(value['deadline'],value['startedAt']+5)
        self.assertEqual(value['snapshots'][0]['control']['nativeHwnd'],4321)
        self.assertEqual(probe.calls.count('click'),1);self.assertIn(('close',10),probe.calls)
        self.assertTrue(value['engineHandleReleased']);self.assertTrue(value['dpiScope']['restored'])
        self.assertTrue(value['providerClientReleased'])
        self.assertGreater(probe.calls.index('provider-close'),probe.calls.index('dpi-restore'))
        self.assertEqual(value['after']['transition'],'original-owned-dialog-destroyed')
    def test_foreign_owner_heading_capture_stale_control_or_late_observation_never_click(self):
        for bad in ('owner','heading','schema','notice','buttons','capture','stale','late','hit'):
            with self.subTest(bad=bad):
                f=self.fixture();f[-1].bad=bad
                with self.assertRaises(AssertionError):self.run_cancel(f)
                self.assertNotIn('click',f[-1].calls);self.assertIn(('close',10),f[-1].calls)
    def test_original_shell_and_engine_generations_must_match_trigger(self):
        for bad in ('shell','engine'):
            with self.subTest(bad=bad):
                f=self.fixture();f[-1].bad=bad
                with self.assertRaises(AssertionError):self.run_cancel(f)
                self.assertNotIn('click',f[-1].calls)
                if bad=='engine':self.assertIn(('close',10),f[-1].calls)
    def test_missing_or_unrelated_native_origin_is_rejected_before_input(self):
        f=self.fixture('save')
        with self.assertRaises(AssertionError):self.run_cancel(f)
        self.assertNotIn('click',f[-1].calls)
        f=self.fixture();f[3]['nativeMenuActions']=[]
        with self.assertRaises(AssertionError):self.run_cancel(f)
        self.assertNotIn('click',f[-1].calls)
    def test_partial_insertion_preserves_primary_without_second_click(self):
        f=self.fixture();f[-1].bad='partial'
        with self.assertRaisesRegex(AssertionError,'partial cancel'):self.run_cancel(f)
        self.assertEqual(f[-1].calls.count('click'),1)
        self.assertTrue(f[3]['nativeMenuPromptCancels'][-1]['engineHandleReleased'])
    def test_failed_handle_release_cannot_qualify_cancel(self):
        f=self.fixture();f[-1].bad='close'
        with self.assertRaises(AssertionError):self.run_cancel(f)
        self.assertFalse(f[3]['nativeMenuPromptCancels'][-1]['success'])
    def test_failed_provider_release_cannot_qualify_cancel(self):
        f=self.fixture();f[-1].bad='provider-close'
        with self.assertRaises(AssertionError):self.run_cancel(f)
        value=f[3]['nativeMenuPromptCancels'][-1]
        self.assertFalse(value['success']);self.assertIn('AssertionError',value['cleanupErrors'])
        self.assertTrue(value['engineHandleReleased']);self.assertTrue(value['dpiScope']['restored'])
    def test_cancel_probe_uses_native_menu_private_provider_timeout_policy(self):
        from owned_native_menu import NativeMenuProbe
        self.assertTrue(issubclass(self.feature().NativeMenuCancelProbe,NativeMenuProbe))

    def test_entry_selects_probe_once_before_origin_replay_with_the_original_action_deadline(self):
        import native_menu_source_selection as source
        f=self.fixture();module,api,process,record,clock,probe=f;calls=[]
        replay=module.require_native_menu_action
        def select(actual,deadline,actual_clock,*,build,supplied=None):
            calls.append(('select',actual,deadline,actual_clock,supplied))
            return source.selected_native_menu_probe(actual,deadline,actual_clock,build=build,supplied=supplied)
        def origin(*args,**kwargs):calls.append(('origin',));return replay(*args,**kwargs)
        with patch.object(module,'selected_native_menu_probe',select,create=True),patch.object(module,'require_native_menu_action',origin):
            value=self.run_cancel(f)
        self.assertEqual([row[0] for row in calls],['select','origin'])
        self.assertIs(calls[0][1],process);self.assertIs(calls[0][3],clock);self.assertIs(calls[0][4],probe)
        self.assertEqual(calls[0][2],value['startedAt']+5)

    def test_cancel_constructor_forwards_the_identical_optional_source_selection(self):
        import inspect
        module=self.feature();self.assertIn('source_selection',inspect.signature(module.NativeMenuCancelProbe).parameters)
        context=self.source_context()[1];calls=[]
        def initialize(probe,deadline,clock,**options):calls.append((deadline,clock,options))
        with patch.object(module.NativeMenuProbe,'__init__',initialize):
            probe=module.NativeMenuCancelProbe(6.,lambda:1.,11,44,CAPTION,source_selection=context)
        self.assertEqual(calls[0][0],6.);self.assertIs(calls[0][2]['source_selection'],context)
        self.assertEqual((probe.document,probe.dialog,probe.expected_caption),(11,44,CAPTION))

    def test_actual_cancel_point_uses_strict_global_control_without_an_office_target(self):
        module=self.feature();probe=module.NativeMenuCancelProbe.__new__(module.NativeMenuCancelProbe)
        target=object();other=object();selected=[target];calls=[]
        probe._call=lambda fn,*args:fn(*args)
        def pid(hwnd,out):out._obj.value=77;return 7
        probe.user=NS(WindowFromPhysicalPoint=lambda point:4321,GetWindowThreadProcessId=pid,
            GetAncestor=lambda hwnd,kind:44,IsChild=lambda parent,child:False)
        probe._raw=lambda element:dict(nativeHwnd=4321)
        probe.desktop=NS(from_point=lambda *point:NS(element_info=NS(_element=selected[0])))
        probe.uia=NS(iuia=NS(CompareElements=lambda left,right:left is right))
        probe._provider_local_point_v4=lambda *args,**kwargs:calls.append('forbidden-local-provider')
        control=NS(element_info=NS(_element=target))
        self.assertNotIn('_active_target',vars(probe))
        try:result=probe.point_snapshot(44,[60,115],control)
        except AttributeError:self.fail('Shell Cancel incorrectly inherited the Office target dependency')
        self.assertEqual((result['pid'],result['rootHwnd'],result['hitHwnd']),(77,44,4321))
        self.assertIs(result['uiaMatches'],True);self.assertIs(result['withinControl'],True)
        selected[0]=other;self.assertIs(probe.point_snapshot(44,[60,115],control)['uiaMatches'],False)
        self.assertEqual(calls,[])

    @classmethod
    def source_context(cls):
        if not hasattr(cls,'_source_context'):
            from suite.tests.test_native_menu_source_selection import SourceMenuSelectionTests
            case=SourceMenuSelectionTests(methodName='test_prepares_actual_bare_gate_context_and_freezes_contexts')
            case.setUp();cls.addClassCleanup(case.doCleanups)
            cls._source_context=(case,case.selected(case.prepared()))
        return cls._source_context

    def selected_fixture(self):
        case,selection=self.source_context()
        f=self.fixture(suite_root=case.suite);module,api,process,record,clock,probe=f
        process.opengeul_source_menu_selection=selection;probe.source_selection=selection
        clock.now=selection.launch_deadline+200
        return f,selection

    def test_selected_entry_rechecks_once_and_joins_current_generation_before_dpi(self):
        import owned_native_menu as core
        import time
        self.assertTrue(callable(getattr(core,'_bind_source_generation',None)))
        f,selection=self.selected_fixture();module,api,process,record,clock,probe=f
        admission=selection.prepared.admission;calls=[];rechecks=[]
        verify=type(admission).verify_provider_files;bind=core._bind_source_generation
        def checked(actual,deadline):rechecks.append((actual,deadline));return verify(actual,deadline)
        def replay(*args,**kwargs):calls.append('origin');self.assertTrue(kwargs.get('source_admission') is admission)
        def binding(*args):
            calls.append('bind');self.assertNotIn('dpi-enter',probe.calls)
            self.assertEqual(args[5]['handleValue'],10);return bind(*args)
        with patch.object(time,'monotonic',clock),patch.object(type(admission),'verify_provider_files',checked), \
                patch.object(module,'require_native_menu_action',replay),patch.object(core,'_bind_source_generation',binding):
            value=self.run_cancel(f)
        self.assertEqual(calls,['origin','bind']);self.assertEqual(len(rechecks),1)
        self.assertIs(rechecks[0][0],admission);self.assertEqual(rechecks[0][1],value['deadline'])
        self.assertEqual(value['sourceMenu']['admission']['admissionSha256'],admission.admission_sha256)
        self.assertEqual(value['sourceMenu']['generation']['engineHandleValue'],10)
        self.assertEqual(value['sourceMenu']['generation']['shellHandleValue'],8)
        self.assertTrue(value['success'])

    def test_selected_factory_rejection_never_replays_origin_opens_or_inputs(self):
        import time
        for reason in ('probe','fake','pending','provider','late'):
            with self.subTest(reason=reason):
                f,selection=self.selected_fixture();module,api,process,record,clock,probe=f
                if reason=='probe':probe.source_selection=self.source_context()[0].selected(selection.prepared)
                elif reason=='fake':process.opengeul_source_menu_selection=True
                import native_menu_msaa_hit as hit
                admission=selection.prepared.admission;verify=type(admission).verify_provider_files
                def checked(actual,deadline):
                    if reason=='provider':raise ValueError('Synthetic provider recheck rejection')
                    result=verify(actual,deadline)
                    if reason=='late':clock.now=deadline
                    return result
                with patch.object(time,'monotonic',clock), \
                        patch.object(type(admission),'verify_provider_files',checked), \
                        patch.object(hit,'pending_msaa_hit',return_value=object() if reason=='pending' else None), \
                        patch.object(module,'require_native_menu_action',side_effect=AssertionError('Rejected selection reached origin')):
                    with self.assertRaises(ValueError):self.run_cancel(f)
                self.assertEqual(probe.calls,[])

    def test_attachment_must_be_current_before_generation_binding_or_dpi(self):
        f=self.fixture();f[1].attachment=lambda hwnd:(55,999,88)
        with self.assertRaises(AssertionError):self.run_cancel(f)
        self.assertNotIn('dpi-enter',f[-1].calls);self.assertNotIn('click',f[-1].calls)

    def schema_fixture(self,bad=None):
        """Exercise production fixed queries, retaining no arbitrary UIA name."""
        m=self.feature();probe=m.NativeMenuCancelProbe.__new__(m.NativeMenuCancelProbe)
        heading='변경 내용을 저장하시겠습니까?'
        notice='저장하지 않음을 선택하면 변경 내용이 사라집니다.'
        expected=[('Text',heading),('Text',notice),('Button','저장'),('Button','저장하지 않음'),('Button','취소')]
        queried=[];elements=[];probe.dialog=44
        for i,(kind,name) in enumerate(expected):
            row=dict(pid=77,controlType=kind,visible=True,enabled=True,
                nativeHwnd=100+i if kind=='Button' else 0,runtimeId=[42,100+i])
            if bad=='hidden' and name=='저장':row['visible']=False
            if bad=='disabled' and name=='저장하지 않음':row['enabled']=False
            if bad=='foreign' and name=='취소':row['pid']=999
            element=NS(CurrentName='wrong' if bad=='renamed' and name=='저장' else name,row=row)
            if not (bad=='notice-missing' and name==notice):elements.append((kind,name,element))
        if bad=='duplicate':elements.append(elements[-1])
        if bad=='extra':elements.append(('Button','unread',NS(row=dict(pid=77,controlType='Button',visible=True,enabled=True))))
        def find(scope,condition):
            self.assertEqual(scope,4);kind,name=condition;queried.append(condition)
            self.assertIn(condition,expected+[('Button',None),('Button','Close')])
            found=[e for k,n,e in elements if k==kind and (name is None or n==name)]
            return NS(Length=len(found),GetElement=lambda index:found[index])
        root=NS(FindAll=find,row=dict(pid=77,controlType='Window',visible=True,enabled=True))
        root.row.update(nativeHwnd=44,runtimeId=[42,44]);root.parent=None
        for _,_,element in elements:element.parent=root
        if bad and bad.startswith('titlebar'):
            prefix=[42,44,3,-2147483647,44,-2]
            bar=NS(parent=root,row=dict(pid=77,controlType='TitleBar',visible=True,enabled=True,
                nativeHwnd=0,runtimeId=prefix+[0]))
            close=NS(CurrentName='Close',CurrentAutomationId='',CurrentClassName='',parent=bar,
                row=dict(pid=77,controlType='Button',visible=True,enabled=True,nativeHwnd=0,runtimeId=prefix+[5]))
            elements.append(('Button','Close',close))
            if bad=='titlebar-client':close.parent=root
            if bad=='titlebar-foreign':bar.row['pid']=999
            if bad=='titlebar-root':bar.parent=NS(parent=None,row=dict(root.row,nativeHwnd=99,runtimeId=[42,99]))
            if bad=='titlebar-runtime':close.row['runtimeId']=[42,44,123]
            if bad=='titlebar-hwnd':close.row['nativeHwnd']=100
            if bad=='titlebar-id':close.CurrentAutomationId='CommandButton_103'
            if bad=='titlebar-class':close.CurrentClassName='ClientButton'
            if bad=='titlebar-renamed':close.CurrentName='Wrong'
            if bad=='titlebar-duplicate':elements.append(('Button','Close',close))
            if bad=='titlebar-pane':bar.parent=NS(parent=root,row=dict(pid=77,controlType='Pane',
                visible=True,enabled=True,nativeHwnd=50,runtimeId=[42,50]))
            if bad=='titlebar-hidden':close.row['visible']=False
            if bad=='titlebar-choice':elements[2][2].parent=bar
        probe._call=lambda fn,*args:fn(*args)
        probe._chrome=lambda element:dict(element.row)
        probe.window_snapshot=lambda hwnd:dict(hwnd=hwnd,pid=77,rootHwnd=44)
        probe.user=NS(IsChild=lambda parent,child:parent==44 and child in (102,103,104))
        probe.uia=NS(build_condition=lambda **kw:(kw['control_type'],kw.get('name')),tree_scope={'descendants':4},
            iuia=NS(CompareElements=lambda left,right:left is right,
                RawViewWalker=NS(GetParentElement=lambda element:element.parent)))
        return probe,root,queried,expected

    def test_actual_prompt_schema_uses_only_fixed_queries_and_exact_button_inventory(self):
        probe,root,queried,expected=self.schema_fixture()
        row=probe._prompt_schema(root)
        self.assertTrue(row['promptSchemaVerified']);self.assertTrue(row['noticeMatches'])
        self.assertEqual(row['noticeCount'],1);self.assertEqual(row['promptButtonCount'],3)
        self.assertEqual(set(queried),set(expected+[('Button',None)]))

    def test_actual_prompt_schema_rejects_missing_duplicate_extra_or_changed_fixed_chrome(self):
        for bad in ('notice-missing','duplicate','extra','hidden','disabled','foreign','renamed'):
            with self.subTest(bad=bad):
                probe,root,_,_=self.schema_fixture(bad)
                with self.assertRaises(AssertionError):probe._prompt_schema(root)
    def test_actual_prompt_schema_separates_verified_nonclient_close_from_three_choices(self):
        probe,root,queried,_=self.schema_fixture('titlebar')
        row=probe._prompt_schema(root)
        self.assertTrue(row['promptSchemaVerified']);self.assertEqual(row['promptButtonCount'],3)
        self.assertEqual(row['promptTotalButtonCount'],4);self.assertEqual(row['nonclientCloseCount'],1)
        self.assertEqual([part['controlType'] for part in row['nonclientCloseProof']['ancestry']],
            ['Button','TitleBar','Window'])
        self.assertIn(('Button','Close'),queried)
        f=self.fixture();boundary=f[-1];original_snapshot=boundary.snapshot
        def snapshot(*args):
            value=original_snapshot(*args)
            value.update({key:row[key] for key in ('promptSchemaVerified','promptButtonCount',
                'promptTotalButtonCount','nonclientCloseCount','nonclientCloseProof','clientChoicesVerified')})
            return value
        boundary.snapshot=snapshot;receipt=self.run_cancel(f)
        self.assertTrue(receipt['success']);self.assertEqual(boundary.calls.count('click'),1)
        self.assertTrue(receipt['engineHandleReleased']);self.assertTrue(receipt['providerClientReleased'])
    def test_actual_prompt_schema_never_exempts_a_fake_nonclient_close(self):
        for bad in ('client','foreign','root','runtime','hwnd','id','class','renamed','duplicate','pane','hidden','choice'):
            with self.subTest(bad=bad):
                probe,root,_,_=self.schema_fixture('titlebar-'+bad)
                with self.assertRaises(AssertionError):probe._prompt_schema(root)
    def test_same_origin_cannot_be_replayed_for_another_cancel_attempt(self):
        f=self.fixture();self.run_cancel(f);before=f[-1].calls.count('click')
        with self.assertRaises(AssertionError):self.run_cancel(f)
        self.assertEqual(f[-1].calls.count('click'),before)

    def actual_transition_fixture(self,*,changed_owner=False):
        """Keep the actual old dialog branch; replace only its native calls."""
        from owned_control_actions import NativeControlProbe
        f=self.fixture();probe=f[-1];queries=[]
        probe._call=lambda function,*args:function(*args)
        probe.user=NS(IsWindow=lambda hwnd:hwnd==11 or changed_owner and hwnd==44)
        def window(hwnd):
            queries.append(hwnd)
            if hwnd==11:return dict(hwnd=11,pid=77,threadId=7,rootHwnd=11,visible=True,enabled=True)
            assert hwnd==44
            return dict(hwnd=44,pid=77,threadId=7,rootHwnd=44,ownerHwnd=999,
                visible=True,enabled=True,className='#32770',title=CAPTION)
        probe._window=window
        probe.transition_snapshot=MethodType(NativeControlProbe.transition_snapshot,probe)
        probe.target_snapshot=lambda *a,**k:self.fail('Dialog retirement must not invoke the legacy menu recipient proof')
        return f,queries

    def test_actual_dialog_transition_branch_accepts_new_purpose_after_original_dialog_disappears(self):
        f,queries=self.actual_transition_fixture();value=self.run_cancel(f)
        self.assertTrue(value['success']);self.assertEqual(value['purpose'],'MENU_CANCEL')
        self.assertEqual(value['after']['transition'],'original-owned-dialog-destroyed')
        self.assertEqual(queries,[11,11])
        self.assertEqual(f[-1].calls.count('click'),1)

    def test_actual_dialog_transition_branch_rejects_replacement_owner_without_another_click(self):
        f,queries=self.actual_transition_fixture(changed_owner=True)
        with self.assertRaisesRegex(AssertionError,'dialog identity changed'):self.run_cancel(f)
        self.assertIn(44,queries);self.assertEqual(f[-1].calls.count('click'),1)
        self.assertTrue(f[3]['nativeMenuPromptCancels'][-1]['engineHandleReleased'])
