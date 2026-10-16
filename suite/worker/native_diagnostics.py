"""Opt-in evidence for our own Office process/profile; never a recovery path."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import uuid


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
        self.manifest = {'schemaVersion': 1, 'ownedProfile': str(profile),
                         'workerPid': os.getpid(), 'launcherPid': getattr(process, 'pid', None),
                         'archiveComplete': False, 'files': []}
        self._write_manifest()

    def _write_manifest(self):
        (self.directory / 'manifest.json').write_text(
            json.dumps(self.manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    def record(self, phase):
        event = {'phase': phase, 'utc': datetime.now(timezone.utc).isoformat()}
        try:
            if self.process is not None:
                if self.witnesses is None:
                    self.witnesses = self.process.open_diagnostic_witnesses()
                event['processes'] = self.witnesses.snapshot()
        except Exception as exc:
            event['processQueryError'] = {'type': type(exc).__name__, 'message': str(exc),
                                          'winerror': getattr(exc, 'winerror', None)}
        with (self.directory / 'events.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + '\n')

    def archive_crash(self):
        # Nothing outside this registered private profile/crash is eligible.
        plain_path(self.profile)
        crash = plain_path(self.profile / 'crash')
        if not crash.exists():
            self.manifest['crashDirectoryPresent'] = False
            self.manifest['archiveComplete'] = True
            self._write_manifest()
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

    def close(self):
        if self.witnesses is not None:
            self.witnesses.close()
            self.witnesses = None
