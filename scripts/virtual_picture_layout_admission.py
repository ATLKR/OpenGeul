"""Pin real-body admission before the picture-band scan; preserve virtual setters."""
from pathlib import Path
import hashlib
import stat

ROOT = Path(__file__).resolve().parents[1]
HELPER = 'scripts/virtual_picture_layout_admission.py'
SOURCE_FILES = ('third_party/rhwp/src/document_core/commands/text_editing.rs',)
INPUT_SOURCE_SHA256 = {'third_party/rhwp/src/document_core/commands/text_editing.rs': '12341f00051996a9f163cdd506a5111c3993eb9f107314272b3c0230f10df62c'}
OUTPUT_SOURCE_SHA256 = {'third_party/rhwp/src/document_core/commands/text_editing.rs': '2c71b1ef4a3d35ab3387b5713e118fc4e60acbc91b110ae7cd76e4c9c4775755'}
REPLACEMENTS = (('        let section = self.document.sections.get(section_idx)?;\n        let host_index = (0..=para_idx).rev().find(|&index| {', "        let section = self.document.sections.get(section_idx)?;\n        // Only a real body paragraph can participate in this body's picture band.\n        // Public picture setters also address virtual Endnote paragraphs.\n        section.paragraphs.get(para_idx)?;\n        let host_index = (0..=para_idx).rev().find(|&index| {"),)

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def regular(path):
    path = Path(path)
    for candidate in (path, *path.parents):
        if candidate.exists() or candidate.is_symlink():
            info = candidate.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise ValueError('Virtual picture layout admission source must not use symlink/reparse paths')
    if not path.is_file():
        raise ValueError('Missing pinned virtual picture layout admission source')

def apply(source):
    source = Path(source)
    name = SOURCE_FILES[0]; path = source/name; regular(path)
    raw = path.read_bytes(); before = hashlib.sha256(raw).hexdigest()
    if before != INPUT_SOURCE_SHA256[name]:
        raise ValueError('Virtual picture layout admission source drift or reapplication')
    value = raw
    for old, new in REPLACEMENTS:
        if value.count(old.encode()) != 1:
            raise ValueError('Virtual picture layout admission anchor must occur exactly once')
        value = value.replace(old.encode(), new.encode())
    if hashlib.sha256(value).hexdigest() != OUTPUT_SOURCE_SHA256[name]:
        raise ValueError('Virtual picture layout admission output differs from frozen patch')
    path.write_bytes(value)
    return {'beforeSha256': {name: before}, 'afterSha256': {name: sha(path)},
            'helperSha256': sha(ROOT/HELPER)}

def validate_contract(proof, prepared_files, helpers):
    expected = {'beforeSha256': INPUT_SOURCE_SHA256, 'afterSha256': OUTPUT_SOURCE_SHA256,
                'helperSha256': sha(ROOT/HELPER)}
    if type(proof) is not dict or set(proof) != set(expected) or proof != expected:
        raise ValueError('Exact virtual picture layout admission before/after/helper proof required')
    if type(prepared_files) is not dict or any(prepared_files.get(name) != digest for name,digest in OUTPUT_SOURCE_SHA256.items()):
        raise ValueError('Current virtual picture layout admission prepared source differs')
    if type(helpers) is not dict or helpers.get(HELPER) != expected['helperSha256']:
        raise ValueError('Current virtual picture layout admission helper is missing or drifted')
