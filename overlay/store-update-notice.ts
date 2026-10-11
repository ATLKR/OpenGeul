import type { DesktopUpdateState } from '@/core/tauri-bridge';

export interface UpdateNoticeActions {
  openStore?: () => Promise<void>;
  dismissUpdate?: () => Promise<void>;
  checkUpdates?: () => Promise<DesktopUpdateState>;
}

export class UpdateNotice {
  private readonly actions: UpdateNoticeActions;
  private readonly root: HTMLDivElement;
  private readonly titleEl: HTMLHeadingElement;
  private readonly bodyEl: HTMLParagraphElement;
  private readonly metaEl: HTMLParagraphElement;
  private readonly errorEl: HTMLParagraphElement;
  private readonly actionsEl: HTMLDivElement;
  private state: DesktopUpdateState = { status: 'idle' };
  private stateRevision = 0;
  private actionPending = false;
  private actionError: string | null = null;

  constructor(actions: UpdateNoticeActions = {}) {
    this.actions = actions;
    this.root = document.createElement('div');
    this.root.className = 'update-notice';
    this.root.hidden = true;

    this.titleEl = document.createElement('h2');
    this.titleEl.className = 'update-notice__title';

    this.bodyEl = document.createElement('p');
    this.bodyEl.className = 'update-notice__body';

    this.metaEl = document.createElement('p');
    this.metaEl.className = 'update-notice__meta';

    this.errorEl = document.createElement('p');
    this.errorEl.className = 'update-notice__error';

    this.actionsEl = document.createElement('div');
    this.actionsEl.className = 'update-notice__actions';

    this.root.append(this.titleEl, this.bodyEl, this.metaEl, this.errorEl, this.actionsEl);
    document.body.appendChild(this.root);
  }

  setState(state: DesktopUpdateState): void {
    this.state = state;
    this.stateRevision += 1;
    this.actionError = null;
    this.render();
  }

  private render(): void {
    if (this.state.status !== 'available' && this.state.status !== 'error') {
      this.root.hidden = true;
      return;
    }
    this.root.hidden = false;
    this.root.dataset.state = this.state.status;
    this.actionsEl.replaceChildren();

    if (this.state.status === 'available') {
      this.titleEl.textContent = `새 버전 ${this.state.version} 사용 가능`;
      this.bodyEl.textContent = 'Microsoft Store에서 업데이트하시겠습니까?';
      this.setOptionalText(this.metaEl, 'Store 페이지를 엽니다. 문서를 닫거나 앱을 다시 시작하지 않습니다.');
      this.actionsEl.append(
        this.createActionButton('Microsoft Store 열기', true, () => {
          void this.runAction(this.actions.openStore, 'Microsoft Store를 열지 못했습니다');
        }),
        this.createActionButton('나중에', false, () => { void this.dismiss(); }),
      );
    } else {
      this.titleEl.textContent = '업데이트 확인 실패';
      this.bodyEl.textContent = this.state.message;
      this.setOptionalText(this.metaEl, null);
      this.actionsEl.append(
        this.createActionButton('다시 확인', true, () => { void this.recheck(); }),
        this.createActionButton('닫기', false, () => { void this.dismiss(); }),
      );
    }
    this.setOptionalText(this.errorEl, this.actionError);
  }

  private createActionButton(label: string, primary: boolean, onClick: () => void): HTMLButtonElement {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `update-notice__button${primary ? ' update-notice__button--primary' : ''}`;
    button.textContent = label;
    button.disabled = this.actionPending;
    button.addEventListener('click', () => { if (!this.actionPending) onClick(); });
    return button;
  }

  private async dismiss(): Promise<void> {
    const revision = this.stateRevision;
    await this.runAction(this.actions.dismissUpdate && (async () => {
      await this.actions.dismissUpdate!();
      if (this.stateRevision === revision) this.setState({ status: 'idle' });
    }), '나중에 알림 설정을 저장하지 못했습니다');
  }

  private async recheck(): Promise<void> {
    const revision = this.stateRevision;
    await this.runAction(this.actions.checkUpdates && (async () => {
      const state = await this.actions.checkUpdates!();
      if (this.stateRevision === revision) this.setState(state);
    }), '업데이트를 확인하지 못했습니다');
  }

  private async runAction(action: (() => Promise<void>) | undefined, errorPrefix: string): Promise<void> {
    if (!action || this.actionPending) return;
    const revision = this.stateRevision;
    this.actionPending = true;
    this.actionError = null;
    this.render();
    try {
      await action();
    } catch (error) {
      if (this.stateRevision === revision) this.actionError = `${errorPrefix}: ${this.errorText(error)}`;
    } finally {
      this.actionPending = false;
      this.render();
    }
  }

  private setOptionalText(element: HTMLElement, text: string | null): void {
    element.textContent = text ?? '';
    element.hidden = !text;
  }

  private errorText(error: unknown): string {
    return error instanceof Error && error.message ? error.message : String(error);
  }
}
