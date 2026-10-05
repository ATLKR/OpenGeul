import { invoke } from '@tauri-apps/api/core';
import resources from './opengeul-font-resources';

interface LocalFont { family: string }

const button = document.createElement('button');
button.type = 'button'; button.textContent = '글꼴 도움말'; button.title = '설치된 글꼴 확인 및 공식 다운로드';
button.style.cssText = 'margin-left:auto;padding:4px 12px;font:inherit;cursor:pointer';
const host = document.getElementById('menu-bar');
if (host) host.append(button);

button.addEventListener('click', () => {
  const dialog = document.createElement('dialog');
  dialog.style.cssText = 'max-width:620px;width:85vw;padding:24px;font:16px/1.6 system-ui,sans-serif';
  const title = document.createElement('h2'); title.textContent = 'OpenGeul · 글꼴 도움말'; dialog.append(title);
  const description = document.createElement('p');
  description.textContent = 'OpenGeul은 설치된 글꼴을 사용합니다. 글꼴 파일을 제공하거나 자동으로 설치하지 않습니다. 부족한 글꼴은 아래 공식 페이지에서 내려받으세요.';
  dialog.append(description);
  for (const resource of resources) {
    const control = document.createElement('button'); control.type = 'button'; control.textContent = resource.label;
    control.style.cssText = 'display:block;margin:8px 0;padding:8px;font:inherit';
    control.addEventListener('click', async () => {
      try { await invoke('open_font_resource', { resource: resource.id }); }
      catch (error) { status.textContent = '열지 못했습니다: ' + String(error); }
    });
    dialog.append(control);
  }
  const howto = document.createElement('p');
  howto.textContent = '설치 방법: 공식 페이지에서 글꼴 받기 → ZIP 압축 풀기 → .ttf 또는 .otf 파일을 Windows 글꼴 설정에 끌어놓기 → 문서를 저장하고 OpenGeul 다시 시작. 회사 PC는 관리자 정책을 따라 주세요.';
  dialog.append(howto);
  const warning = document.createElement('p');
  warning.textContent = '대체 글꼴은 줄바꿈·표·쪽 수를 바꿀 수 있습니다. 원본을 보존하세요. 설치 여부만으로 이용 허락이 확인되는 것은 아니며 PDF 포함 권한도 별도입니다.';
  dialog.append(warning);
  const status = document.createElement('p'); status.setAttribute('role','status'); dialog.append(status);
  const refresh = document.createElement('button'); refresh.type='button'; refresh.textContent='설치 확인';
  refresh.addEventListener('click', async () => {
    try {
      const fonts = await invoke<LocalFont[]>('list_local_fonts');
      const families = new Set(fonts.map(font => font.family.toLowerCase()));
      status.textContent = ['Noto Sans KR','Noto Serif KR'].map(name => `${name}: ${families.has(name.toLowerCase()) ? '설치됨' : '찾지 못함'}`).join(' / ');
    } catch (error) { status.textContent='설치 확인 실패: '+String(error); }
  });
  dialog.append(refresh);
  const close=document.createElement('button'); close.type='button'; close.textContent='닫기'; close.style.marginLeft='12px';
  close.addEventListener('click',()=>dialog.close()); dialog.append(close);
  dialog.addEventListener('close',()=>dialog.remove()); document.body.append(dialog); dialog.showModal();
  refresh.click();
});
