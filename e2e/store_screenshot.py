"""Capture the real packaged editor with synthetic text on a disposable runner."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path

from prepare_payload import stream_hash, verify_checksums


def capture_expected_sha(provenance):
    runtime = (provenance['architectures']['x64']['runtimeSha256']
               if provenance.get('formatVersion') == 2 else provenance['runtimeSha256'])
    return runtime['OpenGeul.exe']


def capture(executable: Path, output: Path):
    if os.name != 'nt' or os.environ.get('GITHUB_ACTIONS') != 'true':
        raise RuntimeError('Store capture requires a disposable Windows GitHub runner')
    from driver import Session, digest, edit, until
    import win32api
    import win32con
    from pywinauto import Desktop

    executable=executable.resolve(); output=output.resolve()
    verify_checksums(output)
    provenance=json.loads((output/'store-provenance.json').read_text(encoding='utf-8'))
    expected=capture_expected_sha(provenance)
    if digest(executable) != expected: raise ValueError('Screenshot executable differs from the Store package')
    original=win32api.EnumDisplaySettings(None,win32con.ENUM_CURRENT_SETTINGS)
    changed=False; session=None
    try:
        if original.PelsWidth < 1600 or original.PelsHeight < 900:
            candidates=[]
            for index in range(512):
                try: mode=win32api.EnumDisplaySettings(None,index)
                except win32api.error: break
                if mode.PelsWidth >= 1600 and mode.PelsHeight >= 900:
                    candidates.append(mode)
            if not candidates: raise RuntimeError('The runner has no Store-sized display mode')
            mode=min(candidates,key=lambda item:item.PelsWidth*item.PelsHeight)
            result=win32api.ChangeDisplaySettings(mode,0)
            if result!=win32con.DISP_CHANGE_SUCCESSFUL:
                raise RuntimeError(f'The runner rejected the Store-sized display mode: {result}')
            changed=True
        actual=win32api.EnumDisplaySettings(None,win32con.ENUM_CURRENT_SETTINGS)
        if actual.PelsWidth<1600 or actual.PelsHeight<900:
            raise RuntimeError('The actual runner display is smaller than the required capture area')
        session=Session('native',Path('.work/store-capture'),None,executable=executable)
        windows=[window for window in Desktop(backend='win32').windows(process=session.proc.pid,visible_only=True)
                 if window.class_name()=='Tauri Window']
        if len(windows)!=1: raise AssertionError('Expected exactly one owned OpenGeul app window')
        window=windows[0]; window.restore(); window.move_window(x=0,y=0,width=1366,height=768); window.set_focus()
        until(lambda: window.rectangle().width()>=1366 and window.rectangle().height()>=768)
        rectangle=window.rectangle()
        if rectangle.left<0 or rectangle.top<0 or rectangle.right>actual.PelsWidth or rectangle.bottom>actual.PelsHeight:
            raise ValueError('The native OpenGeul window is outside the actual display')
        sample='OpenGeul 문서 작성 예시\n\n회의 메모\n프로젝트: 함께 만드는 문서\n일정: 월요일 오전 10시\n\n오늘의 작업\n문서 내용을 확인하고 필요한 부분을 수정합니다.\nHWP와 HWPX 문서를 OpenGeul에서 편집합니다.'
        edit(session.page,sample)
        session.page.wait_for_function('document.title.startsWith("• ")',timeout=30000)
        session.page.evaluate('document.fonts.ready')
        session.page.evaluate('new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
        if session.page.locator('dialog[open]').count(): raise AssertionError('A dialog covers the editor screenshot')
        image=window.capture_as_image()
        if image.width < 1366 or image.height < 768: raise ValueError('Native screenshot is smaller than the Store minimum')
        if all(high-low<=2 for low,high in image.convert('RGB').getextrema()):
            raise ValueError('Native screenshot is blank; the runner desktop did not render the app')
        image.save(output/'OpenGeul-editor.png')
        metadata={'scope':'Real native OpenGeul window with text inserted through the normal editor UI',
                  'executableSha256':expected,'sourceCommit':provenance['sourceCommit'],
                  'width':image.width,'height':image.height,'syntheticText':sample,
                  'runId':os.environ.get('GITHUB_RUN_ID')}
        (output/'screenshot-provenance.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    finally:
        try:
            if session: session.close()
        finally:
            if changed: win32api.ChangeDisplaySettings(original,0)
    if digest(executable)!=expected: raise ValueError('Screenshot capture changed the executable')
    hashes=[]
    for path in sorted(output.iterdir()):
        if path.name=='SHA256SUMS.txt': continue
        with path.open('rb') as stream: hashes.append(stream_hash(stream)+'  '+path.name+'\n')
    (output/'SHA256SUMS.txt').write_text(''.join(hashes),encoding='utf-8')
    verify_checksums(output)
    print(f'Captured real native app window: {image.width} x {image.height}')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(); capture(args.exe,args.output)
