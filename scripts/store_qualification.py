"""Store x64/ARM64 원본과 같은 실행의 실제 설치·전체 WACK 증거를 연결한다.

외부 요청/제출을 하지 않는다. 원본 체크섬을 먼저 검증하고 증거 hash만 append한다.
실제 Actions 같은 실행의 성공 gate와 canonical 제출 허가는 외부 제출기가 재확인한다.
"""
from __future__ import annotations
import argparse
import hashlib
import itertools
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'e2e'))
from buildkit import manifest, package_version
from prepare_payload import PACKAGING_ONLY, inventory, stream_hash, verify_checksums
from releasekit import verify_msix
from release_pair import ARCHES, _check_wack, _copy, _fresh, _separate, basename, budget, digest, encoded, read_json, require, verify_pair, source_fingerprint
from store_package import STORE_IDENTITY
from windows_arch import machine_for, require_architecture
from windows_components import identity, regular, sha
from mcp_qualification import verify as verify_mcp

STORE_CAP = 96 * 1024 * 1024
RAW_CAP = 16 * 1024 * 1024
RAW = ('install.json', 'wack.xml', 'wack.json', 'wack-context.json', 'installed-launch.json', 'installed-cli.json')
DETAIL_KEYS = {'formatVersion','storeAppId','identity','version','sourceRelease','sourceReleaseId','sourceCommit','sourceRunId','sourceRunAttempt','sourceAssetFingerprintSha256','repackageCommit','repackageRunId','architectures','unsigned','storeCertified'}


def _context(details, env):
    current = identity(os.environ if env is None else env)
    require(details['repackageCommit'] == current['commit'] and details['repackageRunId'] == current['runId'], '현재 Store 실행과 다른 원본')
    return current


def _fingerprint(directory):
    return hashlib.sha256(encoded([{'name': p.name, 'size': p.stat().st_size, 'sha256': sha(p)} for p in sorted(directory.iterdir())])).hexdigest()


def _store(directory, env):
    paths=list(itertools.islice(directory.iterdir(),65));require(len(paths)<=64,'Store 원본 파일 수 한도 초과')
    budget(paths, STORE_CAP); verify_checksums(directory)
    details = read_json(directory / 'store-provenance.json')
    require(set(details) == DETAIL_KEYS and type(details['formatVersion']) is int and details['formatVersion'] == 2, '두 Store 아키텍처 provenance 필요')
    require(details['storeAppId'] == '9PJH0T3PHRMF' and details['identity'] == STORE_IDENTITY and details['unsigned'] is True and details['storeCertified'] is False, '예약 Store 신원/unsigned 불일치')
    current = _context(details, env)
    source = read_json(directory / 'source-provenance.json')
    require(source.get('formatVersion') == 2 and source.get('repository') == 'ATLKR/OpenGeul' and all(details[d] == source[s] for d,s in [('sourceCommit','commit'),('sourceRunId','runId'),('sourceRunAttempt','runAttempt'),('version','version')]), 'Source 쌍과 Store 출처 불일치')
    require(type(details['sourceReleaseId']) is int and details['sourceReleaseId'] > 0 and digest(details['sourceAssetFingerprintSha256']) == details['sourceAssetFingerprintSha256'], 'Source release/fingerprint 불일치')
    base = 'https://github.com/ATLKR/OpenGeul/releases/tag/v' + details['version']
    attempt = details['sourceRunAttempt']; url = details['sourceRelease']
    require(isinstance(attempt, str) and re.fullmatch(r'[1-9][0-9]{0,19}', attempt), '정확한 Source attempt 필요')
    # dev.N의 N은 run_number다. GET 원본 다운로드의 authorize_release가 실제 API 번호를 검증한다.
    require(isinstance(url, str) and (url == base or re.fullmatch(re.escape(base) + r'-dev\.[1-9][0-9]{0,19}\.' + re.escape(attempt), url)), '정확한 Source 태그 URL 필요')
    require(isinstance(details['architectures'], dict) and set(details['architectures']) == set(ARCHES), '두 Store 아키텍처 필요')
    names = {'source-provenance.json','store-provenance.json','SHA256SUMS.txt'}
    for arch in ARCHES:
        entry = details['architectures'][arch]
        require(isinstance(entry, dict) and set(entry) == {'sourceMsix','sourceMsixSha256','package','sha256','manifest','runtimeSha256'}, '아키텍처 Store record 불일치')
        expected_package = f'OpenGeul_{package_version(details["version"])}_{arch}_store-unsigned.msix'
        require(entry['package'] == expected_package and entry['manifest'] == 'AppxManifest-' + arch + '.xml', 'Store 원본 파일명/아키텍처 불일치')
        original = source['architectures'][arch]['provenance']
        require(entry['sourceMsix'] == original['package'] and entry['sourceMsixSha256'] == original['sha256'], '원본 Source MSIX 불일치')
        names.update((entry['package'], entry['manifest']))
        actual = verify_msix(directory / entry['package'], architecture=arch)
        require(actual['sha256'] == entry['sha256'], 'Store MSIX 해시 불일치')
        expected_manifest = manifest(STORE_IDENTITY, details['version'], arch).encode('utf-8')
        with zipfile.ZipFile(directory / entry['package']) as archive:
            members = inventory(archive)
            require(archive.read('AppxManifest.xml') == expected_manifest == (directory / entry['manifest']).read_bytes(), '실제 Store MSIX manifest 신원 불일치')
            hashes = {}
            for name, member in members.items():
                if name in PACKAGING_ONLY or name == 'AppxManifest.xml': continue
                with archive.open(member) as stream: hashes[name] = stream_hash(stream)
            require(hashes == entry['runtimeSha256'], '실제 Store runtime map 불일치')
    actual_names = {p.name for p in directory.iterdir()}
    screenshots = {'OpenGeul-editor.png','screenshot-provenance.json'}
    require(actual_names in (names, names | screenshots), '알 수 없는/누락 Store 원본')
    if screenshots <= actual_names:
        screenshot = read_json(directory / 'screenshot-provenance.json')
        require(screenshot.get('sourceCommit') == details['sourceCommit'] and screenshot.get('runId') == current['runId'] and screenshot.get('executableSha256') == details['architectures']['x64']['runtimeSha256']['OpenGeul.exe'], '현재 x64 Store 화면 provenance 불일치')
    return details, current


def _package_identity(details, arch):
    return {'Name': STORE_IDENTITY['name'], 'Publisher': STORE_IDENTITY['publisher'], 'Version': package_version(details['version']), 'ProcessorArchitecture': arch}


def _native(evidence, details, current, arch):
    launch = read_json(evidence / 'installed-launch.json'); cli = read_json(evidence / 'installed-cli.json')
    installation = read_json(evidence / 'install.json'); full_name = installation['packageFullName']
    require(set(installation.get('fileTypes', [])) == {'.hwp','.hwpx'}, '등록된 HWP/HWPX 연결 증거 필요')
    helper = ROOT / 'e2e/native_architecture.py'; regular(helper); helper_sha = sha(helper)
    machine = machine_for(arch); records = []
    with zipfile.ZipFile(Path(details['_directory']) / details['architectures'][arch]['package']) as package:
        for proof, runtime in ((launch,'OpenGeul.exe'),(cli,'Tools/rhwp.exe')):
            require(proof.get('success') is True and proof.get('packageFullName') == full_name, '설치된 실제 process package 신원 불일치')
            native = proof.get('nativeArchitecture')
            require(isinstance(native, dict) and native.get('architecture') == arch and native.get('native') is True, '실제 native 제품 관측 필요')
            for key, expected in (('peMachine',machine),('processMachine',0),('nativeMachine',machine)):
                require(type(native.get(key)) is int and native[key] == expected, '제품 PE/WOW/native machine 불일치')
            require(type(native.get('processId')) is int and native['processId'] > 0 and native.get('packageFullName') == full_name, '실제 product PID/package 신원 필요')
            require(native.get('sourceCommit') == current['commit'] and native.get('sourceRun') == current['runId'] and native.get('runAttempt') == current['runAttempt'] and native.get('helperSha256') == helper_sha, '다른 실행/helper의 native 관측')
            require(native.get('sha256') == details['architectures'][arch]['runtimeSha256'][runtime] and type(native.get('bytes')) is int and native['bytes'] == package.getinfo(runtime).file_size, '실제 native executable bytes 불일치')
            image = PureWindowsPath(native.get('imagePath',''))
            require(image.is_absolute() and tuple(p.lower() for p in image.parts[-len(PureWindowsPath(runtime).parts)-1:]) == tuple(p.lower() for p in (full_name,*PureWindowsPath(runtime).parts)), '실제 설치 executable 경로 불일치')
            require(type(native.get('runningAtInspection')) is bool, 'process 생존 관측 형식 불일치')
            records.append(native)
    gui = records[0]
    require(launch.get('architecture') == arch and launch.get('processId') == gui['processId'] and launch.get('executable') == gui['imagePath'] and gui['runningAtInspection'] is True, '실제 owned GUI가 검사 중 종료됐거나 다른 PID임')
    require(type(cli.get('exitCode')) is int and cli['exitCode'] == 0 and type(cli.get('helpBytes')) is int and 0 < cli['helpBytes'] <= 1024*1024 and digest(cli.get('helpSha256')), 'native CLI 정상 종료/help 증거 필요')
    for record in (installation, cli):
        proof = verify_mcp(record.get('mcp'), arch, details['architectures'][arch]['runtimeSha256']['Tools/rhwp.exe'],
            full_name, current['commit'], current['runId'], current['runAttempt'])
        require(proof['serverNativeArchitecture']['bytes'] == records[1]['bytes'], 'MCP 실제 CLI 크기가 Store 원본과 다름')
    require(encoded(installation['mcp']) == encoded(cli['mcp']), '설치/MSIX와 CLI의 MCP 증명이 서로 다름')
    web = gui.get('webview2Native')
    require(isinstance(web, dict) and web.get('rootProcessId') == gui['processId'] and web.get('architecture') == arch and web.get('helperSha256') == helper_sha, 'GUI가 소유한 native WebView2 증거 필요')
    processes = web.get('processes')
    require(isinstance(processes, list) and 1 <= len(processes) <= 64, 'bounded WebView2 process 관측 필요')
    parents = {}
    for row in processes:
        pid = row.get('processId'); parent = row.get('parentProcessId')
        require(type(pid) is int and pid > 0 and pid not in parents and type(parent) is int and parent > 0, 'WebView2 PID/부모 형식 불일치')
        require(all(type(row.get(k)) is int and row[k] == v for k,v in [('peMachine',machine),('processMachine',0),('nativeMachine',machine)]) and row.get('runningAtInspection') is True, 'native WebView2가 아니거나 종료됨')
        require(type(row.get('bytes')) is int and row['bytes'] > 0 and digest(row.get('sha256')) and PureWindowsPath(row.get('imagePath','')).name.lower() == 'msedgewebview2.exe', '실제 WebView2 image/hash 불일치')
        parents[pid] = parent
    for pid in parents:
        seen = set()
        while pid != gui['processId']:
            require(pid in parents and pid not in seen, 'WebView2가 owned GUI의 자손이 아님')
            seen.add(pid); pid = parents[pid]


def _proof(details, current, arch, evidence):
    paths = [evidence / name for name in RAW]; budget(paths, RAW_CAP)
    _check_wack(evidence, _package_identity(details, arch), details['architectures'][arch]['sha256'], arch)
    _native(evidence, details, current, arch)
    names = {name: Path(name).stem + '-' + arch + Path(name).suffix for name in RAW}
    raw = {names[name]: {'size': (evidence / name).stat().st_size, 'sha256': sha(evidence / name)} for name in RAW}
    return names, raw


def select(architecture, directory, output, *, env=None):
    require_architecture(architecture); _fresh(output); _separate(output, directory)
    details, _ = _store(directory, env); entry = details['architectures'][architecture]
    output.parent.mkdir(parents=True,exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='opengeul-store-select-', dir=output.parent))
    try:
        _copy(directory / entry['package'], stage / entry['package'], entry['sha256'])
        _copy(directory / entry['manifest'], stage / 'AppxManifest.xml', sha(directory / entry['manifest']))
        _fresh(output); stage.rename(output)
    finally:
        if stage.exists(): shutil.rmtree(stage)


def collect(architecture, directory, evidence, output, *, env=None):
    require_architecture(architecture); _fresh(output); _separate(output, directory, evidence)
    details, current = _store(directory, env)
    require((os.environ if env is None else env).get('GITHUB_JOB') == 'store-wack', 'Store WACK job 원본 관측만 허용')
    details['_directory'] = str(directory)
    names, raw = _proof(details, current, architecture, evidence)
    receipt = {'formatVersion': 1, 'architecture': architecture, 'repository': current['repository'],
        'sourceCommit': details['sourceCommit'], 'sourceRunId': details['sourceRunId'], 'sourceRunAttempt': details['sourceRunAttempt'],
        'sourceReleaseId': details['sourceReleaseId'], 'sourceAssetFingerprintSha256': details['sourceAssetFingerprintSha256'],
        'repackageCommit': current['commit'], 'repackageRunId': current['runId'], 'storeRunAttempt': current['runAttempt'],
        'originalStoreFingerprintSha256': _fingerprint(directory), 'originalMsix': details['architectures'][architecture]['package'],
        'originalChecksumsSha256': sha(directory / 'SHA256SUMS.txt'), 'originalChecksumsBytes': (directory / 'SHA256SUMS.txt').stat().st_size,
        'originalMsixSha256': details['architectures'][architecture]['sha256'], 'fullWackPassed': True,
        'raw': raw, 'storeCertified': False}
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.opengeul-store-proof-', dir=output.parent))
    try:
        for original, flat in names.items(): _copy(evidence / original, stage / flat, raw[flat]['sha256'])
        (stage / 'qualification.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        _fresh(output); stage.rename(output)
    finally:
        if stage.exists(): shutil.rmtree(stage)
    return receipt


def verify(directory, source_directory, x64, arm64, *, env=None):
    details, current = _store(directory, env)
    source = verify_pair(source_directory)
    require(source == read_json(directory / 'source-provenance.json') and source_fingerprint(source_directory) == details['sourceAssetFingerprintSha256'], '실제 원본 Source22가 다름')
    from store_package import verify_repackage
    fingerprint = _fingerprint(directory); receipts = {}; additions = {}
    with tempfile.TemporaryDirectory(prefix='opengeul-store-proof-check-') as temporary:
        for arch, supplied in (('x64',x64),('arm64',arm64)):
            require(supplied.is_dir() and not supplied.is_symlink(), '두 Store WACK 원본 proof가 필요함')
            receipt = read_json(supplied / 'qualification.json')
            require(receipt.get('formatVersion') == 1 and receipt.get('architecture') == arch and receipt.get('originalStoreFingerprintSha256') == fingerprint, '다른 Store 원본 proof')
            require(type(receipt.get('formatVersion')) is int and receipt.get('fullWackPassed') is True and receipt.get('storeCertified') is False
                and receipt.get('originalChecksumsSha256') == sha(directory / 'SHA256SUMS.txt') and receipt.get('originalChecksumsBytes') == (directory / 'SHA256SUMS.txt').stat().st_size
                and receipt.get('originalMsix') == details['architectures'][arch]['package'] and receipt.get('originalMsixSha256') == details['architectures'][arch]['sha256'], '원본 checksum/MSIX/전체 PASS receipt 불일치')
            for key in ('sourceCommit','sourceRunId','sourceRunAttempt','sourceReleaseId','sourceAssetFingerprintSha256'):
                require(receipt.get(key) == details[key], '다른 Source의 Store WACK proof')
            require(receipt.get('repackageCommit') == current['commit'] and receipt.get('repackageRunId') == current['runId'] and receipt.get('storeRunAttempt') == current['runAttempt'] and receipt.get('repository') == current['repository'], '다른 Store 실행/시도의 proof')
            raw = receipt.get('raw'); require(isinstance(raw,dict) and len(raw) == 6, 'raw6 원본 proof 필요')
            wack = Path(temporary) / ('wack-' + arch); wack.mkdir()
            expected_names = {Path(n).stem + '-' + arch + Path(n).suffix for n in RAW}
            require(set(raw) == expected_names and {p.name for p in supplied.iterdir()} == expected_names | {'qualification.json'}, '알 수 없는/누락 raw6 proof')
            for name in RAW:
                flat = Path(name).stem + '-' + arch + Path(name).suffix; item = raw[flat]
                require(set(item) == {'size','sha256'} and type(item['size']) is int and item['size'] == (supplied / flat).stat().st_size and item['sha256'] == sha(supplied / flat), '수집 뒤 raw proof 변조')
                _copy(supplied / flat, wack / name, item['sha256']); additions[flat] = (supplied / flat,item['sha256'])
            details['_directory'] = str(directory); _proof(details,current,arch,wack)
            source_msix = source_directory / details['architectures'][arch]['sourceMsix']
            require(sha(source_msix) == details['architectures'][arch]['sourceMsixSha256'], '실제 Source MSIX hash 불일치')
            verify_repackage(source_msix,directory / details['architectures'][arch]['package'],details['version'],architecture=arch)
            receipts[arch] = receipt
    require(len(additions) == 12, '두 Store architecture raw12 필요')
    result = {'formatVersion':1,'repository':current['repository'], **{key:details[key] for key in ('sourceCommit','sourceRunId','sourceRunAttempt','sourceReleaseId','sourceAssetFingerprintSha256')},
        'repackageCommit':current['commit'],'repackageRunId':current['runId'],'storeRunAttempt':current['runAttempt'],
        'originalStoreFingerprintSha256':fingerprint,'architectures':receipts,'storeCertified':False,
        'originalChecksumsSha256':sha(directory / 'SHA256SUMS.txt'),'originalChecksumsBytes':(directory / 'SHA256SUMS.txt').stat().st_size,
        'scope':'실제 Store 신원 설치/native process와 전체 WACK PASS; Microsoft Store 승인/제출은 별도'}
    original_sums = (directory / 'SHA256SUMS.txt').read_bytes()
    require(original_sums.endswith(b'\n'), '원본 checksum 끝의 개행이 필요함')
    require(not (directory / 'store-qualification.json').exists() and all(not (directory / n).exists() for n in additions), '기존 qualification 덮어쓰기 거부')
    new_json = (json.dumps(result,ensure_ascii=False,indent=2)+'\n').encode()
    budget(list(directory.iterdir()) + [p for p,_ in additions.values()], STORE_CAP)
    require(sum(p.stat().st_size for p in directory.iterdir()) + sum(p.stat().st_size for p,_ in additions.values()) + len(new_json) + 4096 <= STORE_CAP,'qualification 후 Store96MiB 초과')
    written = []
    try:
        for name,(source_path,expected_sha) in additions.items():
            written.append(directory / name); _copy(source_path,directory / name,expected_sha)
        target = directory / 'store-qualification.json'; target.write_bytes(new_json); written.append(target)
        appended = ''.join(sha(p) + '  ' + p.name + '\n' for p in sorted(written)).encode()
        (directory / 'SHA256SUMS.txt').write_bytes(original_sums + appended)
        verify_checksums(directory); budget(list(directory.iterdir()),STORE_CAP)
    except Exception:
        (directory / 'SHA256SUMS.txt').write_bytes(original_sums)
        for p in written:
            if p.exists(): p.unlink()
        raise
    return result


def inspect_qualified(directory, source_directory, *, env=None):
    """제출 전 원본 prefix를 임시 복원해 actual raw/native/source를 재검증한다. 입력 쓰기 없음."""
    paths=list(itertools.islice(directory.iterdir(),65));require(len(paths)<=64,'qualified Store 파일 수 한도 초과')
    budget(paths, STORE_CAP);verify_checksums(directory)
    retained = read_json(directory / 'store-qualification.json')
    require(type(retained.get('formatVersion')) is int and retained['formatVersion'] == 1 and set(retained.get('architectures', {})) == set(ARCHES), 'qualification 공통 형식 불일치')
    length = retained.get('originalChecksumsBytes')
    require(type(length) is int and 0 < length <= 64*1024, '원본 checksum prefix 크기 불일치')
    prefix = (directory / 'SHA256SUMS.txt').read_bytes()[:length]
    require(hashlib.sha256(prefix).hexdigest() == retained.get('originalChecksumsSha256') and prefix.endswith(b'\n'), '원본 checksum prefix 불일치')
    with tempfile.TemporaryDirectory(prefix='opengeul-store-qualified-reader-') as temporary:
        base = Path(temporary); seed = base / 'store'; seed.mkdir(); proofs = {}
        names = {'SHA256SUMS.txt'}
        for line in prefix.decode('utf-8').splitlines():
            words = line.split('  ',1); require(len(words) == 2 and digest(words[0]), '원본 checksum record 불일치')
            name = basename(words[1]); require(name not in names, '원본 checksum 중복')
            _copy(directory / name,seed / name,words[0]); names.add(name)
        (seed / 'SHA256SUMS.txt').write_bytes(prefix)
        expected = set(names) | {'store-qualification.json'}
        for arch in ARCHES:
            proof = retained['architectures'][arch]; folder = base / arch; folder.mkdir(); proofs[arch] = folder
            for name,item in proof['raw'].items():
                basename(name); require(name not in expected, '중복 qualification raw 파일')
                _copy(directory / name,folder / name,item['sha256']); expected.add(name)
            (folder / 'qualification.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        require(expected == {p.name for p in directory.iterdir()}, '알 수 없는 qualified Store 파일')
        actual = verify(seed,source_directory,proofs['x64'],proofs['arm64'],env=env)
        require(actual == retained, 'actual raw/source 재검증 결과와 qualification receipt 불일치')
    return retained


def main():
    parser = argparse.ArgumentParser(description=__doc__); commands = parser.add_subparsers(dest='command',required=True)
    for name in ('select','collect'):
        p=commands.add_parser(name);p.add_argument('--architecture',choices=ARCHES,required=True);p.add_argument('--directory',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
        if name=='collect':p.add_argument('--evidence',type=Path,required=True)
    p=commands.add_parser('verify');p.add_argument('--directory',type=Path,required=True);p.add_argument('--source-directory',type=Path,required=True);p.add_argument('--x64',type=Path,required=True);p.add_argument('--arm64',type=Path,required=True)
    args=parser.parse_args()
    if args.command=='select':select(args.architecture,args.directory,args.output)
    elif args.command=='collect':collect(args.architecture,args.directory,args.evidence,args.output)
    else:verify(args.directory,args.source_directory,args.x64,args.arm64)
    print('검증된 Store 신원 원본/설치/전체 WACK 증거를 처리했습니다. Store 제출·승인은 아닙니다.')


if __name__=='__main__':main()
