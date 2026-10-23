"""Bounded E2E-only getter of the original owned Writer model.

The controller makes no UNO calls. An unchanged suspended->private-job->resume
launcher contains every helper call, including pipe resolution. This reader has
no document creation, loading, input, dispatch, focus, save or close capability.
Portable raw-receipt validators below do not query Windows or the filesystem.
"""
from __future__ import annotations

from collections import namedtuple
import ctypes
from ctypes import wintypes as W
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import stat
import sys
import time
import traceback
from urllib.parse import unquote, urlsplit

MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_BODY_BYTES = 1024 * 1024
MAX_MEMBER_STATE_SAMPLES = 4096
MAX_JOB_CENSUS_ANOMALIES = 32
MAX_JOB_CENSUS_GROUPS = 8192
PROFILE_DIRECTORY_ACCESS = 0x80  # FILE_READ_ATTRIBUTES
PROFILE_DIRECTORY_SHARE = 1 | 2 | 4  # FILE_SHARE_READ | WRITE | DELETE
PROFILE_DIRECTORY_FLAGS = 0x02000000  # FILE_FLAG_BACKUP_SEMANTICS
OPERATIONS = ['resolve-existing-owned-frame','Text.getString','isModified','verify-retained-generation']
WRITER_MODEL_SERVICE = 'com.sun.star.text.TextDocument'
WRITER_GETTER_CONTRACT = 'writer-body-v1'
CALC_MODEL_SERVICE = 'com.sun.star.sheet.SpreadsheetDocument'
CALC_GETTER_CONTRACT = 'calc-a1-b1-c1-d1-v1'
CALC_PENDING_GETTER_CONTRACT = 'calc-a1-b1-c1-d1-pending-input-v1'
CALC_PENDING_INITIAL_GETTER_CONTRACT = 'calc-a1-b1-c1-d1-pending-initial-selection-v2'
CALC_OPERATIONS = ['resolve-existing-owned-frame','Sheet0.A1.getString','Sheet0.B1.getValue',
    'Sheet0.C1.getValue','Sheet0.D1.getFormula','Sheet0.D1.getValue','isModified','verify-retained-generation']
_ModelContract = namedtuple('_ModelContract','service getters kind cleanup_kind operations')
_WRITER_CONTRACT = _ModelContract(WRITER_MODEL_SERVICE,WRITER_GETTER_CONTRACT,
    'existing-owned-writer-body','owned-writer-reader-cleanup',tuple(OPERATIONS))
_CALC_CONTRACT = _ModelContract(CALC_MODEL_SERVICE,CALC_GETTER_CONTRACT,
    'existing-owned-calc-cells','owned-calc-reader-cleanup',tuple(CALC_OPERATIONS))
CALC_PENDING_OPERATIONS = [CALC_OPERATIONS[0],
    'XSelectionSupplier.getSelection.rangeAddress',
    'owned-test-accessible.A1-editor.XAccessibleText.getText']+CALC_OPERATIONS[1:]
_CALC_PENDING_CONTRACT = _ModelContract(CALC_MODEL_SERVICE,CALC_PENDING_GETTER_CONTRACT,
    'existing-owned-calc-pending-input','owned-calc-pending-reader-cleanup',tuple(CALC_PENDING_OPERATIONS))
CALC_PENDING_INITIAL_OPERATIONS = [CALC_PENDING_OPERATIONS[0],
    'XSelectionSupplier.getSelection.source-RPC-initial-or-strict-range']+CALC_PENDING_OPERATIONS[2:]
_CALC_PENDING_INITIAL_CONTRACT = _ModelContract(CALC_MODEL_SERVICE,CALC_PENDING_INITIAL_GETTER_CONTRACT,
    'existing-owned-calc-pending-initial-program','owned-calc-pending-initial-program-reader-cleanup',
    tuple(CALC_PENDING_INITIAL_OPERATIONS))
WRITER_EDIT_GETTER_CONTRACT='writer-active-edit-context-v1'
CALC_EDIT_GETTER_CONTRACT='calc-a1-active-edit-context-v1'
IMPRESS_MODEL_SERVICE='com.sun.star.presentation.PresentationDocument'
IMPRESS_EDIT_GETTER_CONTRACT='impress-active-edit-context-v1'
_WRITER_EDIT_CONTRACT=_ModelContract(WRITER_MODEL_SERVICE,WRITER_EDIT_GETTER_CONTRACT,
    'existing-owned-writer-edit-context','owned-writer-edit-context-reader-cleanup',
    ('resolve-existing-owned-frame','retained-controller.getViewCursor','ViewCursor.isCollapsed',
     'ViewCursor.getText','ViewCursor.getEnd','Text.getEnd','Text.compareRegionEnds','Text.getString',
     'isModified','verify-retained-generation'))
_CALC_EDIT_CONTRACT=_ModelContract(CALC_MODEL_SERVICE,CALC_EDIT_GETTER_CONTRACT,
    'existing-owned-calc-edit-context','owned-calc-edit-context-reader-cleanup',
    tuple([CALC_OPERATIONS[0],'XSelectionSupplier.getSelection.rangeAddress',
           'owned-native-frame.XAccessible.actual-A1-editing-context']+CALC_OPERATIONS[1:]))
_IMPRESS_EDIT_CONTRACT=_ModelContract(IMPRESS_MODEL_SERVICE,IMPRESS_EDIT_GETTER_CONTRACT,
    'existing-owned-impress-edit-context','owned-impress-edit-context-reader-cleanup',
    ('resolve-existing-owned-frame','owned-native-frame.XAccessible.actual-active-Outliner-editing-context',
     'isModified','verify-retained-generation'))
_EDIT_MODULES={_WRITER_EDIT_CONTRACT:'writer',_CALC_EDIT_CONTRACT:'calc',_IMPRESS_EDIT_CONTRACT:'impress'}
PROCESS_KEYS = ('pid','creationTime','image','handleValue','waitResult','exitCode')

sys.path.insert(0,str(Path(__file__).resolve().parent))
from native_accessibility import private_pipe as _parse_private_pipe


def _model_contract(expected_service,getter_contract):
    """Only the caller selects a fixed contract; receipt fields never select it."""
    assert type(expected_service) is str and type(getter_contract) is str, 'Explicit model service/getter contract is required'
    for contract in (_WRITER_CONTRACT,_CALC_CONTRACT,_CALC_PENDING_CONTRACT,_CALC_PENDING_INITIAL_CONTRACT,*_EDIT_MODULES):
        if (expected_service,getter_contract)==(contract.service,contract.getters):return contract
    raise AssertionError('Unsupported explicit model service/getter pair')


def _require_calc_values(value):
    assert type(value.get('sheetIndex')) is int and value['sheetIndex']==0, 'Calc getter must read fixed sheet zero'
    assert isinstance(value.get('a1Text'),str) and len(value['a1Text'].encode('utf-8'))<=MAX_BODY_BYTES, 'Invalid bounded Calc A1 string'
    assert isinstance(value.get('d1Formula'),str) and len(value['d1Formula'].encode('utf-8'))<=MAX_BODY_BYTES, 'Invalid bounded Calc D1 formula'
    for key in ('b1Value','c1Value','d1Value'):
        assert type(value.get(key)) in (int,float) and math.isfinite(value[key]), 'Invalid finite Calc numeric getter: '+key
    assert type(value.get('isModified')) is bool, 'Invalid Calc modified state'


_SELECTION_FIELDS=(('sheet','Sheet'),('startColumn','StartColumn'),('startRow','StartRow'),
                   ('endColumn','EndColumn'),('endRow','EndRow'))
_SELECTION_INTERFACES={'com.sun.star.sheet.XSheetCellRanges','com.sun.star.sheet.XSheetCellRangeContainer'}


def _selection_scalar(value):
    """Bounded local projection; never stringify an unknown UNO object."""
    result=dict(type=type(value).__name__,value=None)
    if type(value) is str and len(value)>256:result.update(omitted=True,length=len(value))
    elif type(value) is int and value.bit_length()>64:result.update(omitted=True,bitLength=value.bit_length())
    elif type(value) is float and not math.isfinite(value):result.update(omitted=True,nonfinite=True)
    elif type(value) in (int,float,str,bool,type(None)):result['value']=value
    else:result['omitted']=True
    return result


def _calc_selection_attempt(capture):
    value=capture.get('shapeWitness')
    if value is None:return None
    raw=json.dumps(value,ensure_ascii=False,allow_nan=False).encode('utf-8')
    assert len(raw)<=65536,'Calc selection witness exceeded its finite byte bound'
    return json.loads(raw)


def read_calc_selection(controller,*,deadline,capture=None,proxy_type=None,clock=None):
    """Read one rectangle from the retained controller under its original budget.

    XSelectionSupplier permits an object or a collection. Only a missing scalar
    method lookup plus a positively reported sheet-range interface selects the
    indexed path; errors from an existing scalar getter are never caught here.
    """
    clock=clock or time.monotonic;deadline=_finite(deadline)
    proxy_type=proxy_type or type(controller)
    assert type(controller) is proxy_type,'Calc selection controller proxy type changed'
    witness=dict(schemaVersion=1,kind='owned-calc-selection-shape',shape='addressable-range',
        complete=False,helperPid=os.getpid(),controllerId=id(controller),proxyTypeId=id(proxy_type),
        proxyTypeName=proxy_type.__name__,proxyTypeModule=proxy_type.__module__,selectedId=None,childId=None,
        readerDeadline=deadline,startedAt=clock(),finishedAt=None,singularLookupMissing=False,
        interfaceNames=None,preCount=None,postCount=None,index=None,rawCounts=[],rawAddress={},address=None,calls=[])
    if capture is not None:
        capture.clear();capture.update(stage='getSelection',controller=controller,selected=None,shapeWitness=witness)
    def check():
        if _finite(clock())>=deadline:raise TimeoutError('Original Calc selection reader deadline expired')
    def call(name,getter,project):
        check();row=dict(getter=name,startedAt=clock(),returnedAt=None,result=None);witness['calls'].append(row)
        if capture is not None:capture['stage']=name
        value=None
        try:
            check()  # Recording intent must not let a getter cross the original deadline.
            value=getter();row['returnedAt']=clock();row['result']=project(value)
            check();return value
        except BaseException as exc:
            row['error']=dict(type=type(exc).__name__,message=str(exc)[:1024]);raise
        finally:value=None  # Exception tracebacks must not retain a transient indexed proxy.
    def proxy(value,key):
        if value is not None:witness[key]=id(value)
        return None if value is None else dict(proxyId=id(value),typeId=id(type(value)))
    def types(value):
        assert type(value) in (tuple,list) and len(value)<=64,'Invalid bounded Calc selection interface metadata'
        names=[item.typeName for item in value]
        assert all(type(n) is str and 0<len(n)<=256 for n in names),'Invalid Calc selection interface name'
        witness['interfaceNames']=names;return names
    def count(value,key):
        raw=_selection_scalar(value);witness['rawCounts'].append(dict(phase=key,raw=raw))
        if type(value) is int and 0<=value<=0x7fffffff:witness[key]=value
        return raw
    def address(value):
        fields={}
        for key,source in _SELECTION_FIELDS:
            fields[key]=getattr(value,source);witness['rawAddress'][key]=_selection_scalar(fields[key])
        assert all(type(n) is int and 0<=n<=(0x7fff if key=='sheet' else 0x7fffffff)
                   for key,n in fields.items()),'Invalid exact Calc range address scalar'
        assert fields['startColumn']<=fields['endColumn'] and fields['startRow']<=fields['endRow'],'Reversed Calc range address'
        witness['address']=fields;return dict(witness['rawAddress'])
    selected=call('XSelectionSupplier.getSelection',lambda:controller.getSelection(),lambda v:proxy(v,'selectedId'))
    if capture is not None:capture.update(stage='getRangeAddress',selected=selected)
    assert selected is not None,'Calc has no single cell/range selection'
    assert type(selected) is proxy_type,'Calc selection proxy type changed'
    check()
    try:getter=selected.getRangeAddress
    except AttributeError:
        witness.update(shape='cell-range-container',singularLookupMissing=True)
        call('XTypeProvider.getTypes',lambda:selected.getTypes(),types)
        if not set(witness['interfaceNames'])&_SELECTION_INTERFACES:raise
        before=call('XIndexAccess.getCount.before',lambda:selected.getCount(),lambda v:count(v,'preCount'))
        assert type(before) is int and before==1,'Calc selection must contain exactly one range'
        witness['index']=0
        child=None
        try:
            child=call('XIndexAccess.getByIndex[0]',lambda:selected.getByIndex(0),lambda v:proxy(v,'childId'))
            assert type(child) is proxy_type,'Calc indexed range proxy type changed'
            call('XCellRangeAddressable.getRangeAddress[0]',lambda:child.getRangeAddress(),address)
            after=call('XIndexAccess.getCount.after',lambda:selected.getCount(),lambda v:count(v,'postCount'))
            assert type(after) is int and after==1,'Calc selection range count changed'
        finally:child=None
    else:call('XCellRangeAddressable.getRangeAddress',getter,address)
    # ScCellRangeObj::getSpreadsheet creates a fresh wrapper; proxy equality
    # with separately fetched Sheet0 is not sheet identity. getSelection is
    # bound to this already verified retained controller's own DocShell.
    witness.update(complete=True,finishedAt=clock());check()
    value=dict(readOnly=True,source='retained-controller.getSelection',range=witness['address'],shapeWitness=witness)
    _require_calc_selection(value)
    if capture is not None:capture.clear()
    return value


def _same_selection_fact(actual,expected):
    """Receipt joins keep JSON scalar types; Python True == 1 is insufficient."""
    if type(actual) is not type(expected):return False
    if isinstance(expected,dict):
        return set(actual)==set(expected) and all(_same_selection_fact(actual[k],v) for k,v in expected.items())
    if isinstance(expected,list):
        return len(actual)==len(expected) and all(_same_selection_fact(a,b) for a,b in zip(actual,expected))
    return actual==expected


def _require_calc_selection_witness(value):
    proof=value['shapeWitness'];area=value['range']
    assert isinstance(proof,dict) and set(proof)=={'schemaVersion','kind','shape','complete','helperPid','controllerId',
        'proxyTypeId','proxyTypeName','proxyTypeModule','selectedId','childId','readerDeadline','startedAt','finishedAt',
        'singularLookupMissing','interfaceNames','preCount','postCount','index','rawCounts','rawAddress','address','calls'}
    assert type(proof['schemaVersion']) is int and proof['schemaVersion']==1
    assert proof['kind']=='owned-calc-selection-shape' and proof['complete'] is True
    for key in ('helperPid','controllerId','proxyTypeId','selectedId'):_positive(proof[key])
    assert all(type(proof[k]) is str and 0<len(proof[k])<=256 for k in ('proxyTypeName','proxyTypeModule'))
    start=_finite(proof['startedAt']);finish=_finite(proof['finishedAt']);deadline=_finite(proof['readerDeadline'])
    assert start<=finish<deadline
    assert _same_selection_fact(proof['address'],area) and set(proof['rawAddress'])==set(area)
    raw={key:dict(type='int',value=n) for key,n in area.items()}
    assert _same_selection_fact(proof['rawAddress'],raw)
    assert all(n<=(0x7fff if key=='sheet' else 0x7fffffff) for key,n in area.items())
    expected=['XSelectionSupplier.getSelection']
    if proof['shape']=='addressable-range':
        assert proof['singularLookupMissing'] is False and proof['interfaceNames'] is None
        assert all(proof[k] is None for k in ('childId','preCount','postCount','index')) and proof['rawCounts']==[]
        expected+=['XCellRangeAddressable.getRangeAddress'];results=[dict(proxyId=proof['selectedId'],typeId=proof['proxyTypeId']),raw]
    else:
        assert proof['shape']=='cell-range-container' and proof['singularLookupMissing'] is True
        names=proof['interfaceNames']
        assert isinstance(names,list) and len(names)<=64 and all(type(n) is str and 0<len(n)<=256 for n in names)
        assert set(names)&_SELECTION_INTERFACES
        assert type(proof['preCount']) is type(proof['postCount']) is int and proof['preCount']==proof['postCount']==1
        assert type(proof['index']) is int and proof['index']==0;_positive(proof['childId'])
        count=dict(type='int',value=1)
        assert _same_selection_fact(proof['rawCounts'],[dict(phase='preCount',raw=count),dict(phase='postCount',raw=count)])
        expected+=['XTypeProvider.getTypes','XIndexAccess.getCount.before','XIndexAccess.getByIndex[0]',
                   'XCellRangeAddressable.getRangeAddress[0]','XIndexAccess.getCount.after']
        results=[dict(proxyId=proof['selectedId'],typeId=proof['proxyTypeId']),names,count,
                 dict(proxyId=proof['childId'],typeId=proof['proxyTypeId']),raw,count]
    calls=proof['calls'];assert isinstance(calls,list) and len(calls)==len(expected)
    last=start
    for row,name,result in zip(calls,expected,results):
        assert isinstance(row,dict) and set(row)=={'getter','startedAt','returnedAt','result'}
        assert row['getter']==name and _same_selection_fact(row['result'],result)
        begin=_finite(row['startedAt']);end=_finite(row['returnedAt']);assert last<=begin<=end<=finish
        last=end
    _calc_selection_attempt(dict(shapeWitness=proof))


def _require_calc_selection_owner(selection,observation):
    if 'shapeWitness' not in selection:return  # Historical scalar receipts only; fresh-source audit requires proof.
    proof=selection['shapeWitness'];proxy=observation['unoSnapshots']['before']['proxyIdentity']
    assert proof['helperPid']==observation['readerProcess']['pid']==proxy['helperPid']
    assert proof['controllerId']==proxy['retainedIds']['controller']
    for name,key in (('proxyTypeId','proxyTypeId'),('proxyTypeName','proxyTypeName'),('proxyTypeModule','proxyTypeModule')):
        assert proof[name]==proxy[key],'Calc selection witness belongs to another PyUNO type'
    assert _finite(observation['readStartedAt'])<=proof['startedAt']<=proof['finishedAt']<=_finite(observation['readFinishedAt'])


def _require_calc_selection(value):
    assert isinstance(value,dict) and value.get('readOnly') is True
    assert value.get('source')=='retained-controller.getSelection', 'Calc selection getter source differs'
    area=value.get('range')
    assert isinstance(area,dict) and set(area)=={'sheet','startColumn','startRow','endColumn','endRow'}
    assert all(type(n) is int and n>=0 for n in area.values()), 'Invalid Calc range address'
    assert area['startColumn']<=area['endColumn'] and area['startRow']<=area['endRow']
    if 'shapeWitness' in value:_require_calc_selection_witness(value)
    return value


def require_calc_a1_selection(value):
    _require_calc_selection(value)
    assert all(n==0 for n in value['range'].values()), 'Physical CtrlHome did not select exactly A1 on sheet zero'
    return value


def _calc_pending_program_phase(action,sequence):
    assert type(action) is str, 'Invalid Calc pending RPC action type'
    assert type(sequence) is int and 0<=sequence<=120, 'Invalid Calc pending RPC sequence'
    assert (action=='start' and sequence==0) or (action=='read' and sequence>0), 'Invalid Calc pending RPC phase'
    return dict(program=CALC_PENDING_INITIAL_GETTER_CONTRACT,requestAction=action,requestSequence=sequence,
                phase='initial' if action=='start' else 'strict')


def require_calc_pending_program_phase(observation,*,expected_action=None,expected_sequence=None,expected_phase=None):
    proof=observation.get('calcSelectionPhase')
    assert isinstance(proof,dict) and set(proof)=={'program','requestAction','requestSequence','phase'}
    expected=_calc_pending_program_phase(proof['requestAction'],proof['requestSequence'])
    assert _same_selection_fact(proof,expected), 'Calc selection phase differs from the fixed RPC program'
    if expected_action is not None:assert proof['requestAction']==expected_action
    if expected_sequence is not None:
        assert type(expected_sequence) is int and proof['requestSequence']==expected_sequence
    if expected_phase is not None:assert proof['phase']==expected_phase
    return proof


def read_calc_initial_selection(controller,*,deadline,capture=None,proxy_type=None,clock=None):
    """Measure initial ranges; this never qualifies a selection for later input."""
    clock=clock or time.monotonic;deadline=_finite(deadline);proxy_type=proxy_type or type(controller)
    assert type(controller) is proxy_type, 'Initial Calc controller proxy type changed'
    witness=dict(schemaVersion=1,kind='owned-calc-initial-selection-shape',shape='addressable-range',complete=False,
        helperPid=os.getpid(),controllerId=id(controller),proxyTypeId=id(proxy_type),proxyTypeName=proxy_type.__name__,
        proxyTypeModule=proxy_type.__module__,selectedId=None,readerDeadline=deadline,startedAt=clock(),finishedAt=None,
        singularLookupMissing=False,interfaceNames=None,preCount=None,postCount=None,rawCounts=[],entries=[],calls=[])
    if capture is not None:
        capture.clear();capture.update(stage='getSelection',controller=controller,selected=None,shapeWitness=witness)
    def check():
        if _finite(clock())>=deadline:raise TimeoutError('Original Calc initial reader deadline expired')
    def call(name,getter,project):
        check();row=dict(getter=name,startedAt=clock(),returnedAt=None,result=None);witness['calls'].append(row)
        if capture is not None:capture['stage']=name
        value=None
        try:
            check();value=getter();row['returnedAt']=clock();row['result']=project(value)
            _calc_selection_attempt(dict(shapeWitness=witness));check();return value
        except BaseException as exc:
            row['error']=dict(type=type(exc).__name__,message=str(exc)[:1024]);raise
        finally:value=None
    def proxy(value,entry=None):
        if value is not None:
            if entry is None:witness['selectedId']=id(value)
            else:entry['childId']=id(value)
        return None if value is None else dict(proxyId=id(value),typeId=id(type(value)))
    def types(value):
        assert type(value) in (tuple,list) and len(value)<=64, 'Invalid initial Calc interface metadata'
        names=[item.typeName for item in value]
        assert all(type(n) is str and 0<len(n)<=256 for n in names), 'Invalid initial Calc interface name'
        witness['interfaceNames']=names;return names
    def count(value,key):
        raw=_selection_scalar(value);witness['rawCounts'].append(dict(phase=key,raw=raw))
        if type(value) is int and 0<=value<=0x7fffffff:witness[key]=value
        return raw
    def address(value,entry):
        fields={}
        for key,source in _SELECTION_FIELDS:
            fields[key]=getattr(value,source);entry['rawAddress'][key]=_selection_scalar(fields[key])
        assert all(type(n) is int and 0<=n<=(0x7fff if key=='sheet' else 0x7fffffff)
                   for key,n in fields.items()), 'Invalid initial Calc range address scalar'
        assert fields['startColumn']<=fields['endColumn'] and fields['startRow']<=fields['endRow'], 'Reversed initial Calc range'
        entry['address']=fields;return dict(entry['rawAddress'])
    selected=call('XSelectionSupplier.getSelection',lambda:controller.getSelection(),proxy)
    if capture is not None:capture.update(stage='getRangeAddress',selected=selected)
    assert selected is not None and type(selected) is proxy_type, 'Initial Calc selection proxy type changed'
    check()
    try:getter=selected.getRangeAddress
    except AttributeError:
        witness.update(shape='cell-range-container',singularLookupMissing=True)
        call('XTypeProvider.getTypes',lambda:selected.getTypes(),types)
        if not set(witness['interfaceNames'])&_SELECTION_INTERFACES:raise
        before=call('XIndexAccess.getCount.before',lambda:selected.getCount(),lambda v:count(v,'preCount'))
        assert type(before) is int and 1<=before<=64, 'Initial Calc range count must be within 1..64'
        for index in range(before):
            entry=dict(index=index,childId=None,rawAddress={},address=None);witness['entries'].append(entry);child=None
            try:
                child=call('XIndexAccess.getByIndex['+str(index)+']',lambda:selected.getByIndex(index),lambda v:proxy(v,entry))
                assert type(child) is proxy_type, 'Initial indexed Calc proxy type changed'
                call('XCellRangeAddressable.getRangeAddress['+str(index)+']',lambda:child.getRangeAddress(),lambda v:address(v,entry))
            finally:child=None
        after=call('XIndexAccess.getCount.after',lambda:selected.getCount(),lambda v:count(v,'postCount'))
        assert type(after) is int and after==before, 'Initial Calc range count changed'
    else:
        entry=dict(index=None,childId=None,rawAddress={},address=None);witness['entries'].append(entry)
        call('XCellRangeAddressable.getRangeAddress',getter,lambda v:address(v,entry))
    witness.update(complete=True,finishedAt=clock());check()
    value=dict(readOnly=True,source='retained-controller.getSelection',ranges=[e['address'] for e in witness['entries']],shapeWitness=witness)
    _require_calc_initial_selection(value)
    if capture is not None:capture.clear()
    return value


def _require_calc_initial_selection(value):
    assert isinstance(value,dict) and set(value)=={'readOnly','source','ranges','shapeWitness'}
    assert value['readOnly'] is True and value['source']=='retained-controller.getSelection'
    proof=value['shapeWitness'];ranges=value['ranges']
    assert isinstance(proof,dict) and set(proof)=={'schemaVersion','kind','shape','complete','helperPid','controllerId',
        'proxyTypeId','proxyTypeName','proxyTypeModule','selectedId','readerDeadline','startedAt','finishedAt',
        'singularLookupMissing','interfaceNames','preCount','postCount','rawCounts','entries','calls'}
    assert type(proof['schemaVersion']) is int and proof['schemaVersion']==1
    assert proof['kind']=='owned-calc-initial-selection-shape' and proof['complete'] is True
    for key in ('helperPid','controllerId','proxyTypeId','selectedId'):_positive(proof[key])
    assert all(type(proof[k]) is str and 0<len(proof[k])<=256 for k in ('proxyTypeName','proxyTypeModule'))
    start=_finite(proof['startedAt']);finish=_finite(proof['finishedAt']);assert start<=finish<_finite(proof['readerDeadline'])
    entries=proof['entries'];assert isinstance(entries,list) and 1<=len(entries)<=64
    assert isinstance(ranges,list) and _same_selection_fact(ranges,[e['address'] for e in entries])
    names=proof['interfaceNames'];expected=['XSelectionSupplier.getSelection'];results=[dict(proxyId=proof['selectedId'],typeId=proof['proxyTypeId'])]
    scalar=proof['shape']=='addressable-range'
    if scalar:
        assert len(entries)==1 and proof['singularLookupMissing'] is False and names is None
        assert proof['preCount'] is proof['postCount'] is None and proof['rawCounts']==[]
    else:
        assert proof['shape']=='cell-range-container' and proof['singularLookupMissing'] is True
        assert isinstance(names,list) and len(names)<=64 and all(type(n) is str and 0<len(n)<=256 for n in names)
        assert set(names)&_SELECTION_INTERFACES
        assert type(proof['preCount']) is type(proof['postCount']) is int
        assert proof['preCount']==proof['postCount']==len(entries)
        count=dict(type='int',value=len(entries));assert _same_selection_fact(proof['rawCounts'],[dict(phase='preCount',raw=count),dict(phase='postCount',raw=count)])
        expected+=['XTypeProvider.getTypes','XIndexAccess.getCount.before'];results+=[names,count]
    for index,entry in enumerate(entries):
        assert isinstance(entry,dict) and set(entry)=={'index','childId','rawAddress','address'}
        area=entry['address'];_require_calc_selection(dict(readOnly=True,source=value['source'],range=area))
        assert all(n<=(0x7fff if key=='sheet' else 0x7fffffff) for key,n in area.items())
        raw={key:dict(type='int',value=n) for key,n in area.items()};assert _same_selection_fact(entry['rawAddress'],raw)
        if scalar:
            assert entry['index'] is entry['childId'] is None
            expected+=['XCellRangeAddressable.getRangeAddress'];results+=[raw]
        else:
            assert type(entry['index']) is int and entry['index']==index;_positive(entry['childId'])
            expected+=['XIndexAccess.getByIndex['+str(index)+']','XCellRangeAddressable.getRangeAddress['+str(index)+']']
            results+=[dict(proxyId=entry['childId'],typeId=proof['proxyTypeId']),raw]
    if not scalar:expected+=['XIndexAccess.getCount.after'];results+=[count]
    calls=proof['calls'];assert isinstance(calls,list) and len(calls)==len(expected);last=start
    for row,name,result in zip(calls,expected,results):
        assert isinstance(row,dict) and set(row)=={'getter','startedAt','returnedAt','result'}
        assert row['getter']==name and _same_selection_fact(row['result'],result)
        begin=_finite(row['startedAt']);end=_finite(row['returnedAt']);assert last<=begin<=end<=finish;last=end
    _calc_selection_attempt(dict(shapeWitness=proof))
    return value


def _path(value):
    assert isinstance(value,str) and value, 'Missing absolute native path'
    path=PureWindowsPath(value)
    if path.is_absolute():
        assert '..' not in path.parts
        return str(path).casefold()
    path=PurePosixPath(value)
    assert path.is_absolute() and '..' not in path.parts, 'Relative native path'
    return str(path)


def _join(root,relative):
    p=PureWindowsPath(str(root))
    return str(p/relative) if p.is_absolute() else str(PurePosixPath(str(root))/relative)


def _positive(value):
    assert type(value) is int and value>0, 'Missing positive native identifier'
    return value


def _finite(value):
    assert type(value) in (int,float) and math.isfinite(value) and value>=0, 'Invalid controller monotonic time'
    return value


def _pipe(arguments):
    # Same public pinned parser as the existing accessibility harness.
    assert isinstance(arguments,list) and 1<=len(arguments)<=64 and all(isinstance(x,str) for x in arguments)
    return _parse_private_pipe(arguments)


def _profile(arguments):
    values=[v[len('-env:UserInstallation='):] for v in arguments if v.startswith('-env:UserInstallation=')]
    assert len(values)==1,'Expected one private Office profile'
    value=values[0];uri=urlsplit(value)
    assert uri.scheme=='file' and not uri.netloc and not uri.query and not uri.fragment
    path=unquote(uri.path)
    assert path.startswith('/') and '..' not in PurePosixPath(path).parts and '\\' not in path
    return value


def office_profile_url(arguments):
    """Parse the single original profile URL from native Windows argv, without I/O."""
    return _profile(arguments)


def _profile_decoded_path(profile_url):
    assert isinstance(profile_url,str) and _profile(['-env:UserInstallation='+profile_url])==profile_url
    path=unquote(urlsplit(profile_url).path,errors='strict')
    assert re.match(r'^/[A-Za-z]:/',path) and '\x00' not in path, 'Profile URI must identify a local drive directory'
    local=PureWindowsPath(path[1:])
    assert re.fullmatch('[A-Za-z]:',local.drive) and local.is_absolute() and '..' not in local.parts
    return str(local)


def _profile_canonical_path(value):
    assert isinstance(value,str) and '\x00' not in value
    if value.startswith('\\\\?\\'):value=value[4:]
    path=PureWindowsPath(value)
    assert re.fullmatch('[A-Za-z]:',path.drive) and path.is_absolute() and '..' not in path.parts, 'Native profile path must be a local DOS directory'
    return str(path)


def _profile_directory_identity(info):
    assert isinstance(info,dict), 'Missing native profile directory information'
    for key in ('fileAttributes','volumeSerialNumber','fileIndexHigh','fileIndexLow','fileType'):
        assert type(info.get(key)) is int and 0<=info[key]<=0xffffffff
    for key in ('creationTime','lastAccessTime','lastWriteTime','size','numberOfLinks'):
        assert type(info.get(key)) is int and info[key]>=0
    assert info['fileType']==1 and info['fileAttributes']&0x10, 'Profile HANDLE does not identify a disk directory'
    assert info['fileIndexHigh'] or info['fileIndexLow'], 'Native profile directory FileID is missing'
    # Office legitimately changes directory contents/times while editing.
    return (_path(_profile_canonical_path(info.get('finalPath'))),info['volumeSerialNumber'],info['fileIndexHigh'],info['fileIndexLow'])


def require_profile_directory_witness(witness,profile_url,recheck=None):
    """Pure replay of native URL->retained DIRECTORYHANDLE canonical identity."""
    assert isinstance(witness,dict) and type(witness.get('schemaVersion')) is int and witness['schemaVersion']==1
    assert witness.get('kind')=='native-owned-profile-directory' and witness.get('profileUrl')==profile_url
    assert witness.get('decodedPath')==_profile_decoded_path(profile_url), 'Profile directory was not opened from original native argv'
    _positive(witness.get('handleValue'))
    for key,value in (('desiredAccess',PROFILE_DIRECTORY_ACCESS),('shareMode',PROFILE_DIRECTORY_SHARE),('openFlags',PROFILE_DIRECTORY_FLAGS)):
        assert type(witness.get(key)) is int and witness[key]==value
    identity=_profile_directory_identity(witness.get('openedInfo'))
    assert _path(_profile_canonical_path(witness.get('canonicalPath')))==identity[0], 'Profile canonical path differs from native HANDLE'
    if recheck is not None:
        assert _profile_directory_identity(recheck)==identity, 'Retained native profile directory identity changed'
    return witness


def canonical_profile_projection(witness,profile_url):
    """Archive-join descriptor from actual canonical path/FileID, never an alias guess."""
    require_profile_directory_witness(witness,profile_url)
    path,volume,high,low=_profile_directory_identity(witness['openedInfo'])
    return dict(profileUrl=profile_url,canonicalPath=path,volumeSerialNumber=volume,fileIndexHigh=high,fileIndexLow=low)


def _require_binding(binding,suite_root):
    assert isinstance(binding,dict), 'Missing original Writer binding'
    for key in ('shellPid','shellCreationTime','officePid','officeCreationTime','suiteHwnd','parentHwnd','childHwnd','rootHwnd'):_positive(binding.get(key))
    assert binding['shellPid']!=binding['officePid'] and binding['rootHwnd']==binding['suiteHwnd']
    assert len({binding['suiteHwnd'],binding['parentHwnd'],binding['childHwnd']})==3
    assert _path(binding.get('expectedImage'))==_path(_join(suite_root,'Office/program/soffice.bin'))
    assert isinstance(binding.get('privatePipe'),str) and re.fullmatch(r'OpenGeul_[0-9a-f]{32}',binding['privatePipe'])


def _require_native(raw,binding,suite_root):
    _require_binding(binding,suite_root)
    assert isinstance(raw,dict), 'Missing raw retained native snapshot'
    for name,pid,created,image in (
        ('shell',binding['shellPid'],binding['shellCreationTime'],_join(suite_root,'OpenGeul.Office.exe')),
        ('office',binding['officePid'],binding['officeCreationTime'],binding['expectedImage'])):
        row=raw.get(name,{})
        assert row.get('pid')==pid and type(row.get('pid')) is int
        assert row.get('creationTime')==created and type(created) is int and created>0
        _positive(row.get('handleValue'))
        assert _path(row.get('image'))==_path(image), 'Retained executable changed'
        assert type(row.get('waitResult')) is int and type(row.get('exitCode')) is int
        assert row['waitResult']==258 and row['exitCode']==259, 'Original process is no longer alive'
    windows=raw.get('windows',{})
    for name,hwnd,pid in (('suite',binding['suiteHwnd'],binding['shellPid']),
                          ('parent',binding['parentHwnd'],binding['shellPid']),
                          ('child',binding['childHwnd'],binding['officePid'])):
        row=windows.get(name,{})
        assert row.get('isWindow') is True and row.get('hwnd')==hwnd and row.get('pid')==pid
        assert row.get('rootHwnd')==binding['suiteHwnd'], 'Window left original Suite root'
    assert windows['suite']['parentHwnd']==0
    assert windows['parent']['parentHwnd']==binding['suiteHwnd'], 'Original panel parent changed'
    assert windows['child']['parentHwnd']==binding['parentHwnd'], 'Original editor parent changed'
    assert windows.get('exportedParentHwnd')==binding['parentHwnd'] and windows.get('exportedChildHwnd')==binding['childHwnd']
    assert raw.get('privatePipe')==binding['privatePipe']==_pipe(raw.get('officeCommandLine')), 'Original private pipe changed'
    assert raw.get('profileUrl')==_profile(raw['officeCommandLine']), 'Private profile URL is missing'
    profile=raw.get('profileDirectory',{})
    assert isinstance(profile.get('recheck'),dict), 'Native profile DIRECTORY recheck is missing'
    require_profile_directory_witness(profile.get('witness'),raw['profileUrl'],profile['recheck'])


def _require_pair(before,after,binding,suite_root):
    _require_native(before,binding,suite_root);_require_native(after,binding,suite_root)
    for name in ('shell','office'):
        assert before[name]['handleValue']==after[name]['handleValue'], 'Retained process HANDLE was replaced'
    assert before['officeCommandLine']==after['officeCommandLine'] and before['profileUrl']==after['profileUrl'], 'Original Office command/profile changed'
    assert before['profileDirectory']['witness']==after['profileDirectory']['witness'], 'Retained original profile DIRECTORY HANDLE was replaced'


def _require_uno(raw,binding,*,contract=_WRITER_CONTRACT):
    assert isinstance(raw,dict) and type(raw.get('frameCount')) is int and 1<=raw['frameCount']<=8
    frames=raw.get('frames')
    assert isinstance(frames,list) and len(frames)==raw['frameCount']
    assert all(type(r.get('index')) is int for r in frames) and [r.get('index') for r in frames]==list(range(raw['frameCount'])), 'Frame enumeration is incomplete'
    matches=[r for r in frames if r.get('containerHwnd')==binding['childHwnd']]
    assert len(matches)==1 and type(raw.get('matchedFrameIndex')) is int and raw.get('matchedFrameIndex')==matches[0]['index'], 'Original native frame is ambiguous or foreign'
    retained=raw.get('retained',{})
    for name in ('frame','controller','model'):
        value=binding[name+'Identity']
        assert isinstance(value,str) and re.fullmatch(r'pyuno-proxy:0x[1-9a-f][0-9a-f]*',value), 'Missing retained helper-local proxy identity'
        assert retained.get(name)==value
    proxy=raw.get('proxyIdentity',{})
    assert proxy.get('proxyTypeName')=='pyuno' and isinstance(proxy.get('proxyTypeModule'),str)
    for key in ('helperPid','localContextId','proxyTypeId'):_positive(proxy.get(key))
    ids=proxy.get('retainedIds',{});types=proxy.get('typeMatches',{})
    assert set(ids)==set(types)=={'frame','controller','model'} and all(v is True for v in types.values())
    assert len(set(ids.values()))==3
    for name,value in ids.items():
        _positive(value);assert retained[name]=='pyuno-proxy:0x'+format(value,'x')
    eq=raw.get('equalities',{})
    assert set(eq)=={'frame','controller','model','controllerFrame','modelController'} and all(v is True for v in eq.values()), 'Original live UNO links changed'
    assert raw.get('modelService')==contract.service and raw.get('documentUrl')==binding['documentUrl'], 'Foreign Writer model or URL' if contract==_WRITER_CONTRACT else 'Foreign Calc model or URL'


def _reader_member(row,binding,suite_root,alive,*,exiting=False):
    assert isinstance(row,dict) and row.get('inOwnedJob') is True and row.get('isInJobApiSucceeded') is True
    _positive(row.get('jobHandleValue'))
    assert _positive(row.get('pid')) not in (binding['shellPid'],binding['officePid'])
    _positive(row.get('creationTime'));_positive(row.get('handleValue'))
    root=_path(_join(suite_root,'Office/program'))
    image=_path(row.get('image'))
    assert image.startswith(root+('\\' if '\\' in root else '/'))
    tail=image[len(root)+1:].replace('\\','/')
    assert tail=='python.exe' or re.fullmatch(r'python-core-3\.13\.15/bin/python\.exe',tail), 'Reader job contains a foreign executable'
    assert type(row.get('waitResult')) is int and type(row.get('exitCode')) is int
    assert row.get('waitResult')==(258 if alive else 0) and row.get('exitCode')==(0 if exiting else 259 if alive else 0), 'Reader did not exit normally' if not alive else 'Reader is not alive'
    assert not exiting or alive, 'Only an unsignaled release sample can be pending'


def _require_member_state_sample(row):
    """Replay the ordered native pair; never project a later exit back into Wait."""
    assert type(row.get('sampleIndex')) is int and 0<=row['sampleIndex']<MAX_MEMBER_STATE_SAMPLES
    assert row.get('phase') in ('read','release')
    started=_finite(row.get('sampleStartedAt'));finished=_finite(row.get('sampleFinishedAt'))
    assert started<=finished
    membership=row.get('membershipCall',{})
    assert membership.get('api')=='IsProcessInJob' and membership.get('result') is True and membership.get('inOwnedJob') is True
    assert membership.get('handleValue')==row['handleValue'] and membership.get('jobHandleValue')==row['jobHandleValue']
    calls=row.get('stateCalls')
    assert isinstance(calls,list) and len(calls)==2
    wait,exit_=calls
    assert wait.get('api')=='WaitForSingleObject' and wait.get('timeoutMilliseconds')==0
    assert type(wait.get('result')) is int and wait['result'] in (0,258) and row.get('waitResult')==wait['result']
    assert exit_.get('api')=='GetExitCodeProcess' and exit_.get('result') is True
    assert type(exit_.get('exitCode')) is int and 0<=exit_['exitCode']<=0xffffffff and row.get('exitCode')==exit_['exitCode']
    previous=started
    for call in (membership,wait,exit_):
        assert call.get('handleValue')==row['handleValue']
        assert type(call.get('lastError')) is int and 0<=call['lastError']<=0xffffffff
        at=_finite(call.get('observedAt'));assert previous<=at<=finished;previous=at


def _member_samples_receipt(rows):
    """Keep every raw result while storing each retained identity only once."""
    identities=[];samples=[]
    for row in rows:
        identity={key:row[key] for key in ('pid','creationTime','image','handleValue','jobHandleValue')}
        if identity not in identities:identities.append(identity)
        calls=[]
        member=row.get('membershipCall')
        if member:calls.append([member['api'],member['observedAt'],member['result'],member['inOwnedJob'],member['lastError']])
        for call in row['stateCalls']:
            values=[call['api'],call['observedAt'],call['result']]
            if call['api']=='GetExitCodeProcess':values.append(call['exitCode'])
            calls.append(values+[call['lastError']])
        samples.append(dict(index=row['sampleIndex'],member=identities.index(identity),phase=row['phase'],
            times=[row['sampleStartedAt'],row['sampleFinishedAt']],calls=calls))
    return dict(memberStateIdentities=identities,memberStateSamples=samples)


def _expand_member_sample(sample,identities):
    assert isinstance(sample,dict) and type(sample.get('member')) is int and 0<=sample['member']<len(identities)
    assert isinstance(sample.get('times'),list) and len(sample['times'])==2
    row=dict(identities[sample['member']],sampleIndex=sample.get('index'),phase=sample.get('phase'),
        sampleStartedAt=sample['times'][0],sampleFinishedAt=sample['times'][1])
    calls=sample.get('calls');assert isinstance(calls,list) and [len(c) if isinstance(c,list) else 0 for c in calls]==[5,4,5]
    membership,wait,exit_=calls
    row.update(inOwnedJob=membership[3],isInJobApiSucceeded=membership[2],waitResult=wait[2],exitCode=exit_[3],
        membershipCall=dict(api=membership[0],observedAt=membership[1],result=membership[2],inOwnedJob=membership[3],lastError=membership[4],handleValue=row['handleValue'],jobHandleValue=row['jobHandleValue']),
        stateCalls=[dict(api=wait[0],observedAt=wait[1],result=wait[2],lastError=wait[3],handleValue=row['handleValue'],timeoutMilliseconds=0),
            dict(api=exit_[0],observedAt=exit_[1],result=exit_[2],exitCode=exit_[3],lastError=exit_[4],handleValue=row['handleValue'])])
    return row


def _require_launch(receipt,job=None):
    assert isinstance(receipt,dict) and receipt.get('firstFailure') is None, 'Missing or failed actual helper launch APIs'
    steps=receipt.get('steps')
    assert isinstance(steps,list) and [r.get('api') for r in steps]==[
        'CreateJobObjectW','CreateProcessW','AssignProcessToJobObject','ResumeThread','CloseHandle']
    assert all(type(row.get('lastError')) is int and 0<=row['lastError']<=0xffffffff for row in steps), 'Raw helper launch LastError is missing'
    created,process,assigned,resumed,closed=steps
    job_handle=_positive(created.get('handleValue'))
    if job is not None:assert job_handle==job
    assert process.get('result') is True and type(process.get('creationFlags')) is int and process['creationFlags']==0x08000404
    assert process.get('inheritHandles') is False and isinstance(process.get('application'),str) and isinstance(process.get('command'),str)
    assert 0<len(process['command'])<=32767
    pid=_positive(process.get('pid'));_positive(process.get('threadId'))
    process_handle=_positive(process.get('processHandleValue'));thread_handle=_positive(process.get('threadHandleValue'))
    assert assigned.get('result') is True and assigned.get('jobHandleValue')==job_handle and assigned.get('processHandleValue')==process_handle
    assert type(resumed.get('previousSuspendCount')) is int and resumed['previousSuspendCount']==1 and resumed.get('threadHandleValue')==thread_handle
    assert closed.get('result') is True and closed.get('handleValue')==thread_handle, 'Initial helper thread HANDLE was not closed'
    return pid,process_handle,job_handle


def _require_owned_observation(observation,binding,suite_root,contract):
    assert isinstance(observation,dict) and observation.get('kind')==contract.kind
    assert observation.get('bindingBefore')==binding==observation.get('bindingAfter')
    for key in ('retainedProcessHandle','readOnlyObservation','sameFrameControllerModelVerified','readCallCleanupSucceeded','readerStillRetained'):
        assert observation.get(key) is True, 'Incomplete read-only observation: '+key
    assert observation.get('handleSignaled') is False and observation.get('operations')==list(contract.operations)
    require_console_host_witness(observation.get('systemConsoleHost'),observation.get('systemConsoleHostRecheck'))
    assert isinstance(observation.get('systemConsoleHostRecheck'),dict)
    native=observation.get('nativeSnapshots',{})
    for prefix in ('controller','helper'):
        _require_pair(native.get(prefix+'Before'),native.get(prefix+'After'),binding,suite_root)
    assert native['controllerBefore']['officeCommandLine']==native['helperBefore']['officeCommandLine'], 'Helper resolved another private transport/profile'
    assert canonical_profile_projection(native['controllerBefore']['profileDirectory']['witness'],native['controllerBefore']['profileUrl'])==canonical_profile_projection(native['helperBefore']['profileDirectory']['witness'],native['helperBefore']['profileUrl']), 'Helper opened a different canonical profile directory'
    uno=observation.get('unoSnapshots',{})
    _require_uno(uno.get('before'),binding,contract=contract);_require_uno(uno.get('after'),binding,contract=contract)
    assert uno['before']['proxyIdentity']==uno['after']['proxyIdentity']
    assert uno['before']['proxyIdentity']['helperPid']==observation.get('readerProcess',{}).get('pid')
    _reader_member(observation.get('readerProcess'),binding,suite_root,True)
    _require_launch(observation.get('helperLaunch'),observation['readerProcess']['jobHandleValue'])
    assert _path(observation['helperLaunch']['steps'][1]['application'])==_path(_join(suite_root,'Office/program/python.exe'))
    observed=observation.get('pythonIdentity',{}).get('observed',{})
    assert _path(observation['readerProcess']['image'])==_path(observed.get('processImage')), 'Actual reader process does not match the packaged Python observation'
    if contract in (_CALC_CONTRACT,_CALC_PENDING_CONTRACT,_CALC_PENDING_INITIAL_CONTRACT):_require_calc_values(observation)
    if contract==_CALC_PENDING_CONTRACT:
        from calc_pending_input import require_pending_receipt
        _require_calc_selection(observation.get('calcSelection'))
        _require_calc_selection_owner(observation['calcSelection'],observation)
        require_pending_receipt(observation.get('pendingInput'),binding['childHwnd'])
    if contract==_CALC_PENDING_INITIAL_CONTRACT:
        from calc_pending_input import require_pending_receipt
        phase=require_calc_pending_program_phase(observation)
        if phase['phase']=='initial':
            assert 'calcSelection' not in observation
            selection=observation.get('calcInitialSelection');_require_calc_initial_selection(selection)
        else:
            assert 'calcInitialSelection' not in observation
            selection=observation.get('calcSelection')
            assert isinstance(selection,dict) and 'shapeWitness' in selection
            _require_calc_selection(selection)
        _require_calc_selection_owner(selection,observation)
        require_pending_receipt(observation.get('pendingInput'),binding['childHwnd'])
    if contract in _EDIT_MODULES:
        from ime_semantic_context import require_edit_context
        require_edit_context(observation.get('editContext'),_EDIT_MODULES[contract],binding['childHwnd'])
        assert type(observation.get('isModified')) is bool
        if contract==_CALC_EDIT_CONTRACT:
            from calc_pending_input import require_pending_receipt
            _require_calc_values(observation);_require_calc_selection(observation.get('calcSelection'))
            _require_calc_selection_owner(observation['calcSelection'],observation)
            require_pending_receipt(observation['editContext'].get('pendingInput'),binding['childHwnd'])
    return observation


def require_owned_observation(observation,binding,suite_root):
    """Replay the unchanged fixed Writer contract, with no native calls or I/O."""
    return _require_owned_observation(observation,binding,suite_root,_WRITER_CONTRACT)


def require_owned_model_observation(observation,binding,suite_root,*,expected_service,getter_contract):
    """Pure replay against an explicit caller-selected service/getter pair."""
    return _require_owned_observation(observation,binding,suite_root,_model_contract(expected_service,getter_contract))


def _require_job_census(group,job,deadline):
    """Pure replay of complete, bounded raw class-3 calls; never accept partial IDs."""
    assert isinstance(group,dict) and type(group.get('schemaVersion')) is int and group['schemaVersion']==1
    assert group.get('kind')=='private-job-process-census'
    assert group.get('api')=='QueryInformationJobObject' and type(group.get('informationClass')) is int and group['informationClass']==3
    for key,expected in (('jobHandleValue',job),('capacity',128),('maxAttempts',3),
                         ('bufferBytes',1032),('headerBytes',8),('processIdBytes',8)):
        assert type(group.get(key)) is int and group[key]==expected
    assert type(group.get('sequence')) is int and 0<=group['sequence']<MAX_JOB_CENSUS_GROUPS
    assert group.get('phase') in ('read-members','release-members','release-final','forced-final')
    assert group.get('classification')=='complete' and 'error' not in group
    started=_finite(group.get('startedAt'));finished=_finite(group.get('finishedAt'))
    assert started<=finished<=deadline
    calls=group.get('calls');assert isinstance(calls,list) and 1<=len(calls)<=3
    previous=started
    for index,row in enumerate(calls,1):
        assert isinstance(row,dict) and type(row.get('attempt')) is int and row['attempt']==index
        assert row.get('result') is True
        assert type(row.get('lastError')) is int and 0<=row['lastError']<=0xffffffff
        for key in ('assigned','count','returnLength'):assert type(row.get(key)) is int
        assert 0<=row['count']<=row['assigned']<=128
        assert 8+8*row['count']<=row['returnLength']<=1032
        pids=row.get('pids');assert isinstance(pids,list) and len(pids)==row['count']
        assert all(type(pid) is int and 0<pid<=0xffffffff for pid in pids) and len(set(pids))==len(pids)
        assert previous<=_finite(row.get('startedAt'))<=_finite(row.get('finishedAt'))<=finished
        previous=row['finishedAt']
        if index<len(calls):
            assert row['count']<row['assigned'] and row.get('classification')=='incomplete'
        else:assert row['count']==row['assigned'] and row.get('classification')=='complete'
    return group


def _require_cleanup_censuses(cleanup,job,members,deadline):
    final=_require_job_census(cleanup.get('lastJobCensus'),job,deadline)
    assert final['phase']=='release-final' and final['calls'][-1]['pids']==[]
    assert final['startedAt']>=max(row['sampleFinishedAt'] for row in members)
    assert cleanup['startedAt']<=final['startedAt']<=final['finishedAt']<=cleanup['finishedAt']
    anomalies=cleanup.get('jobCensusAnomalies')
    assert isinstance(anomalies,list) and len(anomalies)<=MAX_JOB_CENSUS_ANOMALIES
    previous_sequence=-1;previous_finish=0;known={row['pid'] for row in members}
    for group in anomalies:
        _require_job_census(group,job,deadline)
        assert group['phase']!='forced-final', 'Successful cleanup contains a forced helper-job census'
        assert len(group['calls'])>=2, 'Anomalous census lost its original incomplete call'
        assert previous_sequence<group['sequence']<=final['sequence']
        assert previous_finish<=group['startedAt']
        previous_sequence=group['sequence'];previous_finish=group['finishedAt']
        if group['phase']=='read-members':assert group['finishedAt']<=cleanup['startedAt']
        else:assert group['startedAt']>=cleanup['startedAt']
        assert all(set(row['pids'])<=known for row in group['calls']), 'Census contains an unobserved helper member'
        if group['sequence']==final['sequence']:assert group==final
        else:assert group['finishedAt']<=final['startedAt']
    if len(final['calls'])>=2:assert final in anomalies, 'Resolved final census lost incomplete-call history'


def _require_physical_cleanup(cleanup,binding,deadline,*,contract=_WRITER_CONTRACT):
    """Replay final helper quiescence separately from every still-retained read."""
    assert isinstance(cleanup,dict) and cleanup.get('kind')==contract.cleanup_kind
    assert cleanup.get('deadline')==deadline and _finite(cleanup.get('startedAt'))<=_finite(cleanup.get('finishedAt'))<=_finite(deadline)
    assert cleanup.get('terminated') is False and cleanup.get('errors')==[] and cleanup.get('finalJobPids')==[]
    # Infer only a lexical root, never resolve a recorded Windows path on Linux.
    image=binding['expectedImage'];p=PureWindowsPath(image)
    root=str(p.parents[2]) if p.is_absolute() else str(PurePosixPath(image).parents[2])
    _require_pair(cleanup.get('nativeBefore'),cleanup.get('nativeAfter'),binding,root)
    members=cleanup.get('readerMembers')
    assert isinstance(members,list) and members and len(members)<=128
    assert len({r.get('pid') for r in members})==len(members)
    console=require_console_host_witness(cleanup.get('systemConsoleHost'),cleanup.get('systemConsoleHostRecheck'))
    assert isinstance(cleanup.get('systemConsoleHostRecheck'),dict)
    roles=[_job_member(member,binding,root,False,console) for member in members]
    assert roles.count('owned-console-host')<=1,'Multiple ancillary console hosts are not accepted'
    for member in members:_require_member_state_sample(member)
    samples=cleanup.get('memberStateSamples')
    assert isinstance(samples,list) and 1<=len(samples)<=MAX_MEMBER_STATE_SAMPLES, 'Missing bounded raw member state samples'
    identities=cleanup.get('memberStateIdentities')
    assert isinstance(identities,list) and 1<=len(identities)<=128
    assert len({r.get('pid') for r in identities})==len(identities)
    assert {r['pid'] for r in identities}=={r['pid'] for r in members}, 'Unobserved retained member identity'
    final={row['pid']:row for row in members};latest={};terminal=set();previous=0
    for index,sample in enumerate(samples):
        row=_expand_member_sample(sample,identities)
        _require_member_state_sample(row)
        assert row['sampleIndex']==index and row['pid'] in final
        assert previous<=row['sampleStartedAt']<=row['sampleFinishedAt']<=cleanup['finishedAt'];previous=row['sampleFinishedAt']
        if row['phase']=='release':assert row['sampleStartedAt']>=cleanup['startedAt'], 'Release sample predates cleanup'
        else:assert row['sampleFinishedAt']<=cleanup['startedAt'], 'Read sample follows cleanup start'
        for key in ('pid','creationTime','handleValue','jobHandleValue','image'):
            assert row[key]==final[row['pid']][key], 'Retained member generation/HANDLE changed'
        exiting=row['phase']=='release' and (row['waitResult'],row['exitCode'])==(258,0)
        _job_member(row,binding,root,row['waitResult']==258,console,exiting=exiting)
        key=(row['pid'],row['handleValue'])
        assert key not in terminal or row['waitResult']==0, 'Terminated retained process became unsignaled'
        if row['waitResult']==0:terminal.add(key)
        latest[row['pid']]=row
    assert latest==final, 'Final members are not the last actual same-HANDLE samples'
    assert all(row['phase']=='release' and row['sampleStartedAt']>=cleanup['startedAt'] for row in members)
    ack=cleanup.get('releaseAcknowledgement',{})
    assert ack.get('action')=='release' and ack.get('proxiesReleased') is True
    helper_profile=ack.get('profileDirectory',{})
    assert isinstance(helper_profile.get('recheck'),dict), 'Helper profile DIRECTORY release proof is missing'
    profile_url=cleanup['nativeBefore']['profileUrl']
    require_profile_directory_witness(helper_profile.get('witness'),profile_url,helper_profile['recheck'])
    assert canonical_profile_projection(helper_profile['witness'],profile_url)==canonical_profile_projection(cleanup['nativeBefore']['profileDirectory']['witness'],profile_url), 'Released helper profile differs from original directory'
    helper_closures=ack.get('observerHandleClosures')
    assert isinstance(helper_closures,list) and len(helper_closures)==3 and all(row.get('result') is True for row in helper_closures), 'Helper native HANDLE cleanup failed'
    assert {row.get('kind') for row in helper_closures}=={'shell','office','profile-directory'}
    assert [row.get('handleValue') for row in helper_closures if row['kind']=='profile-directory']==[helper_profile['witness']['handleValue']], 'Actual helper profile DIRECTORY HANDLE was not closed'
    readers=[r for r in members if r['pid']==ack.get('readerPid')]
    assert len(readers)==1
    _reader_member(readers[0],binding,root,False)
    assert _path(readers[0]['image'])==_path(_join(root,'Office/program/python-core-3.13.15/bin/python.exe')), 'Release acknowledgement is not the actual core Python reader'
    job=_positive(cleanup.get('jobHandleValue'))
    launch_pid,launch_handle,_=_require_launch(cleanup.get('helperLaunch'),job)
    assert _path(cleanup['helperLaunch']['steps'][1]['application'])==_path(_join(root,'Office/program/python.exe'))
    assert launch_pid in {r['pid'] for r in members}
    assert all(r['jobHandleValue']==job for r in members)
    _require_cleanup_censuses(cleanup,job,members,deadline)
    closures=cleanup.get('handleClosures')
    assert isinstance(closures,list) and all(r.get('result') is True for r in closures)
    expected={('profile-directory',cleanup['nativeAfter']['profileDirectory']['witness']['handleValue']),('system-console-file',console['handleValue']),('job',job),('shell',cleanup['nativeAfter']['shell']['handleValue']),('office',cleanup['nativeAfter']['office']['handleValue'])}
    expected|={('member',r['handleValue']) for r in members}
    actual={(r.get('kind'),r.get('handleValue')) for r in closures}
    assert len(actual)==len(closures) and expected<=actual and [(r.get('handleValue')) for r in closures if r.get('kind')=='process']==[launch_handle], 'Missing actual owned HANDLE closure'
    return cleanup



def require_reader_cleanup(cleanup,binding,deadline):
    """A successful model context additionally requires complete physical cleanup."""
    assert isinstance(binding,dict),'No Writer model binding was established'
    assert cleanup.get('binding')==binding and cleanup.get('cleanupSucceeded') is True
    assert cleanup.get('physicalCleanupSucceeded') is True and cleanup.get('contextQualified') is True
    return _require_physical_cleanup(cleanup,binding,deadline)


def require_model_reader_cleanup(cleanup,binding,deadline,*,expected_service,getter_contract):
    """Use the same raw cleanup proof, with an explicit expected model kind."""
    contract=_model_contract(expected_service,getter_contract)
    assert isinstance(binding,dict), 'No explicit model binding was established'
    assert cleanup.get('binding')==binding and cleanup.get('cleanupSucceeded') is True
    assert cleanup.get('physicalCleanupSucceeded') is True and cleanup.get('contextQualified') is True
    return _require_physical_cleanup(cleanup,binding,deadline,contract=contract)


class ReaderBackendError(AssertionError):
    def __init__(self,raw):
        self.raw=raw
        super().__init__('Owned Writer reader failed: '+str(raw.get('error')))


def _require_reply(raw,sequence,action):
    assert isinstance(raw,dict) and raw.get('sequence')==sequence and raw.get('action')==action, 'Foreign or stale reader reply'
    if raw.get('ok') is not True:raise ReaderBackendError(raw)
    return raw


def _safe_file(path,existing=True):
    path=Path(path)
    for parent in (path.parent,*path.parent.parents):
        metadata=parent.lstat()
        assert stat.S_ISDIR(metadata.st_mode) and not parent.is_symlink() and not (getattr(metadata,'st_file_attributes',0)&0x400), 'Reader transport directory is linked'
    if existing:
        metadata=path.lstat()
        assert stat.S_ISREG(metadata.st_mode) and not path.is_symlink() and not (getattr(metadata,'st_file_attributes',0)&0x400), 'Reader transport file is linked'
        assert metadata.st_size<=MAX_JSON_BYTES, 'Reader transport exceeded its finite byte limit'
    else:assert not path.exists() and not path.is_symlink(), 'Reader transport name was reused'


def _atomic_json(path,value):
    path=Path(path);_safe_file(path,False)
    data=json.dumps(value,ensure_ascii=False,allow_nan=False).encode('utf-8')
    assert len(data)<=MAX_JSON_BYTES, 'Reader transport exceeded its finite byte limit'
    temp=path.with_name(path.name+'.tmp');_safe_file(temp,False)
    with temp.open('xb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
    assert not path.exists();os.replace(temp,path)


def _read_json(path):
    path=Path(path);_safe_file(path)
    with path.open('rb') as stream:data=stream.read(MAX_JSON_BYTES+1)
    assert len(data)<=MAX_JSON_BYTES
    _safe_file(path)
    return json.loads(data.decode('utf-8'))


def _calc_selection_diagnostic_header(sequence,action,reader,capture,deadline,error,*,clock=time.monotonic):
    """Only local data: this skeleton accompanies an already fatal reader error."""
    selected=capture.get('selected')
    proxy=None if selected is None else dict(type=type(selected).__name__,module=type(selected).__module__,localId=id(selected))
    return dict(schemaVersion=1,kind='failed-calc-selection-diagnostic',status='not-started',reason=None,
        sequence=sequence,action=action,helperPid=os.getpid(),readerDeadline=deadline,startedAt=clock(),
        primaryErrorSha256=hashlib.sha256(json.dumps(error,ensure_ascii=False,allow_nan=False).encode()).hexdigest(),
        selectedProxy=proxy,selectionStage=capture.get('stage'),selectionAttempt=error.get('calcSelectionAttempt'),interfaceNames=None,implementation=None,
        services=None,preCount=None,postCount=None,rawCounts=[],indexedAddresses=[],calls=[],guard=None,
        pendingRequest=False,errors=[],qualification=False)


class _SelectionDiagnosticStop(Exception):pass


def _collect_calc_selection_diagnostic(directory,reader,anchor,capture,header,*,clock=time.monotonic):
    """Post-failure observations only; never alters the primary reply or accepts a range."""
    state=json.loads(json.dumps(header,allow_nan=False));directory=Path(directory)
    selected=capture.get('selected');records=0
    def emit():
        nonlocal records
        assert records<140,'Selection diagnostic record bound exceeded'
        data=json.dumps(state,ensure_ascii=False,allow_nan=False).encode()
        assert len(data)<=65536,'Selection diagnostic byte bound exceeded'
        path=directory/f'selection-diagnostic-{header["sequence"]:03d}-{records:03d}.json';records+=1
        _atomic_json(path,state)
    def check():
        if clock()>=_finite(state['readerDeadline']):raise _SelectionDiagnosticStop('deadline')
        if (directory/f'request-{header["sequence"]+1:03d}.json').exists():
            state['pendingRequest']=True;raise _SelectionDiagnosticStop('pending-request')
    def guard(side):
        check();state['guard']=dict(side=side,startedAt=clock(),finishedAt=None,native=None,uno=None)
        state['guard']['native']=anchor.snapshot();check()
        state['guard']['uno']=reader.snapshot();check();state['guard']['finishedAt']=clock()
    def call(name,function,project):
        value=None
        try:
            check();assert len(state['calls'])<69,'Selection diagnostic getter bound exceeded'
            guard('before');check()
            row=dict(getter=name,intentAt=clock(),returnedAt=None,result=None,guardAfter=False)
            state['calls'].append(row);state['status']='reading';emit();check()
            value=function();row['returnedAt']=clock();row['result']=project(value)
            guard('after');row['guardAfter']=True;emit();return value
        finally:value=None
    def names(value):
        assert type(value) in (tuple,list) and len(value)<=64,'Invalid bounded interface metadata'
        result=[item.typeName for item in value]
        assert all(type(name) is str and 0<len(name)<=256 for name in result),'Invalid interface name'
        state['interfaceNames']=result;return result
    def text(value):
        assert type(value) is str and len(value)<=256,'Invalid bounded service text'
        return value
    def services(value):
        assert type(value) in (tuple,list) and len(value)<=64,'Invalid bounded service metadata'
        result=[text(item) for item in value];state['services']=result;return result
    def count(value,key):
        state['rawCounts'].append(dict(phase=key,raw=scalar(value)))
        assert type(value) is int and 0<=value<=0x7fffffff,'Invalid exact range count'
        state[key]=value;return value
    def scalar(value):
        result=dict(type=type(value).__name__,value=None)
        if type(value) is str and len(value)>256:result.update(omitted=True,length=len(value))
        elif type(value) is int and value.bit_length()>64:result.update(omitted=True,bitLength=value.bit_length())
        elif type(value) is float and not math.isfinite(value):result.update(omitted=True,nonfinite=True)
        elif type(value) in (int,float,str,bool,type(None)):result['value']=value
        else:result['omitted']=True
        return result
    def proxy(value):
        assert type(value) is reader.proxy_type,'Indexed range proxy type mismatch'
        return dict(type=type(value).__name__,module=type(value).__module__,localId=id(value))
    def address(value,index):
        fields={key:getattr(value,source) for key,source in (
            ('sheet','Sheet'),('startColumn','StartColumn'),('startRow','StartRow'),
            ('endColumn','EndColumn'),('endRow','EndRow'))}
        raw={key:scalar(v) for key,v in fields.items()}
        valid=all(type(v) is int and 0<=v<=(0x7fff if key=='sheet' else 0x7fffffff) for key,v in fields.items())
        state['indexedAddresses'].append(dict(index=index,address=fields if valid else None,raw=raw))
        assert valid,'Invalid exact range address scalar'
        return fields
    try:
        emit();check()
        if selected is None:raise _SelectionDiagnosticStop('no-selection')
        if type(selected) is not reader.proxy_type:raise _SelectionDiagnosticStop('proxy-type-mismatch')
        if capture.get('controller') is not reader.controller:raise _SelectionDiagnosticStop('controller-mismatch')
        call('XTypeProvider.getTypes',lambda:selected.getTypes(),names)
        reported=state['interfaceNames']
        if 'com.sun.star.lang.XServiceInfo' in reported:
            def implementation(value):state['implementation']=text(value);return value
            call('XServiceInfo.getImplementationName',lambda:selected.getImplementationName(),implementation)
            call('XServiceInfo.getSupportedServiceNames',lambda:selected.getSupportedServiceNames(),services)
        if not set(reported)&{'com.sun.star.sheet.XSheetCellRanges','com.sun.star.sheet.XSheetCellRangeContainer'}:
            raise _SelectionDiagnosticStop('unsupported-interfaces')
        call('XIndexAccess.getCount.before',lambda:selected.getCount(),lambda v:count(v,'preCount'))
        if state['preCount']>32:raise _SelectionDiagnosticStop('range-count-bound')
        for index in range(state['preCount']):
            child=None
            try:
                child=call(f'XIndexAccess.getByIndex[{index}]',lambda:selected.getByIndex(index),proxy)
                call(f'XCellRangeAddressable.getRangeAddress[{index}]',lambda:child.getRangeAddress(),lambda v:address(v,index))
            finally:child=None
        call('XIndexAccess.getCount.after',lambda:selected.getCount(),lambda v:count(v,'postCount'))
        if state['preCount']!=state['postCount']:raise _SelectionDiagnosticStop('range-count-changed')
        state['status']='complete'
    except _SelectionDiagnosticStop as exc:state.update(status='partial',reason=str(exc))
    except BaseException as exc:
        state['status']='error';state['errors'].append(dict(type=type(exc).__name__,message=str(exc)[:1024]))
    finally:
        selected=None;capture.clear()
        try:emit()
        except BaseException as exc:
            state['status']='error';state['errors'].append(dict(type=type(exc).__name__,message=str(exc)[:1024]))
    return state


def _worker_native():
    directory=Path(__file__).resolve().parents[1]/'worker'
    sys.path.insert(0,str(directory))
    try:
        spec=importlib.util.spec_from_file_location('_writer_reader_owned_native',directory/'native_windows.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        return module
    finally:sys.path.remove(str(directory))


def _clear_last_error():
    clear=getattr(ctypes,'set_last_error',None)
    if clear:clear(0)


def _last_error():
    get=getattr(ctypes,'get_last_error',None)
    return int(get()) if get else 0


# LastAccessTime is recorded but deliberately excluded from content identity.
CONSOLE_IDENTITY_KEYS=('fileAttributes','creationTime','lastWriteTime','volumeSerialNumber',
    'size','numberOfLinks','fileIndexHigh','fileIndexLow','fileType','finalPath')
MAX_CONSOLE_BYTES=32*1024*1024


def _final_path(value):
    assert isinstance(value,str)
    if value.startswith('\\\\?\\'):value=value[4:]
    return _path(value)


def _console_identity(info):
    assert isinstance(info,dict)
    assert all(type(info.get(k)) is int and info[k]>=0 for k in CONSOLE_IDENTITY_KEYS if k!='finalPath')
    assert type(info.get('lastAccessTime')) is int and info['lastAccessTime']>=0
    assert info['fileType']==1 and not info['fileAttributes']&(0x10|0x400)
    assert 0<info['size']<=MAX_CONSOLE_BYTES and info['numberOfLinks']>=1
    assert info['fileIndexHigh'] or info['fileIndexLow']
    return tuple(_final_path(info[k]) if k=='finalPath' else info[k] for k in CONSOLE_IDENTITY_KEYS)


def _system_console_path(query):
    assert isinstance(query,dict) and query.get('api')=='GetSystemDirectoryW' and query.get('capacity')==32768
    path=query.get('path');assert isinstance(path,str) and '\x00' not in path
    local=PureWindowsPath(path)
    assert re.fullmatch('[A-Za-z]:',local.drive) and local.is_absolute() and '..' not in local.parts, 'System directory must be a simple absolute local drive path'
    assert type(query.get('returnedLength')) is int and query['returnedLength']==len(path.encode('utf-16-le'))//2
    assert 0<query['returnedLength']<query['capacity']
    return str(local/'conhost.exe')


def require_console_host_witness(witness,recheck=None):
    """Portable replay of an actual prelaunch native system-file witness."""
    assert isinstance(witness,dict) and type(witness.get('schemaVersion')) is int and witness['schemaVersion']==1
    expected_path=_system_console_path(witness.get('systemDirectoryQuery'))
    assert _path(witness.get('path'))==_path(expected_path)
    _positive(witness.get('handleValue'))
    assert all(type(witness.get(key)) is int for key in ('desiredAccess','shareMode','openFlags'))
    assert witness.get('desiredAccess')==0x80000000 and witness.get('shareMode')==1 and witness.get('openFlags')==0x200080
    before=witness.get('fileInfoBefore');after=witness.get('fileInfoAfterHash')
    assert _console_identity(before)==_console_identity(after)
    assert _final_path(after['finalPath'])==_path(witness['path'])
    assert type(witness.get('bytesHashed')) is int and witness['bytesHashed']==after['size']
    assert isinstance(witness.get('sha256'),str) and re.fullmatch('[a-f0-9]{64}',witness['sha256'])
    if recheck is not None:assert _console_identity(recheck)==_console_identity(after),'Frozen system console file identity changed'
    return witness


class _FileTime(ctypes.Structure):
    _fields_=[('low',ctypes.c_uint32),('high',ctypes.c_uint32)]


class _FileInformation(ctypes.Structure):
    _fields_=[('attributes',ctypes.c_uint32),('creation',_FileTime),('access',_FileTime),('write',_FileTime),
        ('volume',ctypes.c_uint32),('sizeHigh',ctypes.c_uint32),('sizeLow',ctypes.c_uint32),
        ('links',ctypes.c_uint32),('indexHigh',ctypes.c_uint32),('indexLow',ctypes.c_uint32)]


class _ConsoleFileApi:
    """Typed local OS-file calls only; no process or document mutation."""
    def __init__(self):
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        def bind(name,args,result):
            function=getattr(kernel,name);function.argtypes=args;function.restype=result;return function
        self.directory=bind('GetSystemDirectoryW',[W.LPWSTR,W.UINT],W.UINT)
        self.open_file=bind('CreateFileW',[W.LPCWSTR,W.DWORD,W.DWORD,ctypes.c_void_p,W.DWORD,W.DWORD,W.HANDLE],W.HANDLE)
        self.get_info=bind('GetFileInformationByHandle',[W.HANDLE,ctypes.POINTER(_FileInformation)],W.BOOL)
        self.file_type=bind('GetFileType',[W.HANDLE],W.DWORD)
        self.final_name=bind('GetFinalPathNameByHandleW',[W.HANDLE,W.LPWSTR,W.DWORD,W.DWORD],W.DWORD)
        self.read_file=bind('ReadFile',[W.HANDLE,ctypes.c_void_p,W.DWORD,ctypes.POINTER(W.DWORD),ctypes.c_void_p],W.BOOL)
        self.close_handle=bind('CloseHandle',[W.HANDLE],W.BOOL)

    def system_directory(self):
        buffer=ctypes.create_unicode_buffer(32768);length=int(self.directory(buffer,len(buffer)))
        assert 0<length<len(buffer),'Cannot query the actual Windows system directory'
        return dict(api='GetSystemDirectoryW',capacity=len(buffer),returnedLength=length,path=buffer.value)

    def open(self,path):
        handle=self.open_file(path,0x80000000,1,None,3,0x200080,None)
        if not handle or int(handle)==ctypes.c_void_p(-1).value:raise ctypes.WinError(ctypes.get_last_error())
        return handle

    def info(self,handle):
        data=_FileInformation()
        if not self.get_info(handle,ctypes.byref(data)):raise ctypes.WinError(ctypes.get_last_error())
        buffer=ctypes.create_unicode_buffer(32768);length=int(self.final_name(handle,buffer,len(buffer),0))
        assert 0<length<len(buffer),'Cannot resolve the retained native system file'
        def ticks(value):return (int(value.high)<<32)|int(value.low)
        return dict(fileAttributes=int(data.attributes),creationTime=ticks(data.creation),lastAccessTime=ticks(data.access),lastWriteTime=ticks(data.write),
            volumeSerialNumber=int(data.volume),size=(int(data.sizeHigh)<<32)|int(data.sizeLow),numberOfLinks=int(data.links),
            fileIndexHigh=int(data.indexHigh),fileIndexLow=int(data.indexLow),fileType=int(self.file_type(handle)),finalPath=buffer.value)

    def read(self,handle,count):
        buffer=ctypes.create_string_buffer(count);read=W.DWORD()
        if not self.read_file(handle,buffer,count,ctypes.byref(read),None):raise ctypes.WinError(ctypes.get_last_error())
        assert read.value<=count
        return buffer.raw[:read.value]


class _ProfileDirectoryApi(_ConsoleFileApi):
    def open(self,path):
        # CreateFileW: READ_ATTRIBUTES, share READ|WRITE|DELETE, OPEN_EXISTING,
        # BACKUP_SEMANTICS opens a directory. GetFinalPathNameByHandleW flags0
        # returns its actual normalized DOS path; no alias expansion is guessed.
        # https://learn.microsoft.com/windows/win32/api/fileapi/nf-fileapi-createfilew
        # https://learn.microsoft.com/windows/win32/api/fileapi/nf-fileapi-getfinalpathnamebyhandlew
        handle=self.open_file(path,PROFILE_DIRECTORY_ACCESS,PROFILE_DIRECTORY_SHARE,None,3,PROFILE_DIRECTORY_FLAGS,None)
        if not handle or int(handle)==ctypes.c_void_p(-1).value:raise ctypes.WinError(ctypes.get_last_error())
        return handle


class _NativeProfileDirectory:
    """Retain the native directory behind the exact original profile URI."""
    def __init__(self,profile_url,deadline,clock=time.monotonic,api=None):
        self.handle=None;self.api=api or _ProfileDirectoryApi();self.deadline=_finite(deadline);self.clock=clock
        self.profile_url=profile_url
        try:
            self._remaining();path=_profile_decoded_path(profile_url)
            self.handle=self.api.open(path);info=self.api.info(self.handle);self._remaining()
            self.witness=dict(schemaVersion=1,kind='native-owned-profile-directory',profileUrl=profile_url,
                decodedPath=path,canonicalPath=_profile_canonical_path(info['finalPath']),handleValue=int(self.handle),
                desiredAccess=PROFILE_DIRECTORY_ACCESS,shareMode=PROFILE_DIRECTORY_SHARE,openFlags=PROFILE_DIRECTORY_FLAGS,openedInfo=info)
            require_profile_directory_witness(self.witness,profile_url)
        except BaseException as exc:
            exc.profile_directory_diagnostic=dict(profileUrl=profile_url,handleValue=int(self.handle or 0),openedInfo=locals().get('info'))
            if self.handle:
                try:exc.profile_directory_closure=self.close()
                except BaseException as later:exc.add_note('Profile DIRECTORY HANDLE cleanup failed: '+str(later))
            raise

    def _remaining(self):
        if self.clock()>=self.deadline:raise TimeoutError('Native profile witness exhausted original reader budget')

    def snapshot(self):
        self._remaining();assert self.handle, 'Profile DIRECTORY HANDLE was released'
        current=self.api.info(self.handle);self._remaining()
        require_profile_directory_witness(self.witness,self.profile_url,current)
        return dict(witness=self.witness,recheck=current)

    def close(self):
        handle=self.handle;assert handle, 'Profile DIRECTORY HANDLE was already closed'
        _clear_last_error()
        try:result=bool(self.api.close_handle(handle));error=_last_error()
        finally:self.handle=None
        return dict(kind='profile-directory',handleValue=int(handle),result=result,lastError=error)


class _SystemConsoleHost:
    """One readonly native file HANDLE and one finite prelaunch SHA, not per-read IO."""
    def __init__(self,deadline,clock,api=None):
        import hashlib
        self.api=api or _ConsoleFileApi();self.handle=None;self.clock=clock;self.deadline=deadline
        def remaining():
            if self.clock()>=deadline:raise TimeoutError('System console witness exhausted original reader budget')
        try:
            remaining();query=self.api.system_directory();path=_system_console_path(query)
            self.handle=self.api.open(path);before=self.api.info(self.handle);_console_identity(before)
            digest=hashlib.sha256();count=0
            while True:
                remaining();block=self.api.read(self.handle,min(1024*1024,MAX_CONSOLE_BYTES+1-count))
                if not block:break
                count+=len(block);assert count<=MAX_CONSOLE_BYTES;digest.update(block)
            after=self.api.info(self.handle);remaining()
            self.witness=dict(schemaVersion=1,systemDirectoryQuery=query,path=path,handleValue=int(self.handle),desiredAccess=0x80000000,
                shareMode=1,openFlags=0x200080,fileInfoBefore=before,fileInfoAfterHash=after,bytesHashed=count,sha256=digest.hexdigest())
            require_console_host_witness(self.witness)
        except BaseException as exc:
            exc.system_console_diagnostic=dict(handleValue=int(self.handle or 0),fileInfoBefore=locals().get('before'),fileInfoAfterHash=locals().get('after'))
            if self.handle:
                try:exc.system_console_closure=self.close()
                except BaseException as later:exc.add_note('Native system-file HANDLE cleanup failed: '+str(later))
            raise

    def recheck(self):
        assert self.handle,'System console file HANDLE is no longer retained'
        current=self.api.info(self.handle);require_console_host_witness(self.witness,current);return current

    def close(self):
        handle=self.handle;_clear_last_error();result=bool(self.api.close_handle(handle));error=_last_error();self.handle=None
        return dict(kind='system-console-file',handleValue=int(handle),result=result,lastError=error)


def _job_member(row,binding,suite_root,alive,console,*,exiting=False):
    if _path(row.get('image'))==_path(console['path']):
        assert row.get('inOwnedJob') is True and row.get('isInJobApiSucceeded') is True
        for key in ('pid','creationTime','handleValue','jobHandleValue'):_positive(row.get(key))
        assert row['pid'] not in (binding['shellPid'],binding['officePid'])
        assert type(row.get('waitResult')) is int and row['waitResult']==(258 if alive else 0)
        assert type(row.get('exitCode')) is int and row['exitCode']==(0 if exiting else 259 if alive else 0)
        assert not exiting or alive
        return 'owned-console-host'
    _reader_member(row,binding,suite_root,alive,exiting=exiting);return 'packaged-python'



def _launch_owned(native,argv,cwd):
    """Observe constructor APIs without changing the shared product implementation."""
    original_bind=native.bind;receipt={'steps':[],'firstFailure':None};active=True
    watched={'CreateJobObjectW','CreateProcessW','AssignProcessToJobObject','ResumeThread','CloseHandle'}
    def observed_bind(dll,name,args,result):
        function=original_bind(dll,name,args,result)
        if name not in watched:return function
        def observed(*values):
            _clear_last_error()
            value=function(*values);last_error=_last_error()
            if active:
                row={'api':name,'lastError':last_error}
                if name=='CreateJobObjectW':row['handleValue']=int(value or 0)
                elif name=='CreateProcessW':
                    info=values[-1]._obj
                    row.update(result=bool(value),creationFlags=int(values[5]),application=str(values[0]),command=values[1].value,inheritHandles=bool(values[4]),
                        pid=int(info.dwProcessId),threadId=int(info.dwThreadId),
                        processHandleValue=int(info.hProcess or 0),threadHandleValue=int(info.hThread or 0))
                elif name=='AssignProcessToJobObject':row.update(result=bool(value),jobHandleValue=int(values[0]),processHandleValue=int(values[1]))
                elif name=='ResumeThread':row.update(previousSuspendCount=int(value),threadHandleValue=int(values[0]))
                else:row.update(result=bool(value),handleValue=int(values[0]))
                receipt['steps'].append(row)
                failed=(value==0xffffffff) if name=='ResumeThread' else not bool(value)
                if failed and receipt['firstFailure'] is None:receipt['firstFailure']=dict(row)
            return value
        return observed
    native.bind=observed_bind
    try:return native.OwnedOfficeProcess(argv,cwd),receipt
    except BaseException as exc:exc.helper_launch=receipt;raise
    finally:active=False;native.bind=original_bind


class _NativeAnchor:
    """Read-only handles retained once; PID recycling cannot replace them."""
    def __init__(self,config):
        from startup_smoke import EngineProcessWitness
        from windows_smoke import Windows
        self.config=config;self.processes={};self.profile=None;self.api=Windows();self.native=_worker_native();self.diagnostics=self.native.ProcessDiagnosticsApi()
        self.get_parent=self.native.bind(self.api.user,'GetParent',[W.HWND],W.HWND)
        try:
            expected_shell_creation=_positive(config['expected_shell_creation'])
            shell=EngineProcessWitness(config['shell_pid']);self.processes['shell']=shell
            identity=self.diagnostics.identity(shell.handle)
            shell_raw=dict(identity,pid=config['shell_pid'],handleValue=int(shell.handle),
                waitResult=int(self.diagnostics.wait_for(shell.handle,0)),exitCode=shell.code())
            self.last_snapshot={'shell':shell_raw}
            assert identity['creationTime']==shell.creation_time==expected_shell_creation, 'Original Popen shell generation changed before Office/UNO capture'
            assert _path(identity['image'])==_path(_join(config['suite'],'OpenGeul.Office.exe')) and shell_raw['waitResult']==258 and shell_raw['exitCode']==259
            self.processes['office']=EngineProcessWitness(config['office_pid'])
            first=self.snapshot()
            self.base=dict(shellPid=config['shell_pid'],shellCreationTime=first['shell']['creationTime'],
                officePid=config['office_pid'],officeCreationTime=first['office']['creationTime'],
                expectedImage=str(Path(config['suite'])/'Office/program/soffice.bin'),suiteHwnd=config['suite_hwnd'],
                parentHwnd=config['parent_hwnd'],childHwnd=config['child_hwnd'],rootHwnd=config['suite_hwnd'],privatePipe=first['privatePipe'])
            _require_native(first,self.base,str(config['suite']))
            if 'expected_native_binding' in config:
                assert self.base==config['expected_native_binding'], 'Helper opened a different native generation before UNO resolution'
                assert first['officeCommandLine']==config['expected_office_command_line'], 'Helper observed a changed private transport/profile before UNO resolution'
        except BaseException as exc:
            exc.native_snapshot=getattr(self,'last_snapshot',None)
            try:
                exc.native_handle_closures=self.close()
                if not all(row['result'] for row in exc.native_handle_closures):exc.add_note('Read-only native HANDLE CloseHandle returned false')
            except BaseException as cleanup_error:exc.add_note('Read-only native handle cleanup failed: '+str(cleanup_error))
            raise

    def snapshot(self):
        from native_accessibility import _command_line
        raw={};self.last_snapshot=raw
        for name,process in self.processes.items():
            identity=self.diagnostics.identity(process.handle)
            waited=int(self.diagnostics.wait_for(process.handle,0))
            if waited not in (0,258):raise ctypes.WinError(ctypes.get_last_error())
            raw[name]=dict(identity,pid=self.config[name+'_pid'],handleValue=int(process.handle),waitResult=waited,exitCode=process.code())
        windows={}
        for name in ('suite','parent','child'):
            hwnd=self.config[name+'_hwnd']
            windows[name]=dict(hwnd=hwnd,isWindow=bool(self.api.user.IsWindow(hwnd)),pid=self.api.pid(hwnd),
                parentHwnd=int(self.get_parent(hwnd) or 0),rootHwnd=int(self.api.user.GetAncestor(hwnd,2) or 0))
        windows.update(exportedParentHwnd=int(self.api.user.GetPropW(self.config['suite_hwnd'],'OpenGeul.Office.ParentHwnd') or 0),
            exportedChildHwnd=int(self.api.user.GetPropW(self.config['suite_hwnd'],'OpenGeul.Office.ChildHwnd') or 0))
        raw.update(windows=windows,officeCommandLine=_command_line(self.processes['office']))
        raw['privatePipe']=_pipe(raw['officeCommandLine']);raw['profileUrl']=_profile(raw['officeCommandLine'])
        if self.profile is None:self.profile=_NativeProfileDirectory(raw['profileUrl'],self.config['readerDeadline'])
        assert self.profile.profile_url==raw['profileUrl'], 'Original profile URI changed before native recheck'
        raw['profileDirectory']=self.profile.snapshot()
        if hasattr(self,'base'):_require_native(raw,self.base,str(self.config['suite']))
        return raw

    def close(self):
        result=[]
        if self.profile and self.profile.handle:
            handle=int(self.profile.handle)
            try:result.append(self.profile.close())
            except BaseException as exc:result.append(dict(kind='profile-directory',handleValue=handle,result=False,error=str(exc)))
        for name,process in self.processes.items():
            if process.handle:
                handle=int(process.handle);ok=bool(process.close_handle(process.handle));process.handle=None
                result.append(dict(kind=name,handleValue=handle,result=ok))
        return result


def _native_anchor(config):return _NativeAnchor(config)


class _UnoReader:
    """Hold actual PyUNO proxies; display repr is not an identity contract.

    Pinned pyuno.cxx PyUNOType.tp_name is 'pyuno'; PyUNO_cmp compares the
    wrapped UNO Any. Python id() identifies only our held local wrapper, scoped
    by the actual reader generation. Native UNO equality remains authoritative.
    """
    def __init__(self,config,anchor,*,contract=_WRITER_CONTRACT):
        self.config=config;self.contract=contract;self.diagnostic={'proxyTypes':{},'frameEnumeration':[]}
        self.model=self.controller=self.frame=self.desktop=self.context=self.local_context=None
        self.retained={};self.pending_input=None;self.edit_context=None;self.calc_selection_capture=None
        try:
            import uno
            self.local_context=uno.getComponentContext();self.proxy_type=type(self.local_context)
            assert self.proxy_type.__name__=='pyuno','Local component context is not the pinned PyUNO extension type'
            resolver=self.local_context.ServiceManager.createInstanceWithContext('com.sun.star.bridge.UnoUrlResolver',self.local_context)
            self.context=resolver.resolve('uno:pipe,name='+anchor.base['privatePipe']+';urp;StarOffice.ComponentContext')
            self._type(self.context,'resolvedContext')
            self.desktop=self.context.ServiceManager.createInstanceWithContext('com.sun.star.frame.Desktop',self.context)
            self._type(self.desktop,'desktop')
            self.frame,self.controller,self.model=self._current()
            self.retained={k:'pyuno-proxy:0x'+format(id(getattr(self,k)),'x') for k in ('frame','controller','model')}
            self.snapshot()
        except BaseException as exc:
            exc.uno_diagnostic=dict(self.diagnostic)
            exc.uno_snapshot=getattr(self,'last_snapshot',None)
            exc.frame_enumeration=getattr(self,'last_frames',[])
            self.release();exc.observer_proxies_released=True
            raise

    def _type(self,obj,role):
        kind=type(obj)
        row=dict(typeName=kind.__name__,typeModule=kind.__module__,typeId=id(kind),proxyId=id(obj),sameAsLocalType=kind is self.proxy_type)
        self.diagnostic['proxyTypes'][role]=row
        assert kind is self.proxy_type,'Original '+role+' is not the actual local PyUNO extension type'
        return row

    def _enumerate(self):
        frames=self.desktop.getFrames();count=frames.getCount()
        assert type(count) is int and 1<=count<=8,'Original engine frame count exceeded bound'
        rows=[];matches=[];self.last_frames=rows;self.diagnostic['frameEnumeration']=rows
        for index in range(count):
            frame=frames.getByIndex(index);self._type(frame,'enumeratedFrame')
            peer=frame.getContainerWindow();hwnd=int(peer.getWindowHandle((),1)) if peer is not None else 0
            rows.append(dict(index=index,containerHwnd=hwnd))
            if hwnd==self.config['child_hwnd']:matches.append((index,frame))
        assert len(matches)==1,'Original frame is missing or ambiguous'
        return rows,matches[0]

    def _current(self):
        _,(_,frame)=self._enumerate();self._type(frame,'frame')
        controller=frame.getController();self._type(controller,'controller')
        model=controller.getModel();self._type(model,'model')
        return frame,controller,model

    def snapshot(self):
        rows,(index,frame)=self._enumerate();self._type(frame,'currentFrame')
        controller=frame.getController();self._type(controller,'currentController')
        model=controller.getModel();self._type(model,'currentModel')
        raw=dict(frameCount=len(rows),frames=rows,matchedFrameIndex=index,retained=dict(self.retained),
            proxyIdentity=dict(helperPid=os.getpid(),localContextId=id(self.local_context),proxyTypeId=id(self.proxy_type),
                proxyTypeName=self.proxy_type.__name__,proxyTypeModule=self.proxy_type.__module__,
                retainedIds={k:id(getattr(self,k)) for k in ('frame','controller','model')},
                typeMatches={k:type(getattr(self,k)) is self.proxy_type for k in ('frame','controller','model')}),
            equalities=dict(frame=frame==self.frame,controller=controller==self.controller,model=model==self.model,
                controllerFrame=self.controller.getFrame()==self.frame,modelController=self.model.getCurrentController()==self.controller),
            documentUrl=self.model.getURL(),modelService=self.contract.service if self.model.supportsService(self.contract.service) else '')
        self.last_snapshot=raw
        expected=dict(childHwnd=self.config['child_hwnd'],documentUrl=self.config['expected_url'],**{k+'Identity':v for k,v in self.retained.items()})
        _require_uno(raw,expected,contract=self.contract)
        return raw

    def read(self,*,request_action=None,request_sequence=None):
        self.calc_selection_capture={}
        phase=_calc_pending_program_phase(request_action,request_sequence) if self.contract==_CALC_PENDING_INITIAL_CONTRACT else None
        before=self.snapshot()
        if self.contract in _EDIT_MODULES:
            from ime_semantic_context import EditingContextReader
            module=_EDIT_MODULES[self.contract]
            if self.edit_context is None:
                self.edit_context=EditingContextReader(module,self.frame,self.controller,self.model,
                    self.config['child_hwnd'],deadline=self.config['readerDeadline'])
            editing=self.edit_context.read()
            value=dict(editContext=editing,isModified=self.model.isModified())
            assert type(value['isModified']) is bool
            if module=='writer':value['bodyText']=editing['textAfter']
            if module=='calc':
                sheet=self.model.getSheets().getByIndex(0)
                value.update(sheetIndex=0,a1Text=sheet.getCellRangeByName('A1').getString(),
                    b1Value=sheet.getCellRangeByName('B1').getValue(),c1Value=sheet.getCellRangeByName('C1').getValue(),
                    d1Formula=sheet.getCellRangeByName('D1').getFormula(),d1Value=sheet.getCellRangeByName('D1').getValue(),
                    calcSelection=read_calc_selection(self.controller,deadline=self.config['readerDeadline'],
                        proxy_type=self.proxy_type,capture=self.calc_selection_capture))
                _require_calc_values(value)
            after=self.snapshot()
        elif self.contract in (_CALC_CONTRACT,_CALC_PENDING_CONTRACT,_CALC_PENDING_INITIAL_CONTRACT):
            sheet=self.model.getSheets().getByIndex(0)
            pending={}
            if self.contract in (_CALC_PENDING_CONTRACT,_CALC_PENDING_INITIAL_CONTRACT):
                from calc_pending_input import AccessiblePendingReader
                if self.pending_input is None:
                    self.pending_input=AccessiblePendingReader(self.frame,self.config['child_hwnd'],
                        deadline=self.config['readerDeadline'])
                if phase is not None and phase['phase']=='initial':
                    selection=read_calc_initial_selection(self.controller,deadline=self.config['readerDeadline'],
                        proxy_type=self.proxy_type,capture=self.calc_selection_capture)
                    pending=dict(calcInitialSelection=selection)
                else:
                    pending=dict(calcSelection=read_calc_selection(self.controller,deadline=self.config['readerDeadline'],
                        proxy_type=self.proxy_type,capture=self.calc_selection_capture))
                pending['pendingInput']=self.pending_input.read()
                if phase is not None:pending['calcSelectionPhase']=phase
            value=dict(sheetIndex=0,a1Text=sheet.getCellRangeByName('A1').getString(),
                b1Value=sheet.getCellRangeByName('B1').getValue(),c1Value=sheet.getCellRangeByName('C1').getValue(),
                d1Formula=sheet.getCellRangeByName('D1').getFormula(),d1Value=sheet.getCellRangeByName('D1').getValue(),
                isModified=self.model.isModified(),**pending)
            after=self.snapshot()
            _require_calc_values(value)
        else:
            body=self.model.getText().getString();modified=self.model.isModified();after=self.snapshot()
            assert isinstance(body,str) and len(body.encode('utf-8'))<=MAX_BODY_BYTES,'Writer body exceeded getter bound'
            assert type(modified) is bool
            value=dict(bodyText=body,isModified=modified)
        value['unoSnapshots']=dict(before=before,after=after)
        return value

    def release(self):
        # Client references only. The live document is never closed/disposed.
        if getattr(self,'calc_selection_capture',None) is not None:self.calc_selection_capture.clear()
        if getattr(self,'edit_context',None) is not None:self.edit_context.release();self.edit_context=None
        if self.pending_input is not None:self.pending_input.release();self.pending_input=None
        self.model=self.controller=self.frame=self.desktop=self.context=self.local_context=None


class OwnedWriterReader:
    _contract=_WRITER_CONTRACT
    _helper_flag='--helper'

    def __init__(self,suite,output,*,shell_pid,expected_shell_creation,suite_hwnd,parent_hwnd,child_hwnd,office_pid,expected_url,clock=time.monotonic):
        self.config=dict(suite=str(suite),shell_pid=shell_pid,expected_shell_creation=expected_shell_creation,suite_hwnd=suite_hwnd,parent_hwnd=parent_hwnd,
            child_hwnd=child_hwnd,office_pid=office_pid,expected_url=expected_url)
        self.suite=Path(suite);self.output=Path(output);self.clock=clock;self.binding=None
        self.deadline=None;self.anchor=None;self.process=None;self.diagnostics=None;self.members={}
        self.member_state_samples=[]
        self.job_census_anomalies=[];self.last_job_census=None;self.job_census_sequence=0
        self.sequence=0;self.closed=False;self.failed=False;self.last_observation=None;self.first_error=None;self.forced=False;self.auxiliary_errors=[];self.attempted_observation=None;self.helper_launch=None;self.console=None

    def _remaining(self,deadline):
        _finite(deadline)
        if self.deadline is None:self.deadline=deadline
        assert deadline==self.deadline,'Reader absolute deadline cannot be reset'
        remaining=deadline-self.clock()
        if remaining<=0:raise TimeoutError('Original Writer reader absolute deadline expired')
        return remaining

    def _census_receipt(self):
        return dict(jobCensusAnomalies=list(self.job_census_anomalies),lastJobCensus=self.last_job_census)

    def _job_pids(self,*,phase):
        assert self.job_census_sequence<MAX_JOB_CENSUS_GROUPS, 'Reader job census group bound exceeded'
        sequence=self.job_census_sequence;self.job_census_sequence+=1
        def record(group):
            value=dict(group,sequence=sequence,phase=phase)
            if group['classification']=='complete':self.last_job_census=value
            if len(group['calls'])>1 or group['classification']!='complete':
                assert len(self.job_census_anomalies)<MAX_JOB_CENSUS_ANOMALIES, 'Reader job census anomaly bound exceeded'
                self.job_census_anomalies.append(value)
        return self.diagnostics.job_pids(self.process.job,record=record,check=lambda:self._remaining(self.deadline))

    def _member_snapshots(self,*,releasing=False):
        for pid in self._job_pids(phase='release-members' if releasing else 'read-members'):
            assert pid not in (self.config['shell_pid'],self.config['office_pid']), 'Editor unexpectedly belongs to observation job'
            if pid not in self.members:
                handle=self.diagnostics.open_owned(pid,self.process.job)
                try:self.members[pid]=(handle,self.diagnostics.identity(handle))
                except BaseException:
                    try:
                        closed=bool(self.diagnostics.close_handle(handle))
                        self.auxiliary_errors.append(dict(stage='failed-member-identity-handle-close',handleValue=int(handle),result=closed))
                    except BaseException as later:self.auxiliary_errors.append(dict(stage='failed-member-identity-handle-close',handleValue=int(handle),type=type(later).__name__,message=str(later)))
                    raise
        rows=[]
        for pid,(handle,identity) in self.members.items():
            assert len(self.member_state_samples)<MAX_MEMBER_STATE_SAMPLES, 'Reader member sample bound exceeded'
            row=dict(identity,pid=pid,handleValue=int(handle),jobHandleValue=int(self.process.job),
                sampleIndex=len(self.member_state_samples),phase='release' if releasing else 'read',sampleStartedAt=self.clock(),stateCalls=[])
            self.member_state_samples.append(row)  # Retain partial API failures before any assertion.
            try:
                member=W.BOOL();_clear_last_error()
                succeeded=bool(self.diagnostics.is_in_job(handle,self.process.job,ctypes.byref(member)));error=_last_error()
                row.update(inOwnedJob=bool(member.value),isInJobApiSucceeded=succeeded)
                row['membershipCall']=dict(api='IsProcessInJob',handleValue=int(handle),jobHandleValue=int(self.process.job),result=succeeded,inOwnedJob=bool(member.value),lastError=error,observedAt=self.clock())
                if not succeeded:raise ctypes.WinError(error)
                assert member.value,'Retained helper left its private job'
                _clear_last_error();waited=int(self.diagnostics.wait_for(handle,0));error=_last_error()
                row['stateCalls'].append(dict(api='WaitForSingleObject',handleValue=int(handle),timeoutMilliseconds=0,result=waited,lastError=error,observedAt=self.clock()))
                row['waitResult']=waited
                if waited not in (0,258):raise ctypes.WinError(error)
                code=W.DWORD();_clear_last_error()
                succeeded=bool(self.diagnostics.get_exit(handle,ctypes.byref(code)));error=_last_error()
                row['stateCalls'].append(dict(api='GetExitCodeProcess',handleValue=int(handle),result=succeeded,exitCode=int(code.value) if succeeded else None,lastError=error,observedAt=self.clock()))
                row['exitCode']=int(code.value) if succeeded else None
                if not succeeded:raise ctypes.WinError(error)
            finally:row['sampleFinishedAt']=self.clock()
            rows.append(row)
        if self.console:
            roles=[_job_member(row,self.anchor.base,str(self.suite),row['waitResult']==258,self.console.witness,
                exiting=releasing and (row['waitResult'],row['exitCode'])==(258,0)) for row in rows]
            assert roles.count('owned-console-host')<=1,'Multiple ancillary console hosts are not accepted'
        return rows

    def _rpc(self,action,deadline):
        self._remaining(deadline)
        sequence=self.sequence;self.sequence+=1
        request=dict(sequence=sequence,action=action)
        _atomic_json(self.output/f'request-{sequence:03d}.json',request)
        path=self.output/f'reply-{sequence:03d}.json'
        while True:
            remaining=self._remaining(deadline)
            self._member_snapshots(releasing=action=='release')
            if path.exists():return _require_reply(_read_json(path),sequence,action)
            if self.process.poll() is not None:
                if action=='release' and path.exists():return _require_reply(_read_json(path),sequence,action)
                raise AssertionError('Owned reader exited before its reply')
            time.sleep(min(.01,remaining))

    def start(self,deadline):
        self._remaining(deadline)
        assert not self.closed and not self.failed and self.process is None,'Reader cannot restart'
        try:
            self.output.mkdir(parents=True,exist_ok=False)
            self.config['readerDeadline']=deadline
            self.anchor=_native_anchor(self.config)
            self._remaining(deadline)
            helper_config=dict(self.config,expected_native_binding=dict(self.anchor.base),expected_office_command_line=self.anchor.snapshot()['officeCommandLine'])
            _atomic_json(self.output/'configuration.json',helper_config)
            self.console=_SystemConsoleHost(deadline,self.clock)
            native=_worker_native();self.diagnostics=native.ProcessDiagnosticsApi()
            argv=[str(self.suite/'Office/program/python.exe'),str(Path(__file__).resolve()),self._helper_flag,str(self.output)]
            self.process,self.helper_launch=_launch_owned(native,argv,self.suite/'Office/program')
            _require_launch(self.helper_launch,int(self.process.job))
            self._remaining(deadline)
            return self._read(deadline,'start')
        except BaseException as exc:
            self._record_failure(exc);raise

    def _record_failure(self,exc):
        self.failed=True
        if self.first_error is None:
            self.first_error=dict(type=type(exc).__name__,message=str(exc),winerror=getattr(exc,'winerror',None),traceback=traceback.format_exc(),
                attemptedObservation=self.attempted_observation,nativeSnapshot=getattr(self.anchor,'last_snapshot',getattr(exc,'native_snapshot',None)),
                **_member_samples_receipt(self.member_state_samples),
                **self._census_receipt(),jobCensusError=getattr(exc,'job_census',None),
                nativeHandleClosures=getattr(exc,'native_handle_closures',None),profileDirectoryDiagnostic=getattr(exc,'profile_directory_diagnostic',None),profileDirectoryClosure=getattr(exc,'profile_directory_closure',None),systemConsoleDiagnostic=getattr(exc,'system_console_diagnostic',None),
                systemConsoleClosure=getattr(exc,'system_console_closure',None),helperLaunch=self.helper_launch or getattr(exc,'helper_launch',None))
            try:
                if self.output.exists():_atomic_json(self.output/'failure.json',self.first_error)
            except BaseException as later:self.auxiliary_errors.append(dict(stage='retain-primary-error',type=type(later).__name__,message=str(later)))
        if isinstance(exc,TimeoutError) and self.process is not None and not self.forced:
            try:self.process.terminate();self.forced=True
            except BaseException as later:self.auxiliary_errors.append(dict(stage='terminate-owned-helper-job',type=type(later).__name__,message=str(later)))

    def _read(self,deadline,action):
        issued_sequence=self.sequence
        started=self.clock();before=self.anchor.snapshot();reply=self._rpc(action,deadline)
        from writer_style_smoke import require_packaged_python
        result=reply['observation'];self.attempted_observation=result
        if self._contract==_CALC_PENDING_INITIAL_CONTRACT:
            assert type(reply.get('sequence')) is int and reply['sequence']==issued_sequence and reply.get('action')==action, 'Calc program RPC envelope differs'
            require_calc_pending_program_phase(result,expected_action=action,expected_sequence=issued_sequence)
        identity=require_packaged_python(self.suite,result['pythonIdentity']['observed'])
        assert identity==result['pythonIdentity'],'Helper Python identity changed between actual file checks'
        member=[r for r in self._member_snapshots() if r['pid']==reply.get('readerPid')]
        assert len(member)==1,'Actual reader PID was not retained in the private job'
        assert _path(member[0]['image'])==_path(identity['observed']['processImage'])
        result.update(readerProcess=member[0],readStartedAt=started,helperLaunch=self.helper_launch,
            systemConsoleHost=self.console.witness,systemConsoleHostRecheck=self.console.recheck())
        result['nativeSnapshots'].update(controllerBefore=before,controllerAfter=self.anchor.snapshot())
        result['readFinishedAt']=self.clock()
        derived=dict(self.anchor.base,**{k+'Identity':v for k,v in result['unoSnapshots']['before']['retained'].items()},documentUrl=self.config['expected_url'])
        if self.binding is None:self.binding=derived
        assert derived==self.binding,'Original Writer binding changed'
        result.update(bindingBefore=dict(self.binding),bindingAfter=dict(self.binding))
        _require_owned_observation(result,self.binding,str(self.suite),self._contract);self._remaining(deadline)
        _atomic_json(self.output/f'observation-{self.sequence-1:03d}.json',result)
        self._remaining(deadline)
        self.last_observation=result
        return result

    def read(self,deadline):
        try:
            self._remaining(deadline)
            assert self.process is not None and not self.closed and not self.failed,'Reader context is not retained'
            assert self.sequence<=120, 'Reader exceeded its finite request count'
            return self._read(deadline,'read')
        except BaseException as exc:self._record_failure(exc);raise

    def close(self,deadline):
        assert deadline==self.deadline and not self.closed,'Reader cleanup must use original deadline once'
        cleanup=dict(kind=self._contract.cleanup_kind,binding=self.binding,cleanupSucceeded=False,startedAt=self.clock(),deadline=deadline,
            terminated=self.forced,helperLaunch=self.helper_launch,releaseAcknowledgement=None,readerMembers=[],finalJobPids=None,jobHandleValue=int(self.process.job) if self.process else 0,
            nativeBefore=None,nativeAfter=None,systemConsoleHost=self.console.witness if self.console else None,systemConsoleHostRecheck=None,handleClosures=[],errors=list(self.auxiliary_errors))
        def error(exc):cleanup['errors'].append(dict(type=type(exc).__name__,message=str(exc),winerror=getattr(exc,'winerror',None),jobCensus=getattr(exc,'job_census',None)))
        try:
            self._remaining(deadline)
            assert not self.forced, 'Reader job required forced cleanup'
            if self.anchor:cleanup['nativeBefore']=self.anchor.snapshot()
            if self.process:
                ack=self._rpc('release',deadline);cleanup['releaseAcknowledgement']=dict(action='release',readerPid=ack['readerPid'],proxiesReleased=ack['proxiesReleased'],profileDirectory=ack.get('profileDirectory'),observerHandleClosures=ack.get('observerHandleClosures'))
                while True:
                    remaining=self._remaining(deadline)
                    rows=self._member_snapshots(releasing=True);pids=self._job_pids(phase='release-final')
                    if rows and not pids and all(r['waitResult']==0 for r in rows):
                        cleanup.update(readerMembers=rows,finalJobPids=pids);break
                    time.sleep(min(.01,remaining))
            if self.anchor:cleanup['nativeAfter']=self.anchor.snapshot()
            if self.console:cleanup['systemConsoleHostRecheck']=self.console.recheck()
        except BaseException as exc:
            error(exc)
            if self.process:
                try:
                    # Only this private helper job is terminated. Never the engine.
                    if not self.forced:self.process.terminate();self.forced=True
                    cleanup['terminated']=self.forced
                    cleanup['readerMembers']=self._member_snapshots(releasing=True);cleanup['finalJobPids']=self._job_pids(phase='forced-final')
                except BaseException as later:error(later)
        finally:
            for pid,(handle,identity) in self.members.items():
                try:cleanup['handleClosures'].append(dict(kind='member',handleValue=int(handle),result=bool(self.diagnostics.close_handle(handle))))
                except BaseException as exc:error(exc)
            self.members.clear()
            if self.process:
                original=self.process.close_handle
                process_handle=int(self.process.handle);job_handle=int(self.process.job)
                def close_recorded(handle):
                    result=original(handle);cleanup['handleClosures'].append(dict(kind='process' if int(handle)==process_handle else 'job',handleValue=int(handle),result=bool(result)));return result
                self.process.close_handle=close_recorded
                try:self.process.close()
                except BaseException as exc:error(exc)
            if self.anchor:
                try:cleanup['handleClosures']+=self.anchor.close()
                except BaseException as exc:error(exc)
            if self.console:
                try:cleanup['handleClosures'].append(self.console.close())
                except BaseException as exc:error(exc)
            self.closed=True
            cleanup.update(_member_samples_receipt(self.member_state_samples))
            cleanup.update(self._census_receipt())
            cleanup['finishedAt']=self.clock()
            cleanup['cleanupSucceeded']=not cleanup['errors'] and not cleanup['terminated'] and cleanup['finishedAt']<=deadline
            if cleanup['cleanupSucceeded']:
                try:_require_physical_cleanup(cleanup,self.anchor.base,deadline,contract=self._contract)
                except BaseException as exc:error(exc);cleanup['cleanupSucceeded']=False
            cleanup['physicalCleanupSucceeded']=cleanup['cleanupSucceeded']
            cleanup['contextQualified']=self.binding is not None and not self.failed and self.first_error is None
            cleanup['cleanupSucceeded']=cleanup['cleanupSucceeded'] and cleanup['contextQualified']
            if self.output.exists():
                try:_atomic_json(self.output/'cleanup.json',cleanup)
                except BaseException as exc:error(exc);cleanup['cleanupSucceeded']=False
        return cleanup


class OwnedModelReader(OwnedWriterReader):
    """Additive explicit API; no auto-detection, dynamic getters, or writer fallback."""
    _helper_flag='--model-helper'

    def __init__(self,suite,output,*,expected_service,getter_contract,shell_pid,expected_shell_creation,
                 suite_hwnd,parent_hwnd,child_hwnd,office_pid,expected_url,clock=time.monotonic):
        self._contract=_model_contract(expected_service,getter_contract)
        super().__init__(suite,output,shell_pid=shell_pid,expected_shell_creation=expected_shell_creation,
            suite_hwnd=suite_hwnd,parent_hwnd=parent_hwnd,child_hwnd=child_hwnd,office_pid=office_pid,
            expected_url=expected_url,clock=clock)
        self.config.update(expected_service=expected_service,getter_contract=getter_contract)

    def start(self,deadline):
        assert _model_contract(self.config['expected_service'],self.config['getter_contract'])==self._contract, 'Explicit model contract changed before startup'
        return super().start(deadline)


def _qpc():
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    counter,frequency=ctypes.c_longlong(),ctypes.c_longlong()
    query=kernel.QueryPerformanceCounter;query.argtypes=[ctypes.POINTER(ctypes.c_longlong)];query.restype=W.BOOL
    freq=kernel.QueryPerformanceFrequency;freq.argtypes=[ctypes.POINTER(ctypes.c_longlong)];freq.restype=W.BOOL
    if not query(ctypes.byref(counter)) or not freq(ctypes.byref(frequency)):raise ctypes.WinError(ctypes.get_last_error())
    assert counter.value>=0 and frequency.value>0
    return int(counter.value),int(frequency.value)


def _helper(directory,*,explicit_model=False):
    directory=Path(directory);config=_read_json(directory/'configuration.json')
    contract=_model_contract(config['expected_service'],config['getter_contract']) if explicit_model else _WRITER_CONTRACT
    anchor=reader=None;sequence=0;failed=False;identity=None
    try:
        while sequence<123:
            path=directory/f'request-{sequence:03d}.json'
            if not path.exists():time.sleep(.005);continue
            request=_read_json(path);action=request.get('action')
            reply=dict(sequence=sequence,action=action,readerPid=os.getpid(),ok=False);observation=None;diagnostic=None;selection_capture=None
            try:
                assert request.get('sequence')==sequence and action in ('start','read','release')
                if contract==_CALC_PENDING_INITIAL_CONTRACT:
                    assert type(request.get('sequence')) is int, 'Calc program RPC sequence must be an exact integer'
                if action=='release':
                    if reader:reader.release();reader=None
                    profile=anchor.profile.snapshot() if anchor and anchor.profile else None
                    closures=anchor.close() if anchor else []
                    assert all(c['result'] is True for c in closures), 'Helper native observer HANDLE cleanup failed'
                    anchor=None
                    reply.update(ok=True,proxiesReleased=True,profileDirectory=profile,observerHandleClosures=closures)
                else:
                    assert not failed,'Failed reader cannot resume'
                    if action=='start':
                        assert reader is None and sequence==0
                        from writer_style_smoke import observe_packaged_python,require_packaged_python
                        identity=require_packaged_python(Path(config['suite']),observe_packaged_python())
                        anchor=_native_anchor(config)
                        reader=_UnoReader(config,anchor,contract=contract) if explicit_model else _UnoReader(config,anchor)
                    else:assert reader is not None
                    from writer_style_smoke import observe_packaged_python,require_packaged_python
                    identity=require_packaged_python(Path(config['suite']),observe_packaged_python())
                    ticks,frequency=_qpc()
                    before=anchor.snapshot()
                    if contract==_CALC_PENDING_INITIAL_CONTRACT:
                        observation=reader.read(request_action=action,request_sequence=sequence)
                        require_calc_pending_program_phase(observation,expected_action=action,expected_sequence=sequence)
                    else:observation=reader.read()
                    after=anchor.snapshot()
                    finished_ticks,finished_frequency=_qpc();assert finished_frequency==frequency
                    observation['helperQpc']=dict(startedTicks=ticks,finishedTicks=finished_ticks,frequency=frequency)
                    observation.update(kind=contract.kind,pythonIdentity=identity,nativeSnapshots=dict(helperBefore=before,helperAfter=after),
                        retainedProcessHandle=True,handleSignaled=False,readOnlyObservation=True,sameFrameControllerModelVerified=True,
                        readCallCleanupSucceeded=True,readerStillRetained=True,operations=list(contract.operations))
                    reply.update(ok=True,observation=observation)
            except BaseException as exc:
                failed=True;reply['error']=dict(type=type(exc).__name__,message=str(exc),winerror=getattr(exc,'winerror',None),traceback=traceback.format_exc(),
                    attemptedObservation=observation,nativeSnapshot=getattr(anchor,'last_snapshot',getattr(exc,'native_snapshot',None)),
                    unoSnapshot=getattr(reader,'last_snapshot',getattr(exc,'uno_snapshot',None)),frameEnumeration=getattr(reader,'last_frames',getattr(exc,'frame_enumeration',None)),
                    unoDiagnostic=getattr(reader,'diagnostic',getattr(exc,'uno_diagnostic',None)),
                    pendingInputDiagnostic=getattr(exc,'pending_input_diagnostic',
                        getattr(getattr(reader,'pending_input',None),'last_diagnostic',None)),
                    impressGeometryDiagnostic=getattr(exc,'impress_geometry_diagnostic',None),
                    impressDiscoveryDiagnostic=getattr(exc,'impress_discovery_diagnostic',None),
                    observerProxiesReleased=getattr(exc,'observer_proxies_released',None),pythonIdentity=identity,nativeHandleClosures=getattr(exc,'native_handle_closures',None),profileDirectoryDiagnostic=getattr(exc,'profile_directory_diagnostic',None),profileDirectoryClosure=getattr(exc,'profile_directory_closure',None))
                selection_capture=getattr(reader,'calc_selection_capture',None)
                if selection_capture:
                    # Returned count/address facts precede every assertion. Keep
                    # their bounded local projection in the primary reply before
                    # a release request can preempt optional remote diagnostics.
                    try:
                        attempt=_calc_selection_attempt(selection_capture)
                        if attempt is not None:reply['error']['calcSelectionAttempt']=attempt
                    except BaseException:
                        reply['error']['calcSelectionAttempt']=dict(unavailable=True,reason='local-projection-error')
                    # Detach every nested primary snapshot before diagnostic reads
                    # may update the reader's mutable observation dictionaries.
                    reply['error']=json.loads(json.dumps(reply['error'],ensure_ascii=False,allow_nan=False))
                    try:
                        diagnostic=_calc_selection_diagnostic_header(sequence,action,reader,selection_capture,
                            config['readerDeadline'],reply['error'],clock=time.monotonic)
                        reply['calcSelectionDiagnostic']=diagnostic
                    except BaseException as later:
                        # Optional local metadata must never withhold the primary.
                        reply['calcSelectionDiagnostic']=dict(schemaVersion=1,kind='failed-calc-selection-diagnostic',
                            status='unavailable',reason='header-error',sequence=sequence,action=action,
                            helperPid=reply['readerPid'],readerDeadline=config['readerDeadline'],startedAt=None,
                            primaryErrorSha256=None,selectedProxy=None,selectionStage=None,
                            selectionAttempt=reply['error'].get('calcSelectionAttempt'),interfaceNames=None,
                            implementation=None,services=None,preCount=None,postCount=None,rawCounts=[],
                            indexedAddresses=[],calls=[],guard=None,pendingRequest=False,
                            errors=[dict(type=type(later).__name__,message='Diagnostic header preparation failed')],qualification=False)
            _atomic_json(directory/f'reply-{sequence:03d}.json',reply);sequence+=1
            if selection_capture is not None:
                try:
                    if diagnostic is not None:
                        _collect_calc_selection_diagnostic(directory,reader,anchor,selection_capture,diagnostic,clock=time.monotonic)
                except BaseException as later:
                    # The original failed reply is already immutable and visible.
                    try:_atomic_json(directory/f'selection-diagnostic-{sequence-1:03d}-unexpected.json',
                        dict(qualification=False,type=type(later).__name__,message=str(later)[:1024]))
                    except BaseException:pass
                finally:selection_capture.clear()
            if action=='release':return 0 if reply['ok'] else 1
    finally:
        if reader:reader.release()
        if anchor:anchor.close()
    return 1


if __name__=='__main__':
    assert len(sys.argv)==3 and sys.argv[1] in ('--helper','--model-helper')
    raise SystemExit(_helper(sys.argv[2],explicit_model=sys.argv[1]=='--model-helper'))
