"""Synthetic cache-only location checks; no actual browser or bundle attribution."""
import ast
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('warning_location_under_test', ROOT/'e2e/native_clipboard.py')
API = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(API)

# Deliberately small synthetic cache shapes, not Playwright implementations.
# Actual package compatibility requires the separately reviewed source and Windows.
class PublicMessage:
    @property
    def type(self): return self._impl_obj.type
    @property
    def location(self): raise AssertionError('Public location getter forbidden')


class ImplMessage:
    @property
    def type(self): return self._event['type']
    @property
    def location(self): raise AssertionError('Impl location getter forbidden')


class OtherImplMessage: pass


_MISSING=object()

OWNER = {'hwnd':101, 'pid':11, 'creation':1234567, 'session':1, 'sequence':3}
SIDECAR_KEYS = {'schemaVersion','sidecarType','packetSchemaVersion','diagnosticOnly',
    'acceptanceEligible','qualification','transportCode','clipboardOwner','callbackWindowMs',
    'dirtyWaitMs','eventCount','warningLocations','installKnown','installed','pageIdentityKnown',
    'pageIdentityMatched','cleanupKnown','ownReferenceReleased','scriptIdentityKnown',
    'warningOriginKnown','handlerSuccessKnown'}


class Poison:
    reads = 0
    def fail(self, *_args, **_kwargs):
        type(self).reads += 1
        raise AssertionError('Forbidden payload access')
    __str__ = __repr__ = fail
    def __getattribute__(self, name):
        if name == 'fail': return object.__getattribute__(self, name)
        return object.__getattribute__(self, 'fail')()


class Session:
    def __init__(self): self.page = object(); self._clipboard_callback_sink = None


def message(line=31, column=7, *, location=None, impl_type=ImplMessage):
    impl = object.__new__(impl_type)
    object.__getattribute__(impl, '__dict__')['_event'] = {
        'type':'warning', 'text':Poison(), 'args':Poison(),
        'location':{'url':Poison(), 'lineNumber':line, 'columnNumber':column}
            if location is None else location}
    wrapper = object.__new__(PublicMessage)
    object.__getattribute__(wrapper, '__dict__')['_impl_obj'] = impl
    return wrapper


class WarningLocationTests(unittest.TestCase):
    def setUp(self):
        self.read = getattr(API, '_cb_cached_warning_location', None)
        self.assertTrue(callable(self.read), 'Required cache-only helper absent')
        self.public_module = types.ModuleType('playwright.sync_api._generated')
        self.public_module.ConsoleMessage = PublicMessage
        self.impl_module = types.ModuleType('playwright._impl.console_message')
        self.impl_module.ConsoleMessage = ImplMessage
        self.modules=(('playwright.sync_api._generated',self.public_module),
                      ('playwright._impl.console_message',self.impl_module))
        self.old_modules=[sys.modules.get(name,_MISSING) for name,_module in self.modules]
        for name,module in self.modules: sys.modules[name]=module
        self.addCleanup(self.restore_module)
        Poison.reads = 0

    def restore_module(self):
        for (name,_module),previous in zip(self.modules,self.old_modules):
            if previous is _MISSING: sys.modules.pop(name,None)
            else: sys.modules[name]=previous

    def observe(self, events, *, writer=None, enabled=True, primary=None, packet_writer=None):
        session=Session(); old=[]; side=[]; ticks=iter((1,2,5,7))
        sink=API.ClipboardCallbackObservation(session, session.page, 2, dict(OWNER),
            old.append if packet_writer is None else packet_writer, clock=lambda:next(ticks),
            enabled=enabled, location_writer=side.append if writer is None else writer)
        sink.__enter__()
        for event in events: API.forward_clipboard_console(session,session.page,event)
        sink.begin_wait();sink.end_wait(primary=primary)
        result=sink.__exit__(type(primary) if primary is not None else None,primary,None)
        return sink,old,side,result

    def test_exact_cache_reads_two_numbers_without_public_getter_or_payload(self):
        calls=[]
        def forbidden(_self): calls.append(1); raise AssertionError('Public getter forbidden')
        with mock.patch.object(PublicMessage,'location',property(forbidden)), \
             mock.patch.object(ImplMessage,'location',property(forbidden)):
            self.assertTrue(self.read(message()) == (31,7))
            self.assertTrue(self.read(message(0,2**31-1)) == (0,2**31-1))
        self.assertTrue(calls == [] and Poison.reads == 0)

    def test_missing_module_and_different_impl_type_remain_unknown(self):
        sys.modules.pop('playwright._impl.console_message')
        self.assertTrue(self.read(message()) is None)
        sys.modules['playwright._impl.console_message']=self.impl_module
        self.assertTrue(self.read(message(impl_type=OtherImplMessage)) is None)

    def test_native_dict_shapes_exact_type_and_coordinates_closed_bounds(self):
        class DictChild(dict):
            def get(self,*_): raise AssertionError('Dict subclass queried')
        for loc in (DictChild(lineNumber=1,columnNumber=2), [], None, {},
                    {'lineNumber':True,'columnNumber':1}, {'lineNumber':-1,'columnNumber':1},
                    {'lineNumber':2**31,'columnNumber':1}, {'lineNumber':1.0,'columnNumber':1},
                    {'lineNumber':1,'columnNumber':float('inf')}, {'lineNumber':1,'columnNumber':False},
                    {'lineNumber':Poison(),'columnNumber':1}, {'lineNumber':lambda:1,'columnNumber':1}):
            current=message(location={} if loc is None else loc)
            self.assertTrue(self.read(current) is None)
        current=message();impl=object.__getattribute__(current,'__dict__')['_impl_obj']
        object.__getattribute__(impl,'__dict__')['_event']=DictChild()
        self.assertTrue(self.read(current) is None)
        for inner in (False,True):
            current=message()
            target=object.__getattribute__(current,'__dict__')['_impl_obj'] if inner else current
            object.__setattr__(target,'__dict__',DictChild(object.__getattribute__(target,'__dict__')))
            self.assertTrue(self.read(current) is None)
        class Child(PublicMessage): pass
        self.assertTrue(self.read(object.__new__(Child)) is None)
        self.assertTrue(self.read(mock.Mock(spec=PublicMessage)) is None)
        self.assertTrue(Poison.reads == 0)

    def test_hostile_dict_descriptor_and_module_subclass_are_never_executed(self):
        calls=[]
        class Hostile:
            @property
            def __dict__(self): calls.append(1); raise AssertionError('Descriptor executed')
        public_module=sys.modules['playwright.sync_api._generated']
        with mock.patch.object(public_module,'ConsoleMessage',Hostile):
            self.assertTrue(self.read(Hostile()) is None)
        current=object.__new__(PublicMessage)
        object.__getattribute__(current,'__dict__')['_impl_obj']=Hostile()
        with mock.patch.object(self.impl_module,'ConsoleMessage',Hostile):
            self.assertTrue(self.read(current) is None)
        class ModuleChild(types.ModuleType):
            def __getattribute__(self,name): calls.append(2); raise AssertionError('Module queried')
        sys.modules['playwright._impl.console_message']=ModuleChild('playwright._impl.console_message')
        self.assertTrue(self.read(message()) is None)
        self.assertTrue(calls == [] and Poison.reads == 0)

    def test_optional_sidecar_correlates_owner_window_event_ordinal_and_old_packet(self):
        event=message();sink,old,side,result=self.observe([event])
        self.assertTrue(result is False and len(old)==len(side)==1)
        packet=old[0];out=side[0]
        self.assertTrue(set(out)==SIDECAR_KEYS and out['schemaVersion']==out['sidecarType']==1)
        self.assertTrue(out['packetSchemaVersion']==packet['schemaVersion']==1)
        self.assertTrue(out['warningLocations']==[[1,True,31,7]] and out['eventCount']==1)
        self.assertTrue(packet['events']==[[1,19,True]] and packet['consoleTypeCounts'][19]==1)
        for name in ('clipboardOwner','transportCode','callbackWindowMs','dirtyWaitMs',
                     'installKnown','installed','pageIdentityKnown','pageIdentityMatched',
                     'cleanupKnown','ownReferenceReleased'):
            self.assertTrue(out[name]==packet[name])
        self.assertTrue(out['diagnosticOnly'] is True)
        self.assertTrue(all(out[name] is False for name in ('acceptanceEligible','qualification',
            'scriptIdentityKnown','warningOriginKnown','handlerSuccessKnown')))
        self.assertTrue(len(json.dumps(out,allow_nan=False).encode('ascii'))<=8192)
        self.assertTrue(Poison.reads==0)

    def test_existing_eight_event_bound_and_only_warning_code19_queries_cache(self):
        class Other:
            @property
            def type(self): return 'log'
        reads=[]
        def cache(event): reads.append(1); return (1,2)
        with mock.patch.object(API,'_cb_cached_warning_location',cache):
            sink,old,side,_=self.observe([Other(),message()]+[Other()]*6+[message()])
        self.assertTrue(reads==[1] and old[0]['overflow'] is True)
        self.assertTrue(old[0]['events']==[[1,10,True],[1,19,True]]+[[1,10,True]]*6)
        self.assertTrue(side[0]['eventCount']==8 and side[0]['warningLocations']==[[2,True,1,2]])

    def test_unknown_cache_and_getter_failure_never_change_original_counts_or_primary(self):
        class Primary(TimeoutError):
            __str__=__repr__=Poison.fail
        primary=Primary()
        with mock.patch.object(API,'_cb_cached_warning_location',side_effect=KeyboardInterrupt):
            sink,old,side,result=self.observe([message()],primary=primary)
        self.assertTrue(result is False and old[0]['events']==[[1,19,True]])
        self.assertTrue(old[0]['optionalErrors']==[])
        self.assertTrue(side[0]['warningLocations']==[[1,False,None,None]])

    def test_sidecar_writer_cancellation_does_not_replace_primary_or_old_success(self):
        def failing_writer(_packet): raise SystemExit()
        for primary in (None,TimeoutError(),KeyboardInterrupt()):
            sink,old,side,result=self.observe([message()],writer=failing_writer,primary=primary)
            self.assertTrue(result is False and len(old)==1 and side==[])
            self.assertTrue(old[0]['optionalErrors']==[] and sink.write_known is True)
        calls=[]
        def old_failure(_packet): raise ValueError()
        sink,old,side,result=self.observe([message()],packet_writer=old_failure,
            writer=lambda _packet:calls.append(1),primary=TimeoutError())
        self.assertTrue(result is False and old==side==calls==[] and sink.write_known is False)

    def test_disabled_or_no_writer_does_not_query_cache_or_create_sidecar(self):
        def forbidden(*_): raise AssertionError('Optional cache queried')
        with mock.patch.object(API,'_cb_cached_warning_location',forbidden):
            _sink,old,side,_=self.observe([message()],enabled=False)
            self.assertTrue(old==side==[])
            session=Session();packets=[];ticks=iter((1,7))
            with API.ClipboardCallbackObservation(session,session.page,1,dict(OWNER),packets.append,
                    clock=lambda:next(ticks),enabled=True):
                API.forward_clipboard_console(session,session.page,message())
            self.assertTrue(packets[0]['events']==[[1,19,True]])

    def test_narrow_source_normalizer_still_rejects_primary_counter_and_other_changes(self):
        spec=importlib.util.spec_from_file_location('original_observation_contract',
            ROOT/'tests/test_clipboard_callback_observation.py')
        original=importlib.util.module_from_spec(spec);spec.loader.exec_module(original)
        normalize=getattr(original,'without_warning_location_sidecar',None)
        self.assertTrue(callable(normalize),'Required exact seam normalizer absent')
        def guarded(tree):
            normalized=normalize(tree)
            init=original.method(normalized,'ClipboardCallbackObservation','__init__')
            index=next(i for i,arg in enumerate(init.args.kwonlyargs) if arg.arg=='enabled')
            if init.args.kw_defaults[index].value is not False:return False
            init.args.kw_defaults[index]=ast.Constant(value=True)
            return original.ast_digest(normalized)==original.V2_AST_SHA256['native_clipboard.py']
        self.assertTrue(guarded(original.source_tree('native_clipboard.py')))
        for kind in (1,2,3):
            tree=original.source_tree('native_clipboard.py')
            if kind==1:
                function=original.method(tree,'ClipboardCallbackObservation','__exit__')
                function.body[-1].value=ast.Constant(value=True)
            elif kind==2:
                function=next(node for node in tree.body if isinstance(node,ast.FunctionDef)
                    and node.name=='_forward_clipboard_callback')
                counter=next(node for node in ast.walk(function) if isinstance(node,ast.AugAssign))
                counter.value=ast.Constant(value=2)
            else:
                function=original.method(tree,'ClipboardCallbackObservation','__init__')
                statement=next(node for node in function.body if isinstance(node,ast.Assign)
                    and any(isinstance(target,ast.Attribute) and target.attr=='_enabled' for target in node.targets))
                statement.value=ast.Constant(value=False)
            self.assertTrue(guarded(tree) is False)


if __name__=='__main__': unittest.main()
