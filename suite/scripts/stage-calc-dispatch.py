"""Overlay an externally authenticated diagnostic engine on a verified ARM64 Suite.

The baseline metadata remains historical baseline metadata. The root overlay
receipt explicitly disqualifies this copy from ordinary package acceptance.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import stat
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from suite import payload

MARKER = 'program/opengeul-calc-dispatch-diagnostic.json'
OVERLAY = 'calc-dispatch-diagnostic.json'
MAX_ARCHIVE_BYTES = 8 * 1024**3
MAX_EXTRACTED_BYTES = 16 * 1024**3
MAX_MEMBER_BYTES = 2 * 1024**3


def _local(path):
    path = Path(path).absolute()
    if str(path).startswith(('\\\\', '//')):
        raise ValueError('Local diagnostic inputs and output are required')
    for part in (*reversed(path.parents), path):
        if part.exists() or part.is_symlink(): payload._kind(part)
    return path.resolve(strict=False)


def _diagnostic_inputs(archive, receipt, commit, receipt_sha, archive_sha):
    if not payload.COMMIT.fullmatch(commit or '') or not all(payload._sha(x) for x in (receipt_sha, archive_sha)):
        raise ValueError('Externally trusted source and both input digests are required')
    archive, receipt = _local(archive), _local(receipt)
    if not 0 < payload._kind(receipt).st_size <= payload.MAX_METADATA:
        raise ValueError('Diagnostic receipt size exceeds bound')
    if payload._hash(receipt) != receipt_sha:
        raise ValueError('Diagnostic receipt differs from externally trusted digest')
    proof = payload._json(receipt)
    if (proof.get('schemaVersion') != 1 or type(proof['schemaVersion']) is not int
            or proof.get('kind') != 'native-office-engine-calc-dispatch-diagnostic'
            or proof.get('architecture') != 'arm64'
            or proof.get('status') != 'native-engine-calc-dispatch-diagnostic-built'
            or proof.get('passed') is not True or proof.get('fullEngineQualified') is not False
            or proof.get('acceptanceEligible') is not False or proof.get('sourceCommit') != commit
            or not payload._sha(proof.get('sourceLockSha256'))):
        raise ValueError('Diagnostic source build receipt is failed, unbound, or ordinarily qualified')
    artifact = proof.get('artifact', {})
    if (not isinstance(artifact, dict) or artifact.get('sha256') != archive_sha
            or type(artifact.get('size')) is not int or not 0 < artifact['size'] <= MAX_ARCHIVE_BYTES
            or archive.stat().st_size != artifact['size'] or payload._hash(archive) != archive_sha):
        raise ValueError('Diagnostic archive differs from externally trusted digest or size')
    return archive, receipt, proof


def _members(archive, proof):
    entries = archive.infolist()
    if not entries or len(entries) > payload.MAX_FILES:
        raise ValueError('Diagnostic archive count exceeds bound')
    aliases, nodes, spellings, total = set(), {}, {}, 0
    for entry in entries:
        name = payload._name(entry.filename.rstrip('/'))
        kind = stat.S_IFMT(entry.external_attr >> 16)
        directory = entry.is_dir()
        if (name.casefold() in aliases or entry.flag_bits & 1
                or kind not in ((0, stat.S_IFDIR) if directory else (0, stat.S_IFREG))
                or entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                or directory and entry.file_size != 0
                or entry.file_size > MAX_MEMBER_BYTES
                or name.casefold() == 'opengeul-branding.json'
                or name.split('/')[0].casefold() in ('hwp', 'office', 'worker', payload.INVENTORY, OVERLAY)):
            raise ValueError('Unsafe diagnostic archive member')
        aliases.add(name.casefold()); nodes[name.casefold()] = directory
        parts = name.split('/')
        for index in range(1, len(parts)+1):
            prefix = '/'.join(parts[:index]); key = prefix.casefold()
            if key in spellings and spellings[key] != prefix:
                raise ValueError('Case-aliased diagnostic archive directory')
            spellings[key] = prefix
        total += entry.file_size
        if total > MAX_EXTRACTED_BYTES: raise ValueError('Diagnostic archive size exceeds bound')
    for name in nodes:
        for parent in Path(name).parents:
            if str(parent) != '.' and nodes.get(parent.as_posix()) is False:
                raise ValueError('Diagnostic archive file/directory collision')
    for required in (MARKER, 'program/soffice.bin', 'program/soffice.exe', 'program/python.exe'):
        if nodes.get(required) is not False:
            raise ValueError('Diagnostic runtime is missing a required file')
    if archive.getinfo(MARKER).file_size > payload.MAX_METADATA:
        raise ValueError('Diagnostic runtime marker exceeds bound')
    marker = payload._json_bytes(archive.read(MARKER), MARKER)
    if (type(marker.get('schemaVersion')) is not int or marker['schemaVersion'] != 1
            or marker.get('kind') != 'calc-save-dispatch-diagnostic'
            or marker.get('acceptanceEligible') is not False
            or marker.get('fullEngineQualified') is not False
            or any(marker.get(key) != proof[key] for key in ('sourceCommit', 'sourceLockSha256'))):
        raise ValueError('Diagnostic runtime marker differs from authenticated receipt')
    return entries


def stage(*, baseline, archive, receipt, output, expected_engine_source_commit, expected_suite_source_commit,
          expected_receipt_sha256, expected_archive_sha256):
    baseline = _local(baseline)
    inventory = payload._json(baseline/payload.INVENTORY)
    # Complete normal qualification is mandatory before opening diagnostic input.
    payload.verify_payload(baseline, inventory)
    if (not payload.COMMIT.fullmatch(expected_suite_source_commit or '') or inventory['architecture'] != 'arm64'
            or payload._json(baseline/'suite-provenance.json')['sourceCommit'] != expected_suite_source_commit):
        raise ValueError('Baseline source/architecture differs from trusted Suite source')
    archive, receipt, proof = _diagnostic_inputs(archive, receipt, expected_engine_source_commit,
        expected_receipt_sha256, expected_archive_sha256)
    output = _local(output)
    if output.exists() or output == baseline or baseline in output.parents or output in baseline.parents:
        raise ValueError('A fresh diagnostic-only output outside the baseline is required')
    if any(output == item or output in item.parents for item in (archive, receipt)):
        raise ValueError('Diagnostic output must not contain its source inputs')
    overlay = dict(schemaVersion=2, kind='calc-save-dispatch-diagnostic', architecture='arm64',
        engineSourceCommit=expected_engine_source_commit, admittedSuiteSourceCommit=expected_suite_source_commit,
        sourceLockSha256=proof['sourceLockSha256'],
        acceptanceEligible=False, fullEngineQualified=False, baselineMetadataOnly=True,
        inputs=dict(baselineInventorySha256=payload._hash(baseline/payload.INVENTORY),
            receiptSha256=expected_receipt_sha256, archiveSha256=expected_archive_sha256,
            archiveBytes=proof['artifact']['size']))
    with zipfile.ZipFile(archive) as zipped:
        entries = _members(zipped, proof)
        shutil.copytree(baseline, output,
            ignore=lambda folder, names: ['Office'] if Path(folder) == baseline else [])
        # Mark the fresh copy before extracting any diagnostic executable, so
        # an interrupted extraction cannot become an ordinary package candidate.
        (output/OVERLAY).write_text(json.dumps(overlay, indent=2)+'\n', encoding='utf-8')
        office = output/'Office'; office.mkdir()
        for entry in entries:
            target = office/entry.filename.rstrip('/')
            if entry.is_dir(): target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with zipped.open(entry) as source, target.open('xb') as destination:
                    shutil.copyfileobj(source, destination, 1024*1024)
                if target.stat().st_size != entry.file_size:
                    raise ValueError('Diagnostic extracted member size changed')
        shutil.copyfile(baseline/'Office/opengeul-branding.json', office/'opengeul-branding.json')
    if (payload._hash(archive) != expected_archive_sha256
            or payload._hash(receipt) != expected_receipt_sha256):
        raise ValueError('Diagnostic source inputs changed during staging')
    payload.verify_payload(baseline, inventory)
    files = payload._scan(output)
    if any(files.get(name) != value for name, value in inventory['files'].items() if not name.startswith('Office/')):
        raise ValueError('Diagnostic copy changed non-Office baseline files')
    # This is a byte inventory of an explicitly diagnostic overlay, not the
    # distributable qualification performed by create_inventory.
    fresh = dict(schemaVersion=1, architecture='arm64', files=payload._scan(output))
    (output/payload.INVENTORY).write_text(json.dumps(fresh, indent=2)+'\n', encoding='utf-8')
    return overlay


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('baseline', 'archive', 'receipt', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    for name in ('expected-engine-source-commit', 'expected-suite-source-commit',
                 'expected-receipt-sha256', 'expected-archive-sha256'):
        parser.add_argument('--'+name, required=True)
    result = stage(**vars(parser.parse_args(argv)))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__': raise SystemExit(main())
