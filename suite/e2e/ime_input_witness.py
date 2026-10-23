"""Explicit diagnostic IME hook witness; never Office replacement qualification.

The production observer, commands, ABI, budgets, keys and predicates are unchanged
on disk. Extra readonly hook calls can perturb timing and IMM bookkeeping. Entry
LastError is restored; raw per-query errors may be stale. Samples precede
downstream handling and do not observe TSF compartments.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys


BASE_SOURCE_SHA256 = 'd5f0a4730aad7fbe37930e8e2db7f1e82fcf224b758b235e9d8c4d4dc2de03cd'
DIAGNOSTIC_MESSAGES = frozenset((0x100, 0x101, 0x102, 0x51, 0x281))
NATIVE_WITNESS_SOURCE = r'''
static bool input_witness_message(UINT message) {
    return message==WM_KEYDOWN || message==WM_KEYUP || message==WM_CHAR
        || message==WM_INPUTLANGCHANGE || message==WM_IME_SETCONTEXT;
}
static void input_witness(HWND hwnd,UINT message,WPARAM wp,LPARAM lp,UINT origin) {
    struct RestoreEntryLastError {
        DWORD value;
        ~RestoreEntryLastError() { SetLastError(value); }
    } restoreEntryLastError{GetLastError()};
    DWORD pid=0;
    if(GetWindowThreadProcessId(hwnd,&pid)!=shared->tid || pid!=shared->pid) return;
    LONG index=InterlockedIncrement(&shared->count)-1;
    if(index<0 || index>=512) { InterlockedExchange(&shared->overflow,1); return; }
    Event* event=&shared->events[index];
    event->message=message;event->flags=(uint32_t)lp;event->pid=pid;event->tid=GetCurrentThreadId();
    event->hwnd=(uint64_t)(UINT_PTR)hwnd;event->layout=(uint64_t)(UINT_PTR)GetKeyboardLayout(0);event->origin=origin;
    LARGE_INTEGER counter={},frequency={};
    const int counterOk=QueryPerformanceCounter(&counter);
    const int frequencyOk=QueryPerformanceFrequency(&frequency);
    HIMC context=ImmGetContext(hwnd);const DWORD contextError=GetLastError();
    int opened=0,converted=0,released=0;DWORD openError=0,conversionError=0,releaseError=0,conversion=0,sentence=0;
    if(context) {
        opened=ImmGetOpenStatus(context);openError=GetLastError();
        converted=ImmGetConversionStatus(context,&conversion,&sentence);conversionError=GetLastError();
        released=ImmReleaseContext(hwnd,context);releaseError=GetLastError();
    }
    char openText[16]="null",openErrorText[16]="null",convertedText[16]="null";
    char conversionText[16]="null",sentenceText[16]="null",conversionErrorText[16]="null";
    char releasedText[16]="null",releaseErrorText[16]="null";
    if(context) {
        snprintf(openText,sizeof(openText),"%d",opened);
        snprintf(openErrorText,sizeof(openErrorText),"%lu",(unsigned long)openError);
        snprintf(convertedText,sizeof(convertedText),"%d",converted);
        snprintf(conversionErrorText,sizeof(conversionErrorText),"%lu",(unsigned long)conversionError);
        snprintf(releasedText,sizeof(releasedText),"%d",released);
        snprintf(releaseErrorText,sizeof(releaseErrorText),"%lu",(unsigned long)releaseError);
        if(converted) {
            snprintf(conversionText,sizeof(conversionText),"%lu",(unsigned long)conversion);
            snprintf(sentenceText,sizeof(sentenceText),"%lu",(unsigned long)sentence);
        }
    }
    char payload[256]={};
    const int length=snprintf(payload,sizeof(payload),
        "{\"v\":1,\"w\":\"%llu\",\"l\":\"%lld\",\"q\":[%d,\"%lld\",%d,\"%lld\"],\"h\":\"%llu\",\"i\":[%lu,%s,%s,%s,%s,%s,%s,%s,%s]}",
        (unsigned long long)wp,(long long)lp,counterOk,(long long)counter.QuadPart,
        frequencyOk,(long long)frequency.QuadPart,(unsigned long long)(UINT_PTR)context,
        (unsigned long)contextError,openText,openErrorText,convertedText,conversionText,sentenceText,
        conversionErrorText,releasedText,releaseErrorText);
    // Fail closed before publication; composition[256] remains the original ABI.
    if(length<0 || length>=256 || length*2>=512) { InterlockedExchange(&shared->overflow,1); return; }
    for(int i=0;i<length;++i) event->composition[i]=(WCHAR)(unsigned char)payload[i];
    event->composition[length]=0;event->compositionBytes=length*2;event->resultBytes=0;
    MemoryBarrier();InterlockedExchange((volatile LONG*)&event->sequence,index+1);
}
'''

_INCLUDE = '#include <stdint.h>\n'
_OBSERVE = 'static void observe(HWND hwnd,UINT message,WPARAM wp,LPARAM lp,UINT origin) {'
_FILTER = '    if (message!=WM_IME_STARTCOMPOSITION && message!=WM_IME_ENDCOMPOSITION && message!=WM_IME_COMPOSITION) return;'
_BRANCH = '    if(input_witness_message(message)) { input_witness(hwnd,message,wp,lp,origin); return; }\n'


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def instrument_source(source):
    assert type(source) is str and _sha(source.encode()) == BASE_SOURCE_SHA256, 'Production observer source drifted'
    changes = ((_INCLUDE, _INCLUDE + '#include <stdio.h>\n'),
               (_OBSERVE, NATIVE_WITNESS_SOURCE + '\n' + _OBSERVE),
               (_FILTER, _BRANCH + _FILTER))
    generated, replacements = source, []
    for old, new in changes:
        assert generated.count(old) == 1, 'Diagnostic source anchor is absent or ambiguous'
        replacements.append(dict(anchorSha256=_sha(old.encode()), count=1))
        generated = generated.replace(old, new, 1)
    assert remove_instrumentation(generated) == source
    return generated, dict(originalSourceSha256=BASE_SOURCE_SHA256,
                           instrumentedTemplateSha256=_sha(generated.encode()), replacements=replacements,
                           diagnosticOnly=True, abiChanged=False, eventCapacity=512, payloadUtf16BytesExclusiveLimit=512)


def remove_instrumentation(source):
    for old, new in reversed(((_INCLUDE, _INCLUDE + '#include <stdio.h>\n'),
                              (_OBSERVE, NATIVE_WITNESS_SOURCE + '\n' + _OBSERVE),
                              (_FILTER, _BRANCH + _FILTER))):
        assert source.count(new) == 1, 'Diagnostic source replacement drifted'
        source = source.replace(new, old, 1)
    return source


def _integer(value, low, high):
    assert type(value) is int and low <= value <= high, 'Diagnostic integer differs from native width'
    return value


def _decimal(value, low, high):
    assert type(value) is str and re.fullmatch(r'0|-?[1-9][0-9]{0,19}', value), 'Noncanonical native decimal'
    return _integer(int(value), low, high)


def partition_events(rows):
    composition, witnesses = [], []
    for row in rows:
        if row['message'] not in DIAGNOSTIC_MESSAGES:
            composition.append(row)  # Keep every original row and its native sequence unchanged.
            continue
        raw = row['composition']
        assert type(raw) is str and raw.isascii() and len(raw.encode('utf-16-le')) < 512
        value = json.loads(raw)
        assert type(value) is dict and set(value) == {'v', 'w', 'l', 'q', 'h', 'i'} and type(value['v']) is int and value['v'] == 1
        q, imm = value['q'], value['i']
        assert type(q) is list and len(q) == 4 and type(imm) is list and len(imm) == 9
        for n in (0, 2): _integer(q[n], -2**31, 2**31-1)
        for n in (1, 3): _decimal(q[n], -2**63, 2**63-1)
        context = _decimal(value['h'], 0, 2**64-1)
        _integer(imm[0], 0, 2**32-1)
        if context:
            for n in (1, 3, 7): _integer(imm[n], -2**31, 2**31-1)
            for n in (2, 6, 8): _integer(imm[n], 0, 2**32-1)
            if imm[3]:
                for n in (4, 5): _integer(imm[n], 0, 2**32-1)
            else: assert imm[4:6] == [None, None], 'Failed getter has no observed conversion values'
        else: assert imm[1:] == [None] * 8, 'Absent HIMC cannot claim getter calls'
        assert row['origin'] in ('sent', 'posted')
        witnesses.append(dict(row, nativeSequence=row['sequence'], rawPayload=raw,
            wParam=_decimal(value['w'], 0, 2**64-1), lParam=_decimal(value['l'], -2**63, 2**63-1),
            qpc=dict(counterResult=q[0], counter=_decimal(q[1], -2**63, 2**63-1),
                     frequencyResult=q[2], frequency=_decimal(q[3], -2**63, 2**63-1)),
            himc=context, imm=dict(contextLastError=imm[0], open=imm[1], openLastError=imm[2],
                conversionSucceeded=imm[3], conversion=imm[4], sentence=imm[5], conversionLastError=imm[6],
                releaseSucceeded=imm[7], releaseLastError=imm[8]),
            scope=('WH_CALLWNDPROC-before-CallNextHookEx' if row['origin'] == 'sent'
                   else 'WH_GETMESSAGE-PM_REMOVE-before-CallNextHookEx'),
            rawLastErrorMayBeStale=True, tsfStateObserved=False, diagnosticOnly=True))
    return composition, witnesses


def diagnostic_report(original):
    report = copy.deepcopy(original)
    report.update(kind='native-ime-input-witness-diagnostic', diagnosticOnly=True,
                  productionCaseOutcomeObserved=original.get('success') is True,
                  success=False, imeVerified=False, officeReplacementCertified=False,
                  mainNativePrivacySetupPerformed=False, diagnosticPreparationSeparatelyRecorded=True,
                  diagnosticPreparationEvidence='.work/suite-input-witness-preparation/', privacyPreparationQualified=False,
                  hostReadyQualified=False, productQualified=False, qualification=False)
    return report


def _file_pin(path):
    raw = path.read_bytes()
    return dict(path=str(path), bytes=len(raw), sha256=_sha(raw))


def _observer_class(production):
    class DiagnosticObserver(production.CompositionObserver):
        def __init__(self, api, root, child, focus, pid, folder, profile, **kwargs):
            self.witness_folder = Path(folder)
            self.witness_rows, self.native_rows = [], []
            self.witness_close_started = False
            super().__init__(api, root, child, focus, pid, folder, profile, **kwargs)

        def events(self):
            rows = super().events()  # Original acquire/copy, overflow and completed-prefix checks.
            composition, witness = partition_events(rows)
            self.native_rows, self.witness_rows = rows, witness
            return composition

        def close(self):
            if self.witness_close_started: return
            self.witness_close_started = True
            primary = sys.exc_info()[1]
            snapshot, failure = None, None
            try:
                if getattr(self, 'mapping', None) is not None and hasattr(self, 'dll'):
                    state = self.state()
                    snapshot = dict(count=int(state.count), overflow=int(state.overflow),
                        snapshotEvidence=state.snapshotEvidence, nativeStateBytesHex=bytes(state).hex())
                    self.events()  # Retain fatal overflow/decoding behavior, including final snapshot.
            except BaseException as exc:
                failure = exc
            cleanup_failure = persistence_failure = None
            try:
                super().close()
            except BaseException as exc:
                cleanup_failure = exc
            try:
                if self.witness_folder.is_dir():
                    report = dict(schemaVersion=1, kind='pre-downstream-native-input-witness',
                        diagnosticOnly=True, success=False, officeReplacementCertified=False,
                        mainNativePrivacySetupPerformed=False, diagnosticPreparationSeparatelyRecorded=True,
                        diagnosticPreparationEvidence='.work/suite-input-witness-preparation/', qualification=False,
                        nativeRows=self.native_rows, witnessRows=self.witness_rows, beforeUnhookNativeSnapshot=snapshot,
                        nativeRowsAndRawSnapshotAreSeparateAcquireCopies=True,
                        snapshotError=None if failure is None else type(failure).__name__ + ': ' + str(failure),
                        originalCleanupError=None if cleanup_failure is None else type(cleanup_failure).__name__ + ': ' + str(cleanup_failure),
                        limits=['Readonly IMM queries may perturb bookkeeping and timing; entry LastError is restored and per-query raw errors may be stale.',
                                'Samples precede downstream handling; they do not observe TSF state.',
                                'Diagnostic rows share original cap512; overflow remains fatal.',
                                'Original composition rows and native sequence gaps are never rewritten.'])
                    source = self.witness_folder / 'ime-observer.cpp'
                    if source.is_file(): report['compiledSource'] = _file_pin(source)
                    (self.witness_folder / 'input-witness.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            except BaseException as exc:
                persistence_failure = exc
            for error in (cleanup_failure, failure, persistence_failure):
                if error is not None:
                    if primary is None: raise error
                    print('Diagnostic cleanup error; original exception preserved: ' + type(error).__name__ + ': ' + str(error), file=sys.stderr)
    return DiagnosticObserver


def run_diagnostic(production, argv, output, binding):
    assert not output.exists() and not output.is_symlink() and not getattr(output, 'is_junction', lambda: False)(), 'Diagnostic output must be fresh'
    original_source, original_observer = production.OBSERVER_SOURCE, production.CompositionObserver
    generated, audit = instrument_source(original_source)
    original_exception = None
    code = 1
    try:
        production.OBSERVER_SOURCE = generated
        production.CompositionObserver = _observer_class(production)
        code = production.main(argv)  # All three original cases, readiness, ASCII preparation and guards.
        return code
    except BaseException as exc:
        original_exception = exc
        raise
    finally:
        production.OBSERVER_SOURCE, production.CompositionObserver = original_source, original_observer
        if output.is_dir() and not isinstance(original_exception, FileExistsError):
            report_file = output / 'results.json'
            try:
                report_error = None
                if report_file.is_file():
                    (output / 'production-case-results.json').write_bytes(report_file.read_bytes())
                    try:
                        original = json.loads(report_file.read_text(encoding='utf-8'))
                        assert type(original) is dict
                    except BaseException as exc:
                        original, report_error = {}, exc
                else:
                    original = {}
                    if original_exception is None: report_error = AssertionError('Original case report is absent')
                report = diagnostic_report(original)
                report.update(sourceBinding=binding, instrumentation=audit, productionExitCode=code,
                    error=None if original_exception is None else type(original_exception).__name__ + ': ' + str(original_exception),
                    originalReportError=None if report_error is None else type(report_error).__name__ + ': ' + str(report_error),
                    generatedSources=[_file_pin(path) for path in sorted(output.glob('ime-*/ime-observer.cpp'))])
                encoded = json.dumps(report, ensure_ascii=False, indent=2)
                (output / 'input-witness-diagnostic.json').write_text(encoded, encoding='utf-8')
                report_file.write_text(encoded, encoding='utf-8')
                if report_error is not None and original_exception is None: raise report_error
            except BaseException:
                if original_exception is None: raise
                print('Diagnostic report persistence failed; original failure preserved', file=sys.stderr)


def source_binding(environment, repository):
    required = ('GITHUB_SHA', 'GITHUB_REF', 'GITHUB_WORKFLOW_REF', 'GITHUB_WORKFLOW',
                'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'GITHUB_JOB', 'GITHUB_REPOSITORY')
    binding = {key: environment.get(key) for key in required}
    assert environment.get('GITHUB_ACTIONS') == 'true' and environment.get('RUNNER_OS') == 'Windows'
    assert all(type(value) is str and value for value in binding.values())
    assert re.fullmatch('[0-9a-f]{40}', binding['GITHUB_SHA'])
    assert binding['GITHUB_REF'] == 'refs/heads/work/native35-arm64-input-witness'
    assert binding['GITHUB_WORKFLOW_REF'] == binding['GITHUB_REPOSITORY'] + '/.github/workflows/suite-native35-input-witness.yml@' + binding['GITHUB_REF']
    head = subprocess.run(['git', '-C', str(repository), 'rev-parse', 'HEAD'], capture_output=True, text=True, check=True).stdout.strip()
    assert head == binding['GITHUB_SHA'], 'Diagnostic checkout differs from actual hosted source'
    files = []
    for name in ('ime_input_witness.py', 'korean_ime_smoke.py'):
        path = Path(__file__).with_name(name)
        committed = subprocess.run(['git', '-C', str(repository), 'cat-file', 'blob', head + ':suite/e2e/' + name], capture_output=True, check=True).stdout
        assert path.read_bytes() == committed, 'Diagnostic executable source differs from committed bytes'
        files.append(_file_pin(path))
    return dict(binding, gitHead=head, sourceFiles=files, diagnosticOnly=True,
                mainNativePrivacySetupPerformed=False, diagnosticPreparationSeparatelyRecorded=True,
                diagnosticPreparationEvidence='.work/suite-input-witness-preparation/')


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('suite', 'fixtures', 'readiness', 'output'): parser.add_argument('--' + flag, type=Path, required=True)
    args = parser.parse_args(argv)
    if os.name != 'nt' or not __debug__: raise RuntimeError('Native Windows diagnostic requires assertions')
    binding = source_binding(os.environ, Path(__file__).resolve().parents[2])
    import korean_ime_smoke as production
    return run_diagnostic(production, argv, args.output.resolve(), binding)


if __name__ == '__main__': raise SystemExit(main())
