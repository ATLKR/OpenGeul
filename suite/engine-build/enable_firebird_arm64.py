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
           b'$(call gb_Helper_extend_ld_path,$(gb_UnpackedTarball_workdir)/icu/source/lib:$(firebird_BUILDDIR)/lib),'
           + old + b')')
    changed = original.replace(old, new)
    if hashlib.sha256(changed).hexdigest() != lock['afterSha256']:
        raise ValueError('LibreOffice Firebird build path result SHA256 differs from its lock')
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
    project_evidence = {}
    if evidence is not None:
        evidence = Path(evidence)
        if any(path.is_symlink() for path in (evidence, *evidence.parents)) or not evidence.is_dir():
            raise ValueError('Firebird build path evidence requires regular owned directories')
        project_evidence = {'original': evidence / 'original-ExternalProject_firebird.mk',
                            'effective': evidence / 'effective-ExternalProject_firebird.mk'}
        if any(path.exists() or path.is_symlink() for path in project_evidence.values()):
            raise ValueError('Firebird build path evidence already exists')
    hook = ('\n# OpenGeul native Windows ARM64 Firebird CPU identity port.\n'
            'ifeq ($(OS)_$(CPUNAME),WNT_AARCH64)\n'
            '$(eval $(call gb_UnpackedTarball_add_patches,firebird,\\\n'
            '\texternal/firebird/' + patch_name + ' \\\n'
            '))\nendif\n').encode('utf-8')
    changed = original + hook
    # All source and patch checks precede source writes. The fresh build tree is
    # owned by this invocation; a repeated or changed hook is rejected above.
    bootstrap = install_module_bootstrap(source, evidence)
    for name, raw in (('original', project_original), ('effective', project_changed)):
        if project_evidence:
            with project_evidence[name].open('xb') as stream:
                stream.write(raw)
    with output.open('xb') as stream:
        stream.write(patch)
    try:
        with target.open('wb') as stream:
            stream.write(changed)
        with configure.open('wb') as stream:
            stream.write(configure_changed)
        project.write_bytes(project_changed)
        if _regular(project) != project_changed:
            raise ValueError('Effective Firebird build recipe bytes changed after write')
    except BaseException:
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
            'nativeBuildVerified': False, 'basePersistenceVerified': False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--libreoffice-source', type=Path, required=True)
    parser.add_argument('--evidence-directory', type=Path)
    args = parser.parse_args()
    print(json.dumps(install(args.libreoffice_source, args.evidence_directory), indent=2))


if __name__ == '__main__':
    main()
