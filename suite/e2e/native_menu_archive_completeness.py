"""Join the six original menu cases to their isolated, sealed native archives.

The original 83-generation verifier is unchanged. Its archive/file/shutdown and
original-shell/generation validators are reused; only this source-fixed plan and
an additional terminal-event predicate belong to the menu gate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from suite.e2e import native_archive_completeness as original
from suite.e2e.native_menu_smoke import CORE_COMMANDS, MODULES, VIEW_MODULES

REPORT = '.work/suite-native-menu/results.json'
ROOT = '.work/suite-native-menu/worker-diagnostics'


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _key(row):
    return (original._positive(row.get('pid')), original._positive(row.get('creationTime')),
            original._image(row.get('image')))


def _view_case(row, module):
    expected = module in VIEW_MODULES
    _require(row.get('viewRoundtripCompleted') is expected
        and row.get('viewPhysicalVerified') is expected,
        'Original native view case coverage differs from the source plan')
    if not expected:
        _require('nativeViewRoundtrip' not in row, 'Unplanned native view roundtrip')
        return
    view = row.get('nativeViewRoundtrip')
    _require(type(view) is dict and view.get('kind') == 'native-view-roundtrip'
        and view.get('module') == module and view.get('success') is True
        and view.get('originalHomeSurvived') is True,
        'Original native view roundtrip did not pass for this module')
    # Join the producer's fixed plan, without duplicating its detailed UIA,
    # keyboard, focus, timing or retained-handle receipt validators.
    for field, kind, count in (
            ('previewActions', 'owned-native-menu-action', 2),
            ('observations', 'owned-native-view-observation', 4),
            ('fullscreenActions', 'owned-native-fullscreen-toggle', 2),
            ('coreCommands', 'owned-native-menu-action', 2)):
        items = view.get(field)
        _require(type(items) is list and len(items) == count
            and all(type(item) is dict and item.get('kind') == kind
                    and item.get('success') is True for item in items),
            'Original native view steps are incomplete or changed')
    _require(all(item.get('command') == 'printPreview' and item.get('gesture') is False
        for item in view['previewActions']), 'Original native preview plan differs')
    for item, (preview, visible) in zip(view['observations'],
            ((True, True), (False, True), (False, False), (False, True))):
        _require(item.get('module') == module and item.get('preview') is preview
            and item.get('menuVisible') is visible, 'Original native view observation order differs')
        version = item.get('statusSequenceVersion')
        started, completed = (item.get(key) for key in
                              ('firstTargetStartedSequence', 'lastTargetCompletedSequence'))
        _require(item.get('statusRpcProved') is True and type(version) is int and version == 1
            and all(type(value) is int and 0 <= value < (1 << 28) for value in (started, completed))
            and completed > started,
            'Original native view observation lacks a later completed status RPC')
    _require(all(item.get('module') == module and item.get('focusReturned') is True
        for item in view['fullscreenActions']), 'Original native fullscreen plan differs')
    _require(all(item.get('command') == 'core-commands' and item.get('gesture') is True
        and item.get('coreCommandsVerified') is True and item.get('focusReturned') is True
        and item.get('coreCommands') == list(CORE_COMMANDS)
        for item in view['coreCommands']), 'Original native core command plan differs')


def _expected(workspace, suite):
    raw = original._bytes(workspace / REPORT, original.MAX_REPORT_BYTES)
    report = original._json(raw)
    _require(type(report.get('schemaVersion')) is int and report['schemaVersion'] == 1
        and report.get('kind') == 'native-menu-gesture-matrix', 'Wrong original menu report')
    _require(all(report.get(key) is True for key in ('success', 'actualWindowsExecuted',
        'nativeMenuVerified', 'scenarioSuccess')), 'Original native menu report did not pass')
    _require(report.get('viewPhysicalVerified') is True
        and all(type(report.get(key)) is int and report[key] == len(VIEW_MODULES)
                for key in ('viewPhysicalExpectedCaseCount', 'viewPhysicalVerifiedCaseCount')),
        'Original native view report coverage differs from the source plan')
    _require(report.get('acceptanceEligible') is False, 'Partial menu gate cannot qualify the complete Suite')
    _require(all(type(report.get(key)) is int and report[key] == len(MODULES)
        for key in ('expectedCaseCount', 'completedCaseCount', 'passedCaseCount'))
        and report.get('missingModules') == [] and report.get('failedModules') == [],
        'Original menu source coverage counts differ')
    rows = report.get('tests')
    _require(type(rows) is list and len(rows) == len(MODULES), 'Original menu case list differs')
    image = str(suite / 'Office/program/soffice.bin')
    expected = {}
    for module, row in zip(MODULES, rows):
        _require(type(row) is dict and row.get('module') == module
            and row.get('case') == 'native-menu-' + module
            and row.get('kind') == 'native-menu-gesture-case',
            'Original menu source cases are missing, duplicated or reordered')
        _require(all(row.get(key) is True for key in ('success', 'scenarioCompleted',
            'actualWindowsExecuted', 'nativeMenuVerified', 'cleanupConfirmed', 'cleanClose',
            'officeExited', 'officeExitedAfterCleanup', 'engineHandleReleased'))
            and row.get('forcedCleanupRequired') is False
            and all(type(row.get(key)) is int and row[key] == 0
                    for key in ('officeExitCode', 'shellExitCode')),
            'Original native menu case cleanup did not pass')
        _view_case(row, module)
        attachment = original._attachment(row)
        for value in attachment.values():
            original._positive(value)
        shell = original._shell(row, attachment, suite)
        generation = original._original_generation(row, attachment, 'gui', image)
        _require(type(row.get('officeCreationTime')) is int
            and row['officeCreationTime'] == generation['creationTime'],
            'Original menu retained engine generation differs')
        key = _key(generation)
        _require(key not in expected, 'Duplicate original native menu engine generation')
        expected[key] = dict(scope='suite-native-menu', case=row['case'], slot=0,
            suiteShellPid=shell, root=ROOT, **generation)
    descriptor = dict(path=REPORT, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    return expected, descriptor


def _earlier_diagnostic_members(events, begin, wanted):
    """Bind diagnostic-only terminal rows to the same earlier job witness.

    The diagnostic observer starts at bootstrap and retains an exited helper.
    The separate shutdown observer starts immediately before termination, so it
    cannot enumerate that earlier-dead member. Only such already observed exact
    generations may extend the shutdown member set; a new terminal PID cannot.
    """
    found = set()
    for line in events[:begin].splitlines():
        _require(0 < len(line) <= original.MAX_RECEIPT_BYTES,
            'Earlier native menu diagnostic event exceeds its bound')
        event = original._json(line)
        _require(type(event.get('phase')) is str and 0 < len(event['phase']) <= 128
            and type(event.get('utc')) is str and 0 < len(event['utc']) <= 64
            and 'processQueryError' not in event,
            'Earlier native menu diagnostic observation failed')
        rows = event.get('processes')
        _require(type(rows) is list and len(rows) <= 128,
            'Earlier native menu process observation is missing or unbounded')
        for row in rows:
            _require(type(row) is dict, 'Earlier native menu process observation is invalid')
            key = _key(row)
            if key not in wanted:
                continue
            code = row.get('exitCode')
            _require(not any('error' in name.lower() for name in row)
                and type(row.get('alive')) is bool
                and type(row.get('waitResult')) is int
                and row['waitResult'] == (258 if row['alive'] else 0)
                and row.get('getExitCodeProcessResult') is True
                and type(code) is int and 0 <= code <= 0xffffffff
                and row.get('exitCodeHex') == f'0x{code:08x}',
                'Earlier native menu member lacks an owned native observation')
            found.add(key)
    _require(found == wanted, 'New terminal menu member has no earlier owned generation')
    return found


def _last_event(workspace, archive):
    folder = (workspace / archive['manifest']).parent
    events = original._bytes(folder / 'events.jsonl', 16 * 1024 * 1024, single_link=True)
    _require(len(events) == archive['eventsBytes']
        and hashlib.sha256(events).hexdigest() == archive['eventsSha256'],
        'Sealed menu event bytes changed after archive validation')
    _require(events.endswith(b'\n'), 'Native menu terminal event is partial')
    begin = events.rfind(b'\n', 0, len(events) - 1) + 1
    last = events[begin:-1]
    _require(0 < len(last) <= original.MAX_RECEIPT_BYTES, 'Native menu terminal event exceeds its bound')
    event = original._json(last)
    _require(set(event) == {'phase', 'utc', 'processes'}
        and event.get('phase') == 'after-owned-shutdown', 'Native menu terminal event does not prove shutdown')
    _require(type(event.get('utc')) is str and 0 < len(event['utc']) <= 64,
        'Native menu terminal event timestamp is missing')
    rows = event.get('processes')
    _require(type(rows) is list and 0 < len(rows) <= 128, 'Native menu terminal members missing or unbounded')
    shutdown = original._bytes(folder / 'shutdown.json', original.MAX_RECEIPT_BYTES)
    _require(hashlib.sha256(shutdown).hexdigest() == archive['shutdownSha256'],
        'Original menu shutdown bytes changed after archive validation')
    cleanup = original.load_cleanup_receipt(shutdown)
    # Diagnostic and shutdown observers retain different HANDLEs. Join their
    # actual PID/creation/image identities; do not invent or compare handles.
    expected = {_key(row) for row in cleanup['finalMembers']}
    matched, pids = set(), set()
    for row in rows:
        _require(type(row) is dict and not any('error' in key.lower() for key in row),
            'Native menu terminal member has a query error')
        key = _key(row)
        _require(key not in matched and key[0] not in pids,
            'Duplicate native menu terminal member')
        _require(row.get('alive') is False and row.get('getExitCodeProcessResult') is True
            and type(row.get('waitResult')) is int and row['waitResult'] == 0
            and type(row.get('exitCode')) is int and row['exitCode'] == 0
            and row.get('exitCodeHex') == '0x00000000',
            'Native menu terminal member is alive, nonzero or unproved')
        matched.add(key); pids.add(key[0])
    _require(expected <= matched and _key(archive) in matched,
        'Native menu terminal event lost original shutdown process generations')
    earlier = _earlier_diagnostic_members(events, begin, matched - expected) if matched - expected else set()
    return dict(lastEventVerified=True, lastEventMemberCount=len(matched),
        earlierDiagnosticMemberCount=len(earlier))


def verify_native_menu_archive_completeness(workspace, suite):
    workspace, suite = Path(workspace), Path(suite)
    _require(workspace.is_absolute() and suite.is_absolute(), 'Absolute menu coverage roots required')
    original._plain(workspace); original._plain(suite)
    expected, descriptor = _expected(workspace, suite)
    archives = original._archived(workspace, {ROOT}, str(suite / 'Office/program/soffice.bin'))
    matched = {}
    for archive in archives:
        key = _key(archive)
        _require(key in expected, 'Orphan native menu archive generation')
        _require(key not in matched, 'Duplicate native menu archive generation')
        _require(archive['root'] == ROOT, 'Native menu archive escaped its isolated root')
        matched[key] = dict(archive, **_last_event(workspace, archive))
    _require(set(matched) == set(expected), 'Missing original native menu archive generation coverage')
    proofs = [dict(row, **{key: value for key, value in matched[identity].items() if key not in row})
              for identity, row in expected.items()]
    return dict(schemaVersion=1, kind='native-menu-archive-generation-completeness', success=True,
        acceptanceEligible=False, expectedGenerations=len(expected), matchedGenerations=len(matched),
        sourceReceipts=[descriptor], archives=proofs)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('workspace', 'suite', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args(argv)
    workspace, suite, output = (path.absolute() for path in (args.workspace, args.suite, args.output))
    original._plain(workspace); original._plain(suite)
    original._plain(output.parent)
    if output.exists() or output.is_symlink() or getattr(output, 'is_junction', lambda: False)():
        original._plain(output)
    workspace, suite, output = workspace.resolve(), suite.resolve(), output.resolve()
    _require(suite != output and suite not in output.parents, 'Menu verification output must be outside the payload')
    diagnostics = workspace / ROOT
    _require(diagnostics != output and diagnostics not in output.parents,
        'Menu verification output must not mutate its verified archive root')
    try:
        result = verify_native_menu_archive_completeness(workspace, suite)
    except (ValueError, OSError, AssertionError) as exc:
        result = dict(schemaVersion=1, kind='native-menu-archive-generation-completeness',
            success=False, acceptanceEligible=False, errorType=type(exc).__name__)
    with output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, allow_nan=False, indent=2)
    print(json.dumps({key: value for key, value in result.items() if key not in ('archives', 'sourceReceipts')}))
    return 0 if result['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
