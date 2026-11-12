"""Byte-only lexical failure continuation; no SDK, OS process or parent env."""
import copy
import unittest
from types import SimpleNamespace as NS

import test_bootstrap_errors as existing
import test_runtime as legacy
from runtime import bootstrap_errors as capture
from runtime import bounded


class ContinuationApi(legacy.FakeApi):
    def __init__(self,clock,mode='natural'):
        super().__init__(clock,root_exits=False,held_child=False)
        helper=existing.PipeCaptureTests()
        self.module,self.win,self.kernel,self.pipe=helper.api()
        self.cap=helper.prepare(self.pipe,self.win)
        helper.create(self.pipe,self.win)
        self.pipe.release_launch_local(helper.owned(self.cap))
        self.kernel.broken=False
        self.mode=mode;self.drains=0

    def launch_captured(self,*args,**kwargs):
        owned=super().launch(*args,**kwargs)
        owned.bootstrap_capture=self.cap
        return owned

    def identity(self,handle):
        if self.mode=='identity' and self.drains:return (999,999)
        return super().identity(handle)

    def state(self,handle):
        if self.root_exits or self.terminations:return (0,1)
        return (258,259)

    def drain_capture(self,owned,deadline,clock,*,final=False):
        if not final:
            self.drains+=1
            if self.drains==1:
                self.kernel.data[101]=b'error XYZ7: SYNTHETIC_OPAQUE\n'
            elif self.drains==2:
                if self.mode=='api':self.kernel.peek_fault=True
                elif self.mode=='overflow':self.cap.streams[0].max_bytes=self.cap.streams[0].offset
                elif self.mode=='invariant':
                    scanner=self.cap.streams[0];feed=scanner.feed
                    scanner.feed=lambda offset,data:feed(offset-1,data)
                if self.mode!='timeout':
                    self.kernel.data[101]=b'error MSB3073: SYNTHETIC_OPAQUE\n'
                    self.kernel.data[103]=b'error CS2012: SYNTHETIC_OPAQUE\n'
                if self.mode=='natural':self.root_exits=True;self.kernel.broken=True
        return self.pipe.drain_capture(owned,deadline,clock,final=final)

    def release_launch_local(self,owned):return True
    def close_capture(self,owned):return self.pipe.close_capture(owned)
    def capture_result(self,owned):return self.pipe.capture_result(owned)


class BootstrapUnknownTests(unittest.TestCase):
    def scan(self,raw,**options):
        scanner=capture.ErrorCodes(**options);scanner.feed(0,raw)
        return scanner.finish()

    def run_owned(self,mode='natural'):
        clock=legacy.Clock();api=ContinuationApi(clock,mode)
        row=bounded.Runner(api,clock=clock,pause=clock.pause).run(
            [(['owned.exe'],'owned',legacy.explicit_environment(bounded))],3.,bootstrap_capture=True)
        return api,clock,row

    def test_six_shapes_are_only_fixed_integer_enums(self):
        cases=[(1,b'error NU13'),(2,b'error : '),(3,b'error XYZ1301: '),
               (4,b'error NUx: '),(5,b'error \x1b[31mNU1301: '),(6,b'error !?: ')]
        for code,raw in cases:
            value=self.scan(raw)
            self.assertEqual(value['unknownShapes'],[[code,1]])
            self.assertTrue(value['unknown']);self.assertFalse(value['complete'])
            self.assertEqual(value['codes'],[])

    def test_all_chunk_boundaries_preserve_shape_and_code_counts(self):
        raw=b'error XYZ7: x\nerror NU1301: x\nerror XYZ7: x\nerror NU13'
        for split in range(len(raw)+1):
            scanner=capture.ErrorCodes();scanner.feed(0,raw[:split]);scanner.feed(split,raw[split:])
            value=scanner.finish()
            self.assertEqual(value['unknownShapes'],[[1,1],[3,2]])
            self.assertEqual(value['codes'],[[1,1301,1]])

    def test_unknown_and_known_in_later_chunk_do_not_complete_capture(self):
        scanner=capture.ErrorCodes();scanner.feed(0,b'error XYZ7: SYNTHETIC_OPAQUE\n')
        scanner.feed(scanner.offset,b'error NETSDK1004: SYNTHETIC_OPAQUE\n')
        value=scanner.finish()
        self.assertEqual(value['unknownShapes'],[[3,1]])
        self.assertEqual(value['codes'],[[3,1004,1]])
        self.assertFalse(value['complete'])
        self.assertNotIn('SYNTHETIC_OPAQUE',str(value));self.assertNotIn('XYZ',str(value))

    def test_streams_do_not_join_shapes_or_code_tokens(self):
        a=self.scan(b'error NU');b=self.scan(b'1301: ')
        self.assertEqual(a['unknownShapes'],[[1,1]])
        self.assertEqual(b['unknownShapes'],[])
        self.assertEqual(a['codes']+b['codes'],[])

    def test_pending_short_unknown_is_finalized_once_at_eof(self):
        scanner=capture.ErrorCodes();scanner.feed(0,b'error NU13')
        self.assertFalse(scanner.unknown)
        a=scanner.finish();b=scanner.finish()
        self.assertEqual(a,b);self.assertEqual(a['unknownShapes'],[[1,1]])

    def test_shape_count_overflow_is_fatal(self):
        scanner=capture.ErrorCodes(max_count=1)
        with self.assertRaises(ValueError):scanner.feed(0,b'error XYZ1: x\nerror XYZ1: x\n')
        self.assertTrue(scanner.finish()['overflow'])

    def test_input_type_and_offset_after_unknown_remain_fatal(self):
        for bad_offset,bad_data in [(False,b''),(-1,b''),(None,b''),(None,'SYNTHETIC_OPAQUE')]:
            scanner=capture.ErrorCodes();scanner.feed(0,b'error XYZ7: x\n')
            offset=scanner.offset if bad_offset is None else bad_offset
            if bad_offset is None and type(bad_data) is bytes:offset-=1
            with self.assertRaises(ValueError):scanner.feed(offset,bad_data)

    def test_reuse_after_finalization_remains_fatal(self):
        scanner=capture.ErrorCodes();scanner.feed(0,b'error XYZ7: x\n');scanner.finish()
        with self.assertRaises(ValueError):scanner.feed(scanner.offset,b'error NU1301: x\n')

    def test_pipe_unknown_continues_to_both_known_streams_and_eof(self):
        helper=existing.PipeCaptureTests();m,w,k,api=helper.api();cap=helper.prepare(api,w)
        helper.create(api,w);owned=helper.owned(cap);api.release_launch_local(owned)
        k.broken=False;k.data[101]=b'error XYZ7: x\n'
        self.assertTrue(api.drain_capture(owned,9.,lambda:1.))
        k.data[101]=b'error NU1301: x\n';k.data[103]=b'error CS2012: x\n';k.broken=True
        self.assertTrue(api.drain_capture(owned,9.,lambda:1.,final=True))
        self.assertTrue(api.close_capture(owned));value=api.capture_result(owned)
        self.assertFalse(value['complete']);self.assertEqual(value['failureCode'],4)
        self.assertEqual(value['streams'][0]['codes'],[[1,1301,1]])
        self.assertEqual(value['streams'][1]['codes'],[[4,2012,1]])
        self.assertEqual(value['streams'][0]['unknownShapes'],[[3,1]])
        self.assertIs(m.validate_capture(value),value)

    def test_unknown_observes_natural_exit_without_controller_termination(self):
        api,clock,row=self.run_owned()
        self.assertFalse(row['completed']);self.assertFalse(row['forcedCleanup'])
        self.assertTrue(row['cleanupProved']);self.assertEqual(api.terminations,0)
        self.assertEqual(row['deadline'],3.);self.assertLess(clock.now,2.)
        child=row['children'][0]
        self.assertTrue(child['identityRechecked']);self.assertTrue(child['exitObserved'])
        self.assertEqual(child['exitCode'],1)
        self.assertEqual(child['bootstrapErrorCodes']['streams'][0]['codes'],[[2,3073,1]])
        self.assertFalse(child['bootstrapErrorCodes']['complete'])
        self.assertEqual(api.closed,{11,12,13,99})

    def test_unknown_timeout_keeps_original_deadline_and_cleanup(self):
        api,clock,row=self.run_owned('timeout')
        self.assertFalse(row['completed']);self.assertTrue(row['forcedCleanup'])
        self.assertTrue(row['cleanupProved']);self.assertEqual(api.terminations,1)
        self.assertGreaterEqual(clock.now,2.);self.assertLessEqual(clock.now,3.)
        self.assertEqual(row['deadline'],3.)

    def test_unknown_then_identity_change_is_immediate_failure(self):
        api,clock,row=self.run_owned('identity')
        self.assertTrue(row['forcedCleanup']);self.assertEqual(api.drains,1)
        self.assertEqual(api.terminations,1);self.assertLess(clock.now,1.)
        self.assertFalse(row['completed']);self.assertTrue(row['cleanupProved'])

    def test_unknown_then_api_failure_is_immediate_failure(self):
        api,clock,row=self.run_owned('api')
        self.assertTrue(row['forcedCleanup']);self.assertEqual(api.drains,2)
        self.assertEqual(row['children'][0]['bootstrapErrorCodes']['failureCode'],2)
        self.assertEqual(api.terminations,1);self.assertLess(clock.now,1.)

    def test_unknown_then_overflow_is_immediate_failure(self):
        api,clock,row=self.run_owned('overflow')
        self.assertTrue(row['forcedCleanup']);self.assertEqual(api.drains,2)
        self.assertEqual(row['children'][0]['bootstrapErrorCodes']['failureCode'],3)
        self.assertEqual(api.terminations,1);self.assertLess(clock.now,1.)

    def test_unknown_then_feed_invariant_failure_is_immediate_failure(self):
        api,clock,row=self.run_owned('invariant')
        self.assertTrue(row['forcedCleanup']);self.assertEqual(api.drains,2)
        self.assertEqual(row['children'][0]['bootstrapErrorCodes']['failureCode'],4)
        self.assertEqual(api.terminations,1);self.assertLess(clock.now,1.)

    def test_final_unknown_cannot_be_relabelled_complete(self):
        api,clock,row=self.run_owned()
        value=row['children'][0]['bootstrapErrorCodes']
        with self.assertRaises(ValueError):capture.validate_capture({**value,'complete':True,'failureCode':0})

    def test_shape_schema_rejects_unknown_duplicate_or_noninteger_values(self):
        api,clock,row=self.run_owned();original=row['children'][0]['bootstrapErrorCodes']
        for rows in ([[0,1]],[[7,1]],[[True,1]],[[1,False]],[[1,0]],[[1,65536]],
                     [[3,1],[3,1]],[[3,1],[1,1]],[[3,1,'SYNTHETIC_OPAQUE']]):
            value=copy.deepcopy(original);value['streams'][0]['unknownShapes']=rows
            with self.assertRaises(ValueError):capture.validate_capture(value)

    def test_clean_stream_cannot_claim_unknown_shapes(self):
        api,clock,row=self.run_owned();value=copy.deepcopy(row['children'][0]['bootstrapErrorCodes'])
        value['streams'][1]['unknownShapes']=[[3,1]]
        with self.assertRaises(ValueError):capture.validate_capture(value)


if __name__=='__main__':unittest.main()
