"""Independent ZIP/XML output oracle. It does not call the application or rhwp."""
from __future__ import annotations
import io
from pathlib import Path, PurePosixPath
import re
import zipfile
import xml.etree.ElementTree as ET


def inspect_hwpx(data: bytes | Path, *, max_bytes: int = 128*1024*1024) -> dict:
    if isinstance(data, Path): data=data.read_bytes()
    if not data.startswith(b'PK\x03\x04'): raise ValueError('Not an HWPX ZIP stream')
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries=archive.infolist()
            if not entries or entries[0].filename != 'mimetype' or entries[0].compress_type != zipfile.ZIP_STORED:
                raise ValueError('HWPX mimetype must be first and uncompressed')
            if any(entry.orig_filename != entry.filename for entry in entries):
                raise ValueError('ZIP member name was normalized or truncated')
            names=[entry.filename for entry in entries]
            if len(set(names)) != len(names): raise ValueError('Duplicate ZIP entry')
            for name in names:
                parts=PurePosixPath(name).parts
                if '\\' in name or ':' in name or name.startswith('/') or any(p in ('..','.') for p in name.split('/')) or '//' in name:
                    raise ValueError('Unsafe ZIP path')
                if not parts: raise ValueError('Empty ZIP path')
            if sum(entry.file_size for entry in entries)>max_bytes: raise ValueError('Uncompressed size limit')
            required={'mimetype','Contents/header.xml','Contents/content.hpf','Contents/section0.xml'}
            if not required.issubset(names): raise ValueError('Missing required HWPX package parts')
            if archive.read('mimetype') != b'application/hwp+zip': raise ValueError('Wrong HWPX MIME')
            trees={}
            for name in names:
                if name.endswith(('.xml','.hpf','.rdf')):
                    raw=archive.read(name)
                    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper(): raise ValueError('DTD/entity not allowed')
                    trees[name]=ET.fromstring(raw)
            sections=sorted((name for name in names if re.fullmatch(r'Contents/section\d+\.xml',name)),key=lambda n:int(re.search(r'(\d+)\.xml$',n)[1]))
            text='\n'.join(''.join(''.join(node.itertext()) for node in trees[name].iter() if node.tag.rsplit('}',1)[-1]=='t') for name in sections)
            return {'text':text,'sections':len(sections),'entries':len(entries),
                'binary_parts':sum(name.startswith('BinData/') and not name.endswith('/') for name in names)}
    except (zipfile.BadZipFile, ET.ParseError, KeyError, RuntimeError, OSError) as error:
        raise ValueError(f'Invalid HWPX package: {error}') from error
