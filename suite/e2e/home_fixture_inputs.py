"""Generate owned Home-route HWP inputs using only the current packaged CLI.

Run after complete Suite verification. This checks the selected tool against that
package's inventory; it does not replace full payload/source verification or
qualify Windows UI behavior. Portable tests fake only the subprocess boundary.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import stat
import struct
import subprocess
import time
import xml.etree.ElementTree as ET
import zipfile

TOOL = 'HWP/Tools/rhwp.exe'
NAMES = {'hwpx': 'basic.hwpx', 'hwp': 'basic.hwp', 'roundtrip': 'roundtrip.hwpx'}
TIMEOUT = 60
CAP = 8 * 1024 * 1024
LOG_CAP = 2 * 1024 * 1024
CFB = bytes.fromhex('d0cf11e0a1b11ae1')


def require(value, message):
    if not value:
        raise ValueError(message)


def plain(path, *, directory=False, absent=False):
    path = Path(path)
    require('..' not in path.parts, 'Owned paths cannot contain traversal')
    path = Path(os.path.abspath(path))  # Inspect links before any resolve().
    for item in reversed((path, *path.parents)):
        if item == path and absent:
            require(not item.exists() and not item.is_symlink(), 'Fixture namespace must be fresh')
            continue
        info = item.lstat()
        require(not stat.S_ISLNK(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400,
                'Linked or reparse fixture/tool paths are not accepted')
        require(stat.S_ISDIR(info.st_mode) if item != path or directory else stat.S_ISREG(info.st_mode),
                'Owned path has the wrong file type')
    return path


def read_bytes(path, cap=CAP):
    path = plain(path)
    before = path.stat()
    require(before.st_size <= cap, 'Fixture or metadata exceeds its bound')
    with path.open('rb') as stream:
        data = stream.read(cap + 1)
    after = path.stat()
    require(len(data) <= cap and len(data) == before.st_size and
            (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns), 'Owned bytes changed during observation')
    plain(path)
    return data


def strict_json(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'Duplicate JSON key')
            result[key] = value
        return result
    return json.loads(data.decode('utf-8-sig'), object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))


def metadata(path, root):
    raw = read_bytes(path)
    return {'path': Path(path).relative_to(root).as_posix(), 'size': len(raw),
            'sha256': hashlib.sha256(raw).hexdigest()}


def _lifecycle():
    path = Path(__file__).with_name('lifecycle_smoke.py')
    spec = importlib.util.spec_from_file_location('home_owned_lifecycle', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source_records(lifecycle):
    root = Path(__file__).resolve().parents[2]
    records = {}
    for role, path in (('helper', Path(__file__)), ('constructor', Path(lifecycle.__file__)),
                       ('template', root / 'tests/fixtures/advanced-owned/owned-blank.hwpx')):
        path = plain(path)
        records[role] = {**metadata(path, root), 'absolutePath': str(path)}
    return records


def package_tool(suite):
    suite = plain(suite, directory=True)
    inventory_path = suite / 'suite-inventory.json'
    inventory_raw = read_bytes(inventory_path)
    inventory = strict_json(inventory_raw)
    require(type(inventory.get('schemaVersion')) is int and inventory['schemaVersion'] == 1
            and inventory.get('architecture') in ('x64', 'arm64') and isinstance(inventory.get('files'), dict),
            'Current verified Suite inventory is required')
    path = plain(suite / TOOL)
    raw = read_bytes(path, 256 * 1024 * 1024)
    record = {'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
    require(inventory['files'].get(TOOL) == record, 'Packaged HWP CLI differs from the inventory')
    require(len(raw) >= 64 and raw[:2] == b'MZ', 'Packaged HWP CLI is not a PE image')
    offset = struct.unpack_from('<I', raw, 0x3c)[0]
    require(64 <= offset <= len(raw) - 6 and raw[offset:offset + 4] == b'PE\0\0', 'Invalid packaged HWP CLI PE header')
    machine = struct.unpack_from('<H', raw, offset + 4)[0]
    require(machine == {'x64': 0x8664, 'arm64': 0xaa64}[inventory['architecture']],
            'Packaged HWP CLI architecture differs from the Suite')
    return suite, {'path': str(path), 'relativePath': TOOL, **record, 'peMachine': machine}, {
        'path': str(inventory_path), 'size': len(inventory_raw),
        'sha256': hashlib.sha256(inventory_raw).hexdigest(), 'architecture': inventory['architecture']}


def xml_marker(path, expected):
    plain(path)
    require(0 < path.stat().st_size <= CAP, 'Owned HWPX is empty or oversized')
    with zipfile.ZipFile(path) as package:
        names = package.namelist()
        require(len(names) <= 128 and len(names) == len(set(names)), 'Owned HWPX member set differs')
        require(sum(item.file_size for item in package.infolist()) <= CAP, 'Owned HWPX expands beyond its bound')
        for item in package.infolist():
            require(not item.filename.startswith('/') and '\\' not in item.filename and
                    '..' not in Path(item.filename).parts and not stat.S_ISLNK(item.external_attr >> 16),
                    'Owned HWPX member escaped its container')
        sections = sorted(name for name in names if re.fullmatch(r'Contents/section[0-9]+\.xml', name))
        require(sections == ['Contents/section0.xml'], 'Owned basic HWPX must contain exactly one section')
        raw = package.read(sections[0])
        require(b'<!DOCTYPE' not in raw.upper() and b'<!ENTITY' not in raw.upper(), 'Unexpected XML declarations')
        root = ET.fromstring(raw)
        body = ''.join(node.text or '' for node in root.iter('{http://www.hancom.co.kr/hwpml/2011/paragraph}t'))
        require(body == expected and body.count(expected) == 1, 'Owned HWPX body marker differs')
    return {'sections': sections, 'bodyText': body, 'markerOccurrences': 1}


def cfb_header(path):
    raw = read_bytes(path)
    require(len(raw) >= 1536 and raw[:8] == CFB, 'Actual HWP must be CFB, never a renamed HWPX ZIP')
    major, order, shift, mini = (struct.unpack_from('<H', raw, p)[0] for p in (26, 28, 30, 32))
    require(order == 0xfffe and (major, shift) in ((3, 9), (4, 12)) and mini == 6
            and len(raw) % (1 << shift) == 0, 'Owned HWP CFB header/sector bounds differ')
    return {'signature': CFB.hex(), 'majorVersion': major, 'sectorShift': shift}


def envelope(raw, source, output, fmt):
    value = strict_json(raw)
    require(isinstance(value, dict) and value.get('schemaVersion') == '1.0'
            and value.get('source', str(source)) == str(source) and value.get('output') == str(output)
            and value.get('format') == fmt and type(value.get('bytes')) is int
            and value['bytes'] == plain(output).stat().st_size, 'Packaged HWP command envelope differs')
    verify = value.get('verify')
    require(isinstance(verify, dict) and verify.get('identical') is True
            and type(verify.get('diffCount')) is int and verify['diffCount'] == 0,
            'Packaged HWP command did not verify its actual round trip')
    return value


def _write_proof(root, proof, *, fresh=False):
    path = root / 'provenance.json'
    if not fresh:
        plain(path)
    with path.open('x' if fresh else 'w', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(proof, ensure_ascii=False, indent=2) + '\n')


def _command(root, tool, operation, source, target, proof):
    require(not target.exists() and not target.is_symlink(), 'CLI outputs must be fresh')
    before = metadata(source, root)['sha256']
    started = time.monotonic()
    row = {'operation': operation, 'argv': [tool['path'], operation, str(source), str(target), '--verify', '--json'],
           'cwd': str(root), 'timeoutSeconds': TIMEOUT, 'startedAt': started, 'deadline': started + TIMEOUT,
           'inputBeforeSha256': before, 'exitCode': None, 'timedOut': False}
    proof['commands'].append(row)
    stdout, stderr = root / (operation + '.stdout.json'), root / (operation + '.stderr.log')
    try:
        with stdout.open('xb') as out, stderr.open('xb') as err:
            try:
                result = subprocess.run(row['argv'], cwd=root, stdin=subprocess.DEVNULL,
                    stdout=out, stderr=err, timeout=TIMEOUT, check=False, shell=False)
                row['exitCode'] = result.returncode
            except subprocess.TimeoutExpired as exc:
                row['timedOut'] = True
                raise ValueError('Packaged HWP command exceeded its deadline') from exc
    finally:
        row['finishedAt'] = time.monotonic()
        row['inputAfterSha256'] = metadata(source, root)['sha256']
        row['stdout'], row['stderr'] = metadata(stdout, root), metadata(stderr, root)
    require(row['exitCode'] == 0 and row['finishedAt'] <= row['deadline']
            and row['inputAfterSha256'] == before, 'Packaged HWP command failed or changed its input')
    row['outputSha256'] = metadata(target, root)['sha256']
    envelope(read_bytes(stdout, LOG_CAP), source, target, 'hwp5' if operation == 'convert' else 'hwpx')


def require_hwp_fixture_provenance(proof, suite, fixture_root):
    """Re-read owned files/current tool and replay receipt; never execute a tool."""
    require(__debug__, 'Do not disable owned fixture checks with Python -O')
    suite, tool, inventory = package_tool(suite)
    root = plain(fixture_root, directory=True)
    require(not root.is_relative_to(suite), 'Fixture evidence must be outside the payload')
    lifecycle = _lifecycle()
    require(isinstance(proof, dict) and type(proof.get('schemaVersion')) is int and proof['schemaVersion'] == 1
            and proof.get('kind') == 'owned-home-hwp-fixtures' and proof.get('success') is True
            and not proof.get('error') and proof.get('suiteRoot') == str(suite) and proof.get('fixtureRoot') == str(root)
            and proof.get('tool') == tool and proof.get('inventory') == inventory
            and proof.get('sources') == source_records(lifecycle) and proof.get('marker') == lifecycle.HWPX_MARKER,
            'HWP fixture provenance identity differs from current package/source/owned paths')
    expected_names = set(NAMES.values()) | {'provenance.json', 'convert.stdout.json', 'convert.stderr.log',
                                         'export-hwpx.stdout.json', 'export-hwpx.stderr.log'}
    require({p.name for p in root.iterdir()} == expected_names, 'Owned fixture namespace has missing or unlisted paths')
    for path in root.iterdir(): plain(path)
    paths = {role: root / name for role, name in NAMES.items()}
    require(proof.get('files') == {role: metadata(path, root) for role, path in paths.items()}, 'Owned fixture hashes/paths differ')
    validation = {'inputXml': xml_marker(paths['hwpx'], lifecycle.HWPX_MARKER),
                  'cfb': cfb_header(paths['hwp']), 'roundtripXml': xml_marker(paths['roundtrip'], lifecycle.HWPX_MARKER)}
    require(proof.get('validation') == validation, 'Independent CFB/XML fixture validation differs')
    commands = proof.get('commands')
    require(isinstance(commands, list) and len(commands) == 2, 'Exactly the two packaged HWP conversions are required')
    previous = 0.0
    for row, operation, src, target in zip(commands, ('convert', 'export-hwpx'),
            (paths['hwpx'], paths['hwp']), (paths['hwp'], paths['roundtrip'])):
        require(isinstance(row, dict) and row.get('operation') == operation
                and row.get('argv') == [tool['path'], operation, str(src), str(target), '--verify', '--json']
                and row.get('cwd') == str(root) and type(row.get('timeoutSeconds')) is int and row['timeoutSeconds'] == TIMEOUT
                and type(row.get('exitCode')) is int and row['exitCode'] == 0 and row.get('timedOut') is False,
                'Packaged HWP command/exit/path differs')
        require(all(type(row.get(k)) in (int, float) and math.isfinite(row[k]) for k in ('startedAt', 'deadline', 'finishedAt'))
                and previous <= row['startedAt'] <= row['finishedAt'] <= row['deadline']
                and row['deadline'] == row['startedAt'] + TIMEOUT, 'Packaged HWP command deadline is invalid')
        previous = row['finishedAt']
        stdout, stderr = root / (operation + '.stdout.json'), root / (operation + '.stderr.log')
        require(row.get('stdout') == metadata(stdout, root) and row.get('stderr') == metadata(stderr, root)
                and row.get('inputBeforeSha256') == row.get('inputAfterSha256') == metadata(src, root)['sha256']
                and row.get('outputSha256') == metadata(target, root)['sha256'], 'Packaged HWP command original bytes differ')
        read_bytes(stderr, LOG_CAP)
        envelope(read_bytes(stdout, LOG_CAP), src, target, 'hwp5' if operation == 'convert' else 'hwpx')
    return paths


def produce_hwp_fixtures(suite, output):
    require(__debug__, 'Do not disable owned fixture checks with Python -O')
    suite, tool, inventory = package_tool(suite)
    root = plain(output, absent=True)
    require(not root.is_relative_to(suite), 'Fixture evidence must be outside the payload')
    lifecycle = _lifecycle()
    sources = source_records(lifecycle)
    root.mkdir()  # Existing parent only; never create or reuse a foreign namespace.
    proof = {'schemaVersion': 1, 'kind': 'owned-home-hwp-fixtures', 'success': False,
             'suiteRoot': str(suite), 'fixtureRoot': str(root), 'marker': lifecycle.HWPX_MARKER,
             'tool': tool, 'inventory': inventory, 'sources': sources, 'commands': []}
    _write_proof(root, proof, fresh=True)
    try:
        paths = {role: root / name for role, name in NAMES.items()}
        lifecycle.generate_hwpx(paths['hwpx'])
        original_xml = xml_marker(paths['hwpx'], lifecycle.HWPX_MARKER)
        _command(root, tool, 'convert', paths['hwpx'], paths['hwp'], proof)
        cfb = cfb_header(paths['hwp'])
        _command(root, tool, 'export-hwpx', paths['hwp'], paths['roundtrip'], proof)
        proof['files'] = {role: metadata(path, root) for role, path in paths.items()}
        proof['validation'] = {'inputXml': original_xml, 'cfb': cfb,
                               'roundtripXml': xml_marker(paths['roundtrip'], lifecycle.HWPX_MARKER)}
        proof['success'] = True
        _write_proof(root, proof)
        require_hwp_fixture_provenance(proof, suite, root)
        return proof
    except Exception as exc:
        proof.update(success=False, error={'type': type(exc).__name__, 'message': str(exc)})
        _write_proof(root, proof)
        raise


def main(argv=None):
    require(__debug__, 'Do not disable owned fixture checks with Python -O')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    produce_hwp_fixtures(args.suite, args.output)
    print('Owned HWP/HWPX fixture provenance verified.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
