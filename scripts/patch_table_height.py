"""Narrow rhwp#6074 backport; refuse source drift rather than weakening layout rules."""
from pathlib import Path
import hashlib
import json
import os
import tempfile

# Exact Git blob of height_measurer.rs at pinned rhwp 496333b27d21ddb9114ba9ae340bcb895870c9a7.
SOURCE_BLOB = 'c5cc6c9b9207602da1ae963cd24683f1ca93bad9'
ANCHOR = '''                                        if include_trailing_ls {
                                            h + hwpunit_to_px(line.line_spacing, self.dpi)
                                        } else {
                                            h
                                        }'''
REPLACEMENT = '''                                        if include_trailing_ls {
                                            let trailing = hwpunit_to_px(line.line_spacing, self.dpi);
                                            // rhwp#6074 / OpenGeul: a terminal inline-cell line
                                            // has no following line to compress. Keep positive
                                            // spacing and all nonterminal/block-cell rules.
                                            let trailing = if is_cell_last_line && table.common.treat_as_char {
                                                trailing.max(0.0)
                                            } else {
                                                trailing
                                            };
                                            h + trailing
                                        } else {
                                            h
                                        }'''

def transform(text: str) -> str:
    if text.count(ANCHOR) != 2:
        raise ValueError('Expected exactly two reviewed table-height sites')
    return text.replace(ANCHOR, REPLACEMENT)

def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def apply(core: Path) -> None:
    target = core/'src/renderer/height_measurer.rs'
    ledger = core/'.opengeul-table-height.json'
    if target.is_symlink() or ledger.is_symlink():raise ValueError('Symlinked patch inputs refused')
    original = target.read_bytes()
    if ledger.exists():
        value = json.loads(ledger.read_text(encoding='utf-8'))
        if value.get('sourceBlob') != SOURCE_BLOB or value.get('patcher') != digest(Path(__file__).read_bytes()) or value.get('patchedSha256') != digest(original):
            raise ValueError('Table-height patch state has changed')
        return
    blob = hashlib.sha1(b'blob '+str(len(original)).encode()+b'\0'+original).hexdigest()
    if blob != SOURCE_BLOB:raise ValueError('Pinned height_measurer.rs bytes have changed')
    patched = transform(original.decode('utf-8')).encode('utf-8')
    fd, name = tempfile.mkstemp(prefix='.opengeul-table-', dir=target.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:stream.write(patched)
        os.replace(name, target)
    finally:
        Path(name).unlink(missing_ok=True)
    value = {'sourceBlob': SOURCE_BLOB, 'patcher': digest(Path(__file__).read_bytes()),
             'patchedSha256': digest(patched), 'adaptedFrom': 'https://github.com/edwardkim/rhwp/pull/6074'}
    ledger.write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')
    print('Applied two terminal-negative-spacing fixes; rendering must pass separate gates.')

if __name__ == '__main__':
    import argparse
    parser=argparse.ArgumentParser(); parser.add_argument('core', type=Path)
    apply(parser.parse_args().core.resolve())
