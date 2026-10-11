import type { CommandDef, CommandServices } from '@/upstream/commands';
import type { EventBus } from '@/upstream/core';
import type { DesktopUpdateState } from '@/core/tauri-bridge';

type Preferences = { autoCheck: boolean };
type UpdateBridge = {
  checkStoreUpdate?: () => Promise<DesktopUpdateState>;
  getUpdatePreferences?: () => Promise<Preferences>;
  setUpdateAutoCheck?: (enabled: boolean) => Promise<Preferences>;
};
const AUTO_COMMAND = 'file:auto-check-update';
const CHECK_COMMAND = 'file:check-update';
const preferencePending = new WeakSet<object>();
const checkPending = new WeakSet<object>();
const preferenceRevisions = new WeakMap<object, number>();
const stateRevisions = new WeakMap<object, number>();
const observedBuses = new WeakMap<object, WeakSet<EventBus>>();

function desktopBridge(value: unknown): UpdateBridge | null {
  return value !== null && typeof value === 'object' ? value as UpdateBridge : null;
}

function applyPreferences(value: unknown): boolean {
  if (!value || typeof value !== 'object' || typeof (value as Preferences).autoCheck !== 'boolean') return false;
  const enabled = (value as Preferences).autoCheck;
  for (const element of document.querySelectorAll<HTMLElement>(`[data-cmd="${AUTO_COMMAND}"]`)) {
    element.setAttribute('aria-checked', String(enabled));
    element.classList.toggle('active', enabled);
    const icon = element.querySelector('.md-icon');
    if (icon) icon.textContent = enabled ? '✓' : '';
  }
  return true;
}

function observeUpdateEvents(desktop: UpdateBridge, eventBus: EventBus): void {
  let buses = observedBuses.get(desktop);
  if (!buses) { buses = new WeakSet<EventBus>(); observedBuses.set(desktop, buses); }
  if (buses.has(eventBus)) return;
  buses.add(eventBus);
  eventBus.on('desktop-update-preferences', (payload) => {
    if (applyPreferences(payload)) preferenceRevisions.set(desktop, (preferenceRevisions.get(desktop) ?? 0) + 1);
  });
  eventBus.on('desktop-update-state', () => {
    stateRevisions.set(desktop, (stateRevisions.get(desktop) ?? 0) + 1);
  });
}

export async function initStoreUpdateMenu(bridge: unknown, eventBus: EventBus): Promise<void> {
  const desktop = desktopBridge(bridge);
  for (const element of document.querySelectorAll<HTMLElement>(`[data-cmd="${CHECK_COMMAND}"]`)) {
    element.hidden = typeof desktop?.checkStoreUpdate !== 'function';
  }
  for (const element of document.querySelectorAll<HTMLElement>(`[data-cmd="${AUTO_COMMAND}"]`)) {
    element.hidden = typeof desktop?.getUpdatePreferences !== 'function';
  }
  if (!desktop?.getUpdatePreferences) return;
  observeUpdateEvents(desktop, eventBus);
  const hydrationRevision = preferenceRevisions.get(desktop) ?? 0;
  try {
    const preferences = await desktop.getUpdatePreferences();
    if ((preferenceRevisions.get(desktop) ?? 0) === hydrationRevision) applyPreferences(preferences);
  } catch (error) {
    eventBus.emit('desktop-status', `자동 업데이트 확인 설정을 읽지 못했습니다: ${errorText(error)}`);
  }
}

function errorText(error: unknown): string {
  return error instanceof Error && error.message ? error.message : String(error);
}

function unavailable(services: CommandServices): void {
  services.eventBus.emit('desktop-status', 'Store 업데이트 확인은 Windows 앱에서 사용할 수 있습니다.');
}

export const storeUpdateCommands: CommandDef[] = [
  {
    id: CHECK_COMMAND,
    label: 'Store 업데이트 확인',
    async execute(services) {
      const desktop = desktopBridge(services.wasm);
      if (!desktop?.checkStoreUpdate) return unavailable(services);
      observeUpdateEvents(desktop, services.eventBus);
      if (checkPending.has(desktop)) return;
      checkPending.add(desktop);
      const revision = stateRevisions.get(desktop) ?? 0;
      try {
        services.eventBus.emit('desktop-status', 'Store 업데이트 확인 중...');
        const state = await desktop.checkStoreUpdate();
        if ((stateRevisions.get(desktop) ?? 0) !== revision) {
          services.eventBus.emit('desktop-status', 'Store 업데이트 확인을 마쳤습니다.');
          return;
        }
        services.eventBus.emit('desktop-update-state', state);
        services.eventBus.emit('desktop-status', state.status === 'idle'
          ? '현재 버전이 최신입니다.' : state.status === 'error' ? state.message : '새 버전이 있습니다.');
      } catch (error) {
        if ((stateRevisions.get(desktop) ?? 0) !== revision) {
          services.eventBus.emit('desktop-status', 'Store 업데이트 확인을 마쳤습니다.');
          return;
        }
        const message = `업데이트를 확인하지 못했습니다: ${errorText(error)}`;
        services.eventBus.emit('desktop-update-state', { status: 'error', version: '', message });
        services.eventBus.emit('desktop-status', message);
      } finally {
        checkPending.delete(desktop);
      }
    },
  },
  {
    id: AUTO_COMMAND,
    label: 'Store 업데이트 자동 확인',
    async execute(services) {
      const desktop = desktopBridge(services.wasm);
      if (!desktop?.getUpdatePreferences || !desktop.setUpdateAutoCheck) return unavailable(services);
      observeUpdateEvents(desktop, services.eventBus);
      if (preferencePending.has(desktop)) return;
      preferencePending.add(desktop);
      try {
        const current = await desktop.getUpdatePreferences();
        const revision = preferenceRevisions.get(desktop) ?? 0;
        const updated = await desktop.setUpdateAutoCheck(!current.autoCheck);
        if ((preferenceRevisions.get(desktop) ?? 0) !== revision) return;
        services.eventBus.emit('desktop-update-preferences', updated);
        services.eventBus.emit('desktop-status', updated.autoCheck ? 'Store 업데이트 자동 확인을 켰습니다.' : 'Store 업데이트 자동 확인을 껐습니다.');
      } catch (error) {
        services.eventBus.emit('desktop-status', `자동 업데이트 확인 설정을 저장하지 못했습니다: ${errorText(error)}`);
      } finally {
        preferencePending.delete(desktop);
      }
    },
  },
];
