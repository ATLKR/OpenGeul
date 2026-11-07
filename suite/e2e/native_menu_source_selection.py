"""Explicit E2E source selection with bounded, read-only cache invalidation.

Full source admission runs once per prepared cohort. Epochs detect ordinary
filesystem drift; they are not an OS/loader attestation or persistent byte
oracle. Critical bytes are rechecked before launch and each selected probe.
Callers own their source-only startup cap and the native controller exit fence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
import os
from pathlib import Path
import stat
import sys
import time

# Keep one production Gate class identity, including isolated bare E2E imports.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import native_menu_source_admission as gate


SOURCE_PREPARATION_SECONDS = 150
_PREPARED_SEAL, _SELECTION_SEAL = object(), object()
_MAX_FILES = gate.payload.MAX_FILES+1  # The stored inventory is excluded upstream.
_MAX_ENTRIES = 2*gate.payload.MAX_FILES+1024  # Independently bound directories.
_MAX_DEPTH = 128
_EXECUTABLES = ('OpenGeul.Office.exe', 'OpenGeul.Office.dll',
                'Office/program/soffice.exe', 'Office/program/soffice.bin')


def _deadline(deadline, *, maximum=None, clock=None):
    now = (clock or time.monotonic)()
    if (type(deadline) not in (int, float) or not math.isfinite(deadline)
            or type(now) not in (int, float) or not math.isfinite(now)
            or not now < deadline or maximum is not None and deadline > now+maximum):
        raise ValueError('Source menu original deadline expired or exceeds its cap')


def _pending_zero():
    from native_menu_msaa_hit import pending_msaa_hit
    try:
        pending = pending_msaa_hit()
    except Exception:
        raise ValueError('Source menu pending registry is unknown') from None
    if pending is not None:
        raise ValueError('Source menu has an unretired native callback')


def _absolute(path):
    path = gate._absolute(path)
    if str(path).startswith(('\\\\', '//')):
        raise ValueError('Source menu requires a local identity path')
    return path


def _ordinary(path, deadline, *, directory=False):
    _deadline(deadline)
    try:
        info = path.lstat()
    except OSError:
        raise ValueError('Source menu epoch path is unavailable') from None
    if (stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400
            or not (stat.S_ISDIR(info.st_mode) if directory else
                    stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode))):
        raise ValueError('Source menu epoch contains a linked or nonregular path')
    _deadline(deadline)
    return info


@dataclass(frozen=True, slots=True)
class _FileEpoch:
    path: str  # Preserve exact case, including on case-insensitive Windows Path.
    identity: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class _InputEpoch:
    path: Path
    state: gate._FileState
    limit: int


@dataclass(frozen=True, slots=True)
class _Anchor:
    path: Path
    size: int
    sha256: str
    state: gate._FileState
    limit: int


def _payload_epoch(suite, deadline):
    """Finite metadata walk, including directories and every added/removed name."""
    suite = _absolute(suite)
    result = []
    for parent in reversed(suite.parents):
        info = _ordinary(parent, deadline, directory=True)
        # Sibling evidence/cache writes outside the payload do not change it.
        result.append(_FileEpoch(str(parent), gate._stat_identity(info)[:3]))
    pending = [(suite, 0, None)]
    aliases, file_count, entry_count = set(), 0, 0
    while pending:
        path, depth, previous = pending.pop()
        info = _ordinary(path, deadline)
        identity = gate._stat_identity(info)
        if previous is not None:
            if identity != previous:
                raise ValueError('Source menu directory changed during its epoch scan')
            continue
        entry_count += 1
        if entry_count > _MAX_ENTRIES or depth > _MAX_DEPTH:
            raise ValueError('Source menu payload epoch exceeds its entry or depth bound')
        directory = stat.S_ISDIR(info.st_mode)
        if path == suite and not directory:
            raise ValueError('Source menu payload root is not a directory')
        if path != suite:
            name = path.relative_to(suite).as_posix()
            try:
                gate.payload._name(name)
                gate.payload._layout(name, directory=directory)
            except ValueError:
                raise ValueError('Source menu payload epoch has an unsafe path') from None
            key = name.casefold()
            if key in aliases:
                raise ValueError('Source menu payload epoch has a case alias')
            aliases.add(key)
        result.append(_FileEpoch(str(path), identity))
        if directory:
            try:
                with os.scandir(path) as entries:
                    names = []
                    for entry in entries:
                        _deadline(deadline)
                        names.append(entry.name)
                        if len(names)+entry_count > _MAX_ENTRIES:
                            raise ValueError('Source menu payload directory exceeds its entry bound')
            except OSError:
                raise ValueError('Source menu payload directory scan failed') from None
            pending.append((path, depth, identity))
            pending.extend((path/name, depth+1, None) for name in reversed(sorted(names)))
        else:
            file_count += 1
            if file_count > _MAX_FILES:
                raise ValueError('Source menu payload epoch exceeds its file bound')
    _deadline(deadline)
    return tuple(result)


def _input_paths(architecture):
    if type(architecture) is not str or architecture not in ('x64', 'arm64'):
        raise ValueError('Source menu architecture is unsupported')
    root = _absolute(gate._HARNESS_ROOT)
    lock = 'runtime.arm64.lock.json' if architecture == 'arm64' else 'runtime.lock.json'
    inputs = root/'.work/source-engine-input'
    return ((root/'suite/config'/lock, gate.payload.MAX_METADATA),
            (inputs/('OpenGeul-Office-engine-'+architecture+'.zip'), gate._MAX_ARCHIVE_BYTES),
            (inputs/'source-build-receipt.json', 8*1024*1024))


def _input_epoch(architecture, deadline):
    return tuple(_InputEpoch(path, gate._file_state(path, deadline, limit=limit), limit)
                 for path, limit in _input_paths(architecture))


@dataclass(frozen=True, slots=True, init=False)
class PreparedSourceMenu:
    admission: gate.SourceMenuAdmission
    payload_epoch: tuple[_FileEpoch, ...] = field(repr=False)
    input_epoch: tuple[_InputEpoch, ...] = field(repr=False)
    _anchors: tuple[_Anchor, ...] = field(repr=False)
    _admission_sha256: str = field(repr=False)
    _seal: object = field(repr=False, compare=False)

    def __init__(self):
        raise TypeError('Prepared source menu requires the verified factory')


@dataclass(frozen=True, slots=True, init=False)
class SourceMenuSelection:
    prepared: PreparedSourceMenu
    launch_deadline: float
    _seal: object = field(repr=False, compare=False)

    def __init__(self):
        raise TypeError('Source menu selection requires the verified factory')


def _require_prepared(prepared):
    if (type(prepared) is not PreparedSourceMenu or getattr(prepared, '_seal', None) is not _PREPARED_SEAL
            or type(prepared.admission) is not gate.SourceMenuAdmission
            or prepared.admission.admission_sha256 != prepared._admission_sha256
            or prepared.admission.summary()['admissionSha256'] != prepared._admission_sha256):
        raise ValueError('Source menu runtime was not prepared by its verified factory')


def _require_selection(selection):
    if (type(selection) is not SourceMenuSelection or getattr(selection, '_seal', None) is not _SELECTION_SEAL
            or type(selection.launch_deadline) not in (int, float)
            or not math.isfinite(selection.launch_deadline)):
        raise ValueError('Source menu selection was not explicitly prepared')
    _require_prepared(selection.prepared)


_EPOCH_SEAL = object()
_EPOCH_FIELDS = ('schemaVersion','branchCode','comparisonStatusCode','baselineCount',
    'currentCount','countsKnown','addedCount','removedCount','changedCount',
    'orderChanged','structureChanged','sampleTruncated')
_EPOCH_ROW_FIELDS = ('changeCode','roleCode','baselineOrdinal','fieldMask')


@dataclass(frozen=True, slots=True, repr=False)
class _EpochObservation:
    prepared: object
    exception: object
    values: tuple
    rows: tuple
    seal: object

    def __repr__(self):
        return '<source-epoch-observation>'


def _epoch_entries(prepared, branch, epoch):
    if branch == 1:
        root = str(prepared.admission.suite_root)
        for row in epoch:
            role = 1 if len(row.identity)==3 else 2 if row.path==root else 3 if stat.S_ISDIR(row.identity[2]) else 4
            yield row.path, role, row.identity
    else:
        for index, row in enumerate(epoch):
            for ordinal, identity in enumerate(row.state.ancestors):
                yield (index,1,ordinal), 21+index, identity
            yield (index,0,str(row.path)), 11+index, row.state.file


def _epoch_difference(prepared, branch, current, deadline):
    """Pure comparison of retained metadata; never resolve or inspect a path."""
    before = prepared.payload_epoch if branch==1 else prepared.input_epoch
    baseline_count = len(before) if branch==1 else sum(len(row.state.ancestors)+1 for row in before)
    current_count = len(current) if branch==1 else sum(len(row.state.ancestors)+1 for row in current)
    def incomplete(status):
        return (1,branch,status,baseline_count,current_count,0,0,0,0,0,int(status==3),0), ()
    def expired():
        now = time.monotonic()
        return type(now) not in (int,float) or not math.isfinite(now) or now>=deadline
    records = []
    for epoch in (before,current):
        result, order = {}, []
        for ordinal, (key,role,identity) in enumerate(_epoch_entries(prepared,branch,epoch),1):
            if expired():return incomplete(2)
            if (key in result or len(identity) not in (3,6)
                    or any(type(value) is not int for value in identity)):
                return incomplete(3)
            result[key] = (ordinal,role,identity)
            order.append(key)
        records.append((result,order))
    baseline, old_order = records[0];actual, new_order = records[1]
    added = removed = changed = structure = 0
    rows = []
    def sample(code,role,ordinal,mask):
        if len(rows)<16:rows.append((code,role,ordinal,mask))
    for key in old_order:
        if expired():return incomplete(2)
        ordinal,role,identity = baseline[key]
        if key not in actual:
            removed += 1;sample(2,role,ordinal,0)
        elif identity != actual[key][2]:
            other = actual[key][2]
            structure |= int(len(identity)!=len(other))
            mask = sum(1<<i for i,(left,right) in enumerate(zip(identity,other)) if left!=right)
            changed += 1;sample(3,role,ordinal,mask)
    for key in new_order:
        if expired():return incomplete(2)
        if key not in baseline:
            added += 1;sample(1,actual[key][1],0,0)
    old_shared = [key for key in old_order if key in actual]
    new_shared = [key for key in new_order if key in baseline]
    if branch==2:
        structure |= int(len(before)!=len(current) or any(left.limit!=right.limit
            or len(left.state.ancestors)!=len(right.state.ancestors)
            for left,right in zip(before,current)))
    if expired():return incomplete(2)
    values = (1,branch,1,baseline_count,current_count,1,added,removed,changed,
        int(old_shared!=new_shared),structure,int(added+removed+changed>len(rows)))
    return values, tuple(rows)


def _source_epoch_exception(prepared, branch, current, deadline):
    failure = ValueError('Source menu epoch changed; an explicit new preparation is required')
    try:
        _require_prepared(prepared)
        values, rows = _epoch_difference(prepared,branch,current,deadline)
        failure._source_epoch_observation = _EpochObservation(prepared,failure,values,rows,_EPOCH_SEAL)
    except Exception:
        # Observation is optional; it can never replace the original refusal.
        pass
    return failure


def _source_epoch_failure_summary(failure, prepared):
    """Export only this exact exception's closed numeric observation."""
    try:
        _require_prepared(prepared)
        observation = getattr(failure,'_source_epoch_observation',None)
        if (type(failure) is not ValueError or type(observation) is not _EpochObservation
                or observation.seal is not _EPOCH_SEAL or observation.prepared is not prepared
                or observation.exception is not failure):return None
        values,rows = observation.values,observation.rows
        if (type(values) is not tuple or len(values)!=len(_EPOCH_FIELDS)
                or any(type(value) is not int or value<0 for value in values)
                or type(rows) is not tuple or len(rows)>16):return None
        value = dict(zip(_EPOCH_FIELDS,values))
        if (value['schemaVersion']!=1 or value['branchCode'] not in (1,2)
                or value['comparisonStatusCode'] not in (1,2,3)
                or any(value[key] not in (0,1) for key in ('countsKnown','orderChanged','structureChanged','sampleTruncated'))
                or value['countsKnown']!=int(value['comparisonStatusCode']==1)):
            return None
        for row in rows:
            if (type(row) is not tuple or len(row)!=4 or any(type(item) is not int for item in row)
                    or row[0] not in (1,2,3) or row[1] not in (1,2,3,4,11,12,13,21,22,23)
                    or not 0<=row[2]<=value['baselineCount'] or not 0<=row[3]<=63
                    or (row[2]==0)!=(row[0]==1) or row[0] in (1,2) and row[3]!=0):return None
        value['rows'] = [dict(zip(_EPOCH_ROW_FIELDS,row)) for row in rows]
        return value
    except Exception:
        return None


def _unchanged_epochs(prepared, deadline):
    admission = prepared.admission
    current = _payload_epoch(admission.suite_root, deadline)
    if current != prepared.payload_epoch:
        raise _source_epoch_exception(prepared,1,current,deadline)
    current = _input_epoch(admission.architecture, deadline)
    if current != prepared.input_epoch:
        raise _source_epoch_exception(prepared,2,current,deadline)


def _anchors(admission, payload_epoch, input_epoch, deadline):
    suite, summary = admission.suite_root, admission.summary()
    digest, data, state = gate._hash_file(suite/'suite-inventory.json', deadline=deadline,
        limit=gate.payload.MAX_METADATA, collect=True)
    if digest != summary['inventorySha256']:
        raise ValueError('Source menu inventory differs from its admitted bytes')
    inventory = gate.payload._json_bytes(data, 'admitted source menu inventory')
    if inventory.get('architecture') != admission.architecture:
        raise ValueError('Source menu admitted inventory architecture differs')
    result = [_Anchor(suite/'suite-inventory.json', state.file[3], digest, state, gate.payload.MAX_METADATA)]
    identities = {item.path: item.identity for item in payload_epoch}
    for name in _EXECUTABLES:
        record = inventory['files'].get(name)
        path = suite/name
        before = gate._file_state(path, deadline, limit=gate._MAX_FILE_BYTES)
        if (not isinstance(record, dict) or before.file != identities.get(str(path))
                or before.file[3] != record.get('size') or not gate.payload._sha(record.get('sha256'))):
            raise ValueError('Source menu executable anchor is missing or changed')
        result.append(_Anchor(path, record['size'], record['sha256'], before, gate._MAX_FILE_BYTES))
    for item, key in ((input_epoch[0], 'lockSha256'), (input_epoch[2], 'receiptSha256')):
        result.append(_Anchor(item.path, item.state.file[3], summary[key], item.state, item.limit))
    return tuple(result)


def prepare_source_menu_runtime(suite: Path, architecture: str, *, deadline: float) -> PreparedSourceMenu:
    """One full Gate under a caller's explicit source-only cap (at most150s)."""
    _deadline(deadline, maximum=SOURCE_PREPARATION_SECONDS)
    _pending_zero()
    suite = _absolute(suite)
    before = _payload_epoch(suite, deadline)
    inputs = _input_epoch(architecture, deadline)
    _, archive, receipt = _input_paths(architecture)
    admission = gate.admit_source_menu_runtime(suite, architecture=architecture,
        engine_zip=archive[0], receipt=receipt[0], deadline=deadline)
    anchors = _anchors(admission, before, inputs, deadline)
    if (before != _payload_epoch(suite, deadline) or inputs != _input_epoch(architecture, deadline)):
        raise ValueError('Source menu changed during preparation; no cache was admitted')
    _pending_zero()
    _deadline(deadline)
    prepared = object.__new__(PreparedSourceMenu)
    for key, value in (('admission', admission), ('payload_epoch', before), ('input_epoch', inputs),
            ('_anchors', anchors), ('_admission_sha256', admission.admission_sha256), ('_seal', _PREPARED_SEAL)):
        object.__setattr__(prepared, key, value)
    return prepared


def source_menu_for_launch(prepared: PreparedSourceMenu, *, deadline: float) -> SourceMenuSelection:
    """Attach this launch's existing cap without re-running or renewing admission."""
    _deadline(deadline, maximum=SOURCE_PREPARATION_SECONDS)
    _require_prepared(prepared)
    _pending_zero()
    _deadline(deadline)
    selection = object.__new__(SourceMenuSelection)
    for key, value in (('prepared', prepared), ('launch_deadline', deadline), ('_seal', _SELECTION_SEAL)):
        object.__setattr__(selection, key, value)
    return selection


def _verify_runtime(prepared, deadline):
    _require_prepared(prepared)
    _deadline(deadline)
    _pending_zero()
    _unchanged_epochs(prepared, deadline)
    for anchor in prepared._anchors:
        digest, _, state = gate._hash_file(anchor.path, deadline=deadline, limit=anchor.limit)
        if state != anchor.state or state.file[3] != anchor.size or digest != anchor.sha256:
            raise ValueError('Source menu critical anchor changed; a new preparation is required')
    prepared.admission.verify_provider_files(deadline)
    _unchanged_epochs(prepared, deadline)
    _deadline(deadline)
    _pending_zero()
    _deadline(deadline)


def _command_root(command, suite, prepared):
    root = prepared.admission.suite_root
    if (str(_absolute(suite)) != str(root) or not isinstance(command, (list, tuple)) or not command
            or not isinstance(command[0], (str, Path)) or not Path(command[0]).is_absolute()
            or str(_absolute(command[0])) != str(root/'OpenGeul.Office.exe')):
        raise ValueError('Source menu launch suite or executable root differs')


def _verify_source_menu_launch(selection, command, suite):
    _require_selection(selection)
    _deadline(selection.launch_deadline)
    _command_root(command, suite, selection.prepared)
    _verify_runtime(selection.prepared, selection.launch_deadline)


def _source_menu_launch_ready(selection, command, suite):
    """Recheck after pointer/file setup, with pending0 directly before Popen."""
    _require_selection(selection)
    _deadline(selection.launch_deadline)
    _command_root(command, suite, selection.prepared)
    _unchanged_epochs(selection.prepared, selection.launch_deadline)
    _deadline(selection.launch_deadline)
    _pending_zero()
    _deadline(selection.launch_deadline)


def _process_selection(process):
    selection = getattr(process, 'opengeul_source_menu_selection', None)
    if selection is None:
        return None
    _require_selection(selection)
    _command_root(process.args, process.opengeul_suite_root, selection.prepared)
    if (getattr(process, 'opengeul_native_menu_point_profile', False) is not False
            or getattr(process, 'opengeul_native_menu_point_profile_version', 1) != 1
            or getattr(process, 'opengeul_native_menu_identity_diagnostic', 0) != 0):
        raise ValueError('Source menu selection cannot mix legacy or diagnostic profiles')
    return selection


def selected_native_menu_probe(process, deadline: float, clock, *, build, supplied=None):
    """Recheck each selected action's bytes; an old startup cap is not its clock."""
    selection = _process_selection(process)
    if selection is None:
        return supplied if supplied is not None else build(None)
    _deadline(deadline, maximum=5, clock=clock)
    _verify_runtime(selection.prepared, deadline)
    probe = supplied if supplied is not None else build(selection)
    if getattr(probe, 'source_selection', None) is not selection:
        raise ValueError('Source menu probe lost or changed its original selection')
    _deadline(deadline, clock=clock)
    _pending_zero()
    _deadline(deadline, clock=clock)
    return probe
