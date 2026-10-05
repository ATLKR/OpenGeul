export const TOOLBAR_LABELS_KEY = 'opengeul.toolbar.labels.visible';
export function readToolbarLabels(storage: Pick<Storage, 'getItem'>): boolean {
  try { return storage.getItem(TOOLBAR_LABELS_KEY) !== 'false'; }
  catch { return true; }
}
export function writeToolbarLabels(storage: Pick<Storage, 'setItem'>, visible: boolean): boolean {
  try { storage.setItem(TOOLBAR_LABELS_KEY, String(visible)); return true; }
  catch { return false; }
}
