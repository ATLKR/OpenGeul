"""Repackage a successful public GitHub release for the reserved Store product.

Run on a disposable Windows runner through .github/workflows/store-package.yml.
Checksums and complete MSIX/portable parity prove byte equality; the successful
source run proves its recorded gates passed. This does not certify or sign it.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import zipfile

from buildkit import manifest, package_version, validate_identity
from releasekit import REPOSITORY, verify_msix
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'e2e'))
from prepare_payload import PACKAGING_ONLY, inventory, prepare, safe_name, stream_hash, verify_checksums

STORE_IDENTITY = {'name': '57904TaewonLiodLim.OpenGeul',
                  'publisher': 'CN=D7EE05D6-C091-4FB1-BAF9-DA4E6852DA97',
                  'displayName': 'Taewon "Liod" Lim'}
STORE_APP_ID = '9PJH0T3PHRMF'
REQUIRED_JOBS = {'preflight', 'wasm', 'build', 'release', 'msix-install',
                 'native-e2e (windows-2022)', 'native-e2e (windows-2025)',
                 'virtual-print (windows-2022)', 'virtual-print (windows-2025)',
                 'browser-e2e (chromium)', 'browser-e2e (firefox)', 'browser-e2e (webkit)'}


def github(path, *, pages=False):
    command = ['gh', 'api', f'repos/{REPOSITORY}/{path}']
    if pages: command += ['--paginate', '--slurp']
    return json.loads(subprocess.check_output(command, text=True, encoding='utf-8'))


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
    passed = {job['name'] for job in jobs if job.get('conclusion') == 'success'}
    if not REQUIRED_JOBS <= passed:
        raise ValueError('Required source release gates did not all succeed')


def verify_repackage(source, store, version):
    verify_msix(store)
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(store) as repackaged:
        before, after = inventory(original), inventory(repackaged)
        expected_manifest = manifest(validate_identity(STORE_IDENTITY, store=True), version).encode('utf-8')
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


def build(tag, makeappx, output):
    if not re.fullmatch(r'v[1-9][0-9]*\.[0-9]+\.[0-9]+(?:-dev\.[1-9][0-9]*\.[1-9][0-9]*)?', tag):
        raise ValueError('Select an existing OpenGeul version or development release tag')
    if os.name != 'nt': raise ValueError('MakeAppx repackaging requires Windows')
    source = Path('.work/store-source')
    payload = Path('.work/store-payload')
    if any(path.exists() or path.is_symlink() for path in (source, payload, output)):
        raise ValueError('Refusing to overwrite existing source, payload or Store outputs')
    release = github(f'releases/tags/{tag}')
    assets = release.get('assets', [])
    if release.get('draft') is not False or release.get('tag_name') != tag or not 1 <= len(assets) <= 64:
        raise ValueError('Expected an existing published OpenGeul release')
    if sum(asset['size'] for asset in assets) > 96 * 1024 * 1024:
        raise ValueError('Source release exceeds the existing 96 MiB package limit')
    for asset in assets:
        if safe_name(asset['name']) != asset['name'] or '/' in asset['name']:
            raise ValueError('Release asset name must be a safe basename')
    subprocess.run(['gh', 'release', 'download', tag, '--repo', REPOSITORY, '--dir', str(source)], check=True)
    verify_checksums(source)
    provenance = json.loads((source / 'provenance.json').read_text(encoding='utf-8'))
    run_id = str(provenance.get('runId', ''))
    if not re.fullmatch(r'[1-9][0-9]{0,19}', run_id): raise ValueError('Invalid source run ID')
    run = github(f'actions/runs/{run_id}')
    jobs = [job for page in github(f'actions/runs/{run_id}/jobs?per_page=100', pages=True) for job in page['jobs']]
    authorize_release(tag, provenance, run, github(f'commits/{tag}')['sha'], jobs)
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
    parser.add_argument('--makeappx', required=True, type=Path)
    parser.add_argument('--output', type=Path, default=Path('store-output'))
    args = parser.parse_args()
    build(args.release_tag, args.makeappx, args.output)
