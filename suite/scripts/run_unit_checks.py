"""Run ordinary unittest discovery and optionally emit one closed numeric result."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys
import types
import unittest

from suite.e2e.numeric_notice import EXCEPTIONS, escape_data, public_context

ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOTS = ('suite/tests','suite/e2e','suite/scripts','suite','e2e')
UNIT_TITLE = 'OpenGeul numeric unit v1'
UNIT_OPT_IN = 'OPENGEUL_SUITE_UNIT_NOTICE'
MAX_BYTES, MAX_FAILURES, MAX_FILE_CODE, MAX_LINE = 2048, 8, 65535, 10_000_000
_COUNTS = ('testsRun','errorCount','failureCount','skippedCount','expectedFailureCount',
           'unexpectedSuccessCount','descriptorCount','droppedFailureCount','fileCount')
_HEADER = {'schemaVersion','kind','sourceCommit','runId','runAttempt','architecture'}
_DESCRIPTOR = {'resultCode','exceptionCode','fileCode','line','testFileCode','testLine'}
_KEYS = _HEADER | set(_COUNTS) | {'failures'}


def source_file_map(source_root=ROOT):
    """Public lookup for an exact source checkout; IDs are sorted relative names."""
    root=Path(source_root)
    names=[]
    for relative in SOURCE_ROOTS:
        directory=root/relative
        if directory.is_symlink(): continue
        for path in directory.glob('*.py'):
            if path.suffix=='.py' and path.is_file() and not path.is_symlink(): names.append(relative+'/'+path.name)
    names=sorted(names)
    if len(names)>MAX_FILE_CODE: raise ValueError('Public source map exceeded its bound')
    return dict(enumerate(names,1))


def _path_codes(files):
    return {os.path.normcase(str(ROOT/name)):code for code,name in files.items()}


def _integer(value, maximum=0xffffffff, minimum=0):
    return type(value) is int and minimum<=value<=maximum


def _test_location(test, paths):
    # Subtest parameter strings and TestCase.__str__ are never consulted.
    values=object.__getattribute__(test,'__dict__')
    parent=values.get('test_case')
    if isinstance(parent,unittest.TestCase): test=parent; values=object.__getattribute__(test,'__dict__')
    name=values.get('_testMethodName')
    if type(name) is not str: return 0,0
    for cls in type(test).__mro__:
        method=vars(cls).get(name)
        if isinstance(method,(staticmethod,classmethod)): method=method.__func__
        if type(method) is types.FunctionType:
            code=paths.get(os.path.normcase(method.__code__.co_filename),0)
            line=method.__code__.co_firstlineno if code else 0
            return (code,line) if _integer(line,MAX_LINE,1) else (0,0)
        if method is not None: break
    return 0,0


class UnitResult(unittest.TextTestResult):
    """Observe existing error tuples before normal unittest formatting."""
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.source_paths={}
        self.numeric_failures=[]
        self.dropped_failures=0

    def _record(self,test,err,result_code):
        try:
            if len(self.numeric_failures)>=MAX_FAILURES:
                self.dropped_failures+=1
                return
            file_code=line=0
            exception_code=EXCEPTIONS.get(err[0],0) if err is not None else 0
            trace=err[2] if err is not None else None
            for _ in range(64):
                if trace is None: break
                code=self.source_paths.get(os.path.normcase(trace.tb_frame.f_code.co_filename),0)
                if code and _integer(trace.tb_lineno,MAX_LINE,1): file_code,line=code,trace.tb_lineno
                trace=trace.tb_next
            test_code,test_line=_test_location(test,self.source_paths)
            self.numeric_failures.append(dict(resultCode=result_code,exceptionCode=exception_code,
                fileCode=file_code,line=line,testFileCode=test_code,testLine=test_line))
        except Exception:
            # This optional observer cannot change the primary result callback.
            self.dropped_failures+=1

    def addError(self,test,err):
        self._record(test,err,1)
        super().addError(test,err)

    def addFailure(self,test,err):
        self._record(test,err,2)
        super().addFailure(test,err)

    def addSubTest(self,test,subtest,err):
        if err is not None:
            self._record(test,err,4 if issubclass(err[0],test.failureException) else 3)
        super().addSubTest(test,subtest,err)

    def addUnexpectedSuccess(self,test):
        self._record(test,None,5)
        super().addUnexpectedSuccess(test)


class UnitRunner(unittest.TextTestRunner):
    """A silent observer: only main may emit the one unit annotation."""
    resultclass=UnitResult

    def __init__(self,*args,source_files=None,**kwargs):
        super().__init__(*args,**kwargs)
        self.source_files={} if source_files is None else dict(source_files)

    def _makeResult(self):
        result=super()._makeResult()
        result.source_paths=_path_codes(self.source_files)
        return result


def _unique(pairs):
    result={}
    for key,value in pairs:
        if key in result: raise ValueError('Duplicate unit notice key')
        result[key]=value
    return result


def decode_unit_notice(message,expected_source_commit,expected_run_id,*,
                       expected_run_attempt=1,expected_architecture=None,expected_file_count=None):
    """Pure closed-schema validation; the caller selects UNIT_TITLE separately."""
    if (type(expected_source_commit) is not str or not re.fullmatch('[0-9a-f]{40}',expected_source_commit)
            or expected_source_commit=='0'*40 or not _integer(expected_run_id,2**63-1,1)
            or type(expected_run_attempt) is not int or expected_run_attempt!=1
            or (expected_architecture is not None and (type(expected_architecture) is not int or expected_architecture not in (0x8664,0xaa64)))
            or (expected_file_count is not None and not _integer(expected_file_count,MAX_FILE_CODE))):
        raise ValueError('Expected unit notice context differs')
    if type(message) is not str or len(message.encode('utf-8'))>MAX_BYTES: raise ValueError('Unit notice size rejected')
    value=json.loads(message,object_pairs_hook=_unique,parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite unit notice')))
    if type(value) is not dict or value.keys()!=_KEYS: raise ValueError('Closed unit notice required')
    for key in value.keys()-{'sourceCommit','failures'}:
        if not _integer(value[key],2**63-1 if key=='runId' else 0xffffffff): raise ValueError('Exact unit integers required')
    if (value['schemaVersion']!=1 or value['kind']!=3 or value['sourceCommit']!=expected_source_commit
            or value['runId']!=expected_run_id or value['runAttempt']!=expected_run_attempt
            or value['architecture'] not in (0x8664,0xaa64)
            or (expected_architecture is not None and value['architecture']!=expected_architecture)
            or value['fileCount']>MAX_FILE_CODE
            or (expected_file_count is not None and value['fileCount']!=expected_file_count)):
        raise ValueError('Unit notice identity differs')
    failures=value['failures']
    if (type(failures) is not list or len(failures)>MAX_FAILURES or value['descriptorCount']!=len(failures)
            or value['descriptorCount']+value['droppedFailureCount']!=value['errorCount']+value['failureCount']+value['unexpectedSuccessCount']):
        raise ValueError('Unit failure counts differ')
    observed={code:0 for code in range(1,6)}
    for descriptor in failures:
        if type(descriptor) is not dict or descriptor.keys()!=_DESCRIPTOR: raise ValueError('Closed unit descriptor required')
        if any(not _integer(item) for item in descriptor.values()): raise ValueError('Exact unit descriptor integers required')
        if descriptor['resultCode'] not in observed or descriptor['exceptionCode'] not in (0,*EXCEPTIONS.values()):
            raise ValueError('Unit descriptor enum differs')
        observed[descriptor['resultCode']]+=1
        for file_key,line_key in (('fileCode','line'),('testFileCode','testLine')):
            code,line=descriptor[file_key],descriptor[line_key]
            if code>value['fileCount'] or (line!=0 if code==0 else not 1<=line<=MAX_LINE):
                raise ValueError('Unit source location differs')
        if descriptor['resultCode']==5 and any(descriptor[key] for key in ('exceptionCode','fileCode','line')):
            raise ValueError('Unexpected success has no caught error')
    if (observed[1]+observed[3]>value['errorCount'] or observed[2]+observed[4]>value['failureCount']
            or observed[5]>value['unexpectedSuccessCount']): raise ValueError('Unit descriptor totals differ')
    return value


def emit_unit_notice(result,context,files,*,stream=None):
    try:
        if context is None: return False
        value=dict(schemaVersion=1,kind=3,**context,testsRun=result.testsRun,
            errorCount=len(result.errors),failureCount=len(result.failures),skippedCount=len(result.skipped),
            expectedFailureCount=len(result.expectedFailures),unexpectedSuccessCount=len(result.unexpectedSuccesses),
            descriptorCount=len(result.numeric_failures),droppedFailureCount=result.dropped_failures,
            fileCount=len(files),failures=result.numeric_failures)
        message=json.dumps(value,separators=(',',':'),allow_nan=False)
        decode_unit_notice(message,context['sourceCommit'],context['runId'],
            expected_architecture=context['architecture'],expected_file_count=len(files))
        print('::notice title='+UNIT_TITLE+'::'+escape_data(message),file=stream or sys.stdout,flush=True)
        return True
    except Exception:
        return False


def main(argv=None):
    # Freeze before discovery/imports/tests can patch any context fields.
    context=public_context() if os.environ.get(UNIT_OPT_IN)=='1' else None
    try: files=source_file_map() if context is not None else {}
    except Exception: context=None; files={}
    class ConfiguredRunner(UnitRunner):
        def __init__(self,**kwargs): super().__init__(source_files=files,**kwargs)
    args=list(sys.argv[1:] if argv is None else argv)
    program=unittest.TestProgram(module=None,argv=['python -m unittest','discover',*args],
        testRunner=ConfiguredRunner,exit=False)
    try: emit_unit_notice(program.result,context,files)
    except Exception: pass
    if program.result.testsRun==0 and len(program.result.skipped)==0: return 5
    return 0 if program.result.wasSuccessful() else 1


if __name__=='__main__':
    raise SystemExit(main())
