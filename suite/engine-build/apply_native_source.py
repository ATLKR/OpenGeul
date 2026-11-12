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
CORE = '9dea406ab7695df6325b11b0e19fdca8db4b7276'
POLICY_SHA256 = 'ba8d627adefb2dfe90e048546f6f55d54c8e739d0f4f21afbe8a556af54768bc'
RECIPES = {'arm64': ('windows-arm64-v1', ['arm64Full', 'winAccFocusOrder', 'flexFatalCompatibility', 'dotnetProjectGraph']),
           'x64': ('windows-x64-common-v2', ['moduleBootstrap', 'firebirdLoaderPath', 'zstdSourceLinks', 'gpgBuildCompilerPath', 'atlNativePaths', 'harfbuzzNativeMesonPaths', 'cliPublisherPolicyPlatform', 'x86CompanionStaticRuntime', 'winAccFocusOrder', 'flexFatalCompatibility', 'dotnetProjectGraph'])}
DOTNET_GRAPH_SOURCES = (
    ('solenv/gbuild/DotnetLibrary.mk', 5315, 'f4d2e54af51037267b4027461d7caa6c7a22d3660b99bedeb68f2160d46f476b',
     5728, 'cc1e4a62d0d97681b1742ada794af15945e465af86d4d2f54b38b245c8889db3'),
    ('solenv/gbuild/DotnetTest.mk', 5154, '5391ab97bd1a43c71584afd2819499c1fca75ab95a2e35835dc7e10a02813272',
     5555, '09987ad29eb2afac9f2ff7a973bd2b7c32ccd54f286a4281610b5bc89fe939f7'))
FLEX_PATH = 'connectivity/source/parse/sqlflex.l'
FLEX_BEFORE = (37027, '87e66cc9306322ca97c2e4ccbb41b0960fb8857aee4e536bf051c043ebf6c11a')
FLEX_AFTER = (37161, 'f0890c54e65b52ac31a37a99b20a17fb9e9282985f25fa99ba4718490975200c')
LOADER_PATH = 'external/firebird/ExternalProject_firebird.mk'
ZSTD_PATH = 'external/zstd/UnpackedTarball_zstd.mk'
GPG_PATH = 'solenv/gbuild/platform/com_MSC_defs.mk'
GPG_CONDITION = 'WNT_X86_64 && BUILD_PLATFORM=%cygwin'
HARFBUZZ_PATH = 'external/harfbuzz/ExternalProject_harfbuzz.mk'
HARFBUZZ_CONDITION = 'WNT_X86_64_MSC_WNT && MAKE_HOST=%-cygwin'
CLI_POLICY_PATH = 'cli_ure/CliNativeLibrary_cli_cppuhelper.mk'
ARM_PATHS = ('configure.ac', 'external/firebird/UnpackedTarball_firebird.mk',
             'external/firebird/ExternalProject_firebird.mk', 'external/zstd/UnpackedTarball_zstd.mk',
             'external/mdds/UnpackedTarball_mdds.mk', 'external/python3/ExternalProject_python3.mk',
             'extensions/Library_so_activex.mk', 'embedserv/Library_emser.mk',
             'extensions/Library_oleautobridge.mk', 'winaccessibility/Library_uacccom.mk',
             'winaccessibility/Library_winaccessibility.mk', 'winaccessibility/WinResTarget_uacccom.mk',
             'external/harfbuzz/ExternalProject_harfbuzz.mk')
ATL_PATHS = ARM_PATHS[6:12]
ATL_CONDITION = 'WNT_X86_64_MSC && MAKE_HOST=%-cygwin'
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
X86_CRT = _installer('apply_x86_companion_crt')


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
        common.append(_flex_pin(lock['flexFatalCompatibility']))
        common.extend(_dotnet_graph_pins(lock['windowsDotnetProjectGraph']))
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
            gpg = lock['windowsGpgBuildCompilerPath']
            if (set(gpg) != {'path', 'size', 'sha256', 'afterSize', 'afterSha256', 'condition'}
                    or gpg['condition'] != GPG_CONDITION):
                raise ValueError('source-recipe-input')
            common.append(_pin(gpg, GPG_PATH))
            common.extend(_pin(pin, path) for pin, path in zip(_atl_pins(lock), ATL_PATHS))
            harfbuzz = lock['windowsHarfbuzzNativeMesonPaths']
            if (set(harfbuzz) != {'path', 'size', 'sha256', 'afterSize', 'afterSha256', 'condition'}
                    or harfbuzz['condition'] != HARFBUZZ_CONDITION
                    or any(harfbuzz[key] != lock['harfbuzzNativeMesonPaths']['recipe'][key]
                           for key in ('path', 'size', 'sha256'))):
                raise ValueError('source-recipe-input')
            common.append(_pin(harfbuzz, HARFBUZZ_PATH))
            cli_policy = lock['windowsCliPublisherPolicyPlatform']
            if (set(cli_policy) != {'path', 'size', 'sha256', 'afterSize', 'afterSha256', 'condition'}
                    or cli_policy['condition'] != 'WNT_X86_64'):
                raise ValueError('source-recipe-input')
            common.append(_pin(cli_policy, CLI_POLICY_PATH))
            X86_CRT.descriptor(lock['windowsX86CompanionStaticRuntime'])
            common.extend(_pin(pin, pin['path']) for pin in lock['windowsX86CompanionStaticRuntime']['sources'])
            guarded = [row for row in guarded if row['path'] not in (LOADER_PATH, ZSTD_PATH, *ATL_PATHS, HARFBUZZ_PATH)]
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


def _dotnet_graph_pin(pin):
    fields = ('path', 'size', 'sha256', 'afterSize', 'afterSha256')
    if (type(pin) is not dict or set(pin) != set(fields)
            or any(type(pin[key]) is not str for key in ('path', 'sha256', 'afterSha256'))
            or any(type(pin[key]) is not int for key in ('size', 'afterSize'))
            or tuple(pin[key] for key in fields) not in DOTNET_GRAPH_SOURCES):
        raise ValueError('source-recipe-input')
    return _pin(pin, pin['path'])


def _dotnet_graph_pins(descriptor):
    if (type(descriptor) is not dict or set(descriptor) != {'schemaVersion', 'coreCommit', 'sources'}
            or type(descriptor['schemaVersion']) is not int or descriptor['schemaVersion'] != 1
            or type(descriptor['coreCommit']) is not str or descriptor['coreCommit'] != CORE
            or type(descriptor['sources']) is not list or len(descriptor['sources']) != 2):
        raise ValueError('source-recipe-input')
    pins = [_dotnet_graph_pin(pin) for pin in descriptor['sources']]
    if [row['path'] for row in pins] != [row[0] for row in DOTNET_GRAPH_SOURCES]:
        raise ValueError('source-recipe-input')
    return pins


def _dotnet_graph_bytes(original, pin):
    _dotnet_graph_pin(pin)
    if type(original) is not bytes or (len(original), _sha(original)) != (pin['size'], pin['sha256']):
        raise ValueError('source-recipe-input')
    kind = 'Library' if pin['path'] == DOTNET_GRAPH_SOURCES[0][0] else 'Test'
    prefix = 'gb_Dotnet' + kind
    command = b'build' if kind == 'Library' else b'test'
    old_cli = b'"$$(DOTNET)" ' + command + b' $$< $$(DOTNET_BUILD_FLAGS) -o $$(dir $$@),'
    new_cli = b'"$$(DOTNET)" ' + command + b' $$< $$(DOTNET_BUILD_FLAGS),'
    owner = ('$$(' + prefix + '_$(1)_project) : DOTNET_PROPERTY_ELEMENTS += ').encode()
    assembly = owner + b'<AssemblyName>$(1)</AssemblyName>\n'
    # gbuild workdirs already use the same native path representation as the
    # existing ProjectReference and original CLI -o. Do not call the deprecated
    # gb_Helper_native_path or propagate a global SDK output override.
    properties = (owner + ('<OutputPath>$(' + prefix + '_workdir)/$(1)/</OutputPath>\n').encode()
                  + owner + b'<AppendTargetFrameworkToOutputPath>false</AppendTargetFrameworkToOutputPath>\n'
                  + owner + b'<BuildProjectReferences>false</BuildProjectReferences>\n')
    reference = b'<ProjectReference Include="$(gb_DotnetLibrary_$(2)_project)"/>'
    scoped = b'<ProjectReference Include="$(gb_DotnetLibrary_$(2)_project)" GlobalPropertiesToRemove="OutputPath;OutDir"/>'
    for before in (old_cli, assembly, reference):
        if original.count(before) != 1: raise ValueError('source-recipe-input')
    changed = original.replace(old_cli, new_cli, 1).replace(assembly, assembly + properties, 1).replace(reference, scoped, 1)
    if (len(changed), _sha(changed)) != (pin['afterSize'], pin['afterSha256']):
        raise ValueError('source-recipe-output')
    return changed


def _install_dotnet_project_graph(source, evidence, descriptor, architecture):
    if type(architecture) is not str or architecture not in RECIPES:
        raise ValueError('source-recipe-input')
    _directory(source); _directory(evidence)
    if source == evidence or source in evidence.parents or evidence in source.parents:
        raise ValueError('source-recipe-input')
    _dotnet_graph_pins(descriptor)
    prepared = []
    for pin in descriptor['sources']:
        target = source / pin['path']; original = _regular(target)
        changed = _dotnet_graph_bytes(original, pin)
        retained = {phase: evidence / (phase + '-' + target.name) for phase in ('original', 'effective')}
        if any(path.exists() or path.is_symlink() for path in retained.values()):
            raise ValueError('source-recipe-input')
        prepared.append((pin, target, original, changed, retained))
    rows = []
    for pin, target, original, changed, retained in prepared:
        if _regular(target) != original: raise ValueError('source-recipe-input')
        for phase, raw in (('original', original), ('effective', changed)):
            with retained[phase].open('xb') as output: output.write(raw)
            if _regular(retained[phase]) != raw: raise ValueError('source-recipe-output')
        target.write_bytes(changed)
        if _regular(target) != changed: raise ValueError('source-recipe-output')
        rows.append(dict(path=pin['path'], beforeBytes=pin['size'], afterBytes=pin['afterSize'],
                         beforeSha256=pin['sha256'], afterSha256=pin['afterSha256'],
                         evidence={name: str(path) for name, path in retained.items()}))
    return dict(schemaVersion=1, kind='windows-dotnet-project-graph-source-hook', coreCommit=CORE,
                architecture=architecture, sources=rows, nativeBuildVerified=False,
                fullEngineQualified=False, acceptanceEligible=False, guiVerified=False)


def _flex_pin(pin):
    if (type(pin) is not dict or set(pin) != {'path', 'size', 'sha256', 'afterSize', 'afterSha256', 'condition'}
            or any(type(pin[key]) is not str for key in ('path', 'sha256', 'afterSha256', 'condition'))
            or type(pin['size']) is not int or type(pin['afterSize']) is not int
            or pin['path'] != FLEX_PATH or pin['condition'] != 'WNT'
            or (pin['size'], pin['sha256']) != FLEX_BEFORE
            or (pin['afterSize'], pin['afterSha256']) != FLEX_AFTER):
        raise ValueError('source-recipe-input')
    return _pin(pin, FLEX_PATH)


def _flex_fatal_bytes(original, pin):
    _flex_pin(pin)
    if type(original) is not bytes or (len(original), _sha(original)) != FLEX_BEFORE:
        raise ValueError('source-recipe-input')
    before = b'    /*hack to silence -Wunused-function*/\n    if ((0)) yy_fatal_error(msg);'
    after = (b'    /*hack to silence -Wunused-function*/\n'
             b'#if YY_FLEX_MAJOR_VERSION == 2 && YY_FLEX_MINOR_VERSION == 6 && YY_FLEX_SUBMINOR_VERSION == 5\n'
             b'    if ((0)) yypanic(msg);\n'
             b'#else\n'
             b'    if ((0)) yy_fatal_error(msg);\n'
             b'#endif')
    if original.count(before) != 1: raise ValueError('source-recipe-input')
    changed = original.replace(before, after, 1)
    if (len(changed), _sha(changed)) != FLEX_AFTER: raise ValueError('source-recipe-output')
    return changed


def _install_flex_fatal_compat(source, evidence, pin, architecture):
    if architecture not in RECIPES: raise ValueError('source-recipe-input')
    _directory(source); _directory(evidence)
    target = source / FLEX_PATH; original = _regular(target)
    changed = _flex_fatal_bytes(original, pin)
    retained = {phase: evidence / (phase + '-' + architecture + '-sqlflex.l')
                for phase in ('original', 'effective')}
    if any(path.exists() or path.is_symlink() for path in retained.values()):
        raise ValueError('source-recipe-input')
    for phase, raw in [('original', original), ('effective', changed)]:
        with retained[phase].open('xb') as stream: stream.write(raw)
        if _regular(retained[phase]) != raw: raise ValueError('source-recipe-output')
    target.write_bytes(changed)
    if _regular(target) != changed: raise ValueError('source-recipe-output')
    return {'schemaVersion': 1, 'kind': 'windows-flex-fatal-compatibility-source-hook',
            'coreCommit': CORE, 'architecture': architecture, 'path': FLEX_PATH,
            'beforeBytes': len(original), 'afterBytes': len(changed),
            'beforeSha256': _sha(original), 'afterSha256': _sha(changed),
            'evidence': {phase: str(path) for phase, path in retained.items()},
            'nativeBuildVerified': False, 'fullEngineQualified': False,
            'acceptanceEligible': False, 'guiVerified': False}


def _cli_policy_bytes(original, pin):
    old = b'$(eval $(call gb_CliNativeLibrary_CliNativeLibrary,cli_cppuhelper))\n'
    new = old + (b'\nifeq ($(OS)_$(CPUNAME),WNT_X86_64)\n'
                 b'$(eval $(call gb_CliNativeLibrary_set_platform,cli_cppuhelper,x64))\nendif\n')
    if (set(pin) != {'path', 'size', 'sha256', 'afterSize', 'afterSha256', 'condition'}
            or pin['path'] != CLI_POLICY_PATH or pin['condition'] != 'WNT_X86_64'
            or type(pin['size']) is not int or type(pin['afterSize']) is not int
            or len(original) != pin['size'] or _sha(original) != pin['sha256'] or original.count(old) != 1):
        raise ValueError('source-recipe-input')
    changed = original.replace(old, new, 1)
    if len(changed) != pin['afterSize'] or _sha(changed) != pin['afterSha256']:
        raise ValueError('source-recipe-input')
    return changed


def _install_cli_policy_platform(source, evidence, pin):
    target = source / CLI_POLICY_PATH; original = _regular(target)
    changed = _cli_policy_bytes(original, pin)
    retained = {name: evidence / (name + '-x64-CliNativeLibrary_cli_cppuhelper.mk')
                for name in ('original', 'effective')}
    if any(path.exists() or path.is_symlink() for path in retained.values()):
        raise ValueError('source-recipe-input')
    for name, raw in [('original', original), ('effective', changed)]:
        with retained[name].open('xb') as stream: stream.write(raw)
    target.write_bytes(changed)
    if _regular(target) != changed: raise ValueError('source-recipe-output')
    return {'schemaVersion': 1, 'kind': 'windows-x64-cli-publisher-policy-platform-source-hook',
            'path': CLI_POLICY_PATH, 'condition': 'WNT_X86_64',
            'beforeBytes': len(original), 'afterBytes': len(changed),
            'beforeSha256': _sha(original), 'afterSha256': _sha(changed),
            'evidence': {name: str(path) for name, path in retained.items()},
            'nativeBuildVerified': False, 'fullEngineQualified': False,
            'acceptanceEligible': False, 'guiVerified': False}


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


def _gpg_build_compiler_bytes(original, pin):
    old = b'REAL_BUILD_CC="$(filter-out -%,$(CC_FOR_BUILD))"'
    new = (b'REAL_BUILD_CC="$(if $(and $(filter WNT_X86_64,$(OS)_$(CPUNAME)),'
           b'$(filter %cygwin,$(BUILD_PLATFORM))),'
           b'$(shell cygpath -w $(filter-out -%,$(CC_FOR_BUILD))),'
           b'$(filter-out -%,$(CC_FOR_BUILD)))"')
    if (set(pin) != {'path', 'size', 'sha256', 'afterSize', 'afterSha256', 'condition'}
            or pin['path'] != GPG_PATH or pin['condition'] != GPG_CONDITION
            or type(pin['size']) is not int or type(pin['afterSize']) is not int
            or len(original) != pin['size'] or _sha(original) != pin['sha256'] or original.count(old) != 1):
        raise ValueError('source-recipe-input')
    changed = original.replace(old, new, 1)
    if len(changed) != pin['afterSize'] or _sha(changed) != pin['afterSha256']:
        raise ValueError('source-recipe-input')
    return changed


def _install_gpg_build_compiler_path(source, evidence, pin):
    target = source / GPG_PATH; original = _regular(target)
    changed = _gpg_build_compiler_bytes(original, pin)
    retained = {'original': evidence / 'original-x64-com_MSC_defs.mk',
                'effective': evidence / 'effective-x64-com_MSC_defs.mk'}
    if any(path.exists() or path.is_symlink() for path in retained.values()):
        raise ValueError('source-recipe-input')
    for name, raw in [('original', original), ('effective', changed)]:
        with retained[name].open('xb') as stream: stream.write(raw)
        if _regular(retained[name]) != raw: raise ValueError('source-recipe-output')
    target.write_bytes(changed)
    if _regular(target) != changed: raise ValueError('source-recipe-output')
    return {'schemaVersion': 1, 'kind': 'windows-gpg-build-compiler-path-source-hook',
            'path': GPG_PATH, 'condition': GPG_CONDITION,
            'beforeBytes': len(original), 'afterBytes': len(changed),
            'beforeSha256': _sha(original), 'afterSha256': _sha(changed),
            'evidence': {name: str(path) for name, path in retained.items()},
            'nativeBuildVerified': False, 'fullEngineQualified': False,
            'acceptanceEligible': False, 'guiVerified': False}


def _harfbuzz_bytes(original, pin):
    """Confine the existing native Meson boundary to the pinned x64 recipe."""
    if (set(pin) != {'path', 'size', 'sha256', 'afterSize', 'afterSha256', 'condition'}
            or pin['path'] != HARFBUZZ_PATH or pin['condition'] != HARFBUZZ_CONDITION
            or type(pin['size']) is not int or type(pin['afterSize']) is not int
            or len(original) != pin['size'] or _sha(original) != pin['sha256']):
        raise ValueError('source-recipe-input')
    hook = r'''# OpenGeul: only native Windows Meson needs these Cygwin process boundaries.
harfbuzz_meson_env :=
harfbuzz_meson_pkg_config_path = ${PKG_CONFIG_PATH}$(LIBO_PATH_SEPARATOR)$(gb_UnpackedTarball_workdir)/graphite$(if $(SYSTEM_ICU),,$(LIBO_PATH_SEPARATOR)$(gb_UnpackedTarball_workdir)/icu)
ifeq ($(OS)_$(CPUNAME)_$(COM)_$(OS_FOR_BUILD),WNT_X86_64_MSC_WNT)
ifneq ($(filter %-cygwin,$(MAKE_HOST)),)
ifeq ($(BUILD_PLATFORM),$(HOST_PLATFORM))
ifeq ($(strip $(WSL)$(PYTHON_FOR_BUILD)$(SYSTEM_PYTHON)),)
ifneq ($(filter MESON,$(BUILD_TYPE)),)
# Keep shell quoting separate from the literal double quotes parsed by Meson.
harfbuzz_meson_shquote = '$(subst ','"'"',$(1))'
define harfbuzz_meson_native_path
$(eval harfbuzz_meson_path := $(shell cygpath -lm $(call harfbuzz_meson_shquote,$(1))))$(if $(filter 0,$(.SHELLSTATUS)),,$(error HarfBuzz Meson path conversion failed))$(if $(strip $(harfbuzz_meson_path)),,$(error HarfBuzz Meson path conversion returned no path))$(harfbuzz_meson_path)
endef
define harfbuzz_meson_native_executable
$(if $(strip $(1)),,$(error HarfBuzz Meson $(2) executable is empty))$(eval harfbuzz_meson_path := $(shell value=$(call harfbuzz_meson_shquote,$(1)); value=$${value#"$${value%%[![:space:]]*}"}; value=$${value%"$${value##*[![:space:]]}"}; test -f "$$value" && cygpath -lm "$$value"))$(if $(filter 0,$(.SHELLSTATUS)),,$(error HarfBuzz Meson $(2) executable validation/conversion failed; wrappers and flags are unsupported))$(if $(strip $(harfbuzz_meson_path)),,$(error HarfBuzz Meson path conversion returned no path))$(harfbuzz_meson_path)
endef
harfbuzz_meson_cc := $(call harfbuzz_meson_native_executable,$(CC),CC)
harfbuzz_meson_cxx := $(call harfbuzz_meson_native_executable,$(CXX),CXX)
# Split native or POSIX lists per entry; a drive-letter colon is never a separator.
harfbuzz_meson_pkg_prefix := $(shell value=$(call harfbuzz_meson_shquote,$(PKG_CONFIG_PATH)); out=; item=; \
    emit() { if [ -n "$$item" ]; then native=$$(cygpath -lm "$$item") || return 7; \
        [ -n "$$native" ] || return 8; out="$${out:+$$out;}$$native"; fi; item=; }; \
    while [ -n "$$value" ]; do char=$${value%"$${value#?}"}; value=$${value#?}; \
        case "$$char" in (';') emit || exit $$?;; (':') \
            case "$$item" in ([a-zA-Z]) item="$$item:";; (*) emit || exit $$?;; esac;; \
            (*) item="$$item$$char";; esac; done; emit || exit $$?; printf '%s' "$$out")
ifneq ($(filter 0,$(.SHELLSTATUS)),0)
$(error HarfBuzz Meson pkg-config path conversion failed)
endif
harfbuzz_meson_pkg_config_path := $(harfbuzz_meson_pkg_prefix)$(if $(harfbuzz_meson_pkg_prefix),;)$(call harfbuzz_meson_native_path,$(gb_UnpackedTarball_workdir)/graphite)$(if $(SYSTEM_ICU),,;$(call harfbuzz_meson_native_path,$(gb_UnpackedTarball_workdir)/icu))
harfbuzz_meson_env = export CC=$(call harfbuzz_meson_shquote,"$(harfbuzz_meson_cc)") CXX=$(call harfbuzz_meson_shquote,"$(harfbuzz_meson_cxx)") &&
endif
endif
endif
endif
endif

'''.encode('utf-8')
    marker = b'# cannot use CROSS_COMPILING as condition since we have cross-compilation "light" for cases where\n'
    old = b'\t\tPKG_CONFIG_PATH="${PKG_CONFIG_PATH}$(LIBO_PATH_SEPARATOR)$(gb_UnpackedTarball_workdir)/graphite$(if $(SYSTEM_ICU),,$(LIBO_PATH_SEPARATOR)$(gb_UnpackedTarball_workdir)/icu)" \\\n'
    if original.count(marker) != 1 or original.count(old) != 1:
        raise ValueError('source-recipe-input')
    changed = original.replace(marker, hook + marker, 1).replace(old,
        b'\t\t$(harfbuzz_meson_env) \\\n\t\tPKG_CONFIG_PATH="$(harfbuzz_meson_pkg_config_path)" \\\n', 1)
    if len(changed) != pin['afterSize'] or _sha(changed) != pin['afterSha256']:
        raise ValueError('source-recipe-input')
    return changed


def _install_harfbuzz_native_meson_paths(source, evidence, pin):
    target = source / HARFBUZZ_PATH; original = _regular(target)
    changed = _harfbuzz_bytes(original, pin)
    retained = {phase: evidence / (phase + '-x64-ExternalProject_harfbuzz.mk')
                for phase in ('original', 'effective')}
    if any(path.exists() or path.is_symlink() for path in retained.values()):
        raise ValueError('source-recipe-input')
    for phase, raw in [('original', original), ('effective', changed)]:
        with retained[phase].open('xb') as stream: stream.write(raw)
        if _regular(retained[phase]) != raw: raise ValueError('source-recipe-output')
    target.write_bytes(changed)
    if _regular(target) != changed: raise ValueError('source-recipe-output')
    return {'schemaVersion': 1, 'kind': 'windows-x64-harfbuzz-native-meson-source-hook',
            'path': HARFBUZZ_PATH, 'condition': HARFBUZZ_CONDITION,
            'beforeBytes': len(original), 'afterBytes': len(changed),
            'beforeSha256': _sha(original), 'afterSha256': _sha(changed),
            'evidence': {phase: str(path) for phase, path in retained.items()},
            'nativeBuildVerified': False, 'fullEngineQualified': False,
            'acceptanceEligible': False, 'guiVerified': False}


def _atl_pins(lock):
    descriptor = lock['windowsAtlNativePaths']
    original = [lock['atlNativePaths']['recipe'], *lock['atlConsumerNativePaths']['recipes']]
    if (set(descriptor) != {'condition', 'recipes'} or descriptor['condition'] != ATL_CONDITION
            or type(descriptor['recipes']) is not list or len(descriptor['recipes']) != 6):
        raise ValueError('source-recipe-input')
    for path, baseline, pin in zip(ATL_PATHS, original, descriptor['recipes']):
        if (set(pin) != {'path', 'size', 'sha256', 'afterSize', 'afterSha256'}
                or pin['path'] != path or baseline['path'] != path
                or any(pin[key] != baseline[key] for key in ('size', 'sha256'))):
            raise ValueError('source-recipe-input')
        _pin(pin, path)
    return descriptor['recipes']


def _atl_bytes(original, pin):
    if (set(pin) != {'path', 'size', 'sha256', 'afterSize', 'afterSha256'}
            or pin['path'] not in ATL_PATHS or type(pin['size']) is not int
            or type(pin['afterSize']) is not int or not 0 < pin['size'] <= 1024 * 1024
            or not 0 < pin['afterSize'] <= 1024 * 1024
            or len(original) != pin['size'] or _sha(original) != pin['sha256']):
        raise ValueError('source-recipe-input')
    # Reuse the finite recipe renderer without changing its ARM defaults or pins.
    consumers = ((ATL_PATHS[0], 'so_activex', b'$(foreach i,$(ATL_INCLUDE), -I$(i))', 'libpath'),
                 *ARM._ATL_CONSUMERS)
    changed = ARM._atl_consumer_native_recipe(original, consumers[ATL_PATHS.index(pin['path'])])
    guard = b'ifeq ($(OS)_$(CPUNAME)_$(COM),WNT_AARCH64_MSC)'
    if changed.count(guard) != 1: raise ValueError('source-recipe-input')
    changed = changed.replace(guard, b'ifeq ($(OS)_$(CPUNAME)_$(COM),WNT_X86_64_MSC)', 1)
    if len(changed) != pin['afterSize'] or _sha(changed) != pin['afterSha256']:
        raise ValueError('source-recipe-input')
    return changed


def _install_atl_native_paths(source, evidence, descriptor):
    planned = []
    for index, pin in enumerate(descriptor['recipes'], 1):
        target = source / pin['path']; original = _regular(target)
        changed = _atl_bytes(original, pin)
        retained = {label: evidence / f'{label}-x64-atl-{index:02d}-{target.name}'
                    for label in ('original', 'effective')}
        if any(path.exists() or path.is_symlink() for path in retained.values()):
            raise ValueError('source-recipe-input')
        planned.append((pin, target, original, changed, retained))
    rows = []
    for pin, target, original, changed, retained in planned:
        for label, raw in (('original', original), ('effective', changed)):
            with retained[label].open('xb') as stream: stream.write(raw)
            if _regular(retained[label]) != raw: raise ValueError('source-recipe-output')
        target.write_bytes(changed)
        if _regular(target) != changed: raise ValueError('source-recipe-output')
        rows.append(dict(path=pin['path'], beforeBytes=len(original), afterBytes=len(changed),
                         beforeSha256=_sha(original), afterSha256=_sha(changed),
                         evidence={label: str(path) for label, path in retained.items()}))
    return dict(schemaVersion=1, kind='windows-x64-native-atl-source-hooks',
                condition=ATL_CONDITION, recipes=rows, nativeBuildVerified=False,
                fullEngineQualified=False, acceptanceEligible=False, guiVerified=False)


def _validate_common(inputs, lock, payloads, architecture):
    _flex_fatal_bytes(inputs[FLEX_PATH], lock['flexFatalCompatibility'])
    _dotnet_graph_pins(lock['windowsDotnetProjectGraph'])
    for pin in lock['windowsDotnetProjectGraph']['sources']:
        _dotnet_graph_bytes(inputs[pin['path']], pin)
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
        _gpg_build_compiler_bytes(inputs[GPG_PATH], lock['windowsGpgBuildCompilerPath'])
        for pin in _atl_pins(lock): _atl_bytes(inputs[pin['path']], pin)
        _harfbuzz_bytes(inputs[HARFBUZZ_PATH], lock['windowsHarfbuzzNativeMesonPaths'])
        _cli_policy_bytes(inputs[CLI_POLICY_PATH], lock['windowsCliPublisherPolicyPlatform'])
        for pin in lock['windowsX86CompanionStaticRuntime']['sources']:
            X86_CRT.transform(inputs[pin['path']], pin)


def _install_x86_companion_static_runtime(source, evidence, pin):
    return X86_CRT.install(source, evidence, pin)


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
                 'gpgBuildCompilerPath': _install_gpg_build_compiler_path(source, evidence, lock['windowsGpgBuildCompilerPath']),
                 'atlNativePaths': _install_atl_native_paths(source, evidence, lock['windowsAtlNativePaths']),
                 'harfbuzzNativeMesonPaths': _install_harfbuzz_native_meson_paths(source, evidence, lock['windowsHarfbuzzNativeMesonPaths']),
                 'cliPublisherPolicyPlatform': _install_cli_policy_platform(source, evidence, lock['windowsCliPublisherPolicyPlatform']),
                 'x86CompanionStaticRuntime': _install_x86_companion_static_runtime(source, evidence, lock['windowsX86CompanionStaticRuntime']),
                 'nativeBuildVerified': False, 'basePersistenceVerified': False}
    winacc = WINACC.install(source, evidence, CORE)
    flex = _install_flex_fatal_compat(source, evidence, lock['flexFatalCompatibility'], architecture)
    hooks['dotnetProjectGraph'] = _install_dotnet_project_graph(source, evidence, lock['windowsDotnetProjectGraph'], architecture)
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
    return {'sourceHooks': hooks, 'winAccFocusOrderSourcePatch': winacc,
            'flexFatalCompatibilitySourcePatch': flex, 'sourceRecipeProof': proof}


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
