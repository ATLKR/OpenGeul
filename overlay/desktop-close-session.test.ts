import { beforeEach, describe, expect, it, vi } from 'vitest';
import { TauriBridge } from './tauri-bridge';
import { setupDesktopEvents } from './desktop-events';

const boundary = vi.hoisted(() => ({
  invoke: vi.fn(), message: vi.fn(), save: vi.fn(), fsOpen: vi.fn(),
  handlers: new Map<string, (event: { payload: unknown }) => Promise<void>>(),
  close: null as null | ((event: { preventDefault(): void }) => Promise<void>),
  text: 'visible original document',
}));
vi.mock('@tauri-apps/api/core', () => ({ invoke: boundary.invoke }));
vi.mock('@tauri-apps/api/event', () => ({ listen: async () => () => undefined }));
vi.mock('@tauri-apps/api/webviewWindow', () => ({ getCurrentWebviewWindow: () => ({
  listen: async (name: string, callback: (event: { payload: unknown }) => Promise<void>) => {
    boundary.handlers.set(name, callback); return () => undefined;
  },
  onCloseRequested: async (callback: typeof boundary.close) => { boundary.close = callback; return () => undefined; },
}) }));
vi.mock('@tauri-apps/plugin-dialog', () => ({ message: boundary.message, save: boundary.save }));
vi.mock('@tauri-apps/plugin-fs', () => ({
  open: boundary.fsOpen, remove: async () => undefined,
  stat: async (path: string) => ({
    size: path.includes('.hop-save-') ? new TextEncoder().encode(boundary.text).byteLength : 3,
    isFile: true, mtime: new Date('2026-10-13T00:00:00Z'),
  }),
}));
vi.mock('@/core/bridge-factory', () => ({ isTauriRuntime: () => true }));
vi.mock('@/upstream/ui', () => ({ showHwpPasswordDialog: vi.fn() }));
vi.mock('@/upstream/core', () => ({ WasmBridge: class {
  fileName = 'retained.hwp';
  loadDocument() { return { pageCount: 1, fontsUsed: [] }; }
  exportHwp() { return new TextEncoder().encode(boundary.text); }
  getSourceFormat() { return 'hwp'; }
} }));

describe('native close acceptance retains the actual document bridge', () => {
  beforeEach(() => {
    vi.clearAllMocks(); boundary.handlers.clear(); boundary.close = null;
    boundary.text = 'visible original document';
    (globalThis as { document?: unknown }).document = { title: '' };
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    vi.spyOn(console, 'warn').mockImplementation(() => undefined);
  });

  async function loaded() {
    const sessions = new Map([['retained-doc', { dirty: false, sourcePath: '/tmp/retained.hwp' }]]);
    const messages: string[] = []; const writes: Uint8Array[] = [];
    let rejects = 0; let cancels = 0; let destroyed = false;
    boundary.message.mockResolvedValue('저장 안 함');
    boundary.fsOpen.mockImplementation(async (_path: string, _options: { read?: boolean }) => {
      let read = false;
      return { close: async () => undefined,
        read: async (bytes: Uint8Array) => { if (read) return null; read = true; bytes.set([1, 2, 3]); return 3; },
        write: async (bytes: Uint8Array) => { writes.push(bytes.slice()); return bytes.byteLength; },
      };
    });
    boundary.invoke.mockImplementation(async (command: string, args: Record<string, unknown> = {}) => {
      if (command === 'prepare_document_open' || command === 'record_recent_document' || command === 'note_finder_recent_document') return;
      if (command === 'open_document_tracking') return { docId: 'retained-doc', fileName: 'retained.hwp',
        sourcePath: '/tmp/retained.hwp', format: 'hwp', revision: 1, dirty: false, pageCount: 1 };
      if (command === 'take_pending_open_paths') return [];
      if (command === 'get_update_state') return { status: 'idle' };
      if (command === 'close_document') { sessions.delete(args.docId as string); return; }
      if (command === 'destroy_current_window') {
        if (rejects > 0) { rejects -= 1; throw new Error('native destroy failed'); }
        destroyed = true; sessions.delete(args.docId as string); return;
      }
      if (command === 'cancel_app_quit') { cancels += 1; return; }
      if (command === 'mark_document_dirty') { expect(sessions.has(args.docId as string)).toBe(true); sessions.get(args.docId as string)!.dirty = true; return; }
      if (command === 'check_external_modification') return { changed: false };
      if (command === 'prepare_staged_hwp_save') return '/tmp/retained.hwp.hop-save-0123456789abcdef0123456789abcdef.tmp';
      if (command === 'commit_staged_hwp_save') {
        expect(args.docId).toBe('retained-doc'); expect(sessions.has('retained-doc')).toBe(true);
        sessions.get('retained-doc')!.dirty = false;
        return { docId: 'retained-doc', sourcePath: '/tmp/retained.hwp', format: 'hwp', revision: 2, dirty: false, warnings: [] };
      }
      throw new Error(`Unexpected native command ${command}`);
    });
    const bridge = new TauriBridge();
    await bridge.openDocumentByPath('/tmp/retained.hwp');
    await setupDesktopEvents({ bridge, dispatcher: { dispatch() {} } as never,
      eventBus: { emit() {} } as never, setMessage: (message) => messages.push(message), onUpdateState() {} });
    return { bridge, sessions, messages, writes, failDestroy: (n: number) => { rejects = n; },
      cancellations: () => cancels, destroyed: () => destroyed };
  }

  it.each(['close', 'quit'])('keeps the document editable and saveable after two rejected %s destroys, then retries safely', async (kind) => {
    const app = await loaded(); const title = document.title;
    app.failDestroy(2);
    const close = () => kind === 'close' ? boundary.close!({ preventDefault() {} })
      : boundary.handlers.get('hop-app-quit-requested')!({ payload: null });
    await expect(close()).resolves.toBeUndefined();
    expect(app.sessions.has('retained-doc')).toBe(true);
    expect(document.title).toBe(title);
    expect(app.messages).toEqual([`${kind === 'close' ? '창 닫기 실패' : '앱 종료 실패'}: Error: native destroy failed`]);
    expect(app.cancellations()).toBe(kind === 'quit' ? 1 : 0);
    expect(boundary.invoke).not.toHaveBeenCalledWith('close_document', expect.anything());

    boundary.text = 'edited after failed close'; app.bridge.markDocumentDirty();
    await vi.waitFor(() => expect(app.sessions.get('retained-doc')!.dirty).toBe(true));
    expect(app.bridge.hasUnsavedChanges()).toBe(true);
    await expect(app.bridge.saveDocumentFromCommand()).resolves.toMatchObject({ docId: 'retained-doc', dirty: false });
    expect(new TextDecoder().decode(app.writes[0])).toBe('edited after failed close');
    expect(app.bridge.hasUnsavedChanges()).toBe(false);
    await close();
    expect(app.destroyed()).toBe(true); expect(app.sessions.has('retained-doc')).toBe(false);
    expect(boundary.invoke).toHaveBeenCalledWith('destroy_current_window', { docId: 'retained-doc' });
  });

  it('consents without releasing the document and delegates accepted close cleanup to native code', async () => {
    const app = await loaded();
    expect(await app.bridge.confirmWindowClose()).toBe(true);
    expect(app.sessions.has('retained-doc')).toBe(true);
    expect(boundary.invoke).not.toHaveBeenCalledWith('close_document', expect.anything());
    await app.bridge.destroyCurrentWindow();
    expect(app.sessions.has('retained-doc')).toBe(false);
    expect(boundary.invoke).toHaveBeenLastCalledWith('destroy_current_window', { docId: 'retained-doc' });
  });

  it('preserves unsaved edits after discard consent when native destruction fails', async () => {
    const app = await loaded(); boundary.text = 'unsaved after discard'; app.bridge.markDocumentDirty();
    await vi.waitFor(() => expect(app.sessions.get('retained-doc')!.dirty).toBe(true));
    const title = document.title; app.failDestroy(2);
    await boundary.handlers.get('hop-app-quit-requested')!({ payload: null });
    expect(app.sessions.has('retained-doc')).toBe(true); expect(app.bridge.hasUnsavedChanges()).toBe(true);
    expect(document.title).toBe(title); expect(app.cancellations()).toBe(1);
    expect(app.messages).toEqual(['앱 종료 실패: Error: native destroy failed']);
    expect(boundary.invoke.mock.calls.filter(([command]) => command === 'destroy_current_window')).toHaveLength(1);
    await expect(app.bridge.saveDocumentFromCommand()).resolves.toMatchObject({
      docId: 'retained-doc', sourcePath: '/tmp/retained.hwp', dirty: false,
    });
    expect(new TextDecoder().decode(app.writes[0])).toBe('unsaved after discard');
  });

  it('passes no document session for an empty window', async () => {
    const app = await loaded(); const empty = new TauriBridge();
    expect(await empty.confirmWindowClose()).toBe(true);
    await empty.destroyCurrentWindow();
    expect(boundary.invoke).toHaveBeenLastCalledWith('destroy_current_window', { docId: null });
    expect(app.sessions.has('retained-doc')).toBe(true);
  });

  it.each(['cancel', 'save failure'])('keeps a dirty document and its session after %s', async (mode) => {
    const app = await loaded(); boundary.text = 'unsaved edit'; app.bridge.markDocumentDirty();
    await vi.waitFor(() => expect(app.sessions.get('retained-doc')!.dirty).toBe(true));
    boundary.message.mockResolvedValue(mode === 'cancel' ? '취소' : '저장');
    if (mode === 'save failure') boundary.fsOpen.mockRejectedValueOnce(new Error('disk full'));
    await boundary.handlers.get('hop-app-quit-requested')!({ payload: null });
    expect(app.sessions.has('retained-doc')).toBe(true); expect(app.bridge.hasUnsavedChanges()).toBe(true);
    expect(app.cancellations()).toBe(1); expect(app.destroyed()).toBe(false);
    expect(boundary.invoke).not.toHaveBeenCalledWith('close_document', expect.anything());
    expect(boundary.invoke).not.toHaveBeenCalledWith('destroy_current_window', expect.anything());
  });
});
