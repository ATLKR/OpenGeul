"""같은 소스 실행의 x64/ARM64 원본과 전체 WACK PASS를 22파일로 결합한다.

체크섬은 저자 인증이 아니다. CI/API의 같은 실행 선택·성공 gate는 호출자가 유지한다.
verify_pair는 Store 실행 HEAD를 source HEAD로 오인하지 않으며 입력을 수정하지 않는다.
"""
from __future__ import annotations
import argparse
import contextlib
import hashlib
import io
import itertools
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'e2e'))
from buildkit import DEV_IDENTITY, package_version
from prepare_payload import prepare, safe_name, verify_checksums, stream_hash
from wack_result import inspect
from windows_arch import component_artifact_name, require_architecture
from windows_components import identity, regular, sha, _ancestors

ARCHES = ('x64', 'arm64')
ARCH_LIMIT = 96 * 1024 * 1024
PAIR_LIMIT = 192 * 1024 * 1024
METADATA = ('AppxManifest.xml', 'provenance.json', 'SHA256SUMS.txt', 'rhwp-help.txt')
WACK = {'install': 'install.json', 'report': 'wack.xml', 'summary': 'wack.json', 'context': 'wack-context.json'}
COMMON = ('repository', 'commit', 'runId', 'runAttempt', 'version', 'sourceContractSha256')
PROVENANCE_KEYS = {'unsigned', 'architecture', 'members', 'sha256', 'repository', 'commit', 'runId',
    'version', 'package', 'upstream', 'sourceParity', 'manualWindowsUx', 'storeCertified', 'windowsComponents'}


def require(value, message):
    if not value:
        raise ValueError(message)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def _pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, '중복 JSON 키')
        result[key] = value
    return result


def read_json(path):
    regular(path)
    require(0 < path.stat().st_size <= 512 * 1024, 'JSON 크기 한도 초과')
    value = json.loads(path.read_text(encoding='utf-8-sig'), object_pairs_hook=_pairs)
    require(isinstance(value, dict), 'JSON 객체가 필요함')
    return value


def digest(value):
    require(isinstance(value, str) and re.fullmatch('[0-9a-fA-F]{64}', value), '잘못된 SHA256')
    return value.lower()


def basename(name):
    require(isinstance(name, str) and '/' not in name and '\\' not in name and safe_name(name) == name, '안전한 원본 파일명 필요')
    return name


def budget(paths, cap):
    total = 0
    for path in paths:
        regular(path)
        size = path.stat().st_size
        require(0 <= size <= cap, '원본 파일 크기 한도 초과')
        total += size
    require(total <= cap, '고정 릴리스 바이트 한도 초과')
    return total


def _names(package, provenance):
    package_name = basename(provenance['package'])
    require(package_name.endswith('.msix'), 'MSIX 원본 파일명 필요')
    portable = [p.name for p in package.iterdir() if p.name.endswith('portable.zip')]
    require(len(portable) == 1, 'portable 원본이 정확히 하나 필요함')
    return set(METADATA) | {package_name, basename(portable[0])}


def _flatten(name, arch):
    return Path(name).stem + '-' + arch + Path(name).suffix if name in METADATA else name


def _wack_names(arch):
    return {key: Path(name).stem + '-' + arch + Path(name).suffix for key, name in WACK.items()}


def _publisher_id(publisher):
    bits = ''.join(f'{byte:08b}' for byte in hashlib.sha256(publisher.encode('utf-16le')).digest()[:8]) + '0'
    alphabet = '0123456789abcdefghjkmnpqrstvwxyz'
    return ''.join(alphabet[int(bits[i:i + 5], 2)] for i in range(0, 65, 5))


def _check_wack(folder, package_identity, msix_hash, arch):
    version = package_identity['Version']; name = package_identity['Name']; publisher = package_identity['Publisher']
    installation = read_json(folder / 'install.json')
    require(installation.get('success') is True and digest(installation.get('originalSha256')) == msix_hash, '설치 원본 MSIX 해시/성공 불일치')
    signed = digest(installation.get('signedTestPackageSha256'))
    require(signed != msix_hash and installation.get('publisher') == publisher, '설치 서명/게시자 불일치')
    full_name = f'{name}_{version}_{arch}__{_publisher_id(publisher)}'
    require(installation.get('packageFullName') == full_name, '설치 identity/version/architecture/publisherId 불일치')
    context = read_json(folder / 'wack-context.json')
    require(context.get('invocationMode') == 'documented-appxpackagepath' and digest(context.get('inputPackageSha256')) == signed, 'WACK가 실제 설치에 사용한 signed MSIX를 검사하지 않음')
    summary = read_json(folder / 'wack.json')
    require(type(summary.get('exitCode')) is int and summary['exitCode'] == 0, 'WACK 미실행/실패')
    actual = inspect(folder / 'wack.xml', name, version, summary['exitCode'])
    require(actual['passed'] is True and actual['status'] == 'passed' and actual == summary, 'raw WACK XML/summary가 전체 PASS와 정확히 일치하지 않음')
    report = ET.fromstring((folder / 'wack.xml').read_bytes())
    embedded = report.findall('./APPLICATIONS/Installed_Programs/Program[@Source="AppxPackage"]/Indicators/WindowsStoreAppManifestIndicators/PackageManifest/Package/Identity')
    require(len(embedded) == 1 and all(embedded[0].get(k) == v for k, v in package_identity.items()), 'WACK embedded package identity 불일치')


def _architecture(package, wack, arch, expected=None):
    require_architecture(arch)
    provenance = read_json(package / 'provenance.json')
    require(set(provenance) == PROVENANCE_KEYS, '원본 provenance 필드 불일치')
    names = _names(package, provenance)
    require(len(names) == 6 and {p.name for p in package.iterdir()} == names, '아키텍처 원본이 정확히 6파일이어야 함')
    budget([package / n for n in names] + [wack / n for n in WACK.values()], ARCH_LIMIT)
    checksums = verify_checksums(package)
    require(provenance['repository'] == 'ATLKR/OpenGeul' and provenance['architecture'] == arch and provenance['unsigned'] is True and provenance['storeCertified'] is False, '원본 repository/architecture/unsigned 불일치')
    config = read_json(ROOT / 'config/product.json')
    require(provenance['version'] == config['version'] and provenance['upstream'] == read_json(ROOT / 'config/upstream.lock.json'), '현재 버전/upstream과 다른 원본')
    parity = provenance['sourceParity']
    require(isinstance(parity, dict) and parity.get('version') == provenance['version'] and parity.get('source') == 'OpenGeul distribution overlays', '준비된 소스 ledger 불일치')
    components = provenance['windowsComponents']
    require(isinstance(components, dict) and set(components) == {'formatVersion', 'repository', 'commit', 'runId', 'runAttempt', 'sourceContractSha256', 'components'} and type(components['formatVersion']) is int and components['formatVersion'] == 1, '구성 요소 출처 형식 불일치')
    current = identity({'GITHUB_REPOSITORY': provenance['repository'], 'GITHUB_SHA': provenance['commit'], 'GITHUB_RUN_ID': provenance['runId'], 'GITHUB_RUN_ATTEMPT': components['runAttempt']})
    require(all(components[k] == v for k, v in current.items()) and digest(components['sourceContractSha256']) == components['sourceContractSha256'], '구성 요소 소스 실행 불일치')
    if expected is not None:
        require(current == expected, '현재 CI 소스 실행/시도와 다른 패키지')
    msix = package / provenance['package']
    msix_hash = checksums[msix.name]
    require(provenance['sha256'] == msix_hash, '원본 MSIX provenance 해시 불일치')
    with tempfile.TemporaryDirectory(prefix='opengeul-pair-verify-') as temporary:
        with contextlib.redirect_stdout(io.StringIO()):
            prepare(package, Path(temporary) / 'runtime', architecture=arch)
    with zipfile.ZipFile(msix) as archive:
        require(type(provenance['members']) is int and provenance['members'] == len(archive.infolist()), 'MSIX 멤버 수 불일치')
        require(archive.read('AppxManifest.xml') == (package / 'AppxManifest.xml').read_bytes(), '외부 manifest가 실제 MSIX와 다름')
        doc = ET.fromstring(archive.read('AppxManifest.xml'))
        identity_node = doc.find('{http://schemas.microsoft.com/appx/manifest/foundation/windows10}Identity')
        package_identity = {k: identity_node.get(k) for k in ('Name', 'Publisher', 'Version', 'ProcessorArchitecture')}
        require(package_identity == {'Name': DEV_IDENTITY['name'], 'Publisher': DEV_IDENTITY['publisher'], 'Version': package_version(provenance['version']), 'ProcessorArchitecture': arch}, 'MSIX 개발 identity/version 불일치')
        records = components['components']
        require(isinstance(records, dict) and set(records) == {'editor', 'cli'}, 'editor/CLI 구성 요소 둘 다 필요함')
        for role, runtime in [('editor', 'OpenGeul.exe'), ('cli', 'Tools/rhwp.exe')]:
            record = records[role]
            require(isinstance(record, dict) and set(record) == {'artifactName', 'runAttempt', 'provenanceSha256', 'runtime', 'size', 'sha256'}, '구성 요소 record 불일치')
            attempt = record['runAttempt']
            require(isinstance(attempt, str) and re.fullmatch('[1-9][0-9]*', attempt) and int(attempt) <= int(current['runAttempt']), '미래/잘못된 구성 요소 시도')
            require(record['artifactName'] == component_artifact_name(role, current['runId'], arch) and record['runtime'] == runtime, '다른 아키텍처/실행 구성 요소')
            require(digest(record['provenanceSha256']) == record['provenanceSha256'] and digest(record['sha256']) == record['sha256'], '잘못된 producer 해시')
            require(type(record['size']) is int and record['size'] == archive.getinfo(runtime).file_size, '구성 요소 runtime 크기 불일치')
            with archive.open(runtime) as stream:
                require(stream_hash(stream) == record['sha256'], 'MSIX runtime과 producer 해시 불일치')
    _check_wack(wack, package_identity, msix_hash, arch)
    return provenance, current, names


def _copy(source, target, expected_hash):
    regular(source)
    size = source.stat().st_size
    require(size <= ARCH_LIMIT, '복사 한도 초과')
    with source.open('rb') as original, target.open('xb') as output:
        remaining = size
        while remaining:
            raw = original.read(min(1024 * 1024, remaining))
            require(bool(raw), '원본 복사 중 변경됨')
            output.write(raw); remaining -= len(raw)
        require(not original.read(1), '원본이 복사 중 커짐')
    require(sha(target) == expected_hash, '복사 원본 hash가 변경됨')


def _fresh(output):
    _ancestors(output)
    require(not output.exists() and not output.is_symlink(), '기존 출력 덮어쓰기 거부')


def _separate(output, *inputs):
    target = output.resolve()
    for source in inputs:
        original = source.resolve()
        require(not target.is_relative_to(original) and not original.is_relative_to(target), '출력은 원본 경로와 분리해야 함')


def _publish(output, files, provenance=None):
    _fresh(output); output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.opengeul-pair-', dir=output.parent))
    try:
        for name, (source, expected_hash) in files.items():
            _copy(source, stage / basename(name), expected_hash)
        if provenance is not None:
            (stage / 'provenance.json').write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            (stage / 'SHA256SUMS.txt').write_text(''.join(sha(p) + '  ' + p.name + '\n' for p in sorted(stage.iterdir())), encoding='utf-8')
            budget(list(stage.iterdir()), PAIR_LIMIT)
            verify_pair(stage)
        else:
            verify_checksums(stage)
        _fresh(output); stage.rename(output)
    finally:
        if stage.exists(): shutil.rmtree(stage)


def assemble(x64, arm64, wack_x64, wack_arm64, output, *, env=None):
    """현재 소스 CI 환경을 요구하며 모든 입력 검증 뒤에만 출력을 만든다."""
    _fresh(output); _separate(output, x64, arm64, wack_x64, wack_arm64)
    current = identity(os.environ if env is None else env)
    entries, files, common, reference = {}, {}, None, None
    snapshots = {}
    for package, wack in ((x64, wack_x64), (arm64, wack_arm64)):
        paths = list(itertools.islice(package.iterdir(), 7))
        require(len(paths) == 6, '입력 package 원본은 정확히 6파일이어야 함')
        paths += [wack / name for name in WACK.values()]
        budget(paths, ARCH_LIMIT)
        snapshots.update({p: sha(p) for p in paths})
    for arch, package, wack in [('x64', x64, wack_x64), ('arm64', arm64, wack_arm64)]:
        prov, bound, names = _architecture(package, wack, arch, current)
        fingerprint = {key: prov[key] for key in ('sourceParity', 'upstream')}
        top = {**bound, 'version': prov['version'], 'sourceContractSha256': prov['windowsComponents']['sourceContractSha256']}
        if common is not None:
            require(common == top and reference == fingerprint, '아키텍처별 소스/상위입력/ledger가 서로 다름')
        common, reference = top, fingerprint
        asset_map = {name: _flatten(name, arch) for name in sorted(names)}
        wack_map = _wack_names(arch)
        entries[arch] = {'provenance': prov, 'assets': asset_map, 'wack': wack_map}
        for original, flattened in asset_map.items():
            require(flattened not in files, '아키텍처 원본 파일명 충돌')
            files[flattened] = (package / original, snapshots[package / original])
        for key, flattened in wack_map.items():
            require(flattened not in files, 'WACK 파일명 충돌')
            source = wack / WACK[key]; files[flattened] = (source, snapshots[source])
    require(len(files) == 20, '고정 20원본 필요')
    budget([source for source, _ in files.values()], PAIR_LIMIT)
    result = {'formatVersion': 2, **common, 'architectures': entries}
    _publish(output, files, result)
    return result


def _descriptor(directory):
    _ancestors(directory)
    require(directory.is_dir() and not directory.is_symlink(), '잘못된 pair 디렉터리')
    paths = list(itertools.islice(directory.iterdir(), 23))
    require(len(paths) == 22, 'pair는 정확히 22원본 파일이어야 함')
    budget(paths, PAIR_LIMIT); verify_checksums(directory)
    value = read_json(directory / 'provenance.json')
    require(set(value) == {'formatVersion', 'architectures', *COMMON} and type(value['formatVersion']) is int and value['formatVersion'] == 2, 'pair provenance 형식 불일치')
    require(isinstance(value['architectures'], dict) and set(value['architectures']) == set(ARCHES), 'x64/arm64 두 아키텍처 필요')
    expected = {'provenance.json', 'SHA256SUMS.txt'}
    for arch in ARCHES:
        entry = value['architectures'][arch]
        require(isinstance(entry, dict) and set(entry) == {'provenance', 'assets', 'wack'}, '아키텍처 entry 불일치')
        require(isinstance(entry['assets'], dict) and len(entry['assets']) == 6 and set(METADATA) <= set(entry['assets']), '원본 6파일 매핑 필요')
        for name, flattened in entry['assets'].items():
            require(basename(flattened) == _flatten(basename(name), arch) and flattened not in expected, 'flat asset 매핑/이름 충돌')
            expected.add(flattened)
        require(entry['wack'] == _wack_names(arch), 'raw WACK 매핑 불일치')
        expected.update(entry['wack'].values())
        require(read_json(directory / entry['assets']['provenance.json']) == entry['provenance'], '원본 provenance와 global entry 불일치')
        budget([directory / n for n in [*entry['assets'].values(), *entry['wack'].values()]], ARCH_LIMIT)
    require(expected == {p.name for p in paths} and len(expected) == 22, '알 수 없는/누락 pair asset')
    return value


def copy_architecture(directory, architecture, output):
    """global SUMS/map/복원 SUMS만 확인해 원본6을 복원한다. 먼저 verify_pair를 호출한다."""
    require_architecture(architecture); _separate(output, directory); value = _descriptor(directory)
    _restore(directory, value['architectures'][architecture], output)


def _restore(directory, entry, output):
    files = {original: (directory / flattened, sha(directory / flattened)) for original, flattened in entry['assets'].items()}
    _publish(output, files)


def verify_pair(directory):
    """양쪽 원본/전체 parity/source-input/raw-WACK를 읽기 전용으로 재검증한다."""
    value = _descriptor(directory); reference = None
    with tempfile.TemporaryDirectory(prefix='opengeul-pair-reader-') as temporary:
        base = Path(temporary)
        for arch in ARCHES:
            package, wack = base / arch, base / ('wack-' + arch)
            entry = value['architectures'][arch]
            _restore(directory, entry, package); wack.mkdir()
            for key, name in entry['wack'].items():
                _copy(directory / name, wack / WACK[key], sha(directory / name))
            prov, current, _ = _architecture(package, wack, arch)
            top = {**current, 'version': prov['version'], 'sourceContractSha256': prov['windowsComponents']['sourceContractSha256']}
            require(top == {k: value[k] for k in COMMON} and prov == entry['provenance'], '공통 pair 출처 불일치')
            inputs = {k: prov[k] for k in ('sourceParity', 'upstream')}
            require(reference is None or reference == inputs, '아키텍처별 준비 소스가 다름')
            reference = inputs
    return value


def source_fingerprint(directory):
    """검증된 flat22파일의 바이트 fingerprint; CI qualification을 대신하지 않는다."""
    _descriptor(directory)
    rows = [{'name': p.name, 'size': p.stat().st_size, 'sha256': sha(p)} for p in sorted(directory.iterdir())]
    return hashlib.sha256(encoded(rows)).hexdigest()


def main():
    parser = argparse.ArgumentParser(description='같은 소스의 x64·ARM64 전체 WACK 통과 원본 결합')
    command = parser.add_subparsers(dest='command', required=True).add_parser('assemble')
    for name in ('x64', 'arm64', 'wack-x64', 'wack-arm64', 'output'):
        command.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    assemble(args.x64, args.arm64, args.wack_x64, args.wack_arm64, args.output)
    print('x64·ARM64 원본 22파일과 전체 WACK PASS를 결합했습니다. Store 승인이 아닙니다.')


if __name__ == '__main__': main()
