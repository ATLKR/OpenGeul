import { AboutDialog as UpstreamAboutDialog } from '@/upstream/ui';

// Reviewed with config/upstream.lock.json; __HOP_VERSION__ is the product version.
const HOP_BASE_VERSION = '0.4.5';

export class AboutDialog extends UpstreamAboutDialog {
  protected override createBody(): HTMLElement {
    const body = super.createBody();
    const name = body.querySelector('.about-product-name');
    if (name) name.textContent = 'OpenGeul';
    const description = body.querySelector('.about-product-name-ko');
    if (description) description.textContent = '오픈글 · HWP/HWPX 문서 편집기';
    const version = body.querySelector('.about-version');
    if (version) version.textContent = `rhwp 버전 ${__APP_VERSION__}`;

    const productVersion = document.createElement('div');
    productVersion.className = 'about-hop-version';
    productVersion.textContent = `OpenGeul 버전 ${__HOP_VERSION__}`;
    if (version?.parentNode) version.parentNode.insertBefore(productVersion, version);
    else body.appendChild(productVersion);

    const upstream = document.createElement('div');
    upstream.className = 'about-tech';
    upstream.textContent = `기반 HOP 버전 ${HOP_BASE_VERSION}`;
    body.appendChild(upstream);

    const contact = document.createElement('div');
    contact.className = 'about-opengeul-contact';
    contact.style.textAlign = 'left';
    contact.style.marginTop = '12px';
    for (const [title, value, className] of [
      ['문의 이메일', 'allenlim@allenlim.net', 'about-opengeul-email'],
      ['웹사이트', 'https://opengeul.allenlim.net', 'about-opengeul-website'],
    ]) {
      const label = document.createElement('label');
      label.textContent = title;
      label.style.display = 'block';
      const input = document.createElement('input');
      input.className = className;
      input.type = 'text';
      input.readOnly = true;
      input.value = value;
      // The existing modal permits default keyboard copying for input elements.
      input.style.userSelect = 'text';
      input.style.width = '100%';
      input.style.font = 'inherit';
      input.style.color = 'inherit';
      input.style.background = 'transparent';
      input.style.border = '0';
      label.appendChild(input);
      contact.appendChild(label);
    }
    body.appendChild(contact);
    return body;
  }
}
