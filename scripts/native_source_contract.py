"""고정 WinRT compiler source를 producer와 consumer에서 같은 기준으로 확인한다.

REFERENCE는 검토한 공식 crate 원본 166개와 패치 결과 5개의 SHA-256이다.
archive checksum만 적힌 임의 ledger를 원본 증명으로 받아들이지 않는다.
원본·패치가 바뀌면 이 고정 reference도 명시적으로 다시 검토해야 한다.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import tomllib

from buildkit import ROOT, replace_once
from native_activation import FEATURE, VENDOR_VERSIONS, validate_lock

NATIVE_ROOT = 'apps/desktop/src-tauri'
LEDGER_PATH = NATIVE_ROOT + '/.opengeul-native-activation.json'
SHIM_FILES = ('Cargo.toml', 'LICENSE.txt', 'README.md', 'src/activation.rs', 'src/lib.rs')
MAX_LEDGER = 256 * 1024
MAX_VENDOR = 32 * 1024 * 1024
SHA = re.compile(r'[0-9a-f]{64}\Z')
PATCH_SHA256 = '6f03c803258d068b7cb41d5e839ece1a0a9ddbb4ef1ed9f4a9e23b61527caad2'


def _require(value, message):
    if not value:
        raise ValueError(message)


def _shape(value, keys, message):
    _require(isinstance(value, dict) and set(value) == set(keys), message)


def _digest(value):
    return isinstance(value, str) and SHA.fullmatch(value) is not None


def _prepared_lock_sha256(config):
    seed = (ROOT/'overlay/desktop-cargo.lock.toml').read_bytes()
    _require(hashlib.sha256(seed).hexdigest() == config['helpers'].get('overlay/desktop-cargo.lock.toml'),
             'Native activation lock helper mismatch')
    # prepare_upstream reads the seed as text and writes LF after replacing only
    # the HOP desktop package version. Preserve that exact compiler input rule.
    value = seed.decode('utf-8').replace('\r\n', '\n').replace('\r', '\n')
    value = replace_once(value, 'name = "hop-desktop"\nversion = "'+config['upstream']['hop']['version']+'"',
                         'name = "hop-desktop"\nversion = "'+config['product']['version']+'"')
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def ledger_bytes(ledger):
    """native_activation.apply의 고정 LF 직렬화를 key 순서와 무관하게 복원한다."""
    fields = ('formatVersion', 'patchInputSha256', 'originalManifestSha256',
              'preparedManifestSha256', 'preparedLockSha256', 'crates', 'shimFiles')
    _shape(ledger, fields, 'Invalid native activation ledger fields')
    result = {key: ledger[key] for key in fields}
    result['crates'] = {}
    for name, item in sorted(ledger['crates'].items()):
        result['crates'][name] = {
            'name': item['name'], 'version': item['version'],
            'archiveSha256': item['archiveSha256'],
            'originalFiles': dict(sorted(item['originalFiles'].items())),
            'preparedFiles': dict(sorted(item['preparedFiles'].items())),
        }
    result['shimFiles'] = dict(sorted(ledger['shimFiles'].items()))
    data = (json.dumps(result, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    _require(len(data) <= MAX_LEDGER, 'Native activation ledger exceeds cap')
    return data


def validate(record, prepared_files, config):
    """소비자는 로컬 원본 크레이트나 네트워크 없이 고정 source proof를 확인한다."""
    _shape(record, {'ledger'}, 'Invalid native activation source contract')
    ledger = record['ledger']
    fields = {'formatVersion', 'patchInputSha256', 'originalManifestSha256',
              'preparedManifestSha256', 'preparedLockSha256', 'crates', 'shimFiles'}
    _shape(ledger, fields, 'Invalid native activation ledger fields')
    _require(type(ledger['formatVersion']) is int and ledger['formatVersion'] == 1,
             'Invalid native activation ledger version')
    _require(ledger['patchInputSha256'] == PATCH_SHA256 ==
             config['helpers'].get('overlay/native-activation-patches.json'),
             'Native activation patch helper mismatch')
    for name in ('originalManifestSha256', 'preparedManifestSha256', 'preparedLockSha256'):
        _require(_digest(ledger[name]), 'Invalid native activation manifest/lock digest')
    _shape(ledger['crates'], REFERENCE, 'Invalid native activation crate selection')
    for name, expected in REFERENCE.items():
        item = ledger['crates'][name]
        _shape(item, {'name', 'version', 'archiveSha256', 'originalFiles', 'preparedFiles'},
               'Invalid native activation crate ledger')
        for key in ('name', 'version', 'archiveSha256'):
            _require(item[key] == expected[key], 'Native activation crate origin mismatch')
        _require(item['originalFiles'] == expected['originalFiles'],
                 'Native activation original source inventory mismatch')
        prepared = {**expected['originalFiles'], **expected['patchedFiles']}
        _require(item['preparedFiles'] == prepared,
                 'Native activation prepared source inventory mismatch')
    expected_shim = {name: config['helpers'].get('overlay/native-open/' + name) for name in SHIM_FILES}
    _require(all(_digest(digest) for digest in expected_shim.values()) and
             ledger['shimFiles'] == expected_shim, 'Native activation shim helper mismatch')
    for name, digest in expected_shim.items():
        _require(prepared_files.get(NATIVE_ROOT + '/opengeul-native/native-open/' + name) == digest,
                 'Native activation prepared shim mismatch')
    for key, name in (('preparedManifestSha256', 'Cargo.toml'), ('preparedLockSha256', 'Cargo.lock')):
        _require(ledger[key] == prepared_files.get(NATIVE_ROOT + '/' + name),
                 'Native activation prepared manifest/lock mismatch')
    _require(ledger['preparedLockSha256'] == _prepared_lock_sha256(config),
             'Native activation prepared lock derivation mismatch')
    _require(hashlib.sha256(ledger_bytes(ledger)).hexdigest() == prepared_files.get(LEDGER_PATH),
             'Native activation raw ledger digest mismatch')


def capture(source: Path, prepared_files, config, *, read_json, tree, sha):
    """컴파일한 준비 tree 전체를 감사한 뒤에만 producer 증명을 만든다."""
    path = source / LEDGER_PATH
    record = {'ledger': read_json(path)}
    validate(record, prepared_files, config)
    _require(sha(path) == hashlib.sha256(ledger_bytes(record['ledger'])).hexdigest(),
             'Native activation ledger changed during capture')
    expected_files = {}
    for name, item in record['ledger']['crates'].items():
        expected_files.update({name + '/' + filename: digest
                               for filename, digest in item['preparedFiles'].items()})
    expected_files.update({'native-open/' + name: digest
                           for name, digest in record['ledger']['shimFiles'].items()})
    actual, directories = tree(source / NATIVE_ROOT / 'opengeul-native', MAX_VENDOR)
    _require({name: item['sha256'] for name, item in actual.items()} == expected_files,
             'Native activation compiler source inventory mismatch')
    expected_directories = {parent.as_posix() for name in expected_files
                            for parent in PurePosixPath(name).parents if parent.as_posix() != '.'}
    _require(directories == expected_directories, 'Unexpected native activation source directory')
    for name in ('Cargo.toml', 'Cargo.lock'):
        _require(sha(source / NATIVE_ROOT / name) == prepared_files[NATIVE_ROOT + '/' + name],
                 'Native activation compiler manifest/lock changed during capture')
    validate_lock((source / NATIVE_ROOT / 'Cargo.lock').read_text(encoding='utf-8'))
    manifest = tomllib.loads((source / NATIVE_ROOT / 'Cargo.toml').read_text(encoding='utf-8'))
    _require(manifest.get('package', {}).get('version') == config['product']['version'],
             'Native activation compiler product version mismatch')
    windows = manifest['target']['cfg(windows)']['dependencies']
    _require(windows.get('opengeul-native-open') == {'path': 'opengeul-native/native-open'}
             and 'open' not in windows and 'open' not in manifest['dependencies'] and
             manifest['target']['cfg(not(windows))']['dependencies']['open'] == '5',
             'Native activation desktop dependency contract mismatch')
    _require(manifest['dependencies']['tauri'] == {'version': '=' + VENDOR_VERSIONS['tauri'], 'features': [FEATURE]},
             'Native activation Tauri feature contract mismatch')
    for name in ('tauri', 'tauri-runtime-wry'):
        _require(manifest['patch']['crates-io'][name] == {'path': 'opengeul-native/' + name + '-' + VENDOR_VERSIONS[name]},
                 'Native activation vendor compiler path mismatch')
    _require(manifest['workspace'] == {'members': ['opengeul-native/native-open'],
             'default-members': ['.'], 'exclude': ['opengeul-native/tauri-2.12.5',
             'opengeul-native/tauri-runtime-wry-2.12.3'], 'resolver': '2'},
             'Native activation workspace contract mismatch')
    return record


REFERENCE = {'tauri-2.12.5': {'name': 'tauri',
                  'version': '2.12.5',
                  'archiveSha256': '5fb0244332cfb9cee7e2a568bf5da29a36ed8fdbd717f6f47a66b6b7b358c072',
                  'originalFiles': {'.cargo_vcs_info.json': '8537afb4fe7e71c689f778070c5b68b12eb04765f5ab9b84427be574e07f9db8',
                                    'Cargo.lock': '74d52b73d9bff1ccdfe01e3eac4411712fb439cba5825e86184bbefa3f07828b',
                                    'Cargo.toml': '7ecaec70bb98cfb858e7ec5ec88122915584c414ac747208916912e05d3026c7',
                                    'Cargo.toml.orig': '8bf5fc10c4cc637dc343d0ea872771a9f04806cf825b69f59e75d7ccf4f3b183',
                                    'LICENSE-APACHE-2.0': '0d542e0c8804e39aa7f37eb00da5a762149dc682d7829451287e11b938e94594',
                                    'LICENSE-MIT': '9dd42ea92cff2ede5cd477cbfcce051b2d0115c0ac7f368ee88cb545055dff1d',
                                    'README.md': 'd53737b76e569ea9d7af01d69be6fb729959b97bc08d0564a421c3917b584070',
                                    'build.rs': '98109a67415599af635edd9c041ccdd9b92525556d012369e59cb4b4df25ca29',
                                    'mobile/android-codegen/TauriActivity.kt': '575a5890676bcc363294d2e3ec6ebe0a3943358fac4bc168e7ea2df0b7bc3640',
                                    'mobile/android/.gitignore': '5c3174b74edc6f2b9e0743594b8bd3c7f31e4f4405758cc9872b3fe1de1d28b4',
                                    'mobile/android/build.gradle.kts': '7cd902e29c3d5e495600f98669fb67a2b7983d58e69e627fc7d8778be58802d4',
                                    'mobile/android/consumer-rules.pro': '07ae2ffe37f0f484c46401f510ef003e1bbe9f708d1d2597546c729eb9956cca',
                                    'mobile/android/src/androidTest/java/app/tauri/ExampleInstrumentedTest.kt': '1e7c0c6f613431962750a2f80dcf8a0c231c4b5fb2f569bfd55b5fa0e80f2e7d',
                                    'mobile/android/src/main/AndroidManifest.xml': '8ef94a6aec2218c5fd02408d018f6d52602c0ef4473dd1c115c5c6964f1e63e1',
                                    'mobile/android/src/main/java/app/tauri/AppPlugin.kt': '087ae5fb739031d886365aeed1c27bde043c5f7d00f892050662bc602e7451b4',
                                    'mobile/android/src/main/java/app/tauri/FsUtils.kt': '217851c9539c6171c46354fb24c8af9501babd045a122e239f01009794d122c9',
                                    'mobile/android/src/main/java/app/tauri/JniMethod.kt': 'ece2f2b7179edeb9cf0a62acb116390f53c23a32e51520b6e4c2d7601a581a88',
                                    'mobile/android/src/main/java/app/tauri/Logger.kt': '771fa4822dec7cc95aab726ee1c176c17970c4ffee737ad53959fea1fa26ef7d',
                                    'mobile/android/src/main/java/app/tauri/PathPlugin.kt': 'fe5a98a6ed0ca6e34aa1ea0ee190c16e8e07766e59938f5fb22cf1b5e8f8ed41',
                                    'mobile/android/src/main/java/app/tauri/PermissionHelper.kt': '7df0ea86bfa5159a5fbbf7660687c36d15d7cf2cd167d051144e4447a650cb8e',
                                    'mobile/android/src/main/java/app/tauri/PermissionState.kt': 'c38e1f200db71faf05f8d7acf643b2f1d6dd8970b8ae51a6a7c842743a596be2',
                                    'mobile/android/src/main/java/app/tauri/annotation/ActivityCallback.kt': 'aec0ebccfe66d7b857606a9244e717d5aa3b02324f50fbdfe4b4ee1a67ad8637',
                                    'mobile/android/src/main/java/app/tauri/annotation/InvokeArg.kt': '6b747509a75a7c8f1c31c03a23a80b4f83cd226f87033a318db1782505b2aeab',
                                    'mobile/android/src/main/java/app/tauri/annotation/Permission.kt': 'bca04adb46a3de1c36da755fb62a5efb40481a7a529dd0f727eadd95466ecbd7',
                                    'mobile/android/src/main/java/app/tauri/annotation/PermissionCallback.kt': 'd0a63179ca048629d37e9efe696d2c6554095b7de64bbbc1450a8f07d3888d8e',
                                    'mobile/android/src/main/java/app/tauri/annotation/PluginMethod.kt': 'aee7aef7a3f59ad67ca3a2cfbcb2a2c2cacfa28bddf4b2f565ed6e930f92c8c1',
                                    'mobile/android/src/main/java/app/tauri/annotation/TauriPlugin.kt': '361783a7baf30a33192c22f922f50fb2c97d8a7d9ae9dc774d8b637f9eeea04a',
                                    'mobile/android/src/main/java/app/tauri/plugin/Channel.kt': 'f6f5c2dcc442b9e81165f55f80d363129bc91b130586abb8489cd3006af00011',
                                    'mobile/android/src/main/java/app/tauri/plugin/InvalidPluginMethodException.kt': '90d2dddfb918447ed8fd35c44be7f00e41b89fcd586eeca995e0ead56c38b6c4',
                                    'mobile/android/src/main/java/app/tauri/plugin/Invoke.kt': '05cadb94907dbd3979d8c7eaad7bd8f540c38cc9d988a5513777eadd18330028',
                                    'mobile/android/src/main/java/app/tauri/plugin/JSArray.kt': 'fca8b72a6bf357b6cc57aa21ac787dbe3d69fca27f927b0c3f598567dc17f52f',
                                    'mobile/android/src/main/java/app/tauri/plugin/JSObject.kt': '234a9afa4da858b3dbd8d5a688209a640984166482e040ab908b34ed577726b5',
                                    'mobile/android/src/main/java/app/tauri/plugin/Plugin.kt': 'c5dc0d1b59ac2024399afd0893f1182ae583b4d4f2cc88a5ba7864d365f77f7c',
                                    'mobile/android/src/main/java/app/tauri/plugin/PluginHandle.kt': '628b69f19d03b861765a2f7f3140e5b6a79bd991966019bb250bf7ae79bfd301',
                                    'mobile/android/src/main/java/app/tauri/plugin/PluginManager.kt': '053958be1e83d8633d26348ded26bbd6d4ab21121e662985194fa3342eef1e95',
                                    'mobile/android/src/main/java/app/tauri/plugin/PluginMethodData.kt': 'c3024eb23b038fdd1566e69db725c8c5d39fb66909baf45d258ccfe8449daedf',
                                    'mobile/android/src/main/java/app/tauri/plugin/PluginResult.kt': '437f44a6ccf5354a5ec1a3a3c894609f6df90999f397e52dfaafb6e74d30c006',
                                    'mobile/android/src/test/java/app/tauri/ExampleUnitTest.kt': 'c0b0b313769a0e3f519c203bf0862f35bd6128a6eeef67ca4965c12b4ef0ac4b',
                                    'mobile/ios-api/.gitignore': 'bc9466a4cd82cf38d2a4471c15c5c6b8153182f361a72c9926a9f422d966e3b0',
                                    'mobile/ios-api/Package.swift': 'd2d922090185ea571cddd4a1d88d353225aceae99fdbc52a8995080809a3add2',
                                    'mobile/ios-api/README.md': 'a06a181db430708640f970ac98611e3feea64430d5b4ab82c15d778604937591',
                                    'mobile/ios-api/Sources/Tauri/Channel.swift': '850e8239ccb561ea7177f0f66b33d5b63e97faeefcb79b60640007934c3894a4',
                                    'mobile/ios-api/Sources/Tauri/Invoke.swift': 'afc9ee63daafe1754969b6dfd104d49d2ca09fd41e7c6343063c13d9e56f7d3e',
                                    'mobile/ios-api/Sources/Tauri/JSTypes.swift': 'bce9da78d74d495a2d05176cb0b68bd9a40ebfcac8c8e9cb1678d4ca142bd653',
                                    'mobile/ios-api/Sources/Tauri/JsonValue.swift': 'a22a4bad5788132955a63160bda00eeb62a6e138993d46504f6f96e2fb94246d',
                                    'mobile/ios-api/Sources/Tauri/Logger.swift': '9624719792f6ce0baf6df0aaf2928efc8c0aef77972a3fb638ce67e3a6dfb918',
                                    'mobile/ios-api/Sources/Tauri/Plugin/Plugin.swift': 'e5d2e0e6f6c178b0ea2745dcd88f68b6a142154c3b245845bb6b9026b3a76d69',
                                    'mobile/ios-api/Sources/Tauri/Tauri.swift': 'c642bec9d8ce5305f109d950cdb95e3d06e6debaef784da61f35b0de857f223b',
                                    'mobile/ios-api/Sources/Tauri/UiUtils.swift': 'c12b2a5a3bde289c45dd6c348cc41d7072c81a1559eac76339ea061c4fa5d89c',
                                    'mobile/ios-api/Tests/TauriTests/TauriTests.swift': 'ef1e10dafc147b1d6b145f19ab0a81cb44eb80d7b989abfae4e2447209a88a34',
                                    'mobile/proguard-tauri.pro': '9f6f2555912c6b984ab9be8e4766da646b175dd33c3a193a4d72c4a56a1b6a2c',
                                    'permissions/app/autogenerated/reference.md': 'f8e0917f509f1607e16d6bbdc6218a96c69fc7113f143a0df03d943251268a84',
                                    'permissions/event/autogenerated/reference.md': '018766e1817884ed384b525480e58e63d1860994441c114d1a2517967a267d49',
                                    'permissions/image/autogenerated/reference.md': 'e3fe93fbb7e62c0139592f4b030d50254c1fbbcc518785bb98ab1f037e251e5c',
                                    'permissions/menu/autogenerated/reference.md': '4bed65930223d505c3fc3295d299f07165d5b355b7a5ba910501fc089b2f0044',
                                    'permissions/path/autogenerated/reference.md': '8be6a806aaaf1a081fe25aadabf253b74337c5f31b5f356c078ce43ddd47a098',
                                    'permissions/resources/autogenerated/reference.md': '593941263d28df065d95a9db260220fad053d4c5aca3b74a9d58977199127210',
                                    'permissions/tray/autogenerated/reference.md': 'f17969a556be8c3788821cc5eaffa3a2604ab78f647aaae294305a93b67c0178',
                                    'permissions/webview/autogenerated/reference.md': '5ee143504a878ca35dcd1277310c152fc93668da50573c1acfab051fa9cfe8ec',
                                    'permissions/window/autogenerated/reference.md': '9c688eabe29028b8e183b656fdcefd06a0d43f0903607c80a61886f38015483b',
                                    'scripts/bundle.global.js': 'a3b7a940291799a812e00653bc3ddbe087063627bffa9d8d97a4e33debe9e358',
                                    'scripts/core.js': '71056442a732cca1f03572ccae96d68e16104c3a591c64de9618cd304e063070',
                                    'scripts/freeze_prototype.js': '599745f0da51f0ba6c7dcbb7c770d6f538f337f6df7f1bf420e4043b9e4b6bf9',
                                    'scripts/init.js': '2a062abc65bc99ac458dd9a78701a8a9e3f473aa1f25afa64dc810036932f973',
                                    'scripts/ipc-protocol.js': '68ae690606006f733bde75dd8bb6748464954a22c7e83914a93b1abc221d7072',
                                    'scripts/ipc.js': '3e3766fc90efa68003096cbf0a07c6a00cb31c5756d55b5a68ebbfd2930c4865',
                                    'scripts/isolation.js': '58e79828ba6d68c79eceb276d62f766710f77df70c5fec1f79176bd6aa6d0ae1',
                                    'scripts/pattern.js': '149570459687f1636c02e41ede8b40efe52378965eeddb6dbfebc0c525a3551b',
                                    'scripts/process-ipc-message-fn.js': 'd51917f89e4d3d318d63f1f4f5a7ac7ea1399a5b85c81a840c4d606597f29132',
                                    'src/app.rs': 'ef71e5c2da6696f9bef817f5f32d34c7710b678ca7ec8a00e539527bca5ad1d4',
                                    'src/app/plugin.rs': '68ae251a4c9abbbef89d618784ce81e6557396a0f1e0fcdc9b5c0653e3782c6d',
                                    'src/async_runtime.rs': '2e46673c2b396b34cc70e8a09cabce4ea9ef0eb517b782d1825299d2e998209c',
                                    'src/error.rs': 'dfe50c5983d770d846d88ea3b0b83d156d36fb8ae1636fbb90d8f5bf481bc8b7',
                                    'src/event/event-system-spec.md': 'ca15ed691a62d531b790f1fab1d3b07f6e5dad3711c14e6c821d64b802038e02',
                                    'src/event/event_name.rs': '982908c70b4d51378d2298f8446fbbf1dbb253856b46c591c680303affd4765e',
                                    'src/event/init.js': '8946488895cc9879f2bf8fee98be454d0f21949b946c264b47d2a2fc84eb1df0',
                                    'src/event/listener.rs': '17ad77a53df1669aeb80fabc20b1496ebf41e67583a5e01676c61222ee2b3873',
                                    'src/event/mod.rs': 'dad05d91113bb2c932318db93a2dcf534d995c49039cd24cc66463690c82d6d3',
                                    'src/event/plugin.rs': '32f3b01840e02b21b34e8ec7e35fdc27123717ee4a27d44f26c6814e7df44f0f',
                                    'src/image/mod.rs': '3ea357f4b38c35bb48007fa10fb9180f90dd4a072995c84f4b6e8dae5d431334',
                                    'src/image/plugin.rs': '921e0dc65f9923fd742c7d431162ca2166aa43994eb454d9cc9ae8f534daa60e',
                                    'src/ios.rs': 'c5dec514616e24eb39419985f48de428449eb9a4e46884a98130c6c35f938c05',
                                    'src/ipc/authority.rs': 'e0d98da404549cc74fe4c5a7b038a3b45f8886fe11a38fb690e9a13e0ce5e6d8',
                                    'src/ipc/capability_builder.rs': '835d94cfb7d021a7cdacb1210bf4e01eb587c4d71317878ebde40080f72a28cd',
                                    'src/ipc/channel.rs': '9d20fad897f8377484c7bd7f63b030653501a08b36f03def9cc5123c2a98623e',
                                    'src/ipc/command.rs': 'f5ee670a88bb1ac69e51c2c7ca22d82b11dc183d447c74720a7354a9b9e37fd2',
                                    'src/ipc/format_callback.rs': 'e9de68956b9437f440291d37292bb9544b6c0b180029e6d2772685aa768a494d',
                                    'src/ipc/mod.rs': '6aa3624871ec604883e799e728346e6f474808589ab5b67c1db7bc600ef0068b',
                                    'src/ipc/protocol.rs': 'bf93dc095490db290d5d3fc2a3c81fa0778ca8142911a7c2f97dcbcc98b3be97',
                                    'src/lib.rs': 'fda874d750f7ce7959b5914707257ebd49b4a619d2e1c23c74b52821371c2bd0',
                                    'src/manager/menu.rs': '3bb2b10650ed22166eaf28f8d7dbee1333a9f2a1908be4532d3fd4e621b9603d',
                                    'src/manager/mod.rs': '6e39aff7d45d40f163a26f2b9484f1aab6977209762204a0650b9d3ad9636793',
                                    'src/manager/tray.rs': 'b84c32a8921e5a9da80ff388d6c529e45713a5f7fc8f6be1b09795748a04edc7',
                                    'src/manager/webview.rs': '3bfb8bba5dbd61d08ec5ff4ce2fa882997df78666b840a8f13b30aea2c2e7381',
                                    'src/manager/window.rs': '01afc333b4d626650a3e23cd526018bb6dd01e7dab8b45680b9f99404dc63b25',
                                    'src/menu/builders/check.rs': 'b50d23149fbf6ef12f9ef126f0c9e6ec759bb0126ef2f5b669069c44fc07cb74',
                                    'src/menu/builders/icon.rs': '5acb00bab97cf8ed585d2c0a97872a4a8fc7f170272e5ef77262b9b9aefb43f2',
                                    'src/menu/builders/menu.rs': '270946a7cd242bd14ce993ffe2df8faa08e2984dc6a362ba882c20b019632716',
                                    'src/menu/builders/mod.rs': '8e47f079550864a58a0a9b3e0dcce452ccc210ac303861bb91b92b7553b497ea',
                                    'src/menu/builders/normal.rs': '2b93c00d50b9bf4f01dea4be90bbe902997cc6319f9a01e201ca324f61dce783',
                                    'src/menu/check.rs': 'c18429d823a153631295ea1b7abf206ca7be5e3d273f87d3b3dbf4a4e844d03a',
                                    'src/menu/icon.rs': 'b9e556a6387dadc723d3db1b66cfea035134dd3aab6323cb2e73c01d78b0a830',
                                    'src/menu/menu.rs': 'dc892512d5718a15f994193a329d59301cbaeb545c00c0c4e1b74f4d7bc5d789',
                                    'src/menu/mod.rs': 'c534080732897386d0b0bc531d1f702c50f5c0ddc472659bb0da49bf6e5076af',
                                    'src/menu/normal.rs': 'cd8243024d763935c0c3c8d521b6513c0b7a02eae029bdf83b3f0614c68f1485',
                                    'src/menu/plugin.rs': 'af225e605a40a4e360fecffaa3c2cf508ac7ada8a368ceadb5144e8f743162f0',
                                    'src/menu/predefined.rs': 'dd082dcd3b4f77bd3130c567856ab2cd575b3fcb3b502e554457115411a18a07',
                                    'src/menu/submenu.rs': '83acf7bd950faa49a501addb0ca3ebc14935db91c54de96d81a03977a2bb8606',
                                    'src/path/android.rs': '8d82a2cb98a062bc115f0f68fdcfff0ec7a12771c7278e5cd6fe549f9e282214',
                                    'src/path/desktop.rs': '5da45b29ceeeb002e67e73bb8de84c8648dfb9f8efa4471d6ff40976729de477',
                                    'src/path/init.js': '6ecfef8c9078a591f04c5eb7ed355721efcba1eb820a0b5067be1dcca7748ef3',
                                    'src/path/mod.rs': '342c7b8fe55de2284cad6667c5d86296f143539aa3c8b4dba645a449b26dcf05',
                                    'src/path/plugin.rs': 'b6e69d7dfe1490cd21125abef6aad35a5f56661a0a54484e5276a2ff1d436381',
                                    'src/pattern.rs': '0d4a4f4c88fa93a590a3e9ce3e0438dd4263b42ab27cc2424bb83de7c8a56edd',
                                    'src/plugin.rs': '8c8a9c3cdb93d1d149f1f1822e5bf8cd5e454f1ce7f3e57a427b97ba59f52a9f',
                                    'src/plugin/mobile.rs': '7a59c1bb02d56dc88410c74c4f83fe79aa4b08229b6a2f64f025eace9fc1b186',
                                    'src/process.rs': '4bd9af755113e8ed6230cb301748a12ec454e490ade398d397bf518e5d4f0075',
                                    'src/protocol/asset.rs': '14a045e4d5d6eebaa9a334bca08726d078db13cea547bfc06676832c30a48bc2',
                                    'src/protocol/isolation.rs': '65ae247b18dd551e7ce9a1c535beb5114891d73f33ddef50f3c8c9d3de7062af',
                                    'src/protocol/mod.rs': '4c5bffce1f2b4a493a0a8daca3c84551ccc78a3d06a1c8bbe17dcc1dfd7f31fa',
                                    'src/protocol/tauri.rs': '8f9f0e76176535d3d922ce030b104d4164c24fb161a18046d730860edae0945a',
                                    'src/resources/mod.rs': 'c70407d96ebe8851ed7d269cdd7ee167c148d542dc08026086ddb8473f46a4ce',
                                    'src/resources/plugin.rs': '4aa9ad316ace48bf9821f4cfb7a88134f92f97ed5d73d9e7ff8e33b628ac0c6e',
                                    'src/scope/fs.rs': '13f7132cc2cb4c2985a97bb5a60bfb5551e712992eec0977445de861e7440c15',
                                    'src/scope/mod.rs': 'f72963f21cdfddeac4a60dd6609765b699ec86cbde293314a55f09779c4583b1',
                                    'src/state.rs': '2a6982ffa78274c476d2af7af785c94f36a033de030fa382cd727b18595481b8',
                                    'src/test/mock_runtime.rs': 'ef04c3634879fd347d994c73666becbe85fe5001347e73ac5d35cde64dc05ee5',
                                    'src/test/mod.rs': '99dbbe5445c5a8619624b2a3d9ff90ca95d4f4bdcd431e1f5e11157d431c4618',
                                    'src/tray/mod.rs': 'ff073c5dec626463e013e133bed97553fce3f7b9fa1b007dd6e16a5886ced052',
                                    'src/tray/plugin.rs': 'b59e76ce21cb806037744997af9d15e13bc023aeb9a4755506429847f86aab43',
                                    'src/vibrancy/macos.rs': '053b272e9eeb4c99356486d3afe8ead9cc6f8827ed6894c1cfe875083add468f',
                                    'src/vibrancy/mod.rs': 'dbf1cfbc0783cec7af0f8156bed76b9e737d80f17720ad0f46a8fa209fe95f40',
                                    'src/vibrancy/windows.rs': '7cc46026788b31a9d08f7820d73fe69957ed5289b7ef6e3692cea885a1245522',
                                    'src/webview/mod.rs': 'b5319b171c09a8e652d75585be39d92b387df370340ca90b58141b501c17009a',
                                    'src/webview/plugin.rs': '5a7ac2c1401c8c06946e00b6bc8956d3efcdcb4f494aeb794e5ed7053ac0fc71',
                                    'src/webview/scripts/print.js': '2a7c344c3c7285cc30ae14b741484db1acf24f03a22bda6ffe6c6d16d8acbf0b',
                                    'src/webview/scripts/toggle-devtools.js': '433c08901992823a37396ce72a695636bd034c1b960364b7d9c75f261f771770',
                                    'src/webview/scripts/zoom-hotkey.js': '3a29990c1551bbb7bbca34e318dd6a044963c6d8b7cc14c1600db6e6f45fdc97',
                                    'src/webview/webview_window.rs': '5cf28b52b0ed7179926b1087df08d8765bf2c31805fb532f9260908a57422230',
                                    'src/window/mod.rs': '58734d4a9165cd270b021bee75310b897d7d3f4ad64644b1b574b898a48fa153',
                                    'src/window/plugin.rs': '125ce6fffffdd5ba7aec2b0bd4c75fb83a4fad868e11f93cf725a2ec7b664eab',
                                    'src/window/scripts/drag.js': '2d47d2e302512024af4ded95b89f8b1f5c8d83530d287c252052112901a59888',
                                    'tests/restart.rs': '8b74b8e3845b0cf8ee7233fb5d3327b6099ec34db6cb4ca33aebd20a3ecacdc9'},
                  'patchedFiles': {'Cargo.toml': 'eba29bdefac17aa5f45dcab5b028996a167e3ac9d398b15d75d08a42db7ed69f',
                                   'src/process.rs': '7b270507e5882935ba685d254e67a1b0564ab9cad8a3a0263751716d37d2c306',
                                   'src/app.rs': 'bd7f510437e1021721cc6839114e9425e81d1af347cb706a7721338c5fa1c40f'}},
 'tauri-runtime-wry-2.12.3': {'name': 'tauri-runtime-wry',
                              'version': '2.12.3',
                              'archiveSha256': 'e1aa9d8b7a120f879f44fdc1053f7b7dbf416bf0bbc6a72b714dec46b782b52f',
                              'originalFiles': {'.cargo_vcs_info.json': 'ee78dea43d942dce4445107474e64ff80152b0f8bb617706943049b229d680c0',
                                                'Cargo.lock': '1113b853a8f241413ddff0023729572ff0de8dae6e9c4eb4cd54b7b1b9ad4518',
                                                'Cargo.toml': '88bdc06cd424f92acd4da737c17200fdf1301982def6a9204afab32c37a1cf70',
                                                'Cargo.toml.orig': '2eaca382037b6bd5583701340882964b2bd52dad2b367fd918c2c6118a5bb271',
                                                'LICENSE-APACHE-2.0': '0d542e0c8804e39aa7f37eb00da5a762149dc682d7829451287e11b938e94594',
                                                'LICENSE-MIT': '9dd42ea92cff2ede5cd477cbfcce051b2d0115c0ac7f368ee88cb545055dff1d',
                                                'README.md': 'cf468efdcd6eb86ef6a2c0b1fbe6aca80f0df6a9d3016f77c0bfdb64dc4091c0',
                                                'build.rs': '68b2727346e58a9963803a75ac29695b500aaa7d0673e18551465502b60cbf11',
                                                'src/dialog/mod.rs': 'ed391f94760a3f257ea7244fa62ad9b536e41f52f83b3994dedde23e5bbd287d',
                                                'src/dialog/windows.rs': 'cb340da9de1e9688e281be9bab126cdb48ddd5802c8aabceb82170c8f1f00518',
                                                'src/lib.rs': 'ec343fc347aff1fb5327100df2541992e47eb6be1ddb55102170e2253b9c6d59',
                                                'src/monitor/linux.rs': 'ebf2b48ebe0fa8facd0457fc5d16dc3156842e65a6c6334b1e0e4daa439160b2',
                                                'src/monitor/macos.rs': '31bfae5bf45dff98c68a1f2f19d8787cba5e3f0575d7d13ec564e524d79abae8',
                                                'src/monitor/mod.rs': 'f3a4161b3306afa32edb416d6c81773749d32f3068018eb83e32f055ae4c31c2',
                                                'src/monitor/windows.rs': 'c177f8f1d7d7f40350076a89d495511c1fd24d79d2f44fb6a1efd0d7e1726657',
                                                'src/undecorated_resizing.rs': '68973f395909062fc92f7ac9a3b6968b1a97b5192249d82e12326658c6ba7a3c',
                                                'src/util.rs': 'e62f698760e663b6d7204c1d48afa523487284e8be521992465353a9a66c428c',
                                                'src/webview.rs': 'e38ffe02336ee9bd558b444b6c6efa6a6a9fdfbaebfa8b441e925a37ae1828c8',
                                                'src/webview_permissions.rs': '84b1285e40854edb12286731cc2232955fd95ac3bc881f7d5ebb6376a3cab3f3',
                                                'src/window/linux.rs': '8cae057b27bd9576aefada130cb68eb0e39ce0e73af3dad793bab7d03b269ce2',
                                                'src/window/macos.rs': '23568a452b8e0da7b6627929e6ae05dd54b8bcec16cf91cff7ce2b1a7f818142',
                                                'src/window/mod.rs': '8f61d6436681791f011367948eef559192e8bee441446525c76c4917f15e5185',
                                                'src/window/windows.rs': '87236e11e0e18c9a09a916072a5c6a599f0bda44d6416cbcf2ec7a17dd0f6c54'},
                              'patchedFiles': {'Cargo.toml': 'e68a7a545046a01d8f6138c31971886def4e9a918528044d73901c91b787bc90',
                                               'src/dialog/windows.rs': 'd2a849e3ec69770c217eae0c1c8207f0c6c8b3849219a908d9ac946406a457fe'}}}
