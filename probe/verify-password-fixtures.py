"""Independent bounded CFB and ZIP/XML checks; never invokes rhwp or the app."""
import argparse
import base64
import hashlib
import json
from pathlib import Path, PurePosixPath
import struct
import zipfile
import xml.etree.ElementTree as ET
import zlib

LIMIT = 16 * 1024 * 1024
END = 0xFFFFFFFE
FREE = 0xFFFFFFFF


def cfb_streams(data):
    assert data[:8] == bytes.fromhex('d0cf11e0a1b11ae1'), 'CFB signature'
    assert len(data) <= LIMIT
    u16 = lambda offset: struct.unpack_from('<H', data, offset)[0]
    u32 = lambda offset: struct.unpack_from('<I', data, offset)[0]
    sector_size, mini_size = 1 << u16(30), 1 << u16(32)
    assert sector_size in (512, 4096) and mini_size == 64

    def sector(index):
        offset = (index + 1) * sector_size
        assert 0 <= index < len(data) // sector_size - 1
        return data[offset:offset + sector_size]

    fat_sectors = [u32(offset) for offset in range(76, 512, 4) if u32(offset) != FREE]
    current, seen = u32(68), set()
    for _ in range(u32(72)):
        assert current not in seen
        seen.add(current)
        raw = sector(current)
        words = list(struct.unpack('<' + 'I' * (sector_size // 4), raw))
        fat_sectors.extend(index for index in words[:-1] if index != FREE)
        current = words[-1]
    assert len(fat_sectors) == u32(44)
    fat = [word for index in fat_sectors for word in
           struct.unpack('<' + 'I' * (sector_size // 4), sector(index))]

    def chain(first, table, read):
        chunks, visited = [], set()
        while first != END:
            assert first < len(table) and first not in visited
            visited.add(first)
            chunks.append(read(first))
            assert sum(map(len, chunks)) <= LIMIT
            first = table[first]
        return b''.join(chunks)

    directory = chain(u32(48), fat, sector)
    entries = []
    for offset in range(0, len(directory), 128):
        row = directory[offset:offset + 128]
        if row[66] not in (2, 5):
            continue
        name_length = struct.unpack_from('<H', row, 64)[0]
        assert 2 <= name_length <= 64
        entries.append((row[:name_length - 2].decode('utf-16le'), row[66],
                        struct.unpack_from('<I', row, 116)[0],
                        struct.unpack_from('<Q', row, 120)[0]))
    root = next(entry for entry in entries if entry[1] == 5)
    assert root[3] <= LIMIT
    mini_root = chain(root[2], fat, sector)[:root[3]] if root[3] else b''
    mini_fat_bytes = chain(u32(60), fat, sector) if u32(64) else b''
    mini_fat = list(struct.unpack('<' + 'I' * (len(mini_fat_bytes) // 4), mini_fat_bytes))

    def mini_sector(index):
        offset = index * mini_size
        assert offset + mini_size <= len(mini_root)
        return mini_root[offset:offset + mini_size]

    streams = {}
    for name, kind, first, size in entries:
        if kind != 2:
            continue
        assert size <= LIMIT and name not in streams, 'small unique synthetic streams'
        if not size:
            value = b''
        elif size < u32(56):
            value = chain(first, mini_fat, mini_sector)[:size]
        else:
            value = chain(first, fat, sector)[:size]
        assert len(value) == size
        streams[name] = value
    return streams


def inspect_hwp(path, encrypted, expected_text=None):
    streams = cfb_streams(path.read_bytes())
    header = streams['FileHeader']
    assert len(header) == 256 and header.startswith(b'HWP Document File')
    flags, version = struct.unpack_from('<I', header, 36)[0], struct.unpack_from('<I', header, 44)[0]
    assert header[35] == 5 and bool(flags & 2) == encrypted
    assert version == (4 if encrypted else 0)
    if expected_text is not None:
        body = streams['Section0']
        if flags & 1:
            inflater = zlib.decompressobj(-15)
            body = inflater.decompress(body, LIMIT + 1)
            assert len(body) <= LIMIT and inflater.eof
        assert expected_text.encode('utf-16le') in body, 'independent HWP body text marker'
    assert not any(name.lower().endswith(('.ttf', '.otf', '.ttc', '.woff', '.woff2')) for name in streams)
    return {'container': 'CFB', 'headerBytes': len(header), 'majorVersion': header[35],
            'encrypted': bool(flags & 2), 'compressed': bool(flags & 1), 'encryptVersion': version}


def inspect_hwpx(path, encrypted, expected_text=None):
    assert path.stat().st_size <= LIMIT
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        assert members[0].filename == 'mimetype' and members[0].compress_type == zipfile.ZIP_STORED
        names = [item.filename for item in members]
        assert len(names) == len(set(names)) and sum(item.file_size for item in members) <= LIMIT
        for name in names:
            assert not name.startswith('/') and '\\' not in name and ':' not in name
            assert all(part not in ('', '.', '..') for part in PurePosixPath(name).parts)
            assert not name.lower().endswith(('.ttf', '.otf', '.ttc', '.woff', '.woff2'))
        assert archive.read('mimetype') == b'application/hwp+zip'
        assert {'Contents/header.xml', 'Contents/section0.xml', 'Contents/content.hpf'}.issubset(names)

        def xml(name):
            raw = archive.read(name)
            assert b'<!DOCTYPE' not in raw.upper() and b'<!ENTITY' not in raw.upper()
            return ET.fromstring(raw)

        ns = {'odf': 'urn:oasis:names:tc:opendocument:xmlns:manifest:1.0'}
        manifest = xml('META-INF/manifest.xml')
        entries = manifest.findall('odf:file-entry', ns)
        protected = [entry for entry in entries if entry.find('odf:encryption-data', ns) is not None]
        assert bool(protected) == encrypted
        def attr(node, key):
            # The pinned writer uses unqualified attributes on odf: elements.
            candidates = [value for name, value in node.attrib.items()
                          if name in (key, f'{{{ns["odf"]}}}{key}')]
            assert len(candidates) == 1, f'unique {key} attribute'
            return candidates[0]
        if encrypted:
            paths = []
            for entry in protected:
                name = attr(entry, 'full-path')
                paths.append(name)
                metadata = entry.find('odf:encryption-data', ns)
                algorithm = metadata.find('odf:algorithm', ns)
                derivation = metadata.find('odf:key-derivation', ns)
                assert attr(algorithm, 'algorithm-name') == 'http://www.w3.org/2001/04/xmlenc#aes256-cbc'
                assert attr(derivation, 'key-derivation-name').endswith('#pbkdf2')
                assert attr(derivation, 'key-size') == '32' and int(attr(derivation, 'iteration-count')) == 1024
                assert len(base64.b64decode(attr(algorithm, 'initialisation-vector'), validate=True)) == 16
                assert len(base64.b64decode(attr(derivation, 'salt'), validate=True)) == 16
                assert attr(metadata, 'checksum-type').endswith('#sha256-1k')
                assert len(base64.b64decode(attr(metadata, 'checksum'), validate=True)) == 32
                assert archive.getinfo(name).compress_type == zipfile.ZIP_STORED
            assert {'Contents/header.xml', 'Contents/section0.xml'}.issubset(paths)
            return {'container': 'ZIP', 'algorithm': 'ODF AES-256-CBC', 'kdf': 'PBKDF2',
                    'keyBytes': 32, 'iterations': 1024, 'saltBytes': 16, 'ivBytes': 16,
                    'checksum': 'SHA-256-1K', 'encryptedParts': paths}
        sections = sorted(name for name in names if name.startswith('Contents/section') and name.endswith('.xml'))
        text = '\n'.join(''.join(''.join(node.itertext()) for node in xml(name).iter()
                                 if node.tag.rsplit('}', 1)[-1] == 't') for name in sections)
        if expected_text is not None:
            assert text == expected_text, 'independent ZIP/XML text marker'
        for name in names:
            if name.endswith(('.xml', '.hpf', '.rdf')):
                xml(name)
        return {'container': 'ZIP', 'encrypted': False, 'text': text, 'sections': len(sections)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--plaintext-hwpx', type=Path)
    parser.add_argument('--text')
    args = parser.parse_args()
    if args.plaintext_hwpx is not None:
        print(json.dumps(inspect_hwpx(args.plaintext_hwpx, False, args.text), ensure_ascii=False))
        return
    assert args.manifest is not None
    value = json.loads(args.manifest.read_text(encoding='utf-8'))
    root = args.manifest.parent
    result = {'fixtures': {}, 'plaintextRoundtrips': [], 'prior':
              inspect_hwpx(root / value['priorPath'], False, value['priorExpectedText'])}
    for fixture in value['fixtures']:
        path = root / fixture['path']
        assert path.stat().st_size == fixture['bytes']
        assert hashlib.sha256(path.read_bytes()).hexdigest() == fixture['sha256']
        result['fixtures'][fixture['format']] = (inspect_hwp(path, True) if fixture['format'] == 'hwp'
                                                else inspect_hwpx(path, True))
    for row in value['roundtrips']:
        path = root / row['path']
        assert path.stat().st_size == row['bytes']
        assert hashlib.sha256(path.read_bytes()).hexdigest() == row['sha256']
        inspection = (inspect_hwp(path, False, value['expectedText']) if row['outputFormat'] == 'hwp'
                      else inspect_hwpx(path, False, value['expectedText']))
        result['plaintextRoundtrips'].append({'inputFormat': row['inputFormat'],
                                             'outputFormat': row['outputFormat'], 'inspection': inspection})
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
