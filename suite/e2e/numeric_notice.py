"""Closed notices from the current controller; no new target observations."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys

CASE_TITLE = 'OpenGeul numeric case v1'
TRACE_TITLE = 'OpenGeul Calc numeric trace v1'
OPT_IN = 'OPENGEUL_SUITE_NUMERIC_NOTICE'
TRACE_OPT_IN = 'OPENGEUL_SUITE_CALC_TRACE_NOTICE'
FOREGROUND_OPT_IN = 'OPENGEUL_SUITE_FOREGROUND_NOTICE'
# Extend numeric identifiers at the end so earlier run notices keep their meaning.
SCOPES = {'calc-close':1,'home-routes':2,'korean-ime':3,'korean-ui':4,'writer-style':5,
          'lifecycle':6,'native-first':7,'native-second':8,'calc-dispatch':9,'native-integrity':10,
          'native31-privacy':12,'calc-save':13}
MAX_CASE_BYTES, MAX_TRACE_BYTES, MAX_NOTICES = 2048, 32768, 8
EXCEPTIONS = {kind: index for index, kind in enumerate((AssertionError, TimeoutError,
    PermissionError, FileNotFoundError, FileExistsError, OSError, ValueError, TypeError,
    RuntimeError, KeyError, AttributeError, NotImplementedError), 1)}
UNO_RUNTIME_EXCEPTION_CODE = 13  # Classified only by the existing UNO child; no UNO import here.
SOURCE_FILES = {name: index for index, name in enumerate((
    'windows_smoke.py', 'calc_close_probe.py', 'home_routing_smoke.py', 'korean_ime_smoke.py',
    'korean_ui_smoke.py', 'writer_style_smoke.py', 'lifecycle_smoke.py', 'writer_model_reader.py',
    'writer_model_barrier.py', 'calc_model_barrier.py', 'ime_keyboard_session.py',
    'ime_engine_retirement.py', 'scenario_editor_shortcuts.py', 'counted_editor_shortcuts.py',
    'owned_control_actions.py', 'owned_save_menu.py', 'native_window_evidence.py',
    'ime_calc_setup.py', 'native_accessibility.py', 'calc_dispatch_diagnostic.py',
    'ime_semantic_context.py', 'calc_pending_input.py', 'native_archive_completeness.py',
    'capture_readiness.py', 'ascii_editor_input.py', 'impress_focused_view.py',
    'native31_desktop_control.py', 'native31_privacy_prepare.py', 'native31_suite_prepare.py',
    'runner-ready.py', 'policy.py', 'native_cleanup_receipt.py', 'calc_save_smoke.py',
    'editor_click_readiness.py', 'suite_window_activation.py'), 1)}
_ROOT_SOURCE_FILES = {'native31_desktop_control.py':'e2e/native31_desktop_control.py',
    'native31_privacy_prepare.py':'e2e/native31_privacy_prepare.py',
    'native31_suite_prepare.py':'e2e/native31_suite_prepare.py',
    'runner-ready.py':'e2e/runner-ready.py', 'policy.py':'ci/policy.py'}
_OWNED_FILES = {os.path.normcase(str(Path(__file__).with_name(name))): code
    for name, code in SOURCE_FILES.items() if name not in _ROOT_SOURCE_FILES}
_OWNED_FILES.update({os.path.normcase(str(Path(__file__).resolve().parents[2] / relative)): SOURCE_FILES[name]
    for name, relative in _ROOT_SOURCE_FILES.items()})
MODULES = {name: index for index, name in enumerate(('writer','calc','impress','draw','math','base','hwp'), 1)}
_FORMATS = ('writer-odt','writer-docx','writer-doc','writer-rtf','writer-txt','calc-ods',
    'calc-xlsx','calc-xls','calc-csv','impress-odp','impress-pptx','impress-ppt','draw-odg',
    'math-odf','base-odb','hwp-hwp','hwp-hwpx')
_CASES = (('home', '') , *((name, name) for name in MODULES if name != 'hwp'),
    *((f'new-{name}', name) for name in MODULES if name != 'hwp'),
    *((f'calc-close-{name}', 'calc') for name in ('save','discard','cancel')),
    *((f'ime-{name}', name) for name in ('writer','calc','impress')),
    *((f'korean-ui-{name}', name) for name in ('writer','calc','impress','draw')),
    ('writer-heading1','writer'), *((f'tile-{name}',name) for name in MODULES if name != 'hwp'),
    ('home-open-cancel',''), *((f'home-open-{name}',name.split('-')[0]) for name in _FORMATS),
    ('document-file-open','writer'),
    *((name,'writer') for name in ('dirty-writer-cancel-save','dirty-writer-discard',
      'new-writer-saveas-cancel','failed-saveas-retains-editor','home-two-documents-cancel','resize-minimize-restore')),
    ('hwp-tile-hwpx-route','hwp'), ('lifecycle-summary',''), ('native-integrity',''), ('native31-privacy',''),
    ('calc-active-cell-save','calc'))
CASES = {name: (index, MODULES.get(module, 0)) for index, (name,module) in enumerate(_CASES, 1)}
_STAGES = ('setup','startup','case-setup','verify-fixture','verify-generated-fixture','launch','attach',
    'prepare-window','focus-editor','prepare-owned-native-focus','prepare-editor','physical-editor-input',
    'native-controller-architecture','native-shell-architecture','native-office-architecture',
    'observe-before-input','type-without-enter','single-physical-ctrl-w',
    'require-existing-save-discard-cancel-prompt','verify-cancel-before-any-later-save',
    'authorized-cleanup-discard-after-cancel-proof','wait-original-close','verify-saved-body',
    'physical-heading1-shortcut','save-via-suite-menu','capture-saved-editor','gui-complete',
    'capture-screenshot','capture-os-accessibility-diagnostic','capture-native-accessible-objects',
    'assert-korean-tabbed-ui','wait-engine-exit','verify-final-fixtures','find-home','close-home',
    'wait-shell-exit','close-document','wait-document-close','wait-editor-close','complete',
    'verify-pre-prefix-editing-context','type-ascii-prefix-before-ime','verify-post-prefix-editing-context',
    'verify-calc-context-before-ime-observer','install-owned-thread-observer','activate-microsoft-korean-profile',
    'physical-dubeolsik-composition','commit-native-composition','restore-owned-input-thread','save-ctrl-s',
    'actual-uno-reopen','calc-dispatch-observation-complete','launch-owned-home','await-original-home',
    'copy-owned-route-input','trigger-owned-open-dialog','wait-owned-open-dialog-readiness',
    'send-owned-open-dialog-escape','assign-owned-open-filename','click-owned-open-button',
    'wait-owned-open-dialog-disappearance','observe-owned-home-calc','capture-csv-post-getter',
    'await-owned-hwp-route','wait-real-saveas-error','close-home-with-two-documents',
    'hwpx-route-native-readiness','hwp-tile-native-readiness',
    *(f'await-new-{m}-attachment' for m in MODULES), *(f'close-owned-{m}' for m in MODULES),
    *(f'verify-retained-{m}-exit' for m in MODULES), *(f'dirty-close-{c}' for c in ('save','discard','cancel')),
    'verify-native-archives', 'prepare-native31', 'observe-clean-before-input',
    'physical-edit-without-enter', 'single-physical-ctrl-s', 'wait-exact-durable-workbook',
    'close-original-editor', 'independent-fresh-engine-reopen',
    *(f'native-integrity-{root}-{gate}'
      for root in ('shared','calc-save','calc-close-save','calc-close-discard','calc-close-cancel')
      for gate in ('root-admission','manifest-discovery','path-crash-scan','archive-members','shutdown-proof')),
    *(f'native-integrity-evidence-{root}-{gate}' for root in ('calc-save','calc-close')
      for gate in ('root-admission','path-crash-scan')),
    'native-integrity-generation-completeness',
    'writer-os-owner', 'writer-os-abi', 'writer-os-root', 'writer-os-focus',
    'writer-os-document-role', 'writer-os-focus-state', 'writer-os-ia2',
    'writer-os-text', 'writer-os-parent', 'writer-os-cleanup', 'writer-os-complete',
    'writer-os-protocol', 'writer-os-timeout')
STAGES = {name:index for index,name in enumerate(_STAGES, 1)}

# Each bit means that the source field was present and had the declared type.
# A zero with an unset bit is unknown, including an unobserved exit code.
_FIELDS = (
    ('shellPid','pid',(('shellPid',),)), ('enginePid','pid',(('officePid',),)),
    ('officeCreationTime','u64',(('officeCreationTime',),('imeKeyboardSession','expectedNative','officeCreationTime'))),
    ('shellCreationTime','u64',(('originalShell','nativeCreation','fileTime'),('imeKeyboardSession','expectedNative','shellCreationTime'))),
    ('shellExitCode','u32',(('shellExitCode',),)), ('officeExitCode','u32',(('officeExitCode',),)),
    ('cleanupShellExitCode','u32',(('testProcessCleanup','shellExitCode'),)),
    ('cleanClose','bool',(('cleanClose',),)), ('forcedCleanup','bool',(('forcedCleanup',),)),
    ('forcedCleanupRequired','bool',(('forcedCleanupRequired',),)),
    ('originalFixtureUnchanged','bool',(('originalFixtureUnchanged',),)),
    ('originalCloseVerified','bool',(('originalCloseVerified',),)),
    ('diskOutcomeVerified','bool',(('diskOutcomeVerified',),)),
    ('packagedUnoVerified','bool',(('packagedUnoVerified',),)), ('promptVerified','bool',(('promptVerified',),)),
    ('officeExitedAfterCleanup','bool',(('officeExitedAfterCleanup',),)),
    ('engineHandleReleased','bool',(('imeKeyboardSession','engineHandleReleased'),)),
    ('forceRequested','bool',(('testProcessCleanup','forceRequested'),)),
    ('closeShortcutCount','u32',(('closeShortcutCount',),)),
    ('choiceClickCount','u32',(('choiceClickCount',),)),
    ('saveAttempted','bool',(('calcDispatchOracle','saveAttempted'),)),
    ('saveReturned','bool',(('calcDispatchOracle','saveReturned'),)),
    ('savedMarkerObserved','bool',(('calcDispatchOracle','savedMarkerObserved'),)),
    ('dispatchEntered','u32',(('calcDispatchDiagnostic','analysis','entered'),)),
    ('dispatchReturned','u32',(('calcDispatchDiagnostic','analysis','returned'),)),
    ('dispatchOpen','u32',(('calcDispatchDiagnostic','analysis','openInvocations'),)),
    ('dispatchComplete','flag',(('calcDispatchDiagnostic','analysis','complete'),)),
    ('processExitProved','flag',(('processExitProved',),)),
    ('controllerResourcesReleased','flag',(('calcDispatchDiagnostic','cleanup','controllerResourcesReleased'),)),
    ('withinDeadline','bool',(('calcDispatchLocalCleanup','withinDeadline'),)),
    ('expectedCaseCount','u32',(('expectedCaseCount',),)),
    ('completedCaseCount','u32',(('completedCaseCount',),)),
    ('passedCaseCount','u32',(('passedCaseCount',),)),
    ('failedCaseCount','count',(('failedCases',),)), ('missingCaseCount','count',(('missingCases',),)),
    ('duplicateCaseCount','count',(('duplicateCases',),)), ('unexpectedCaseCount','count',(('unexpectedCases',),)),
    ('baselineFixturesUnchanged','bool',(('baselineFixturesUnchanged',),)),
    ('packagedUnoExitCode','u32',(('packagedUnoExitCode',),)),
    ('cleanupErrorCount','count',(('cleanupErrors',),)),
    ('diagnosticRunnerPassed','bool',(('diagnosticRunnerPassed',),)),
    ('shellExitObserved','bool',(('calcDispatchShell','shellExitObserved'),)),
    ('shellHandleReleased','bool',(('calcDispatchShell','shellHandleReleased'),)),
    ('shellDisposalError','u32',(('calcDispatchShell','error'),)),
    ('shellCleanupExitCode','u32',(('calcDispatchShell','exitCode'),)),
    ('retirementClosed','bool',(('imeEngineRetirement','close','result'),)),
    ('localCleanupErrorCount','count',(('calcDispatchLocalCleanup','errors'),)),
    ('keyboardCleanupErrorCount','count',(('imeKeyboardSession','cleanupErrors'),)),
    ('retirementCleanupErrorCount','count',(('imeEngineRetirement','cleanupErrors'),)),
)
OBSERVATION_NAMES = tuple(row[0] for row in _FIELDS)
_FIELDS_V2 = _FIELDS + (
    ('imeCompositionOrdinal','ordinal',(('imeCompositionOrdinal',),)),
    ('imeCompositionStartEventCount','u32',(('imeCompositionStartEventCount',),)),
)
OBSERVATION_NAMES_V2 = tuple(row[0] for row in _FIELDS_V2)
_FIELDS_V9 = _FIELDS_V2 + (('childHwnd','u64',(('childHwnd',),)),)
OBSERVATION_NAMES_V9 = tuple(row[0] for row in _FIELDS_V9)
_MODE_NAMES = ('imeModeSamples','imeModeClosed','imeModeAlpha','imeLastOpen','imeLastNative')
_FIELDS_V3 = _FIELDS_V2 + tuple((name,'sample' if index<3 else 'flag',(('_imeModeSummary',name),))
    for index,name in enumerate(_MODE_NAMES))
OBSERVATION_NAMES_V3 = tuple(row[0] for row in _FIELDS_V3)
_COMMON = {'schemaVersion','kind','sourceCommit','runId','runAttempt','architecture','scopeCode','sequence','remainingBudget'}
_CASE_KEYS = _COMMON | {'moduleCode','caseCode','stageCode','exceptionCode','fileCode','line',
                       'fieldPresenceMask','observations'}
_CASE_KEYS_V2 = _CASE_KEYS | {'ownedFrames'}
_CASE_KEYS_V3 = _CASE_KEYS_V2 | {'startup'}
_CASE_KEYS_V4 = _CASE_KEYS_V2 | {'focus'}
_CASE_KEYS_V5 = _CASE_KEYS_V4 | {'foreground'}
_CASE_KEYS_V6 = _CASE_KEYS_V2 | {'capture'}
_CASE_KEYS_V7 = _CASE_KEYS_V2 | {'captureGate'}
_CASE_KEYS_V8 = _CASE_KEYS_V2 | {'readerGuard'}
_CASE_KEYS_V9 = _CASE_KEYS_V2 | {'writerOs'}
_CASE_KEYS_V10 = _CASE_KEYS_V2 | {'keyboardLayout'}
_FAILURE_KEYS = {'captured','exceptionCode','fileCode','line'}
_TRACE_KEYS = _COMMON | {'diagnostic','oracleFlags','oraclePresenceMask'}
_STARTUP_FAILURES = []  # At most 32 strong references prevent object-id reuse.


def _integer(value, maximum=0xffffffff, minimum=0):
    return type(value) is int and minimum <= value <= maximum


def _get(record, path):
    for key in path:
        if type(record) is not dict or key not in record: return None
        record = record[key]
    return record


def public_context(environ=None):
    environ = os.environ if environ is None else environ
    expected = {'GITHUB_ACTIONS':'true','GITHUB_REPOSITORY':'ATLKR/OpenGeul',
        'GITHUB_JOB':'windows-suite','GITHUB_EVENT_NAME':'push','GITHUB_RUN_ATTEMPT':'1',
        'GITHUB_REF':'refs/heads/work/opengeul-office-arm64','GITHUB_ACTOR':'ATLKR','GITHUB_ACTOR_ID':'65988341'}
    if any(environ.get(key) != value for key,value in expected.items()): return None
    sha, run = environ.get('GITHUB_SHA'), environ.get('GITHUB_RUN_ID')
    arch = {'X64':0x8664,'ARM64':0xaa64}.get(environ.get('RUNNER_ARCH'))
    if (type(sha) is not str or not re.fullmatch('[0-9a-f]{40}',sha) or sha == '0'*40
            or environ.get('GITHUB_WORKFLOW_SHA') != sha or type(run) is not str
            or not re.fullmatch('[1-9][0-9]{0,18}',run) or int(run)>2**63-1 or arch is None): return None
    return dict(sourceCommit=sha,runId=int(run),runAttempt=1,architecture=arch)


def _context(environ):
    context = public_context(environ)
    scope = environ.get('OPENGEUL_SUITE_NOTICE_SCOPE')
    if (context is None or environ.get(OPT_IN)!='1' or type(scope) is not str
            or scope not in tuple(str(n) for n in SCOPES.values())): return None
    return dict(context,scopeCode=int(scope))


def notices_enabled(environ=None):
    return _context(os.environ if environ is None else environ) is not None


def capture_failure_code(exc):
    # The helper may have captured the original owned location before its IPC
    # wrapper was raised. No message, formatted traceback or proxy data is read.
    result=None
    if isinstance(exc,BaseException):
        raw = vars(exc).get('raw')
        numeric = _get(raw,('error','numericFailure'))
        try:
            result=validate_failure_code(numeric)
        except ValueError:
            pass
    if result is None:
        result = dict(captured=int(isinstance(exc,BaseException)),exceptionCode=EXCEPTIONS.get(type(exc),0),fileCode=0,line=0)
        trace = exc.__traceback__ if isinstance(exc,BaseException) else None
        for _ in range(64):
            if trace is None: break
            code = _OWNED_FILES.get(os.path.normcase(trace.tb_frame.f_code.co_filename))
            if code and _integer(trace.tb_lineno,10_000_000,1): result.update(fileCode=code,line=trace.tb_lineno)
            trace = trace.tb_next
    try:
        context=_context(os.environ)
        if context is not None:
            for name in ('startup_diagnostics','suite.e2e.startup_diagnostics'):
                module=sys.modules.get(name)
                observed=module.project_exception(exc,environ=os.environ) if module is not None else None
                if (type(observed) is dict and observed.keys()=={'shellPid','startup'}
                        and _integer(observed['shellPid'],minimum=1) and _valid_startup(observed['startup'],observed=True)):
                    _STARTUP_FAILURES.append((result,dict(context),observed['shellPid'],tuple(observed['startup'])))
                    del _STARTUP_FAILURES[:-32]
                    break
    except Exception:
        pass
    return result


def capture_failure_frames(exc):
    """Keep the deepest eight owned locations within the first 64 trace nodes."""
    frames=[]
    trace=exc.__traceback__ if isinstance(exc,BaseException) else None
    for _ in range(64):
        if trace is None: break
        code=_OWNED_FILES.get(os.path.normcase(trace.tb_frame.f_code.co_filename))
        if code and _integer(trace.tb_lineno,10_000_000,1): frames.append([code,trace.tb_lineno])
        trace=trace.tb_next
    return frames[-8:]


def validate_failure_frames(value):
    if (type(value) is not list or len(value)>8 or any(type(row) is not list or len(row)!=2
            or type(row[0]) is not int or row[0] not in SOURCE_FILES.values()
            or not _integer(row[1],10_000_000,1) for row in value)):
        raise ValueError('Closed numeric owned frames required')
    return [list(row) for row in value]


def _failure(value):
    return (type(value) is dict and value.keys()==_FAILURE_KEYS and value['captured']==1
        and all(type(v) is int for v in value.values()) and value['exceptionCode'] in (0,*EXCEPTIONS.values(),UNO_RUNTIME_EXCEPTION_CODE)
        and value['fileCode'] in (0,*SOURCE_FILES.values()) and
        (value['line']==0 if value['fileCode']==0 else _integer(value['line'],10_000_000,1)))


def validate_failure_code(value):
    if not _failure(value): raise ValueError('Closed numeric failure required')
    return dict(value)


def _cleanup_failed(record):
    if any(record.get(key) is True for key in ('forcedCleanup','forcedCleanupRequired')): return True
    if any(record.get(key) is False for key in ('officeExitedAfterCleanup','originalFixtureUnchanged')): return True
    if _integer(record.get('shellExitCode'),minimum=1): return True
    for key in ('cleanupError','cleanupTraceback','imeCleanupError','hookCleanupError','keyboardCleanupError',
                'retirementCleanupError','failedReaderCleanupError'):
        value = record.get(key)
        if type(value) is str and len(value)>0: return True  # Presence only; never inspect the text.
    for path in (('cleanupErrors',),('engineCleanupErrors',),('preInputCleanupBindingHandleErrors',),
                 ('failureCleanup','handleErrors'),('imeKeyboardSession','cleanupErrors'),
                 ('imeEngineRetirement','cleanupErrors')):
        value = _get(record,path)
        if type(value) is list and len(value)>0: return True
    if _get(record,('imeEngineRetirement','close','result')) is False: return True
    if _get(record,('failureCleanup','attempted')) is True and _get(record,('failureCleanup','success')) is False: return True
    rows = record.get('retainedHandleClosures')
    return type(rows) is list and any(type(row) is dict and row.get('closeHandleResult') is False for row in rows[:128])


def project_case_notice(name, record, *, environ=None):
    environ = os.environ if environ is None else environ
    context = _context(environ)
    if context is None or type(record) is not dict: return None
    return _project_case(name,record,context,require_failure=True,environ=environ)


def _valid_mode_summary(value):
    return (type(value) is dict and value.keys()==set(_MODE_NAMES)
        and _integer(value['imeModeSamples'],128,1)
        and all(_integer(value[key],128) for key in ('imeModeClosed','imeModeAlpha'))
        and value['imeModeClosed']+value['imeModeAlpha']<=value['imeModeSamples']
        and all(_integer(value[key],1) for key in ('imeLastOpen','imeLastNative')))


def _valid_startup(value,*,observed=False):
    if type(value) is not list or len(value)!=3 or any(type(v) is not int for v in value):return False
    if value==[0,0,0]:return not observed
    phase,reason,native=value
    return (phase in (1,2,3) and reason in (*range(28),*range(32,39))
        and native in (0,2,3,5,8,14,32,87,126,127,193,216,740))


def _startup_summary(record,context):
    for failure,captured,pid,startup in reversed(_STARTUP_FAILURES):
        if (record.get('numericFailure') is failure and context==captured
                and type(record.get('shellPid')) is int and record['shellPid']==pid):return list(startup)
    return [0,0,0]


def captured_startup(record,*,environ=None):
    """Retain only an actual private receipt associated with this failure object."""
    context=_context(os.environ if environ is None else environ)
    return _startup_summary(record,context) if context is not None and type(record) is dict else [0,0,0]


def _mode_summary(record,context):
    try:
        source=_get(record,('readiness','source'))
        expected=dict(sourceCommit=context['sourceCommit'],sourceRun=str(context['runId']),
            runAttempt=str(context['runAttempt']),architecture={0x8664:'x64',0xaa64:'arm64'}[context['architecture']])
        if type(source) is not dict or any(source.get(key)!=value for key,value in expected.items()): return None
        if __package__:
            from .ime_mode_summary import project
        else:
            from ime_mode_summary import project
        value=project(record)
        return dict(value) if _valid_mode_summary(value) else None
    except Exception:
        return None


def _valid_focus(value):
    return (type(value) is list and len(value)==5 and
        all(_integer(number,maximum) for number,maximum in zip(value,(5,5,2,121,1)))
        and (value[3]!=121 or value[2]==value[4]==0))


def _focus_context(case,stage,context):
    return (stage in (STAGES['focus-editor'],STAGES['verify-pre-prefix-editing-context'],STAGES['verify-post-prefix-editing-context'])
        and ((context['scopeCode']==SCOPES['korean-ime'] and case in tuple(CASES['ime-'+name][0] for name in ('writer','calc','impress')))
            or (context['scopeCode']==SCOPES['calc-dispatch'] and context['architecture']==0xaa64 and case==CASES['ime-calc'][0])))


def _focus_summary(record,context):
    try:
        case=CASES.get(record.get('case'),(0,0))[0]
        if not _focus_context(case,STAGES.get(record.get('stage'),0),context):return None
        source=_get(record,('readiness','source'))
        expected=dict(sourceCommit=context['sourceCommit'],sourceRun=str(context['runId']),
            runAttempt=str(context['runAttempt']),architecture={0x8664:'x64',0xaa64:'arm64'}[context['architecture']])
        if type(source) is not dict or any(source.get(key)!=value for key,value in expected.items()):return None
        if __package__:
            from .focus_summary import project
        else:
            from focus_summary import project
        value=project(record)
        return list(value) if _valid_focus(value) else None
    except Exception:
        return None


def _foreground_enabled(context,environ):
    return (environ.get(FOREGROUND_OPT_IN)=='1' and context['architecture']==0xaa64
        and context['scopeCode']==SCOPES['calc-dispatch'])


def _foreground_summary(record,context,environ,focus):
    if (focus is None or not _foreground_enabled(context,environ)
            or record.get('kind')!='calc-save-dispatch-diagnostic' or record.get('module')!='calc'):return None
    try:
        if __package__:
            from .foreground_summary import project
        else:
            from foreground_summary import project
        return project(record)
    except Exception:return None


def _valid_foreground(value,focus):
    if __package__:
        from .foreground_summary import valid
    else:
        from foreground_summary import valid
    return valid(value,focus)


def _valid_capture(value):
    return (type(value) is list and len(value)==5 and all(type(item) is int for item in value)
        and value[0] in (7,15) and value[1]==1 and value[2] in (0,1) and 1<=value[3]<=5
        and value[4] in (0,1) and (bool(value[0]&8) or value[4]==0))


def _capture_context(case,stage,context):
    return (context['scopeCode']==SCOPES['writer-style'] and case==CASES['writer-heading1'][0]
        and stage==STAGES['physical-heading1-shortcut'])


def _capture_summary(record,context):
    value=record.get('numericCaptureSnapshot')
    if (type(record.get('case')) is not str or type(record.get('stage')) is not str
            or type(record.get('kind')) is not str or record['kind']!='native-writer-style'
            or type(record.get('module')) is not str or record['module']!='writer'
            or type(record.get('architecture')) is not str
            or record.get('architecture')!={0x8664:'x64',0xaa64:'arm64'}[context['architecture']]
            or not _capture_context(CASES.get(record.get('case'),(0,0))[0],STAGES.get(record.get('stage'),0),context)
            or not _valid_capture(value)):return None
    failure=record.get('numericFailure')
    try:frames=validate_failure_frames(record.get('numericFailureFrames'))
    except ValueError:return None
    if (not _failure(failure) or failure['exceptionCode']!=1 or failure['fileCode']!=1 or not frames
            or frames[-1]!=[failure['fileCode'],failure['line']]
            or not any(row[0]==SOURCE_FILES['writer_style_smoke.py'] for row in frames[:-1])):return None
    return list(value)


def _valid_capture_gate(value):
    if (type(value) is not list or len(value)!=7 or any(type(item) is not int for item in value)
            or value[0] not in (47,63) or value[1] not in (1,2,3,4,5)
            or any(value[index] not in (0,1) for index in (2,3,4,6)) or not 0<=value[5]<=5):return False
    mask,phase,observed,validated,pending,relation,finished=value
    return (bool(mask&16)==bool(observed) and (observed or relation==validated==pending==0)
        and (not validated or observed) and (not pending or validated)
        and (phase==1 or observed) and (phase!=2 or not validated)
        and (phase not in (3,4,5) or validated) and (phase!=4 or relation==0)
        and (phase!=5 or pending) and (not pending or relation>0))


def _capture_gate_summary(record,context):
    value=record.get('numericCaptureGateSnapshot')
    if (type(record.get('case')) is not str or type(record.get('stage')) is not str
            or type(record.get('kind')) is not str or record['kind']!='native-writer-style'
            or type(record.get('module')) is not str or record['module']!='writer'
            or type(record.get('architecture')) is not str
            or record['architecture']!={0x8664:'x64',0xaa64:'arm64'}[context['architecture']]
            or not _capture_context(CASES.get(record['case'],(0,0))[0],STAGES.get(record['stage'],0),context)
            or not _valid_capture_gate(value)):return None
    failure=record.get('numericFailure')
    try:frames=validate_failure_frames(record.get('numericFailureFrames'))
    except ValueError:return None
    if (not _failure(failure) or failure['exceptionCode']!=1 or failure['fileCode']!=24
            or not frames or frames[-1]!=[24,failure['line']]
            or [row[0] for row in frames]!=[6,13,13,13,13,13,24]):return None
    try:
        if __package__:
            from .writer_capture_summary import bound_timeout
        else:
            from writer_capture_summary import bound_timeout
        return bound_timeout(record)
    except BaseException:
        return None


def _reader_guard_context(case, stage, context, failure, frames):
    if (not frames or failure.get('exceptionCode') != 1
            or frames[-1] != [failure.get('fileCode'), failure.get('line')]):
        return 0
    sources = [row[0] for row in frames]
    if (context['scopeCode'] == SCOPES['calc-close']
            and case == CASES['calc-close-cancel'][0]
            and stage == STAGES['type-without-enter'] and failure.get('fileCode') == 24
            and 2 in sources[:-1] and 14 in sources[:-1]):
        return 1
    if (context['scopeCode'] == SCOPES['korean-ime'] and case == CASES['ime-writer'][0]
            and stage == STAGES['verify-pre-prefix-editing-context']
            and ((failure.get('fileCode') == 11 and 24 in sources[:-1])
                 or (failure.get('fileCode') == 24 and 11 in sources[:-1]))):
        return 2
    return 0


def _reader_guard_site(value, failure):
    return ((failure.get('fileCode') == 11 and value[0] == 2 and value[2] == 0)
            or (failure.get('fileCode') == 24 and 1 <= value[2] <= 5))


def _valid_reader_guard(value):
    try:
        if __package__:
            from .reader_guard_summary import valid
        else:
            from reader_guard_summary import valid
        return valid(value)
    except BaseException:
        return False


def _reader_guard_summary(record, context):
    try:
        failure = validate_failure_code(record.get('numericFailure'))
        frames = validate_failure_frames(record.get('numericFailureFrames'))
        code = _reader_guard_context(CASES.get(record.get('case'), (0,0))[0],
            STAGES.get(record.get('stage'), 0), context, failure, frames)
        if not code:
            return None
        if code == 2 and record.get('architecture') != {0x8664:'x64',0xaa64:'arm64'}[context['architecture']]:
            return None
        if __package__:
            from .reader_guard_summary import project
        else:
            from reader_guard_summary import project
        value = project(record)
        return (value if _valid_reader_guard(value) and value[0] == code
                and _reader_guard_site(value, failure) else None)
    except BaseException:
        return None


def capture_reader_guard(record, primary):
    """Optional projection cannot change the original failure or observe a target."""
    try:
        context = _context(os.environ)
        if context is None or context['scopeCode'] not in (SCOPES['calc-close'], SCOPES['korean-ime']):
            return
        if __package__:
            from .reader_guard_summary import bind
        else:
            from reader_guard_summary import bind
        bind(record, primary)
    except BaseException:
        pass


def emit_reader_guard_case(name, record):
    """The in-memory Writer diagnostic may emit only its qualified guard failure."""
    try:
        context = _context(os.environ)
        if (name != 'ime-writer' or context is None
                or context['scopeCode'] != SCOPES['korean-ime']
                or _reader_guard_summary(record, context) is None):
            return False
        return emit_case_notice(name, record)
    except BaseException:
        return False


def _writer_os_site(case, module, stage, context, failure, frames, value):
    try:
        if __package__:
            from .writer_os_summary import valid, STAGE_NAMES
        else:
            from writer_os_summary import valid, STAGE_NAMES
        return (valid(value) and context['scopeCode'] == SCOPES['korean-ui']
            and case == CASES['korean-ui-writer'][0] and module == MODULES['writer']
            and stage == STAGES[STAGE_NAMES[value[1]]]
            and failure.get('exceptionCode') == 1 and failure.get('fileCode') == 5
            and frames == [[5, failure.get('line')]])
    except BaseException:
        return False


def _writer_os_summary(name, record, context):
    try:
        if (name != 'korean-ui-writer' or record.get('case') != name
                or ('architecture' in record and record['architecture'] !=
                    {0x8664:'x64',0xaa64:'arm64'}[context['architecture']])):
            return None
        failure = validate_failure_code(record.get('numericFailure'))
        frames = validate_failure_frames(record.get('numericFailureFrames'))
        if __package__:
            from .writer_os_summary import project
        else:
            from writer_os_summary import project
        value = project(record)
        # The original observation omits conflicting generations. Preserve its
        # legacy notice when that existing ambiguity cannot bind this vector.
        other_generation = _get(record,('imeKeyboardSession','expectedNative','officeCreationTime'))
        if (_integer(other_generation,2**64-1,1)
                and (value is None or other_generation != value[4])):
            return None
        return (value if _writer_os_site(CASES.get(name,(0,0))[0],
            MODULES.get(record.get('module'),0), STAGES.get(record.get('stage'),0),
            context, failure, frames, value) else None)
    except BaseException:
        return None


def _keyboard_layout_site(case, module, context, failure, frames, value):
    try:
        if __package__:
            from .keyboard_layout_summary import valid
        else:
            from keyboard_layout_summary import valid
        if (not valid(value) or failure.get('exceptionCode') != 1 or len(frames) < 2
                or frames[-1] != [failure.get('fileCode'),failure.get('line')]):
            return False
        scope=context['scopeCode']
        if value[0] == 1:
            allowed=(scope == SCOPES['korean-ime'] and case in
                tuple(CASES['ime-'+name][0] for name in ('writer','calc','impress')))
            allowed=allowed or (scope == SCOPES['calc-dispatch'] and
                context['architecture'] == 0xaa64 and case == CASES['ime-calc'][0])
            source,caller=11,4
        else:
            groups={SCOPES['korean-ui']:(5,tuple('korean-ui-'+name for name in ('writer','calc','impress','draw'))),
                SCOPES['writer-style']:(6,('writer-heading1',)),
                SCOPES['lifecycle']:(7,('dirty-writer-cancel-save','dirty-writer-discard',
                    'new-writer-saveas-cancel','failed-saveas-retains-editor',
                    'home-two-documents-cancel','resize-minimize-restore')),
                SCOPES['native-first']:(1,('writer','calc','impress')),
                SCOPES['native-second']:(1,('writer','calc','impress'))}
            caller,names=groups.get(scope,(0,()))
            allowed=case in tuple(CASES[name][0] for name in names)
            source=13
        modules={code:kind for code,kind in CASES.values()}
        return (allowed and module == modules.get(case) and failure.get('fileCode') == source
            and any(frame[0] == caller for frame in frames[:-1]))
    except BaseException:
        return False


def _keyboard_layout_summary(name, record, context):
    try:
        if ('architecture' in record and record['architecture'] !=
                {0x8664:'x64',0xaa64:'arm64'}[context['architecture']]):
            return None
        failure=validate_failure_code(record.get('numericFailure'))
        frames=validate_failure_frames(record.get('numericFailureFrames'))
        if __package__:
            from .keyboard_layout_summary import project
        else:
            from keyboard_layout_summary import project
        value=project(record)
        case,module=CASES.get(name,(0,0))
        if not _keyboard_layout_site(case,module,context,failure,frames,value):return None
        # Preserve existing ambiguity handling before filling absent optional
        # observations from this original retained guard's identity.
        for key,slot in (('enginePid',2),('officeCreationTime',3)):
            kind,paths=next((kind,paths) for field,kind,paths in _FIELDS_V2 if field == key)
            maximum=2**64-1 if kind == 'u64' else 0xffffffff
            if any(_integer(_get(record,path),maximum,1) and
                    _get(record,path) != value[slot] for path in paths):return None
        return value
    except BaseException:
        return None


def _project_case(name, record, context, *, require_failure,environ=None):
    primary_name = record.get('case') if type(record.get('case')) is str and record['case'] in CASES else name
    if type(primary_name) is not str or primary_name not in CASES: return None
    aggregate_error = (primary_name=='lifecycle-summary' and
        (record.get('baselineFixturesUnchanged') is False or
         (type(record.get('error')) is str and len(record['error'])>0) or
         any(type(record.get(key)) is list and len(record[key])>0 for key in ('failedCases','missingCases','duplicateCases','unexpectedCases'))))
    failure = record.get('numericFailure')
    if not _failure(failure):
        if require_failure and (record.get('success') is not False or not (_cleanup_failed(record) or aggregate_error)): return None
        failure = dict(exceptionCode=0,fileCode=0,line=0)
    case, module = CASES.get(primary_name,(0,0)) if type(primary_name) is str else (0,0)
    try: frames=validate_failure_frames(record.get('numericFailureFrames'))
    except ValueError: frames=[]
    extended=bool(frames) or _integer(record.get('imeCompositionOrdinal'),8,1) or _integer(record.get('imeCompositionStartEventCount'))
    mode=_mode_summary(record,context)
    startup=_startup_summary(record,context)
    focus=_focus_summary(record,context)
    foreground=_foreground_summary(record,context,os.environ if environ is None else environ,focus)
    capture=_capture_summary(record,context)
    capture_gate=_capture_gate_summary(record,context)
    reader_guard=_reader_guard_summary(record,context)
    writer_os=_writer_os_summary(name,record,context)
    keyboard_layout=_keyboard_layout_summary(primary_name,record,context)
    version=8 if reader_guard is not None else (7 if capture_gate is not None else (6 if capture is not None else (5 if foreground is not None else (4 if focus is not None else (3 if mode is not None or startup[0]>0 else (2 if extended else 1))))))
    if writer_os is not None: version=9
    if keyboard_layout is not None: version=10
    fields=_FIELDS_V9 if version in (9,10) else (_FIELDS_V3 if version==3 else (_FIELDS_V2 if version>=2 else _FIELDS))
    source=dict(record,_imeModeSummary=mode)
    if version==10:
        source.update(officePid=keyboard_layout[2],officeCreationTime=keyboard_layout[3],childHwnd=keyboard_layout[4])
    observed, mask = {}, 0
    for index,(key,kind,paths) in enumerate(fields):
        values = []
        for path in paths:
            value = _get(source,path)
            if key=='shellCleanupExitCode' and _get(record,('calcDispatchShell','shellExitObserved')) is not True: value=None
            if kind=='count': value = len(value) if type(value) is list else None
            valid = (type(value) is bool if kind=='bool' else _integer(value,
                1 if kind=='flag' else (8 if kind=='ordinal' else (128 if kind=='sample' else (2**64-1 if kind=='u64' else 0xffffffff))),
                1 if kind in ('pid','u64','ordinal') else 0))
            if valid:
                values.append(int(value))
        present = bool(values) and len(set(values))==1
        observed[key] = values[0] if present else 0
        if present: mask |= 1 << index
    value=dict(schemaVersion=version,kind=1,**context,moduleCode=module,caseCode=case,
        stageCode=STAGES.get(record.get('stage'),0) if type(record.get('stage')) is str else 0,
        **{key:failure[key] for key in ('exceptionCode','fileCode','line')},
        fieldPresenceMask=mask,observations=observed)
    if version>=2: value['ownedFrames']=frames
    if version==3: value['startup']=startup
    if version in (4,5): value['focus']=focus
    if version==5: value['foreground']=foreground
    if version==6: value['capture']=capture
    if version==7: value['captureGate']=capture_gate
    if version==8: value['readerGuard']=reader_guard
    if version==9: value['writerOs']=writer_os
    if version==10: value['keyboardLayout']=keyboard_layout
    return value


def capture_calc_snapshot(record, *, environ=None):
    environ = os.environ if environ is None else environ
    context = _context(environ)
    if (context is None or context['scopeCode']!=SCOPES['calc-dispatch'] or context['architecture']!=0xaa64
            or type(record) is not dict or record.get('kind')!='calc-save-dispatch-diagnostic'
            or record.get('module')!='calc'): return None
    value = _project_case('ime-calc',record,context,require_failure=False,environ=environ)
    if value is not None and _get(record,('calcDispatchDiagnostic','identity')) is None:
        for key in ('saveAttempted','saveReturned','savedMarkerObserved'):
            value['observations'][key]=0
            value['fieldPresenceMask'] &= ~(1<<OBSERVATION_NAMES.index(key))
    return value


def escape_data(value):
    return value.replace('%','%25').replace('\r','%0D').replace('\n','%0A')


def _unique(pairs):
    result = {}
    for key,value in pairs:
        if key in result: raise ValueError('Duplicate notice key')
        result[key]=value
    return result


def decode_notice(message, expected_source_commit, expected_run_id, *, title=CASE_TITLE,
                  expected_run_attempt=1, expected_architecture=None, expected_scope=None):
    if (type(expected_source_commit) is not str or not re.fullmatch('[0-9a-f]{40}',expected_source_commit)
            or not _integer(expected_run_id,2**63-1,1) or type(expected_run_attempt) is not int or expected_run_attempt!=1
            or (expected_architecture is not None and (type(expected_architecture) is not int or expected_architecture not in (0x8664,0xaa64)))
            or (expected_scope is not None and (type(expected_scope) is not int or expected_scope not in SCOPES.values()))):
        raise ValueError('Expected notice context is invalid')
    limit = {CASE_TITLE:MAX_CASE_BYTES,TRACE_TITLE:MAX_TRACE_BYTES}.get(title)
    if limit is None or type(message) is not str or len(message.encode('utf-8'))>limit: raise ValueError('Notice title/size rejected')
    value = json.loads(message,object_pairs_hook=_unique,parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite notice')))
    extended=title==CASE_TITLE and type(value) is dict and type(value.get('schemaVersion')) is int and value['schemaVersion'] in (2,3,4,5,6,7,8,9,10)
    keys = ({2:_CASE_KEYS_V2,3:_CASE_KEYS_V3,4:_CASE_KEYS_V4,5:_CASE_KEYS_V5,6:_CASE_KEYS_V6,7:_CASE_KEYS_V7,8:_CASE_KEYS_V8,9:_CASE_KEYS_V9,10:_CASE_KEYS_V10}[value['schemaVersion']] if extended else _CASE_KEYS) if title==CASE_TITLE else _TRACE_KEYS
    if type(value) is not dict or value.keys()!=keys: raise ValueError('Closed notice schema required')
    for key in value.keys()-{'sourceCommit','observations','diagnostic','oracleFlags','ownedFrames','startup','focus','foreground','capture','captureGate','readerGuard','writerOs','keyboardLayout'}:
        if not _integer(value[key],2**63-1): raise ValueError('Integer notice fields required')
    if (value['schemaVersion'] not in ((1,2,3,4,5,6,7,8,9,10) if title==CASE_TITLE else (1,)) or value['kind']!=(1 if title==CASE_TITLE else 2) or type(value['sourceCommit']) is not str
            or not re.fullmatch('[0-9a-f]{40}',value['sourceCommit']) or value['sourceCommit']=='0'*40
            or value['sourceCommit']!=expected_source_commit or value['runId']!=expected_run_id or value['runId']<=0
            or value['runAttempt']!=expected_run_attempt or value['runAttempt']!=1
            or value['architecture'] not in (0x8664,0xaa64)
            or (expected_architecture is not None and value['architecture']!=expected_architecture)
            or value['scopeCode'] not in SCOPES.values() or (expected_scope is not None and value['scopeCode']!=expected_scope)
            or not 1<=value['sequence']<=MAX_NOTICES or value['remainingBudget']!=MAX_NOTICES-value['sequence']
            ): raise ValueError('Notice identity/range differs')
    if title==TRACE_TITLE:
        if value['scopeCode']!=SCOPES['calc-dispatch'] or value['architecture']!=0xaa64 or value['oraclePresenceMask']>7:
            raise ValueError('Calc trace context differs')
        flags = value['oracleFlags']
        if type(flags) is not list or len(flags)!=3 or any(not _integer(v,1) for v in flags): raise ValueError('Closed oracle flags required')
        if any(not value['oraclePresenceMask'] & (1<<i) and flag for i,flag in enumerate(flags)): raise ValueError('Unknown oracle has a value')
        value['diagnostic'] = _decode_trace(value['diagnostic'])
        if value['diagnostic']['identity'] is None and (value['oraclePresenceMask'] or any(flags)):
            raise ValueError('Oracle lacks original native admission')
        return value
    fields=_FIELDS_V9 if value['schemaVersion'] in (9,10) else (_FIELDS_V3 if value['schemaVersion']==3 else (_FIELDS_V2 if extended else _FIELDS))
    if extended: value['ownedFrames']=validate_failure_frames(value['ownedFrames'])
    if (value['moduleCode'] not in (0,*MODULES.values()) or value['caseCode'] not in tuple(row[0] for row in CASES.values())
            or value['stageCode'] not in (0,*STAGES.values()) or value['exceptionCode'] not in (0,*EXCEPTIONS.values(),UNO_RUNTIME_EXCEPTION_CODE)
            or value['fileCode'] not in (0,*SOURCE_FILES.values())
            or (value['line']!=0 if value['fileCode']==0 else not 1<=value['line']<=10_000_000)
            or value['fieldPresenceMask'] >= 1<<len(fields)): raise ValueError('Notice identity/range differs')
    modules = {case:module for case,module in CASES.values()}
    if value['moduleCode']!=modules.get(value['caseCode'],0): raise ValueError('Notice module differs from its case')
    observations = value['observations']
    if type(observations) is not dict or observations.keys()!=set(row[0] for row in fields): raise ValueError('Closed notice observations required')
    for index,(key,kind,_) in enumerate(fields):
        maximum = 1 if kind in ('bool','flag') else (8 if kind=='ordinal' else (128 if kind=='sample' else (2**64-1 if kind=='u64' else 0xffffffff)))
        if (not _integer(observations[key],maximum) or
                (kind in ('pid','u64','ordinal') and value['fieldPresenceMask'] & (1<<index) and observations[key]==0) or
                (not value['fieldPresenceMask'] & (1<<index) and observations[key]!=0)):
            raise ValueError('Notice observation type/presence differs')
    if value['schemaVersion']==2 and not value['ownedFrames'] and not value['fieldPresenceMask'] & (3<<len(_FIELDS)):
        raise ValueError('Extended case notice lacks observed frames or progress')
    if value['schemaVersion']==3:
        mode_mask=value['fieldPresenceMask'] & (31<<len(_FIELDS_V2))
        if (not _valid_startup(value['startup']) or mode_mask not in (0,31<<len(_FIELDS_V2))
                or (mode_mask and not _valid_mode_summary({key:observations[key] for key in _MODE_NAMES}))
                or (not mode_mask and not value['startup'][0])):
            raise ValueError('Mode samples or observed startup tuple required')
    if value['schemaVersion'] in (4,5) and (not _valid_focus(value['focus'])
            or not _focus_context(value['caseCode'],value['stageCode'],value)
            or (value['stageCode']==STAGES['focus-editor'])!=(value['focus'][3]==121)):
        raise ValueError('Bounded existing-focus context required')
    if value['schemaVersion']==5 and (value['scopeCode']!=SCOPES['calc-dispatch'] or value['architecture']!=0xaa64
            or value['caseCode']!=CASES['ime-calc'][0] or not _valid_foreground(value['foreground'],value['focus'])):
        raise ValueError('Bounded existing-foreground Calc context required')
    if value['schemaVersion']==6 and (not _valid_capture(value['capture'])
            or not _capture_context(value['caseCode'],value['stageCode'],value)
            or value['exceptionCode']!=1 or value['fileCode']!=1 or not value['ownedFrames']
            or value['ownedFrames'][-1]!=[value['fileCode'],value['line']]
            or not any(row[0]==SOURCE_FILES['writer_style_smoke.py'] for row in value['ownedFrames'][:-1])):
        raise ValueError('Bounded original Writer capture rejection required')
    if value['schemaVersion']==7 and (not _valid_capture_gate(value['captureGate'])
            or not _capture_context(value['caseCode'],value['stageCode'],value)
            or value['exceptionCode']!=1 or value['fileCode']!=24 or not value['ownedFrames']
            or value['ownedFrames'][-1]!=[24,value['line']]
            or [row[0] for row in value['ownedFrames']]!=[6,13,13,13,13,13,24]):
        raise ValueError('Bounded original Writer pre-insertion capture deadline required')
    if value['schemaVersion']==8 and (not _valid_reader_guard(value['readerGuard'])
            or value['readerGuard'][0] != _reader_guard_context(value['caseCode'],
                value['stageCode'],value,value,value['ownedFrames'])
            or not _reader_guard_site(value['readerGuard'],value)):
        raise ValueError('Bounded original reader guard failure required')
    if value['schemaVersion']==9:
        if not _writer_os_site(value['caseCode'],value['moduleCode'],value['stageCode'],
                value,value,value['ownedFrames'],value['writerOs']):
            raise ValueError('Bounded original Writer OS failure required')
        for key, slot in (('enginePid',3),('officeCreationTime',4),('childHwnd',5)):
            if (not value['fieldPresenceMask'] & (1<<OBSERVATION_NAMES_V9.index(key))
                    or observations[key] != value['writerOs'][slot]):
                raise ValueError('Writer OS retained process identity differs')
    if value['schemaVersion']==10:
        if not _keyboard_layout_site(value['caseCode'],value['moduleCode'],value,
                value,value['ownedFrames'],value['keyboardLayout']):
            raise ValueError('Bounded original keyboard layout guard required')
        for key,slot in (('enginePid',2),('officeCreationTime',3),('childHwnd',4)):
            if (not value['fieldPresenceMask'] & (1<<OBSERVATION_NAMES_V9.index(key))
                    or observations[key] != value['keyboardLayout'][slot]):
                raise ValueError('Keyboard layout retained process identity differs')
    return value


def _decode_trace(value):
    if __package__:
        from .calc_dispatch_diagnostic import decode_artifact
    else:
        from calc_dispatch_diagnostic import decode_artifact
    return decode_artifact(value)


class NoticeEmitter:
    def __init__(self, *, environ=None, stream=None):
        self.environ, self.stream = environ, stream
        self.count = 0; self.seen = set(); self.per_case = {}

    def emit_case_notice(self, name, record):
        try:
            value = project_case_notice(name,record,environ=self.environ)
            if value is None: return False
            return self._emit(CASE_TITLE,value,value['caseCode'])
        except Exception:
            return False

    def _emit(self, title, value, key):
        try:
            signature = json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)
            if self.count>=MAX_NOTICES or self.per_case.get(key,0)>=2 or signature in self.seen: return False
            value.update(sequence=self.count+1,remainingBudget=MAX_NOTICES-self.count-1)
            message = json.dumps(value,separators=(',',':'),allow_nan=False)
            decode_notice(message,value['sourceCommit'],value['runId'],title=title,expected_architecture=value['architecture'])
            # Count attempts before I/O: a broken pipe must not trigger a retry.
            self.count += 1; self.per_case[key] = self.per_case.get(key,0)+1; self.seen.add(signature)
            print('::notice title='+title+'::'+escape_data(message),file=self.stream or sys.stdout,flush=True)
            return True
        except Exception:
            return False

    def emit_calc_report(self, report):
        try:
            environ = os.environ if self.environ is None else self.environ
            context = _context(environ)
            if context is None or context['scopeCode']!=SCOPES['calc-dispatch'] or context['architecture']!=0xaa64: return 0
            if (type(report) is not dict or type(report.get('schemaVersion')) is not int or report['schemaVersion']!=1
                    or report.get('kind')!='calc-save-dispatch-diagnostic' or report.get('acceptanceEligible') is not False
                    or report.get('fullEngineQualified') is not False or report.get('imeVerified') is not False
                    or type(report.get('success')) is not bool): return 0
            binding = report.get('runBinding')
            if (type(binding) is not dict or binding.get('sourceCommit')!=context['sourceCommit']
                    or binding.get('runId')!=str(context['runId']) or binding.get('runAttempt')!='1'
                    or binding.get('architecture')!='arm64'): return 0
            trace = _decode_trace(report['diagnostic']) if report.get('diagnostic') is not None else None
            flags, mask = [0,0,0], 0
            oracle = report.get('originalSaveOracle') if report.get('numericOracleObserved') is True and trace is not None and trace['identity'] is not None else None
            for index,key in enumerate(('saveAttempted','saveReturned','savedMarkerObserved')):
                item = _get(oracle,(key,))
                if type(item) is bool: flags[index]=int(item); mask |= 1<<index
            adapted = dict(diagnosticRunnerPassed=report['success'])
            if oracle is not None: adapted['calcDispatchOracle']=oracle
            if trace is not None and trace['identity'] is not None:
                adapted.update(officePid=trace['identity']['ownerPid'],officeCreationTime=trace['identity']['ownerCreated'])
                if trace['state'] is not None: adapted['calcDispatchDiagnostic']=trace
                if trace['exit']['observed']: adapted['processExitProved']=trace['analysis']['processExitProved']
            value = _project_case('ime-calc',adapted,context,require_failure=False,environ=environ)
            snapshot = report.get('numericCaseSnapshot')
            if snapshot is not None:
                checked = dict(snapshot,sequence=1,remainingBudget=MAX_NOTICES-1)
                checked = decode_notice(json.dumps(checked,separators=(',',':')),context['sourceCommit'],context['runId'],
                    expected_architecture=0xaa64,expected_scope=SCOPES['calc-dispatch'])
                if checked['caseCode']!=CASES['ime-calc'][0]: return 0
                if checked['schemaVersion']==5 and not _foreground_enabled(context,environ):
                    checked.pop('foreground');checked['schemaVersion']=4
                checked.pop('sequence'); checked.pop('remainingBudget')
                # Only explicit source-case fields can describe local cleanup,
                # exception location or stage. Final fallback defaults cannot.
                for index,key in enumerate(OBSERVATION_NAMES):
                    if value['fieldPresenceMask'] & (1<<index):
                        checked['observations'][key]=value['observations'][key]
                        checked['fieldPresenceMask'] |= 1<<index
                value = checked
            for index,key in enumerate(('saveAttempted','saveReturned','savedMarkerObserved')):
                bit=1<<OBSERVATION_NAMES.index(key)
                value['fieldPresenceMask'] &= ~bit
                value['observations'][key]=0
                if mask & (1<<index):
                    value['observations'][key]=flags[index]; value['fieldPresenceMask'] |= bit
            count = int(self._emit(CASE_TITLE,value,CASES['ime-calc'][0]))
            if trace is not None and environ.get(TRACE_OPT_IN)=='1':
                value = dict(schemaVersion=1,kind=2,**context,diagnostic=trace,oracleFlags=flags,oraclePresenceMask=mask)
                count += int(self._emit(TRACE_TITLE,value,CASES['ime-calc'][0]))
            return count
        except Exception:
            return 0


_EMITTER = NoticeEmitter()


def emit_case_notice(name, record):
    return _EMITTER.emit_case_notice(name,record)


def emit_calc_report(report):
    return _EMITTER.emit_calc_report(report)
