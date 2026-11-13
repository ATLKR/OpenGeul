"""Opt-in evidence for our own Office process/profile; never a recovery path."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import uuid

MAX_EVENTS_BYTES = 16 * 1024 * 1024


def plain_path(path):
    path = Path(path)
    for item in (path, *path.parents):
        if item.is_symlink() or (hasattr(item, 'is_junction') and item.is_junction()):
            raise ValueError('Diagnostic paths must not traverse links: ' + str(item))
    return path


def create_diagnostics(environment, payload, profile, process):
    raw = environment.get('OPENGEUL_SUITE_DIAGNOSTICS')
    if not raw:
        return None
    root = Path(raw)
    if (not root.is_absolute() or str(root).startswith(('\\\\', '//'))
            or '..' in root.parts):
        raise ValueError('Diagnostics require an explicit local absolute directory')
    plain_path(root)
    root = root.resolve()
    for protected in (Path(payload).resolve(), Path(profile).resolve()):
        if root == protected or protected in root.parents:
            raise ValueError('Diagnostics must be outside the payload and private profile')
    root.mkdir(parents=True, exist_ok=True)
    return NativeDiagnostics(root, plain_path(Path(profile)).resolve(), process)


class NativeDiagnostics:
    def __init__(self, root, profile, process):
        self.directory = root / uuid.uuid4().hex
        self.directory.mkdir(exist_ok=False)
        self.profile, self.process, self.witnesses = profile, process, None
        self._events_sealed = self._event_write_failed = self._crash_complete = False
        self.manifest = {'schemaVersion': 1, 'kind': 'owned-office-native-diagnostics', 'ownedProfile': str(profile),
                         'workerPid': os.getpid(), 'launcherPid': getattr(process, 'pid', None),
                         'archiveComplete': False, 'files': []}
        self._write_manifest()

    def _write_manifest(self):
        (self.directory / 'manifest.json').write_text(
            json.dumps(self.manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    def record(self, phase, metadata=None):
        try:
            if self._events_sealed:
                self._invalidate_event_seal()
            self._record_event(phase, metadata)
        except Exception:
            self._event_write_failed = True
            try:
                self._invalidate_event_seal()
            except Exception:
                pass
            raise

    def _record_event(self, phase, metadata):
        event = {'phase': phase, 'utc': datetime.now(timezone.utc).isoformat()}
        if metadata is not None:
            event['metadata'] = metadata
        try:
            if self.process is not None:
                if self.witnesses is None:
                    self.witnesses = self.process.open_diagnostic_witnesses()
                event['processes'] = self.witnesses.snapshot()
        except Exception as exc:
            event['processQueryError'] = {'type': type(exc).__name__, 'message': str(exc),
                                          'winerror': getattr(exc, 'winerror', None)}
        with (self.directory / 'events.jsonl').open('a', encoding='utf-8') as stream:
            line = json.dumps(event, ensure_ascii=False, allow_nan=False) + '\n'
            if stream.write(line) != len(line):
                raise ValueError('Owned diagnostic event append was incomplete')

    def _invalidate_event_seal(self):
        self.manifest['archiveComplete'] = False
        self.manifest['files'] = [item for item in self.manifest['files'] if item['path'] != 'events.jsonl']
        self._write_manifest()
        self._events_sealed = False

    def _event_descriptor(self):
        if self._event_write_failed:
            raise ValueError('Owned diagnostic event append failed before sealing')
        try:
            path = plain_path(self.directory / 'events.jsonl')
            before = path.lstat()
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 0 < before.st_size <= MAX_EVENTS_BYTES:
                raise ValueError('Owned event stream type or size differs')
            def identity(info):
                return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_nlink
            digest = hashlib.sha256()
            count = 0; last = None
            with path.open('rb') as stream:
                if identity(os.fstat(stream.fileno())) != identity(before):
                    raise ValueError('Owned event stream changed before sealing')
                while True:
                    block = stream.read(min(65536, MAX_EVENTS_BYTES + 1 - count))
                    if not block:
                        break
                    count += len(block); last = block[-1]
                    if count > MAX_EVENTS_BYTES:
                        raise ValueError('Owned event stream exceeded its seal bound')
                    digest.update(block)
                after = os.fstat(stream.fileno())
            if (count != before.st_size or last != 10 or identity(after) != identity(before)
                    or identity(plain_path(path).lstat()) != identity(before)):
                raise ValueError('Owned event stream changed or ended partially')
            return dict(path='events.jsonl', bytes=count, sha256=digest.hexdigest())
        except (OSError, ValueError) as exc:
            raise ValueError('Owned diagnostic event stream could not be sealed') from exc

    def archive_crash(self):
        # Nothing outside this registered private profile/crash is eligible.
        plain_path(self.profile)
        crash = plain_path(self.profile / 'crash')
        if not crash.exists():
            self.manifest['crashDirectoryPresent'] = False
            self.manifest['archiveComplete'] = True
            self._write_manifest()
            self._crash_complete = True
            return
        if not crash.is_dir() or crash.resolve().parent != self.profile:
            raise ValueError('Crash evidence escaped the owned private profile')
        sources = []
        for directory, names, files in os.walk(crash, followlinks=False):
            for name in names:
                plain_path(Path(directory) / name)
            for name in files:
                source = plain_path(Path(directory) / name)
                if not stat.S_ISREG(source.lstat().st_mode):
                    raise ValueError('Only regular owned crash files can be archived')
                sources.append(source)
        archived = []
        for source in sorted(sources):
            relative = source.relative_to(self.profile)
            target = self.directory / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.open('rb') as incoming, target.open('xb') as outgoing:
                shutil.copyfileobj(incoming, outgoing)
            with target.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            archived.append({'path': relative.as_posix(), 'bytes': target.stat().st_size, 'sha256': digest})
        self.manifest.update(crashDirectoryPresent=True, archiveComplete=True, files=archived)
        self._write_manifest()
        self._crash_complete = True

    def close(self):
        if self.witnesses is not None:
            self.witnesses.close()
            self.witnesses = None

    def record_shutdown(self, record):
        """Bind the explicit final shutdown proof to this owned archive."""
        self._invalidate_event_seal()
        events = self._event_descriptor()
        target = plain_path(self.directory / 'shutdown.json')
        raw = (json.dumps(record, ensure_ascii=False, allow_nan=False, indent=2) + '\n').encode('utf-8')
        if len(raw) > 256 * 1024:
            raise ValueError('Owned shutdown receipt exceeded its finite limit')
        target.write_bytes(raw)
        files = [item for item in self.manifest['files'] if item['path'] not in ('shutdown.json', 'events.jsonl')]
        files.append(dict(path='shutdown.json', bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()))
        files.append(events)
        self.manifest['files'] = files
        self.manifest['archiveComplete'] = self._crash_complete
        self._write_manifest()
        self._events_sealed = True
