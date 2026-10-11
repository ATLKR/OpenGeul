import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { UpdateNotice } from './update-notice';

class FakeElement {
  className = '';
  textContent = '';
  hidden = false;
  disabled = false;
  type = '';
  dataset: Record<string, string> = {};
  children: FakeElement[] = [];
  private listeners = new Map<string, Array<() => void>>();

  append(...children: FakeElement[]): void {
    this.children.push(...children);
  }

  appendChild(child: FakeElement): FakeElement {
    this.children.push(child);
    return child;
  }

  replaceChildren(...children: FakeElement[]): void {
    this.children = [...children];
  }

  addEventListener(type: string, listener: () => void): void {
    const listeners = this.listeners.get(type) ?? [];
    listeners.push(listener);
    this.listeners.set(type, listeners);
  }

  click(): void {
    this.listeners.get('click')?.forEach((listener) => {
      listener();
    });
  }
}

class FakeDocument {
  body = new FakeElement();

  createElement(): FakeElement {
    return new FakeElement();
  }
}

function getNoticeRoot(document: FakeDocument): FakeElement {
  const root = document.body.children[0];
  if (!root) throw new Error('missing notice root');
  return root;
}

describe('Store update notice', () => {
  let fakeDocument: FakeDocument;
  beforeEach(() => {
    fakeDocument = new FakeDocument();
    (globalThis as { document?: Document }).document = fakeDocument as unknown as Document;
  });
  afterEach(() => { delete (globalThis as { document?: Document }).document; });

  it('asks about the Store and opens it only after an explicit button click', async () => {
    const openStore = vi.fn().mockResolvedValue(undefined);
    const notice = new UpdateNotice({ openStore });
    notice.setState({ status: 'available', version: '1.1.4.0' });
    const root = getNoticeRoot(fakeDocument);
    const [title, body, meta, , actions] = root.children;
    expect(root.hidden).toBe(false);
    expect(title.textContent).toBe('새 버전 1.1.4.0 사용 가능');
    expect(body.textContent).toBe('Microsoft Store에서 업데이트하시겠습니까?');
    expect(meta.textContent).toBe('Store 페이지를 엽니다. 문서를 닫거나 앱을 다시 시작하지 않습니다.');
    expect(openStore).not.toHaveBeenCalled();
    expect(actions.children.map((button) => button.textContent)).toEqual(['Microsoft Store 열기', '나중에']);
    actions.children[0].click();
    await flush();
    expect(openStore).toHaveBeenCalledOnce();
    expect(root.dataset.state).toBe('available');
    expect(root.hidden).toBe(false);
  });

  it('prevents a second Store request while the first is pending even after a state event', async () => {
    let finish!: () => void;
    const openStore = vi.fn(() => new Promise<void>((resolve) => { finish = resolve; }));
    const notice = new UpdateNotice({ openStore });
    notice.setState({ status: 'available', version: '1.1.4.0' });
    const root = getNoticeRoot(fakeDocument);
    root.children[4].children[0].click();
    notice.setState({ status: 'available', version: '1.1.4.0' });
    root.children[4].children[0].click();
    expect(openStore).toHaveBeenCalledOnce();
    expect(root.children[4].children.every((button) => button.disabled)).toBe(true);
    finish(); await flush();
    expect(root.children[4].children.every((button) => !button.disabled)).toBe(true);
  });

  it('reports a Store opening error without offering install or restart', async () => {
    const notice = new UpdateNotice({ openStore: vi.fn().mockRejectedValue(new Error('연결 끊김')) });
    notice.setState({ status: 'available', version: '1.1.4.0' });
    const root = getNoticeRoot(fakeDocument);
    root.children[4].children[0].click(); await flush();
    expect(root.children[3].hidden).toBe(false);
    expect(root.children[3].textContent).toBe('Microsoft Store를 열지 못했습니다: 연결 끊김');
    expect(root.children[4].children.map((button) => button.textContent)).toEqual(['Microsoft Store 열기', '나중에']);
  });

  it('waits for persisted dismissal then lets a manual result show the same version again', async () => {
    let finish!: () => void;
    const dismissUpdate = vi.fn(() => new Promise<void>((resolve) => { finish = resolve; }));
    const notice = new UpdateNotice({ dismissUpdate });
    notice.setState({ status: 'available', version: '1.1.4.0' });
    const root = getNoticeRoot(fakeDocument);
    root.children[4].children[1].click();
    expect(dismissUpdate).toHaveBeenCalledOnce();
    expect(root.hidden).toBe(false);
    finish(); await flush(); expect(root.hidden).toBe(true);
    notice.setState({ status: 'idle' }); // The native automatic check keeps a dismissed version hidden.
    expect(root.hidden).toBe(true);
    notice.setState({ status: 'available', version: '1.1.4.0' }); // Manual check bypasses native dismissal.
    expect(root.hidden).toBe(false);
  });

  it('keeps the notice visible if saving the later choice fails', async () => {
    const notice = new UpdateNotice({ dismissUpdate: vi.fn().mockRejectedValue(new Error('설정 저장 거부')) });
    notice.setState({ status: 'available', version: '1.1.4.0' });
    const root = getNoticeRoot(fakeDocument);
    root.children[4].children[1].click(); await flush();
    expect(root.hidden).toBe(false);
    expect(root.children[3].textContent).toBe('나중에 알림 설정을 저장하지 못했습니다: 설정 저장 거부');
  });

  it('does not hide a newer version when an older dismissal finishes', async () => {
    let finish!: () => void;
    const notice = new UpdateNotice({ dismissUpdate: () => new Promise<void>((resolve) => { finish = resolve; }) });
    notice.setState({ status: 'available', version: '1.1.4.0' });
    const root = getNoticeRoot(fakeDocument);
    root.children[4].children[1].click();
    notice.setState({ status: 'available', version: '1.1.5.0' });
    finish(); await flush();
    expect(root.hidden).toBe(false);
    expect(root.children[0].textContent).toBe('새 버전 1.1.5.0 사용 가능');
  });

  it('keeps a fresh manual result visible when an older dismissal of the same version finishes', async () => {
    let finish!: () => void;
    const notice = new UpdateNotice({ dismissUpdate: () => new Promise<void>((resolve) => { finish = resolve; }) });
    notice.setState({ status: 'available', version: '1.1.4.0' });
    const root = getNoticeRoot(fakeDocument);
    root.children[4].children[1].click();
    notice.setState({ status: 'available', version: '1.1.4.0' }); // A concurrent File-menu manual check.
    finish(); await flush();
    expect(root.hidden).toBe(false);
    expect(root.children[1].textContent).toBe('Microsoft Store에서 업데이트하시겠습니까?');
  });

  it('does not attach an older action error to a fresh same-version result', async () => {
    let reject!: (error: Error) => void;
    const notice = new UpdateNotice({ openStore: () => new Promise<void>((_, fail) => { reject = fail; }) });
    notice.setState({ status: 'available', version: '1.1.4.0' });
    const root = getNoticeRoot(fakeDocument);
    root.children[4].children[0].click();
    notice.setState({ status: 'available', version: '1.1.4.0' });
    reject(new Error('이전 요청 실패')); await flush();
    expect(root.children[3].hidden).toBe(true);
    expect(root.children[3].textContent).toBe('');
  });

  it('rechecks after a manual error and requires another explicit Store choice', async () => {
    const openStore = vi.fn();
    const checkUpdates = vi.fn().mockResolvedValue({ status: 'available', version: '1.1.4.0' });
    const notice = new UpdateNotice({ openStore, checkUpdates });
    notice.setState({ status: 'error', version: '1.1.3.0', message: '연결 실패' });
    const root = getNoticeRoot(fakeDocument);
    expect(root.children[0].textContent).toBe('업데이트 확인 실패');
    expect(root.children[4].children[0].textContent).toBe('다시 확인');
    root.children[4].children[0].click(); await flush();
    expect(checkUpdates).toHaveBeenCalledOnce();
    expect(openStore).not.toHaveBeenCalled();
    expect(root.children[1].textContent).toBe('Microsoft Store에서 업데이트하시겠습니까?');
  });

  it('does not replace a newer event with an older pending recheck result', async () => {
    let finish!: (state: { status: 'available'; version: string }) => void;
    const notice = new UpdateNotice({ checkUpdates: () => new Promise((resolve) => { finish = resolve; }) });
    notice.setState({ status: 'error', version: '1.1.3.0', message: '연결 실패' });
    const root = getNoticeRoot(fakeDocument);
    root.children[4].children[0].click();
    notice.setState({ status: 'available', version: '1.1.5.0' });
    finish({ status: 'available', version: '1.1.4.0' }); await flush();
    expect(root.children[0].textContent).toBe('새 버전 1.1.5.0 사용 가능');
  });

  it('shows a rejected recheck error and does not start a Store action', async () => {
    const notice = new UpdateNotice({ checkUpdates: vi.fn().mockRejectedValue(new Error('서버 응답 없음')) });
    notice.setState({ status: 'error', version: '1.1.3.0', message: '연결 실패' });
    const root = getNoticeRoot(fakeDocument);
    root.children[4].children[0].click(); await flush();
    expect(root.children[3].textContent).toBe('업데이트를 확인하지 못했습니다: 서버 응답 없음');
    expect(root.hidden).toBe(false);
  });
});

async function flush(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}
