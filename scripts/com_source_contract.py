"""고정 CLI 원문·COM 대체 경계와 컴파일한 작업자 모듈을 필수 증명한다."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import tomllib

from buildkit import ROOT
from prepare_native_tests import TARGETS

CORE = 'third_party/rhwp'
LEDGER_PATH = CORE + '/.opengeul-com-worker.json'
FILES = ('mod.rs', 'wire.rs', 'windows.rs')
PATCHED_PATHS = ('src/main.rs', 'src/mcp_serve.rs', 'Cargo.toml')
FIXED_CLSID = 'c6c4d247-b4f0-563d-a649-4765796e3164'
HELPER_SHA256 = 'b27f6029d64308773a63a9ea70620b0d51ef7eb1ddb928658c3c1d3946e99bae'
NATIVE_MARKER = '\n# OpenGeul distribution-only integration gates.\n'
MAX_LEDGER = 64 * 1024
MAX_SOURCE = 4 * 1024 * 1024
REFERENCE = {
    'originalFiles': {
        'src/main.rs': 'a5dbc5951e0e3e95ed56a5c0f28980a912f9a38ddc8c3dd86213e03877a79e85',
        'src/mcp_serve.rs': '1b2ff2113d6c6dcfd0514fcc22bb14aad960bd62ef8d6fcedcbb13f8ab69b281',
        'Cargo.toml': '17d3f9d347d3d5c1011e3299ac85f640d9f31e854e442c4696f55da85809700b',
    },
    'patchedFiles': {
        'src/main.rs': 'd55823e3ea2325e5e78e4d46bd55b99ff17f28dcc6a53d67736a964f93231fef',
        'src/mcp_serve.rs': '205b4dab4f32f3996340c8e237b1b5fec3a39b74e8789bf34297da23902bd471',
        'Cargo.toml': '769745d72376286c03413925eff943af5014db3467e21798d9fc886044d02405',
    },
    # prepare_native_tests writes host newlines after appending the exact two
    # integration targets to the pinned COM-patched manifest.
    'preparedManifestSha256': (
        '8fbbc05a985091264101cf14fc4d01563eacef548fd9f7f02e68993e8aebc5e3',
        'db5bb7fa8f838c3597aaed8e4f85ba9acaa5d0f1eca290fe8240d3b045c093a3',
    ),
}


def _require(value, message):
    if not value:
        raise ValueError(message)


def _shape(value, keys):
    _require(isinstance(value, dict) and set(value) == set(keys), 'Invalid COM worker source ledger fields')


def _dependencies(config):
    raw = (ROOT/'overlay/com-worker/Cargo.toml').read_bytes()
    _require(len(raw) <= MAX_LEDGER and hashlib.sha256(raw).hexdigest() ==
             config['helpers'].get('overlay/com-worker/Cargo.toml'), 'COM worker dependency helper mismatch')
    result = tomllib.loads(raw.decode('utf-8'))['target']['cfg(windows)']['dependencies']
    _shape(result, {'windows-core', 'windows'})
    _shape(result['windows'], {'version', 'features'})
    _require(result['windows-core'] == '=0.61.2' and result['windows']['version'] == '=0.61.3',
             'COM worker Windows dependency version mismatch')
    return result


def ledger_bytes(ledger, config):
    fields = ('formatVersion', 'fixedClsid', 'helperSha256', 'originalFiles',
              'patchedFiles', 'copiedFiles', 'windowsDependencies', 'qualification')
    _shape(ledger, fields)
    result = {key: ledger[key] for key in fields}
    for key in ('originalFiles', 'patchedFiles'):
        result[key] = {name: ledger[key][name] for name in PATCHED_PATHS}
    result['copiedFiles'] = {'src/opengeul_com_worker/'+name:
                             ledger['copiedFiles']['src/opengeul_com_worker/'+name] for name in FILES}
    # The helper's TOML parser preserves source key order, whereas public
    # component metadata sorts nested keys. Recreate the exact helper bytes.
    result['windowsDependencies'] = _dependencies(config)
    raw = (json.dumps(result, ensure_ascii=False, indent=2)+'\n').encode('utf-8')
    _require(len(raw) <= MAX_LEDGER, 'COM worker source ledger exceeds cap')
    return raw


def validate(record, prepared_files, native_tests, config):
    _shape(record, {'ledger'});ledger = record['ledger']
    _shape(ledger, {'formatVersion','fixedClsid','helperSha256','originalFiles',
                   'patchedFiles','copiedFiles','windowsDependencies','qualification'})
    _require(type(ledger['formatVersion']) is int and ledger['formatVersion'] == 1 and
             ledger['qualification'] is False, 'COM worker source proof cannot claim qualification')
    _require(ledger['fixedClsid'] == FIXED_CLSID and ledger['helperSha256'] == HELPER_SHA256 ==
             config['helpers'].get('scripts/com_worker.py'), 'COM worker activation/helper identity mismatch')
    for name in ('originalFiles','patchedFiles'):
        _require(ledger[name] == REFERENCE[name], 'COM worker '+name+' source inventory mismatch')
    copied = {'src/opengeul_com_worker/'+name: config['helpers'].get('overlay/com-worker/src/'+name)
              for name in FILES}
    _require(ledger['copiedFiles'] == copied, 'COM worker copied helper source mismatch')
    for name, digest in copied.items():
        _require(prepared_files.get(CORE+'/'+name) == digest, 'COM worker compiled module source mismatch')
    for name in ('src/main.rs','src/mcp_serve.rs'):
        _require(prepared_files.get(CORE+'/'+name) == ledger['patchedFiles'][name],
                 'COM worker typed CLI dispatch source mismatch')
    _require(native_tests.get('originalManifestSha256') == ledger['patchedFiles']['Cargo.toml'],
             'COM worker and native-test original manifest mismatch')
    _require(prepared_files.get(CORE+'/Cargo.toml') in REFERENCE['preparedManifestSha256'],
             'COM worker compiled native-test manifest mismatch')
    _require(ledger['windowsDependencies'] == _dependencies(config), 'COM worker Windows dependency source mismatch')
    _require(prepared_files.get(CORE+'/Cargo.lock') == config['helpers'].get('overlay/cli-cargo.lock.toml'),
             'COM worker exact CLI lock source mismatch')
    _require(hashlib.sha256(ledger_bytes(ledger, config)).hexdigest() == prepared_files.get(LEDGER_PATH),
             'COM worker raw source ledger digest mismatch')


def capture(source: Path, prepared_files, native_tests, config, *, read_json, tree, sha):
    path = source/LEDGER_PATH;record = {'ledger': read_json(path)}
    validate(record, prepared_files, native_tests, config)
    _require(sha(path) == hashlib.sha256(ledger_bytes(record['ledger'], config)).hexdigest(),
             'COM worker source ledger changed during capture')
    root = source/CORE/'src/opengeul_com_worker'
    inventory, directories = tree(root, MAX_SOURCE)
    expected = {name: record['ledger']['copiedFiles']['src/opengeul_com_worker/'+name] for name in FILES}
    _require({name: item['sha256'] for name,item in inventory.items()} == expected and not directories,
             'COM worker complete module source inventory mismatch')
    for name in ('src/main.rs','src/mcp_serve.rs','Cargo.toml','Cargo.lock'):
        _require(sha(source/CORE/name) == prepared_files[CORE+'/'+name],
                 'COM worker compiler input changed during capture')
    manifest = (source/CORE/'Cargo.toml').read_text(encoding='utf-8')
    _require(manifest.count(NATIVE_MARKER) == 1, 'COM worker native-test manifest marker mismatch')
    before, after = manifest.split(NATIVE_MARKER)
    expected_tests = ''
    for name in TARGETS:
        expected_tests += '\n[[test]]\nname = "'+name+'"\npath = "tests/'+name+'.rs"\n'
        if name == 'opengeul_pdf_policy':expected_tests += 'required-features = ["native-skia"]\n'
    _require(hashlib.sha256(before.encode('utf-8')).hexdigest() == record['ledger']['patchedFiles']['Cargo.toml']
             and after == expected_tests, 'COM worker compiler manifest or native-test suffix mismatch')
    return record
