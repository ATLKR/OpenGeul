"""Preserve validated GitHub releases and repackage them for the Store product.

Source publication follows the full release gates. Windows Store repackaging
requires a completed successful source run and complete MSIX/portable parity.
This does not certify or sign packages.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import zipfile

from buildkit import manifest, package_version, validate_identity
from releasekit import REPOSITORY, release_allowed, release_tag, verify_msix
from windows_arch import require_architecture
from windows_components import _ancestors
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'e2e'))
from prepare_payload import PACKAGING_ONLY, inventory, prepare, safe_name, stream_hash, verify_checksums

STORE_IDENTITY = {'name': '57904TaewonLiodLim.OpenGeul',
                  'publisher': 'CN=D7EE05D6-C091-4FB1-BAF9-DA4E6852DA97',
                  'displayName': 'Allen Taewon Lim'}
STORE_APP_ID = '9PJH0T3PHRMF'
SOURCE_ARCH_LIMIT = 96 * 1024 * 1024
SOURCE_PAIR_LIMIT = 2 * SOURCE_ARCH_LIMIT
STORE_LIMIT = 96 * 1024 * 1024
LEGACY_REQUIRED_JOBS = {'preflight', 'wasm', 'windows-editor', 'windows-cli', 'build', 'release', 'msix-install',
                 'native-e2e (windows-2022)', 'native-e2e (windows-2025)',
                 'virtual-print (windows-2022)', 'virtual-print (windows-2025)',
                 'browser-e2e (chromium)', 'browser-e2e (firefox)', 'browser-e2e (webkit)'}
REQUIRED_JOBS = LEGACY_REQUIRED_JOBS | {
    'windows-editor-arm64', 'windows-cli-arm64', 'build-arm64', 'msix-install-arm64',
    'native-e2e (windows-11-arm)', 'virtual-print (windows-11-arm)'}


def _output_boundary(output, *inputs):
    _ancestors(output)
    target = output.resolve()
    for source in inputs:
        origin = source.resolve()
        if target == origin or target in origin.parents or origin in target.parents:
            raise ValueError('Store output cannot overlap source or runtime inputs')


def _dual_source(provenance):
    if not isinstance(provenance, dict):
        raise ValueError('Source provenance must be an object')
    if 'formatVersion' not in provenance:
        return False
    if type(provenance['formatVersion']) is not int or provenance['formatVersion'] != 2:
        raise ValueError('Unsupported source release architecture protocol')
    return True


def github(path, *, pages=False):
    command = ['gh', 'api', f'repos/{REPOSITORY}/{path}']
    if pages: command += ['--paginate', '--slurp']
    return json.loads(subprocess.check_output(command, text=True, encoding='utf-8', timeout=30))


def wait_for_source_run(run_id, timeout=600):
    if not re.fullmatch(r'[1-9][0-9]{0,19}', str(run_id)):
        raise ValueError('Invalid source run ID')
    deadline = time.monotonic() + timeout
    while True:
        run = github(f'actions/runs/{run_id}')
        if (str(run.get('id')) != str(run_id)
                or run.get('repository', {}).get('full_name') != REPOSITORY
                or run.get('path') != '.github/workflows/msix.yml'):
            raise ValueError('Source completion lookup returned a different run')
        if run.get('status') == 'completed':
            if run.get('conclusion') != 'success':
                raise ValueError('Source release run did not complete successfully')
            return run
        if run.get('status') not in ('queued', 'in_progress', 'waiting', 'pending', 'requested'):
            raise ValueError('Unexpected source completion status')
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError('Timed out waiting for source release completion')
        time.sleep(min(10, remaining))


def _verify_source_release(directory, version):
    verify_checksums(directory)
    provenance = json.loads((directory / 'provenance.json').read_text(encoding='utf-8'))
    if _dual_source(provenance):
        from release_pair import verify_pair
        provenance = verify_pair(directory)
        if (provenance['version'] != version or provenance['repository'] != REPOSITORY
                or provenance['commit'] != os.getenv('GITHUB_SHA')
                or str(provenance['runId']) != os.getenv('GITHUB_RUN_ID')
                or provenance['runAttempt'] != os.getenv('GITHUB_RUN_ATTEMPT')):
            raise ValueError('Source release artifacts do not match the authorized build')
        return provenance
    packages = list(directory.glob('*.msix'))
    if (provenance.get('version') != version or len(packages) != 1
            or provenance.get('repository') != REPOSITORY
            or provenance.get('commit') != os.getenv('GITHUB_SHA')
            or not re.fullmatch(r'[0-9a-f]{40}', provenance.get('commit', ''))
            or str(provenance.get('runId')) != os.getenv('GITHUB_RUN_ID')
            or provenance.get('package') != packages[0].name
            or provenance.get('sha256') != verify_msix(packages[0])['sha256']):
        raise ValueError('Source release artifacts do not match the authorized build')
    if sum(path.stat().st_size for path in directory.iterdir()) > SOURCE_ARCH_LIMIT:
        raise ValueError('Source release exceeds the 96 MiB package limit')
    return provenance


def ensure_source_release(tag, directory):
    if not release_allowed(os.getenv('GITHUB_REPOSITORY', ''), os.getenv('GITHUB_EVENT_NAME', ''),
                           os.getenv('GITHUB_REF', '')):
        raise ValueError('Source release publication is not authorized')
    version = json.loads((Path(__file__).resolve().parents[1] / 'config/product.json').read_text(encoding='utf-8'))['version']
    expected = release_tag(version, os.environ['GITHUB_REF'], os.environ['GITHUB_RUN_NUMBER'],
                           os.environ['GITHUB_RUN_ATTEMPT'])
    if tag != expected:
        raise ValueError('Source release tag does not match the authorized build')
    provenance = _verify_source_release(directory, version)
    paths = sorted(directory.iterdir())
    releases = [item for page in github('releases?per_page=100', pages=True) for item in page
                if item.get('tag_name') == tag]
    if len(releases) > 1:
        raise ValueError('Multiple source releases use the same tag')
    if releases or os.environ['GITHUB_REF'].startswith('refs/tags/'):
        if github(f'commits/{tag}').get('sha') != provenance['commit']:
            raise ValueError('Release tag points to a different source commit')
    if releases:
        release = releases[0]
        assets = release.get('assets', [])
        names = {path.name for path in paths}
        if (release.get('draft') is not False or len(assets) != len(names)
                or any(asset.get('state') != 'uploaded' for asset in assets)
                or {asset.get('name') for asset in assets} != names
                or any(type(asset.get('size')) is not int or asset['size'] < 0 for asset in assets)
                or sum(asset['size'] for asset in assets) > (SOURCE_PAIR_LIMIT if provenance.get('formatVersion') == 2 else SOURCE_ARCH_LIMIT)):
            raise ValueError('Existing release asset inventory does not match this build')
        with tempfile.TemporaryDirectory(prefix='opengeul-release-') as temporary:
            existing = Path(temporary) / 'assets'
            existing.mkdir()
            subprocess.run(['gh', 'release', 'download', tag, '--repo', REPOSITORY,
                            '--dir', str(existing)], check=True, timeout=180)
            original = _verify_source_release(existing, version)
            if (original.get('formatVersion') == 2) != (provenance.get('formatVersion') == 2):
                raise ValueError('Existing release uses another source architecture protocol')
            if original.get('formatVersion') == 2:
                from release_pair import source_fingerprint
                if source_fingerprint(existing) != source_fingerprint(directory):
                    raise ValueError('Existing dual release bytes differ from the currently validated candidate')
            else:
                prepare(existing, Path(temporary) / 'payload')
        print('Original source release verified; existing publication preserved.')
        return False
    subprocess.run(['gh', 'release', 'create', tag, *[str(path) for path in paths],
                    '--repo', REPOSITORY, '--target', provenance['commit'], '--prerelease', '--latest=false',
                    '--title', f'OpenGeul {tag} — 검증을 통과한 서명 없는 Windows 개발판',
                    '--notes-file', 'docs/RELEASE_NOTES.md'], check=True, timeout=180)
    return True


def dispatch_store(tag):
    package_version(tag.removeprefix('v'))
    if (os.getenv('GITHUB_REPOSITORY') != REPOSITORY or os.getenv('GITHUB_EVENT_NAME') != 'push'
            or os.getenv('GITHUB_REF') != 'refs/tags/' + tag
            or not re.fullmatch(r'v[1-9][0-9]*\.[0-9]+\.[0-9]+', tag)):
        raise ValueError('Store dispatch requires an owned explicit stable tag push')
    subprocess.run(['gh', 'workflow', 'run', 'store-package.yml', '--repo', REPOSITORY,
                    '--ref', 'main', '-f', 'release_tag=' + tag, '-f', 'submit_to_store=true'],
                   check=True, timeout=30)


def authorize_release(tag, provenance, run, tag_sha, jobs):
    version = provenance['version']
    package_version(version)
    expected_tags = {'v' + version, f'v{version}-dev.{run["run_number"]}.{run["run_attempt"]}'}
    if (tag not in expected_tags or provenance.get('repository') != REPOSITORY
            or not re.fullmatch(r'[0-9a-f]{40}', provenance.get('commit', ''))
            or provenance['commit'] != tag_sha or run.get('head_sha') != tag_sha
            or str(run.get('id')) != str(provenance.get('runId'))
            or run.get('repository', {}).get('full_name') != REPOSITORY
            or run.get('path') != '.github/workflows/msix.yml'
            or run.get('event') not in ('push', 'workflow_dispatch')
            or run.get('status') != 'completed' or run.get('conclusion') != 'success'):
        raise ValueError('Release provenance does not match a successful owned source run')
    dual = _dual_source(provenance)
    required = REQUIRED_JOBS if dual else LEGACY_REQUIRED_JOBS
    passed = {job['name'] for job in jobs if job.get('conclusion') == 'success'}
    if not required <= passed:
        raise ValueError('Required source release gates did not all succeed')
    if dual:
        raw_attempt = provenance.get('runAttempt')
        if (not isinstance(raw_attempt, str) or not re.fullmatch(r'[1-9][0-9]{0,19}', raw_attempt)
                or type(run.get('run_attempt')) is not int or int(raw_attempt) != run['run_attempt']):
            raise ValueError('Dual source release attempt does not match its qualified run')
        attempt = int(raw_attempt)
        for name in required:
            evidence = [job for job in jobs if job.get('name') == name]
            if (len(evidence) != 1 or evidence[0].get('conclusion') != 'success'
                    or type(evidence[0].get('run_attempt')) is not int or evidence[0]['run_attempt'] != attempt
                    or str(evidence[0].get('run_id')) != str(run['id']) or evidence[0].get('head_sha') != tag_sha):
                raise ValueError('Dual source gate evidence is duplicated or belongs to another source run or attempt')


def verify_repackage(source, store, version, architecture='x64'):
    architecture = require_architecture(architecture)
    verify_msix(source, architecture)
    verify_msix(store, architecture)
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(store) as repackaged:
        before, after = inventory(original), inventory(repackaged)
        expected_manifest = manifest(validate_identity(STORE_IDENTITY, store=True), version, architecture).encode('utf-8')
        if repackaged.read('AppxManifest.xml') != expected_manifest:
            raise ValueError('Store manifest does not match the reserved identity and source version')
        ignored = PACKAGING_ONLY | {'AppxManifest.xml'}
        if set(before) - ignored != set(after) - ignored:
            raise ValueError('Runtime file set changed during Store repackaging')
        digests = {}
        for name in sorted(set(before) - ignored):
            with original.open(before[name]) as stream: digest = stream_hash(stream)
            with repackaged.open(after[name]) as stream:
                if stream_hash(stream) != digest: raise ValueError(f'Runtime bytes changed: {name}')
            digests[name] = digest
        return digests


def _release_assets(tag, release):
    assets = release.get('assets', [])
    if (release.get('draft') is not False or release.get('tag_name') != tag
            or not isinstance(assets, list) or not 1 <= len(assets) <= 64):
        raise ValueError('Expected an existing published OpenGeul release')
    names = set()
    for asset in assets:
        if (not isinstance(asset, dict) or type(asset.get('size')) is not int or asset['size'] < 0
                or not isinstance(asset.get('name'), str) or asset['name'] in names
                or safe_name(asset['name']) != asset['name'] or '/' in asset['name']):
            raise ValueError('Release asset name must be a safe basename')
        names.add(asset['name'])
    if sum(asset['size'] for asset in assets) > SOURCE_PAIR_LIMIT:
        raise ValueError('Source release exceeds the fixed 192 MiB dual package limit')
    return assets


def download_source_release(tag, output):
    """GET/download a qualified dual source; never call publication or Store writes."""
    if (not isinstance(tag, str)
            or not re.fullmatch(r'v[1-9][0-9]*\.[0-9]+\.[0-9]+(?:-dev\.[1-9][0-9]*\.[1-9][0-9]*)?', tag)):
        raise ValueError('Select an explicit owned stable or development source release')
    package_version(tag[1:].split('-dev.', 1)[0])
    _output_boundary(output)
    if output.exists() or output.is_symlink():
        raise ValueError('Refusing to overwrite an existing source download')
    release = github(f'releases/tags/{tag}')
    assets = _release_assets(tag, release)
    if (type(release.get('id')) is not int or release['id'] <= 0
            or release.get('html_url') != f'https://github.com/{REPOSITORY}/releases/tag/{tag}'):
        raise ValueError('Read-only source release identity does not match the owned tag')
    from release_pair import source_fingerprint, verify_pair
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='opengeul-source-read-', dir=output.parent) as temporary:
        stage = Path(temporary) / 'source'; stage.mkdir()
        subprocess.run(['gh', 'release', 'download', tag, '--repo', REPOSITORY, '--dir', str(stage)],
                       check=True, timeout=180)
        if ({path.name for path in stage.iterdir()} != {asset['name'] for asset in assets}
                or any((stage / asset['name']).stat().st_size != asset['size'] for asset in assets)):
            raise ValueError('Downloaded source asset inventory changed')
        provenance = verify_pair(stage)
        run_id = provenance['runId']
        run = wait_for_source_run(run_id)
        jobs = [job for page in github(f'actions/runs/{run_id}/jobs?per_page=100', pages=True) for job in page['jobs']]
        authorize_release(tag, provenance, run, github(f'commits/{tag}')['sha'], jobs)
        fingerprint = source_fingerprint(stage)
        if output.exists() or output.is_symlink():
            raise ValueError('Source output appeared during read-only download')
        _output_boundary(output, stage)
        stage.rename(output)
    return {'sourceReleaseId': release['id'], 'sourceCommit': provenance['commit'], 'sourceRunId': run_id,
            'sourceRunAttempt': provenance['runAttempt'], 'sourceAssetFingerprintSha256': fingerprint,
            'storeWritesPerformed': False}


def _build_pair(source, payload, output, makeappx, release, provenance):
    from release_pair import copy_architecture, source_fingerprint, verify_pair
    if verify_pair(source) != provenance:
        raise ValueError('Dual source provenance changed before Store repackaging')
    fingerprint = source_fingerprint(source)
    version = provenance['version']
    with tempfile.TemporaryDirectory(prefix='opengeul-store-pair-', dir=source.parent) as temporary:
        working = Path(temporary)
        stage = working / 'output'; stage.mkdir()
        architectures = {}
        for architecture in ('x64', 'arm64'):
            restored = working / ('source-' + architecture)
            copy_architecture(source, architecture, restored)
            runtime = payload / architecture
            validated = prepare(restored, runtime, architecture)
            original = restored / validated['msix']
            entry = provenance['architectures'][architecture]
            original_hash = verify_msix(original, architecture)['sha256']
            if original_hash != entry['provenance']['sha256']:
                raise ValueError('Original architecture package changed after source validation')
            store_manifest = manifest(STORE_IDENTITY, version, architecture).encode('utf-8')
            (runtime / 'AppxManifest.xml').write_bytes(store_manifest)
            package = stage / f'OpenGeul_{package_version(version)}_{architecture}_store-unsigned.msix'
            subprocess.run([str(makeappx), 'pack', '/d', str(runtime), '/p', str(package)], check=True)
            digests = verify_repackage(original, package, version, architecture)
            manifest_name = f'AppxManifest-{architecture}.xml'
            (stage / manifest_name).write_bytes(store_manifest)
            architectures[architecture] = {
                'sourceMsix': entry['assets'][validated['msix']], 'sourceMsixSha256': original_hash,
                'package': package.name, 'sha256': verify_msix(package, architecture)['sha256'],
                'manifest': manifest_name, 'runtimeSha256': digests}
        if source_fingerprint(source) != fingerprint:
            raise ValueError('Dual source release bytes changed during Store repackaging')
        details = {'formatVersion': 2, 'storeAppId': STORE_APP_ID, 'identity': STORE_IDENTITY, 'version': version,
                   'sourceRelease': release['html_url'], 'sourceReleaseId': release['id'],
                   'sourceCommit': provenance['commit'], 'sourceRunId': provenance['runId'],
                   'sourceRunAttempt': provenance['runAttempt'], 'sourceAssetFingerprintSha256': fingerprint,
                   'repackageCommit': os.getenv('GITHUB_SHA'), 'repackageRunId': os.getenv('GITHUB_RUN_ID'),
                   'architectures': architectures, 'unsigned': True, 'storeCertified': False}
        (stage / 'source-provenance.json').write_bytes((source / 'provenance.json').read_bytes())
        (stage / 'store-provenance.json').write_text(json.dumps(details, indent=2) + '\n', encoding='utf-8')
        hashes = []
        for path in sorted(stage.iterdir()):
            with path.open('rb') as stream: hashes.append(stream_hash(stream) + '  ' + path.name + '\n')
        (stage / 'SHA256SUMS.txt').write_text(''.join(hashes), encoding='utf-8')
        verify_checksums(stage)
        if sum(path.stat().st_size for path in stage.iterdir()) > STORE_LIMIT:
            raise ValueError('Dual Store outputs exceed the existing 96 MiB package limit')
        if output.exists() or output.is_symlink():
            raise ValueError('Store output appeared during dual repackaging')
        _output_boundary(output, source, payload)
        stage.rename(output)
    print('Verified unchanged x64 and ARM64 runtimes in two unsigned Store packages.')
    if os.getenv('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as stream:
            for architecture, details in architectures.items():
                stream.write(f'package_{architecture}={(output / details["package"]).as_posix()}\n')
            stream.write(f'package={(output / architectures["x64"]["package"]).as_posix()}\n')


def build(tag, makeappx, output):
    if not re.fullmatch(r'v[1-9][0-9]*\.[0-9]+\.[0-9]+(?:-dev\.[1-9][0-9]*\.[1-9][0-9]*)?', tag):
        raise ValueError('Select an existing OpenGeul version or development release tag')
    if os.name != 'nt': raise ValueError('MakeAppx repackaging requires Windows')
    source = Path('.work/store-source')
    payload = Path('.work/store-payload')
    _output_boundary(output, source, payload)
    if any(path.exists() or path.is_symlink() for path in (source, payload, output)):
        raise ValueError('Refusing to overwrite existing source, payload or Store outputs')
    release = github(f'releases/tags/{tag}')
    assets = _release_assets(tag, release)
    subprocess.run(['gh', 'release', 'download', tag, '--repo', REPOSITORY, '--dir', str(source)], check=True)
    verify_checksums(source)
    provenance = json.loads((source / 'provenance.json').read_text(encoding='utf-8'))
    run_id = str(provenance.get('runId', ''))
    if not re.fullmatch(r'[1-9][0-9]{0,19}', run_id): raise ValueError('Invalid source run ID')
    run = wait_for_source_run(run_id)
    jobs = [job for page in github(f'actions/runs/{run_id}/jobs?per_page=100', pages=True) for job in page['jobs']]
    authorize_release(tag, provenance, run, github(f'commits/{tag}')['sha'], jobs)
    if _dual_source(provenance):
        _build_pair(source, payload, output, makeappx, release, provenance)
        return
    if sum(path.stat().st_size for path in source.iterdir()) > SOURCE_ARCH_LIMIT:
        raise ValueError('Historical x64 source release exceeds the 96 MiB package limit')
    validated = prepare(source, payload)
    original = source / validated['msix']
    if provenance.get('package') != original.name or provenance.get('sha256') != verify_msix(original)['sha256']:
        raise ValueError('Original package does not match release provenance')
    version = provenance['version']
    (payload / 'AppxManifest.xml').write_text(manifest(STORE_IDENTITY, version), encoding='utf-8', newline='\n')
    output.mkdir(parents=True)
    package = output / f'OpenGeul_{package_version(version)}_x64_store-unsigned.msix'
    subprocess.run([str(makeappx), 'pack', '/d', str(payload), '/p', str(package)], check=True)
    digests = verify_repackage(original, package, version)
    (output / 'AppxManifest.xml').write_bytes((payload / 'AppxManifest.xml').read_bytes())
    (output / 'source-provenance.json').write_bytes((source / 'provenance.json').read_bytes())
    details = {'storeAppId': STORE_APP_ID, 'identity': STORE_IDENTITY, 'version': version,
               'sourceRelease': release['html_url'], 'sourceReleaseId': release['id'],
               'sourceCommit': provenance['commit'], 'sourceRunId': run_id,
               'sourceMsixSha256': provenance['sha256'], 'repackageCommit': os.getenv('GITHUB_SHA'),
               'repackageRunId': os.getenv('GITHUB_RUN_ID'), 'runtimeSha256': digests,
               'package': package.name, 'sha256': verify_msix(package)['sha256'],
               'unsigned': True, 'storeCertified': False}
    (output / 'store-provenance.json').write_text(json.dumps(details, indent=2) + '\n', encoding='utf-8')
    hashes = []
    for path in sorted(output.iterdir()):
        with path.open('rb') as stream: hashes.append(stream_hash(stream) + '  ' + path.name + '\n')
    (output / 'SHA256SUMS.txt').write_text(''.join(hashes), encoding='utf-8')
    verify_checksums(output)
    print(f'Verified {len(digests)} unchanged runtime files: {package}')
    if os.getenv('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as stream:
            stream.write(f'package={package.as_posix()}\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release-tag', required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--publish-release', action='store_true')
    mode.add_argument('--dispatch-store', action='store_true')
    mode.add_argument('--download-source-release', action='store_true')
    parser.add_argument('--package-directory', type=Path)
    parser.add_argument('--makeappx', type=Path)
    parser.add_argument('--output', type=Path, default=Path('store-output'))
    args = parser.parse_args()
    if args.publish_release:
        if args.package_directory is None: parser.error('--publish-release requires --package-directory')
        ensure_source_release(args.release_tag, args.package_directory)
    elif args.dispatch_store:
        dispatch_store(args.release_tag)
    elif args.download_source_release:
        print(json.dumps(download_source_release(args.release_tag, args.output), sort_keys=True))
    else:
        if args.makeappx is None: parser.error('Store packaging requires --makeappx')
        build(args.release_tag, args.makeappx, args.output)
