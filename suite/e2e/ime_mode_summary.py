"""Project finite IMM samples from a canonical NORMAL-case first snapshot.

The reviewed producer retains its first message snapshot before command 4 on
success and failure paths. This control-flow contract is the restoration
boundary; the raw header and ACK 3 alone do not authenticate a cutoff or detect
forged late ACK-3 rows. A flow regression protects that producer ordering.
Counts describe valid observed samples only, never continuous mode or causation.
Payload, message/key codes, HIMC and document text are not inspected or returned.
"""
from __future__ import annotations

import ntpath
import re

if __package__:
    from .ime_thread_mode import require_mode_receipt
else:
    from ime_thread_mode import require_mode_receipt

_HEADER={'schemaVersion','kind','status','capacity','observedCount','events'}
_ROW={'sequence','message','origin','pid','tid','commandAck','hwnd','layout','wparam','lparam',
      'focusHwnd','counter','immContextPresent','immConversionSucceeded','immOpen','immConversion','immSentence','himc'}
_SOURCE={'sourceCommit','sourceRun','runAttempt','repository','job','architecture'}
_CONTEXT={'magic','version','pid','tid','targetHwnd','rootHwnd'}
_U32=2**32-1
_U64=2**64-1


class _Invalid(ValueError):
    pass


def _need(condition):
    if not condition:raise _Invalid('Unbound canonical IMM observation')


def _integer(value,maximum=_U32,minimum=0):
    _need(type(value) is int and minimum<=value<=maximum)
    return value


def _dict(value,keys=None):
    _need(type(value) is dict)
    if keys is not None:_need(value.keys()==keys)
    return value


def _image(value):
    _need(type(value) is str and value and '\x00' not in value and ntpath.isabs(value))
    return ntpath.normcase(ntpath.normpath(value))


def _guid(value):
    _need(type(value) is str and re.fullmatch(r'\{[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\}',value))
    return value.lower()


def _binding(record):
    module=record.get('module')
    _need(module in ('writer','calc','impress') and record.get('kind')=='native-korean-ime'
          and record.get('case')=='ime-'+module)
    _need(_integer(record.get('imePolicyVersion'))==4)
    architecture=record.get('architecture')
    _need(architecture in ('x64','arm64'))
    readiness=_dict(record.get('readiness'));source=_dict(readiness.get('source'),_SOURCE)
    _need(type(source['sourceCommit']) is str and re.fullmatch('[0-9a-f]{40}',source['sourceCommit'])
          and source['sourceCommit']!='0'*40)
    _need(type(source['sourceRun']) is str and re.fullmatch('[1-9][0-9]{0,18}',source['sourceRun'])
          and int(source['sourceRun'])<2**63 and source['runAttempt']=='1'
          and source['repository']=='ATLKR/OpenGeul' and source['job']=='windows-suite'
          and source['architecture']==architecture)
    _need(_integer(readiness.get('nativeMachine'))=={'x64':0x8664,'arm64':0xaa64}[architecture]
          and _integer(readiness.get('controllerMachine'))==0)
    profile=_dict(readiness.get('profile'))
    _need(profile.get('registered') is True)
    provider,profile_id=_guid(profile.get('providerClsid')),_guid(profile.get('profileGuid'))
    keyboard=_dict(record.get('imeKeyboardSession'))
    _need(_integer(keyboard.get('schemaVersion'))==1 and keyboard.get('kind')=='owned-first-admission-ime-keyboard')
    binding=_dict(keyboard.get('expectedNative'))
    for field in ('shellPid','officePid','suiteHwnd','parentHwnd','childHwnd','rootHwnd'):
        _integer(binding.get(field),_U32 if field.endswith('Pid') else _U64,1)
    _integer(binding.get('shellCreationTime'),_U64,1);_integer(binding.get('officeCreationTime'),_U64,1)
    _need(binding['officeCreationTime']>=binding['shellCreationTime'] and binding['shellPid']!=binding['officePid'])
    for field in ('shellPid','officePid'):_need(_integer(record.get(field),_U32,1)==binding[field])
    _need(_integer(record.get('windowHwnd'),_U64,1)==binding['suiteHwnd']==binding['rootHwnd'])
    _need(_integer(record.get('parentHwnd'),_U64,1)==binding['parentHwnd']
          and _integer(record.get('childHwnd'),_U64,1)==binding['childHwnd'])
    tid=_integer(record.get('editorTid'),_U32,1);focus=_integer(record.get('keyboardFocusHwnd'),_U64,1)
    image=_image(binding.get('expectedImage'))
    _need(image.endswith('\\office\\program\\soffice.bin'))
    shell_image=ntpath.join(ntpath.dirname(ntpath.dirname(ntpath.dirname(image))),'OpenGeul.Office.exe')
    for key,pid,created,expected_image in (
            ('originalEngine',binding['officePid'],binding['officeCreationTime'],image),
            ('originalShell',binding['shellPid'],binding['shellCreationTime'],shell_image)):
        original=_dict(keyboard.get(key))
        _need(_integer(original.get('pid'),_U32,1)==pid
              and _integer(original.get('creationTime'),_U64,1)==created
              and _integer(original.get('waitResult'))==258 and _image(original.get('image'))==_image(expected_image))
        _integer(original.get('handleValue'),_U64,1)
    commands=record.get('imeCommands')
    _need(type(commands) is list and len(commands) in (3,4))
    _need([_integer(_dict(row).get('command'),4,1) for row in commands]==list(range(1,len(commands)+1)))
    context=dict(magic=0x4f47494d,version=4,pid=binding['officePid'],tid=tid,targetHwnd=focus,rootHwnd=binding['rootHwnd'])
    for number,command in enumerate(commands[:3],1):
        _need(command.get('acknowledged') is True and command.get('success') is True)
        for field,value in (('status',0),('nativeAck',number),('publishedCommand',number),
                            ('nativeAttemptedMask',(1<<number)-1),('nativeCallAttempts',1),
                            ('nativePublicationReturn',1),('policyVersion',4)):
            _need(_integer(command.get(field))==value)
        actual=_dict(command.get('nativeContext'),_CONTEXT)
        _need(all(_integer(actual[key],_U64)==value for key,value in context.items()))
        snapshot=_dict(command.get('snapshotEvidence'),{'copyReturn','ackBefore','ackAfter','stable'})
        _need(snapshot['stable'] is True)
        for field,value in (('copyReturn',1),('ackBefore',number),('ackAfter',number)):
            _need(_integer(snapshot[field])==value)
        rejection=_dict(command.get('commandRejection'),{'count','sequence','during','reason'})
        _need(all(_integer(value)==0 for value in rejection.values()))
    command=commands[2]
    _need(_integer(command.get('activeLanguage'))==0x0412 and _integer(command.get('activeProfileType'))==1
          and _guid(command.get('activeClsid'))==provider and _guid(command.get('activeProfile'))==profile_id)
    for field in ('profileManagerHresult','previousProfileHresult','activateProfileHresult','activeProfileHresult','activateLayoutError'):
        _need(_integer(command.get(field))==0)
    for field in ('tsfModeCaptured','profileChangeAttempted'):_need(_integer(command.get(field))==1)
    layout=_integer(command.get('layout'),_U64,1);_need(layout&0xffff==0x0412)
    require_mode_receipt(_dict(command.get('threadMode')),3)
    imm=_dict(command.get('immState'),{'contextPresent','conversionSucceeded','open','conversion','sentence'})
    _need(all(_integer(imm.get(field),1)==1 for field in ('contextPresent','conversionSucceeded','open')))
    _need(_integer(imm.get('conversion'))&1==1)
    return binding['officePid'],tid,focus,layout


def project(record):
    """Return five closed sample counters, or None for unknown/unbound capture."""
    if not __debug__:return None
    try:
        record=_dict(record);pid,tid,focus,layout=_binding(record)
        capture=_dict(record.get('imeMessageDiagnostics'),_HEADER)
        _need(_integer(capture.get('schemaVersion'))==1 and capture.get('kind')=='passive-owned-ime-messages'
              and capture.get('status')=='complete' and _integer(capture.get('capacity'))==128)
        rows=capture.get('events');_need(type(rows) is list and len(rows)<=128)
        _need(_integer(capture.get('observedCount'),128)==len(rows))
        samples=closed=alpha=0;last_open=last_native=None;previous_ack=previous_counter=0
        for sequence,value in enumerate(rows,1):
            row=_dict(value,_ROW)
            _need(_integer(row.get('sequence'),128,1)==sequence and _integer(row.get('origin'),2,1) in (1,2))
            _need(_integer(row.get('pid'),_U32,1)==pid and _integer(row.get('tid'),_U32,1)==tid
                  and _integer(row.get('hwnd'),_U64,1)==focus)
            ack=_integer(row.get('commandAck'),3);counter=_integer(row.get('counter'),_U64,1)
            _need(previous_ack<=ack and previous_counter<=counter);previous_ack,previous_counter=ack,counter
            row_layout=_integer(row.get('layout'),_U64,1);row_focus=_integer(row.get('focusHwnd'),_U64)
            context=_integer(row.get('immContextPresent'),1);succeeded=_integer(row.get('immConversionSucceeded'),1)
            opened=_integer(row.get('immOpen'),1);conversion=_integer(row.get('immConversion'))
            _need(context or not succeeded)
            if ack!=3:continue
            _need(row_layout==layout and row_focus==focus)
            if not context or not succeeded:continue
            native=int(bool(conversion&1));samples+=1
            closed+=int(opened==0);alpha+=int(opened==1 and native==0)
            last_open,last_native=opened,native
        if not samples:return None
        return dict(imeModeSamples=samples,imeModeClosed=closed,imeModeAlpha=alpha,
                    imeLastOpen=last_open,imeLastNative=last_native)
    except (AssertionError,KeyError,TypeError,ValueError,OverflowError):
        return None
