"""Resolve a missing PDF base family using only permission-filtered installed faces.

Run after pdf_search_text. All inputs and the exact output are checked before
the single renderer write. Existing font options, glyph fallback and licenses
remain unchanged.
"""
from pathlib import Path
import hashlib
import stat

ROOT = Path(__file__).resolve().parents[1]
HELPER = 'scripts/pdf_font_resolution.py'
PDF = 'third_party/rhwp/src/renderer/pdf.rs'
GUARD = 'third_party/rhwp/src/renderer/pdf/opengeul_pdf_guard.rs'
POLICY = 'third_party/rhwp/src/renderer/pdf/opengeul_font_policy.rs'
SOURCE_FILES = (PDF, GUARD, POLICY)
INPUT_SOURCE_SHA256 = {
    PDF: '84bb9980b3a42e42998872bc9112a1714ef82984a5981b59c51d148f90b9e804',
    GUARD: '844e00c23f76bb6bab2554cda58173ef07ed929e7f58971b89366a31db017a68',
    POLICY: 'a27b64bfc47e986cf92bb66237fdaa20fc8522fc88757dfd606d9c17ea70578f',
}
OUTPUT_SOURCE_SHA256 = {
    **INPUT_SOURCE_SHA256,
    PDF: '8bb23f71c9eccd728fb06b66f61247e90289a3c3114edaa5886cd278b4b72ac3',
}
REPLACEMENTS = ((
    b'    options.fontdb = std::sync::Arc::new(fontdb);\n',
    b'    options.fontdb = std::sync::Arc::new(fontdb);\n'
    b'    options.font_resolver.select_font = opengeul_pdf_guard::installed_base_font_selector();\n',
),)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def regular(path):
    path = Path(path)
    for candidate in (path, *path.parents):
        if candidate.exists() or candidate.is_symlink():
            info = candidate.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise ValueError('PDF font resolution source must not use symlink/reparse paths')
    if not path.is_file():
        raise ValueError('Missing pinned PDF font resolution source')


def apply(source):
    source = Path(source)
    for name in SOURCE_FILES:
        regular(source / name)
    inputs = {name: (source / name).read_bytes() for name in SOURCE_FILES}
    before = {name: hashlib.sha256(raw).hexdigest() for name, raw in inputs.items()}
    if before != INPUT_SOURCE_SHA256:
        raise ValueError('PDF font resolution source drift or reapplication')
    output = inputs[PDF]
    for old, new in REPLACEMENTS:
        if output.count(old) != 1:
            raise ValueError('PDF font resolution anchor must occur exactly once')
        output = output.replace(old, new, 1)
    after = {**before, PDF: hashlib.sha256(output).hexdigest()}
    if after != OUTPUT_SOURCE_SHA256:
        raise ValueError('PDF font resolution output differs from frozen patch')
    (source / PDF).write_bytes(output)
    return {'beforeSha256': before, 'afterSha256': after,
            'helperSha256': sha(ROOT / HELPER)}


def validate_contract(proof, prepared_files, helpers):
    expected = {'beforeSha256': INPUT_SOURCE_SHA256,
                'afterSha256': OUTPUT_SOURCE_SHA256,
                'helperSha256': sha(ROOT / HELPER)}
    if type(proof) is not dict or set(proof) != set(expected) or proof != expected:
        raise ValueError('Exact PDF font resolution before/after/helper proof required')
    if type(prepared_files) is not dict or any(
        prepared_files.get(name) != digest for name, digest in OUTPUT_SOURCE_SHA256.items()
    ):
        raise ValueError('Current PDF font resolution prepared source differs')
    if type(helpers) is not dict or helpers.get(HELPER) != expected['helperSha256']:
        raise ValueError('Current PDF font resolution helper is missing or drifted')
