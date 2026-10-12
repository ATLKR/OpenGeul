import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AboutDialog } from './about-dialog';
import { AboutDialog as UpstreamAboutDialog } from '@/upstream/ui';

class Element {
  constructor(readonly tagName: string) {}
  className = '';
  style: Record<string, string> = {};
  parentNode: Element | null = null;
  children: Element[] = [];
  private text = '';
  get textContent(): string { return this.text + this.children.map(child => child.textContent).join(''); }
  set textContent(value: string) { this.text = value; this.children = []; }
  get classList() { return { add: (name: string) => { this.className += ' ' + name; } }; }
  addEventListener(): void {}
  focus(): void {}
  replaceChildren(): void { this.children = []; }
  remove(): void {
    if (this.parentNode) this.parentNode.children = this.parentNode.children.filter(child => child !== this);
    this.parentNode = null;
  }
  get nextSibling(): Element | null {
    return this.parentNode?.children[this.parentNode.children.indexOf(this) + 1] ?? null;
  }
  appendChild(child: Element): Element {
    child.parentNode = this;
    this.children.push(child);
    return child;
  }
  insertBefore(child: Element, before: Element | null): Element {
    if (before === null) return this.appendChild(child);
    child.parentNode = this;
    this.children.splice(this.children.indexOf(before), 0, child);
    return child;
  }
  querySelector(selector: string): Element | null {
    for (const child of this.children) {
      if (selector.startsWith('.') ? child.className.split(' ').includes(selector.slice(1)) : child.tagName === selector) return child;
      const found = child.querySelector(selector);
      if (found) return found;
    }
    return null;
  }
}

class Input extends Element {
  value = '';
  readOnly = false;
}
class TextArea extends Element {}
const captured = new Map<string, (event: unknown) => void>();
let documentBody: Element;

class Product extends AboutDialog {
  body(): HTMLElement { return this.createBody(); }
}
class Upstream extends UpstreamAboutDialog {
  body(): HTMLElement { return this.createBody(); }
}

beforeEach(() => {
  captured.clear();
  documentBody = new Element('body');
  vi.stubGlobal('HTMLInputElement', Input);
  vi.stubGlobal('HTMLTextAreaElement', TextArea);
  vi.stubGlobal('document', {
    body: documentBody,
    createElement: (tag: string) => tag === 'input' ? new Input(tag) : new Element(tag),
    addEventListener: (name: string, fn: (event: unknown) => void) => captured.set(name, fn),
    removeEventListener: (name: string) => captured.delete(name),
    dispatchEvent: () => true,
    querySelector: (selector: string) => documentBody.querySelector(selector),
  });
  vi.stubGlobal('__APP_VERSION__', '0.8.7');
  vi.stubGlobal('__HOP_VERSION__', '1.1.3');
});
afterEach(() => vi.unstubAllGlobals());

describe('OpenGeul 제품 정보', () => {
  it('identifies the installed product and keeps distinct upstream versions', () => {
    const body = new Product().body();
    expect(body.querySelector('.about-product-name')?.textContent).toBe('OpenGeul');
    expect(body.querySelector('.about-hop-version')?.textContent).toBe('OpenGeul 버전 1.1.3');
    expect(body.querySelector('.about-version')?.textContent).toBe('rhwp 버전 0.8.7');
    expect(body.textContent).toContain('기반 HOP 버전 0.4.5');
  });

  it('shows selectable contact details without requiring an email client or launching anything', () => {
    const body = new Product().body();
    const contact = body.querySelector('.about-opengeul-contact') as HTMLElement;
    expect(contact).not.toBeNull();
    expect(contact.textContent).toContain('문의 이메일');
    expect(contact.textContent).toContain('웹사이트');
    for (const [selector, value] of [['.about-opengeul-email', 'allenlim@allenlim.net'], ['.about-opengeul-website', 'https://opengeul.allenlim.net']]) {
      const input = contact.querySelector(selector) as HTMLInputElement;
      expect(input.value).toBe(value);
      expect(input.readOnly).toBe(true);
      expect(input.style.userSelect).toBe('text');
    }
    expect(contact.querySelector('a')).toBeNull();
    expect(contact.querySelector('button')).toBeNull();
  });

  it('preserves actual upstream specification, license and author notices', () => {
    const product = new Product().body();
    const upstream = new Upstream().body();
    for (const selector of ['.about-notice', '.about-license-title', '.about-license-table', '.about-license-note', '.about-copyright']) {
      const original = upstream.querySelector(selector)?.textContent;
      expect(original).toBeTruthy();
      expect(product.querySelector(selector)?.textContent).toBe(original);
    }
  });

  it('uses the current installed product version instead of a hardcoded release number', () => {
    vi.stubGlobal('__HOP_VERSION__', '1.2.0');
    expect(new Product().body().querySelector('.about-hop-version')?.textContent).toBe('OpenGeul 버전 1.2.0');
  });

  it('lets the actual inherited modal keep default keyboard copying in both readonly fields', () => {
    const product = new Product();
    product.show();
    for (const selector of ['.about-opengeul-email', '.about-opengeul-website']) {
      const target = documentBody.querySelector(selector);
      expect(target).toBeInstanceOf(Input);
      const preventDefault = vi.fn();
      const stopPropagation = vi.fn();
      captured.get('keydown')!({ target, key: 'c', ctrlKey: true, preventDefault, stopPropagation });
      expect(stopPropagation).toHaveBeenCalled();
      expect(preventDefault).not.toHaveBeenCalled();
    }
    product.hide();
  });
});
