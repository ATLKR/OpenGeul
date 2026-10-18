"""Install the locked ARM64 Firebird patch into a fresh authenticated LO tree.

The caller verifies the complete LibreOffice source archive against source-build.json
before extraction. This helper additionally authenticates the exact source hook it
changes. It does not build or qualify a native runtime.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import stat

HERE = Path(__file__).resolve().parent


def _regular(path: Path) -> bytes:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError('Source input must be a regular file: ' + str(path))
    return path.read_bytes()


def _icu_build_path(source: Path, lock: dict) -> tuple[Path, bytes, bytes]:
    """Plan the ARM64-only correction before any owned source writes."""
    target = source / lock['path']
    original = _regular(target)
    if hashlib.sha256(original).hexdigest() != lock['sha256']:
        raise ValueError('LibreOffice Firebird build recipe SHA256 differs from the pinned source')
    old = (b'$(call gb_Helper_extend_ld_path,$(gb_UnpackedTarball_workdir)/icu/source/lib)'
           b'$(call gb_Helper_extend_ld_path,$(firebird_BUILDDIR)/lib)')
    new = (b'$(if $(filter WNT_AARCH64,$(OS)_$(CPUNAME)),'
           b'$(call gb_Helper_extend_ld_path,$(gb_UnpackedTarball_workdir)/icu/source/lib:$(firebird_BUILDDIR)/bin),'
           + old + b')')
    changed = original.replace(old, new)
    if hashlib.sha256(changed).hexdigest() != lock['afterSha256']:
        raise ValueError('LibreOffice Firebird build path result SHA256 differs from its lock')
    return target, original, changed


def _zstd_source_links(source: Path, lock: dict) -> tuple[Path, bytes, bytes]:
    """Keep portable source-test links confined to the exact ARM64 untar target."""
    target = source / lock['path']
    if target.parent.is_symlink() or not target.parent.is_dir():
        raise ValueError('Zstd source unpack requires a regular recipe directory')
    original = _regular(target)
    if hashlib.sha256(original).hexdigest() != lock['sha256']:
        raise ValueError('LibreOffice zstd unpack recipe SHA256 differs from the pinned source')
    changed = original + (
        b'\n# Preserve source-only CLI test symlinks whose targets occur later in the archive.\n'
        b'# Keep native module and DLL links strict outside this exact unpack target.\n'
        b'ifeq ($(OS)_$(CPUNAME),WNT_AARCH64)\n'
        b'$(call gb_UnpackedTarget_get_target,$(ZSTD_TARBALL)): export CYGWIN := winsymlinks:sys\n'
        b'endif\n')
    if hashlib.sha256(changed).hexdigest() != lock['afterSha256']:
        raise ValueError('LibreOffice zstd unpack result SHA256 differs from its lock')
    return target, original, changed


def _mdds_equality(source: Path, lock: dict):
    """Authenticate and plan the exact two-header native-control correction."""
    target = source / lock['recipe']['path']
    if target.parent.is_symlink() or not target.parent.is_dir():
        raise ValueError('MDDS source hook requires a regular recipe directory')
    original = _regular(target)
    if hashlib.sha256(original).hexdigest() != lock['recipe']['sha256']:
        raise ValueError('MDDS unpack recipe SHA256 differs from the pinned source')
    upstream = _regular(target.parent / lock['upstreamPatch']['filename'])
    if hashlib.sha256(upstream).hexdigest() != lock['upstreamPatch']['sha256']:
        raise ValueError('MDDS existing GCC12 patch SHA256 differs from its lock')
    patch_name = lock['patch']['filename']
    if Path(patch_name).name != patch_name:
        raise ValueError('Invalid MDDS patch filename')
    patch = _regular(HERE / patch_name)
    if hashlib.sha256(patch).hexdigest() != lock['patch']['sha256']:
        raise ValueError('MDDS equality patch SHA256 differs from its lock')
    output = target.parent / patch_name
    if output.exists() or output.is_symlink():
        raise ValueError('MDDS patch output already exists')
    changed = original + (
        b'\n'
        b'# OpenGeul native Windows ARM64 MDDS equality definition correction.\n'
        b'ifeq ($(OS)_$(CPUNAME),WNT_AARCH64)\n'
        b'$(eval $(call gb_UnpackedTarball_add_patches,mdds,\\\n'
        b'\texternal/mdds/opengeul-arm64-equality.patch.1 \\\n'
        b'))\n'
        b'endif\n'
    )
    if hashlib.sha256(changed).hexdigest() != lock['recipe']['afterSha256']:
        raise ValueError('MDDS unpack result SHA256 differs from its lock')
    return target, original, changed, output, patch


def _python_native_host(source: Path, lock: dict):
    """Plan the proven late compiler/linker host override without changing Python."""
    target = source / lock['recipe']['path']
    if target.parent.is_symlink() or not target.parent.is_dir():
        raise ValueError('Python host source hook requires a regular recipe directory')
    original = _regular(target)
    recipe = lock['recipe']
    if len(original) != recipe['size'] or hashlib.sha256(original).hexdigest() != recipe['sha256']:
        raise ValueError('Python build recipe SHA256 differs from the pinned source')
    name = lock['targets']['filename']
    if Path(name).name != name or name != 'opengeul-native-arm64-tools.targets':
        raise ValueError('Invalid Python host targets filename')
    payload = _regular(HERE / name)
    pin = lock['targets']
    if len(payload) != pin['size'] or hashlib.sha256(payload).hexdigest() != pin['sha256']:
        raise ValueError('Python host targets SHA256 differs from its lock')
    output = target.parent / name
    if output.exists() or output.is_symlink():
        raise ValueError('Python host targets output already exists')
    old = b'MSBuild.exe pcbuild.sln /t:Build $(gb_MSBUILD_CONFIG_AND_PLATFORM) \\\n'
    new = old + (b'\t\t\t$(if $(filter WNT_AARCH64,$(OS)_$(CPUNAME)),/p:ForceImportAfterCppTargets="$(SRCDIR)/external/python3/'
                 + name.encode('ascii') + b'") \\\n')
    changed = original.replace(old, new)
    if len(changed) != recipe['afterSize'] or hashlib.sha256(changed).hexdigest() != recipe['afterSha256']:
        raise ValueError('Python build recipe result SHA256 differs from its lock')
    return target, original, changed, output, payload


def _atl_native_paths(source: Path, lock: dict):
    """Plan recipe-local native Windows argv for the actual Cygwin make profile."""
    recipe = lock['recipe']
    target = source / recipe['path']
    if target.parent.is_symlink() or not target.parent.is_dir():
        raise ValueError('ATL source hook requires a regular recipe directory')
    original = _regular(target)
    if len(original) != recipe['size'] or hashlib.sha256(original).hexdigest() != recipe['sha256']:
        raise ValueError('ATL build recipe SHA256 differs from the pinned source')
    hook = (
        b'# OpenGeul: native MSVC arguments require Windows paths under Cygwin GNU make.\n'
        b'so_activex_ATL_INCLUDE := $(foreach i,$(ATL_INCLUDE), -I$(i))\n'
        b'so_activex_ATL_LIB := $(ATL_LIB)\n'
        b'so_activex_ATL_LIBS := $(ATL_LIB)/atls.lib\n'
        b'so_activex_ATL_LINK_LIB :=\n'
        b'ifeq ($(OS)_$(CPUNAME),WNT_AARCH64)\n'
        b'ifneq ($(filter %-cygwin,$(MAKE_HOST)),)\n'
        b'ifeq ($(strip $(ATL_INCLUDE)),)\n'
        b'$(error ATL include path is empty)\n'
        b'endif\n'
        b'define so_activex_native_atl_path\n'
        b'$(eval so_activex_atl_path := $(shell cygpath -lm "$(1)"))$(if $(filter 0,$(.SHELLSTATUS)),,$(error ATL path conversion failed))$(if $(strip $(so_activex_atl_path)),,$(error ATL path conversion returned no path))"$(so_activex_atl_path)"\n'
        b'endef\n'
        b'so_activex_ATL_INCLUDE := $(foreach i,$(ATL_INCLUDE), -I$(call so_activex_native_atl_path,$(i)))\n'
        b'so_activex_ATL_LIB := $(call so_activex_native_atl_path,$(ATL_LIB))\n'
        b'# T_LIBS is word-sorted by com_MSC_class.mk; keep this quoted path in ldflags.\n'
        b'so_activex_ATL_LINK_LIB := $(so_activex_ATL_LIB)/atls.lib\n'
        b'so_activex_ATL_LIBS :=\n'
        b'endif\n'
        b'endif\n'
        b'\n'
    )
    changed = original.replace(b'$(eval $(call gb_Library_Library,so_activex))',
                               hook + b'$(eval $(call gb_Library_Library,so_activex))')
    changed = changed.replace(b'\t$(foreach i,$(ATL_INCLUDE), -I$(i))', b'\t$(so_activex_ATL_INCLUDE)')
    changed = changed.replace(b'\t-LIBPATH:$(ATL_LIB)',
                              b'\t-LIBPATH:$(so_activex_ATL_LIB) $(so_activex_ATL_LINK_LIB)')
    changed = changed.replace(b'\t$(ATL_LIB)/atls.lib', b'\t$(so_activex_ATL_LIBS)')
    if len(changed) != recipe['afterSize'] or hashlib.sha256(changed).hexdigest() != recipe['afterSha256']:
        raise ValueError('ATL build recipe result SHA256 differs from its lock')
    return target, original, changed


_ATL_CONSUMERS = (
    ('embedserv/Library_emser.mk', 'emser', b'-I$(ATL_INCLUDE)', 'libpath'),
    ('extensions/Library_oleautobridge.mk', 'oleautobridge', b'$(foreach inc,$(ATL_INCLUDE),-I$(inc))', 'libpath'),
    ('winaccessibility/Library_uacccom.mk', 'uacccom', b'$(foreach i,$(ATL_INCLUDE), -I$(i))', 'def'),
    ('winaccessibility/Library_winaccessibility.mk', 'winaccessibility', b'$(foreach i,$(ATL_INCLUDE), -I$(i))', ''),
    ('winaccessibility/WinResTarget_uacccom.mk', 'uacccom_resource', b'$(foreach i,$(ATL_INCLUDE), -I$(i))', ''),
)


def _atl_consumer_native_recipe(original: bytes, consumer: tuple) -> bytes:
    """Render only the five enumerated recipe-local ATL argument corrections."""
    relative, name, include, link = consumer
    prefix = (name + '_native_atl').encode('ascii')
    hook = (b'# OpenGeul: keep native ATL arguments local to this recipe.\n'
            b'@P@_INCLUDE := ' + include + b'\n')
    if link:
        hook += (b'@P@_LIB := $(ATL_LIB)\n'
                 b'@P@_LIBS := $(ATL_LIB)/atls.lib\n'
                 b'@P@_LINK_LIB :=\n')
    hook += r'''ifeq ($(OS)_$(CPUNAME)_$(COM),WNT_AARCH64_MSC)
ifneq ($(filter %-cygwin,$(MAKE_HOST)),)
ifeq ($(strip $(ATL_INCLUDE)),)
$(error ATL include path is empty)
endif
@P@_shquote = '$(subst ','"'"',$(1))'
define @P@_path
$(if $(strip $(1)),,$(error ATL path is empty))$(eval @P@_converted := $(shell cygpath -lm $(call @P@_shquote,$(1))))$(if $(filter 0,$(.SHELLSTATUS)),,$(error ATL path conversion failed))$(if $(strip $(@P@_converted)),,$(error ATL path conversion returned no path))"$(@P@_converted)"
endef
@P@_INCLUDE := $(foreach i,$(ATL_INCLUDE), -I$(call @P@_path,$(i)))
'''.encode('ascii')
    if link:
        hook += (b'@P@_LIB := $(call @P@_path,$(ATL_LIB))\n'
                 b'# Native paths with spaces must bypass the sorted T_LIBS word list.\n'
                 b'@P@_LINK_LIB := $(@P@_LIB)/atls.lib\n'
                 b'@P@_LIBS :=\n')
    hook = (hook + b'endif\nendif\n\n').replace(b'@P@', prefix)
    target = 'UAccCOM' if name in ('uacccom', 'uacccom_resource') else name
    kind = 'WinResTarget' if name == 'uacccom_resource' else 'Library'
    marker = ('$(eval $(call gb_' + kind + '_' + kind + ',' + target + '))').encode('ascii')
    replacements = [(marker, hook + marker),
                    (b'\t' + include + b' \\\n', b'\t$(' + prefix + b'_INCLUDE) \\\n')]
    if link:
        replacements.append((b'\t$(ATL_LIB)/atls.lib \\\n', b'\t$(' + prefix + b'_LIBS) \\\n'))
        if link == 'libpath':
            replacements.append((b'\t-LIBPATH:$(ATL_LIB) \\\n',
                                 b'\t-LIBPATH:$(' + prefix + b'_LIB) $(' + prefix + b'_LINK_LIB) \\\n'))
        else:
            replacements.append((b'\t/DEF:$(SRCDIR)/winaccessibility/source/UAccCOM/UAccCOM.def \\\n',
                                 b'\t/DEF:$(SRCDIR)/winaccessibility/source/UAccCOM/UAccCOM.def $(' + prefix + b'_LINK_LIB) \\\n'))
    changed = original
    for before, after in replacements:
        if changed.count(before) != 1:
            raise ValueError('ATL consumer recipe anchor differs: ' + relative)
        changed = changed.replace(before, after, 1)
    return changed


def _atl_consumer_native_paths(source: Path, lock: dict):
    """Authenticate every remaining production ATL consumer before any writes."""
    pins = lock['recipes']
    if [pin['path'] for pin in pins] != [item[0] for item in _ATL_CONSUMERS]:
        raise ValueError('ATL consumer recipe paths differ from the finite source contract')
    plans = []
    for consumer, recipe in zip(_ATL_CONSUMERS, pins):
        target = source / recipe['path']
        if any(path.is_symlink() or not path.is_dir() for path in (source, target.parent)):
            raise ValueError('ATL consumer source hook requires regular recipe directories')
        original = _regular(target)
        if len(original) != recipe['size'] or hashlib.sha256(original).hexdigest() != recipe['sha256']:
            raise ValueError('ATL consumer recipe SHA256 differs from the pinned source')
        changed = _atl_consumer_native_recipe(original, consumer)
        if len(changed) != recipe['afterSize'] or hashlib.sha256(changed).hexdigest() != recipe['afterSha256']:
            raise ValueError('ATL consumer recipe result SHA256 differs from its lock')
        plans.append((target, original, changed))
    return plans


def _harfbuzz_native_meson_paths(source: Path, lock: dict):
    """Plan the HarfBuzz-only Cygwin to bundled Windows Meson boundary."""
    recipe = lock['recipe']
    target = source / recipe['path']
    if any(path.is_symlink() or not path.is_dir()
           for path in (source / 'external', target.parent)):
        raise ValueError('HarfBuzz Meson source hook requires regular recipe directories')
    original = _regular(target)
    if len(original) != recipe['size'] or hashlib.sha256(original).hexdigest() != recipe['sha256']:
        raise ValueError('HarfBuzz Meson recipe SHA256 differs from the pinned source')
    hook = r'''# OpenGeul: only native Windows Meson needs these Cygwin process boundaries.
harfbuzz_meson_env :=
harfbuzz_meson_pkg_config_path = ${PKG_CONFIG_PATH}$(LIBO_PATH_SEPARATOR)$(gb_UnpackedTarball_workdir)/graphite$(if $(SYSTEM_ICU),,$(LIBO_PATH_SEPARATOR)$(gb_UnpackedTarball_workdir)/icu)
ifeq ($(OS)_$(CPUNAME)_$(COM)_$(OS_FOR_BUILD),WNT_AARCH64_MSC_WNT)
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
    changed = original.replace(marker, hook + marker)
    old = b'\t\tPKG_CONFIG_PATH="${PKG_CONFIG_PATH}$(LIBO_PATH_SEPARATOR)$(gb_UnpackedTarball_workdir)/graphite$(if $(SYSTEM_ICU),,$(LIBO_PATH_SEPARATOR)$(gb_UnpackedTarball_workdir)/icu)" \\\n'
    new = (b'\t\t$(harfbuzz_meson_env) \\\n'
           b'\t\tPKG_CONFIG_PATH="$(harfbuzz_meson_pkg_config_path)" \\\n')
    changed = changed.replace(old, new)
    if len(changed) != recipe['afterSize'] or hashlib.sha256(changed).hexdigest() != recipe['afterSha256']:
        raise ValueError('HarfBuzz Meson recipe result SHA256 differs from its lock')
    return target, original, changed


def install_module_bootstrap(source: Path, evidence: Path | None = None) -> dict:
    """Correct the pinned unpack helper's inverted git-hooks selection only."""
    lock = json.loads((HERE / 'source-build.json').read_text(encoding='utf-8'))['moduleBootstrap']
    source = Path(source).resolve(strict=True)
    target = source / lock['path']
    if target.parent.is_symlink() or not target.parent.is_dir():
        raise ValueError('Source bootstrap requires a regular bin directory')
    original = _regular(target)
    if hashlib.sha256(original).hexdigest() != lock['sha256']:
        raise ValueError('LibreOffice unpack helper SHA256 differs from the pinned source')
    changed = original.replace(b'-type d -path ', b'-type d ! -path ')
    if hashlib.sha256(changed).hexdigest() != lock['afterSha256']:
        raise ValueError('LibreOffice module bootstrap result SHA256 differs from its lock')
    retained = {}
    if evidence is not None:
        evidence = Path(evidence)
        if any(path.is_symlink() for path in (evidence, *evidence.parents)) or not evidence.is_dir():
            raise ValueError('Source bootstrap evidence requires regular owned directories')
        retained = {'original': evidence / 'original-unpack-sources',
                    'effective': evidence / 'effective-unpack-sources'}
        if any(path.exists() or path.is_symlink() for path in retained.values()):
            raise ValueError('Source bootstrap evidence already exists')
        for name, raw in (('original', original), ('effective', changed)):
            with retained[name].open('xb') as stream:
                stream.write(raw)
    target.write_bytes(changed)
    if _regular(target) != changed:
        raise ValueError('Effective source bootstrap bytes changed after write')
    return {'path': lock['path'], 'beforeSha256': lock['sha256'],
            'afterSha256': lock['afterSha256'],
            'evidence': {name: str(path) for name, path in retained.items()}}


def install(source: Path, evidence: Path | None = None) -> dict:
    lock = json.loads((HERE / 'source-build.json').read_text(encoding='utf-8'))
    source = Path(source).resolve(strict=True)
    target = source / lock['sourceHook']['path']
    for directory in (source / 'external', target.parent):
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError('Source hook requires regular directories')
    original = _regular(target)
    before = hashlib.sha256(original).hexdigest()
    if before != lock['sourceHook']['sha256']:
        raise ValueError('LibreOffice Firebird source hook SHA256 differs from the pinned source')
    configure = source / lock['configureSource']['path']
    configure_original = _regular(configure)
    if hashlib.sha256(configure_original).hexdigest() != lock['configureSource']['sha256']:
        raise ValueError('LibreOffice configure.ac SHA256 differs from the pinned source')
    configure_patch = _regular(HERE / lock['configurePatch']['filename'])
    if hashlib.sha256(configure_patch).hexdigest() != lock['configurePatch']['sha256']:
        raise ValueError('LibreOffice configure patch SHA256 differs from its lock')
    configure_changed = configure_original.replace(
        b'        enable_coinmp=no\n        enable_firebird_sdbc=no\n',
        b'        enable_coinmp=no\n')
    if hashlib.sha256(configure_changed).hexdigest() != lock['configureSource']['afterSha256']:
        raise ValueError('LibreOffice configure port result SHA256 differs from its lock')
    patch_name = lock['portPatch']['filename']
    if Path(patch_name).name != patch_name:
        raise ValueError('Invalid port patch filename')
    patch = _regular(HERE / patch_name)
    if hashlib.sha256(patch).hexdigest() != lock['portPatch']['sha256']:
        raise ValueError('Firebird ARM64 port patch SHA256 differs from its lock')
    output = target.parent / patch_name
    if output.exists() or output.is_symlink():
        raise ValueError('Port patch output already exists')
    project, project_original, project_changed = _icu_build_path(source, lock['icuBuildPath'])
    zstd, zstd_original, zstd_changed = _zstd_source_links(source, lock['zstdSourceLinks'])
    mdds, mdds_original, mdds_changed, mdds_output, mdds_patch = _mdds_equality(source, lock['mddsEquality'])
    python, python_original, python_changed, python_output, python_payload = _python_native_host(source, lock['pythonNativeHost'])
    atl, atl_original, atl_changed = _atl_native_paths(source, lock['atlNativePaths'])
    atl_consumers = _atl_consumer_native_paths(source, lock['atlConsumerNativePaths'])
    harfbuzz, harfbuzz_original, harfbuzz_changed = _harfbuzz_native_meson_paths(source, lock['harfbuzzNativeMesonPaths'])
    atl_consumer_evidence = []
    harfbuzz_evidence = {}
    atl_evidence = {}
    python_evidence = {}
    mdds_evidence = {}
    project_evidence = {}
    zstd_evidence = {}
    if evidence is not None:
        evidence = Path(evidence)
        if any(path.is_symlink() for path in (evidence, *evidence.parents)) or not evidence.is_dir():
            raise ValueError('Firebird build path evidence requires regular owned directories')
        atl_evidence = {'original': evidence / 'original-Library_so_activex.mk',
                        'effective': evidence / 'effective-Library_so_activex.mk'}
        if any(path.exists() or path.is_symlink() for path in atl_evidence.values()):
            raise ValueError('ATL recipe evidence already exists')
        for consumer, _, _ in atl_consumers:
            paths = {'original': evidence / ('original-' + consumer.name),
                     'effective': evidence / ('effective-' + consumer.name)}
            if any(path.exists() or path.is_symlink() for path in paths.values()):
                raise ValueError('ATL consumer recipe evidence already exists')
            atl_consumer_evidence.append(paths)
        harfbuzz_evidence = {'original': evidence / 'original-ExternalProject_harfbuzz.mk',
                             'effective': evidence / 'effective-ExternalProject_harfbuzz.mk'}
        if any(path.exists() or path.is_symlink() for path in harfbuzz_evidence.values()):
            raise ValueError('HarfBuzz Meson recipe evidence already exists')
        project_evidence = {'original': evidence / 'original-ExternalProject_firebird.mk',
                            'effective': evidence / 'effective-ExternalProject_firebird.mk'}
        if any(path.exists() or path.is_symlink() for path in project_evidence.values()):
            raise ValueError('Firebird build path evidence already exists')
        zstd_evidence = {'original': evidence / 'original-UnpackedTarball_zstd.mk',
                         'effective': evidence / 'effective-UnpackedTarball_zstd.mk'}
        if any(path.exists() or path.is_symlink() for path in zstd_evidence.values()):
            raise ValueError('Zstd unpack evidence already exists')
        mdds_evidence = {'original': evidence / 'original-UnpackedTarball_mdds.mk',
                         'effective': evidence / 'effective-UnpackedTarball_mdds.mk'}
        if any(path.exists() or path.is_symlink() for path in mdds_evidence.values()):
            raise ValueError('MDDS unpack evidence already exists')
        python_evidence = {'original': evidence / 'original-ExternalProject_python3.mk',
                           'effective': evidence / 'effective-ExternalProject_python3.mk',
                           'targets': evidence / 'effective-opengeul-native-arm64-tools.targets'}
        if any(path.exists() or path.is_symlink() for path in python_evidence.values()):
            raise ValueError('Python build recipe evidence already exists')
    hook = ('\n# OpenGeul native Windows ARM64 Firebird CPU identity port.\n'
            'ifeq ($(OS)_$(CPUNAME),WNT_AARCH64)\n'
            '$(eval $(call gb_UnpackedTarball_add_patches,firebird,\\\n'
            '\texternal/firebird/' + patch_name + ' \\\n'
            '))\nendif\n').encode('utf-8')
    changed = original + hook
    # All source and patch checks precede source writes. The fresh build tree is
    # owned by this invocation; a repeated or changed hook is rejected above.
    bootstrap = install_module_bootstrap(source, evidence)
    for (_, consumer_original, consumer_effective), paths in zip(atl_consumers, atl_consumer_evidence):
        for name, raw in (('original', consumer_original), ('effective', consumer_effective)):
            with paths[name].open('xb') as stream:
                stream.write(raw)
    for name, raw in (('original', harfbuzz_original), ('effective', harfbuzz_changed)):
        if harfbuzz_evidence:
            with harfbuzz_evidence[name].open('xb') as stream:
                stream.write(raw)
    for name, raw in (('original', atl_original), ('effective', atl_changed)):
        if atl_evidence:
            with atl_evidence[name].open('xb') as stream:
                stream.write(raw)
    for name, raw in (('original', project_original), ('effective', project_changed)):
        if project_evidence:
            with project_evidence[name].open('xb') as stream:
                stream.write(raw)
    for name, raw in (('original', zstd_original), ('effective', zstd_changed)):
        if zstd_evidence:
            with zstd_evidence[name].open('xb') as stream:
                stream.write(raw)
    for name, raw in (('original', mdds_original), ('effective', mdds_changed)):
        if mdds_evidence:
            with mdds_evidence[name].open('xb') as stream:
                stream.write(raw)
    for name, raw in (('original', python_original), ('effective', python_changed), ('targets', python_payload)):
        if python_evidence:
            with python_evidence[name].open('xb') as stream:
                stream.write(raw)
    with python_output.open('xb') as stream:
        stream.write(python_payload)
    with mdds_output.open('xb') as stream:
        stream.write(mdds_patch)
    with output.open('xb') as stream:
        stream.write(patch)
    try:
        with target.open('wb') as stream:
            stream.write(changed)
        with configure.open('wb') as stream:
            stream.write(configure_changed)
        project.write_bytes(project_changed)
        zstd.write_bytes(zstd_changed)
        mdds.write_bytes(mdds_changed)
        python.write_bytes(python_changed)
        atl.write_bytes(atl_changed)
        for consumer, _, after in atl_consumers:
            consumer.write_bytes(after)
        harfbuzz.write_bytes(harfbuzz_changed)
        for consumer, _, after in atl_consumers:
            if _regular(consumer) != after:
                raise ValueError('Effective ATL consumer source hook bytes changed after write')
        if _regular(harfbuzz) != harfbuzz_changed:
            raise ValueError('Effective HarfBuzz Meson recipe bytes changed after write')
        if _regular(atl) != atl_changed:
            raise ValueError('Effective ATL source hook bytes changed after write')
        if _regular(python) != python_changed or _regular(python_output) != python_payload:
            raise ValueError('Effective Python host source hook bytes changed after write')
        if _regular(mdds) != mdds_changed or _regular(mdds_output) != mdds_patch:
            raise ValueError('Effective MDDS source hook bytes changed after write')
        if _regular(project) != project_changed:
            raise ValueError('Effective Firebird build recipe bytes changed after write')
        if _regular(zstd) != zstd_changed:
            raise ValueError('Effective zstd unpack recipe bytes changed after write')
    except BaseException:
        python_output.unlink(missing_ok=True)
        mdds_output.unlink(missing_ok=True)
        output.unlink(missing_ok=True)
        raise
    return {'schemaVersion': 1, 'status': 'source-hook-installed-native-build-pending',
            'architecture': 'arm64', 'libreofficeVersion': lock['libreoffice']['version'],
            'firebirdVersion': lock['firebird']['version'],
            'sourceHook': lock['sourceHook']['path'], 'beforeSha256': before,
            'afterSha256': hashlib.sha256(changed).hexdigest(),
            'portPatchSha256': lock['portPatch']['sha256'],
            'configurePatchSha256': lock['configurePatch']['sha256'],
            'configureBeforeSha256': lock['configureSource']['sha256'],
            'configureAfterSha256': lock['configureSource']['afterSha256'],
            'moduleBootstrap': bootstrap,
            'icuBuildPath': {'path': lock['icuBuildPath']['path'],
                             'beforeSha256': lock['icuBuildPath']['sha256'],
                             'afterSha256': lock['icuBuildPath']['afterSha256'],
                             'evidence': {name: str(path) for name, path in project_evidence.items()}},
            'zstdSourceLinks': {'path': lock['zstdSourceLinks']['path'],
                                'beforeSha256': lock['zstdSourceLinks']['sha256'],
                                'afterSha256': lock['zstdSourceLinks']['afterSha256'],
                                'archive': lock['zstdSourceLinks']['archive'],
                                'scope': lock['zstdSourceLinks']['scope'],
                                'evidence': {name: str(path) for name, path in zstd_evidence.items()}},
            'mddsEquality': {'path': lock['mddsEquality']['recipe']['path'],
                             'beforeSha256': lock['mddsEquality']['recipe']['sha256'],
                             'afterSha256': lock['mddsEquality']['recipe']['afterSha256'],
                             'patchSha256': lock['mddsEquality']['patch']['sha256'],
                             'upstreamPatchSha256': lock['mddsEquality']['upstreamPatch']['sha256'],
                             'scope': lock['mddsEquality']['scope'],
                             'evidence': {name: str(path) for name, path in mdds_evidence.items()}},
            'pythonNativeHost': {'path': lock['pythonNativeHost']['recipe']['path'],
                                 'beforeSha256': lock['pythonNativeHost']['recipe']['sha256'],
                                 'afterSha256': lock['pythonNativeHost']['recipe']['afterSha256'],
                                 'targetsSha256': lock['pythonNativeHost']['targets']['sha256'],
                                 'targetsPath': str(python_output),
                                 'scope': lock['pythonNativeHost']['scope'],
                                 'evidence': {name: str(path) for name, path in python_evidence.items()}},
            'atlNativePaths': {'path': lock['atlNativePaths']['recipe']['path'],
                               'beforeSha256': lock['atlNativePaths']['recipe']['sha256'],
                               'afterSha256': lock['atlNativePaths']['recipe']['afterSha256'],
                               'scope': lock['atlNativePaths']['scope'],
                               'evidence': {name: str(path) for name, path in atl_evidence.items()}},
            'atlConsumerNativePaths': {
                'scope': lock['atlConsumerNativePaths']['scope'],
                'recipes': [{'path': str(consumer.relative_to(source)).replace('\\', '/'),
                             'beforeSha256': hashlib.sha256(before).hexdigest(),
                             'afterSha256': hashlib.sha256(after).hexdigest(),
                             'evidence': {name: str(path) for name, path in
                                          (atl_consumer_evidence[index] if atl_consumer_evidence else {}).items()}}
                            for index, (consumer, before, after) in enumerate(atl_consumers)]},
            'harfbuzzNativeMesonPaths': {'path': lock['harfbuzzNativeMesonPaths']['recipe']['path'],
                                       'beforeSha256': lock['harfbuzzNativeMesonPaths']['recipe']['sha256'],
                                       'afterSha256': lock['harfbuzzNativeMesonPaths']['recipe']['afterSha256'],
                                       'scope': lock['harfbuzzNativeMesonPaths']['scope'],
                                       'evidence': {name: str(path) for name, path in harfbuzz_evidence.items()}},
            'nativeBuildVerified': False, 'basePersistenceVerified': False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--libreoffice-source', type=Path, required=True)
    parser.add_argument('--evidence-directory', type=Path)
    args = parser.parse_args()
    print(json.dumps(install(args.libreoffice_source, args.evidence_directory), indent=2))


if __name__ == '__main__':
    main()
