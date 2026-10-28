"""Finite projection of an already captured semantic-setup guard, without APIs.

The five integers are [before relation, after relation, start attempted, returned
observation count, cleanup present]. Relations: 0 no HWND, 1 dead HWND, 2 original
shell/root/thread, 3 original engine/root/thread, 4 owned PID with another root or
thread, 5 another live PID. They classify a snapshot; they do not identify what
changed foreground or prove delivery. No vector means unknown, unlike a known
empty returned-observation list. Start: 0 absent, 1 false, 2 true. Start attempted
does not prove spawn; a cleanup dictionary does not prove cleanup completion.
"""
from __future__ import annotations

import math
import re

_U32,_U64=2**32-1,2**64-1
_SOURCE={'sourceCommit','sourceRun','runAttempt','repository','job','architecture'}
_BINDING=('shellPid','officePid','suiteHwnd','parentHwnd','childHwnd','rootHwnd',
          'shellCreationTime','officeCreationTime')


def _need(condition):
    if not condition:raise ValueError('Unbound existing focus observation')


def _dict(value):
    _need(type(value) is dict)
    return value


def _int(value,maximum=_U32,minimum=0):
    _need(type(value) is int and minimum<=value<=maximum)
    return value


def _time(value):
    _need(type(value) in (int,float) and math.isfinite(value) and value>=0)
    return value


def _window(value):
    row=_dict(value)
    result={key:_int(row.get(key),_U64 if key in ('hwnd','rootHwnd') else _U32)
            for key in ('hwnd','pid','threadId','rootHwnd')}
    _need(type(row.get('isWindow')) is bool)
    result['isWindow']=row['isWindow']
    if result['isWindow']:_need(all(result[key]>0 for key in ('hwnd','pid','threadId','rootHwnd')))
    else:_need(all(result[key]==0 for key in ('pid','threadId','rootHwnd')))
    return result


def _process(value,pid,created,handle=None):
    row=_dict(value)
    _need(_int(row.get('pid'),minimum=1)==pid and
          _int(row.get('creationTime'),_U64,1)==created and _int(row.get('waitResult'))==258)
    observed=_int(row.get('handleValue'),_U64,1)
    _need(handle is None or observed==handle)
    return observed


def _relation(row,binding,threads):
    row=_window(row)
    if not row['isWindow']:return int(row['hwnd']>0)
    if row['pid'] in threads:
        if row['rootHwnd']!=binding['suiteHwnd'] or row['threadId']!=threads[row['pid']]:return 4
        return 2 if row['pid']==binding['shellPid'] else 3
    return 5


def project(record):
    """Return one atomic existing-snapshot vector, or None for unbound data."""
    try:
        record=_dict(record);module=record.get('module')
        _need(module in ('writer','calc','impress') and record.get('case')=='ime-'+module
              and record.get('kind') in ('native-korean-ime','calc-save-dispatch-diagnostic')
              and _int(record.get('imePolicyVersion'))==4)
        _need(record['kind']!='calc-save-dispatch-diagnostic' or module=='calc')
        architecture=record.get('architecture');_need(architecture in ('x64','arm64'))
        readiness=_dict(record.get('readiness'));source=_dict(readiness.get('source'))
        _need(source.keys()==_SOURCE and type(source['sourceCommit']) is str
              and re.fullmatch('[0-9a-f]{40}',source['sourceCommit']) and source['sourceCommit']!='0'*40
              and type(source['sourceRun']) is str and re.fullmatch('[1-9][0-9]{0,18}',source['sourceRun'])
              and int(source['sourceRun'])<2**63 and source['runAttempt']=='1'
              and source['repository']=='ATLKR/OpenGeul' and source['job']=='windows-suite'
              and source['architecture']==architecture)
        _need(_int(readiness.get('nativeMachine'))=={'x64':0x8664,'arm64':0xaa64}[architecture]
              and _int(readiness.get('controllerMachine'))==0)
        keyboard=_dict(record.get('imeKeyboardSession'));binding=_dict(keyboard.get('expectedNative'))
        _need(_int(keyboard.get('schemaVersion'))==1 and keyboard.get('kind')=='owned-first-admission-ime-keyboard'
              and keyboard.get('module')==module)
        expected={key:_int(binding.get(key),_U32 if key.endswith('Pid') else _U64,1) for key in _BINDING}
        _need(expected['shellPid']!=expected['officePid'] and expected['suiteHwnd']==expected['rootHwnd']
              and expected['shellCreationTime']<=expected['officeCreationTime'])
        for key,field in (('shellPid','shellPid'),('officePid','officePid'),('windowHwnd','suiteHwnd'),
                          ('parentHwnd','parentHwnd'),('childHwnd','childHwnd')):
            _need(_int(record.get(key),_U32 if key.endswith('Pid') else _U64,1)==expected[field])
        thread=_int(record.get('editorTid'),minimum=1)
        context=_dict(record.get('imeSemanticContext'));phase=context.get('phase')
        _need(phase in ('pre','post') and record.get('stage')=='verify-'+phase+'-prefix-editing-context'
              and context.get('kind')=='ime-semantic-editing-context' and _int(context.get('schemaVersion'))==1
              and context.get('module')==module and type(context.get('success')) is bool)
        history=record.get('imeSemanticContexts')
        _need(type(history) is list and len(history)<=2)
        appended=bool(history and history[-1] is context)
        if not appended:
            # The actual producer guards the newly installed context before it
            # appends it to history or constructs/starts the reader.
            _need(len(history)==(0 if phase=='pre' else 1)
                  and type(context.get('observations')) is list and len(context['observations'])==0 and 'readerStartAttempted' not in context
                  and 'cleanup' not in context)
            if phase=='post':
                prior=_dict(history[0])
                _need(prior.get('module')==module and prior.get('phase')=='pre'
                      and prior.get('kind')=='ime-semantic-editing-context'
                      and prior.get('setupDeadline')==context.get('setupDeadline'))
                prior_binding=_dict(prior.get('expectedNative'))
                _need(all(_int(prior_binding.get(key),_U32 if key.endswith('Pid') else _U64,1)==value
                          for key,value in expected.items()))
        current=_dict(context.get('expectedNative'))
        _need(all(_int(current.get(key),_U32 if key.endswith('Pid') else _U64,1)==value
                  for key,value in expected.items()))
        setup=_dict(record.get('imeSetupBudget'));deadline=_time(setup.get('deadline'))
        started=_time(context.get('startedAt'));reader_deadline=_time(context.get('readerDeadline'))
        _need(_time(setup.get('startedAt'))<=started<reader_deadline==min(deadline,started+12.)
              and deadline==_time(keyboard.get('setupDeadline'))==_time(context.get('setupDeadline'))
              and 0<deadline-_time(setup.get('startedAt'))<=60.)
        guard=_dict(keyboard.get('lastGuardObservation'));scope=_dict(guard.get('scope'))
        _need(_int(guard.get('keyboardThreadId'),minimum=1)==thread)
        for role,pid,created in (('shell',expected['shellPid'],expected['shellCreationTime']),
                                 ('engine',expected['officePid'],expected['officeCreationTime'])):
            handle=_process(keyboard.get('original'+role.title()),pid,created)
            _process(guard.get(role),pid,created,handle)
        threads={}
        for edge in ('before','after'):
            row=_dict(scope.get(edge));suite=_window(row.get('suite'));editor=_window(row.get('editor'))
            _need(suite['isWindow'] and suite['hwnd']==expected['suiteHwnd']
                  and suite['pid']==expected['shellPid'] and suite['rootHwnd']==expected['suiteHwnd']
                  and editor['isWindow'] and editor['hwnd']==expected['childHwnd']
                  and editor['pid']==expected['officePid'] and editor['rootHwnd']==expected['suiteHwnd']
                  and editor['threadId']==thread and row.get('editorWithinSuite') is True)
            if not threads:threads={expected['shellPid']:suite['threadId'],expected['officePid']:thread}
            _need(suite['threadId']==threads[expected['shellPid']])
        observations=context.get('observations')
        _need(type(observations) is list and len(observations)<=120 and all(type(row) is dict for row in observations))
        attempted=context.get('readerStartAttempted')
        _need('readerStartAttempted' not in context or type(attempted) is bool)
        _need('cleanup' not in context or type(context['cleanup']) is dict)
        return [_relation(scope[edge]['foreground'],expected,threads) for edge in ('before','after')]+[
            int(attempted)+1 if 'readerStartAttempted' in context else 0,len(observations),int('cleanup' in context)]
    except (KeyError,ValueError,TypeError,OverflowError):return None
