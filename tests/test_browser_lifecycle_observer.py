import importlib.util,json,tempfile,sys
from pathlib import Path
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];E2E=ROOT/'e2e'
def load():
    path=E2E/'lifecycle_observer.py';assert path.is_file(),'numeric lifecycle observer missing'
    spec=importlib.util.spec_from_file_location('browser_lifecycle_candidate',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
class Emitter:
    def __init__(self):self.handlers={};self.registered=[];self.removed=[]
    def on(self,event,handler):self.registered.append(event);self.handlers.setdefault(event,[]).append(handler)
    def remove_listener(self,event,handler):self.removed.append(event);self.handlers[event].remove(handler)
    def emit(self,event,*args,**kwargs):
        for handler in list(self.handlers.get(event,())):handler(*args,**kwargs)
class Clock:
    def __init__(self):self.value=10
    def __call__(self):self.value+=10;return self.value
class Tests(unittest.TestCase):
    def make(self,**kwargs):return load().LifecycleObserver(clock=Clock(),**kwargs)
    def test_public_events_are_distinct_and_precleanup(self):
        r=self.make();b,c,p=Emitter(),Emitter(),Emitter();r.bind_browser(b);r.bind_context(c);r.bind_page(p)
        p.emit('crash');p.emit('close');b.emit('disconnected');c.emit('close')
        rows=r.snapshot()['rows'];self.assertEqual([v['kind']for v in rows],[2,1,4,3]);self.assertTrue(all(v['cleanupStarted']is False for v in rows))
    def test_cleanup_delivery_is_marked_without_claiming_os_time(self):
        r=self.make();p=Emitter();r.bind_page(p);r.phase(9);r.cleanup();p.emit('close')
        row=r.snapshot()['rows'][-1];self.assertTrue(row['cleanupStarted']);self.assertEqual(row['phase'],13)
    def test_callback_payload_is_never_read(self):
        class Poison:
            def __str__(self):raise AssertionError('no payload')
            def __repr__(self):raise AssertionError('no payload')
            def __iter__(self):raise AssertionError('no payload')
        r=self.make();p=Emitter();r.bind_page(p);p.emit('crash',Poison());self.assertEqual(r.snapshot()['rows'][0]['kind'],2)
    def test_callback_keywords_cannot_override_fixed_event_kind(self):
        r=self.make();p=Emitter();r.bind_page(p);p.emit('close',kind=999,owner=-2)
        self.assertEqual((r.snapshot()['rows'][0]['kind'],r.snapshot()['rows'][0]['owner']),(1,3))
    def test_only_original_emitter_can_bind(self):
        r=self.make();a,b=Emitter(),Emitter();self.assertTrue(r.bind_page(a));self.assertFalse(r.bind_page(b));b.emit('close');self.assertEqual(r.snapshot()['rows'],[])
    def test_repeat_binding_does_not_duplicate_callbacks(self):
        r=self.make();p=Emitter();r.bind_page(p);r.bind_page(p);p.emit('close');self.assertEqual(len(r.snapshot()['rows']),1);self.assertEqual(p.registered,['close','crash'])
    def test_capacity_is_bounded_and_overflow_explicit(self):
        r=self.make();p=Emitter();r.bind_page(p)
        for _ in range(200):p.emit('close')
        x=r.snapshot();self.assertEqual(len(x['rows']),128);self.assertEqual(x['droppedCount'],72);self.assertFalse(x['callbackWindowComplete'])
    def test_clock_regression_and_invalid_type_are_unknown(self):
        r=self.make();r.phase(1);r.clock=lambda:1;r.phase(2);self.assertFalse(r.snapshot()['clockValid']);self.assertEqual(len(r.snapshot()['rows']),1)
        for bad in(True,-1,1.0):
            r=self.make();r.clock=lambda:bad;r.phase(1);self.assertFalse(r.snapshot()['clockValid'])
    def test_clock_exception_does_not_escape(self):
        r=self.make();r.clock=lambda:(_ for _ in()).throw(OSError());r.phase(1);self.assertFalse(r.snapshot()['clockValid'])
    def test_missing_subscription_is_explicit(self):
        class Bad(Emitter):
            def on(self,event,handler):raise OSError()
        r=self.make();self.assertFalse(r.bind_page(Bad()));self.assertEqual(r.snapshot()['coverageBits'],0);self.assertGreater(r.snapshot()['diagnosticErrors'],0)
    def test_detach_only_own_listeners_and_finish_once(self):
        saved=[];r=self.make(writer=lambda path,data:saved.append(data));p=Emitter();other=lambda *_:None;p.on('close',other);r.bind_page(p)
        with tempfile.TemporaryDirectory()as folder:
            self.assertTrue(r.finish(Path(folder)/'lifecycle.json'));self.assertFalse(r.finish(Path(folder)/'lifecycle.json'))
        self.assertEqual(p.handlers['close'],[other]);self.assertEqual(len(saved),1);n=len(r.snapshot()['rows']);p.emit('crash');self.assertEqual(len(r.snapshot()['rows']),n)
    def test_writer_failure_never_masks_primary_exception(self):
        def fail(*_):raise OSError()
        r=self.make(writer=fail);original=RuntimeError('synthetic-only')
        try:
            try:raise original
            finally:self.assertFalse(r.finish(Path('synthetic')))
        except RuntimeError as caught:self.assertIs(caught,original)
    def test_disabled_native_path_has_no_calls_or_file(self):
        calls=[];r=load().LifecycleObserver(enabled=False,clock=lambda:calls.append(1),writer=lambda *_:calls.append(2));p=Emitter()
        r.bind_page(p);r.phase(1);r.cleanup();r.finish(Path('unused'))
        self.assertEqual(calls,[]);self.assertEqual(p.registered,[])
    def test_fixed_error_class_only(self):
        class TargetClosedError(Exception):
            def __str__(self):raise AssertionError('error text forbidden')
        r=self.make();r.failed(TargetClosedError());x=r.snapshot();self.assertEqual(x['rows'][-1]['errorCode'],2)
    def test_unknown_phase_and_numeric_payload_schema(self):
        r=self.make();r.phase(True);self.assertGreater(r.snapshot()['diagnosticErrors'],0);r.phase(9)
        x=r.snapshot();self.assertFalse(x['qualification']);self.assertTrue(all(type(v)in(int,bool)for row in x['rows']for v in row.values()));self.assertNotIn('message',json.dumps(x))
    def test_callback_window_health_is_not_live_or_os_completeness(self):
        r=self.make(writer=lambda *_:None);r.bind_browser(Emitter());r.bind_context(Emitter());r.bind_page(Emitter())
        self.assertFalse(r.snapshot()['callbackWindowComplete']);r.finish(Path('synthetic'))
        self.assertTrue(r.snapshot()['callbackWindowComplete']);self.assertIs(r.snapshot()['osCauseProven'],False)
    def test_base_exception_clock_is_nonfatal_metadata(self):
        class Stop(BaseException):pass
        def fail():raise Stop()
        r=self.make();r.clock=fail;r.phase(1);self.assertFalse(r.snapshot()['clockValid'])
        r=load().LifecycleObserver(clock=fail);self.assertFalse(r.snapshot()['clockValid'])
    def test_base_exception_listener_and_detach_are_nonfatal_metadata(self):
        class Stop(BaseException):pass
        class BadOn(Emitter):
            def on(self,*_):raise Stop()
        class BadRemove(Emitter):
            def remove_listener(self,*_):raise Stop()
        r=self.make(writer=lambda *_:None);self.assertFalse(r.bind_page(BadOn()));r.finish(Path('synthetic'));self.assertGreater(r.snapshot()['diagnosticErrors'],0)
        r=self.make(writer=lambda *_:None);r.bind_page(BadRemove());r.finish(Path('synthetic'));self.assertGreater(r.snapshot()['diagnosticErrors'],0)
    def test_cancellation_without_primary_still_propagates(self):
        for kind in(KeyboardInterrupt,SystemExit):
            with self.subTest(kind=kind.__name__):
                r=self.make()
                def cancel():raise kind()
                r.clock=cancel
                with self.assertRaises(kind):r.phase(1)
    def test_diagnostic_interrupt_cannot_mask_active_primary(self):
        def cancel(*_):raise KeyboardInterrupt()
        r=self.make(writer=cancel);primary=RuntimeError('synthetic-only')
        try:
            try:raise primary
            finally:self.assertFalse(r.finish(Path('synthetic')))
        except BaseException as caught:self.assertIs(caught,primary)

def driver():
    for p in(str(ROOT),str(E2E)):
        if p not in sys.path:sys.path.insert(0,p)
    spec=importlib.util.spec_from_file_location('candidate_browser_driver',E2E/'driver.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
class DriverTests(unittest.TestCase):
    def exercise(self,*,failure=True,event='crash',sink_failure=False,sink_exception=None,cancel_phase=None,cancel_error=None):
        d=driver();calls=[]
        real_observer=d.LifecycleObserver;held={}
        def make_observer(**kwargs):
            observer=real_observer(**kwargs);held['observer']=observer
            clock=observer.clock;raised=False
            def interrupted_clock():
                nonlocal raised
                if cancel_phase is not None and observer.current_phase==cancel_phase and not raised:
                    raised=True;raise cancel_error
                return clock()
            observer.clock=interrupted_clock
            return observer
        class TargetClosedError(Exception):
            def __str__(self):raise AssertionError('message must remain opaque')
        original=TargetClosedError()
        class Locator:
            def set_input_files(self,*a,**kw):calls.append('file-input')
            def wait_for(self,*a,**kw):calls.append('textarea-ready')
        class Page(Emitter):
            timeout=None;wait_timeout=None
            def set_default_timeout(self,value):self.timeout=value;calls.append('default-timeout')
            def locator(self,*a,**kw):return Locator()
            def goto(self,*a,**kw):calls.append('goto')
            def wait_for_function(self,*a,**kw):
                calls.append('wait-loaded');self.wait_timeout=kw.get('timeout')
                if failure:self.emit(event,self);raise original
            def screenshot(self,*a,**kw):calls.append('screenshot')
            def evaluate(self,*a,**kw):return {'platform':'synthetic','userAgent':'synthetic'}
        page=Page()
        class Tracing:
            def start(self,*a,**kw):calls.append('trace-start')
            def stop(self,*a,**kw):calls.append('trace-stop')
        class Context(Emitter):
            tracing=Tracing()
            def add_init_script(self,*a,**kw):calls.append('init-script')
            def new_page(self):calls.append('page');return page
        context=Context()
        class Browser(Emitter):
            version='synthetic'
            def new_context(self,*a,**kw):calls.append('context');return context
            def close(self):calls.append('browser-close');page.emit('close',page);context.emit('close',context);self.emit('disconnected',self)
        browser=Browser()
        class BrowserType:
            def launch(self,*a,**kw):calls.append('launch');return browser
        class Playwright:
            webkit=BrowserType()
            def start(self):calls.append('start');return self
            def stop(self):calls.append('playwright-stop')
        class Expect:
            def to_contain_text(self,*a,**kw):calls.append('picker-expect')
            def to_have_css(self,*a,**kw):calls.append('style-ready')
        def writer(*args):raise sink_exception if sink_exception is not None else OSError()
        with tempfile.TemporaryDirectory()as folder:
            output=Path(folder)/'session';fixture=Path(folder)/'synthetic.hwpx';fixture.write_bytes(b'synthetic-only')
            with patch.object(d,'sync_playwright',return_value=Playwright()),patch.object(d,'expect',return_value=Expect()),patch.object(d,'LifecycleObserver',side_effect=make_observer):
                if sink_failure:
                    owner=sys.modules['lifecycle_observer'].LifecycleObserver
                    with patch.object(owner,'_write',side_effect=writer):
                        try:d.Session('browser',output,fixture,browser='webkit')
                        except BaseException as error:self.assertIs(error,original)
                elif failure:
                    caught=None
                    try:d.Session('browser',output,fixture,browser='webkit')
                    except BaseException as error:caught=error
                    self.assertIs(caught,original)
                else:
                    session=d.Session('browser',output,fixture,browser='webkit')
                    if cancel_error is None:session.close()
                    else:
                        caught=None
                        try:session.close()
                        except BaseException as error:caught=error
                        self.assertIs(caught,cancel_error,'Original diagnostic cancellation must survive cleanup')
                        self.assertTrue(held['observer'].finished,'Recorder cleanup must complete before propagation')
                        self.assertEqual(held['observer'].handlers,[])
            path=output/'lifecycle.json';data=json.loads(path.read_bytes())if path.exists()else None
            runtime=(output/'runtime.json').exists()
        return calls,page,data,runtime
    def test_startup_failure_events_precede_cleanup_and_preserve_primary(self):
        calls,page,data,runtime=self.exercise();self.assertIsNotNone(data);self.assertFalse(runtime)
        first=next(r for r in data['rows']if r['kind']==2);self.assertFalse(first['cleanupStarted']);self.assertEqual(first['phase'],9)
        later=[r for r in data['rows']if r['kind']in(1,3,4)];self.assertTrue(later and all(r['cleanupStarted']for r in later))
        self.assertEqual(page.wait_timeout,60000);self.assertEqual(page.timeout,15000)
        self.assertEqual(calls,['start','launch','context','init-script','page','trace-start','default-timeout','goto','picker-expect','file-input','wait-loaded','screenshot','trace-stop','browser-close','playwright-stop'])
    def test_close_and_crash_remain_distinct_in_actual_driver(self):
        _,_,data,_=self.exercise(event='close');self.assertIsNotNone(data)
        self.assertEqual([r['kind']for r in data['rows']if not r['cleanupStarted']and r['kind']],[1])
    def test_sink_failure_preserves_original_error_and_close_count(self):
        calls,_,data,_=self.exercise(sink_failure=True);self.assertIsNone(data);self.assertEqual(calls.count('browser-close'),1);self.assertEqual(calls.count('playwright-stop'),1)
    def test_healthy_driver_only_records_cleanup_termination(self):
        _,_,data,runtime=self.exercise(failure=False);self.assertTrue(runtime);self.assertIsNotNone(data)
        self.assertTrue(all(r['cleanupStarted']for r in data['rows']if r['kind']));self.assertFalse(data['qualification'])
    def test_diagnostic_base_exception_preserves_actual_driver_primary(self):
        class Stop(BaseException):pass
        for error in(Stop(),KeyboardInterrupt()):
            with self.subTest(kind=type(error).__name__):
                calls,_,data,_=self.exercise(sink_failure=True,sink_exception=error)
                self.assertIsNone(data);self.assertEqual(calls.count('browser-close'),1);self.assertEqual(calls.count('playwright-stop'),1)

class DeferredCancellationTests(unittest.TestCase):
    def make(self,**kwargs):return load().LifecycleObserver(clock=Clock(),**kwargs)
    def test_cleanup_scope_defers_same_cancellation_until_exit(self):
        for kind in(KeyboardInterrupt,SystemExit):
            with self.subTest(kind=kind.__name__):
                r=self.make(writer=lambda *_:None);cancel=kind();markers=[];caught=None
                try:
                    with r.cleanup_scope():
                        r.clock=lambda:(_ for _ in()).throw(cancel);r.cleanup();markers.append('after-entry')
                        r.phase(17);markers.append('after-phase');r.finish(Path('synthetic'));markers.append('after-finish')
                except BaseException as error:caught=error
                self.assertIs(caught,cancel);self.assertEqual(markers,['after-entry','after-phase','after-finish'])
    def test_nested_scope_propagates_once_at_outer_exit(self):
        r=self.make(writer=lambda *_:None);cancel=KeyboardInterrupt();caught=None;inside=False
        try:
            with r.cleanup_scope():
                with r.cleanup_scope():
                    r.clock=lambda:(_ for _ in()).throw(cancel);r.phase(17)
                inside=True;r.finish(Path('synthetic'))
        except BaseException as error:caught=error
        self.assertTrue(inside);self.assertIs(caught,cancel)
    def test_original_failure_after_deferral_wins(self):
        r=self.make();cancel=SystemExit();primary=RuntimeError('synthetic-only');caught=None
        try:
            with r.cleanup_scope():
                r.clock=lambda:(_ for _ in()).throw(cancel);r.phase(17)
                raise primary
        except BaseException as error:caught=error
        self.assertIs(caught,primary)
    def test_finish_detaches_remaining_listeners_before_cancellation(self):
        cancel=KeyboardInterrupt();calls=[]
        class CancelOnRemove(Emitter):
            def remove_listener(self,event,handler):
                calls.append(event);super().remove_listener(event,handler)
                if len(calls)==1:raise cancel
        r=self.make(writer=lambda *_:calls.append('write'));page=CancelOnRemove();r.bind_page(page);caught=None
        try:r.finish(Path('synthetic'))
        except BaseException as error:caught=error
        self.assertIs(caught,cancel);self.assertEqual(calls,['close','crash','write']);self.assertTrue(r.finished)
    def test_recovered_temporary_exception_does_not_discard_cancellation(self):
        r=self.make(writer=lambda *_:None);cancel=KeyboardInterrupt();caught=None;done=False
        try:
            with r.cleanup_scope():
                try:raise OSError('synthetic-only')
                except OSError:
                    r.clock=lambda:(_ for _ in()).throw(cancel);r.phase(17)
                r.finish(Path('synthetic'));done=True
        except BaseException as error:caught=error
        self.assertTrue(done);self.assertIs(caught,cancel)
    def test_direct_finish_sink_cancel_is_not_swallowed(self):
        for kind in(KeyboardInterrupt,SystemExit):
            with self.subTest(kind=kind.__name__):
                cancel=kind();r=self.make(writer=lambda *_:(_ for _ in()).throw(cancel));page=Emitter();r.bind_page(page);caught=None
                try:r.finish(Path('synthetic'))
                except BaseException as error:caught=error
                self.assertIs(caught,cancel);self.assertTrue(r.finished);self.assertEqual(page.handlers,{'close':[],'crash':[]})
    def test_first_of_multiple_diagnostic_cancellations_is_preserved(self):
        first=KeyboardInterrupt('opaque-synthetic-cancel');second=SystemExit();seen=[];caught=None
        def writer(path,data):
            self.assertNotIn(b'opaque-synthetic-cancel',data);seen.append(True);raise second
        r=self.make(writer=writer)
        try:
            with r.cleanup_scope():
                r.clock=lambda:(_ for _ in()).throw(first);r.cleanup();r.finish(Path('synthetic'))
        except BaseException as error:caught=error
        self.assertEqual(seen,[True]);self.assertIs(caught,first)

class DeferredDriverTests(unittest.TestCase):
    exercise=DriverTests.exercise
    def test_every_cleanup_clock_boundary_preserves_close_stop_and_cancel(self):
        for phase in range(13,21):
            for kind in(KeyboardInterrupt,SystemExit):
                with self.subTest(phase=phase,kind=kind.__name__):
                    calls,_,_,runtime=self.exercise(failure=False,cancel_phase=phase,cancel_error=kind())
                    self.assertTrue(runtime);self.assertEqual(calls.count('browser-close'),1);self.assertEqual(calls.count('playwright-stop'),1)
    def test_cleanup_diagnostic_cancel_never_replaces_constructor_primary(self):
        for phase in(13,17,19,20):
            for kind in(KeyboardInterrupt,SystemExit):
                with self.subTest(phase=phase,kind=kind.__name__):
                    calls,_,_,runtime=self.exercise(cancel_phase=phase,cancel_error=kind())
                    self.assertFalse(runtime);self.assertEqual(calls.count('browser-close'),1);self.assertEqual(calls.count('playwright-stop'),1)
if __name__=='__main__':unittest.main()
