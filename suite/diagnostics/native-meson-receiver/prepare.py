"""Prepare exact production-planner output for a bounded receiver observation.

This performs a control-local write, not full production installer execution.
The installed complete recipe is expanded unchanged by real Cygwin make.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import stat


HERE = Path(__file__).resolve().parent


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def regular(path):
    path = Path(path)
    for parent in (path, *path.parents):
        if parent.is_symlink():
            raise ValueError('Linked input path is forbidden: ' + str(path))
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError('Regular input file required: ' + str(path))
    return path.read_bytes()


def function_hash(source, name):
    functions = [node for node in ast.parse(source).body
                 if isinstance(node, ast.FunctionDef) and node.name == name]
    if len(functions) != 1:
        raise ValueError('Exactly one production planner function is required')
    return digest(ast.get_source_segment(source, functions[0]).encode())


def authentic_macro(source, name):
    start = 'define ' + name + '\n'
    if source.count(start) != 1:
        raise ValueError('Exactly one authentic macro is required: ' + name)
    offset = source.index(start)
    return source[offset:source.index('\nendef', offset) + len('\nendef')] + '\n'


def make_value(value):
    if any(char in value for char in '$#\r\n\0'):
        raise ValueError('Unsupported make assignment metacharacter')
    return value


def write_json(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def prepare(repo, work, evidence, python, meson, pkgconf, cc, python_search_path):
    repo, work, evidence = (Path(p).resolve(strict=True) for p in (repo, work, evidence))
    manifest_path = HERE / 'source-inputs.json'
    manifest = json.loads(regular(manifest_path))
    production = repo / 'suite/engine-build/enable_firebird_arm64.py'
    lock_path = production.with_name('source-build.json')
    module_raw, lock_raw = regular(production), regular(lock_path)
    lock = json.loads(lock_raw)
    key = 'harfbuzzNativeMesonPaths'
    if key not in lock:
        raise ValueError('Approved stable production Meson hook is not integrated')
    if manifest['productionBaseCommit'] == 'PENDING':
        raise ValueError('Approved immutable production base is not bound')
    expected = manifest['productionBinding']
    actual_binding = {'moduleSha256': digest(module_raw), 'lockSha256': digest(lock_raw),
                      'plannerCodeSha256': function_hash(module_raw.decode(), '_harfbuzz_native_meson_paths')}
    if any(actual_binding.get(name) != expected.get(name) for name in actual_binding):
        raise ValueError('Production module/lock/planner differs from the approved immutable binding')
    sources = {}
    for pin in manifest['files']:
        raw = regular(HERE / pin['file'])
        if len(raw) != pin['bytes'] or digest(raw) != pin['sha256']:
            raise ValueError('Authenticated complete source fixture differs: ' + pin['file'])
        sources[pin['file']] = raw
    spec = importlib.util.spec_from_file_location('approved_meson_production_hook', production)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    planner = '_harfbuzz_native_meson_paths'
    if not callable(getattr(module, planner, None)):
        raise ValueError('Approved production planner API is missing')
    recipe_path = lock[key]['recipe']['path']
    original = sources['source/ExternalProject_harfbuzz.mk']
    source = work / 'production-source'
    target = source / recipe_path
    target.parent.mkdir(parents=True)
    target.write_bytes(original)
    planned_target, before, after = getattr(module, planner)(source, lock[key])
    if planned_target != target or before != original or before == after:
        raise ValueError('Production planner did not identify the exact original recipe')
    temporary = target.with_suffix('.control-tmp')
    with temporary.open('xb') as stream:
        stream.write(after)
    os.replace(temporary, target)
    installed = regular(target)
    if installed != after or digest(installed) != lock[key]['recipe']['afterSha256']:
        raise ValueError('Control-local installed recipe bytes differ from production output')
    if digest(before) != expected['originalRecipeSha256'] or digest(installed) != expected['candidateRecipeSha256']:
        raise ValueError('Original/candidate recipe differs from the approved immutable binding')
    (evidence / 'original-ExternalProject_harfbuzz.mk').write_bytes(before)
    (evidence / 'effective-ExternalProject_harfbuzz.mk').write_bytes(installed)
    dependencies = work / 'Dependency Fixtures'
    for name in ('harfbuzz', 'graphite', 'icu', 'prefix pc'):
        (dependencies / name).mkdir(parents=True)
    external_macro = authentic_macro(sources['source/ExternalProject.mk'].decode(), 'gb_ExternalProject_run')
    pkg_macro = authentic_macro(sources['source/Helper.mk'].decode(), 'gb_pkgconfig_file')
    msc = sources['source/com_MSC_defs.mk'].decode().splitlines(keepends=True)
    compiler_binding = ''.join(msc[22:38])
    if 'gb_CC' not in compiler_binding or 'gb_CXX' not in compiler_binding:
        raise ValueError('Authenticated compiler binding slice is missing')
    for value in (str(python), str(meson), str(pkgconf), cc, python_search_path, str(work)):
        make_value(value)
    profile = ('SHELL := /usr/bin/bash\n.DEFAULT_GOAL := all\n'
               'OS := WNT\nOS_FOR_BUILD := WNT\nCPUNAME := AARCH64\nCOM := MSC\n'
               'BUILD_PLATFORM := aarch64-pc-cygwin\nHOST_PLATFORM := aarch64-pc-cygwin\n'
               'WSL :=\nPYTHON_FOR_BUILD :=\nSYSTEM_PYTHON :=\nBUILD_TYPE := MESON\n'
               'export CC := ' + cc + ' \nexport CXX := ' + cc + ' \n'
               'export AR :=\nexport LD :=\nunexport NINJA\n'
               'export PKG_CONFIG := ' + str(pkgconf).replace('\\', '/') + '\n'
               'export PKG_CONFIG_PATH := ' + str(dependencies / 'prefix pc') + '\n'
               'LIBO_PATH_SEPARATOR := :\nSYSTEM_ICU :=\n'
               'CXXFLAGS_CXX11 := -std:c++20 -permissive- -Zc:__cplusplus,preprocessor\n'
               'WHITESPACE := $(subst ,, )\nCOMMA := ,\nverbose := TRUE\n'
               'gb_UnpackedTarball_workdir := ..\n'
               'gb_ExternalProject_get_state_target = all\ngb_Helper_print_on_error = $(1)\n')
    observations = []
    for mode in ('capture', 'recipe'):
        for arm, recipe in (('original', before), ('candidate', installed)):
            observation = dependencies / (arm + '-' + mode)
            observation.mkdir()
            for name in ('meson.build', 'probe.c', 'probe.cpp', 'main.cpp', 'tool-observer.py'):
                (observation / name).write_bytes(regular(HERE / name))
            receiver = [str(python), str(HERE / 'receiver.py'), mode,
                        '--evidence', str(evidence), '--arm', arm]
            if mode == 'recipe':
                receiver += ['--meson', str(meson)]
            receiver += ['--']
            command = ' '.join(shlex.quote(x.replace('\\', '/')) for x in receiver)
            # The bundled interpreter is unavailable. This explicitly substitutes
            # its HOME/PATH precommand with setup-python + a minimal native PATH.
            command = 'PATH=' + shlex.quote(python_search_path) + ' ' + command
            makefile = observation / 'receiver.mk'
            body = (profile + 'EXTERNAL_WORKDIR := .\n'
                    'MESON = ' + command + '\n' + compiler_binding + '\n' + external_macro + '\n'
                    '$(file >$(EXTERNAL_WORKDIR)/builtin-make-host.txt,$(MAKE_HOST))\n' + recipe.decode())
            makefile.write_text(body, encoding='utf-8', newline='\n')
            observations.append({'mode': mode, 'arm': arm, 'directory': str(observation),
                                 'makefile': str(makefile), 'makefileSha256': digest(makefile.read_bytes()),
                                 'crossFile': str(dependencies / 'harfbuzz/cross-file.txt'),
                                 'unexpectedSibling': str(work / 'Dependency'),
                                 'installedRecipeSha256': digest(recipe)})
    binding = {'schemaVersion': 1, 'provenance': 'production planner output/control-local write, not fullinstaller execution',
               'productionBaseCommit': manifest['productionBaseCommit'], 'productionModuleSha256': digest(module_raw),
               'productionLockSha256': digest(lock_raw), 'productionPlannerName': planner,
               'productionPlannerCodeSha256': function_hash(module_raw.decode(), planner),
               'originalRecipeSha256': digest(before), 'returnedCandidateSha256': digest(after),
               'installedRecipeSha256': digest(installed), 'installedRecipe': str(target),
               'sourceInputsSha256': digest(regular(manifest_path)), 'dependencies': str(dependencies),
               'observations': observations, 'configuredCompiler': cc,
               'substitutions': {'scheduler': 'Minimal no-op scheduler/dependency/trace macros; authentic complete recipe and ExternalProject_run macro',
                                 'workdirAliases': 'Owned make cwd is each observation under Dependency Fixtures; EXTERNAL_WORKDIR=. and gb_UnpackedTarball_workdir=.. resolve the same physical spaced fixture directories. Original list entries remain relative; candidate production hook converts them to native absolute paths.',
                                 'python': 'setup-python native ARM64 3.12; explicitly substituted HOME/PATH precommand; not Native23 bundled3.13.15 equivalence',
                                 'tinySetup': 'Full HarfBuzz options captured for parity only; receiver explicitly substitutes tiny-project setup options'},
               'fullHarfBuzzOptionsExecuted': False, 'fullInstallerExecuted': False,
               'nativeEngineQualified': False, 'sourcePins': manifest['files']}
    (evidence / 'gb-pkgconfig-file.mk').write_text(pkg_macro)
    write_json(evidence / 'source-preparation.json', binding)
    return binding


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('repo', 'work', 'evidence', 'python', 'meson', 'pkgconf', 'cc', 'python-search-path'):
        parser.add_argument('--' + name, required=True)
    args = vars(parser.parse_args())
    prepare(**{key.replace('-', '_'): value for key, value in args.items()})


if __name__ == '__main__':
    main()
