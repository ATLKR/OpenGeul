import { captureAsyncClipboardContext } from './input-handler-keyboard';

/** Menu paste uses the same rich paste pipeline as the browser's native event. */
export async function performMenuPaste(self: any): Promise<boolean> {
  if (!self.active || self.isFormMode?.()) return false;
  self.focusTextarea();
  let receivedNativePaste = false;
  const observePaste = () => { receivedNativePaste = true; };
  self.textarea.addEventListener('paste', observePaste, true);
  try {
    // Chromium may reject this deprecated command or report true without a paste.
    // Observe actual delivery instead of treating the boolean as an edit receipt.
    document.execCommand('paste');
  } catch {
    // Clipboard.read provides the supported asynchronous path below.
  } finally {
    self.textarea.removeEventListener('paste', observePaste, true);
  }
  if (receivedNativePaste) return true;

  const context = captureAsyncClipboardContext(self);
  try {
    const clipboard = navigator.clipboard;
    const data = new DataTransfer();
    let hasPayload = false;
    if (clipboard?.read) {
      try {
        const items = await clipboard.read();
        if (!context.isCurrent()) return false;
        for (const item of items) {
          for (const type of item.types) {
            if (type !== 'text/plain' && type !== 'text/html' && type !== 'text/rtf'
              && !type.startsWith('image/')) continue;
            const blob = await item.getType(type);
            if (!context.isCurrent()) return false;
            if (type.startsWith('image/')) {
              data.items.add(new File([blob], 'clipboard-image', { type }));
              hasPayload = true;
            } else {
              const value = await blob.text();
              if (!context.isCurrent()) return false;
              if (value) { data.setData(type, value); hasPayload = true; }
            }
          }
        }
      } catch (error) {
        if (!context.isCurrent()) return false;
        // WebViews with only plain clipboard support still get a real OS read.
        if (hasPayload || !clipboard.readText) throw error;
        const text = await clipboard.readText();
        if (!context.isCurrent()) return false;
        if (text) { data.setData('text/plain', text); hasPayload = true; }
      }
    } else if (clipboard?.readText) {
      const text = await clipboard.readText();
      if (!context.isCurrent()) return false;
      if (text) { data.setData('text/plain', text); hasPayload = true; }
    } else {
      throw new Error('클립보드를 읽을 수 없습니다. 다시 복사한 뒤 붙여넣어 주세요.');
    }
    if (!context.isCurrent() || !hasPayload) return false;
    context.dispose();
    self.onPaste(new ClipboardEvent('paste', { clipboardData: data }));
    return true;
  } finally {
    context.dispose();
  }
}
