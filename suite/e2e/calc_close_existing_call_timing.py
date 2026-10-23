"""Unqualified parent-only timing of the unchanged three CalcClose cases.

No helper, input, getter, durability or deadline policy is changed. New timing
data stays in bounded parent memory until the original main has unwound.
"""
from __future__ import annotations

import argparse
import ast
import copy
import functools
import hashlib
import importlib
import inspect
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time
import traceback
import types


PRIVATE_INVOKE = '_native35_existing_call_timing_invoke'
MAX_EVENTS = 2048
MAX_STACK = 32
MAX_REPORT_BYTES = 2 * 1024 * 1024
OUTSIDE_SEQUENCE = 123
LABELS = (
    'case.run', 'reader.start', 'reader.read', 'reader.rpc', 'reader.census',
    'reader.members', 'reader.close', 'native.anchor', 'python.verify',
    'python.file', 'json.read', 'json.atomic', 'shortcut.retain',
    'atomic.serialize', 'atomic.encode', 'atomic.open', 'atomic.write',
    'atomic.flush', 'atomic.fsync', 'atomic.replace', 'shortcut.serialize',
    'shortcut.encode', 'shortcut.open', 'shortcut.write', 'shortcut.flush',
    'shortcut.fsync',
)
SOURCE_PINS = {
    'suite/e2e/calc_close_probe.py': (23882, '3c2bc1093f150f0bb58b771ef40e5461102b973bbca6a61521335dd88e9d7000'),
    'suite/e2e/calc_save_smoke.py': (30767, 'f89a332409ef3403f072c896b62c45414936903e12492045fc1e0d993c307d11'),
    'suite/e2e/counted_editor_shortcuts.py': (22973, '05c4486c5ae29c00a0209528fa5e9d2c8c0177a731732b6421e148648a69e8cb'),
    'suite/e2e/scenario_editor_shortcuts.py': (29929, 'dedf0966b55a4518ee4c6e66af593d7175d85a4b2446ede97b34eeeebe7fbaa5'),
    'suite/e2e/writer_model_reader.py': (124442, 'edb113fca6da2a582a03a241d427f20dde0422b6362b597828222bc54eed5dd7'),
    'suite/e2e/writer_style_smoke.py': (26159, 'd05397e42231163171d05d537f4aa22b82b4d61bd59bd2937e66ba7b9745689c'),
    'suite/e2e/windows_smoke.py': (89112, 'cfa4a6a8ec41ab43009beb59bf57f44e3499a76f2e5f8273b92cbc12a8b064ef'),
    'suite/e2e/ascii_editor_input.py': (11600, '76bc69bc9824e7a421a3b2af6aac26c4428a9b40dd2990c3eace7fb815c75e86'),
    'suite/e2e/ascii_message_observer.py': (10563, '4f3b826fc211d496121a5711d6f8c529342c67b515ff60f52e33299f3d987f08'),
    'suite/e2e/calc_pending_input.py': (27109, '7de34a28a3432ca6966aec4d6b4e5529cca5a97f0deb25d9e658426dc2451ac9'),
    'suite/e2e/calc_model_barrier.py': (19055, 'ffb6420b5522e2699369672e4d2a69f50c73a18a6ba2bb4c9166fb09d70bf4d1'),
}
IO_AST_PINS = {
    'atomic': '1262b04d1bb23bbbd6281e487d2fb431415d2e8b466b350f0c49037b774f70a7',
    'shortcut': '9b0d305c7150356b7faee94a56fd8568baecca8be8c5d6c5aafb66149bacc983',
}


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _ast_sha(node):
    return _sha(ast.dump(node, include_attributes=False).encode('utf-8'))


class TimingCollector:
    """Only fixed scalar stores are touched while the original main runs."""
    def __init__(self, *, clock=time.monotonic_ns, event_limit=MAX_EVENTS):
        assert type(event_limit) is int and 1 <= event_limit <= MAX_EVENTS
        self.clock, self.event_limit = clock, event_limit
        self.events = [[0] * 10 for _ in range(event_limit)]
        self.stack = [[0] * 9 for _ in range(MAX_STACK)]
        # case(3) * phase(3) * sequence(124) * hot labels(2).
        self.hot = [[0] * 6 for _ in range(2232)]
        self.used = self.depth = self.flags = 0
        self.case, self.phase, self.sequence = -1, 0, OUTSIDE_SEQUENCE
        self.entered, self.returned, self.raised = [0] * 3, [0] * 3, [0] * 3
        self.active = True

    def begin(self, label):
        try:
            if not self.active or type(label) is not int or not 0 <= label < len(LABELS):
                self.flags |= 8
                return -1
            if self.depth == MAX_STACK:
                self.flags |= 4
                return -1
            started = self.clock()
            if type(started) is not int or started < 0:
                self.flags |= 1
                return -1
            case, phase, sequence = self.case, self.phase, self.sequence
            event = hot = -1
            if label in (4, 5):
                if not (0 <= case < 3 and 0 <= phase < 3 and 0 <= sequence < 124):
                    self.flags |= 8
                    return -1
                hot = (((case * 3 + phase) * 124 + sequence) * 2) + label - 4
            else:
                if self.used == self.event_limit:
                    self.flags |= 2
                    return -1
                event = self.used
                self.used += 1
                parent = self.stack[self.depth - 1][8] if self.depth else -1
                row = self.events[event]
                row[0], row[1], row[2], row[3], row[4] = label, case, phase, sequence, parent
                row[5], row[6], row[7], row[8], row[9] = started, 0, 0, 0, 0
            token = self.depth
            row = self.stack[token]
            row[0], row[1], row[2], row[3] = started, label, event, hot
            row[4], row[5], row[6], row[7] = case, phase, sequence, 0
            row[8] = event if event >= 0 else (self.stack[token - 1][8] if token else -1)
            self.depth += 1
            return token
        except BaseException:
            self.flags |= 1
            return -1

    def end(self, token, raised):
        if token < 0:
            return
        try:
            if token != self.depth - 1:
                self.flags |= 16
                return
            self.depth -= 1
            row = self.stack[token]
            if row[2] >= 0:
                event = self.events[row[2]]
                event[7], event[9] = int(raised), 1
            finished = self.clock()
            if type(finished) is not int or finished < row[0]:
                self.flags |= 1
                return
            elapsed = finished - row[0]
            if row[2] >= 0:
                event = self.events[row[2]]
                event[6], event[7], event[8] = finished, int(raised), 1
            else:
                aggregate = self.hot[row[3]]
                aggregate[0] += 1
                aggregate[1] += elapsed
                aggregate[2] = max(aggregate[2], elapsed)
                if aggregate[0] == 1:
                    aggregate[3] = row[0]
                aggregate[4] = finished
                aggregate[5] += int(raised)
        except BaseException:
            self.flags |= 1

    def invoke(self, label, original, *args, **kwargs):
        try:
            token = self.begin(label)
        except BaseException:
            self.flags |= 1
            token = -1
        raised = True
        try:
            result = original(*args, **kwargs)
            raised = False
            return result
        finally:
            try:
                self.end(token, raised)
            except BaseException:
                self.flags |= 1

    def finish(self):
        self.active = False
        if self.depth:
            self.flags |= 16

    def snapshot(self):
        assert not self.active, 'Timing serialization is allowed only after original main unwinds'
        events = []
        for index, row in enumerate(self.events[:self.used]):
            events.append(dict(id=index, label=LABELS[row[0]], caseIndex=row[1], phaseIndex=row[2],
                requestSequence=row[3], parentId=row[4], startedNs=row[5], finishedNs=row[6] if row[8] else None,
                elapsedNs=row[6]-row[5] if row[8] else None, raised=bool(row[7]) if row[9] else None,
                outcomeRecorded=bool(row[9]), finished=bool(row[8])))
        aggregates = []
        for index, row in enumerate(self.hot):
            if not row[0]:
                continue
            key, hot = divmod(index, 2)
            key, sequence = divmod(key, 124)
            case, phase = divmod(key, 3)
            aggregates.append(dict(label=LABELS[hot+4], caseIndex=case, phaseIndex=phase,
                requestSequence=sequence, count=row[0], inclusiveTotalNs=row[1], maxNs=row[2],
                firstStartedNs=row[3], lastFinishedNs=row[4], raisedCount=row[5]))
        return dict(complete=self.flags == 0, faultFlags=self.flags, events=events, hotAggregates=aggregates,
            cases=dict(order=['save', 'discard', 'cancel'], entered=list(self.entered),
                returned=list(self.returned), raised=list(self.raised),
                unwound=[a+b for a, b in zip(self.returned, self.raised)]),
            phaseOrder=['outside', 'before-close-reader', 'after-cancel-reader'], outsideRequestSequence=OUTSIDE_SEQUENCE,
            durationBasis='inclusive parent monotonic_ns intervals; nested spans overlap; RPC residual is unattributed',
            unmeasuredResidual='safe-file/path checks, with enter/exit/close, Python work, scheduling and instrumentation overhead',
            bounds=dict(events=self.event_limit, stack=MAX_STACK, hotCells=len(self.hot)))


def wrap_call(original, label, collector, *, context=None):
    @functools.wraps(original)
    def wrapped(*args, **kwargs):
        previous = collector.case, collector.phase, collector.sequence
        case = -1
        try:
            try:
                if context == 'case':
                    choice = args[0].__dict__['choice']
                    case = ('save', 'discard', 'cancel').index(choice)
                    collector.case, collector.phase, collector.sequence = case, 0, OUTSIDE_SEQUENCE
                    collector.entered[case] += 1
                elif context == 'reader':
                    state = args[0].__dict__
                    collector.phase = ('outside', 'before-close-reader', 'after-cancel-reader').index(state['output'].name)
                    sequence = state['sequence']
                    assert type(sequence) is int and 0 <= sequence <= OUTSIDE_SEQUENCE
                    collector.sequence = sequence
            except BaseException:
                collector.flags |= 8
            raised = True
            try:
                result = collector.invoke(label, original, *args, **kwargs)
                raised = False
                return result
            finally:
                if case >= 0:
                    (collector.raised if raised else collector.returned)[case] += 1
        finally:
            collector.case, collector.phase, collector.sequence = previous
    return wrapped


class _IOTransform(ast.NodeTransformer):
    def __init__(self, which):
        self.which = which
        self.counts = dict.fromkeys(('serialize', 'encode', 'open', 'write', 'flush', 'fsync', 'replace'), 0)

    def visit_Call(self, node):
        name = ast.unparse(node.func)
        kind = {'json.dumps': 'serialize', 'stream.write': 'write', 'stream.flush': 'flush',
                'os.fsync': 'fsync', 'os.replace': 'replace'}.get(name)
        if isinstance(node.func, ast.Attribute) and node.func.attr in ('open', 'encode'):
            kind = node.func.attr
        node = self.generic_visit(node)
        if kind is None:
            return node
        self.counts[kind] += 1
        label = LABELS.index(('atomic.' if self.which == 'atomic' else 'shortcut.') + kind)
        replacement = ast.Call(func=ast.Name(id=PRIVATE_INVOKE, ctx=ast.Load()),
            args=[ast.Constant(value=label), node.func, *node.args], keywords=node.keywords)
        return ast.copy_location(replacement, node)


class _Inverse(ast.NodeTransformer):
    def visit_Call(self, node):
        node = self.generic_visit(node)
        if isinstance(node.func, ast.Name) and node.func.id == PRIVATE_INVOKE:
            assert len(node.args) >= 2 and isinstance(node.args[0], ast.Constant)
            return ast.copy_location(ast.Call(func=node.args[1], args=node.args[2:], keywords=node.keywords), node)
        return node


def transform_io(original, node, which, expected_ast_sha):
    """Compile only a pinned pure-Python function; do not run or bind it here."""
    assert which in ('atomic', 'shortcut') and _ast_sha(node) == expected_ast_sha, 'I/O function AST differs'
    assert original.__closure__ is None and not node.decorator_list
    assert not node.args.defaults and not any(node.args.kw_defaults), 'Unexpected I/O function defaults'
    transformed = copy.deepcopy(node)
    transform = _IOTransform(which)
    transformed = transform.visit(transformed)
    expected = dict.fromkeys(transform.counts, 1)
    if which == 'shortcut':
        expected['replace'] = 0
    assert transform.counts == expected, 'I/O call anchor counts differ'
    inverse = _Inverse().visit(copy.deepcopy(transformed))
    assert ast.dump(inverse, include_attributes=False) == ast.dump(node, include_attributes=False), 'I/O transform is not invertible'
    ast.fix_missing_locations(transformed)
    namespace = {}
    exec(compile(ast.Module(body=[transformed], type_ignores=[]), original.__code__.co_filename, 'exec'), original.__globals__, namespace)
    replacement = namespace[node.name]
    replacement.__defaults__, replacement.__kwdefaults__ = original.__defaults__, original.__kwdefaults__
    replacement.__annotations__ = dict(original.__annotations__)
    replacement.__qualname__, replacement.__module__ = original.__qualname__, original.__module__
    assert inspect.signature(replacement) == inspect.signature(original), 'I/O function signature differs'
    proof = dict(kind=which, callCount=sum(transform.counts.values()), counts=transform.counts,
        originalAstSha256=_ast_sha(node), inverseAstSha256=_ast_sha(inverse),
        transformedAstSha256=_ast_sha(transformed), generatedSource=ast.unparse(transformed),
        filename=original.__code__.co_filename, firstLine=node.lineno,
        signature=str(inspect.signature(original)), sourceLocationsPreserved=True)
    proof['generatedSourceSha256'] = _sha(proof['generatedSource'].encode('utf-8'))
    proof['compilation'] = 'AST with original source locations; rendered text is retained for audit, not reparsed'
    return replacement, proof


class Bindings:
    """Replace only explicit function attributes and two private global names."""
    def __init__(self, changes, globals_, collector):
        self.collector, self.globals = collector, globals_
        self.installed = self.installed_globals = 0
        self.changes = []
        seen = set()
        for owner, name, replacement in changes:
            assert type(owner) in (types.ModuleType, type), 'Only owned modules/plain classes may be bound'
            key = id(owner), name
            assert key not in seen
            seen.add(key)
            self.changes.append((owner, name, inspect.getattr_static(owner, name), replacement))
        assert len({id(g) for g in globals_}) == len(globals_)
        assert all(type(g) is dict and PRIVATE_INVOKE not in g for g in globals_), 'Private timing global already exists'

    def __enter__(self):
        try:
            assert self.installed == self.installed_globals == 0
            for owner, name, original, replacement in self.changes:
                assert inspect.getattr_static(owner, name) is original, 'Original binding changed before installation'
            assert all(PRIVATE_INVOKE not in g for g in self.globals), 'Private timing global changed before installation'
            for g in self.globals:
                g[PRIVATE_INVOKE] = self.collector.invoke
                self.installed_globals += 1
            for owner, name, original, replacement in self.changes:
                setattr(owner, name, replacement)
                self.installed += 1
        except BaseException:
            self.__exit__(*sys.exc_info())
            raise
        return self

    def __exit__(self, kind, value, tb):
        error = None
        for owner, name, original, replacement in reversed(self.changes[:self.installed]):
            try:
                setattr(owner, name, original)
                assert inspect.getattr_static(owner, name) is original
            except BaseException as exc:
                self.collector.flags |= 32
                if error is None:
                    error = exc
        self.installed = 0
        for g in self.globals[:self.installed_globals]:
            g.pop(PRIVATE_INVOKE, None)
        self.installed_globals = 0
        if error is not None and kind is None:
            raise error
        return False


def execute_original(original_main, bindings, collector, argv, persist):
    code = None
    called = returned = installed = False
    main_error = None
    try:
        with bindings:
            installed = True
            original_argv = sys.argv
            sys.argv = argv
            try:
                called = True
                code = original_main()
                returned = True
            except BaseException:
                main_error = sys.exc_info()
                raise
            finally:
                sys.argv = original_argv
    finally:
        # This runs only after the original main and all entered case finally
        # blocks unwind and the exact original bindings are restored.
        kind, value, tb = sys.exc_info()
        try:
            collector.finish()
            snapshot = collector.snapshot()
            primary_kind, primary_value, primary_tb = main_error or (None, None, None)
            instrumentation_failure = None
            if kind is not None and value is not primary_value:
                instrumentation_failure = dict(phase='hook-restore' if installed else 'hook-install',
                    exceptionType=kind.__name__, traceback=''.join(traceback.format_exception(kind, value, tb)))
            report = dict(schemaVersion=1, kind='unqualified-calc-close-existing-call-timing',
                diagnosticOnly=True, success=False, productQualified=False, hostReadyQualified=False,
                officeReplacementCertified=False, originalInvocation=dict(called=called, returned=returned, returnCode=code,
                    exceptionType=primary_kind.__name__ if primary_kind else None,
                    traceback=''.join(traceback.format_exception(primary_kind, primary_value, primary_tb)) if primary_kind else None),
                instrumentationFailure=instrumentation_failure,
                cases=snapshot['cases'], timing=snapshot,
                limitations=['Timing can perturb scheduling and original deadline completion.',
                    'RPC intervals include wait, polling, helper execution and uninstrumented parent work.',
                    'Context-manager close is residual, not directly measured.',
                    'No helper source, native ABI, RPC schema, input, getter, durability or budget changes.'])
            persist(report)
        except BaseException:
            if kind is None:
                raise
            # Do not replace an original pending exception with a timing error.
    return code


def _unlinked(path):
    for item in (path, *path.parents):
        if not item.exists():
            assert not item.is_symlink()
            continue
        info = item.lstat()
        assert not stat.S_ISLNK(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400, 'Linked timing path'


def _canonical_bytes(raw):
    canonical = raw.replace(b'\r\n', b'\n')
    assert raw == canonical or raw == canonical.replace(b'\n', b'\r\n'), 'Mixed source newline representation'
    return canonical


def verify_source_files(root):
    rows = []
    for relative, (size, digest) in SOURCE_PINS.items():
        path = root / relative
        _unlinked(path)
        before = path.stat()
        assert stat.S_ISREG(before.st_mode) and before.st_size <= 2 * size, 'Source file size/type differs'
        with path.open('rb') as stream:
            raw = stream.read(2 * size + 1)
        after = path.stat()
        assert (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns), 'Source file changed during read'
        canonical = _canonical_bytes(raw)
        assert len(canonical) == size and _sha(canonical) == digest, 'Pinned production source differs: ' + relative
        rows.append(dict(path=relative, committedBytes=size, committedSha256=digest, actualBytes=len(raw),
            sha256=_sha(raw), newlineRepresentation='LF' if raw == canonical else 'CRLF'))
    return rows


def _git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], timeout=15)


def source_binding(root):
    rows = verify_source_files(root)
    head = _git(root, 'rev-parse', 'HEAD').decode('ascii').strip()
    tree = _git(root, 'rev-parse', 'HEAD^{tree}').decode('ascii').strip()
    assert re.fullmatch(r'[0-9a-f]{40}', head) and head != '0' * 40
    assert re.fullmatch(r'[0-9a-f]{40}', tree) and tree != '0' * 40
    assert not _git(root, 'status', '--porcelain=v1', '--untracked-files=no'), 'Tracked source is dirty'
    for relative, (_, digest) in SOURCE_PINS.items():
        assert _sha(_git(root, 'show', head + ':' + relative)) == digest, 'Committed production blob differs'
    own = 'suite/e2e/calc_close_existing_call_timing.py'
    assert _git(root, 'show', head + ':' + own) == _canonical_bytes((root / own).read_bytes()), 'Timing runner is not committed at source HEAD'
    github = {key: os.environ.get(key) for key in ('GITHUB_ACTIONS', 'GITHUB_SHA', 'GITHUB_WORKFLOW_SHA',
        'GITHUB_REF', 'GITHUB_WORKFLOW_REF', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'GITHUB_JOB')}
    for name in ('GITHUB_SHA', 'GITHUB_WORKFLOW_SHA'):
        value = github[name]
        if value is not None or github['GITHUB_ACTIONS'] == 'true':
            assert value == head, 'Actual GitHub source/workflow SHA differs from local committed source'
    return dict(head=head, tree=tree, sourceFiles=rows, github=github,
        githubEnvironmentModified=False, mainNativePrivacySetupPerformed=False,
        diagnosticPreparation='Separately retained by the workflow; this runner does not invoke preparation or claim its success.')


def build_bindings(root, collector):
    modules = {name: importlib.import_module(name) for name in
        ('calc_close_probe', 'writer_model_reader', 'writer_style_smoke', 'counted_editor_shortcuts')}
    for name, module in modules.items():
        assert Path(module.__file__).resolve() == (root / 'suite/e2e' / (name + '.py')).resolve(), 'Foreign production import'
    close, reader, style, shortcut = (modules[n] for n in
        ('calc_close_probe', 'writer_model_reader', 'writer_style_smoke', 'counted_editor_shortcuts'))
    targets = [(close.CalcCloseCase, 'run', 0, 'case'),
        (reader.OwnedWriterReader, 'start', 1, 'reader'), (reader.OwnedWriterReader, '_read', 2, 'reader'),
        (reader.OwnedWriterReader, '_rpc', 3, 'reader'), (reader.OwnedWriterReader, '_job_pids', 4, None),
        (reader.OwnedWriterReader, '_member_snapshots', 5, None), (reader.OwnedWriterReader, 'close', 6, 'reader'),
        (reader._NativeAnchor, 'snapshot', 7, None), (style, 'require_packaged_python', 8, None),
        (style, '_packaged_identity_file', 9, None), (reader, '_read_json', 10, None)]
    changes = [(owner, name, wrap_call(getattr(owner, name), label, collector, context=context))
        for owner, name, label, context in targets]
    proofs = []
    for owner, name, module, which, label in [(reader, '_atomic_json', reader, 'atomic', 11),
            (shortcut.CountedEditorShortcuts, '_retain', shortcut, 'shortcut', 12)]:
        source = Path(module.__file__).read_text(encoding='utf-8')
        node = ast.parse(source)
        if which == 'shortcut':
            node = next(n for n in node.body if isinstance(n, ast.ClassDef) and n.name == 'CountedEditorShortcuts')
        node = next(n for n in node.body if isinstance(n, ast.FunctionDef) and n.name == name)
        original = getattr(owner, name)
        assert original.__code__.co_firstlineno == node.lineno and Path(original.__code__.co_filename).resolve() == Path(module.__file__).resolve(), 'I/O source location differs'
        replacement, proof = transform_io(original, node, which, IO_AST_PINS[which])
        changes.append((owner, name, wrap_call(replacement, label, collector)))
        proofs.append(proof)
    assert close.CountedEditorShortcuts is shortcut.CountedEditorShortcuts, 'Shortcut class alias differs'
    return close.main, Bindings(changes, [reader.__dict__, shortcut.__dict__], collector), proofs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', type=Path, required=True)
    parser.add_argument('--fixtures', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if os.name != 'nt' or not __debug__:
        raise RuntimeError('Actual Windows execution with assertions is required')
    for path in (args.suite, args.fixtures, args.output):
        assert not str(path).startswith(('\\\\', '//')) and '..' not in path.parts
        _unlinked(path.absolute())
    suite, fixtures, output = args.suite.resolve(), args.fixtures.resolve(), args.output.resolve()
    assert suite != output and suite not in output.parents and output not in suite.parents
    assert fixtures != output and fixtures not in output.parents and output not in fixtures.parents
    root = Path(__file__).absolute().parents[2]
    binding = source_binding(root)
    collector = TimingCollector()
    original_main, bindings, transforms = build_bindings(root, collector)
    output.mkdir(parents=True, exist_ok=False)
    production = output / 'production'
    def persist(report):
        report.update(source=binding, transforms=transforms, originalOutput=str(production),
            nativePrivacyPreparationQualified=False)
        data = (json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
        assert len(data) <= MAX_REPORT_BYTES, 'Diagnostic timing report exceeds its finite bound'
        with (output / 'timing.json').open('xb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
    code = execute_original(original_main, bindings, collector,
        [str(root / 'suite/e2e/calc_close_probe.py'), '--suite', str(suite), '--fixtures', str(fixtures), '--output', str(production)], persist)
    return code if code else (0 if collector.flags == 0 else 2)


if __name__ == '__main__':
    raise SystemExit(main())
