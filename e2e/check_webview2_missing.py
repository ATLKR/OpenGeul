"""Check real missing-runtime instructions without changing the host installation."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile


def check(executable: Path, output: Path):
    if os.name!='nt' or os.environ.get('GITHUB_ACTIONS')!='true':
        raise RuntimeError('Missing-runtime check requires a disposable Windows runner')
    from pywinauto import Desktop
    executable=executable.resolve();output.mkdir(parents=True,exist_ok=True)
    result={'success':False,'executableSha256':hashlib.sha256(executable.read_bytes()).hexdigest(),
            'scope':'Per-process empty WebView2 folder override; host runtime unchanged'}
    process=None
    try:
        with tempfile.TemporaryDirectory(prefix='opengeul-missing-webview2-') as empty:
            environment=dict(os.environ,WEBVIEW2_BROWSER_EXECUTABLE_FOLDER=empty)
            process=subprocess.Popen([str(executable)],cwd=executable.parent,env=environment)
            dialog=Desktop(backend='win32').window(process=process.pid,class_name='#32770',title='OpenGeul')
            dialog.wait('visible',timeout=20)
            wrapper=dialog.wrapper_object()
            text='\n'.join(item.window_text() for item in wrapper.descendants(class_name='Static'))
            if 'WebView2 Runtime을 찾을 수 없습니다' not in text or 'Evergreen Runtime을 설치' not in text:
                raise AssertionError('Missing-runtime instructions were not displayed in Korean')
            if 'https://developer.microsoft.com/microsoft-edge/webview2/#download-section' not in text:
                raise AssertionError('Missing-runtime instructions have no official installation URL')
            wrapper.capture_as_image().save(output/'webview2-missing.png')
            dialog.child_window(control_id=7,class_name='Button').click_input()
            if process.wait(timeout=20)!=0: raise AssertionError('Declining installation did not exit normally')
            result.update(success=True,dialogText=text,exitCode=process.returncode)
    finally:
        try:
            if process and process.poll() is None:
                subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,timeout=20)
        finally:
            (output/'webview2-missing.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Missing WebView2: real Korean installation dialog and normal exit verified.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();check(args.exe,args.output)
