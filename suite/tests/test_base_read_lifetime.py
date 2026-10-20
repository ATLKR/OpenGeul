"""Behavioral resource boundaries; these fakes are not native Office evidence."""
import importlib
import math
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace as NS

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'e2e'))
import engine_smoke as baseline
import office_feature_smoke as features

SQL='SELECT "ID", "TEXT_VALUE", "AMOUNT" FROM "OPENGEUL_SMOKE" ORDER BY "ID"'


class Database:
    def __init__(self,failures=None,events=None):
        self.failures=failures or {};self.events=events if events is not None else [];self.index=0
        self.result=NS(next=self.next,getInt=lambda n:1 if n==1 else 42,
            getString=lambda n:'Engine-OpenGeul-base 한글',close=lambda:self.call('result.close'))
        self.statement=NS(executeQuery=self.query,close=lambda:self.call('statement.close'))
        self.connection=NS(createStatement=self.statement_open,close=lambda:self.call('connection.close'))
        self.source=NS(getConnection=self.connection_open,getPropertyValue=lambda name:'sdbc:embedded:firebird')
        self.document=NS(DataSource=self.source,setModified=lambda value:self.call('document.setModified'),
            close=lambda ownership:self.call('document.close'))
    def call(self,name):
        self.events.append(name)
        if name in self.failures:raise self.failures[name]
    def next(self):
        self.call('read');self.index+=1;return self.index==1
    def query(self,sql):
        assert sql==SQL;self.call('query');return self.result
    def statement_open(self):self.call('statement.open');return self.statement
    def connection_open(self,user,password):
        assert (user,password)==('','');self.call('connection.open');return self.connection


def readers():
    return [('engine',lambda doc:baseline.observe('base',doc)),
            ('feature',lambda doc:features.observe(dict(module='base',kind='format'),doc))]


class BaseReadLifetimeTests(unittest.TestCase):
    def test_both_readers_close_result_then_statement_then_connection(self):
        for name,read in readers():
            with self.subTest(reader=name):
                db=Database();value=read(db.document)
                self.assertEqual(value['rows'],[dict(id=1,text='Engine-OpenGeul-base 한글',amount=42)])
                self.assertEqual(db.events[-3:],['result.close','statement.close','connection.close'])

    def test_read_error_remains_primary_while_every_close_is_attempted(self):
        for name,read in readers():
            with self.subTest(reader=name):
                primary=ValueError('original read');later=[OSError('result failed'),RuntimeError('statement failed'),OSError('connection failed')]
                db=Database(dict(zip(('read','result.close','statement.close','connection.close'),[primary,*later])))
                with self.assertRaises(ValueError) as caught:read(db.document)
                self.assertIs(caught.exception,primary)
                self.assertEqual(db.events[-3:],['result.close','statement.close','connection.close'])
                self.assertEqual([error for stage,error in primary.base_cleanup_errors],later)

    def test_first_close_error_is_propagated_and_later_closes_are_retained(self):
        for name,read in readers():
            with self.subTest(reader=name):
                first=OSError('result failed');other=RuntimeError('statement failed');last=OSError('connection failed')
                db=Database({'result.close':first,'statement.close':other,'connection.close':last})
                with self.assertRaises(OSError) as caught:read(db.document)
                self.assertIs(caught.exception,first)
                self.assertEqual(db.events[-3:],['result.close','statement.close','connection.close'])
                self.assertEqual([error for stage,error in first.base_cleanup_errors],[other,last])

    def test_query_failure_closes_only_resources_that_were_acquired(self):
        for name,read in readers():
            for stage,closings in [('statement.open',['connection.close']),('query',['statement.close','connection.close'])]:
                with self.subTest(reader=name,stage=stage):
                    primary=ValueError('acquire failed');db=Database({stage:primary})
                    with self.assertRaises(ValueError) as caught:read(db.document)
                    self.assertIs(caught.exception,primary)
                    self.assertEqual([event for event in db.events if event.endswith('.close')],closings)

    def test_feature_rows_closes_query_resources_without_closing_callers_transaction(self):
        db=Database();rows=features._rows(db.connection)
        self.assertEqual(rows,[dict(id=1,text='Engine-OpenGeul-base 한글',amount=42)])
        self.assertEqual(db.events[-2:],['result.close','statement.close']);self.assertNotIn('connection.close',db.events)

    def test_result_statement_connection_document_desktop_order_with_real_engine_cleanup(self):
        from test_engine_smoke import OwnedJobCleanupTests
        engine,api,events=OwnedJobCleanupTests().scenario(graceful=True)
        engine.base_lifetime_enabled=True
        db=Database(events=events)
        baseline.observe('base',db.document,engine.lifetime_diagnostics)
        engine.close_document(db.document);engine.cleanup()
        relevant=[name for name in events if name in ('result.close','statement.close','connection.close','document.close','request-graceful-desktop-exit')]
        self.assertEqual(relevant,['result.close','statement.close','connection.close','document.close','request-graceful-desktop-exit'])
        self.assertTrue(engine.cleanup_evidence['gracefulQualified'])
        stages=engine.cleanup_evidence['lifetimeDiagnostics']['stages']
        closed=[row['stage'] for row in stages if row['stage'].endswith('.close') or row['stage']=='desktop.terminate']
        self.assertEqual(closed,['result.close','statement.close','connection.close','document.close','desktop.terminate'])
        self.assertTrue(all(row['status']=='returned' and math.isfinite(row['startedAt']) and row['startedAt']<=row['finishedAt'] for row in stages))

    def test_incomplete_diagnostics_cannot_qualify_an_otherwise_graceful_exit(self):
        from test_engine_smoke import OwnedJobCleanupTests
        helper=importlib.import_module('base_read_lifetime')
        engine,api,events=OwnedJobCleanupTests().scenario(graceful=True)
        for n in range(helper.MAX_STAGES):engine.lifetime_diagnostics.call('result.close',lambda:None)
        engine.cleanup()
        self.assertFalse(engine.cleanup_evidence['gracefulQualified'])
        self.assertFalse(engine.cleanup_evidence['forcedTermination'])
        self.assertIn('request-graceful-desktop-exit',events)
        self.assertTrue(any('lifetime diagnostics' in error for error in engine.cleanup_errors))

    def test_lifetime_diagnostics_are_bounded_and_never_prevent_remaining_operations(self):
        helper=importlib.import_module('base_read_lifetime')
        trace=helper.LifetimeTrace(clock=lambda:1.)
        calls=[]
        for n in range(helper.MAX_STAGES+3):trace.call('result.close',lambda:calls.append(True))
        self.assertEqual(len(calls),helper.MAX_STAGES+3)
        self.assertEqual(len(trace.receipt['stages']),helper.MAX_STAGES)
        self.assertEqual(trace.receipt['omittedStages'],3);self.assertFalse(trace.receipt['complete'])
        with self.assertRaises(RuntimeError):trace.require_complete()

    def test_invalid_clock_records_incompleteness_without_skipping_close(self):
        helper=importlib.import_module('base_read_lifetime')
        for value in (float('nan'),float('inf'),True):
            with self.subTest(value=value):
                trace=helper.LifetimeTrace(clock=lambda:value);calls=[]
                trace.call('connection.close',lambda:calls.append(True))
                self.assertEqual(calls,[True]);self.assertFalse(trace.receipt['complete'])
                with self.assertRaises(RuntimeError):trace.require_complete()
                for row in trace.receipt['stages']:
                    self.assertIsNone(row['startedAt']);self.assertIsNone(row['finishedAt'])

    def test_actual_typed_desktop_return_is_retained_and_nonboolean_cannot_qualify(self):
        from test_engine_smoke import OwnedJobCleanupTests
        for value in (True,False,None,1):
            with self.subTest(value=value,type=type(value).__name__):
                engine,api,events=OwnedJobCleanupTests().scenario(graceful=True)
                engine.desktop=NS(terminate=lambda:value);engine.cleanup()
                row=next(r for r in engine.cleanup_evidence['lifetimeDiagnostics']['stages'] if r['stage']=='desktop.terminate')
                self.assertEqual(row['returnType'],type(value).__name__);self.assertEqual(row['returnValue'],value)
                self.assertEqual(row['status'],'returned')
                self.assertTrue(math.isfinite(row['startedAt']) and row['startedAt']<=row['finishedAt'])
                self.assertEqual(engine.cleanup_evidence['gracefulQualified'],value is True)

    def test_desktop_error_is_recorded_and_forced_recovery_stays_failure(self):
        from test_engine_smoke import OwnedJobCleanupTests
        engine,api,events=OwnedJobCleanupTests().scenario(graceful=False)
        engine.desktop=NS(terminate=lambda:(_ for _ in ()).throw(OSError('native desktop error')))
        engine.cleanup()
        row=next(r for r in engine.cleanup_evidence['lifetimeDiagnostics']['stages'] if r['stage']=='desktop.terminate')
        self.assertEqual(row['status'],'raised');self.assertEqual(row['errorType'],'OSError')
        self.assertTrue(engine.cleanup_evidence['forcedTermination']);self.assertFalse(engine.cleanup_evidence['gracefulQualified'])
        self.assertIn('terminate-private-job',events)

    def test_uno_like_exception_field_guards_do_not_mask_primary_read_failure(self):
        class UnoLikeError(ValueError):
            def __getattribute__(self,name):
                if name in ('base_cleanup_errors','__notes__'):raise RuntimeError('UNO field lookup')
                return super().__getattribute__(name)
            def __setattr__(self,name,value):
                if name in ('base_cleanup_errors','__notes__'):raise RuntimeError('UNO field assignment')
                return super().__setattr__(name,value)
        for name,read in readers():
            with self.subTest(reader=name):
                primary=UnoLikeError('original UNO read');later=OSError('later close')
                db=Database({'read':primary,'result.close':later})
                with self.assertRaises(UnoLikeError) as caught:read(db.document)
                self.assertIs(caught.exception,primary)
                retained=BaseException.__getattribute__(primary,'__dict__')['base_cleanup_errors']
                self.assertEqual([error for stage,error in retained],[later])

    def test_nonfinite_or_opaque_desktop_results_are_not_dumped_or_qualified(self):
        import json
        from test_engine_smoke import OwnedJobCleanupTests
        class Opaque:
            def __repr__(self):raise AssertionError('must not dump return objects')
            __str__=__repr__
        for value in (float('nan'),Opaque()):
            engine,api,events=OwnedJobCleanupTests().scenario(graceful=True)
            engine.desktop=NS(terminate=lambda:value);engine.cleanup()
            row=next(r for r in engine.cleanup_evidence['lifetimeDiagnostics']['stages'] if r['stage']=='desktop.terminate')
            self.assertFalse(row['returnValueRetained']);self.assertNotIn('returnValue',row)
            self.assertFalse(engine.cleanup_evidence['gracefulQualified'])
            json.dumps(engine.cleanup_evidence,allow_nan=False)

    def test_backwards_clock_is_explicitly_incomplete(self):
        helper=importlib.import_module('base_read_lifetime');times=iter((2.,1.));calls=[]
        trace=helper.LifetimeTrace(clock=lambda:next(times))
        trace.call('result.close',lambda:calls.append(True))
        self.assertEqual(calls,[True]);self.assertFalse(trace.receipt['complete'])
        with self.assertRaises(RuntimeError):trace.require_complete()

    def test_base_document_close_is_attempted_when_discard_preparation_fails(self):
        from test_engine_smoke import OwnedJobCleanupTests
        engine,api,events=OwnedJobCleanupTests().scenario(graceful=True);engine.base_lifetime_enabled=True
        primary=ValueError('setModified failed');later=OSError('document close failed')
        db=Database({'document.setModified':primary,'document.close':later},events)
        with self.assertRaises(ValueError) as caught:engine.close_document(db.document)
        self.assertIs(caught.exception,primary)
        self.assertEqual(events[-2:],['document.setModified','document.close'])
        self.assertEqual([error for stage,error in primary.base_cleanup_errors],[later])
        engine.cleanup();self.assertIn('request-graceful-desktop-exit',events)


if __name__=='__main__':unittest.main()
