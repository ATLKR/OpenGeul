"""Explicit Windows adapter for a nonqualifying, two-fixture print comparison.

Importing this module performs no process, registry, network or printer action.
The effective WebView UDF and actual selected glyph fonts remain unobserved.
"""
import hashlib
import io
import json
import math
import os
from pathlib import Path
import stat
import struct
import time
import zlib

from paired_print_contract import Rejected, digest, integer, require, shape, validate_raster
from paired_print_diagnostic import RetainedLease, invoke_print

PROFILE_SCOPE = 'requested-owned-profile'
ACTUAL_PROFILE_KNOWN = False
MAX_JSON = 128 * 1024


def _identity(info):
    # Windows path and handle ctime can describe different timestamps.
    stamp=getattr(info,'st_birthtime_ns',None) if os.name=='nt' else info.st_ctime_ns
    require(type(stamp) is int,20)
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, stamp)


def _safe(info, *, directory=False):
    try:
        require(not getattr(info, 'st_file_attributes', 0) & 0x400, 20)
        require(stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode), 20)
        if not directory:
            require(info.st_nlink == 1, 20)
    except Rejected as error:
        # Existing stat only; no follow-up query, path or file body is retained.
        try:error.pairedFileStats = (getattr(info, 'st_size', None), getattr(info, 'st_nlink', None))
        except BaseException:pass
        raise


def _parents(path):
    require(len(path.parents) <= 64, 20)
    for parent in path.parents:
        _safe(parent.lstat(), directory=True)


def _read_checked(path, limit, *, clock, check_file, identity):
    path = Path(path).absolute()
    _parents(path)
    before = path.lstat()
    check_file(before)
    require(0 < before.st_size <= limit, 20)
    start = clock()
    require(type(start) in (int, float) and math.isfinite(start), 20)
    chunks, size = [], 0
    with path.open('rb') as stream:
        opened = os.fstat(stream.fileno())
        check_file(opened)
        require(identity(before) == identity(opened), 20)
        while True:
            block = stream.read(min(1024 * 1024, limit + 1 - size))
            size += len(block)
            now = clock()
            require(type(now) in (int, float) and math.isfinite(now)
                    and start <= now < start + 10 and size <= limit, 20)
            if not block:
                break
            chunks.append(block)
        after=os.fstat(stream.fileno())
        check_file(after)
        require(identity(opened) == identity(after) and opened.st_ctime_ns == after.st_ctime_ns, 20)
    final=path.lstat()
    check_file(final)
    require(identity(before) == identity(final) and before.st_ctime_ns == final.st_ctime_ns
            and size == before.st_size, 20)
    return b''.join(chunks), before


def read_regular(path, limit, *, clock=time.monotonic):
    # The public payload/evidence reader always retains its single-link policy.
    return _read_checked(path, limit, clock=clock, check_file=_safe, identity=_identity)


def fingerprint_file(path, limit=96 * 1024 * 1024):
    data, info = read_regular(path, limit)
    return {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data),
            'volume': info.st_dev, 'fileId': info.st_ino, 'modifiedNs': info.st_mtime_ns}


def read_json(path, limit=MAX_JSON):
    integer(limit, 1, 512 * 1024)
    data, _ = read_regular(path, limit)
    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 20)
            result[key] = value
        return result
    try:
        return json.loads(data.decode('utf-8'), object_pairs_hook=object_pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(Rejected(20)))
    except (UnicodeError, json.JSONDecodeError):
        raise Rejected(20) from None


def requested_profile(session):
    """Filesystem identity of the requested profile, not its effective selection."""
    path = Path(session.profile).absolute()
    _parents(path)
    info = path.lstat()
    _safe(info, directory=True)
    require(info.st_ino > 0, 21)
    return {'scopeCode': 1, 'actualSelectedProfileKnown': False,
            'volume': info.st_dev, 'fileId': info.st_ino,
            'createdNs': info.st_ctime_ns}


def _font_safe(info):
    """Read-only fixed OS samples only; no general hard-link exception."""
    try:
        require(not getattr(info, 'st_file_attributes', 0) & 0x400, 20)
        require(stat.S_ISREG(info.st_mode), 20)
        # Support only the observed domain, not arbitrary link counts.
        require(type(info.st_nlink) is int and info.st_nlink in (1, 2), 20)
    except Rejected as error:
        try:error.pairedFileStats = (getattr(info, 'st_size', None), getattr(info, 'st_nlink', None))
        except BaseException:pass
        raise


def _font_identity(info):
    # Both allowed counts must stay identical across all four stat samples.
    return (*_identity(info), info.st_nlink)


def _font_fingerprint(path, fonts_root):
    """Private fixed-name path join; no caller flag changes the public reader."""
    path, fonts_root = Path(path), Path(fonts_root)
    require(fonts_root.is_absolute() and fonts_root.name == 'Fonts'
            and not str(fonts_root).startswith(('\\\\', '//'))
            and path.is_absolute() and path.parent == fonts_root
            and path.name in ('arial.ttf', 'malgun.ttf'), 20)
    data, info = _read_checked(path, 32 * 1024 * 1024, clock=time.monotonic,
                              check_file=_font_safe, identity=_font_identity)
    return {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data),
            'volume': info.st_dev, 'fileId': info.st_ino, 'modifiedNs': info.st_mtime_ns}


def sampled_fonts():
    """Two system-directory samples, not glyph/authenticity/ACL evidence.

    Aliases can modify the same file. Per-read identity/link-count stability and
    the existing later content/identity rechecks remain required.
    """
    import ctypes
    from ctypes import wintypes as W
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    get_windows = kernel.GetSystemWindowsDirectoryW
    get_windows.argtypes, get_windows.restype = [W.LPWSTR, W.UINT], W.UINT
    buffer = ctypes.create_unicode_buffer(32768)
    size = int(get_windows(buffer, len(buffer)))
    require(0 < size < len(buffer), 22)
    windows = Path(buffer.value)
    require(windows.is_absolute() and not str(windows).startswith(('\\\\', '//')), 22)
    folder = windows / 'Fonts'
    rows = []
    for code, name in ((1, 'arial.ttf'), (2, 'malgun.ttf')):
        path = folder / name
        if not path.exists() and not path.is_symlink():
            row = {'present': False, 'bytes': 0, 'sha256': None,
                   'volume': 0, 'fileId': 0, 'modifiedNs': 0}
        else:
            try:
                row = {'present': True, **_font_fingerprint(path, folder)}
            except BaseException as error:
                try:error.pairedFontCode = code
                except BaseException:pass
                raise
        rows.append({'fontCode': code, **row})
    return {'scopeCode': 1, 'files': rows}


def is_ink_mismatch(error):
    """Exact owned PDF wrapper and immediate matcher context, never messages."""
    import ast
    import inspect
    import print_raster
    if (type(error) is not ValueError or type(error.__context__) is not ValueError
            or error.__cause__ is not None or error.__suppress_context__):
        return False
    source, first = inspect.getsourcelines(print_raster.match_reference)
    tree = ast.parse(''.join(source))
    final = tree.body[0].body[-1]
    require(type(final) is ast.Raise, 23)
    matcher_line = first + final.lineno - 1
    wrapper_source, wrapper_first = inspect.getsourcelines(print_raster.inspect_print_pdf)
    wrapper_tree = ast.parse(''.join(wrapper_source))
    wrappers = [node.body[-1] for node in ast.walk(wrapper_tree)
                if type(node) is ast.ExceptHandler and type(node.type) is ast.Name
                and node.type.id == 'ValueError' and node.body
                and type(node.body[-1]) is ast.Raise]
    require(len(wrappers) == 1, 23)
    wrapper_line = wrapper_first + wrappers[0].lineno - 1

    def owned_frame(value, code, line):
        frame = value.__traceback__
        while frame is not None:
            if frame.tb_frame.f_code is code and frame.tb_lineno == line:
                return True
            frame = frame.tb_next
        return False
    return (owned_frame(error, print_raster.inspect_print_pdf.__code__, wrapper_line)
            and owned_frame(error.__context__, print_raster.match_reference.__code__, matcher_line))


def read_single_raster(pdf, case):
    """Independent single-page geometry and the unchanged PDFium fingerprint."""
    import pypdfium2 as pdfium
    from print_raster import SCALE, fingerprint
    data, _ = read_regular(pdf, 20_000_000)
    require(data.startswith(b'%PDF-') and data.rstrip().endswith(b'%%EOF'), 24)
    require(type(case['pages']) is list and len(case['pages']) == 1, 24)
    wanted = case['pages'][0]['size_pt']
    require(type(wanted) is list and len(wanted) == 2, 24)
    with pdfium.PdfDocument(data) as document:
        require(len(document) == 1, 24)
        page = document[0]
        bitmap = None
        try:
            size = page.get_size()
            require(all(type(x) in (int, float) and math.isfinite(x) and 50 <= x <= 1200
                        for x in (*size, *wanted)), 24)
            require(all(abs(a - b) <= 1 for a, b in zip(size, wanted)), 24)
            bitmap = page.render(scale=SCALE)
            result = fingerprint(bitmap.to_pil().convert('L'))
            validate_raster(result)
            return {'raster': result, 'pdfSha256': hashlib.sha256(data).hexdigest(), 'pdfBytes': len(data)}
        finally:
            if bitmap is not None:
                bitmap.close()
            page.close()


def validate_runtime(runtime, renderer, fixture, exe, session, helper_sha):
    """Current harness source is separate from the renderer's compile source."""
    digest(helper_sha)
    require(type(runtime) is dict and runtime.get('mode') == 'native'
            and runtime.get('executableSha256') == renderer['executableSha256']
            and runtime.get('fixtureSha256') == fixture['sha256'], 27)
    app = runtime.get('nativeArchitecture')
    require(type(app) is dict and app.get('architecture') == 'x64'
            and app.get('native') is True and app.get('runningAtInspection') is True, 27)
    for key, wanted in (('processId', session.proc.pid), ('peMachine', 0x8664),
                        ('processMachine', 0), ('nativeMachine', 0x8664),
                        ('bytes', renderer['executableBytes'])):
        require(type(app.get(key)) is int and app[key] == wanted, 27)
    require(app.get('sha256') == renderer['executableSha256']
            and app.get('helperSha256') == helper_sha
            and app.get('sourceCommit') == renderer['harnessSourceCommit']
            and app.get('sourceRun') == str(renderer['harnessRunId'])
            and app.get('runAttempt') == str(renderer['harnessRunAttempt']), 27)
    require(type(app.get('imagePath')) is str and Path(app['imagePath']).resolve() == exe.resolve(), 27)


def fingerprint_png(data):
    """The original grayscale encoder uses IHDR/IDAT/IEND, not text metadata."""
    from PIL import Image
    from print_raster import fingerprint
    require(type(data) is bytes and 33 <= len(data) <= 8 * 1024 * 1024
            and data[:8] == b'\x89PNG\r\n\x1a\n', 28)
    offset, chunks, idats, ended = 8, 0, 0, False
    while offset < len(data):
        require(chunks < 1024 and offset + 12 <= len(data), 28)
        length = struct.unpack('>I', data[offset:offset + 4])[0]
        kind = data[offset + 4:offset + 8]
        require(length <= 8 * 1024 * 1024 and offset + 12 + length <= len(data), 28)
        payload = data[offset + 8:offset + 8 + length]
        crc = struct.unpack('>I', data[offset + 8 + length:offset + 12 + length])[0]
        require(zlib.crc32(kind + payload) & 0xffffffff == crc, 28)
        require(kind in (b'IHDR', b'IDAT', b'IEND') and not ended, 28)
        if kind == b'IHDR':
            require(chunks == 0 and length == 13 and payload[8:] == b'\x08\x00\x00\x00\x00', 28)
            width, height = struct.unpack('>II', payload[:8])
            require(0 < width <= 12000 and 0 < height <= 12000 and width * height <= 16_000_000, 28)
        elif kind == b'IDAT':
            require(chunks > 0, 28)
            idats += 1
        else:
            require(length == 0 and idats > 0, 28)
            ended = True
        chunks += 1
        offset += length + 12
    require(ended and offset == len(data), 28)
    with Image.open(io.BytesIO(data)) as image:
        require(image.format == 'PNG' and image.mode == 'L', 28)
        result = fingerprint(image)
    validate_raster(result)
    return result


class WindowsPort:
    """Each attempt has fresh Session/queue resources and a retained exit barrier."""
    def __init__(self, executables, cases, work, *, printer=None, lease_factory=RetainedLease,
                 raster_reader=read_single_raster, oracle_error=is_ink_mismatch,
                 font_reader=sampled_fonts, native_helper_sha=None):
        self.executables, self.cases = executables, cases
        self.work = Path(work).absolute()
        _parents(self.work)
        require(not self.work.exists() and not self.work.is_symlink(), 25)
        self.work.mkdir()
        if printer is None:
            from virtual_print import print_document
            printer = print_document
        self.printer, self.lease_factory = printer, lease_factory
        self.native_helper_sha = native_helper_sha or fingerprint_file(
            Path(__file__).with_name('native_architecture.py'))['sha256']
        digest(self.native_helper_sha)
        self.raster_reader, self.oracle_error, self.font_reader = raster_reader, oracle_error, font_reader
        self.primary = None
        self.profile_observations, self.attempts = [], []

    def font_snapshot(self):
        return self.font_reader()

    def print_case(self, renderer, fixture):
        role, code = renderer['roleCode'], fixture['caseCode']
        integer(role, 1, 2)
        require(type(code) is int and code in (1, 6), 25)
        require((role, code) not in self.attempts, 25)
        exe, case = Path(self.executables[role]), self.cases[code]
        source = Path(case['path'])
        before, binary = fingerprint_file(source, 20 * 1024 * 1024), fingerprint_file(exe)
        require((before['sha256'], before['bytes']) == (fixture['sha256'], fixture['bytes']), 25)
        require((binary['sha256'], binary['bytes']) ==
                (renderer['executableSha256'], renderer['executableBytes']), 25)
        folder = self.work / f'role-{role}-case-{code}'
        self.attempts.append((role, code))

        def admission(session, observed):
            require(Path(observed) == folder, 25)
            profile = requested_profile(session)
            runtime = read_json(folder / 'session/runtime.json')
            validate_runtime(runtime, renderer, fixture, exe, session, self.native_helper_sha)
            lease = self.lease_factory(session, runtime)
            self.profile_observations.append({'roleCode': role, 'caseCode': code, **profile})
            return lease

        report, primary, retirement = invoke_print(self.printer, exe, source, case, folder,
                                                   admission, self.oracle_error)
        if primary is not None:
            try:primary.pairedRole = role
            except BaseException:pass
        if primary is not None and self.primary is None:
            self.primary = primary
        try:
            after = fingerprint_file(source, 20 * 1024 * 1024)
            require(before == after and fingerprint_file(exe) == binary, 25)
            preserved = read_json(folder / 'source-preservation.json')
            shape(preserved, ('before', 'after', 'unchanged'))
            require(preserved['before'] == preserved['after'] == fixture['sha256']
                    and preserved['unchanged'] is True, 25)
            from print_results import completed_job
            spool = read_json(folder / 'spooler.json')
            shape(spool, ('queue', 'jobs', 'jobMedia'))
            require(type(spool['queue']) is str and spool['queue'].startswith('OpenGeul-CI-'), 25)
            require(completed_job(spool['jobs'], spool['queue'], source.name,
                                  1, spool['jobMedia']) is not None, 25)
            reading = self.raster_reader(folder / 'printed.pdf', case)
            shape(reading, ('raster', 'pdfSha256', 'pdfBytes'))
            raster = reading['raster']
            validate_raster(raster)
            artifacts = {}
            for prefix, path in (('pdf', folder / 'printed.pdf'), ('png', folder / 'pdf-check/page-1.png')):
                fp = fingerprint_file(path, 8 * 1024 * 1024)
                artifacts[prefix + 'Sha256'], artifacts[prefix + 'Bytes'] = fp['sha256'], fp['bytes']
            require(artifacts['pdfSha256'] == reading['pdfSha256']
                    and artifacts['pdfBytes'] == reading['pdfBytes'], 28)
            png, _ = read_regular(folder / 'pdf-check/page-1.png', 8 * 1024 * 1024)
            require(hashlib.sha256(png).hexdigest() == artifacts['pngSha256']
                    and len(png) == artifacts['pngBytes'] and fingerprint_png(png) == raster, 28)
            if primary is None:
                require(type(report) is dict and type(report.get('checks')) is list
                        and len(report['checks']) == 1, 25)
                require(all(report['checks'][0].get(key) == value for key, value in raster.items()), 25)
                require(report.get('sha256') == reading['pdfSha256'], 28)
            else:
                mismatch = read_json(folder / 'pdf-check/page-1-mismatch.json')
                shape(mismatch, ('expected', 'actual'))
                validate_raster(mismatch['expected'])
                require(mismatch['actual'] == raster, 28)
            return {key: renderer[key] for key in (
                'roleCode', 'harnessSourceCommit', 'harnessRunId', 'harnessRunAttempt',
                'appSourceCommit', 'executableSha256', 'executableBytes')} | {
                'caseCode': code, 'wasmProvenanceSha256': renderer['wasmSha256'],
                'fixtureBeforeSha256': before['sha256'], 'fixtureAfterSha256': after['sha256'],
                'pdfCreated': True, 'spoolerCompleted': True, 'paperValidated': True,
                'originalOraclePassed': primary is None, 'primaryErrorCode': int(primary is not None),
                'raster': raster, 'cleanupMayBeForced': True, **retirement, **artifacts}
        except BaseException:
            if primary is not None:
                raise primary
            raise

    def raise_original_oracle(self):
        if self.primary is not None:
            raise self.primary
