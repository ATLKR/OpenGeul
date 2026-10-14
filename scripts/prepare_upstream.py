"""Fetch exact public upstream versions, then apply OpenGeul overlays. Never resets user files."""
from __future__ import annotations
import argparse
import fnmatch
import json
import hashlib
import os
import posixpath
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tomllib
from buildkit import ROOT, FONT_EXTENSIONS, make_assets, package_version, replace_once, tauri_config
from native_activation import apply as apply_native_activation
from com_worker import apply as apply_com_worker


TAURI_VERSION = "2.11.1"
DESKTOP_LOCK = ROOT / "overlay/desktop-cargo.lock.toml"
UPDATE_DEPENDENCIES = '''reqwest = { version = "=0.13.2", default-features = false, features = ["rustls-no-provider"] }
tokio = { version = "=1.52.1", features = ["time", "sync"] }
rustls = { version = "=0.23.45", default-features = false, features = ["ring", "std", "tls12"] }
'''
ASYNC_CLIPBOARD_SOURCE_SHA256 = {
    'input-handler-keyboard.ts': '1076739c3742d73329e91cb3cdf2f638f03fcb21e7df0aa6a326963bf231b87c',
    'input-handler.ts': '9bbba9420b2a8d4c3630a1797976bf9e65b9b1b4a67c608f305e1f5a873c31ce',
}


def run(*args: str, cwd: Path) -> str:
    result=subprocess.run(list(args),cwd=cwd,check=True,text=True,encoding="utf-8",stdout=subprocess.PIPE)
    return result.stdout.strip()


def replace_file(path: Path, old: str, new: str, expected: int = 1, *, newline: str | None = None) -> None:
    path.write_text(replace_once(path.read_text(encoding='utf-8'),old,new,expected=expected),encoding='utf-8',newline=newline)


def checkout_rhwp(destination: Path, repository: str, commit: str) -> None:
    """고정 소스·샘플·시험 입력을 유지하고 대용량 개발 참조만 제외한다."""
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('rhwp checkout requires an exact commit')
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('Refusing to overwrite a nonempty rhwp checkout')
    destination.mkdir(parents=True, exist_ok=True)
    run('git', 'init', '--quiet', str(destination), cwd=ROOT)
    run('git', 'config', 'core.autocrlf', 'false', cwd=destination)
    run('git', 'config', 'core.longpaths', 'true', cwd=destination)
    run('git', 'remote', 'add', 'origin', repository, cwd=destination)
    run('git', 'fetch', '--filter=blob:none', '--depth=1', 'origin', commit, cwd=destination)
    if run('git', 'rev-parse', 'FETCH_HEAD', cwd=destination) != commit:
        raise ValueError('rhwp fetched commit does not match the lock')
    directories = run('git', 'ls-tree', '-d', '-z', '--name-only', 'FETCH_HEAD', cwd=destination).split('\0')
    selected = [name for name in directories if name and name not in ('mydocs', 'pdf', 'tools')]
    manual = run('git', 'ls-tree', '-d', '-z', '--name-only', 'FETCH_HEAD:mydocs', cwd=destination).split('\0')
    selected += ['mydocs/' + name for name in manual if name and name not in ('pr', 'report')]
    # Cargo resolves every workspace member before building a selected target.
    # Tools are not uniformly reference data: retain their required source and
    # local dependency closure, even when those directories are otherwise sparse.
    selected += cargo_source_directories(destination, 'FETCH_HEAD')
    if any('\n' in name or '\r' in name for name in selected):
        raise ValueError('Unsupported upstream directory name')
    run('git', 'sparse-checkout', 'init', '--cone', cwd=destination)
    subprocess.run(['git', 'sparse-checkout', 'set', '--stdin'], cwd=destination,
                   input='\n'.join(selected) + '\n', text=True, encoding='utf-8', check=True)
    run('git', 'checkout', '--detach', 'FETCH_HEAD', cwd=destination)
    restore_compile_inputs(destination)


def cargo_source_directories(source: Path, revision: str) -> list[str]:
    tracked = set(run('git', 'ls-tree', '-r', '-z', '--name-only', revision, cwd=source).split('\0'))
    manifests = {name for name in tracked if name == 'Cargo.toml' or name.endswith('/Cargo.toml')}
    if 'Cargo.toml' not in manifests:
        raise ValueError('Pinned rhwp source has no root Cargo manifest')
    queue = ['Cargo.toml']
    seen = set()
    target_directories = set()

    def dependency_tables(value):
        for key, table in value.items():
            if not isinstance(table, dict):
                continue
            if key in ('dependencies', 'build-dependencies', 'dev-dependencies'):
                yield table
            else:
                yield from dependency_tables(table)

    while queue:
        name = queue.pop()
        if name in seen:
            continue
        if name not in manifests:
            raise ValueError('Missing local Cargo manifest: ' + name)
        seen.add(name)
        size = int(run('git', 'cat-file', '-s', revision + ':' + name, cwd=source))
        if not 0 < size <= 1024 * 1024:
            raise ValueError('Cargo manifest exceeds the source inspection bound')
        value = tomllib.loads(run('git', 'show', revision + ':' + name, cwd=source))
        directory = posixpath.dirname(name)
        for member in value.get('workspace', {}).get('members', []):
            pattern = posixpath.normpath(posixpath.join(directory, member))
            matches = [path for path in manifests if fnmatch.fnmatchcase(posixpath.dirname(path) or '.', pattern)]
            if not matches:
                raise ValueError('Missing Cargo workspace member: ' + pattern)
            queue.extend(matches)
        for table in dependency_tables(value):
            for dependency in table.values():
                if not isinstance(dependency, dict) or 'path' not in dependency:
                    continue
                path = dependency['path']
                if not isinstance(path, str) or '\\' in path or posixpath.isabs(path):
                    raise ValueError('Unsupported local Cargo dependency path')
                path = posixpath.normpath(posixpath.join(directory, path))
                if path == '..' or path.startswith('../'):
                    raise ValueError('Cargo dependency escapes the upstream checkout')
                queue.append(posixpath.normpath(posixpath.join(path, 'Cargo.toml')))
        # Explicit Cargo target paths may point outside the member directory.
        for kind in ('bin', 'test', 'bench', 'example'):
            for target in value.get(kind, []):
                if not isinstance(target, dict) or 'path' not in target:
                    continue
                path = posixpath.normpath(posixpath.join(directory, target['path']))
                if path == '..' or path.startswith('../') or posixpath.isabs(path):
                    raise ValueError('Cargo target source escapes the checkout: ' + path)
                # Some original targets are generated by upstream scripts and
                # are absent even in a complete Git checkout. Keep that original
                # build contract; sparse checkout must retain all tracked ones.
                if path not in tracked:
                    continue
                parent = posixpath.dirname(path)
                if parent:
                    target_directories.add(parent)
    return sorted({posixpath.dirname(name) for name in seen if posixpath.dirname(name)} | target_directories)


def restore_compile_inputs(source: Path) -> None:
    """희소 경로의 literal include 입력도 원래 Git blob으로 복원한다."""
    names = run('git', 'ls-files', '-z', '*.rs', cwd=source).split('\0')
    for name in names:
        rust = source / name
        if not name or not rust.is_file():
            continue
        text = rust.read_text(encoding='utf-8')
        for relative in re.findall(r'\binclude_(?:bytes|str)!\s*\(\s*"([^"\n]+)"', text):
            if '\\' in relative:
                raise ValueError('Unsupported escaped Rust include input')
            target = (rust.parent / relative).resolve()
            try:
                path = target.relative_to(source.resolve()).as_posix()
            except ValueError:
                raise ValueError('Rust include input escapes the upstream checkout') from None
            if target.is_file():
                continue
            # A missing fixture is a preparation failure, never a skipped test.
            try:
                size = int(run('git', 'cat-file', '-s', 'HEAD:' + path, cwd=source))
                kind = run('git', 'cat-file', '-t', 'HEAD:' + path, cwd=source)
            except subprocess.CalledProcessError:
                raise ValueError('Missing tracked Rust include input: ' + path) from None
            if kind != 'blob' or not 0 <= size <= 64 * 1024 * 1024:
                raise ValueError('Unsupported Rust include input: ' + path)
            data = subprocess.check_output(['git', 'show', 'HEAD:' + path], cwd=source)
            if len(data) != size:
                raise ValueError('Rust include blob size changed')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)


def install_store_updates(source: Path) -> None:
    """고정 Store 공개 메타데이터 확인과 사용자가 선택하는 Store 링크만 연결한다."""
    integration = json.loads((ROOT/'overlay/store-update-integration.json').read_text(encoding='utf-8'))
    for local, target in integration['copies'].items():
        destination = source/target
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT/local, destination)
    for item in integration['replacements']:
        replace_file(source/item['file'], item['old'], item['new'])


def install_product_information(source: Path) -> None:
    """기존 정보 화면에 제품 신원과 복사 가능한 연락처만 표시한다."""
    target = source/'apps/studio-host/src/ui/about-dialog.ts'
    original_sha = 'c5e116871de4ce7cd13bb94a1be757164468153e7bcab21bbca4134df0b044af'
    if hashlib.sha256(target.read_bytes()).hexdigest() != original_sha:
        raise ValueError('Upstream product information source changed')
    text = (ROOT/'overlay/about-dialog.ts').read_text(encoding='utf-8')
    match = re.search(r"^const HOP_BASE_VERSION = '([^']+)';$", text, re.MULTILINE)
    pinned = json.loads((ROOT/'config/upstream.lock.json').read_text(encoding='utf-8'))['hop']['version']
    if match is None or match[1] != pinned:
        raise ValueError('Reviewed HOP attribution version does not match the upstream lock')
    shutil.copy2(ROOT/'overlay/about-dialog.ts', target)
    shutil.copy2(ROOT/'overlay/about-dialog.test.ts', target.with_name('about-dialog.test.ts'))


def install_async_clipboard_guard(source: Path) -> dict:
    """고정 clipboard 경로의 대기 작업을 원래 문서·편집 문맥에만 적용한다."""
    engine = source/'third_party/rhwp/rhwp-studio/src/engine'
    expected = ASYNC_CLIPBOARD_SOURCE_SHA256
    original = {name: (engine/name).read_bytes() for name in expected}
    if any(hashlib.sha256(original[name]).hexdigest() != digest for name, digest in expected.items()):
        raise ValueError('Upstream async clipboard source changed')
    keyboard = original['input-handler-keyboard.ts'].decode('utf-8')
    helper = '''/** A pending clipboard conversion owns one document and editing context. */
function captureAsyncClipboardContext(self: any): { isCurrent(): boolean; dispose(): void } {
  const wasm = self.wasm;
  const cursor = self.cursor;
  const generation = wasm.documentGeneration;
  const document = wasm.borrowDocumentHandle?.();
  const readContext = () => JSON.stringify([
    cursor.getPosition(), cursor.getSelection?.(),
    cursor.getFootnoteSelection?.(), cursor.getHeaderFooterSelectionOrdered?.(),
    cursor.captureCellSelection?.(), cursor.blockSelectionPhase?.(),
    cursor.getSelectedPictureRefs?.(), cursor.getSelectedTableRef?.(),
    cursor.headerFooterMode, cursor.hfSectionIdx, cursor.hfApplyTo,
    cursor.hfParaIdx, cursor.hfCharOffset, cursor.hfPreviewPage,
    cursor.isInFootnote?.(), cursor.fnSectionIdx, cursor.fnParaIdx,
    cursor.fnControlIdx, cursor.fnInnerParaIdx, cursor.fnCharOffset,
    self.isFormMode?.(), self.isComposing === true,
  ], (key, value) => key === 'cursorRect' ? undefined : value);
  const context = readContext();
  let cancelled = false;
  const subscriptions: Array<() => void> = [];
  const dispose = () => { for (const off of subscriptions.splice(0)) off(); };
  const cancel = () => { cancelled = true; dispose(); };
  const isCurrent = () => !cancelled && self.active && self.wasm === wasm
    && self.cursor === cursor && wasm.documentGeneration === generation
    && wasm.borrowDocumentHandle?.() === document && readContext() === context;
  // InputHandler publishes selection refreshes on click, drag and navigation.
  // A changed selection stays cancelled even if the user moves back before decode.
  const checkContext = () => { if (!isCurrent()) cancel(); };
  for (const event of [
    'clipboard-context-changed', 'command-state-changed',
    'picture-object-selection-changed', 'table-object-selection-changed',
    'headerFooterModeChanged', 'footnoteModeChanged',
    'cursor-rect-updated', 'editing-page-changed',
  ]) subscriptions.push(self.eventBus.on(event, checkContext));
  // Resumable completion publishes old layout work, not a new content edit.
  subscriptions.push(self.eventBus.on('document-mutated', (reason: unknown) => {
    if (reason === 'input-handler-resumable-pagination') checkContext();
    else cancel();
  }));
  // Older property/format commands publish only document-changed.
  subscriptions.push(self.eventBus.on('document-changed', (reason: unknown) => {
    if (reason === 'deferred-pagination-complete'
      || (typeof reason === 'string' && reason.startsWith('deferred-pagination-flush:'))) checkContext();
    else cancel();
  }));
  subscriptions.push(self.eventBus.on('clipboard-context-invalidated', cancel));
  return { isCurrent, dispose };
}

'''
    keyboard = replace_once(keyboard, 'export function onPaste(this: any, e: ClipboardEvent): void {',
                            helper + 'export function onPaste(this: any, e: ClipboardEvent): void {')
    keyboard = replace_once(keyboard, '''      void (async () => {
        let merged = html;
        try {
          merged = await inlineOfficeClipboardImages(html, rtf);
        } catch (error) {
          console.warn('[paste] RTF 그림 삽입 실패 — 그림 없이 붙여넣기:', error);
        }
        pasteExternalHtml.call(this, merged, text, hasSelection);
      })();''', '''      const clipboardContext = captureAsyncClipboardContext(this);
      void (async () => {
        try {
          let merged = html;
          try {
            merged = await inlineOfficeClipboardImages(html, rtf);
          } catch (error) {
            console.warn('[paste] RTF 그림 삽입 실패 — 그림 없이 붙여넣기:', error);
          }
          if (!clipboardContext.isCurrent()) return;
          clipboardContext.dispose();
          pasteExternalHtml.call(this, merged, text, hasSelection);
        } finally {
          clipboardContext.dispose();
        }
      })();''')
    keyboard = replace_once(keyboard, '''async function pasteImageFile(this: any, file: File, hasSelection: boolean): Promise<void> {
  try {
    const data = new Uint8Array(await file.arrayBuffer());''', '''async function pasteImageFile(this: any, file: File, hasSelection: boolean): Promise<void> {
  const clipboardContext = captureAsyncClipboardContext(this);
  try {
    const data = new Uint8Array(await file.arrayBuffer());
    if (!clipboardContext.isCurrent()) return;''')
    keyboard = replace_once(keyboard, '''      URL.revokeObjectURL(url);
    }

    // px → HWPUNIT''', '''      URL.revokeObjectURL(url);
    }
    if (!clipboardContext.isCurrent()) return;
    clipboardContext.dispose();

    // px → HWPUNIT''')
    keyboard = replace_once(keyboard, '''      if (hasSelection) this.deleteSelection();
      const p = this.cursor.getPosition();
      // 표 셀 안 paste''', '''      if (hasSelection) this.deleteSelection({ deferRecord: true });
      const p = this.cursor.getPosition();
      // 표 셀 안 paste''')
    keyboard = replace_once(keyboard, '''    console.warn('[InputHandler] 클립보드 이미지 삽입 실패:', err);
  }
}''', '''    console.warn('[InputHandler] 클립보드 이미지 삽입 실패:', err);
  } finally {
    clipboardContext.dispose();
  }
}''')
    handler = original['input-handler.ts'].decode('utf-8')
    for anchor, event in [
        ('  private updateSelection(): void {', 'clipboard-context-changed'),
        ('  private updateCellSelection(): void {', 'clipboard-context-changed'),
        ('  deactivate(): void {', 'clipboard-context-invalidated'),
        ('  dispose(): void {', 'clipboard-context-invalidated'),
    ]:
        handler = replace_once(handler, anchor, anchor + f"\n    this.eventBus.emit('{event}');")
    prepared = {'input-handler-keyboard.ts': keyboard, 'input-handler.ts': handler}
    # All contracts and replacements pass before either product file is written.
    for name, text in prepared.items():
        (engine/name).write_text(text, encoding='utf-8', newline='\n')
    return {'beforeSha256': expected,
            'afterSha256': {name: hashlib.sha256(text.encode('utf-8')).hexdigest()
                            for name, text in prepared.items()}}


def patch(source: Path, version: str) -> None:
    package_version(version)
    protected = ['apps/desktop/src-tauri/src/' + x for x in ('commands.rs','state.rs','pdf_export.rs','pending_open.rs','app_quit.rs','recent_documents.rs')]
    protected += ['apps/studio-host/hop-overrides.ts']
    original = {name: hashlib.sha256((source/name).read_bytes()).hexdigest() for name in protected}
    native=source/'apps/desktop/src-tauri'
    host=source/'apps/studio-host'
    upstream=source/'third_party/rhwp'
    build=native/'build.rs'
    if build.read_text(encoding='utf-8') != 'fn main() {\n    tauri_build::build();\n}\n':
        raise ValueError('Upstream native build script changed')
    build.write_text('''fn main() {
    let windows = tauri_build::WindowsAttributes::new()
        .app_manifest(include_str!("windows-app-manifest.xml"));
    let attrs = tauri_build::Attributes::new().windows_attributes(windows);
    tauri_build::try_build(attrs).expect("failed to run Tauri build");
}
''',encoding='utf-8')
    shutil.copy2(ROOT/'overlay/windows-app-manifest.xml',native/'windows-app-manifest.xml')
    replace_file(native/'windows-app-manifest.xml', '@VERSION@', package_version(version))
    cfg=native/'tauri.conf.json'
    cfg.write_text(json.dumps(tauri_config(json.loads(cfg.read_text(encoding='utf-8')),version),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    win=native/'tauri.windows.conf.json'
    w=json.loads(win.read_text(encoding='utf-8'))
    for window in w.get('app',{}).get('windows',[]): window['title']='OpenGeul'
    win.write_text(json.dumps(w,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    for rel in ('package.json','apps/desktop/package.json'):
        path=source/rel; value=json.loads(path.read_text(encoding='utf-8')); value['version']=version
        path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    hop_version=json.loads((ROOT/'config/upstream.lock.json').read_text(encoding='utf-8'))['hop']['version']
    # Tauri rewrites this manifest with LF in the editor build. Prepare identical
    # bytes for the CLI producer so the strict source contract survives that rewrite.
    replace_file(native/'Cargo.toml',f'version = "{hop_version}"',f'version = "{version}"',newline='\n')
    # GHSA-7gmj-67g7-phm9: 로컬 IPC 출처 판별 수정이 포함된 버전을 정확히 고정한다.
    # .toml 확장자로 보안 잠금 입력도 기존 구성 요소 증명의 helper 해시에 포함한다.
    replace_file(native/'Cargo.toml', 'tauri = { version = "2", features = [] }',
                 f'tauri = {{ version = "={TAURI_VERSION}", features = [] }}\n'+UPDATE_DEPENDENCIES.rstrip(), newline='\n')
    lock = DESKTOP_LOCK.read_text(encoding='utf-8')
    selected = [p['version'] for p in tomllib.loads(lock)['package'] if p['name'] == 'tauri']
    if selected != [TAURI_VERSION]:
        raise ValueError('검토한 Tauri 보안 수정 버전과 데스크톱 잠금 파일이 다릅니다')
    lock = replace_once(lock, f'name = "hop-desktop"\nversion = "{hop_version}"',
                        f'name = "hop-desktop"\nversion = "{version}"')
    (native/'Cargo.lock').write_text(lock, encoding='utf-8', newline='\n')
    com_proof = apply_com_worker(source)
    shutil.copy2(ROOT/'overlay/cli-cargo.lock.toml', upstream/'Cargo.lock')
    activation_proof = apply_native_activation(source)
    for component in ('Preview','Thumbnail'):
        path=source/f'apps/desktop/quicklook/Resources/{component}/Info.plist'
        if path.is_file():
            value=path.read_text(encoding='utf-8'); value,n=re.subn(r'(<key>CFBundleShortVersionString</key>\s*<string>)[^<]+',lambda m:m[1]+version,value)
            if n!=1: raise ValueError('Unexpected Quick Look version metadata')
            path.write_text(value,encoding='utf-8')
    replace_file(native/'src/lib.rs','        .plugin(tauri_plugin_updater::Builder::new().build())\n','')
    replace_file(native/'src/lib.rs','mod app_quit;','mod app_quit;\nmod opengeul_font_resources;\n#[cfg(windows)]\nmod opengeul_runtime;')
    replace_file(native/'src/lib.rs','pub fn run() {','pub fn run() {\n    #[cfg(windows)]\n    if !opengeul_runtime::ready() { return; }')
    shutil.copy2(ROOT/'overlay/opengeul_runtime.rs',native/'src/opengeul_runtime.rs')
    replace_file(native/'src/lib.rs','tauri::generate_handler![','tauri::generate_handler![\n            opengeul_font_resources::open_font_resource,')
    shutil.copy2(ROOT/'overlay/updates.rs',native/'src/updates.rs')
    install_store_updates(source)
    # Native font scanning remains restricted to installed system/per-user font directories.
    font=native/'src/font_catalog.rs'
    replace_file(font,'use tauri::{AppHandle, Manager};','use tauri::AppHandle;')
    replace_file(font,'''pub fn pdf_font_dirs(app: &AppHandle) -> Vec<PathBuf> {
    let mut dirs = Vec::new();
    if let Ok(resource_dir) = app.path().resource_dir() {
        dirs.push(resource_dir.join("fonts/pdf"));
    }
    dirs.extend(desktop_extra_font_dirs());
    dedupe_existing_dirs(dirs)
}''','''pub fn pdf_font_dirs(_app: &AppHandle) -> Vec<PathBuf> {
    desktop_extra_font_dirs()
}''')
    replace_file(font, '    let allowed_roots = desktop_extra_font_dirs();', '''    let mut allowed_roots = desktop_extra_font_dirs();
    #[cfg(windows)]
    if let Some(windir) = env_path("WINDIR") {
        allowed_roots.extend(dedupe_existing_dirs(vec![windir.join("Fonts")]));
    }''')
    shutil.copy2(ROOT/'overlay/font-catalog.ts',host/'src/core/font-catalog.ts')
    # Keep proper names while making user-facing version and comparison labels Korean-first.
    ui=upstream/'rhwp-studio/src/ui'
    replace_file(ui/'about-dialog.ts', "titleEn.textContent = 'HWP/HWPX Compatible Module for Rust';",
        "titleEn.textContent = 'Rust용 HWP/HWPX 호환 모듈';")
    replace_file(ui/'about-dialog.ts', 'version.textContent = `Version ${__APP_VERSION__}`;',
        'version.textContent = `버전 ${__APP_VERSION__}`;')
    install_product_information(source)
    async_clipboard_proof = install_async_clipboard_guard(source)
    replace_file(ui/'compare-dialog.ts', 'L: ${this.escape(leftPreview)} / R: ${this.escape(rightPreview)}',
        '왼쪽: ${this.escape(leftPreview)} / 오른쪽: ${this.escape(rightPreview)}')
    replace_file(ui/'history-dialog.ts', 'L: ${this.escape(leftText)} / R: ${this.escape(rightText)}',
        '이력: ${this.escape(leftText)} / 현재: ${this.escape(rightText)}')
    # Migrate the earlier OpenGeul visibility choice into HOP's native preference.
    # A newer explicit HOP choice wins, and storage denial must not break the UI.
    replace_file(host/'src/host/toolbar-labels.ts',
        "  try { return localStorage.getItem(STORAGE_KEY) !== 'hidden'; }", """  try {
    const current = localStorage.getItem(STORAGE_KEY);
    if (current !== null) return current !== 'hidden';
    if (localStorage.getItem('opengeul.toolbar.labels.visible') === 'false') {
      try { localStorage.setItem(STORAGE_KEY, 'hidden'); } catch { /* Current view remains usable. */ }
      return false;
    }
    return true;
  }""")
    # Keep the Vite asset directory, but remove font programs before frontend build.
    for path in (source/'assets/fonts').rglob('*'):
        if path.is_file() and path.suffix.lower() in FONT_EXTENSIONS: path.unlink()
    make_assets(source/'assets/opengeul')
    index=host/'index.html'
    replace_file(index,'<title>HOP</title>','<title>OpenGeul</title>')
    replace_file(index,'href="/favicon.ico"','href="/opengeul.ico"')
    (host/'public').mkdir(exist_ok=True)
    shutil.copy2(source/'assets/opengeul/app.ico',host/'public/opengeul.ico')
    replace_file(index,'</body>','<script type="module" src="/src/opengeul-font-help.ts"></script>\n</body>')
    # Do not rename upstream technical identifiers or credits indiscriminately.
    windows=native/'src/windows.rs'
    content=windows.read_text(encoding='utf-8').replace('"HOP"','"OpenGeul"').replace(' — HOP',' — OpenGeul').replace(' - HOP',' - OpenGeul')
    windows.write_text(content,encoding='utf-8')
    resources=json.loads((ROOT/'config/font-resources.json').read_text(encoding='utf-8'))
    native_lines=['#[tauri::command]','pub fn open_font_resource(resource: String) -> Result<(), String> {','    let target = match resource.as_str() {']
    for item in resources: native_lines.append(f'        {json.dumps(item["id"])} => {json.dumps(item["url"])},')
    native_lines += ['        _ => return Err("허용되지 않은 글꼴 리소스입니다.".into()),','    };','    open::that(target).map_err(|error| error.to_string())','}']
    (native/'src/opengeul_font_resources.rs').write_text('\n'.join(native_lines)+'\n',encoding='utf-8')
    shutil.copy2(ROOT/'overlay/opengeul-font-help.ts',host/'src/opengeul-font-help.ts')
    (host/'src/opengeul-font-resources.ts').write_text('export default '+json.dumps(resources,ensure_ascii=False)+' as const;\n',encoding='utf-8')
    # Do not silently allow the upstream PDF backend to embed every installed font.
    pdf=upstream/'src/renderer/pdf.rs'
    value=pdf.read_text(encoding='utf-8')
    anchor='/// Native PDF implementation selected by callers such as `export-pdf`.'
    value=replace_once(value,anchor,'#[cfg(not(target_arch = "wasm32"))]\nmod opengeul_pdf_guard;\n\n'+anchor)
    value=replace_once(value,'    let fontdb = create_fontdb(export_options);','    let mut fontdb = create_fontdb(export_options);\n    opengeul_pdf_guard::enforce(&mut fontdb, svg_pages)?;')
    incomplete='''        let Some((chunk, svg_ref)) =
            convert_page_chunk(&tree, export_options.embed_text, page_index, &mut to_chunk)?
        else {
            continue;
        };'''
    value=replace_once(value,incomplete,incomplete.replace('            continue;',
        '            return Err(opengeul_pdf_guard::incomplete_page_error(page_index));'))
    value=replace_once(value,' — 이 페이지만 건너뛰고 PDF 를 계속합니다.',
        ' — PDF 내보내기를 중단합니다.',expected=2)
    value=replace_once(value,'    crate::renderer::font_paths::load_into_fontdb(&mut fontdb, &options.font_paths);','    for dir in &options.font_paths { fontdb.load_fonts_dir(dir); }')
    direct='''pub fn layer_trees_to_pdf_with_links(
    layer_trees: &[crate::paint::PageLayerTree],
    links: &[Vec<super::hyperlinks::PdfLink>],
    options: &DirectPdfExportOptions,
) -> Result<Vec<u8>, String> {'''
    value=replace_once(value,direct,direct+'\n    opengeul_pdf_guard::reject_direct_export()?;')
    pdf.write_text(value,encoding='utf-8')
    module_dir=upstream/'src/renderer/pdf'; module_dir.mkdir(exist_ok=True)
    shutil.copy2(ROOT/'overlay/opengeul_pdf_guard.rs',module_dir/'opengeul_pdf_guard.rs')
    shutil.copy2(ROOT/'overlay/font_policy.rs',module_dir/'opengeul_font_policy.rs')
    adapter=source/'apps/desktop/rhwp-adapter/src/lib.rs'
    text=adapter.read_text(encoding='utf-8')
    text=replace_once(text,'"Noto Sans KR".to_string()','"Malgun Gothic".to_string()',expected=3)
    adapter.write_text(text,encoding='utf-8')
    for name, digest in original.items():
        if hashlib.sha256((source/name).read_bytes()).hexdigest() != digest:
            raise ValueError('A protected upstream Windows capability was changed: '+name)
    (source/'.opengeul-overlay.json').write_text(json.dumps({'version':version,'source':'OpenGeul distribution overlays','preservedFiles':original,'nativeActivation':activation_proof,'comWorker':com_proof,'asyncClipboardGuard':async_clipboard_proof,'changes':['branding','installed-only fonts','font help','Windows system-font read allowlist','PDF metadata guard','unreviewed direct Skia PDF embedding denied','legacy toolbar preference migration','disabled upstream updater','Korean-first version and comparison labels','pinned Tauri origin-confusion fix','Windows 기본 앱의 네이티브 활성화와 검증한 Tauri 소스 패치','MCP의 별도 COM 작업자와 원본 표준입출력·실패 격리 유지','asynchronous clipboard document and editing context guard']},indent=2),encoding='utf-8')


def port_windows_contract_test(dest: Path) -> None:
    # Windows baseline run 37290548163 reproduced this separator-only false positive.
    replace_file(dest/'tests/rhwp-boundary.test.mjs',
                 'const relativePath = relative(studioRoot, file);',
                 "const relativePath = relative(studioRoot, file).replaceAll('\\\\', '/');")


def main() -> None:
    parser=argparse.ArgumentParser()
    parser.add_argument('--directory',type=Path,default=ROOT/'.work/hop')
    parser.add_argument('--fetch-only',action='store_true')
    parser.add_argument('--patch-only',action='store_true')
    args=parser.parse_args();dest=args.directory.resolve()
    if args.fetch_only and args.patch_only:raise ValueError('Select one preparation mode')
    lock=json.loads((ROOT/'config/upstream.lock.json').read_text(encoding='utf-8'))
    version=json.loads((ROOT/'config/product.json').read_text(encoding='utf-8'))['version']
    if not args.patch_only:
        if dest.exists() and any(dest.iterdir()):raise ValueError(f'Refusing to reset nonempty work directory: {dest}')
        dest.mkdir(parents=True,exist_ok=True)
        os.environ['GIT_LFS_SKIP_SMUDGE']='1'
        run('git','init',str(dest),cwd=ROOT)
        run('git','config','core.autocrlf','false',cwd=dest)
        run('git','config','core.longpaths','true',cwd=dest)
        run('git','remote','add','origin',lock['hop']['repository'],cwd=dest)
        run('git','-c','core.autocrlf=false','fetch','--depth=1','origin',lock['hop']['commit'],cwd=dest)
        run('git','-c','core.autocrlf=false','checkout','--detach','FETCH_HEAD',cwd=dest)
        # The locked rhwp tree contains gigabytes of development screenshots and
        # reference PDFs. Native ARM runners have 14 GiB; retain all source,
        # samples, tests and literal compile inputs without fetching those blobs.
        run('git', 'submodule', 'init', 'third_party/rhwp', cwd=dest)
        checkout_rhwp(dest/'third_party/rhwp', lock['rhwp']['repository'], lock['rhwp']['commit'])
    if run('git','rev-parse','HEAD',cwd=dest)!=lock['hop']['commit']:raise ValueError('HOP commit mismatch')
    if run('git','rev-parse','HEAD',cwd=dest/'third_party/rhwp')!=lock['rhwp']['commit']:raise ValueError('rhwp submodule mismatch')
    if not args.patch_only:port_windows_contract_test(dest)
    if not args.fetch_only:patch(dest,version)
    print(f'Prepared {dest}; fetch_only={args.fetch_only}. Compilation and runtime verification are separate gates.')

if __name__=='__main__':
    try:main()
    except (ValueError,OSError,subprocess.CalledProcessError) as error:
        print(f'ERROR: {error}',file=sys.stderr);sys.exit(1)
