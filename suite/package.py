"""Assemble a separate, inventoried Suite without changing an installed product."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def git(root: Path, *arguments: str) -> str:
    return subprocess.check_output(['git', '-C', str(root), *arguments], text=True,
                                   encoding='utf-8').strip()


def write_source_archive(root: Path, target: Path) -> str:
    if target.exists() or target.is_symlink(): raise ValueError('Source archive output already exists')
    if git(root, 'status', '--porcelain', '--untracked-files=normal'):
        raise ValueError('Suite build requires a clean, committed source tree')
    commit = git(root, 'rev-parse', 'HEAD')
    if not re.fullmatch(r'[0-9a-f]{40}', commit): raise ValueError('Exact source commit is required')
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['git', '-C', str(root), 'archive', '--format=zip', '--output',
                    str(target.resolve()), commit], check=True, timeout=60)
    return commit


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def copy_regular_tree(source: Path, target: Path) -> None:
    if not source.is_dir() or source.is_symlink(): raise ValueError('Input must be a regular directory')
    for path in source.rglob('*'):
        if path.is_symlink(): raise ValueError('Package inputs must not contain symlinks')
    shutil.copytree(source, target)


def assemble(*, runtime: Path, hwp: Path, shell: Path, output: Path, lock: dict) -> None:
    if output.exists() or output.is_symlink(): raise ValueError('Suite output already exists')
    if not (shell/'OpenGeul.Office.exe').is_file(): raise ValueError('Published Windows shell is required')
    from prepare import check_asset, extract_hwp_zip, validate_source_build_receipt, validate_source_build_runtime
    from runtime_branding import brand_runtime
    from payload import create_inventory, verify_payload
    if lock['runtime'].get('format') == 'source-built-zip':
        receipt = runtime/'opengeul-source-build.json'
        if not receipt.is_file(): raise ValueError('Source-built runtime requires its pinned source-build receipt')
        proof = validate_source_build_receipt(lock['runtime'], receipt, architecture=lock['architecture'])
        validate_source_build_runtime(runtime, proof)
    check_asset(lock['hwp'], hwp)
    product_path = ROOT/'suite/config/product.json'
    product = json.loads(product_path.read_text(encoding='utf-8'))
    copy_regular_tree(shell, output)
    source_commit = write_source_archive(ROOT, output/'Sources/OpenGeul-Office-source.zip')
    branding = brand_runtime(runtime, output/'Office', product)
    write_json(output/'runtime-branding.json', branding)
    extract_hwp_zip(hwp, output/'HWP')
    copy_regular_tree(ROOT/'suite/worker', output/'worker')
    # Python cache files are development intermediates, never packaged sources.
    for path in sorted((output/'worker').rglob('__pycache__'), reverse=True): shutil.rmtree(path)
    shutil.copy2(product_path, output/'suite-product.json')
    notices = output/'Notices'; notices.mkdir()
    shutil.copy2(ROOT/'LICENSE', notices/'OpenGeul-Office-LICENSE.txt')
    for notice in sorted((ROOT/'suite/notices').glob('*.txt')):
        shutil.copy2(notice, notices/notice.name)
    licenses = sorted(path for path in runtime.iterdir() if path.is_file()
                      and path.name.casefold() in ('license', 'license.txt', 'license.html'))
    if not licenses: raise ValueError('Original Office runtime license is missing')
    shutil.copy2(licenses[0], notices/'LibreOffice-LICENSE.txt')
    engine_source_notice = ''
    if lock['runtime'].get('format') == 'source-built-zip':
        build = lock['runtime']['sourceBuild']
        code = 'https://github.com/ATLKR/OpenGeul'
        commit_url = code+'/tree/'+build['sourceCommit']
        blob = code+'/blob/'+build['sourceCommit']
        engine_source_notice = (
            f'Native engine source/build code: {commit_url}\n'
            f'Native engine patch manifest: {blob}/suite/engine-build/source-build.json\n'
            f"Patch manifest SHA256: {build['patchManifestSha256']}\n"
            f'Native engine workflow: {blob}/.github/workflows/office-native-engine.yml\n'
            f"Native engine workflow run: {code}/actions/runs/{build['runId']}\n"
            f"GitHub build artifact ID: {build['artifactId']}\n"
            f"GitHub build artifact SHA256: {build['artifactSha256']}\n"
            'Authenticated native build receipt: ../Office/opengeul-source-build.json\n'
            f"Native build receipt SHA256: {build['receiptSha256']}\n\n"
            'Native engine source patches are enumerated in the pinned patch manifest.\n'
            'The exact patch files are included in the OpenGeul source archive.\n\n'
        )
    source_notice = (
        '# OpenGeul Office corresponding source\n\n'
        f'OpenGeul Suite source commit: {source_commit}\n'
        'Source archive: ../Sources/OpenGeul-Office-source.zip\n\n'
        f"LibreOffice upstream {lock['runtime']['version']}: {lock['runtime']['sourceUrl']}\n"
        f"Upstream source SHA256: {lock['runtime']['sourceSha256']}\n\n"
        + engine_source_notice +
        f"HWP component source: {lock['hwp']['sourceUrl']}\n"
        f"HWP original build provenance: {lock['hwp']['provenanceUrl']}\n\n"
        'Suite branding changes are enumerated in ../runtime-branding.json. The changed\n'
        'registry/configuration and branding files are included in ../Office and the\n'
        'OpenGeul source archive. Original runtime LICENSE/NOTICE/CREDITS remain in Office.\n'
        'OpenGeul Suite additions are MIT; upstream files retain their original licenses.\n'
        'This distribution is independent of The Document Foundation and Hancom.\n'
    )
    (notices/'CORRESPONDING_SOURCE.md').write_text(source_notice, encoding='utf-8')
    provenance = {
        'schemaVersion': 1, 'productName': 'OpenGeul Office', 'version': lock['version'],
        'architecture': lock['architecture'], 'sourceCommit': source_commit,
        'runtime': lock['runtime'], 'hwp': lock['hwp'],
        'sourceArchiveSha256': hashlib.sha256((output/'Sources/OpenGeul-Office-source.zip').read_bytes()).hexdigest(),
        'brandingReceiptSha256': hashlib.sha256((output/'runtime-branding.json').read_bytes()).hexdigest(),
    }
    write_json(output/'suite-provenance.json', provenance)
    (output/'README.txt').write_text(
        'OpenGeul Office 개발판\n\nOpenGeul.Office.exe를 실행하세요.\n'
        'Writer/Calc/Impress/Draw/Math/Base는 OpenGeul 창 내부의 Office 엔진을 사용합니다.\n'
        'HWP/HWPX는 기존 OpenGeul HWP 편집기에서 열립니다.\n'
        '원본 형식을 유지하며 다른 형식은 다른 이름으로 저장에서 선택합니다.\n'
        '새 Base 문서는 내장 Firebird를 사용하며, 다른 이름으로 저장해야 보관됩니다.\n'
        'HWP에는 WebView2가 필요합니다. 외부 데이터베이스/Java 의존성은 별도입니다.\n'
        '32비트 TWAIN 스캐너·SharePoint COM 연동은 이 portable 개발판에서 지원하지 않습니다.\n'
        '이 개발판은 Store 배포판이 아닙니다. 원본을 보관하고 저장 결과를 확인하세요.\n'
        '라이선스·대응 소스: Notices/CORRESPONDING_SOURCE.md\n', encoding='utf-8')
    inventory = create_inventory(output, architecture=lock['architecture'])
    write_json(output/'suite-inventory.json', inventory)
    verify_payload(output, inventory)
