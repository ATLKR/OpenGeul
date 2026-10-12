"""기본 stock SDK appcert의 실제 x64 process를 관측한다. WACK 결과는 별도이다."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
from native_architecture import WindowsProbe, verify_executable


def observe(executable, *, probe=None, process_factory=subprocess.Popen):
    executable=Path(executable)
    machine=verify_executable(executable,'x64')
    raw=executable.read_bytes()
    process=process_factory([str(executable),'/?'],stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    try:
        if not hasattr(process,'_handle') or type(process.pid) is not int or process.pid <= 0:
            raise ValueError('소유한 SDK process handle/PID가 필요합니다')
        actual=(probe or WindowsProbe()).inspect(process.pid,int(process._handle))
        if (any(type(actual.get(key)) is not int for key in ('processId','processMachine','nativeMachine'))
                or actual.get('processId') != process.pid or actual.get('processMachine') != 0
                or actual.get('nativeMachine') != 0x8664):
            raise ValueError('stock SDK는 x64 호스트의 실제 네이티브 process여야 합니다')
        image=Path(actual['imagePath'])
        if not image.is_file() or not image.samefile(executable):
            raise ValueError('SDK process가 다른 실행 파일을 사용합니다')
        help_bytes,_=process.communicate(timeout=30)
        if not isinstance(help_bytes,bytes) or len(help_bytes)>1024*1024 or type(process.returncode) is not int:
            raise ValueError('SDK process가 정상적으로 종료하지 않았거나 도움말 크기를 초과했습니다')
        if executable.read_bytes() != raw:
            raise ValueError('SDK process 관측 중 도구 바이트가 변경되었습니다')
        # /? may ordinarily exit -1. This is process provenance, never WACK PASS.
        return {'path':str(executable.resolve()),'sha256':hashlib.sha256(raw).hexdigest(),
                'bytes':len(raw),'peMachine':machine,'processId':process.pid,
                'processMachine':actual['processMachine'],'nativeMachine':actual['nativeMachine'],
                'ordinaryExit':True,'helpExitCode':process.returncode,
                'observedAt':datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}
    finally:
        if process.poll() is None:
            process.kill();process.wait(timeout=10)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--exe',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    if args.output.exists() or args.output.is_symlink():raise ValueError('기존 SDK process 증거를 재사용하지 않습니다')
    result=observe(args.exe)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('xb') as stream:
        stream.write((json.dumps(result,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))


if __name__=='__main__':main()
