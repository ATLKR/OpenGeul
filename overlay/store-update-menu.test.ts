import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { EventBus } from '@upstream/core/event-bus';
import * as fileModule from './file';

type Initializer = (bridge: unknown, eventBus: EventBus) => Promise<void>;
class MenuItem {
  hidden = false;
  attributes = new Map<string, string>([['aria-checked', 'true']]);
  classes = new Set<string>();
  icon = { textContent: '✓' };
  classList = { toggle: (name: string, on: boolean) => { on ? this.classes.add(name) : this.classes.delete(name); } };
  setAttribute(name: string, value: string) { this.attributes.set(name, value); }
  querySelector() { return this.icon; }
}
let autoItem: MenuItem;
let manualItem: MenuItem;
function command(id: string) {
  const found = fileModule.fileCommands.find((item) => item.id === id);
  expect(found, `missing ${id}`).toBeDefined();
  return found!;
}
async function initialize(bridge: unknown, bus: EventBus) {
  const init = (fileModule as unknown as { initStoreUpdateMenu?: Initializer }).initStoreUpdateMenu;
  expect(init).toBeTypeOf('function');
  await init!(bridge, bus);
}
function services(wasm: unknown, eventBus = new EventBus()) { return { wasm, eventBus }; }
async function flush() { for (let i = 0; i < 5; i++) await Promise.resolve(); }

describe('Store update file menu', () => {
  afterEach(() => { delete (globalThis as { document?: Document }).document; });
  beforeEach(() => {
    autoItem = new MenuItem(); manualItem = new MenuItem();
    globalThis.document = { querySelectorAll: (selector: string) => selector.includes('auto-check-update') ? [autoItem] : [manualItem] } as unknown as Document;
  });

  it('manually checks without opening the Store and sends the result to the notice', async () => {
    const bus = new EventBus(); const state = vi.fn(); bus.on('desktop-update-state', state);
    const bridge = { checkStoreUpdate: vi.fn().mockResolvedValue({ status: 'available', version: '1.1.4.0' }), startUpdateInstall: vi.fn() };
    await command('file:check-update').execute(services(bridge, bus) as never);
    expect(bridge.checkStoreUpdate).toHaveBeenCalledOnce();
    expect(bridge.startUpdateInstall).not.toHaveBeenCalled();
    expect(state).toHaveBeenCalledWith({ status: 'available', version: '1.1.4.0' });
  });

  it.each([
    { status: 'available', version: '1.1.5.0' },
    { status: 'idle' },
  ])('does not overwrite a newer $status event with an older pending menu check', async (latest) => {
    let finish!: (state: { status: 'available'; version: string }) => void;
    const bridge = { checkStoreUpdate: () => new Promise((resolve) => { finish = resolve; }), getUpdatePreferences: () => Promise.resolve({ autoCheck: true }) };
    const bus = new EventBus(); const state = vi.fn(); const message = vi.fn(); bus.on('desktop-update-state', state); bus.on('desktop-status', message); await initialize(bridge, bus);
    const pending = command('file:check-update').execute(services(bridge, bus) as never);
    bus.emit('desktop-update-state', latest); // Native event from a newer check or another window's dismissal.
    finish({ status: 'available', version: '1.1.4.0' }); await pending;
    expect(state.mock.calls).toEqual([[latest]]);
    expect(message).not.toHaveBeenCalledWith('새 버전이 있습니다.');
  });

  it('keeps manual checking available when automatic checks are off', async () => {
    const bridge = { checkStoreUpdate: vi.fn().mockResolvedValue({ status: 'idle' }), getUpdatePreferences: vi.fn().mockResolvedValue({ autoCheck: false }), setUpdateAutoCheck: vi.fn() };
    const bus = new EventBus(); const message = vi.fn(); bus.on('desktop-status', message);
    await command('file:check-update').execute(services(bridge, bus) as never);
    expect(bridge.checkStoreUpdate).toHaveBeenCalledOnce();
    expect(bridge.setUpdateAutoCheck).not.toHaveBeenCalled();
    expect(message).toHaveBeenCalledWith('현재 버전이 최신입니다.');
  });

  it('exposes a rejected manual check as an error instead of claiming latest', async () => {
    const bus = new EventBus(); const state = vi.fn(); const message = vi.fn(); bus.on('desktop-update-state', state); bus.on('desktop-status', message);
    await command('file:check-update').execute(services({ checkStoreUpdate: () => Promise.reject(new Error('연결 실패')) }, bus) as never);
    expect(state).toHaveBeenCalledWith({ status: 'error', version: '', message: '업데이트를 확인하지 못했습니다: 연결 실패' });
    expect(message).toHaveBeenCalledWith('업데이트를 확인하지 못했습니다: 연결 실패');
    expect(message).not.toHaveBeenCalledWith('현재 버전이 최신입니다.');
  });

  it('hydrates the native preference without doing a UI-side network check', async () => {
    const bridge = { getUpdatePreferences: vi.fn().mockResolvedValue({ autoCheck: false }), checkStoreUpdate: vi.fn() };
    expect(autoItem.attributes.get('aria-checked')).toBe('true');
    await initialize(bridge, new EventBus());
    expect(autoItem.attributes.get('aria-checked')).toBe('false');
    expect(autoItem.icon.textContent).toBe('');
    expect(bridge.checkStoreUpdate).not.toHaveBeenCalled();
  });

  it('synchronizes other-window preference events and rejects stale hydration', async () => {
    expect((fileModule as unknown as { initStoreUpdateMenu?: Initializer }).initStoreUpdateMenu).toBeTypeOf('function');
    let finish!: (value: { autoCheck: boolean }) => void;
    const bridge = { getUpdatePreferences: () => new Promise<{ autoCheck: boolean }>((resolve) => { finish = resolve; }) };
    const bus = new EventBus(); const pending = initialize(bridge, bus);
    bus.emit('desktop-update-preferences', { autoCheck: false });
    finish({ autoCheck: true }); await pending;
    expect(autoItem.attributes.get('aria-checked')).toBe('false');
    bus.emit('desktop-update-preferences', { autoCheck: 'true' });
    expect(autoItem.attributes.get('aria-checked')).toBe('false');
    bus.emit('desktop-update-preferences', { autoCheck: true });
    expect(autoItem.attributes.get('aria-checked')).toBe('true');
    expect(autoItem.icon.textContent).toBe('✓');
  });

  it('toggles only after the persisted native result and ignores a duplicate pending action', async () => {
    let finish!: (value: { autoCheck: boolean }) => void;
    const bridge = { getUpdatePreferences: vi.fn().mockResolvedValue({ autoCheck: false }), setUpdateAutoCheck: vi.fn(() => new Promise<{ autoCheck: boolean }>((resolve) => { finish = resolve; })) };
    const bus = new EventBus(); await initialize(bridge, bus);
    const first = command('file:auto-check-update').execute(services(bridge, bus) as never);
    await flush();
    const second = command('file:auto-check-update').execute(services(bridge, bus) as never);
    expect(autoItem.attributes.get('aria-checked')).toBe('false');
    expect(bridge.setUpdateAutoCheck).toHaveBeenCalledOnce();
    expect(bridge.setUpdateAutoCheck).toHaveBeenCalledWith(true);
    finish({ autoCheck: true }); await first; await second;
    expect(autoItem.attributes.get('aria-checked')).toBe('true');
  });

  it('does not overwrite a newer other-window preference with an older setter response', async () => {
    let finish!: (value: { autoCheck: boolean }) => void;
    const bridge = { getUpdatePreferences: vi.fn().mockResolvedValue({ autoCheck: false }), setUpdateAutoCheck: vi.fn(() => new Promise<{ autoCheck: boolean }>((resolve) => { finish = resolve; })) };
    const bus = new EventBus(); const message = vi.fn(); bus.on('desktop-status', message); await initialize(bridge, bus);
    const pending = command('file:auto-check-update').execute(services(bridge, bus) as never);
    await flush();
    bus.emit('desktop-update-preferences', { autoCheck: true }); // This window's setter committed.
    bus.emit('desktop-update-preferences', { autoCheck: false }); // A newer other-window setter committed.
    finish({ autoCheck: true }); await pending;
    expect(autoItem.attributes.get('aria-checked')).toBe('false');
    expect(message).not.toHaveBeenCalledWith('Store 업데이트 자동 확인을 켰습니다.');
  });

  it('keeps the old checkbox when native preference persistence fails', async () => {
    const bridge = { getUpdatePreferences: vi.fn().mockResolvedValue({ autoCheck: false }), setUpdateAutoCheck: vi.fn().mockRejectedValue(new Error('저장 거부')) };
    const bus = new EventBus(); const message = vi.fn(); bus.on('desktop-status', message); await initialize(bridge, bus);
    await command('file:auto-check-update').execute(services(bridge, bus) as never);
    expect(autoItem.attributes.get('aria-checked')).toBe('false');
    expect(message).toHaveBeenCalledWith('자동 업데이트 확인 설정을 저장하지 못했습니다: 저장 거부');
  });
});
