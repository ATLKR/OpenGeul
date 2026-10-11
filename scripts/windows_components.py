"""Verify bounded, same-run editor/CLI inputs before joining a Windows payload.

Checksums establish byte integrity. CI must select artifacts from the current run;
this helper additionally checks its current GitHub identity and local source inputs.
No Cargo, node_modules, or complete upstream source trees cross this boundary.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tempfile
import tomllib
import xml.etree.ElementTree as ET
import zlib

from buildkit import ROOT, audit_payload, package_version
from releasekit import REPOSITORY, pe_machine
from prepare_native_tests import TARGETS
from wasm_artifacts import FILES as WASM_FILES

CAPS = {'editor': 64*1024*1024, 'cli': 32*1024*1024}
MAX_PAYLOAD = 96*1024*1024
CLI_RUNTIME = 'Tools/rhwp.exe'
CLI_GZIP = 'payload/'+CLI_RUNTIME+'.gz'
BLOCK = 1024*1024
MAX_FILES = 10_000
MAX_METADATA = 512*1024
TARGET = 'x86_64-pc-windows-msvc'
FEATURES = {'editor': 'default', 'cli': 'native-skia'}
RESERVED = re.compile(r'(?i)(?:con|prn|aux|nul|com[1-9¹²³]|lpt[1-9¹²³])(?:\..*)?\Z')
SHA = re.compile(r'[0-9a-f]{64}\Z')
COPIED_OVERLAYS = {
    'apps/desktop/src-tauri/src/opengeul_runtime.rs': 'overlay/opengeul_runtime.rs',
    'apps/desktop/src-tauri/src/updates.rs': 'overlay/updates.rs',
    'apps/desktop/src-tauri/src/store_update_policy.rs': 'overlay/store_update_policy.rs',
    'apps/desktop/src-tauri/src/store_update_transport.rs': 'overlay/store_update_transport.rs',
    'apps/desktop/src-tauri/src/opengeul_hwpx_commands.rs': 'overlay/opengeul_hwpx_commands.rs',
    'apps/desktop/src-tauri/src/opengeul_hwpx_state.rs': 'overlay/opengeul_hwpx_state.rs',
    'apps/desktop/src-tauri/src/opengeul_hwpx_state_tests.rs': 'overlay/opengeul_hwpx_state_tests.rs',
    'apps/desktop/src-tauri/src/opengeul_hwp_staging_tests.rs': 'overlay/opengeul_hwp_staging_tests.rs',
    'apps/studio-host/src/core/save-format.ts': 'overlay/save-format.ts',
    'apps/studio-host/src/core/font-catalog.ts': 'overlay/font-catalog.ts',
    'apps/studio-host/src/ui/update-notice.ts': 'overlay/store-update-notice.ts',
    'apps/studio-host/src/host/store-updates.ts': 'overlay/store-update-menu.ts',
    'apps/studio-host/src/opengeul-font-help.ts': 'overlay/opengeul-font-help.ts',
    'third_party/rhwp/src/renderer/pdf/opengeul_pdf_guard.rs': 'overlay/opengeul_pdf_guard.rs',
    'third_party/rhwp/src/renderer/pdf/opengeul_font_policy.rs': 'overlay/font_policy.rs',
    'third_party/rhwp/src/parser/hwpx/opengeul_namespaces.rs': 'overlay/hwpx_namespaces.rs',
    'third_party/rhwp/rhwp-studio/src/engine/opengeul-composition-final.ts': 'overlay/composition-final.ts',
}
SOURCE_FILES = tuple(sorted(set(COPIED_OVERLAYS) | {
    'package.json', 'pnpm-lock.yaml', 'apps/desktop/package.json',
    'apps/desktop/src-tauri/Cargo.toml', 'apps/desktop/src-tauri/Cargo.lock',
    'apps/desktop/src-tauri/build.rs', 'apps/desktop/src-tauri/tauri.conf.json',
    'apps/desktop/src-tauri/tauri.windows.conf.json', 'apps/desktop/src-tauri/windows-app-manifest.xml',
    'apps/desktop/rhwp-adapter/Cargo.toml', 'apps/desktop/rhwp-adapter/src/lib.rs',
    'apps/desktop/src-tauri/src/commands.rs', 'apps/desktop/src-tauri/src/state.rs',
    'apps/desktop/src-tauri/src/lib.rs', 'apps/desktop/src-tauri/src/font_catalog.rs',
    'apps/desktop/src-tauri/src/pdf_export.rs', 'apps/desktop/src-tauri/src/pending_open.rs',
    'apps/desktop/src-tauri/src/app_quit.rs', 'apps/desktop/src-tauri/src/recent_documents.rs',
    'apps/desktop/src-tauri/src/opengeul_font_resources.rs', 'apps/desktop/src-tauri/src/windows.rs',
    'apps/studio-host/package.json', 'apps/studio-host/index.html',
    'apps/studio-host/hop-overrides.ts', 'apps/studio-host/src/style.css',
    'apps/studio-host/src/core/tauri-bridge.ts', 'apps/studio-host/src/main.ts',
    'apps/studio-host/src/core/desktop-events.ts',
    'apps/studio-host/src/command/commands/file.ts', 'apps/studio-host/src/opengeul-font-resources.ts',
    'apps/studio-host/src/command/commands/edit.ts',
    'apps/studio-host/src/host/toolbar-labels.ts',
    'third_party/rhwp/Cargo.toml', 'third_party/rhwp/Cargo.lock',
    'third_party/rhwp/vendor/svg2pdf/Cargo.toml', 'third_party/rhwp/vendor/svg2pdf/RHWP_PATCHES.md',
    'third_party/rhwp/src/renderer/pdf.rs', 'third_party/rhwp/src/cli/outputs/pdf.rs',
    'third_party/rhwp/src/parser/hwpx/header.rs',
    'third_party/rhwp/rhwp-studio/src/engine/input-handler-text.ts',
    'third_party/rhwp/rhwp-studio/src/ui/about-dialog.ts',
    'third_party/rhwp/rhwp-studio/src/ui/compare-dialog.ts',
    'third_party/rhwp/rhwp-studio/src/ui/history-dialog.ts',
}))
NATIVE_FILES = tuple('third_party/rhwp/tests/'+name+'.rs' for name in TARGETS)
CORE_TREES = ('third_party/rhwp/src', 'third_party/rhwp/vendor/svg2pdf/src')
SOURCE_TREE_CAP = 64*1024*1024


def safe_name(name: str) -> str:
    if not isinstance(name, str):
        raise ValueError('Invalid component path')
    parts = name.split('/')
    if (not parts or '\\' in name or any(p in ('', '.', '..') or p.rstrip(' .') != p
            or RESERVED.fullmatch(p) for p in parts)
            or any(ord(c) < 32 or ord(c) == 127 or c in ':<>"|?*' for c in name)):
        raise ValueError(f'Unsafe Windows component path: {name!r}')
    return name


def _kind(path: Path) -> os.stat_result:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
        raise ValueError(f'Component symlink/reparse point: {path}')
    return info


def _ancestors(path: Path) -> None:
    for parent in (path, *path.parents):
        if parent.exists() or parent.is_symlink():
            _kind(parent)


def regular(path: Path) -> None:
    _ancestors(path)
    if not stat.S_ISREG(_kind(path).st_mode):
        raise ValueError(f'Only regular component files are permitted: {path}')


def sha(path: Path) -> str:
    regular(path)
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Duplicate component JSON key')
        value[key] = item
    return value


def read_json(path: Path) -> dict:
    regular(path)
    if not 0 < path.stat().st_size <= MAX_METADATA:
        raise ValueError('Component metadata exceeds cap')
    try:
        value = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=_pairs)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError('Invalid component JSON') from error
    if not isinstance(value, dict):
        raise ValueError('Component metadata must be an object')
    return value


def encoded(value: dict) -> bytes:
    data = (json.dumps(value, indent=2, sort_keys=True)+'\n').encode()
    if len(data) > MAX_METADATA:
        raise ValueError('Component metadata exceeds cap')
    return data


def identity(env=None) -> dict:
    env = os.environ if env is None else env
    value = {'repository': env.get('GITHUB_REPOSITORY'), 'commit': env.get('GITHUB_SHA'),
             'runId': env.get('GITHUB_RUN_ID'), 'runAttempt': env.get('GITHUB_RUN_ATTEMPT')}
    if (value['repository'] != REPOSITORY or not isinstance(value['commit'], str)
            or not re.fullmatch(r'[0-9a-f]{40}', value['commit'])
            or not isinstance(value['runId'], str) or not re.fullmatch(r'[1-9][0-9]*', value['runId'])
            or not isinstance(value['runAttempt'], str) or not re.fullmatch(r'[1-9][0-9]*', value['runAttempt'])):
        raise ValueError('Components require the current owned repository/source/run/positive attempt')
    return value


def helpers() -> dict:
    paths = []
    for directory in ('scripts', 'overlay', 'config'):
        for path in (ROOT/directory).rglob('*'):
            if path.is_file() and '__pycache__' not in path.parts and path.suffix in ('.py','.ps1','.sh','.rs','.ts','.txt','.xml','.json','.toml'):
                paths.append(path)
    return {p.relative_to(ROOT).as_posix(): sha(p) for p in sorted(paths)}


def configured() -> dict:
    return {'product': read_json(ROOT/'config/product.json'),
            'upstream': read_json(ROOT/'config/upstream.lock.json'), 'helpers': helpers()}


def tree(folder: Path, cap: int) -> tuple[dict, set]:
    _ancestors(folder)
    if not folder.is_dir():
        raise ValueError('Missing component directory')
    files = {}; directories = set(); aliases = set(); total = 0
    pending = [folder]
    while pending:
        directory = pending.pop()
        for path in directory.iterdir():
            name = safe_name(path.relative_to(folder).as_posix())
            alias = name.casefold()
            if alias in aliases:
                raise ValueError('Windows case collision in component paths')
            aliases.add(alias)
            info = _kind(path)
            if stat.S_ISDIR(info.st_mode):
                directories.add(name); pending.append(path)
            elif stat.S_ISREG(info.st_mode):
                total += info.st_size
                if total > cap or len(files) >= MAX_FILES:
                    raise ValueError('Component exceeds size/file cap')
                files[name] = {'size': info.st_size, 'sha256': sha(path)}
            else:
                raise ValueError('Only regular component files/directories are permitted')
    return files, directories


def validate_payload(folder: Path, role: str, files: dict) -> None:
    required = {'Tools/rhwp.exe'} if role == 'cli' else {
        'OpenGeul.exe', 'AppxManifest.xml', 'Notices/OpenGeul-LICENSE.txt',
        'Assets/StoreLogo.png', 'Assets/Square44x44Logo.png', 'Assets/Square150x150Logo.png'}
    if not required <= set(files):
        raise ValueError('Component payload lacks required runtime/assets/notices')
    audit_payload(folder)
    for name in files:
        if role == 'cli' and name != 'Tools/rhwp.exe':
            raise ValueError('CLI component payload must contain only Tools/rhwp.exe')
        if role == 'editor' and name.startswith('Tools/'):
            raise ValueError('Editor component cannot contain the CLI')
        if Path(name).suffix.lower() in ('.exe', '.dll'):
            with (folder/name).open('rb') as stream:
                pe_machine(stream.read(4096))
    if role == 'editor':
        try:
            doc = ET.fromstring((folder/'AppxManifest.xml').read_bytes())
            ns = {'p': 'http://schemas.microsoft.com/appx/manifest/foundation/windows10'}
            ident = doc.find('p:Identity', ns); app = doc.find('p:Applications/p:Application', ns)
            version = read_json(ROOT/'config/product.json')['version']
            if (ident is None or ident.get('ProcessorArchitecture') != 'x64'
                    or ident.get('Version') != package_version(version)
                    or app is None or app.get('Executable') != 'OpenGeul.exe'):
                raise ValueError('Wrong editor component manifest identity/architecture')
        except ET.ParseError as error:
            raise ValueError('Invalid editor component manifest') from error


def _hashes(value: dict, names: set) -> None:
    if not isinstance(value, dict) or set(value) != names or any(not isinstance(v, str) or not SHA.fullmatch(v) for v in value.values()):
        raise ValueError('Invalid source hash inventory')


def validate_ledger(ledger: dict, contract: dict, config: dict) -> None:
    if (ledger.get('version') != config['product']['version']
            or ledger.get('source') != 'OpenGeul distribution overlays' or ledger.get('hwpxSaveV1') is not True
            or not isinstance(ledger.get('changes'), list) or not ledger['changes']
            or not isinstance(ledger.get('preservedFiles'), dict)
            or not isinstance(ledger.get('baselinePreservedFiles'), dict)
            or ledger.get('extendedFiles') != ['commands.rs','state.rs','lib.rs','tauri-bridge.ts','main.ts','file.ts','desktop-events.ts','edit.ts']):
        raise ValueError('Incomplete prepared source overlay ledger')
    for key in ('preservedFiles', 'baselinePreservedFiles'):
        for name, digest in ledger[key].items():
            safe_name(name)
            if not isinstance(digest, str) or not SHA.fullmatch(digest):
                raise ValueError('Invalid preserved source hash')
    if any(ledger['baselinePreservedFiles'].get(name) != digest for name, digest in ledger['preservedFiles'].items()):
        raise ValueError('Preserved source baseline mismatch')
    composition = ledger.get('compositionFix', {})
    files = contract['preparedFiles']
    if (not isinstance(composition, dict) or composition.get('helperSha256') != config['helpers']['overlay/composition-final.ts']
            or composition.get('afterSha256') != contract['compositionTextSha256']
            or not isinstance(composition.get('beforeSha256'), str) or not SHA.fullmatch(composition['beforeSha256'])):
        raise ValueError('Incomplete composition source ledger')
    namespace = ledger.get('namespacePatch', {})
    if (namespace != contract['namespacePatch'] or not isinstance(namespace, dict)
            or namespace.get('helperSha256') != config['helpers']['overlay/hwpx_namespaces.rs']
            or namespace.get('patchedHeaderSha256') != files['third_party/rhwp/src/parser/hwpx/header.rs']
            or not isinstance(namespace.get('upstreamHeaderSha256'), str) or not SHA.fullmatch(namespace['upstreamHeaderSha256'])):
        raise ValueError('Invalid namespace source ledger')
    wasm = ledger.get('wasmRebuild', {})
    if (wasm != contract['wasmRebuild'] or not isinstance(wasm, dict)
            or wasm.get('upstream') != config['upstream']
            or wasm.get('namespaceHelper') != config['helpers']['overlay/hwpx_namespaces.rs']
            or wasm.get('namespacePatcher') != config['helpers']['scripts/patch_namespaces.py']
            or wasm.get('generator') != 'wasm-pack 0.14.0 --target web --release --no-opt'):
        raise ValueError('Invalid WASM source ledger')
    _hashes(wasm.get('artifacts'), set(WASM_FILES))


def source_contract(source: Path, config: dict) -> tuple[bytes, dict]:
    for folder, project in ((source, 'hop'), (source/'third_party/rhwp', 'rhwp')):
        _ancestors(folder)
        result = subprocess.run(['git','-C',str(folder),'rev-parse','HEAD'], check=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.stdout.strip() != config['upstream'][project]['commit']:
            raise ValueError('Prepared source git HEAD does not match pinned '+project)
    ledger_path = source/'.opengeul-overlay.json'
    ledger = read_json(ledger_path)
    core = source/'third_party/rhwp'
    native = read_json(core/'.opengeul-native-tests.json')
    expected_tests = {name: config['helpers']['overlay/'+local] for name, local in TARGETS.items()}
    if native.get('targets') != expected_tests:
        raise ValueError('Native test source metadata mismatch')
    regular(core/'Cargo.toml')
    manifest = (core/'Cargo.toml').read_text(encoding='utf-8')
    entries = tomllib.loads(manifest).get('test', [])
    for name in TARGETS:
        selected = [entry for entry in entries if entry.get('name') == name]
        if (len(selected) != 1 or selected[0].get('path') != 'tests/'+name+'.rs'
                or selected[0].get('required-features', []) != (['native-skia'] if name == 'opengeul_pdf_policy' else [])):
            raise ValueError('Native integration test is not correctly registered')
    marker = '\n# OpenGeul distribution-only integration gates.\n'
    if manifest.count(marker) != 1 or hashlib.sha256(manifest.split(marker)[0].encode()).hexdigest() != native.get('originalManifestSha256'):
        raise ValueError('Native original manifest hash mismatch')
    files = {name: sha(source/name) for name in (*SOURCE_FILES, *NATIVE_FILES)}
    core_files = {}
    for directory in CORE_TREES:
        inventory, _ = tree(source/directory, SOURCE_TREE_CAP)
        core_files.update({directory+'/'+name: item['sha256'] for name, item in inventory.items()})
    for upstream, local in COPIED_OVERLAYS.items():
        if files[upstream] != config['helpers'][local]:
            raise ValueError('Prepared overlay helper mismatch: '+upstream)
    for name in TARGETS:
        if files['third_party/rhwp/tests/'+name+'.rs'] != expected_tests[name]:
            raise ValueError('Native test actual source hash mismatch')
    contract = {'ledgerSha256': sha(ledger_path), 'preparedFiles': files, 'coreSourceFiles': core_files, 'nativeTests': native,
                'namespacePatch': read_json(core/'.opengeul-namespaces.json'),
                'wasmRebuild': ledger.get('wasmRebuild'),
                # patch_composition hashes its LF text before write_text translates on Windows.
                'compositionTextSha256': hashlib.sha256((source/'third_party/rhwp/rhwp-studio/src/engine/input-handler-text.ts').read_text(encoding='utf-8').encode()).hexdigest()}
    validate_ledger(ledger, contract, config)
    for name, digest in ledger['preservedFiles'].items():
        if sha(source/name) != digest:
            raise ValueError('Protected source hash mismatch')
    vendor = source/'apps/studio-host/vendor/rhwp-core'
    for name, digest in contract['wasmRebuild']['artifacts'].items():
        if sha(vendor/name) != digest:
            raise ValueError('Installed WASM artifact mismatch')
    if (vendor/'rhwp_bg.wasm').read_bytes()[:8] != b'\0asm\1\0\0\0':
        raise ValueError('Invalid installed WASM binary')
    if (read_json(vendor/'package.json').get('version') != config['upstream']['rhwp']['version']
            or read_json(vendor/'PROVENANCE.json').get('opengeulRebuild') != contract['wasmRebuild']):
        raise ValueError('Installed WASM provenance/version mismatch')
    return ledger_path.read_bytes(), contract


def fresh(path: Path) -> None:
    _ancestors(path)
    if path.exists() or path.is_symlink():
        raise ValueError('Refusing to overwrite component destination: '+str(path))


def _copy(source: Path, target: Path, expected: dict) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    regular(source)
    shutil.copyfile(source, target)
    if target.stat().st_size != expected['size'] or sha(target) != expected['sha256']:
        raise ValueError('Component input changed during staging')


class _GzipBuffer(io.BytesIO):
    def write(self, data: bytes) -> int:
        if self.tell()+len(data) > CAPS['cli']:
            raise ValueError('CLI compressed transport exceeds cap')
        return super().write(data)


def _compress_cli(path: Path, expected: dict) -> bytes:
    regular(path)
    digest = hashlib.sha256(); size = 0
    with _GzipBuffer() as buffer:
        with path.open('rb') as source, gzip.GzipFile(fileobj=buffer, mode='wb', filename='', mtime=0, compresslevel=9) as target:
            for block in iter(lambda: source.read(BLOCK), b''):
                size += len(block)
                if size > expected['size'] or size > MAX_PAYLOAD:
                    raise ValueError('CLI runtime input exceeds size cap')
                digest.update(block); target.write(block)
        if size != expected['size'] or digest.hexdigest() != expected['sha256']:
            raise ValueError('CLI runtime input changed during capture')
        return buffer.getvalue()


def _decode_cli(path: Path, runtime: dict, transport: dict, target=None) -> None:
    """Check one bounded gzip member; an optional target is private staging only."""
    regular(path)
    decoder = zlib.decompressobj(16+zlib.MAX_WBITS)
    raw_hash = hashlib.sha256(); compressed_hash = hashlib.sha256()
    raw_size = 0; compressed_size = 0; header = bytearray()
    try:
        with path.open('rb') as source:
            for compressed in iter(lambda: source.read(BLOCK), b''):
                compressed_size += len(compressed); compressed_hash.update(compressed)
                if compressed_size > transport['size'] or compressed_size > CAPS['cli']:
                    raise ValueError('CLI gzip transport exceeds size cap')
                if decoder.eof:
                    raise ValueError('CLI gzip has trailing or concatenated data')
                pending = compressed
                while True:
                    # Zero would disable zlib's output bound. The extra byte detects overflow.
                    limit = min(BLOCK, runtime['size']-raw_size+1)
                    block = decoder.decompress(pending, limit)
                    pending = decoder.unconsumed_tail
                    raw_size += len(block)
                    if raw_size > runtime['size'] or raw_size > MAX_PAYLOAD:
                        raise ValueError('CLI runtime size exceeds declared size/cap')
                    raw_hash.update(block)
                    if len(header) < 4096:
                        header.extend(block[:4096-len(header)])
                    if target is not None:
                        target.write(block)
                    if decoder.unused_data:
                        raise ValueError('CLI gzip has trailing or concatenated data')
                    if not pending and (len(block) < limit or decoder.eof):
                        break
        if not decoder.eof:
            raise ValueError('CLI gzip stream is truncated')
    except zlib.error as error:
        raise ValueError('Invalid CLI gzip stream or CRC') from error
    if compressed_size != transport['size'] or compressed_hash.hexdigest() != transport['sha256']:
        raise ValueError('CLI gzip input changed during validation/staging')
    if raw_size != runtime['size'] or raw_hash.hexdigest() != runtime['sha256']:
        raise ValueError('CLI runtime size/hash mismatch')
    pe_machine(header)


def capture(role: str, payload: Path, source: Path, out: Path, *, env=None) -> None:
    if role not in CAPS:
        raise ValueError('Unknown component role')
    current = identity(env); config = configured(); fresh(out)
    files, _ = tree(payload, MAX_PAYLOAD if role == 'cli' else CAPS[role]); validate_payload(payload, role, files)
    parity, contract = source_contract(source, config)
    transport = {'payload/'+name: value for name, value in files.items()}
    compressed = None
    if role == 'editor':
        transport['source-parity.json'] = {'size': len(parity), 'sha256': hashlib.sha256(parity).hexdigest()}
    else:
        compressed = _compress_cli(payload/CLI_RUNTIME, files[CLI_RUNTIME])
        transport = {CLI_GZIP: {'size': len(compressed), 'sha256': hashlib.sha256(compressed).hexdigest()}}
    value = {'formatVersion': 2 if role == 'cli' else 1, **current, **config, 'role': role, 'target': TARGET,
             'features': FEATURES[role], 'source': contract, 'files': transport}
    if role == 'cli':
        value['runtime'] = {'path': CLI_RUNTIME, **files[CLI_RUNTIME]}
    metadata = encoded(value)
    if sum(item['size'] for item in transport.values())+len(metadata) > CAPS[role]:
        raise ValueError('Component exceeds total transport cap')
    out.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.opengeul-component-', dir=out.parent))
    try:
        if role == 'editor':
            for name, record in files.items():
                _copy(payload/name, stage/'payload'/name, record)
            (stage/'source-parity.json').write_bytes(parity)
        else:
            path = stage/CLI_GZIP
            path.parent.mkdir(parents=True)
            path.write_bytes(compressed)
        (stage/'provenance.json').write_bytes(metadata)
        fresh(out); stage.rename(out)
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def validate_component(folder: Path, role: str, current: dict, config: dict) -> dict:
    actual, directories = tree(folder, CAPS[role])
    if 'provenance.json' not in actual:
        raise ValueError('Missing component provenance')
    value = read_json(folder/'provenance.json')
    expected_keys = {'formatVersion','repository','commit','runId','runAttempt','product','upstream',
                     'helpers','role','target','features','source','files'}
    if role == 'cli':
        expected_keys.add('runtime')
    attempt = value.get('runAttempt')
    if (set(value) != expected_keys or type(value.get('formatVersion')) is not int or value.get('formatVersion') != (2 if role == 'cli' else 1) or value.get('role') != role
            or value.get('target') != TARGET or value.get('features') != FEATURES[role]
            or any(value.get(k) != v for k, v in current.items() if k != 'runAttempt')
            or not isinstance(attempt, str) or not re.fullmatch(r'[1-9][0-9]*', attempt)
            or int(attempt) > int(current['runAttempt'])):
        raise ValueError('Component source/run/role identity mismatch')
    for key, expected in config.items():
        if value.get(key) != expected:
            raise ValueError('Component local '+key+' mismatch')
    inventory = value['files']
    if not isinstance(inventory, dict):
        raise ValueError('Invalid component inventory')
    for name, record in inventory.items():
        safe_name(name)
        if (not isinstance(record, dict) or set(record) != {'size','sha256'}
                or type(record['size']) is not int or record['size'] < 0
                or not isinstance(record['sha256'], str) or not SHA.fullmatch(record['sha256'])):
            raise ValueError('Invalid component inventory record')
    content = {name: record for name, record in actual.items() if name != 'provenance.json'}
    if content != inventory:
        raise ValueError('Component file inventory mismatch')
    metadata = {'source-parity.json'} if role == 'editor' else set()
    if any(not n.startswith('payload/') and n not in metadata for n in content):
        raise ValueError('Unexpected component file')
    if not metadata <= set(content):
        raise ValueError('Missing component source parity')
    expected_dirs = {parent.as_posix() for name in content for parent in PurePosixPath(name).parents if parent.as_posix() != '.'}
    if directories != expected_dirs:
        raise ValueError('Unexpected component directory')
    if role == 'cli':
        runtime = value['runtime']
        if (not isinstance(runtime, dict) or set(runtime) != {'path','size','sha256'}
                or runtime['path'] != CLI_RUNTIME or type(runtime['size']) is not int
                or not 0 < runtime['size'] <= MAX_PAYLOAD
                or not isinstance(runtime['sha256'], str) or not SHA.fullmatch(runtime['sha256'])):
            raise ValueError('Invalid CLI runtime record or size cap')
        if set(content) != {CLI_GZIP}:
            raise ValueError('CLI component inventory must contain only the gzip runtime')
        _decode_cli(folder/CLI_GZIP, runtime, content[CLI_GZIP])
    else:
        payload = {name.removeprefix('payload/'): record for name, record in content.items() if name.startswith('payload/')}
        validate_payload(folder/'payload', role, payload)
    contract = value['source']
    if (not isinstance(contract, dict) or set(contract) != {'ledgerSha256','preparedFiles','coreSourceFiles','nativeTests','namespacePatch','wasmRebuild','compositionTextSha256'}
            or any(not isinstance(contract[key], str) or not SHA.fullmatch(contract[key]) for key in ('ledgerSha256','compositionTextSha256'))):
        raise ValueError('Invalid prepared source contract')
    _hashes(contract['preparedFiles'], set(SOURCE_FILES) | set(NATIVE_FILES))
    core_files = contract['coreSourceFiles']
    if not isinstance(core_files, dict) or not core_files or len(core_files) > MAX_FILES:
        raise ValueError('Invalid complete core source inventory')
    _hashes(core_files, set(core_files))
    for name in core_files:
        safe_name(name)
        if not any(name.startswith(directory+'/') for directory in CORE_TREES):
            raise ValueError('Unexpected core source inventory path')
    for name, digest in contract['preparedFiles'].items():
        if any(name.startswith(directory+'/') for directory in CORE_TREES) and core_files.get(name) != digest:
            raise ValueError('Complete core source inventory mismatch')
    native = contract['nativeTests']
    if (not isinstance(native, dict) or set(native) != {'targets','originalManifestSha256'}
            or native['targets'] != {name: config['helpers']['overlay/'+local] for name, local in TARGETS.items()}
            or not isinstance(native['originalManifestSha256'], str) or not SHA.fullmatch(native['originalManifestSha256'])):
        raise ValueError('Invalid native test source contract')
    for upstream, local in COPIED_OVERLAYS.items():
        if contract['preparedFiles'][upstream] != config['helpers'][local]:
            raise ValueError('Prepared overlay source contract mismatch')
    for name in TARGETS:
        if contract['preparedFiles']['third_party/rhwp/tests/'+name+'.rs'] != native['targets'][name]:
            raise ValueError('Prepared native test source contract mismatch')
    return value


def combine(editor: Path, cli: Path, payload: Path, source: Path, *, env=None) -> None:
    current = identity(env); config = configured()
    fresh(payload); fresh(source)
    if payload == source or payload in source.parents or source in payload.parents:
        raise ValueError('Component output directories must be separate')
    records = {role: validate_component(folder, role, current, config)
               for role, folder in (('editor', editor), ('cli', cli))}
    if records['editor']['source'] != records['cli']['source']:
        raise ValueError('Editor and CLI prepared source parity mismatch')
    parity_path = editor/'source-parity.json'
    parity = read_json(parity_path)
    contract = records['editor']['source']
    if sha(parity_path) != contract['ledgerSha256']:
        raise ValueError('Prepared source ledger hash mismatch')
    validate_ledger(parity, contract, config)
    editor_size = sum(record['size'] for name, record in records['editor']['files'].items() if name.startswith('payload/'))
    if editor_size+records['cli']['runtime']['size'] > MAX_PAYLOAD:
        raise ValueError('Combined restored payload exceeds size cap')
    receipt = {'formatVersion': 1, **current,
               'sourceContractSha256': hashlib.sha256(encoded(contract)).hexdigest(),
               'components': {}}
    for role, folder, runtime in (('editor', editor, 'OpenGeul.exe'), ('cli', cli, 'Tools/rhwp.exe')):
        inventory = ({key: records[role]['runtime'][key] for key in ('size','sha256')} if role == 'cli'
                     else records[role]['files']['payload/'+runtime])
        receipt['components'][role] = {
            'artifactName': 'opengeul-'+role+'-component-'+current['runId'],
            'runAttempt': records[role]['runAttempt'], 'provenanceSha256': sha(folder/'provenance.json'),
            'runtime': runtime, **inventory}
    receipt_bytes = encoded(receipt)
    # Every input and output path has now passed validation; staging starts here.
    payload.parent.mkdir(parents=True, exist_ok=True); source.parent.mkdir(parents=True, exist_ok=True)
    staged_payload = Path(tempfile.mkdtemp(prefix='.opengeul-joined-', dir=payload.parent))
    staged_source = Path(tempfile.mkdtemp(prefix='.opengeul-source-', dir=source.parent))
    published = []
    try:
        for name, record in records['editor']['files'].items():
            if name.startswith('payload/'):
                _copy(editor/name, staged_payload/name.removeprefix('payload/'), record)
        runtime_path = staged_payload/CLI_RUNTIME
        runtime_path.parent.mkdir(parents=True)
        with runtime_path.open('xb') as target:
            _decode_cli(cli/CLI_GZIP, records['cli']['runtime'], records['cli']['files'][CLI_GZIP], target)
        _copy(parity_path, staged_source/'.opengeul-overlay.json', records['editor']['files']['source-parity.json'])
        (staged_source/'.opengeul-windows-components.json').write_bytes(receipt_bytes)
        audit_payload(staged_payload)
        fresh(payload); fresh(source)
        staged_payload.rename(payload); published.append(payload)
        staged_source.rename(source); published.append(source)
    except Exception:
        for path in published:
            shutil.rmtree(path)
        raise
    finally:
        for path in (staged_payload, staged_source):
            if path.exists():
                shutil.rmtree(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    capture_parser = sub.add_parser('capture')
    capture_parser.add_argument('--role', choices=tuple(CAPS), required=True)
    for flag in ('payload', 'source', 'out'):
        capture_parser.add_argument('--'+flag, type=Path, required=True)
    combine_parser = sub.add_parser('combine')
    for flag in ('editor', 'cli', 'payload', 'source'):
        combine_parser.add_argument('--'+flag, type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == 'capture':
            capture(args.role, args.payload.absolute(), args.source.absolute(), args.out.absolute())
        else:
            combine(args.editor.absolute(), args.cli.absolute(), args.payload.absolute(), args.source.absolute())
    except (ValueError, OSError, subprocess.CalledProcessError, tomllib.TOMLDecodeError) as error:
        parser.exit(1, 'Windows component integrity check failed: '+str(error)+'\n')
    print('Verified Windows component '+args.command+' (same-run transport selection remains required).')


if __name__ == '__main__':
    main()
