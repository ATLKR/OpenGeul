"""Fake UNO command boundaries; these tests do not prove native GUI behavior."""
import importlib
from pathlib import Path
from types import SimpleNamespace as NS
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'worker'))


class CalcSaveTests(unittest.TestCase):
    def setUp(self):
        self.reset_boundary()

    def reset_boundary(self):
        self.api = importlib.import_module('calc_save')
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'Original space 한글.xlsx'
        self.target = Path(self.temp.name) / 'Selected.xlsx'
        self.calls = []
        self.url = self.path.as_uri()
        self.filter = 'Calc MS Excel 2007 XML'
        self.values = {'WarnAlienFormat': True, 'AlwaysSaveAs': True}
        self.config = NS(getPropertyValue=lambda n: self.values[n],
            setPropertyValue=lambda n, v: self.values.__setitem__(n, v),
            commitChanges=lambda: self.calls.append(('config-commit',)))
        self.controller = NS()
        self.peer = NS(getWindowHandle=lambda *a: 456)
        self.frame = NS(getController=lambda: self.controller, getContainerWindow=lambda: self.peer,
            activate=lambda: self.calls.append(('activate',)), isActive=lambda: True,
            queryDispatch=lambda *a: self.fail('The intercepted frame must not be queried'))
        self.document = NS(getCurrentController=lambda: self.controller,
            supportsService=lambda n: n == self.api.CALC_SERVICE,
            getURL=lambda: self.url, hasLocation=lambda: bool(self.url), isReadonly=lambda: False,
            getArgs=lambda: (NS(Name='FilterName', Value=self.filter),), isModified=lambda: False,
            store=lambda: self.fail('Native Save is the sole persistence operation'),
            storeAsURL=lambda *a: self.fail('Native SaveAs is the sole persistence operation'))
        self.controller.getModel = lambda: self.document
        self.controller.getFrame = lambda: self.frame
        self.dispatch = NS(dispatchWithNotification=lambda *a: self.fail('Helper must marshal notification'))
        def query_native(url, target, flags):
            self.assertEqual('.uno:', url.Protocol)
            self.assertIn(url.Path, ('Save', 'SaveAs'))
            self.assertEqual(url.Complete, url.Protocol + url.Path)
            return self.calls.append(('query-native', (url, target, flags))) or self.dispatch
        self.controller.queryDispatch = query_native
        self.result = NS(State=1, Result=True)
        def execute(provider, command, target, flags, props):
            self.calls.append(('execute', provider, command, target, flags, {p.Name:p.Value for p in props}))
            if self.effect: self.effect()
            return self.result
        self.effect = None
        self.helper = NS(executeDispatch=execute)
        def create(name, context):
            if name.endswith('ConfigurationProvider'):
                return NS(createInstanceWithArguments=lambda *a: self.config)
            if name.endswith('DispatchHelper'): return self.helper
            if name.endswith('FilterFactory'): return NS(getByName=lambda name:(NS(Name='Flags',Value=3),))
            self.fail('Unexpected service ' + name)
        self.context = NS(ServiceManager=NS(createInstanceWithContext=create))
        from urllib.parse import unquote, urlsplit
        self.uno = NS(createUnoStruct=lambda n:NS(),
            fileUrlToSystemPath=lambda url: unquote(urlsplit(url).path))
        self.desktop=NS(getFrames=lambda:NS(getCount=lambda:1,getByIndex=lambda i:self.frame))
        self.frame.getCreator=lambda:self.desktop
        self.backend = NS(desktop=self.desktop,document=self.document, frame=self.frame, peer=self.peer, context=self.context,
            uno=self.uno, process=NS(poll=lambda:None),
            window_api=NS(validate_child=lambda c,p:self.calls.append(('validate-child',c,p))),
            _property=lambda n,v:NS(Name=n,Value=v))
        self.abort = object()
        self.patcher = patch.object(self.api, 'make_interaction_handler', return_value=self.abort)
        self.patcher.start(); self.addCleanup(self.patcher.stop)

    def transaction(self):
        return self.api.CalcSaveTransaction(self.backend, {'xlsx':self.filter,'ods':'calc8'}, self.path, 123, 456)

    def executed(self): return [c for c in self.calls if c[0]=='execute']

    def test_backend_calc_save_routes_to_transaction_without_store(self):
        native=importlib.import_module('native'); backend=native.UnoBackend(Path(self.temp.name))
        backend.module_factory='private:factory/scalc'
        backend.document=self.document
        backend.calc_save=NS(save=lambda p,f:self.calls.append(('calc-save',p,f)))
        backend.save(None,None)
        self.assertIn(('calc-save',None,None),self.calls)

    def test_attach_captures_calc_transaction_before_revealing_owned_editor(self):
        native=importlib.import_module('native');calls=[];value=object()
        peer=NS(setProperty=lambda *a:None,getProperty=lambda n:'OpenGeul Calc',
            setPosSize=lambda *a:None,setVisible=lambda v:calls.append('visible'),getWindowHandle=lambda *a:456)
        frame=NS(initialize=lambda p:None,setName=lambda n:None,
            registerDispatchProviderInterceptor=lambda i:None,activate=lambda:calls.append('activate'))
        desktop=NS(getFrames=lambda:NS(append=lambda f:None),loadComponentFromURL=lambda *a:self.document)
        services={'com.sun.star.frame.Desktop':desktop,'com.sun.star.frame.Frame':frame,
            'com.sun.star.awt.Toolkit':NS(createSystemChild=lambda *a:peer)}
        context=NS(ServiceManager=NS(createInstanceWithContext=lambda n,c:services[n]))
        windows=NS(validate_parent=lambda h:None,validate_child=lambda c,p:calls.append('validated'))
        backend=native.UnoBackend(Path(self.temp.name),window_api=windows,uno_loader=lambda:NS(
            Any=lambda *a:None,createUnoStruct=lambda n:NS()),connector=lambda *a:context)
        backend._start_runtime=lambda:None
        backend._isolate_legacy_style_controls=lambda *a:None;backend._bootstrap_ui=lambda *a:None
        module=dict(factory='private:factory/scalc',displayName='OpenGeul Calc',filters={'xlsx':self.filter})
        def capture(*args):
            calls.append('capture');self.assertIs(backend,args[0]);self.assertIs(self.document,backend.document)
            self.assertEqual((module['filters'],self.path,123,456),args[1:]);return value
        with patch.object(native,'make_interceptor',return_value=object()), \
                patch.object(native,'make_interaction_handler',return_value=object()), \
                patch.object(self.api,'CalcSaveTransaction',side_effect=capture):
            backend.attach(123,module,640,480,self.path)
        self.assertIs(value,backend.calc_save)
        self.assertEqual(['validated','capture','visible','activate'],calls)

    def test_confirmed_backend_cleanup_releases_retained_calc_controller(self):
        native=importlib.import_module('native');backend=native.UnoBackend(Path(self.temp.name))
        backend.calc_save=object();backend.cleanup()
        self.assertIsNone(backend.calc_save)

    def test_current_save_uses_retained_controller_main_thread_and_one_native_operation(self):
        save = self.transaction(); save.save(None, None)
        self.assertEqual({'WarnAlienFormat':False,'AlwaysSaveAs':False},self.values)
        self.assertEqual(1,len(self.executed()))
        _,provider,command,target,flags,args=self.executed()[0]
        self.assertIs(provider,self.controller)
        self.assertEqual(('.uno:Save','_self',0),(command,target,flags))
        self.assertIs(args['DontTerminateEdit'],False)
        self.assertIs(args['OnMainThread'],True)
        self.assertIs(args['InteractionHandler'],self.abort)
        self.assertNotIn('URL',args);self.assertNotIn('FilterName',args)
        self.assertIs(save.path,self.path)

    def test_save_as_uses_only_selected_url_filter_and_advances_after_success(self):
        save=self.transaction();self.effect=lambda:setattr(self,'url',self.target.as_uri())
        save.save(self.target,self.filter)
        row=self.executed()[0];self.assertEqual('.uno:SaveAs',row[2])
        self.assertEqual(self.target.as_uri(),row[5]['URL']);self.assertEqual(self.filter,row[5]['FilterName'])
        self.assertIs(row[5]['Overwrite'],True);self.assertNotIn('SaveTo',row[5])
        self.assertEqual(self.target,save.path)

    def test_native_cross_format_save_as_updates_descriptor_before_next_save(self):
        target=self.target.with_suffix('.ods');save=self.transaction()
        self.effect=lambda:(setattr(self,'url',target.as_uri()),setattr(self,'filter','calc8'))
        save.save(target,'calc8');self.effect=None;save.save(None,None)
        self.assertEqual(['.uno:SaveAs','.uno:Save'],[r[2] for r in self.executed()])
        self.assertEqual(target,save.path)

    def test_effective_config_failure_stops_initialization_without_native_write(self):
        self.config.setPropertyValue=lambda n,v:None
        with self.assertRaises(self.api.WorkerError):self.transaction()
        self.assertEqual([],self.executed())

    def test_reentrant_save_is_rejected_without_a_second_native_operation(self):
        save=self.transaction();rejected=[]
        def nested():
            with self.assertRaises(self.api.WorkerError):save.save(None,None)
            rejected.append(True)
        self.effect=nested;save.save(None,None)
        self.assertEqual([True],rejected);self.assertEqual(1,len(self.executed()))

    def test_active_owned_frame_must_survive_native_transaction(self):
        save=self.transaction();self.effect=lambda:setattr(self.frame,'isActive',lambda:False)
        with self.assertRaises(self.api.WorkerError):save.save(None,None)
        self.assertEqual(1,len(self.executed()))

    def test_false_unknown_empty_or_untyped_native_result_is_failure_without_fallback(self):
        for result in [None, NS(State=0,Result=True),NS(State=2,Result=True),NS(State=1,Result=False),
                       NS(State=1,Result=1),NS(State=1,Result='true'),NS(State=True,Result=True),NS(State=1)]:
            with self.subTest(result=result):
                save=self.transaction();self.result=result;self.calls.clear()
                with self.assertRaises(self.api.WorkerError):save.save(None,None)
                self.assertEqual(1,len(self.executed()));self.assertEqual(self.path,save.path)

    def test_cancelled_save_as_keeps_original_owned_path_and_model(self):
        save=self.transaction();self.result=NS(State=0,Result=False)
        with self.assertRaises(self.api.WorkerError):save.save(self.target,self.filter)
        self.assertEqual(self.path,save.path);self.assertIs(self.document,self.backend.document)
        self.assertEqual(1,len(self.executed()))

    def test_wrong_controller_frame_peer_or_native_child_fails_before_dispatch(self):
        mutations=[lambda:setattr(self.document,'getCurrentController',lambda:object()),
            lambda:setattr(self.controller,'getModel',lambda:object()),
            lambda:setattr(self.controller,'getFrame',lambda:object()),
            lambda:setattr(self.frame,'getController',lambda:object()),
            lambda:setattr(self.frame,'getContainerWindow',lambda:object()),
            lambda:setattr(self.peer,'getWindowHandle',lambda *a:999),
            lambda:setattr(self.backend.process,'poll',lambda:1),
            lambda:setattr(self.frame,'getCreator',lambda:object()),
            lambda:setattr(self.desktop,'getFrames',lambda:NS(getCount=lambda:0))]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                self.reset_boundary();save=self.transaction();mutate()
                with self.assertRaises(self.api.WorkerError):save.save(None,None)
                self.assertEqual([],self.executed())

    def test_changed_effective_policy_current_url_readonly_or_filter_fails_before_dispatch(self):
        changes=[lambda:self.values.update(WarnAlienFormat=True),lambda:self.values.update(AlwaysSaveAs=True),
            lambda:setattr(self,'url',self.target.as_uri()),lambda:setattr(self.document,'isReadonly',lambda:True),
            lambda:setattr(self,'filter','foreign-filter'),lambda:setattr(self,'url','file://server/share/other.xlsx')]
        for change in changes:
            with self.subTest(change=change):
                self.reset_boundary();save=self.transaction();change()
                with self.assertRaises(self.api.WorkerError):save.save(None,None)
                self.assertEqual([],self.executed())

    def test_native_dispatch_disposal_or_missing_notification_fails_without_storage_fallback(self):
        save=self.transaction();self.dispatch=NS(dispatch=lambda *a:None)
        with self.assertRaises(self.api.WorkerError):save.save(None,None)
        self.assertEqual([],self.executed())

    def test_failed_postconditions_never_advance_owned_path_or_retry(self):
        for effect in [lambda:None,lambda:setattr(self.document,'getCurrentController',lambda:object()),
                       lambda:setattr(self.document,'isModified',lambda:True)]:
            with self.subTest(effect=effect):
                self.reset_boundary();save=self.transaction();self.effect=effect
                with self.assertRaises(self.api.WorkerError):save.save(self.target,self.filter)
                self.assertEqual(self.path,save.path);self.assertEqual(1,len(self.executed()))

    def test_wrong_native_filter_after_success_does_not_advance_owned_path(self):
        save=self.transaction()
        self.effect=lambda:(setattr(self,'url',self.target.as_uri()),setattr(self,'filter','foreign-filter'))
        with self.assertRaises(self.api.WorkerError):save.save(self.target,self.filter)
        self.assertEqual(self.path,save.path);self.assertEqual(1,len(self.executed()))

    def test_session_failed_native_save_as_preserves_attached_original_path(self):
        from session import DocumentSession
        save=self.transaction();self.backend.save=save.save;self.result=NS(State=0,Result=False)
        session=DocumentSession(Path(self.temp.name),{'calc':{'filters':{'xlsx':self.filter}}})
        session.state='attached';session.module='calc';session.path=self.path;session.backend=self.backend
        with self.assertRaises(self.api.WorkerError) as caught:
            session.dispatch('save',{'path':str(self.target),'filter':self.filter})
        self.assertEqual('save_failed',caught.exception.code)
        self.assertEqual('attached',session.state);self.assertEqual(self.path,session.path)
        self.assertIs(self.backend,session.backend);self.assertEqual(1,len(self.executed()))

    def test_new_document_requires_suite_selected_destination(self):
        self.url='';save=self.api.CalcSaveTransaction(self.backend,{'xlsx':self.filter},None,123,456)
        with self.assertRaises(self.api.WorkerError):save.save(None,None)
        self.assertEqual([],self.executed())

    def test_selected_extension_and_filter_must_match_even_at_native_boundary(self):
        save=self.transaction()
        for path,filter_name in [(self.target,'calc8'),(self.target.with_suffix('.bad'),self.filter)]:
            with self.subTest(path=path),self.assertRaises(self.api.WorkerError):save.save(path,filter_name)
        self.assertEqual([],self.executed())


if __name__=='__main__':unittest.main()
