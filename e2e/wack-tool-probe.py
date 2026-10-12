"""Observe stock WACK tool architecture; product qualification remains separate."""
import argparse,hashlib,json,subprocess
from pathlib import Path
from native_architecture import WindowsProbe

def main():
 p=argparse.ArgumentParser();p.add_argument('--exe',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
 raw=a.exe.read_bytes();offset=int.from_bytes(raw[60:64],'little');machine=int.from_bytes(raw[offset+4:offset+6],'little');a.out.mkdir(parents=True,exist_ok=False)
 proc=subprocess.Popen([str(a.exe),'/?'],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
 result={'scope':'stock SDK tool, separate from native ARM product proof','productQualified':False,'storeCertified':False,'toolSha256':hashlib.sha256(raw).hexdigest(),'toolPeMachine':machine}
 try:
  result['process']=WindowsProbe().inspect(proc.pid,int(proc._handle));data,_=proc.communicate(timeout=30)
  if len(data)>1024*1024:raise ValueError('SDK help exceeds bound')
  (a.out/'help.txt').write_bytes(data);result.update(helpExitCode=proc.returncode,ordinaryExit=True)
  result.update(processObserved=True,helpExitedZero=proc.returncode==0)
 finally:
  if proc.poll() is None:proc.kill();proc.wait(timeout=10);result.update(passed=False,ordinaryExit=False)
  (a.out/'process.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
if __name__=='__main__':main()
