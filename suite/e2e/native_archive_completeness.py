"""Join source-fixed original product cases to manifest-hashed native shutdowns.

This is archive coverage, separate from internal native trace completeness.
Only identities, static case labels and file descriptors enter its result.
"""
from __future__ import annotations
import hashlib
import json
import ntpath
from pathlib import Path, PurePosixPath
import re
import stat
from suite.e2e.native_cleanup_receipt import MAX_RECEIPT_BYTES, load_cleanup_receipt, validate_cleanup_receipt
MAX_REPORT_BYTES = 128 * 1024 * 1024
MAX_TOTAL_REPORT_BYTES = 512 * 1024 * 1024
SHARED = '.work/suite-worker-diagnostics'

def _positive(value):
    if not (type(value) is int and 0 < value <= 18446744073709551615):
        raise ValueError('Missing exact positive original identity')
    return value

def _image(value):
    if not (type(value) is str and value and ('\x00' not in value)):
        raise ValueError('Missing original packaged image')
    return ntpath.normcase(ntpath.normpath(value))

def _plain(path):
    path = Path(path)
    for item in (path, *path.parents):
        info = item.lstat()
        if not (not stat.S_ISLNK(info.st_mode) and (not getattr(info, 'st_file_attributes', 0) & 1024)):
            raise ValueError('Linked original coverage path')
    return path.lstat()

def _bytes(path, maximum):
    info = _plain(path)
    if not (stat.S_ISREG(info.st_mode) and 0 < info.st_size <= maximum):
        raise ValueError('Original coverage file exceeds its bound')
    with path.open('rb') as stream:
        raw = stream.read(maximum + 1)
    if not (len(raw) == info.st_size and len(raw) <= maximum):
        raise ValueError('Original coverage file changed size')
    return raw

def _pairs(items):
    result = {}
    for key, value in items:
        if not key not in result:
            raise ValueError('Duplicate original coverage JSON key')
        result[key] = value
    return result

def _json(raw):

    def constant(value):
        raise ValueError('Nonfinite original coverage JSON')
    value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=constant)
    if not type(value) is dict:
        raise ValueError('Original coverage record must be an object')
    return value

def source_plans():
    from suite.e2e import windows_smoke as native
    import startup_smoke
    import korean_ui_smoke
    import writer_style_smoke
    import lifecycle_smoke
    import calc_save_smoke
    import calc_close_probe
    gui = ('home',) + native.NEW_MODULES + tuple(('new-' + module for module in native.NEW_MODULES))
    lifecycle = {'dirty-writer-cancel-save': 1, 'dirty-writer-discard': 1, 'new-writer-saveas-cancel': 1, 'failed-saveas-retains-editor': 1, 'home-two-documents-cancel': 2, 'resize-minimize-restore': 1, 'hwp-tile-hwpx-route': 0}
    if not tuple(lifecycle) == tuple(lifecycle_smoke.CASE_REQUIREMENTS):
        raise ValueError('Lifecycle source coverage plan changed')
    plans = []

    def add(scope, field, names, counts, kind, root=lambda name: SHARED):
        plans.append(dict(scope=scope, path='.work/' + scope + '/results.json', field=field, kind=kind, cases=[dict(case=name, count=counts(name), root=root(name)) for name in names]))
    for scope in ('suite-native', 'suite-native-2'):
        add(scope, 'tests', gui, lambda name: 0 if name == 'home' else 1, 'gui')
    add('suite-startup', 'attempts', [row['case'] for row in startup_smoke.build_plan(40)], lambda name: 1, 'top')
    add('suite-korean-ime', 'tests', ['ime-' + module for module, _ in native.INPUT_CASES], lambda name: 1, 'ime')
    add('suite-korean-ui', 'tests', ['korean-ui-' + module for module in korean_ui_smoke.MODULES], lambda name: 1, 'top')
    add('suite-writer-style', 'tests', [writer_style_smoke.CASE], lambda name: 1, 'top')
    add('suite-lifecycle', 'tests', list(lifecycle), lifecycle.__getitem__, 'lifecycle')
    add('suite-calc-save', 'tests', [calc_save_smoke.CASE], lambda name: 1, 'calc', lambda name: '.work/suite-calc-save/diagnostics')
    add('suite-calc-close', 'tests', ['calc-close-' + choice for choice in calc_close_probe.CHOICES], lambda name: 1, 'calc', lambda name: '.work/suite-calc-close/' + name + '/diagnostics')
    return plans

def _generation(value, expected_image, *, exact=False):
    if not type(value) is dict:
        raise ValueError('Original engine generation is missing')
    if exact:
        if not set(value) == {'pid', 'creationTime', 'image'}:
            raise ValueError('Original attachment generation schema changed')
    result = {key: value.get(key) for key in ('pid', 'creationTime', 'image')}
    _positive(result['pid'])
    _positive(result['creationTime'])
    if not _image(result['image']) == _image(expected_image):
        raise ValueError('Original engine image is outside the packaged runtime')
    result['image'] = expected_image
    return result

def _attachment(row):
    return dict(hwnd=row.get('windowHwnd'), parent=row.get('parentHwnd'), child=row.get('childHwnd'), officePid=row.get('officePid'))

def _shell(row, attachment, suite):
    shell = _positive(row.get('shellPid'))
    if not shell != _positive(attachment.get('officePid')):
        raise ValueError('Original engine and Suite shell identity collide')
    activations = row.get('windowActivations')
    if not (type(activations) is list and 0 < len(activations) <= 64):
        raise ValueError('Original retained shell activation receipt missing')
    matched = [item for item in activations if type(item) is dict and item.get('suiteHwnd') == attachment.get('hwnd')]
    if not matched:
        raise ValueError('Original case has no retained shell for its attachment')
    identities = set()
    for item in matched:
        original = item.get('originalProcess')
        if not (type(original) is dict and original.get('pid') == shell):
            raise ValueError('Original attachment belongs to another Suite shell')
        identities.add((_positive(original.get('creationTime')), _positive(original.get('handleValue'))))
        if not (_image(original.get('image')) == _image(str(suite / 'OpenGeul.Office.exe')) and type(original.get('waitResult')) is int and (original['waitResult'] == 258)):
            raise ValueError('Original Suite shell was not the retained live packaged process')
    if not len(identities) == 1:
        raise ValueError('Original Suite shell generation changed')
    return shell

def _original_generation(row, attachment, kind, expected_image):
    candidates = []
    if kind == 'top':
        candidates.append(dict(pid=row.get('officePid'), creationTime=row.get('officeCreationTime'), image=expected_image))
    elif kind in ('ime', 'calc'):
        binding = row.get('imeKeyboardSession', {}).get('expectedNative') if kind == 'ime' else row.get('beforeInput', {}).get('bindingBefore')
        if not (type(binding) is dict and binding.get('shellPid') == row.get('shellPid')):
            raise ValueError('Original model/keyboard shell binding missing')
        candidates.append(dict(pid=binding.get('officePid'), creationTime=binding.get('officeCreationTime'), image=binding.get('expectedImage')))
    else:
        carrier = attachment if kind == 'lifecycle' else row
        if 'nativeArchiveGeneration' in carrier:
            candidates.append(_generation(carrier['nativeArchiveGeneration'], expected_image, exact=True))
        sessions = row.get('editorShortcutSessions', [])
        if not (type(sessions) is list and len(sessions) <= 64):
            raise ValueError('Original shortcut generation list is invalid')
        for session in sessions:
            if not type(session) is dict:
                raise ValueError('Original shortcut generation entry is invalid')
            if session.get('attachment') == {key: attachment.get(key) for key in ('hwnd', 'parent', 'child', 'officePid')}:
                if not (type(session.get('originalShell')) is dict and session['originalShell'].get('pid') == row.get('shellPid')):
                    raise ValueError('Original shortcut Suite shell differs')
                candidates.append(_generation(session.get('originalEngine'), expected_image))
    if not candidates:
        raise ValueError('Unbound original attachment generation')
    candidates = [_generation(value, expected_image) for value in candidates]
    if not all((value == candidates[0] for value in candidates)):
        raise ValueError('Original attachment generation changed or is ambiguous')
    if not candidates[0]['pid'] == attachment.get('officePid'):
        raise ValueError('Original attachment PID differs from its retained generation')
    return candidates[0]

def _expected(workspace, suite):
    expected = {}
    descriptors = []
    total = 0
    image = str(suite / 'Office/program/soffice.bin')
    for plan in source_plans():
        path = workspace / plan['path']
        raw = _bytes(path, MAX_REPORT_BYTES)
        total += len(raw)
        if not total <= MAX_TOTAL_REPORT_BYTES:
            raise ValueError('Original report aggregate exceeds its bound')
        report = _json(raw)
        if not report.get('success') is True:
            raise ValueError('Original case report did not pass')
        rows = report.get(plan['field'])
        if not (type(rows) is list and len(rows) <= 128):
            raise ValueError('Original case report list missing')
        if not [row.get('case') if type(row) is dict else None for row in rows] == [item['case'] for item in plan['cases']]:
            raise ValueError('Original source case coverage missing, duplicated, unexpected or reordered')
        descriptors.append(dict(path=plan['path'], bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()))
        for row, item in zip(rows, plan['cases']):
            if not row.get('success') is True:
                raise ValueError('Original planned case did not pass')
            frames = row.get('attachments', []) if plan['kind'] == 'lifecycle' else [] if item['count'] == 0 else [_attachment(row)]
            if not (type(frames) is list and len(frames) == item['count']):
                raise ValueError('Original case attachment coverage differs from its source plan')
            if not frames:
                if not (not row.get('nativeArchiveGeneration') and (not row.get('officePid'))):
                    raise ValueError('No-engine case claimed an Office generation')
            for slot, frame in enumerate(frames):
                if not type(frame) is dict:
                    raise ValueError('Original attachment entry missing')
                for name in ('hwnd', 'parent', 'child', 'officePid'):
                    _positive(frame.get(name))
                shell = _shell(row, frame, suite)
                generation = _original_generation(row, frame, plan['kind'], image)
                key = (generation['pid'], generation['creationTime'], _image(generation['image']))
                if not key not in expected:
                    raise ValueError('Duplicate original engine generation across planned cases')
                expected[key] = dict(scope=plan['scope'], case=item['case'], slot=slot, suiteShellPid=shell, root=item['root'], **generation)
    return (expected, descriptors)

def _archived(workspace, roots, image):
    result = []
    for relative in sorted(roots):
        root = workspace / relative
        if not stat.S_ISDIR(_plain(root).st_mode):
            raise ValueError('Original native diagnostics root missing')
        entries = list(root.iterdir())
        if not len(entries) <= 4096:
            raise ValueError('Native root entry bound exceeded')
        for folder in entries:
            info = _plain(folder)
            if stat.S_ISREG(info.st_mode):
                if not re.fullmatch('worker-save-[1-9][0-9]*-[0-9a-f]{32}\\.jsonl', folder.name):
                    raise ValueError('Unexpected native root file')
                continue
            if not (stat.S_ISDIR(info.st_mode) and re.fullmatch('[0-9a-f]{32}', folder.name)):
                raise ValueError('Unexpected native archive directory')
            manifest_path = folder / 'manifest.json'
            manifest_raw = _bytes(manifest_path, 1024 * 1024)
            manifest = _json(manifest_raw)
            if not (type(manifest.get('schemaVersion')) is int and manifest['schemaVersion'] == 1 and (manifest.get('kind') == 'owned-office-native-diagnostics') and (manifest.get('archiveComplete') is True)):
                raise ValueError('Native archive is incomplete or unbound')
            files = manifest.get('files')
            if not (type(files) is list and len(files) <= 4096):
                raise ValueError('Native archive file list missing')
            seen = set()
            shutdown_raw = None
            for item in files:
                if not type(item) is dict:
                    raise ValueError('Invalid native archive member')
                name = item.get('path')
                if not (type(name) is str and name and ('\\' not in name) and (':' not in name)):
                    raise ValueError('Unsafe native archive member')
                part = PurePosixPath(name)
                if not (not part.is_absolute() and '..' not in part.parts and (part.as_posix() == name) and (name not in seen)):
                    raise ValueError('Aliased native archive member')
                seen.add(name)
                raw = _bytes(folder.joinpath(*part.parts), 16 * 1024 * 1024)
                if not (type(item.get('bytes')) is int and item['bytes'] == len(raw) and (type(item.get('sha256')) is str) and re.fullmatch('[0-9a-f]{64}', item['sha256']) and (hashlib.sha256(raw).hexdigest() == item['sha256'])):
                    raise ValueError('Native archive member hash differs')
                if name == 'shutdown.json':
                    shutdown_raw = raw
            if not (shutdown_raw is not None and len(shutdown_raw) <= MAX_RECEIPT_BYTES):
                raise ValueError('Native archive shutdown proof missing')
            actual = set()
            for member in folder.rglob('*'):
                info = _plain(member)
                if stat.S_ISREG(info.st_mode):
                    actual.add(member.relative_to(folder).as_posix())
                    with member.open('rb') as stream:
                        signature = stream.read(4)
                    if not (member.suffix.lower() not in ('.dmp', '.mdmp') and signature != b'MDMP'):
                        raise ValueError('Native crash dump found')
                elif not stat.S_ISDIR(info.st_mode):
                    raise ValueError('Nonregular native archive member')
                if not len(actual) <= 4096:
                    raise ValueError('Native archive member count exceeded')
            if not seen | {'manifest.json'} <= actual <= seen | {'manifest.json', 'events.jsonl'}:
                raise ValueError('Unlisted native archive member')
            cleanup = load_cleanup_receipt(shutdown_raw)
            validate_cleanup_receipt(cleanup, expected_engine_image=image, launcher_pid=manifest.get('launcherPid'))
            engines = [row for row in cleanup['finalMembers'] if _image(row.get('image')) == _image(image)]
            if not len(engines) == 1:
                raise ValueError('Native shutdown has ambiguous engine generation')
            engine = engines[0]
            result.append(dict(root=relative, pid=engine['pid'], creationTime=engine['creationTime'], image=image, engineLauncherPid=manifest['launcherPid'], manifest=manifest_path.relative_to(workspace).as_posix(), manifestSha256=hashlib.sha256(manifest_raw).hexdigest(), shutdownSha256=hashlib.sha256(shutdown_raw).hexdigest()))
    return result

def verify_native_archive_completeness(workspace, suite):
    workspace, suite = (Path(workspace), Path(suite))
    if not (workspace.is_absolute() and suite.is_absolute()):
        raise ValueError('Absolute original coverage roots required')
    _plain(workspace)
    _plain(suite)
    expected, descriptors = _expected(workspace, suite)
    roots = {row['root'] for row in expected.values()}
    archives = _archived(workspace, roots, str(suite / 'Office/program/soffice.bin'))
    matched = set()
    proofs = []
    for archive in archives:
        key = (archive['pid'], archive['creationTime'], _image(archive['image']))
        if not key in expected:
            raise ValueError('Orphan native archive generation outside original case coverage')
        if not key not in matched:
            raise ValueError('Duplicate native archive generation')
        original = expected[key]
        if not original['root'] == archive['root']:
            raise ValueError('Original case archive belongs to another native root')
        matched.add(key)
        proofs.append(dict(original, **{key: value for key, value in archive.items() if key not in original}))
    if not matched == set(expected):
        raise ValueError('Missing original generation native archive coverage')
    return dict(schemaVersion=1, kind='native-archive-generation-completeness', success=True, expectedGenerations=len(expected), matchedGenerations=len(matched), sourceReceipts=descriptors, archives=proofs)
