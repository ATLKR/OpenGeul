import { readToolbarLabels, writeToolbarLabels } from './opengeul-toolbar-preferences';
import './opengeul-toolbar-labels.css';

const toolbar = document.querySelector<HTMLElement>('#icon-toolbar');
const menu = document.querySelector<HTMLElement>('[data-menu="view"] > .menu-dropdown');
if (toolbar && menu && !document.getElementById('opengeul-toolbar-labels')) {
  // Retain accessible names and hover descriptions even when visible labels are hidden.
  for (const button of toolbar.querySelectorAll<HTMLButtonElement>('button[title]')) {
    if (!button.hasAttribute('aria-label')) button.setAttribute('aria-label', button.title);
  }
  const label = document.createElement('label');
  label.className = 'md-item opengeul-toolbar-label-toggle';
  const checkbox = document.createElement('input');
  checkbox.type = 'checkbox';
  checkbox.id = 'opengeul-toolbar-labels';
  label.append(checkbox, document.createTextNode('도구모음 글자 표시'));
  menu.append(label);
  let visible = true;
  try { visible = readToolbarLabels(window.localStorage); } catch { /* Storage can be disabled by policy. */ }
  const apply = (value: boolean) => {
    checkbox.checked = value;
    toolbar.classList.toggle('opengeul-icons-only', !value);
    window.dispatchEvent(new Event('resize'));
  };
  checkbox.addEventListener('change', () => {
    apply(checkbox.checked);
    try { writeToolbarLabels(window.localStorage, checkbox.checked); } catch { /* Session-only preference. */ }
  });
  apply(visible);
}
