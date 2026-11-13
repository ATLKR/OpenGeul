"""Stage the source-built Windows distribution, rather than developer instdir.

Upstream Helper.mk excludes gb_MERGEDLIBS from AutoInstall: their instdir
targets contain 'invalid - merged lib', while mergedlo.dll holds their code.
This assembler changes the input to the existing PE/CRT/UNO qualification
gates; it does not admit, execute, or classify executable code.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import zipfile


REQUIRED_NATIVE_OUTPUTS = ('program/soffice.bin', 'program/python.exe',
                           'program/pyuno.pyd', 'program/ifbclient.dll',
                           'program/Engine12.dll', 'program/intl/fbintl.dll')
HELP_LANGUAGES = ('en-US', 'ko')


def sha256_file(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def safe_member(name):
    """Return ZIP path parts that name the same regular Windows destination."""
    value = name[:-1] if name.endswith('/') else name
    parts = value.split('/')
    devices = {'CON', 'PRN', 'AUX', 'NUL'} | {
        prefix + number for prefix in ('COM', 'LPT')
        for number in '123456789\u00b9\u00b2\u00b3'}
    if (not value or '\\' in value or any(
            not part or part in ('.', '..') or part[-1] in ' .'
            or any(ord(char) < 32 or char in '<>:"|?*' for char in part)
            or part.split('.', 1)[0].upper() in devices for part in parts)):
        raise ValueError('Unsafe Windows ZIP member: ' + repr(name))
    return tuple(parts)


def configuration(source):
    text = (source / 'config_host.mk').read_text(encoding='utf-8')
    def setting(name):
        matches = re.findall(r'^export ' + re.escape(name) + r'=([^\r\n]*)$', text, re.MULTILINE)
        if len(matches) != 1:
            raise ValueError('Expected one configured ' + name)
        return matches[0]
    product = setting('PRODUCTNAME_WITHOUT_SPACES')
    if product not in ('LibreOffice', 'LibreOfficeDev'):
        raise ValueError('Unexpected source-built distribution product')
    version = '.'.join(setting('LIBO_VERSION_' + name) for name in ('MAJOR', 'MINOR', 'MICRO', 'PATCH'))
    suffix = setting('LIBO_VERSION_SUFFIX')
    if not re.fullmatch(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}', version) or not re.fullmatch(r'[A-Za-z0-9.-]*', suffix):
        raise ValueError('Unexpected source-built distribution version')
    return product, version + suffix


def archive_members(archive):
    rows = []
    names = {}
    for info in archive.infolist():
        parts = safe_member(info.filename)
        mode = stat.S_IFMT(info.external_attr >> 16)
        if mode not in (0, stat.S_IFREG, stat.S_IFDIR) or info.flag_bits & 1:
            raise ValueError('ZIP links or special files are forbidden: ' + info.filename)
        key = '/'.join(parts).casefold()
        if key in names:
            raise ValueError('case-insensitive ZIP collision: ' + info.filename)
        names[key] = info.is_dir()
        rows.append((info, parts))
    for key in names:
        for parent in Path(key).parents:
            parent_key = parent.as_posix()
            if parent_key in names and not names[parent_key]:
                raise ValueError('ZIP file/directory collision: ' + key)
    return rows


def retain_developer_marker(source, evidence):
    path = source / 'instdir/program/avmedialo.dll'
    row = {'path': str(path), 'status': 'absent', 'qualificationEvidence': False}
    if not os.path.lexists(path):
        return row
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode):
        row['status'] = 'not-regular'
        return row
    row.update(status='observed', bytes=metadata.st_size, sha256=sha256_file(path))
    with path.open('rb') as stream:
        data = stream.read(4097)
    row['prefixBase64'] = base64.b64encode(data[:64]).decode('ascii')
    if len(data) <= 4096:
        sample = evidence / 'developer-avmedialo.sample'
        with sample.open('xb') as stream:
            stream.write(data)
        row['samplePath'] = str(sample)
    return row


def stage_runtime(source_root, destination, evidence_directory):
    source, destination, evidence = map(Path, (source_root, destination, evidence_directory))
    receipt = evidence / 'installed-runtime-stage.json'
    if receipt.exists():
        raise FileExistsError('Installed runtime stage receipt already exists')
    record = {'schemaVersion': 1, 'kind': 'source-built-installed-runtime-stage',
              'passed': False, 'runtimeRoot': str(destination),
              'requiredHelpLanguages': list(HELP_LANGUAGES), 'archiveCandidates': [],
              'archives': [], 'files': [], 'identicalCollisions': [],
              'omittedMainMembers': [], 'omittedHelpMembers': [],
              'scope': 'Archive assembly only; original PE/CRT/Base qualification remains required.'}
    opened = []
    try:
        if os.path.lexists(destination):
            raise FileExistsError('Installed runtime destination already exists')
        record['developerMergedMarker'] = retain_developer_marker(source, evidence)
        product, version = configuration(source)
        installation = source / 'workdir/installation'
        roots = {role: installation / name / 'archive/install' for role, name in (
            ('main', product), ('help', product + '_helppack'))}
        candidates = {role: sorted(root.rglob('*.zip')) if root.is_dir() else []
                      for role, root in roots.items()}
        for role in ('main', 'help'):
            for path in candidates[role]:
                record['archiveCandidates'].append({'kind': role, 'path': str(path),
                    'bytes': path.stat().st_size, 'sha256': sha256_file(path)})
        if len(candidates['main']) != 1:
            raise ValueError('Expected a unique main archive from the completed source build')
        main = candidates['main'][0]
        prefix = re.escape(product + '_' + version + '_Win_aarch64_archive')
        if not re.fullmatch(prefix + r'(?:_[A-Za-z0-9_-]+)?\.zip', main.name) or '_helppack_' in main.name or '_sdk' in main.name:
            raise ValueError('Unexpected main archive identity: ' + main.name)
        selected = [('main', None, main)]
        for language in HELP_LANGUAGES:
            matches = [path for path in candidates['help'] if path.parent.name == language]
            if len(matches) != 1:
                raise ValueError('Expected a unique ' + language + ' help archive')
            path = matches[0]
            if path.name != product + '_' + version + '_Win_aarch64_archive_helppack_' + language + '.zip':
                raise ValueError('Unexpected help archive identity: ' + path.name)
            selected.append(('help', language, path))
        record['configuredProduct'] = product
        record['configuredVersion'] = version
        record['mainLanguageDirectory'] = main.parent.name
        plans = []
        for role, language, path in selected:
            archive = zipfile.ZipFile(path)
            opened.append(archive)
            rows = archive_members(archive)
            files = [(info, parts) for info, parts in rows if not info.is_dir()]
            if role == 'main':
                runtime_roots = {parts[:-2] for _, parts in files if parts[-2:] == ('program', 'soffice.bin')}
                if len(runtime_roots) != 1:
                    raise ValueError('Expected a unique runtime root in main archive')
                root = runtime_roots.pop()
                paths = {'/'.join(parts[len(root):]) for _, parts in files if parts[:len(root)] == root}
                for name in REQUIRED_NATIVE_OUTPUTS:
                    if name not in paths:
                        raise ValueError('Installed main archive lacks required native output: ' + name)
            else:
                runtime_roots = {parts[:index] for _, parts in files
                                 for index, part in enumerate(parts[:-2])
                                 if part == 'help' and parts[index + 1] == language}
                if len(runtime_roots) != 1:
                    raise ValueError('Expected a unique ' + language + ' help runtime root')
                root = runtime_roots.pop()
            descriptor = next(row.copy() for row in record['archiveCandidates'] if row['path'] == str(path))
            descriptor.update(language=language, wrapperRoot='/'.join(root), memberCount=len(files))
            record['archives'].append(descriptor)
            plans.append((archive, files, root, role, str(path)))
        destination.mkdir()
        staged = {}
        for archive, files, root, role, archive_path in plans:
            for info, parts in files:
                under_root = parts[:len(root)] == root
                relative = parts[len(root):] if under_root else ()
                include = bool(relative) and (role == 'main' or relative[0] == 'help')
                row = {'archivePath': archive_path, 'archiveMember': info.filename,
                       'bytes': info.file_size}
                digest = hashlib.sha256()
                if not include:
                    with archive.open(info) as stream:
                        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                            digest.update(chunk)
                    row['sha256'] = digest.hexdigest()
                    record['omittedMainMembers' if role == 'main' else 'omittedHelpMembers'].append(row)
                    continue
                name = '/'.join(relative)
                row['path'] = name
                key = name.casefold()
                existing = staged.get(key)
                target = destination.joinpath(*relative)
                if existing:
                    with archive.open(info) as stream:
                        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                            digest.update(chunk)
                    row['sha256'] = digest.hexdigest()
                    if existing['path'] != name or existing['sha256'] != row['sha256'] or existing['bytes'] != row['bytes']:
                        raise ValueError('Differing installed archive overlap: ' + name)
                    row['identicalToArchive'] = existing['archivePath']
                    record['identicalCollisions'].append(row)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info) as stream, target.open('xb') as output:
                        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                            digest.update(chunk)
                            output.write(chunk)
                    row['sha256'] = digest.hexdigest()
                    staged[key] = row
                    record['files'].append(row)
        record['fileCount'] = len(record['files'])
        record['passed'] = True
    except Exception as error:
        record['error'] = type(error).__name__ + ': ' + str(error)
        raise
    finally:
        for archive in reversed(opened):
            archive.close()
        with receipt.open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(record, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--evidence-directory', type=Path, required=True)
    args = parser.parse_args()
    record = stage_runtime(args.source_root, args.destination, args.evidence_directory)
    receipt = args.evidence_directory / 'installed-runtime-stage.json'
    print(json.dumps({'runtimeRoot': str(args.destination), 'passed': record['passed'],
        'fileCount': record['fileCount'], 'archiveCount': len(record['archives']),
        'requiredHelpLanguages': record['requiredHelpLanguages'],
        'receipt': {'path': str(receipt), 'bytes': receipt.stat().st_size, 'sha256': sha256_file(receipt)}}))


if __name__ == '__main__':
    main()
