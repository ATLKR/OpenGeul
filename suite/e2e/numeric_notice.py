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
# Extend numeric identifiers at the end so earlier run notices keep their meaning.
SCOPES = {'calc-close':1,'home-routes':2,'korean-ime':3,'korean-ui':4,'writer-style':5,
          'lifecycle':6,'native-first':7,'native-second':8,'calc-dispatch':9,'native-integrity':10}
MAX_CASE_BYTES, MAX_TRACE_BYTES, MAX_NOTICES = 2048, 32768, 8
EXCEPTIONS = {kind: index for index, kind in enumerate((AssertionError, TimeoutError,
    PermissionError, FileNotFoundError, FileExistsError, OSError, ValueError, TypeError,
    RuntimeError, KeyError, AttributeError, NotImplementedError), 1)}
SOURCE_FILES = {name: index for index, name in enumerate((
    'windows_smoke.py', 'calc_close_probe.py', 'home_routing_smoke.py', 'korean_ime_smoke.py',
    'korean_ui_smoke.py', 'writer_style_smoke.py', 'lifecycle_smoke.py', 'writer_model_reader.py',
    'writer_model_barrier.py', 'calc_model_barrier.py', 'ime_keyboard_session.py',
    'ime_engine_retirement.py', 'scenario_editor_shortcuts.py', 'counted_editor_shortcuts.py',
    'owned_control_actions.py', 'owned_save_menu.py', 'native_window_evidence.py',
    'ime_calc_setup.py', 'native_accessibility.py', 'calc_dispatch_diagnostic.py',
    'ime_semantic_context.py', 'calc_pending_input.py', 'native_archive_completeness.py'), 1)}
_OWNED_FILES = {os.path.normcase(str(Path(__file__).with_name(name))): code for name, code in SOURCE_FILES.items()}
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
    ('hwp-tile-hwpx-route','hwp'), ('lifecycle-summary',''), ('native-integrity',''))
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
    'verify-native-archives')
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
_COMMON = {'schemaVersion','kind','sourceCommit','runId','runAttempt','architecture','scopeCode','sequence','remainingBudget'}
_CASE_KEYS = _COMMON | {'moduleCode','caseCode','stageCode','exceptionCode','fileCode','line',
                       'fieldPresenceMask','observations'}
_FAILURE_KEYS = {'captured','exceptionCode','fileCode','line'}
_TRACE_KEYS = _COMMON | {'diagnostic','oracleFlags','oraclePresenceMask'}


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
    if isinstance(exc,BaseException):
        raw = vars(exc).get('raw')
        numeric = _get(raw,('error','numericFailure'))
        try:
            return validate_failure_code(numeric)
        except ValueError:
            pass
    result = dict(captured=int(isinstance(exc,BaseException)),exceptionCode=EXCEPTIONS.get(type(exc),0),fileCode=0,line=0)
    trace = exc.__traceback__ if isinstance(exc,BaseException) else None
    for _ in range(64):
        if trace is None: break
        code = _OWNED_FILES.get(os.path.normcase(trace.tb_frame.f_code.co_filename))
        if code and _integer(trace.tb_lineno,10_000_000,1): result.update(fileCode=code,line=trace.tb_lineno)
        trace = trace.tb_next
    return result


def _failure(value):
    return (type(value) is dict and value.keys()==_FAILURE_KEYS and value['captured']==1
        and all(type(v) is int for v in value.values()) and value['exceptionCode'] in (0,*EXCEPTIONS.values())
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
    context = _context(os.environ if environ is None else environ)
    if context is None or type(record) is not dict: return None
    return _project_case(name,record,context,require_failure=True)


def _project_case(name, record, context, *, require_failure):
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
    observed, mask = {}, 0
    for index,(key,kind,paths) in enumerate(_FIELDS):
        values = []
        for path in paths:
            value = _get(record,path)
            if key=='shellCleanupExitCode' and _get(record,('calcDispatchShell','shellExitObserved')) is not True: value=None
            if kind=='count': value = len(value) if type(value) is list else None
            valid = (type(value) is bool if kind=='bool' else _integer(value,
                1 if kind=='flag' else (2**64-1 if kind=='u64' else 0xffffffff),
                1 if kind in ('pid','u64') else 0))
            if valid:
                values.append(int(value))
        present = bool(values) and len(set(values))==1
        observed[key] = values[0] if present else 0
        if present: mask |= 1 << index
    return dict(schemaVersion=1,kind=1,**context,moduleCode=module,caseCode=case,
        stageCode=STAGES.get(record.get('stage'),0) if type(record.get('stage')) is str else 0,
        **{key:failure[key] for key in ('exceptionCode','fileCode','line')},
        fieldPresenceMask=mask,observations=observed)


def capture_calc_snapshot(record, *, environ=None):
    context = _context(os.environ if environ is None else environ)
    if (context is None or context['scopeCode']!=SCOPES['calc-dispatch'] or context['architecture']!=0xaa64
            or type(record) is not dict or record.get('kind')!='calc-save-dispatch-diagnostic'
            or record.get('module')!='calc'): return None
    value = _project_case('ime-calc',record,context,require_failure=False)
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
    keys = _CASE_KEYS if title==CASE_TITLE else _TRACE_KEYS
    if type(value) is not dict or value.keys()!=keys: raise ValueError('Closed notice schema required')
    for key in value.keys()-{'sourceCommit','observations','diagnostic','oracleFlags'}:
        if not _integer(value[key],2**63-1): raise ValueError('Integer notice fields required')
    if (value['schemaVersion']!=1 or value['kind']!=(1 if title==CASE_TITLE else 2) or type(value['sourceCommit']) is not str
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
    if (value['moduleCode'] not in (0,*MODULES.values()) or value['caseCode'] not in tuple(row[0] for row in CASES.values())
            or value['stageCode'] not in (0,*STAGES.values()) or value['exceptionCode'] not in (0,*EXCEPTIONS.values())
            or value['fileCode'] not in (0,*SOURCE_FILES.values())
            or (value['line']!=0 if value['fileCode']==0 else not 1<=value['line']<=10_000_000)
            or value['fieldPresenceMask'] >= 1<<len(_FIELDS)): raise ValueError('Notice identity/range differs')
    modules = {case:module for case,module in CASES.values()}
    if value['moduleCode']!=modules.get(value['caseCode'],0): raise ValueError('Notice module differs from its case')
    observations = value['observations']
    if type(observations) is not dict or observations.keys()!=set(OBSERVATION_NAMES): raise ValueError('Closed notice observations required')
    for index,(key,kind,_) in enumerate(_FIELDS):
        maximum = 1 if kind in ('bool','flag') else (2**64-1 if kind=='u64' else 0xffffffff)
        if (not _integer(observations[key],maximum) or
                (kind in ('pid','u64') and value['fieldPresenceMask'] & (1<<index) and observations[key]==0) or
                (not value['fieldPresenceMask'] & (1<<index) and observations[key]!=0)):
            raise ValueError('Notice observation type/presence differs')
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
            value = _project_case('ime-calc',adapted,context,require_failure=False)
            snapshot = report.get('numericCaseSnapshot')
            if snapshot is not None:
                checked = dict(snapshot,sequence=1,remainingBudget=MAX_NOTICES-1)
                checked = decode_notice(json.dumps(checked,separators=(',',':')),context['sourceCommit'],context['runId'],
                    expected_architecture=0xaa64,expected_scope=SCOPES['calc-dispatch'])
                if checked['caseCode']!=CASES['ime-calc'][0]: return 0
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
