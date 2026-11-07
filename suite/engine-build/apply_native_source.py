"""Install a finite authenticated source recipe into a fresh owned LO tree.

Receipts describe source installation only. Native compilation and qualification
remain separate gates. An I/O failure leaves the owned tree unqualified; this
helper does not promise transactional rollback.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import importlib.util
import json
from pathlib import Path
import stat

HERE = Path(__file__).resolve().parent
CORE = 'bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1'
POLICY_SHA256 = 'ba8d627adefb2dfe90e048546f6f55d54c8e739d0f4f21afbe8a556af54768bc'
RECIPES = {'arm64': ('windows-arm64-v1', ['arm64Full', 'winAccFocusOrder']),
           'x64': ('windows-x64-common-v2', ['moduleBootstrap', 'firebirdLoaderPath', 'zstdSourceLinks', 'winAccFocusOrder'])}
LOADER_PATH = 'external/firebird/ExternalProject_firebird.mk'
ZSTD_PATH = 'external/zstd/UnpackedTarball_zstd.mk'
ARM_PATHS = ('configure.ac', 'external/firebird/UnpackedTarball_firebird.mk',
             'external/firebird/ExternalProject_firebird.mk', 'external/zstd/UnpackedTarball_zstd.mk',
             'external/mdds/UnpackedTarball_mdds.mk', 'external/python3/ExternalProject_python3.mk',
             'extensions/Library_so_activex.mk', 'embedserv/Library_emser.mk',
             'extensions/Library_oleautobridge.mk', 'winaccessibility/Library_uacccom.mk',
             'winaccessibility/Library_winaccessibility.mk', 'winaccessibility/WinResTarget_uacccom.mk',
             'external/harfbuzz/ExternalProject_harfbuzz.mk')
COMMON_PATHS = ('bin/unpack-sources', 'winaccessibility/source/service/AccObjectWinManager.cxx',
                'winaccessibility/source/service/AccObject.cxx',
                'winaccessibility/source/UAccCOM/MAccessible.cxx')
ARM_OUTPUTS = {'external/firebird/firebird-windows-arm64.patch': 'firebird-windows-arm64.patch',
               'external/mdds/opengeul-arm64-equality.patch.1': 'opengeul-arm64-equality.patch.1',
               'external/python3/opengeul-native-arm64-tools.targets': 'opengeul-native-arm64-tools.targets'}


def _installer(filename):
    spec = importlib.util.spec_from_file_location(filename, HERE / (filename + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


ARM = _installer('enable_firebird_arm64')
WINACC = _installer('apply_winacc_focus_order')


def _decode_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result: raise ValueError('source-recipe-input')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique)


def _directory(path):
    # Check lexical ancestors before resolve: resolving first hides linked roots.
    for part in (path, *path.parents):
        item = part.lstat()
        if not stat.S_ISDIR(item.st_mode) or getattr(item, 'st_file_attributes', 0) & 0x400:
            raise ValueError('source-recipe-input')


def _regular(path):
    _directory(path.parent)
    item = path.lstat()
    if (not stat.S_ISREG(item.st_mode) or item.st_nlink != 1
            or getattr(item, 'st_file_attributes', 0) & 0x400 or not 0 < item.st_size <= 1024 * 1024):
        raise ValueError('source-recipe-input')
    return path.read_bytes()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _hash(value):
    if (not isinstance(value, str) or len(value) != 64
            or any(char not in '0123456789abcdef' for char in value)):
        raise ValueError('source-recipe-input')
    return value


def _pin(pin, path, *, after=None):
    if pin['path'] != path: raise ValueError('source-recipe-input')
    result = {'path': path, 'beforeSha256': _hash(pin['sha256']),
              'afterSha256': _hash(pin['afterSha256'] if after is None else after)}
    if 'size' in pin:
        if type(pin['size']) is not int or not 0 < pin['size'] <= 1024 * 1024:
            raise ValueError('source-recipe-input')
        result['beforeBytes'] = pin['size']
    if 'afterSize' in pin:
        if type(pin['afterSize']) is not int or not 0 < pin['afterSize'] <= 1024 * 1024:
            raise ValueError('source-recipe-input')
        result['afterBytes'] = pin['afterSize']
    return result


def _select_plan(lock, policy_raw, architecture):
    """Pure schema/selection seam; production always reads the fixed files below."""
    try:
        if architecture not in RECIPES or type(lock['schemaVersion']) is not int or lock['schemaVersion'] != 1:
            raise ValueError('source-recipe-input')
        if lock['nativeTargets'] != {'filename': 'native-targets.json', 'size': 1987, 'sha256': POLICY_SHA256}:
            raise ValueError('source-recipe-input')
        if len(policy_raw) != 1987 or _sha(policy_raw) != POLICY_SHA256:
            raise ValueError('source-recipe-input')
        policy = _decode_json(policy_raw)
        expected = {recipe_id: {'schemaVersion': 1, 'architecture': arch, 'coreCommit': CORE, 'hooks': hooks}
                    for arch, (recipe_id, hooks) in RECIPES.items()}
        if lock['nativeSourceRecipes'] != expected:
            raise ValueError('source-recipe-input')
        for row in lock['nativeSourceRecipes'].values():
            if type(row['schemaVersion']) is not int: raise ValueError('source-recipe-input')
        recipe_id, _ = RECIPES[architecture]
        if policy['targets'][architecture]['sourceRecipe'] != recipe_id:
            raise ValueError('source-recipe-input')
        winacc = lock['winAccFocusOrder']
        if winacc['coreCommit'] != CORE or winacc['path'] != COMMON_PATHS[1]:
            raise ValueError('source-recipe-input')
        if [row['path'] for row in winacc['sources']] != list(COMMON_PATHS[1:]):
            raise ValueError('source-recipe-input')
        common = [_pin(lock['moduleBootstrap'], COMMON_PATHS[0])]
        for row in winacc['sources']:
            after = winacc['afterSha256'] if row['path'] == winacc['path'] else row['sha256']
            common.append(_pin(row, row['path'], after=after))
        if (common[1]['beforeSha256'] != winacc['sha256']
                or common[1]['beforeBytes'] != winacc['beforeBytes']):
            raise ValueError('source-recipe-input')
        common[1]['afterBytes'] = winacc['afterBytes']
        arm_pins = [lock[key] for key in ['configureSource', 'sourceHook', 'icuBuildPath', 'zstdSourceLinks']]
        arm_pins += [lock[key]['recipe'] for key in ['mddsEquality', 'pythonNativeHost', 'atlNativePaths']]
        consumers = lock['atlConsumerNativePaths']['recipes']
        if len(consumers) != 5: raise ValueError('source-recipe-input')
        arm_pins += consumers + [lock['harfbuzzNativeMesonPaths']['recipe']]
        guarded = [_pin(pin, path) for pin, path in zip(arm_pins, ARM_PATHS)]
        if architecture == 'x64':
            loader = lock['windowsFirebirdLoaderPath']
            if (set(loader) != {'path', 'size', 'sha256', 'afterSize', 'afterSha256', 'condition'}
                    or loader['condition'] != 'WNT_X86_64'):
                raise ValueError('source-recipe-input')
            common.append(_pin(loader, LOADER_PATH))
            zstd = lock['windowsZstdSourceLinks']
            if (set(zstd) != {'path', 'size', 'sha256', 'afterSize', 'afterSha256', 'condition'}
                    or zstd['condition'] != 'WNT_X86_64'
                    or zstd['sha256'] != lock['zstdSourceLinks']['sha256']):
                raise ValueError('source-recipe-input')
            common.append(_pin(zstd, ZSTD_PATH))
            guarded = [row for row in guarded if row['path'] not in (LOADER_PATH, ZSTD_PATH)]
        payloads = [('winacc-focus-order.patch', winacc['patch'])]
        dependencies = []
        if architecture == 'arm64':
            upstream = lock['mddsEquality']['upstreamPatch']
            if upstream['filename'] != 'gcc-12-silence-use-after-free.patch.1' or upstream['strip'] != 1:
                raise ValueError('source-recipe-input')
            dependencies.append({'path': 'external/mdds/' + upstream['filename'],
                                 'beforeSha256': _hash(upstream['sha256']),
                                 'afterSha256': _hash(upstream['sha256'])})
            payloads += [('firebird-windows-arm64.patch', lock['portPatch']),
                         ('libreoffice-enable-arm64-firebird.patch', lock['configurePatch']),
                         ('opengeul-arm64-equality.patch.1', lock['mddsEquality']['patch']),
                         ('opengeul-native-arm64-tools.targets', lock['pythonNativeHost']['targets'])]
        selected_payloads = []
        for name, pin in payloads:
            if pin['filename'] != name: raise ValueError('source-recipe-input')
            selected_payloads.append({'filename': name, 'sha256': _hash(pin['sha256'])})
            if 'size' in pin: selected_payloads[-1]['size'] = pin['size']
        if winacc['patch']['strip'] != 1: raise ValueError('source-recipe-input')
        return {'recipeId': recipe_id, 'recipe': lock['nativeSourceRecipes'][recipe_id],
                'sources': common + guarded, 'armGuardedSources': guarded,
                'sourceDependencies': dependencies, 'payloads': selected_payloads}
    except (KeyError, TypeError, IndexError, AttributeError):
        raise ValueError('source-recipe-input') from None


def _loader_bytes(original, pin):
    old = (b'$(call gb_Helper_extend_ld_path,$(gb_UnpackedTarball_workdir)/icu/source/lib)'
           b'$(call gb_Helper_extend_ld_path,$(firebird_BUILDDIR)/lib)')
    new = (b'$(if $(filter WNT_X86_64,$(OS)_$(CPUNAME)),'
           b'$(call gb_Helper_extend_ld_path,$(gb_UnpackedTarball_workdir)/icu/source/lib:$(firebird_BUILDDIR)/bin),'
           + old + b')')
    if (pin['path'] != LOADER_PATH or pin['condition'] != 'WNT_X86_64'
            or len(original) != pin['size'] or _sha(original) != pin['sha256'] or original.count(old) != 1):
        raise ValueError('source-recipe-input')
    changed = original.replace(old, new, 1)
    if len(changed) != pin['afterSize'] or _sha(changed) != pin['afterSha256']:
        raise ValueError('source-recipe-input')
    return changed


def _install_firebird_loader_path(source, evidence, pin):
    target = source / LOADER_PATH; original = _regular(target)
    changed = _loader_bytes(original, pin)
    retained = {'original': evidence / 'original-x64-ExternalProject_firebird.mk',
                'effective': evidence / 'effective-x64-ExternalProject_firebird.mk'}
    if any(path.exists() or path.is_symlink() for path in retained.values()):
        raise ValueError('source-recipe-input')
    for name, raw in [('original', original), ('effective', changed)]:
        with retained[name].open('xb') as stream: stream.write(raw)
    target.write_bytes(changed)
    if _regular(target) != changed: raise ValueError('source-recipe-output')
    return {'schemaVersion': 1, 'kind': 'windows-firebird-loader-path-source-hook',
            'path': LOADER_PATH, 'condition': 'WNT_X86_64',
            'beforeBytes': len(original), 'afterBytes': len(changed),
            'beforeSha256': _sha(original), 'afterSha256': _sha(changed),
            'evidence': {name: str(path) for name, path in retained.items()},
            'nativeBuildVerified': False, 'fullEngineQualified': False,
            'acceptanceEligible': False, 'guiVerified': False}


def _zstd_bytes(original, pin):
    if (set(pin) != {'path', 'size', 'sha256', 'afterSize', 'afterSha256', 'condition'}
            or pin['path'] != ZSTD_PATH or pin['condition'] != 'WNT_X86_64'
            or type(pin['size']) is not int or type(pin['afterSize']) is not int
            or len(original) != pin['size'] or _sha(original) != pin['sha256']):
        raise ValueError('source-recipe-input')
    changed = original + (
        b'\n# Preserve portable source-only CLI test links in this exact Windows x64 unpack target.\n'
        b'# Keep all other source and native module targets under the original link policy.\n'
        b'ifeq ($(OS)_$(CPUNAME),WNT_X86_64)\n'
        b'$(call gb_UnpackedTarget_get_target,$(ZSTD_TARBALL)): export CYGWIN := winsymlinks:sys\n'
        b'endif\n')
    if len(changed) != pin['afterSize'] or _sha(changed) != pin['afterSha256']:
        raise ValueError('source-recipe-input')
    return changed


def _install_zstd_source_links(source, evidence, pin):
    target = source / ZSTD_PATH; original = _regular(target)
    changed = _zstd_bytes(original, pin)
    retained = {'original': evidence / 'original-x64-UnpackedTarball_zstd.mk',
                'effective': evidence / 'effective-x64-UnpackedTarball_zstd.mk'}
    if any(path.exists() or path.is_symlink() for path in retained.values()):
        raise ValueError('source-recipe-input')
    for name, raw in [('original', original), ('effective', changed)]:
        with retained[name].open('xb') as stream: stream.write(raw)
        if _regular(retained[name]) != raw: raise ValueError('source-recipe-output')
    target.write_bytes(changed)
    if _regular(target) != changed: raise ValueError('source-recipe-output')
    return {'schemaVersion': 1, 'kind': 'windows-zstd-source-links-source-hook',
            'path': ZSTD_PATH, 'condition': 'WNT_X86_64',
            'beforeBytes': len(original), 'afterBytes': len(changed),
            'beforeSha256': _sha(original), 'afterSha256': _sha(changed),
            'evidence': {name: str(path) for name, path in retained.items()},
            'nativeBuildVerified': False, 'fullEngineQualified': False,
            'acceptanceEligible': False, 'guiVerified': False}


def _validate_common(inputs, lock, payloads, architecture):
    bootstrap = lock['moduleBootstrap']
    original = inputs[COMMON_PATHS[0]]
    if original.count(b'-type d -path ') != 1 or _sha(original.replace(b'-type d -path ', b'-type d ! -path ')) != bootstrap['afterSha256']:
        raise ValueError('source-recipe-input')
    pin = lock['winAccFocusOrder']; original = inputs[pin['path']]
    moved = b'        pAccObjNew->setFocus();\n'; previous = b'            pAccObjOld->unsetFocus();\n'
    if original.count(moved) != 1 or original.count(previous) != 1:
        raise ValueError('source-recipe-input')
    changed = original.replace(moved, b'', 1).replace(previous, previous + moved, 1)
    if len(changed) != pin['afterBytes'] or _sha(changed) != pin['afterSha256']:
        raise ValueError('source-recipe-input')
    expected = ''.join(difflib.unified_diff(original.decode().splitlines(True), changed.decode().splitlines(True),
                       fromfile='a/' + pin['path'], tofile='b/' + pin['path'])).encode()
    if expected != payloads['winacc-focus-order.patch']: raise ValueError('source-recipe-input')
    if architecture == 'x64':
        _loader_bytes(inputs[LOADER_PATH], lock['windowsFirebirdLoaderPath'])
        _zstd_bytes(inputs[ZSTD_PATH], lock['windowsZstdSourceLinks'])


def apply_native_source(source_root: Path, evidence_directory: Path, *, architecture: str) -> dict:
    manifest_raw = _regular(HERE / 'source-build.json')
    lock = _decode_json(manifest_raw)
    policy_raw = _regular(HERE / 'native-targets.json')
    plan = _select_plan(lock, policy_raw, architecture)
    source = Path(source_root).absolute(); evidence = Path(evidence_directory).absolute()
    _directory(source); _directory(evidence)
    source = source.resolve(strict=True); evidence = evidence.resolve(strict=True)
    if source == evidence or source in evidence.parents or evidence in source.parents or any(evidence.iterdir()):
        raise ValueError('source-recipe-input')
    inputs = {}
    for row in plan['sources'] + plan['sourceDependencies']:
        raw = _regular(source / row['path'])
        if _sha(raw) != row['beforeSha256'] or 'beforeBytes' in row and len(raw) != row['beforeBytes']:
            raise ValueError('source-recipe-input')
        inputs[row['path']] = raw
    payloads = {}
    for row in plan['payloads']:
        raw = _regular(HERE / row['filename'])
        if _sha(raw) != row['sha256'] or 'size' in row and len(raw) != row['size']:
            raise ValueError('source-recipe-input')
        payloads[row['filename']] = raw
    _validate_common(inputs, lock, payloads, architecture)
    if architecture == 'arm64':
        for name in ARM_OUTPUTS:
            output = source / name; _directory(output.parent)
            if output.exists() or output.is_symlink(): raise ValueError('source-recipe-input')
    # The existing helpers reread these fixed manifests. Detect changed inputs at
    # the call boundary, then preserve their original receipt shapes unchanged.
    if _regular(HERE / 'source-build.json') != manifest_raw or _regular(HERE / 'native-targets.json') != policy_raw:
        raise ValueError('source-recipe-input')
    if architecture == 'arm64':
        hooks = ARM.install(source, evidence)
    else:
        hooks = {'kind': 'native-windows-common-source-hooks', 'architecture': 'x64',
                 'moduleBootstrap': ARM.install_module_bootstrap(source, evidence),
                 'firebirdLoaderPath': _install_firebird_loader_path(source, evidence, lock['windowsFirebirdLoaderPath']),
                 'zstdSourceLinks': _install_zstd_source_links(source, evidence, lock['windowsZstdSourceLinks']),
                 'nativeBuildVerified': False, 'basePersistenceVerified': False}
    winacc = WINACC.install(source, evidence, CORE)
    if architecture == 'arm64':
        for path, name in ARM_OUTPUTS.items():
            if _regular(source / path) != payloads[name]: raise ValueError('source-recipe-output')
    guarded = []; guarded_paths = {row['path'] for row in plan['armGuardedSources']}
    for row in plan['sources'] + plan['sourceDependencies']:
        unchanged = architecture == 'x64' and row['path'] in guarded_paths
        expected = row['beforeSha256'] if unchanged else row['afterSha256']
        raw = _regular(source / row['path'])
        if _sha(raw) != expected or not unchanged and 'afterBytes' in row and len(raw) != row['afterBytes']:
            raise ValueError('source-recipe-output')
        if row['path'] in guarded_paths:
            guarded.append({'path': row['path'], 'beforeSha256': row['beforeSha256'],
                            'sha256': expected, 'unchanged': unchanged})
    proof = {'schemaVersion': 1, 'kind': 'native-engine-source-recipe-install',
             'architecture': architecture, 'recipeId': plan['recipeId'],
             'policySha256': _sha(policy_raw), 'manifestSha256': _sha(manifest_raw),
             'recipeSha256': _sha(json.dumps(plan, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()),
             'hookOrder': plan['recipe']['hooks'], 'armGuardedSources': guarded,
             'nativeBuildVerified': False, 'fullEngineQualified': False,
             'acceptanceEligible': False, 'guiVerified': False}
    return {'sourceHooks': hooks, 'winAccFocusOrderSourcePatch': winacc, 'sourceRecipeProof': proof}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--libreoffice-source', type=Path, required=True)
    parser.add_argument('--evidence-directory', type=Path, required=True)
    parser.add_argument('--architecture', choices=('arm64', 'x64'), default='arm64')
    args = parser.parse_args()
    try:
        result = apply_native_source(args.libreoffice_source, args.evidence_directory, architecture=args.architecture)
    except OSError:
        print(json.dumps({'schemaVersion': 1, 'passed': False, 'errorCode': 'source-recipe-io'})); return 1
    except (ValueError, KeyError, TypeError):
        print(json.dumps({'schemaVersion': 1, 'passed': False, 'errorCode': 'source-recipe-input'})); return 1
    print(json.dumps(result, indent=2)); return 0


if __name__ == '__main__': raise SystemExit(main())
