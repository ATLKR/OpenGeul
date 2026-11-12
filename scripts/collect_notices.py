"""Collect dependency license texts; creates a review inventory, not a legal clearance."""
import argparse
import hashlib
import json
import ntpath
import os
from pathlib import Path
import re
import stat
import subprocess
import tomllib
from frontend_dependencies import PREPARED_LOCK_SHA256 as REVIEWED_NPM_LOCK_SHA256

ROOT = Path(__file__).resolve().parents[1]
RUST_SKIA_NAMES = {'skia-safe', 'skia-bindings'}
RUST_SKIA_VERSION = '0.156.0'
RUST_SKIA_COMMIT = 'ce6727ef251518df37bcfdde4865b71f7e3a4352'
RUST_SKIA_SHA256 = '4b33ed5b329a3a79eb1243fd91373c68b0ae0b9df7503bfc50d0c5253adf1b9a'
RUST_SKIA_NOTICE = ROOT / 'notices/rust-skia-0.156.0-LICENSE.txt'
RHWP_SOURCE_COMMIT = 'c9095c5f67632e6721e800ccc7fb43ea49d26682'
# These source-package notices are not all at Cargo's package root. Keep their
# exact origins in the review inventory without claiming that every asset ships.
SUPPLEMENTAL_NOTICES = {
    'rhwp-pdf-import-backend': {
        'version':'0.3.78-rhwp.1', 'license':'MIT OR Apache-2.0',
        'directory':'vendor/rhwp-pdf-import-backend',
        'files':{
            'src/fonts/assets/LICENSE-DejaVu':'5fe93f9ee914fc7c4f0cfc73b7b0e972167f1b8f89ba57f9ad55d6013eb8a8ac',
            'src/fonts/assets/LICENSE-NotoEmoji':'8d64bebb6ad6958b0f38a25e2ca948ffc5df8bca30bfb55d92a67244e1c8fec0',
            'src/fonts/assets/LICENSE-fallback-fonts':'7fee68f76f08309b3a599bd93c66e0c5f263e6ccfe98dbe74ecfabbe1eb77429',
            'TRADEMARKS.md':'09fbcb46691825dc4f3a981e841b6f0521543419860ca1aec64cd576ec067277',
        },
    },
    'rhwp-zune-jpeg': {
        'version':'0.5.15-rhwp.1', 'license':'(MIT OR Apache-2.0 OR Zlib) AND IJG',
        'directory':'vendor/rhwp-zune-jpeg',
        'files':{'README.ijg':'75815e3bf6484201a3c3d17a1bbf10f2e8e3237f84df10a2357ea896db2a81d6'},
    },
    'rhwp-hayro-jpeg2000': {
        'version':'0.4.0-rhwp.1', 'license':'Apache-2.0 OR MIT',
        'directory':'vendor/rhwp-hayro-jpeg2000',
        'files':{'assets/LICENSE.txt':'469d87b5fa48f8aaf69e25f4fcac3a309c97dbb7d561b917638abdb640e004d9'},
    },
}

# Exact reviewed omissions only. Additional third-party notices do not satisfy a
# package's missing declared-license text or change its declaration/clearance.
REVIEWED_SOURCE_NOTICES = {
    ('cargo', 'r-efi'): {
        '5.3.0': {
            'license':'MIT OR Apache-2.0 OR LGPL-2.1-or-later',
            'manifestSha256':'dba000c0173b09b1e3b69afa42a715b5ab64355e6502ce6d9d1767c7845cf402',
            'sourcePath':'AUTHORS',
            'sourceSha256':'ff92bed461f50338dd703a9ba9aee496a425957873df1d91192776e4bdf5dda7',
            'noticeSha256':'ff92bed461f50338dd703a9ba9aee496a425957873df1d91192776e4bdf5dda7',
            'packageLicenseText':True,
            'sourceUrl':'https://raw.githubusercontent.com/r-efi/r-efi/97b55bed1c2c91dcbf787674849f05337ff80b33/AUTHORS',
            'packageProvenance':{
                'archiveUrl':'https://crates.io/api/v1/crates/r-efi/5.3.0/download',
                'archiveSha256':'69cdb34c158ceb288df11e18b4bd39de994f6657d83847bdffdbd7f346754b0f'}},
        '6.0.0': {
            'license':'MIT OR Apache-2.0 OR LGPL-2.1-or-later',
            'manifestSha256':'a021f9fb0645cc5de5770cf7f41594c1deff4b388eca933b289752aa52666829',
            'sourcePath':'AUTHORS',
            'sourceSha256':'d027e91dbc9cdbb2f1190068e498bd6b61cff022b6a032b191021ba658d96111',
            'noticeSha256':'d027e91dbc9cdbb2f1190068e498bd6b61cff022b6a032b191021ba658d96111',
            'packageLicenseText':True,
            'sourceUrl':'https://raw.githubusercontent.com/r-efi/r-efi/7e1b0322d31d625f81a5656096330934f9cd835d/AUTHORS',
            'packageProvenance':{
                'archiveUrl':'https://crates.io/api/v1/crates/r-efi/6.0.0/download',
                'archiveSha256':'f8dcc9c7d52a811697d2151c701e0d08956f92b0e24136cf4cf27b57a6a0d9bf'}},
    },
    ('npm', 'rolldown'): {'1.2.16': {
        'license':'MIT',
        'manifestSha256':'525884560d75c4eecb362453e6bbf92b1618d2261ddfbb1a806f164be0813f84',
        'sourcePath':'THIRD-PARTY-LICENSE',
        'sourceSha256':'a877291d800ed43692f3f9ae09d8e01cc6f7293ad39d43896059c188ffbb8b7c',
        'noticeSha256':'a877291d800ed43692f3f9ae09d8e01cc6f7293ad39d43896059c188ffbb8b7c',
        'packageLicenseText':False,
        'sourceUrl':'https://registry.npmjs.org/rolldown/-/rolldown-1.2.16.tgz',
        'packageProvenance':{
            'archiveUrl':'https://registry.npmjs.org/rolldown/-/rolldown-1.2.16.tgz',
            'archiveIntegrity':'sha512-bWvlMpFKiTfDKfnK7FC2MPgPeWCf/Kpwsq49ApdW+FQaBZb6O6dZ4MAPbPUjp7hYQrw/RobqCzn64BRrQecGHw==',
            'archiveMember':'package/THIRD-PARTY-LICENSE'}}},
    ('npm', 'stackback'): {'0.0.2': {
        'license':'MIT',
        'manifestSha256':'4d984909b27d37d2f1a379b9cda7292a6e3a133c076df166d740a17514ac6e60',
        'sourcePath':'formatstack.js',
        'sourceSha256':'3c1191bd7094a36098418e7d1606e2a49e7ee25b5ddee54b0b2514ea1a43b8a7',
        'lineRange':[1,26],
        'noticeSha256':'b154c4cabeeb587f5cc63a41d0551ae69504460762d189a72ae141558ec5d184',
        'packageLicenseText':False,
        'sourceUrl':'https://registry.npmjs.org/stackback/-/stackback-0.0.2.tgz',
        'packageProvenance':{
            'archiveUrl':'https://registry.npmjs.org/stackback/-/stackback-0.0.2.tgz',
            'archiveIntegrity':'sha512-1XMJE5fQo1jGH6Y/7ebnwPOBEkIEnT4QF32d5R1+VXdXveM0IBMJt8zfaxX1P3QhVwrYe+576+jkANtSS2mBbw==',
            'archiveMember':'package/formatstack.js'}}},
}

# pnpm's isolated graph from HOP c2981601 plus the reviewed Tauri npm overlay. These two
# source packages have no peer suffix. This adapter selects additional notices
# only; it does not change the over-inclusive dependency inventory below.
REVIEWED_NPM_ROOTS = {
    ('rolldown', '1.2.16'): {
        'slot': 'rolldown@1.2.16', 'callerSlot': 'vite@8.3.6',
        'callerName': 'vite', 'callerVersion': '8.3.6',
        'callerManifestSha256': 'c190c4c3dadb457bedc5d756a2269cd648b134a293da9f4d873c01fc66f4186c'},
    ('stackback', '0.0.2'): {
        'slot': 'stackback@0.0.2', 'callerSlot': 'why-is-node-running@2.3.0',
        'callerName': 'why-is-node-running', 'callerVersion': '2.3.0',
        'callerManifestSha256': 'c762d49d3da5e8d8fdaa840ba1f18d68bb433e61c671b66b3127f8430d490fe2'},
}

# Exact inherited declarations and separately reviewed SDK bytes; not legal clearance.
WEBVIEW2_NOTICE_PINS = {'webview2-com': {'version': '0.39.1',
                  'checksum': '3f89fca7a704cee10dcb3654c1dbb8941d1783132f1917358af75bec37a7d7e6',
                  'normalizedManifestSha256': '4ba1c8935a5f535d18115242abbef3c73e9b2dd329a52b87f6f37b7adeae2421',
                  'originalManifestSha256': 'bee8a11a0f7c152ff835ea5ca64bcb5558e8a6079be56eccc4086dddb383288c',
                  'vcsSha256': '88413f4e9de3a9360fafb0d8c9a0fdf5a01a45d73f9ded314fa7b9ffa2108ace',
                  'sourceCommit': 'edc2caf886175ccaebe86078c9cfe1ae2a187328',
                  'sourcePath': 'crates/webview2-com',
                  'workspaceManifestSha256': '86df68bbb014e816ac356a462838914d813ce6aaa1d11b2aa284941701c6c7c2'},
 'webview2-com-sys': {'version': '0.39.1',
                      'checksum': 'b3a07132775117d6065853d9d1178157b8c90e228de47129d6bce2c7edebedfb',
                      'normalizedManifestSha256': '1a3e5684710cb1d2e7e7afdd32af011a4a8038c259f6592ade3f871ca31cad7d',
                      'originalManifestSha256': '00229c125c597e4f0ddb9e598738ee5b38a9086fd59eea6d2577cdda5f8e5875',
                      'vcsSha256': 'd4137410068017c3f66fe98578f2fd40f0e76d3fd628fa361c758f3b262351c7',
                      'sourceCommit': 'edc2caf886175ccaebe86078c9cfe1ae2a187328',
                      'sourcePath': 'crates/bindings',
                      'workspaceManifestSha256': '86df68bbb014e816ac356a462838914d813ce6aaa1d11b2aa284941701c6c7c2'},
 'webview2-com-macros': {'version': '0.8.1',
                         'checksum': '67a921c1b6914c367b2b823cd4cde6f96beec77d30a939c8199bb377cf9b9b54',
                         'normalizedManifestSha256': 'b006cef88171ef3675df724a900cb31eb1f74158f77a20680915f1dbe95d457e',
                         'originalManifestSha256': 'a615e325d5acebc64f6553724028cd5e3639397e534cef107f172540cb78d0fd',
                         'vcsSha256': 'c24c2646f52e6cb4c1f382afc69fa99c0dc78d6d8e4316ade7e51707b4f9af8e',
                         'sourceCommit': 'dffa41a8a46d3f5565eefbff2de57d38d399f158',
                         'sourcePath': 'crates/callback-macros',
                         'workspaceManifestSha256': '5d0444d55131aa8a4290fc3cd54bd8598e9528577ddf5c3368ee48a02e297f6d'}}
WEBVIEW2_MIT_NOTICE = {'path': 'notices/webview2-rs-LICENSE.txt',
 'sha256': '0dcf41516e608bbcb6cdc5229feb7b86fe4a643b85e7df251133c93408fdac73'}
WEBVIEW2_SDK_NOTICE = {'version': '1.0.3800.47',
 'archiveSha256': '56c9f26bdd07916a2d1949fb58a5c7e434dfa1173577dca879206050c4e718db',
 'catalogSha512': 'EASM6IwWa38ppWP825SH1xusVyN3fNCpi1xaDnHP80RVGgvCdBCwyw+Egqns3sdFSkWtDSp66Zj8NH6tFVmIiQ==',
 'sourceUrl': 'https://api.nuget.org/v3-flatcontainer/microsoft.web.webview2/1.0.3800.47/microsoft.web.webview2.1.0.3800.47.nupkg',
 'files': [{'path': 'notices/Microsoft.Web.WebView2-1.0.3800.47-LICENSE.txt',
            'sha256': '0af8f1b807512aae39c2ac1aa4d0cae65cabecb6fd554b8439a5162a0d6eca55',
            'archiveMember': 'LICENSE.txt'},
           {'path': 'notices/Microsoft.Web.WebView2-1.0.3800.47-NOTICE.txt',
            'sha256': '106423785c5b7eba0a8e61d1837f2132e9c828e20ad530f565d981c1df60dd90',
            'archiveMember': 'NOTICE.txt'}],
 'assets': {'arm64/WebView2Loader.dll': {'bytes': 146536,
                                         'sha256': 'a0de1844933a10c898f833771a85f0ab9a0e3c745d4715f63d2d9730f9416025'},
            'arm64/WebView2Loader.dll.lib': {'bytes': 2916,
                                             'sha256': 'd70271daa44507865ca0696cd1c1ede5e58e694eec74cb2d06e17dbbe205e9a2'},
            'arm64/WebView2LoaderStatic.lib': {'bytes': 10505262,
                                               'sha256': '4a1ca4b518337c508aa0d778b220c6e59558fce21f4fd0d79a6ea944dd9d5208'},
            'x64/WebView2Loader.dll': {'bytes': 160880,
                                       'sha256': '86545b66cdb0603bc26b626fb9ad610cb6e71f28d468f5ea66df23b03dda96d5'},
            'x64/WebView2Loader.dll.lib': {'bytes': 2916,
                                           'sha256': 'bfc8ccaaa056be95243a5b66a827e5849d2bb39676fca4dcc2053796d8e15c6d'},
            'x64/WebView2LoaderStatic.lib': {'bytes': 10500472,
                                             'sha256': '89c6b872783b8f6c3cedbff618adb42082d455c615453ae10cfc753f1e8f25d8'},
            'x86/WebView2Loader.dll': {'bytes': 121448,
                                       'sha256': '161dc6673084a31f64670ace8e61cb0e1b55af815b6c7c8217a0cdd8503454e2'},
            'x86/WebView2Loader.dll.lib': {'bytes': 2998,
                                           'sha256': 'a3ec0ee539d58fe72391f2e89cb814f96fab721c6d8d30953d152ea95dffad49'},
            'x86/WebView2LoaderStatic.lib': {'bytes': 10465074,
                                             'sha256': '0513f7e61304321f2d91e1851475be07e091042aa3640597e660608f72521e6c'}}}


class ReviewedNoticeAliasError(ValueError):
    """Reject an alias while retaining its observed, path-free boundary role."""
    def __init__(self, role: str, kind: str, context: dict | None = None, *, reparse_tag=None):
        self.role = role
        self.kind = kind
        self.reparse_tag = reparse_tag if type(reparse_tag) is int and 0 <= reparse_tag <= 0xffffffff else None
        message = 'Reviewed notice input must not use aliases'
        if context is not None:
            message += '; noticeContext=' + json.dumps(context, sort_keys=True, separators=(',', ':'))
        super().__init__(message)


def reviewed_path(location: Path, name: str) -> Path:
    relative=Path(name)
    if relative.is_absolute() or '..' in relative.parts or '\\' in name or ':' in name:
        raise ValueError('Reviewed notice path must remain inside its package')
    path=location/relative
    for component in (path,*path.parents):
        info=component.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0) & 0x400:
            role='root' if component==location else 'leaf' if component==path else 'intermediate'
            kind='symlink' if stat.S_ISLNK(info.st_mode) else 'reparse'
            raise ReviewedNoticeAliasError(role,kind,reparse_tag=getattr(info,'st_reparse_tag',None))
        if component==location:break
    if not stat.S_ISREG(path.stat().st_mode) or not path.resolve().is_relative_to(location.resolve()):
        raise ValueError('Reviewed notice input must be a regular package file')
    return path


def reviewed_file(location: Path, name: str, expected: str) -> bytes:
    path=reviewed_path(location,name)
    with path.open('rb') as stream:data=stream.read(2_000_001)
    if len(data)>2_000_000 or hashlib.sha256(data).hexdigest()!=expected:
        raise ValueError('Reviewed notice source/manifest differs from the exact reviewed bytes')
    data.decode('utf-8')
    return data


def _npm_selection_reject(reason):
    # Reasons are fixed codes, never filesystem input or link target text.
    raise ValueError('Reviewed npm notice selection rejected: ' + reason) from None


def _npm_identity(info):
    return tuple(getattr(info, field, 0) for field in (
        'st_dev', 'st_ino', 'st_mode', 'st_size', 'st_mtime_ns', 'st_ctime_ns',
        'st_file_attributes', 'st_reparse_tag'))


def _npm_alias(info):
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)


def _npm_bytes(path, expected=None):
    with path.open('rb') as stream:
        data = stream.read(2_000_001)
    if len(data) > 2_000_000 or (expected is not None and hashlib.sha256(data).hexdigest() != expected):
        _npm_selection_reject('fingerprint')
    data.decode('utf-8')
    return data


def _npm_regular_input(source, relative, snapshots, expected=None):
    path = reviewed_path(source, relative)
    for component in (path, *path.parents):
        info = component.lstat()
        if _npm_alias(info) or not (stat.S_ISREG(info.st_mode) if component == path else stat.S_ISDIR(info.st_mode)):
            _npm_selection_reject('nonregularInput')
        identity = _npm_identity(info)
        if component in snapshots and snapshots[component] != identity:
            _npm_selection_reject('changedInput')
        snapshots[component] = identity
        if component == source:
            break
    return _npm_bytes(path, expected)


def _npm_exact_link_target(location, target, canonical, *, windows):
    target = str(target)
    if not target or len(target) > 32767 or '\0' in target:
        return False
    if windows:
        # CPython readlink returns the junction substitute name. Accept only
        # the local-drive form pnpm creates, with its optional single slash.
        if target.startswith('\\\\?\\'):
            target = target[4:]
        expected = str(canonical)
        if not re.match(r'^[A-Za-z]:\\', target) or '/' in target:
            return False
        return ntpath.normcase(target) in (ntpath.normcase(expected), ntpath.normcase(expected + '\\'))
    return target == os.path.relpath(canonical, location.parent)


def reviewed_npm_notice_location(source: Path, manifest: Path, item: dict) -> Path:
    """Select two frozen physical sources without granting alias input permission."""
    key = (item.get('name'), item.get('version'))
    binding = REVIEWED_NPM_ROOTS.get(key)
    if binding is None:
        return manifest.parent
    pin = REVIEWED_SOURCE_NOTICES[('npm', key[0])][key[1]]
    if item.get('license') != pin['license']:
        _npm_selection_reject('packageIdentity')
    store = source / 'node_modules/.pnpm'
    canonical = store / binding['slot'] / 'node_modules' / key[0]
    caller = store / binding['callerSlot'] / 'node_modules' / key[0]
    if not source.is_absolute() or manifest not in (canonical / 'package.json', caller / 'package.json'):
        _npm_selection_reject('caller')
    snapshots = {}
    try:
        manager = json.loads(_npm_regular_input(source, 'package.json', snapshots))
        modules = json.loads(_npm_regular_input(source, 'node_modules/.modules.yaml', snapshots))
        if (type(manager) is not dict or manager.get('packageManager') != 'pnpm@10.34.9'
                or type(modules) is not dict or modules.get('packageManager') != 'pnpm@10.34.9'
                or type(modules.get('layoutVersion')) is not int or modules['layoutVersion'] != 5
                or modules.get('nodeLinker') != 'isolated' or modules.get('enableGlobalVirtualStore', False) is not False):
            _npm_selection_reject('layout')
        virtual = modules.get('virtualStoreDir')
        if (not isinstance(virtual, str) or (ntpath.normcase(virtual) != ntpath.normcase(str(store))
                if os.name == 'nt' else virtual != '.pnpm')):
            _npm_selection_reject('virtualStore')
        _npm_regular_input(source, 'pnpm-lock.yaml', snapshots, REVIEWED_NPM_LOCK_SHA256)
        _npm_regular_input(source, 'node_modules/.pnpm/lock.yaml', snapshots, REVIEWED_NPM_LOCK_SHA256)
        for count, entry in enumerate(store.iterdir(), 1):
            if count > 4096:
                _npm_selection_reject('slotBound')
            slot_name = entry.name.casefold()
            own_slot = binding['slot'].casefold()
            if ((slot_name == own_slot and entry.name != binding['slot'])
                    or slot_name.startswith((own_slot + '_', own_slot + '('))):
                _npm_selection_reject('ambiguousSlot')
        raw = _npm_regular_input(source, (canonical / 'package.json').relative_to(source).as_posix(),
                                 snapshots, pin['manifestSha256'])
        identity = json.loads(raw)
        if any(identity.get(field) != item.get(field) for field in ('name', 'version', 'license')):
            _npm_selection_reject('packageIdentity')
        target_before = None
        if manifest.parent == caller:
            host_path = store / binding['callerSlot'] / 'node_modules' / binding['callerName'] / 'package.json'
            host = json.loads(_npm_regular_input(source, host_path.relative_to(source).as_posix(), snapshots,
                                                 binding['callerManifestSha256']))
            if host.get('name') != binding['callerName'] or host.get('version') != binding['callerVersion']:
                _npm_selection_reject('callerIdentity')
            link = caller.lstat()
            if not _npm_alias(link) or (os.name == 'nt' and getattr(link, 'st_reparse_tag', None) != 0xA0000003):
                _npm_selection_reject('rootAlias')
            snapshots[caller] = _npm_identity(link)
            target = os.readlink(caller)  # One raw step only; never resolve this alias.
            if not _npm_exact_link_target(caller, target, canonical, windows=os.name == 'nt'):
                _npm_selection_reject('linkTarget')
            expected_identity = snapshots[canonical][:2]
            target_before = _npm_identity(caller.stat())
            if not all(type(n) is int and n > 0 for n in expected_identity) or target_before[:2] != expected_identity:
                _npm_selection_reject('targetIdentity')
            leaf = manifest.lstat()
            if _npm_alias(leaf) or not stat.S_ISREG(leaf.st_mode):
                _npm_selection_reject('manifestLeaf')
            snapshots[manifest] = _npm_identity(leaf)
            _npm_bytes(manifest, pin['manifestSha256'])
        for path, before in snapshots.items():
            if _npm_identity(path.lstat()) != before:
                _npm_selection_reject('changedInput')
        if target_before is not None and _npm_identity(caller.stat()) != target_before:
            _npm_selection_reject('changedTarget')
        return canonical
    except (OSError, UnicodeError, json.JSONDecodeError):
        _npm_selection_reject('inputUnavailable')


def require_sdk_asset(location: Path, name: str, pin: dict) -> None:
    path=reviewed_path(location,name)
    expected=pin['bytes']
    if type(expected) is not int or not 0<expected<=128*1024*1024 or path.stat().st_size!=expected:
        raise ValueError('Reviewed SDK asset size differs from its exact public source')
    count=0;digest=hashlib.sha256()
    with path.open('rb') as stream:
        while chunk:=stream.read(1024*1024):
            count+=len(chunk)
            if count>expected:raise ValueError('Reviewed SDK asset exceeded its exact size')
            digest.update(chunk)
    if count!=expected or digest.hexdigest()!=pin['sha256']:
        raise ValueError('Reviewed SDK asset bytes differ from its exact public source')


def collect_inherited_webview_notices(item: dict, location: Path, output: Path) -> list[dict]:
    pin=WEBVIEW2_NOTICE_PINS.get(item['name'])
    if pin is None:return []
    registry='registry+https://github.com/rust-lang/crates.io-index'
    if item['version']!=pin['version'] or item.get('license')!='MIT' or item.get('source')!=registry:
        raise ValueError('Reviewed WebView2 registry package version/license/source requires review')
    lock_path=reviewed_path(ROOT,'overlay/desktop-cargo.lock.toml')
    with lock_path.open('rb') as stream:lock_bytes=stream.read(2_000_001)
    if len(lock_bytes)>2_000_000:raise ValueError('Reviewed dependency lock exceeded its bound')
    matches=[entry for entry in tomllib.loads(lock_bytes.decode('utf-8')).get('package',[])
             if entry['name']==item['name'] and entry['version']==item['version']]
    if len(matches)!=1 or matches[0].get('checksum')!=pin['checksum'] or matches[0].get('source')!=registry:
        raise ValueError('Reviewed WebView2 crate checksum/source must match the frozen lock')
    normalized=tomllib.loads(reviewed_file(location,'Cargo.toml',pin['normalizedManifestSha256']).decode('utf-8'))['package']
    original=tomllib.loads(reviewed_file(location,'Cargo.toml.orig',pin['originalManifestSha256']).decode('utf-8'))['package']
    vcs=json.loads(reviewed_file(location,'.cargo_vcs_info.json',pin['vcsSha256']))
    if (normalized.get('name')!=item['name'] or normalized.get('version')!=item['version']
            or normalized.get('license')!='MIT' or original.get('license')!={'workspace':True}
            or vcs!={'git':{'sha1':pin['sourceCommit']},'path_in_vcs':pin['sourcePath']}):
        raise ValueError('Reviewed WebView2 manifest inheritance or VCS identity changed')
    mit=reviewed_file(ROOT,WEBVIEW2_MIT_NOTICE['path'],WEBVIEW2_MIT_NOTICE['sha256'])
    source_url=f'https://raw.githubusercontent.com/wravery/webview2-rs/{pin["sourceCommit"]}/LICENSE'
    provenance={'registryArchiveSha256':pin['checksum'],'sourceCommit':pin['sourceCommit'],
        'sourcePath':pin['sourcePath'],'normalizedManifestSha256':pin['normalizedManifestSha256'],
        'originalManifestSha256':pin['originalManifestSha256'],'vcsSha256':pin['vcsSha256'],
        'reviewedWorkspaceManifestSha256':pin['workspaceManifestSha256'],
        'scope':'Explicit Cargo workspace MIT inheritance; separate SDK notices are not substituted.'}
    pending=[('reviewed/webview2-rs-LICENSE.txt',mit,{'sourcePath':'LICENSE',
        'sha256':WEBVIEW2_MIT_NOTICE['sha256'],'sourceUrl':source_url,
        'packageProvenance':provenance,'packageLicenseText':True})]
    if item['name']=='webview2-com-sys':
        sdk=WEBVIEW2_SDK_NOTICE
        for name,asset in sdk['assets'].items():require_sdk_asset(location,name,asset)
        for entry in sdk['files']:
            raw=reviewed_file(ROOT,entry['path'],entry['sha256'])
            pending.append(('reviewed/'+Path(entry['path']).name,raw,{
                'sourceArchiveMember':entry['archiveMember'],'sha256':entry['sha256'],
                'sourceUrl':sdk['sourceUrl'],'packageLicenseText':False,
                'packageProvenance':{'id':'Microsoft.Web.WebView2','version':sdk['version'],
                    'archiveSha256':sdk['archiveSha256'],'verifiedAssetHashes':sdk['assets'],
                    'scope':'Whole SDK source notice; native-subset component inclusion and legal clearance not asserted.'}}))
    records=[]
    # Validate all package inputs, including SDK assets/notices, before new writes.
    for filename,data,record in pending:
        destination=output/filename;destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_bytes(data);records.append({**record,'file':filename})
    return records


def collect_reviewed_notices(ecosystem: str, item: dict, location: Path, output: Path) -> list[dict]:
    versions=REVIEWED_SOURCE_NOTICES.get((ecosystem,item['name']))
    if versions is None:return []
    pin=versions.get(item['version'])
    if pin is None or item.get('license')!=pin['license']:
        raise ValueError('Reviewed notice package version/license requires review')
    manifest='Cargo.toml' if ecosystem=='cargo' else 'package.json'
    def input_bytes(label, name, expected):
        try:
            return reviewed_file(location,name,expected)
        except ReviewedNoticeAliasError as error:
            # Name/version/license already matched the finite reviewed table.
            # Never include a filesystem path, environment, or package content.
            context={'ecosystem':ecosystem,'package':item['name'],'version':item['version'],
                     'input':label,'role':error.role,'kind':error.kind}
            if error.reparse_tag is not None:context['reparseTag']=error.reparse_tag
            raise ReviewedNoticeAliasError(error.role,error.kind,context,reparse_tag=error.reparse_tag) from None
    input_bytes('manifest',manifest,pin['manifestSha256'])
    data=input_bytes('notice',pin['sourcePath'],pin['sourceSha256'])
    line_range=pin.get('lineRange')
    if line_range is not None:
        lines=data.splitlines(keepends=True)
        if (len(line_range)!=2 or any(type(n) is not int for n in line_range)
                or line_range[0]!=1 or not 1<=line_range[1]<=len(lines)):
            raise ValueError('Reviewed notice comment range is invalid')
        selected=lines[:line_range[1]]
        if not all(line.startswith(b'//') for line in selected):
            raise ValueError('Reviewed notice range must contain only the leading license comment')
        data=b''.join(selected)
    if hashlib.sha256(data).hexdigest()!=pin['noticeSha256']:
        raise ValueError('Reviewed notice output differs from the complete reviewed notice')
    filename='reviewed/'+Path(pin['sourcePath']).name+'.txt'
    destination=output/filename;destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_bytes(data)
    record={'sourcePath':pin['sourcePath'],'sourceSha256':pin['sourceSha256'],
            'sha256':pin['noticeSha256'],'file':filename,'sourceUrl':pin['sourceUrl'],
            'packageProvenance':pin['packageProvenance'],'packageLicenseText':pin['packageLicenseText']}
    if line_range is not None:record['sourceLineRange']=list(line_range)
    return [record]


def collect_supplements(item: dict, location: Path, output: Path) -> list[dict]:
    pin=SUPPLEMENTAL_NOTICES.get(item['name'])
    if pin is None:return []
    if item['version'] != pin['version'] or item.get('license') != pin['license']:
        raise ValueError('Supplemental notice package version/license requires review')
    inputs=[]
    for name,expected in pin['files'].items():
        relative=Path(name)
        if relative.is_absolute() or '..' in relative.parts or '\\' in name:
            raise ValueError('Supplemental notice path must remain in the package')
        path=location/relative
        for component in (path,*path.parents):
            info=component.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0) & 0x400:
                raise ValueError('Supplemental notice source must not use aliases')
            if component==location:break
        if not path.is_file() or not path.resolve().is_relative_to(location.resolve()):
            raise ValueError('Supplemental notice source must remain a regular package file')
        with path.open('rb') as stream:data=stream.read(2_000_001)
        if len(data)>2_000_000 or hashlib.sha256(data).hexdigest()!=expected:
            raise ValueError('Supplemental notice text differs from the reviewed source')
        data.decode('utf-8')
        inputs.append((name,expected,data))
    records=[]
    for name,expected,data in inputs:
        filename='supplemental/'+name+'.txt'
        destination=output/filename;destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_bytes(data)
        records.append({'sourcePath':name,'sha256':expected,'file':filename,
            'sourceUrl':f'https://raw.githubusercontent.com/edwardkim/rhwp/{RHWP_SOURCE_COMMIT}/{pin["directory"]}/{name}'})
    return records


def collect(directory: Path, output: Path) -> list[str]:
    output.mkdir(parents=True,exist_ok=True)
    copied=[]
    for path in directory.iterdir():
        if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(directory.resolve()) and re.match(r'^(licen[cs]e|copying|notice|copyright)([._-]|$)',path.name,re.I):
            try: text=path.read_text(encoding='utf-8')
            except (UnicodeError,OSError): continue
            if len(text)>2_000_000: continue
            dest=output/(path.name+'.txt')
            dest.write_text(text,encoding='utf-8'); copied.append(dest.name)
    return copied


def collect_cargo(packages: list[dict], out: Path) -> list[dict]:
    inventory=[]
    runtime_names=set()
    for item in packages:
        ident=re.sub(r'[^A-Za-z0-9._-]','_','cargo-'+item['name']+'-'+item['version'])
        location=Path(item['manifest_path']).parent
        texts=collect(location,out/ident)
        license_file=item.get('license_file')
        if license_file:
            path=(location/license_file).resolve()
            if path.is_relative_to(location.resolve()) and path.is_file():
                try: (out/ident/'declared-license.txt').write_text(path.read_text(encoding='utf-8'),encoding='utf-8'); texts.append('declared-license.txt')
                except UnicodeError: pass
        record={'ecosystem':'cargo','name':item['name'],'version':item['version'],'declaredLicense':item.get('license'),'texts':texts}
        supplements=collect_supplements(item,location,out/ident)
        if supplements:
            record['supplementalNotices']=supplements
            texts.extend(entry['file'] for entry in supplements)
        reviewed=collect_reviewed_notices('cargo',item,location,out/ident)
        reviewed+=collect_inherited_webview_notices(item,location,out/ident)
        if reviewed:
            record['reviewedNotices']=[entry for entry in reviewed if entry['packageLicenseText']]
            additional=[entry for entry in reviewed if not entry['packageLicenseText']]
            if additional:record['additionalNotices']=additional
            texts.extend(entry['file'] for entry in reviewed if entry['packageLicenseText'])
        if item['name'] in RUST_SKIA_NAMES:
            if item['version'] != RUST_SKIA_VERSION or item.get('license') != 'MIT':
                raise ValueError('Shipped rust-skia version/license changed; review its exact notice before packaging')
            data=RUST_SKIA_NOTICE.read_bytes()
            if hashlib.sha256(data).hexdigest() != RUST_SKIA_SHA256:
                raise ValueError('Shipped rust-skia license text is missing or differs from the reviewed upstream version')
            name='rust-skia-LICENSE.txt'
            (out/ident/name).write_bytes(data)
            texts.append(name)
            record['runtimeNotice']={'sourceCommit':RUST_SKIA_COMMIT,
                'sourceUrl':f'https://raw.githubusercontent.com/rust-skia/rust-skia/{RUST_SKIA_COMMIT}/LICENSE',
                'sha256':RUST_SKIA_SHA256,'file':name,'shippedBy':'Tools/rhwp.exe native-skia'}
            runtime_names.add(item['name'])
        inventory.append(record)
    if runtime_names != RUST_SKIA_NAMES:
        raise ValueError('Metadata is missing a required shipped rust-skia dependency')
    return inventory


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--source',type=Path,required=True); parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args(); source=args.source.resolve(); out=args.out.resolve(); out.mkdir(parents=True,exist_ok=True)
    inventory=[]
    packages={}
    for directory, flags in [('apps/desktop/src-tauri',[]),('third_party/rhwp',['--features','native-skia'])]:
        result=subprocess.run(['cargo','metadata','--format-version','1','--locked',*flags],cwd=source/directory,check=True,capture_output=True,text=True,encoding='utf-8')
        for item in json.loads(result.stdout)['packages']:packages[item['id']]=item
    inventory=collect_cargo(list(packages.values()),out)
    # Over-inclusive build dependency inventory, not a claim that every item ships.
    store=source/'node_modules/.pnpm'
    for manifest in store.glob('*/node_modules/**/package.json'):
        if len(manifest.relative_to(store).parts)>6: continue
        try: item=json.loads(manifest.read_text(encoding='utf-8'))
        except (OSError,ValueError): continue
        name=item.get('name'); version=item.get('version')
        if not isinstance(name,str) or not isinstance(version,str): continue
        ident=re.sub(r'[^A-Za-z0-9._-]','_','npm-'+name+'-'+version)
        texts=collect(manifest.parent,out/ident)
        record={'ecosystem':'npm','name':name,'version':version,'declaredLicense':item.get('license'),'texts':texts}
        notice_location=reviewed_npm_notice_location(source,manifest,item)
        additional=collect_reviewed_notices('npm',item,notice_location,out/ident)
        if additional:record['additionalNotices']=additional
        inventory.append(record)
    (out/'inventory.json').write_text(json.dumps({'status':'requires-human-review','packages':inventory},ensure_ascii=False,indent=2),encoding='utf-8')
    missing=sum(not x['texts'] for x in inventory)
    print(f'Collected {len(inventory)} dependency records; {missing} need missing-license-text review. This does not clear release licensing.')
    print(f'Collected {sum(len(x.get("additionalNotices",[])) for x in inventory)} additional third-party notices; these do not fill a missing declared package license.')

if __name__=='__main__': main()
