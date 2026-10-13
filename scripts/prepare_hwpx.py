"""Apply checked HWPX extensions to the pinned HOP build tree, not the vendor Git history."""
from __future__ import annotations
import argparse
import json
import hashlib
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]

DOCUMENT_CANCELLATION_TESTS = """  it.each([
    ['file:open', 'openDocumentFromDialog', '파일 열기 중...', '파일 열기 취소'],
    ['file:save-as', 'saveDocumentAsFromCommand', '다른 이름으로 저장 중...', '다른 이름으로 저장 취소'],
  ])('reports cancelled %s only after the document operation completes', async (id, method, pending, cancelled) => {
    let cancel!: (value: null) => void;
    let operationPending = true;
    const selected = new Promise<null>((resolve) => { cancel = resolve; });
    const eventBus = { emit: vi.fn((event: string, message: unknown) => {
      if (event === 'desktop-status' && message === cancelled) {
        expect(operationPending).toBe(false);
      }
    }) };
    const wasm = desktopBridge({
      [method]: vi.fn(async () => {
        try {
          return await selected;
        } finally {
          operationPending = false;
        }
      }),
    });
    const saving = command(id).execute(services({ wasm, eventBus }) as never);

    await Promise.resolve();
    expect(eventBus.emit.mock.calls).toEqual([['desktop-status', pending]]);
    expect(operationPending).toBe(true);

    cancel(null);
    await saving;
    expect(eventBus.emit.mock.calls).toEqual([
      ['desktop-status', pending],
      ['desktop-status', cancelled],
    ]);
    expect(globalThis.alert).not.toHaveBeenCalled();
  });

  it('reports failed Save As without claiming cancellation completed', async () => {
    const eventBus = { emit: vi.fn() };
    const wasm = desktopBridge({
      saveDocumentAsFromCommand: vi.fn().mockRejectedValue(new Error('disk full')),
    });

    await command('file:save-as').execute(services({ wasm, eventBus }) as never);

    expect(eventBus.emit.mock.calls).toEqual([
      ['desktop-status', '다른 이름으로 저장 중...'],
      ['desktop-status', '다른 이름으로 저장 실패: disk full'],
    ]);
    expect(globalThis.alert).toHaveBeenCalledWith('다른 이름으로 저장에 실패했습니다:\\ndisk full');
  });

"""

CLOSE_CANCELLATION_TEST = """  it('reports cancelled close only after the close request settles', async () => {
    const { getCloseHandler } = installTauriMocks();
    (globalThis as { window?: unknown }).window = { __TAURI_INTERNALS__: {} };
    installDocumentStub();
    let cancel!: (value: boolean) => void;
    let operationPending = true;
    const decision = new Promise<boolean>((resolve) => { cancel = resolve; });
    const setMessage = vi.fn(() => { expect(operationPending).toBe(false); });
    const bridge = {
      takePendingOpenPaths: vi.fn().mockResolvedValue([]),
      confirmWindowClose: vi.fn(async () => {
        try {
          return await decision;
        } finally {
          operationPending = false;
        }
      }),
      destroyCurrentWindow: vi.fn(),
    };
    await setupDesktopEvents({
      bridge,
      dispatcher: { dispatch: vi.fn() } as never,
      eventBus: { emit: vi.fn() } as never,
      setMessage,
      onUpdateState: vi.fn(),
    });
    const preventDefault = vi.fn();
    const closing = getCloseHandler()?.({ preventDefault });
    await Promise.resolve();
    expect(preventDefault).toHaveBeenCalledOnce();
    expect(setMessage).not.toHaveBeenCalled();
    expect(bridge.destroyCurrentWindow).not.toHaveBeenCalled();

    cancel(false);
    await closing;
    expect(setMessage.mock.calls).toEqual([['창 닫기 취소']]);
    expect(bridge.destroyCurrentWindow).not.toHaveBeenCalled();
  });

"""

def replace(path: Path, old: str, new: str, count: int = 1) -> None:
    text = path.read_text(encoding='utf-8')
    actual = text.count(old)
    if actual != count:
        raise ValueError(f'{path}: expected {count} anchors, found {actual}: {old[:75]!r}')
    path.write_text(text.replace(old, new), encoding='utf-8')

def patch_document_cancellation(host: Path) -> None:
    command = host/'src/command/commands/file.ts'
    replace(command, """      const payload = await desktop.openDocumentFromDialog();
      if (payload) services.eventBus.emit('desktop-document-loaded', payload);""",
        """      emitStatus(services, '파일 열기 중...');
      const payload = await desktop.openDocumentFromDialog();
      if (payload === null) emitStatus(services, '파일 열기 취소');
      if (payload) services.eventBus.emit('desktop-document-loaded', payload);""")
    replace(command, """      const result = await desktop.saveDocumentAsFromCommand();
      if (result) {""",
        """      const result = await desktop.saveDocumentAsFromCommand();
      if (result === null) emitStatus(services, '다른 이름으로 저장 취소');
      if (result) {""")
    replace(host/'src/core/desktop-events.ts', """    } else {
      await onCancel?.();
    }
  } catch (error) {""", """    } else {
      await onCancel?.();
      if (context === 'close request') setMessage('창 닫기 취소');
    }
  } catch (error) {""")
    replace(host/'src/core/desktop-events.ts', """    if (!desktop.hasUnsavedChanges?.()) {
      await desktop.destroyCurrentWindow();
    } else {""", """    if (!desktop.hasUnsavedChanges?.()) {
      try {
        await desktop.destroyCurrentWindow();
      } catch (fallbackError) {
        setMessage(`${errorPrefix}: ${fallbackError}`);
        await onCancel?.();
      }
    } else {""")
    anchor = "  it('uses desktop print integration when available', async () => {"
    replace(host/'src/command/commands/file.test.ts', anchor, DOCUMENT_CANCELLATION_TESTS + anchor)
    anchor = "  it('routes app quit requests through the existing close guard and cancels on refusal', async () => {"
    replace(host/'src/core/desktop-events.test.ts', anchor, CLOSE_CANCELLATION_TEST
        + (ROOT/'overlay/desktop-close-failure-tests.txt').read_text(encoding='utf-8') + anchor)

def patch_clipboard_document_guard(host: Path) -> None:
    command = host/'src/command/commands/edit.ts'
    replace(command, '  void writeSelectedText(services, inputHandler)',
        '  const documentGeneration = services.wasm.documentGeneration;\n  void writeSelectedText(services, inputHandler)')
    replace(command, "        action === 'cut' &&\n        copiedSelection !== null &&",
        "        action === 'cut' &&\n        services.wasm.documentGeneration === documentGeneration &&\n        copiedSelection !== null &&")
    anchor = "  it('delegates object copy and cut to the upstream input handler paths', () => {"
    replace(host/'src/command/commands/edit.test.ts', anchor,
        (ROOT/'overlay/clipboard-document-tests.txt').read_text(encoding='utf-8') + anchor)

def red_probe(source: Path) -> None:
    path = source / 'apps/studio-host/src/core/tauri-bridge.test.ts'
    original = path.read_bytes()
    try:
        replace(path,
            "await expect(bridge.saveDocumentFromCommand()).rejects.toThrow('HWPX 원본 저장은 아직 안전하게 지원하지 않습니다');",
            'await expect(bridge.saveDocumentFromCommand()).resolves.toBeDefined();')
        node = shutil.which('node')
        cli = source/'apps/studio-host/node_modules/vitest/vitest.mjs'
        if not node or not cli.is_file():
            raise RuntimeError('Node and installed Vitest are required for the baseline RED probe')
        command = [node, str(cli), 'run', 'src/core/tauri-bridge.test.ts']
        result = subprocess.run(command, cwd=source/'apps/studio-host', text=True,
            encoding='utf-8', errors='replace', stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180)
        print(result.stdout)
        if result.returncode == 0 or 'HWPX 원본 저장은 아직 안전하게 지원하지 않습니다' not in result.stdout:
            raise RuntimeError('Baseline did not fail for the expected HWPX save rejection')
        print('EXPECTED RED: unchanged application rejects HWPX direct saving; original test restored.')
    finally:
        path.write_bytes(original)

def patch(source: Path) -> None:
    ledger = source/'.opengeul-overlay.json'
    if not ledger.is_file(): raise ValueError('Apply the distribution overlay before HWPX extensions')
    value = json.loads(ledger.read_text(encoding='utf-8'))
    if value.get('hwpxSaveV1'): raise ValueError('HWPX extension already applied')
    native = source/'apps/desktop/src-tauri/src'
    core = source/'apps/studio-host/src/core'
    host = source/'apps/studio-host'
    for name in ('opengeul_hwpx_commands.rs','opengeul_hwpx_state.rs','opengeul_hwpx_state_tests.rs','opengeul_hwp_staging_tests.rs'):
        shutil.copy2(ROOT/'overlay'/name, native/name)
    shutil.copy2(ROOT/'overlay/save-format.ts', core/'save-format.ts')
    replace(native/'commands.rs', 'use crate::font_catalog::LocalFontEntry;',
        '#[path = "opengeul_hwpx_commands.rs"]\npub mod opengeul_hwpx;\n\nuse crate::font_catalog::LocalFontEntry;')
    replace(native/'state.rs', 'use crate::pending_open::PendingOpenPaths;',
        '#[path = "opengeul_hwpx_state.rs"]\nmod opengeul_hwpx;\n\nuse crate::pending_open::PendingOpenPaths;')
    replace(native/'state.rs', '        let bytes = std::fs::read(&staged_path).map_err(|e| {',
        '        opengeul_hwpx::validate_staging_path(&staged_path, &target_path)?;\n        let bytes = std::fs::read(&staged_path).map_err(|e| {')
    replace(native/'state.rs', '        let staged_path = dir.path().join("save.tmp");\n        let target_path = dir.path().join("saved.hwp");',
        '        let target_path = dir.path().join("saved.hwp");\n        let staged_path = target_path.with_file_name(format!("saved.hwp.hop-save-{}.tmp", Uuid::new_v4().simple()));')
    replace(native/'lib.rs', 'tauri::generate_handler![',
        'tauri::generate_handler![\n            commands::opengeul_hwpx::prepare_staged_hwpx_save,\n            commands::opengeul_hwpx::commit_staged_hwpx_save,')
    bridge = core/'tauri-bridge.ts'
    replace(bridge, "type DocumentFormat = 'hwp' | 'hwpx';", "import { resolveSavePath } from './save-format';\n\ntype DocumentFormat = 'hwp' | 'hwpx';")
    replace(bridge, '  private dirty = false;', '  private dirty = false;\n  private editGeneration = 0;\n  private saveInProgress = false;')
    replace(bridge, """    if (this.sourceFormat === 'hwpx') {
      throw new Error('HWPX 원본 저장은 아직 안전하게 지원하지 않습니다. 다른 이름으로 저장에서 HWP 파일로 저장하세요.');
    }
    return this.saveHwpThroughStaging(docId, null);""", """    const target = resolveSavePath(this.sourcePath, this.sourceFormat);
    if (target.format !== this.sourceFormat) return this.saveDocumentAs();
    return this.saveHwpThroughStaging(docId, null, target.format);""")
    replace(bridge, """    const targetPath = await this.selectSavePath(this.suggestedHwpName(), 'HWP 문서', ['hwp']);
    if (!targetPath) return null;""", """    const { save } = await import('@tauri-apps/plugin-dialog');
    const formats: DocumentFormat[] = this.sourceFormat === 'hwpx' ? ['hwpx', 'hwp'] : ['hwp', 'hwpx'];
    const targetPath = await save({
      defaultPath: this.suggestedHwpName().replace(/\\.hwp$/i, `.${this.sourceFormat}`),
      filters: formats.map((format) => ({ name: `${format.toUpperCase()} 문서`, extensions: [format] })),
    });
    if (!targetPath) return null;
    const target = resolveSavePath(targetPath, this.sourceFormat);""")
    # Keep upstream's cleartext consent and private operation methods inside its lock.
    replace(bridge, "return this.saveHwpThroughStaging(docId, this.withExtension(targetPath, 'hwp'));",
        "return this.saveHwpThroughStaging(docId, target.path, target.format);")
    replace(bridge, "저장한 HWP 파일에는 암호가 적용되지 않습니다. 암호 없이 저장하시겠습니까?",
        "저장한 ${target.format.toUpperCase()} 파일에는 암호가 적용되지 않습니다. 암호 없이 저장하시겠습니까?")
    replace(bridge, "message('저장한 ${target.format.toUpperCase()} 파일에는 암호가 적용되지 않습니다. 암호 없이 저장하시겠습니까?',",
        "message(`저장한 ${target.format.toUpperCase()} 파일에는 암호가 적용되지 않습니다. 암호 없이 저장하시겠습니까?`,")
    replace(bridge, '    if (!this.docId || this.dirty) return;', '    if (!this.docId) return;\n    this.editGeneration += 1;\n    if (this.dirty) return;')
    start = bridge.read_text(encoding='utf-8')
    old = start[start.index('  private async saveHwpThroughStaging('):start.index('  private async confirmExternalOverwriteIfNeeded(')]
    replace(bridge, old, """  private async saveHwpThroughStaging(
    docId: string,
    targetPath: string | null,
    format: DocumentFormat = 'hwp',
  ): Promise<DesktopSaveResult | null> {
    if (this.saveInProgress) throw new Error('저장이 진행 중입니다. 완료 후 다시 시도하세요.');
    const finalPath = targetPath ?? this.sourcePath;
    if (!finalPath) throw new Error('새 문서는 저장 경로가 필요합니다');
    this.saveInProgress = true;
    let stagedPath: string | null = null;
    try {
      const allowExternalOverwrite = await this.confirmExternalOverwriteIfNeeded(docId, finalPath);
      if (allowExternalOverwrite === null) return null;
      const bytes = format === 'hwpx' ? super.exportHwpx() : super.exportHwp();
      const generation = this.editGeneration;
      const revision = this.revision;
      stagedPath = await this.invoke<string>(`prepare_staged_${format}_save`, { targetPath: finalPath });
      await writeFileInChunks(stagedPath, bytes);
      const committed = await this.invoke<DesktopSaveResult>(`commit_staged_${format}_save`, {
        docId, stagedPath, targetPath: finalPath, expectedRevision: revision, allowExternalOverwrite,
      });
      await this.noteFinderRecentDocument(finalPath);
      // Finish every asynchronous cleanup before computing the final clean/dirty state.
      await remove(stagedPath).catch(() => undefined);
      stagedPath = null;
      const result = { ...committed, dirty: this.editGeneration !== generation };
      this.applyNativeSaveResult(result);
      this.requiresPasswordForSave = false;
      if (result.dirty) await this.invoke<void>('mark_document_dirty', { docId });
      return result;
    } finally {
      if (stagedPath) await remove(stagedPath).catch(() => undefined);
      this.saveInProgress = false;
    }
  }

""")
    replace(bridge, """    if (this.sourceFormat === 'hwpx' || this.requiresPasswordForSave) {
      return this.saveDocumentAs();
    }
    return this.saveDocument();""", """    if (this.requiresPasswordForSave) return this.saveDocumentAs();
    return this.saveDocument();""")
    replace(bridge, '  private async confirmReadyForDocumentReplacement(): Promise<boolean> {',
        '  private async confirmReadyForDocumentReplacement(): Promise<boolean> {\n    if (this.saveInProgress) return false;')
    replace(bridge, '      return result !== null;', '      return result !== null && !result.dirty;')
    for reason in ('document-changed', 'document-mutated'):
        replace(host/'src/main.ts',
            f"    documentState.markDirty(typeof reason === 'string' ? reason : '{reason}');",
            f"    documentState.markDirty(typeof reason === 'string' ? reason : '{reason}');\n    (wasm as DirtyAwareBridge).markDocumentDirty?.();")
    replace(host/'src/main.ts', """eventBus.on('desktop-document-saved', () => {
  documentState.markClean('save');
  sbMessage().textContent = '저장 완료';
});""", """eventBus.on('desktop-document-saved', (payload) => {
  const stillDirty = Boolean((payload as { dirty?: boolean } | null)?.dirty);
  if (!stillDirty) documentState.markClean('save');
  sbMessage().textContent = stillDirty ? '이전 변경 저장 완료 — 추가 변경 미저장' : '저장 완료';
});""")
    replace(host/'src/command/commands/file.ts', "emitStatus(services, '저장 완료');",
        "emitStatus(services, result.dirty ? '이전 변경 저장 완료 — 추가 변경 미저장' : '저장 완료');", count=2)
    patch_document_cancellation(host)
    patch_clipboard_document_guard(host)
    test = core/'tauri-bridge.test.ts'
    replace(test, "    exportHwpMock = vi.fn(() => new Uint8Array([1, 2, 3]));",
        "    exportHwpMock = vi.fn(() => new Uint8Array([1, 2, 3]));\n    exportHwpxMock = vi.fn(() => new Uint8Array([0x50, 0x4b, 3]));\n    exportHwpx() { return this.exportHwpxMock(); }")
    text = test.read_text(encoding='utf-8')
    begin = text.index("  it('blocks direct save for HWPX sources'")
    end = text.index("  it.each([false, true])('saves HWP bytes through native state", begin)
    replace(test, text[begin:end], (ROOT/'overlay/hwpx-bridge-tests.txt').read_text(encoding='utf-8')+'\n')
    replace(test, "name: 'loadDocumentMock' | 'createNewDocumentMock' | 'exportHwpMock'",
        "name: 'loadDocumentMock' | 'createNewDocumentMock' | 'exportHwpMock' | 'exportHwpxMock'")
    examples = source/'apps/desktop/src-tauri/examples'
    examples.mkdir(exist_ok=True)
    shutil.copy2(ROOT/'e2e/generate-fixtures.rs', examples/'opengeul-fixtures.rs')
    value['baselinePreservedFiles'] = dict(value.get('preservedFiles', {}))
    value['preservedFiles'] = {name: digest for name, digest in value['baselinePreservedFiles'].items()
        if hashlib.sha256((source/name).read_bytes()).hexdigest() == digest}
    value['hwpxSaveV1'] = True
    value['changes'] += ['HWPX native staged save and reopen validation','format-aware WASM export','async-save dirty-state preservation','native-dialog cancellation completion status','async Cut document replacement guard']
    value['extendedFiles'] = ['commands.rs','state.rs','lib.rs','tauri-bridge.ts','main.ts','file.ts','desktop-events.ts','edit.ts']
    ledger.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
    print('Applied checked HWPX extensions. Runtime/round-trip validation must pass separately.')

if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('--red-probe', action='store_true')
    args=parser.parse_args()
    (red_probe if args.red_probe else patch)(args.source.resolve())
