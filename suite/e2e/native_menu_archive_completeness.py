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
from suite.e2e.native_menu_smoke import CORE_COMMANDS, GESTURES, MODULES, VIEW_MODULES, require_hwp_launcher_receipt, require_native_point_preflight

REPORT = '.work/suite-native-menu/results.json'
ROOT = '.work/suite-native-menu/worker-diagnostics'
POINT_METHOD_V2 = 'owned-popup-and-msaa-canonical-hit-v2'
POINT_METHOD_V4 = 'owned-popup-and-source-qualified-ia2-hit-v4'


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _key(row):
    return (original._positive(row.get('pid')), original._positive(row.get('creationTime')),
            original._image(row.get('image')))


def _nodes(value):
    pending=[value];count=0
    while pending:
        item=pending.pop();count+=1
        _require(count<=1_000_000, 'Original menu action tree exceeds its finite bound')
        yield item
        if type(item) is dict:pending.extend(item.values())
        elif type(item) is list:pending.extend(item)


def _action_bytes(action):
    return json.dumps(action,ensure_ascii=False,allow_nan=False,sort_keys=True,
        separators=(',',':')).encode()


def _action_profiles(action):
    from owned_native_menu import _require_provider_point_v2
    points=[];snapshots=[];results=[]
    for item in _nodes(action):
        if type(item) is not dict:continue
        point=item.get('targetPointProof')
        if type(point) is dict and 'providerLocalProof' in point:snapshots.append((point,item))
        if 'providerLocalProof' in item:
            proof=item['providerLocalProof']
            _require(item.get('pointMethod')==POINT_METHOD_V2 and type(proof) is dict
                and type(proof.get('schemaVersion')) is int and proof['schemaVersion']==2
                and proof.get('method')==POINT_METHOD_V2,
                'Original menu point proof is not the declared canonical profile')
            provider=proof.get('provider')
            _require(type(provider) is dict and type(provider.get('schemaVersion')) is int
                and provider['schemaVersion']==2 and type(provider.get('workerSchemaVersion')) is int
                and provider['workerSchemaVersion']==2,
                'Original canonical point worker profile differs')
            points.append(item)
        elif item.get('pointMethod') not in (None,'global-uia'):
            raise ValueError('Original menu local point proof is missing or unknown')
        if 'providerLocalResult' in item:
            result=item['providerLocalResult']
            _require(type(result) is dict and type(result.get('schemaVersion')) is int
                and result['schemaVersion']==2 and type(result.get('workerSchemaVersion')) is int
                and result['workerSchemaVersion']==2,
                'Original menu worker observation mixes profiles')
            results.append(result)
    replayed=set()
    for point,snapshot in snapshots:
        identity=snapshot.get('identityProof')
        _require(snapshot.get('binding')==action['binding']
            and type(identity) is dict and identity.get('scope')==action.get('elementIdentityScope'),
            'Retained native point snapshot belongs to another action scope')
        role=point['providerLocalProof'].get('role')
        _require(type(role) is str and role.startswith('target:'),
            'Original canonical point does not name an exact command')
        _require_provider_point_v2(point,snapshot,role[len('target:'):])
        replayed.add(_action_bytes(point))
    for pointer in action['pointers']:
        for hit,snapshot in zip(pointer.get('hits',[]),pointer.get('snapshots',[])[1:]):
            if 'providerLocalProof' in hit:
                _require_provider_point_v2(hit,snapshot,pointer['target'])
                replayed.add(_action_bytes(hit))
    _require(all(_action_bytes(point) in replayed for point in points),
        'Original canonical point has no replayed action snapshot or hit')
    providers={}
    for point in points:
        proof=point['providerLocalProof'];scope_id=proof['sourceScopeId']
        packet=_action_bytes(proof['provider'])
        _require(scope_id not in providers or providers[scope_id]==packet,
            'One original menu scope describes different worker packets')
        providers[scope_id]=packet
    if providers:
        interop=action.get('uiaInterop')
        _require(type(interop) is dict and 'providerLocalResult' in interop,
            'Original menu final worker diagnostic path is missing')
        latest=providers[max(providers)]
        _require(_action_bytes(interop['providerLocalResult'])==latest
            and all(_action_bytes(result)==latest for result in results),
            'Original menu worker diagnostic packet is not its final replayed point proof')
    else:_require(not results, 'A global-only menu action retained a local worker packet')


def _source_authority(admission,suite):
    from owned_native_menu import _source_admission_summary
    summary=_source_admission_summary(admission)
    _require(str(Path(suite).absolute())==str(admission.suite_root),
        'Source menu archive belongs to another admitted Suite root')
    return summary


def _action_profiles_v4(action,admission):
    from owned_native_menu import _require_provider_point_v4
    digest=admission.admission_sha256
    words=tuple(int(digest[index:index+8],16) for index in range(0,64,8))
    points=[];snapshots=[];results=[]
    for item in _nodes(action):
        if type(item) is not dict:continue
        point=item.get('targetPointProof')
        if type(point) is dict and 'providerLocalProof' in point:snapshots.append((point,item))
        if 'providerLocalProof' in item:
            proof=item['providerLocalProof']
            _require(item.get('pointMethod')==POINT_METHOD_V4 and item.get('uiaMatches') is False
                and type(proof) is dict and type(proof.get('schemaVersion')) is int
                and proof['schemaVersion']==4 and proof.get('method')==POINT_METHOD_V4
                and proof.get('sourceAdmissionSha256')==digest,
                'Source menu point proof differs from its actual admitted profile')
            provider=proof.get('provider')
            _require(type(provider) is dict and type(provider.get('schemaVersion')) is int
                and provider['schemaVersion']==4 and type(provider.get('workerSchemaVersion')) is int
                and provider['workerSchemaVersion']==4
                and tuple(provider.get('admissionDigest'+str(index)) for index in range(8))==words,
                'Source menu worker is not joined to the actual source admission')
            points.append(item)
        elif item.get('pointMethod') not in (None,'global-uia'):
            raise ValueError('Source menu local point proof is missing or mixes profiles')
        if 'providerLocalResult' in item:
            result=item['providerLocalResult']
            _require(type(result) is dict and type(result.get('schemaVersion')) is int
                and result['schemaVersion']==4 and type(result.get('workerSchemaVersion')) is int
                and result['workerSchemaVersion']==4,
                'Source menu worker observation mixes profiles')
            results.append(result)
    replayed=set()
    def replay(point,snapshot,target):
        _require(snapshot.get('binding')==action['binding']
            and type(snapshot.get('identityProof')) is dict
            and snapshot['identityProof'].get('scope')==action.get('elementIdentityScope'),
            'Source menu retained point belongs to another action scope')
        _require_provider_point_v4(point['providerLocalProof'],action['binding'],
            action['originalProcess']['pid'],target,admission_sha256=digest,now=point['pointObservedAt'])
        replayed.add(id(point))
    for point,snapshot in snapshots:
        role=point['providerLocalProof'].get('role')
        _require(type(role) is str and role.startswith('target:'),
            'Source menu point does not identify its exact command')
        replay(point,snapshot,role[len('target:'):])
    for pointer in action['pointers']:
        samples=pointer.get('snapshots',[]);hits=pointer.get('hits',[])
        if len(samples)==3 and len(hits)==2:
            sites=(samples[0].get('targetPointProof'),samples[1].get('targetPointProof'),
                hits[0],samples[2].get('targetPointProof'),hits[1])
            previous_id=0;previous_at=None
            for point in sites:
                if type(point) is not dict or 'providerLocalProof' not in point:continue
                proof=point['providerLocalProof']
                _require(proof['sourceScopeId']>previous_id
                    and (previous_at is None or previous_at<=proof['capturedAt']),
                    'Source menu point sites reused or reordered their fresh acquisitions')
                previous_id=proof['sourceScopeId'];previous_at=point['pointObservedAt']
        for hit,snapshot in zip(hits,samples[1:]):
            if 'providerLocalProof' in hit:replay(hit,snapshot,pointer['target'])
    _require(all(id(point) in replayed for point in points),
        'Source menu point has no replayed snapshot or explicit hit')
    providers={}
    for point in points:
        proof=point['providerLocalProof'];scope_id=proof['sourceScopeId']
        packet=_action_bytes(proof['provider'])
        _require(scope_id not in providers or providers[scope_id]==packet,
            'One source menu scope describes different worker packets')
        providers[scope_id]=packet
    if providers:
        interop=action.get('uiaInterop')
        _require(type(interop) is dict and 'providerLocalResult' in interop,
            'Source menu final worker diagnostic path is missing')
        latest=providers[max(providers)]
        _require(_action_bytes(interop['providerLocalResult'])==latest
            and all(_action_bytes(result)==latest for result in results),
            'Source menu worker diagnostic packet is not its final replayed point')
    else:_require(not results, 'A global-only source menu action retained a local worker packet')


def _menu_actions(row,shell,attachment,generation,suite,*,source_admission=None):
    from owned_native_menu import require_native_menu_action as require_action
    def require_native_menu_action(*args):
        return (require_action(*args) if source_admission is None else
            require_action(*args,source_admission=source_admission))
    profiles=(_action_profiles if source_admission is None else
        lambda action:_action_profiles_v4(action,source_admission))
    document=attachment['hwnd'];ledger=row.get('nativeMenuActions')
    # The producer's original content-free journal admits at most 128 entries.
    _require(type(ledger) is list and 0<len(ledger)<=128,
        'Original native menu action ledger is missing or unbounded')
    binding=dict(document=document,parent=attachment['parent'],child=attachment['child'],officePid=attachment['officePid'])
    activation=next(item['originalProcess'] for item in row['windowActivations']
        if type(item) is dict and item.get('suiteHwnd')==document)
    members={};previous=None
    try:
        for ledger_index,action in enumerate(ledger):
            require_native_menu_action(action,shell,document)
            _require(action['binding']==binding and _key(action['originalEngine'])==_key(generation),
                'Original native action belongs to another attachment or engine generation')
            actor=action['originalProcess']
            _require((actor['pid'],actor['creationTime'],actor['handleValue'])==
                (shell,activation['creationTime'],activation['handleValue'])
                and original._image(actor['image'])==original._image(str(suite/'OpenGeul.Office.exe')),
                'Original native action belongs to another retained shell')
            _require(previous is None or previous<=action['startedAt'],
                'Original native action ledger order changed')
            previous=action['finishedAt'];encoded=_action_bytes(action)
            _require(encoded not in members, 'Duplicate original native action ledger entry')
            members[encoded]=ledger_index
            profiles(action)
        previous_slot=-1;used=set()
        def slot(action,command,gesture):
            nonlocal previous_slot
            require_native_menu_action(action,shell,document,command)
            _require(action['gesture'] is gesture, 'Original native plan slot signature changed')
            encoded=_action_bytes(action)
            _require(encoded in members, 'Original native plan slot has no ledger entry')
            index=members[encoded]
            _require(index>previous_slot, 'Original native plan slots reused or reordered ledger entries')
            previous_slot=index;used.add(index)
        def finish_command(command):
            _require(previous_slot+1<len(ledger), 'Original native finish menu action is missing')
            slot(ledger[previous_slot+1],command,False)
        gestures=row.get('gestures')
        _require(type(gestures) is list and len(gestures)==len(GESTURES),
            'Original fixed native gestures are missing')
        for index,(step,command) in enumerate(zip(gestures,GESTURES)):
            _require(type(step) is dict and type(step.get('index')) is int and step['index']==index
                and step.get('gesture')==command, 'Original fixed native gesture order changed')
            wrapper=step.get('receipt')
            _require(type(wrapper) is dict and wrapper.get('success') is True
                and wrapper.get('gesture')==command,
                'Original fixed native gesture receipt is incomplete')
            action=wrapper.get('receipt')
            slot(action,command,True)
        module=row['module']
        if module in VIEW_MODULES:
            view=row['nativeViewRoundtrip']
            for action in view['previewActions']:slot(action,'printPreview',False)
            for action in view['coreCommands']:slot(action,'core-commands',True)
        if module=='writer':
            slot(row['nativeHwpLauncher']['menuAction'],'new-hwp',False)
            finish_command('home')
        elif module=='calc':
            finish_command('exit')
            wrapper=row.get('postExitCancelMenu')
            _require(type(wrapper) is dict and wrapper.get('gesture')=='open-escape'
                and wrapper.get('success') is True, 'Original Calc cancel menu finish receipt is missing')
            slot(wrapper.get('receipt'),'open-escape',True)
        elif module=='base':
            slot(row['baseSaveMenuAction'],'save',False)
            finish_command('exit')
        elif module in ('draw','math'):finish_command('close')
        _require(len(used)==len(ledger), 'Original native action ledger differs from the complete source plan')
        nested={key:value for key,value in row.items() if key!='nativeMenuActions'}
        for action in _nodes(nested):
            if type(action) is dict and action.get('kind')=='owned-native-menu-action':
                require_native_menu_action(action,shell,document)
                _require(_action_bytes(action) in members,
                    'Nested native action differs from the original flat ledger')
                profiles(action)
    except (AssertionError,KeyError,TypeError,OverflowError,RecursionError):
        raise ValueError('Original native menu action receipt is incomplete, foreign or changed') from None


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


def _source_view_receipts_v4(row,admission):
    """Join already-produced direct view headers to the same flat menu plan."""
    from owned_native_menu import _require_source_header,CAP
    if row['module'] not in VIEW_MODULES:return
    view=row['nativeViewRoundtrip'];ledger=row['nativeMenuActions']
    try:
        for field in ('observations','fullscreenActions'):
            for index,item in enumerate(view[field]):
                _require_source_header(item,admission)
                _require(len(_action_bytes(item))<=CAP and item['pointUses']==[],
                    'Source view receipt exceeds its bound or invents local point uses')
                wanted=len(GESTURES)+(0 if field=='observations' and index==0 else 1)
                _require(type(item['originIndex']) is int and item['originIndex']==wanted,
                    'Source view receipt belongs to another original plan slot')
                origin=ledger[wanted]
                _require(all(item[key]==origin[key] for key in ('binding','originalProcess','originalEngine')),
                    'Source view receipt belongs to another original generation')
                if field=='fullscreenActions':
                    _require(_action_bytes(item['nativeMenuOrigin'])==_action_bytes(origin),
                        'Source fullscreen origin differs from the original flat ledger')
                # These direct operations perform no provider-local point work.
                # Fullscreen alone retains its separately replayed menu origin.
                direct={key:value for key,value in item.items()
                    if not (field=='fullscreenActions' and key=='nativeMenuOrigin')}
                local_fields={'providerLocalResult','providerLocalProof','targetPointProof',
                    'pointObservedAt','workerSchemaVersion','sourceAdmissionSha256'}
                for node in _nodes(direct):
                    if type(node) is not dict:continue
                    _require(not local_fields.intersection(node)
                        and node.get('pointMethod')!=POINT_METHOD_V4 and node.get('method')!=POINT_METHOD_V4,
                        'Global-only source view receipt retained an orphan local point or worker')
    except (AssertionError,KeyError,TypeError,OverflowError,RecursionError):
        raise ValueError('Source view or fullscreen receipt is incomplete, foreign or changed') from None


def _expected(workspace, suite, *, source_admission=None):
    raw = original._bytes(workspace / REPORT, original.MAX_REPORT_BYTES)
    report = original._json(raw)
    _require(type(report.get('schemaVersion')) is int and report['schemaVersion'] == 1
        and report.get('kind') == 'native-menu-gesture-matrix', 'Wrong original menu report')
    profile=2 if source_admission is None else 4
    summary=None if source_admission is None else _source_authority(source_admission,suite)
    _require(type(report.get('nativePointProfileVersion')) is int and report['nativePointProfileVersion']==profile,
        'Original native menu controller profile is missing')
    if summary is not None:
        _require(type(report.get('sourceMenuAdmission')) is dict
            and _action_bytes(report['sourceMenuAdmission'])==_action_bytes(summary),
            'Source menu report differs from the actual admitted source')
    try:require_native_point_preflight(report['nativePointPreflight'])
    except (AssertionError,KeyError,TypeError,ValueError):
        raise ValueError('Original native menu controller preflight did not pass') from None
    _require(all(report.get(key) is True for key in ('success', 'actualWindowsExecuted',
        'nativeMenuVerified', 'scenarioSuccess')), 'Original native menu report did not pass')
    _require(report.get('viewPhysicalVerified') is True
        and all(type(report.get(key)) is int and report[key] == len(VIEW_MODULES)
                for key in ('viewPhysicalExpectedCaseCount', 'viewPhysicalVerifiedCaseCount')),
        'Original native view report coverage differs from the source plan')
    _require(report.get('acceptanceEligible') is False, 'Partial menu gate cannot qualify the complete Suite')
    _require(report.get('nativeHwpMenuLaunchExecuted') is True, 'Original native HWP launcher was not verified')
    _require(all(type(report.get(key)) is int and report[key] == len(MODULES)
        for key in ('expectedCaseCount', 'completedCaseCount', 'passedCaseCount'))
        and report.get('missingModules') == [] and report.get('failedModules') == [],
        'Original menu source coverage counts differ')
    rows = report.get('tests')
    _require(type(rows) is list and len(rows) == len(MODULES), 'Original menu case list differs')
    image = str(suite / 'Office/program/soffice.bin')
    expected = {}
    for module, row in zip(MODULES, rows):
        if summary is not None:
            _require(type(row) is dict and type(row.get('nativePointProfileVersion')) is int
                and row['nativePointProfileVersion']==4 and type(row.get('sourceMenuAdmission')) is dict
                and _action_bytes(row['sourceMenuAdmission'])==_action_bytes(summary),
                'Source menu case differs from the actual admitted source')
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
        if module=='writer':
            _require(row.get('nativeHwpMenuLaunchExecuted') is True and row.get('hwpLauncherCompleted') is True,
                'Original Writer native HWP launcher case did not pass')
            if source_admission is None:require_hwp_launcher_receipt(row.get('nativeHwpLauncher'),row,suite)
            else:require_hwp_launcher_receipt(row.get('nativeHwpLauncher'),row,suite,source_admission=source_admission)
        else:
            _require(row.get('nativeHwpMenuLaunchExecuted') is False and row.get('hwpLauncherCompleted') is False
                and 'nativeHwpLauncher' not in row, 'Unplanned native HWP launcher case')
        key = _key(generation)
        _require(key not in expected, 'Duplicate original native menu engine generation')
        _menu_actions(row,shell,attachment,generation,suite,source_admission=source_admission)
        if source_admission is not None:_source_view_receipts_v4(row,source_admission)
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
    return _verify_archive_matches(workspace,suite,expected,descriptor)


def _verify_archive_matches(workspace,suite,expected,descriptor):
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


def verify_source_qualified_native_menu_archive_completeness(workspace,suite,*,admission):
    """Replay source4 only with a caller's actual, freshly authenticated Gate.

    Saved summaries select no authority. Historical point times are checked by
    the public source-aware action validator, without a live provider query.
    """
    workspace,suite=Path(workspace),Path(suite)
    summary=_source_authority(admission,suite)
    _require(workspace.is_absolute() and suite.is_absolute(), 'Absolute menu coverage roots required')
    original._plain(workspace);original._plain(suite)
    expected,descriptor=_expected(workspace,suite,source_admission=admission)
    result=_verify_archive_matches(workspace,suite,expected,descriptor)
    result.update(nativePointProfileVersion=4,sourceMenuAdmission=summary)
    return result


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
