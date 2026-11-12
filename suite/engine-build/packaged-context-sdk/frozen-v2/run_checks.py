"""NUL child output, fixed synthetic environment, bounded numeric result only."""
from pathlib import Path
import hashlib,io,json,subprocess,sys,time,unittest
BASE=Path(__file__).resolve().parent
RUNTIME=('context_observer.hpp','context_observer_windows.cpp','observation_contract.py')
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def sources():
    paths=[BASE/p for p in RUNTIME]+[BASE/'run_checks.py']+sorted((BASE/'tests').glob('*.py'))+[BASE/'tests/core_tests.cpp']
    return {str(p.relative_to(BASE)):digest(p) for p in paths}
def main():
    if len(sys.argv)!=3 or sys.argv[1] not in ('--output','--numeric-child'):return 2
    output=Path(sys.argv[2]).absolute()
    if output.parent!=BASE or output.exists() or not output.name.startswith('validation-') or output.suffix!='.json':return 2
    if sys.argv[1]=='--numeric-child':
        before=sources();sys.path[:0]=[str(BASE),str(BASE/'tests')];start=time.monotonic()
        result=unittest.TextTestRunner(stream=io.StringIO()).run(unittest.defaultTestLoader.discover(str(BASE/'tests')))
        report=dict(schemaVersion=1,kind='portable-observer-candidate-verification',tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped),elapsedMs=round((time.monotonic()-start)*1000),failedMethods=[getattr(t,'_testMethodName',type(t).__name__)for t,e in result.failures+result.errors],sourceHashes=before,sourceUnchanged=before==sources(),actualWindowsExecuted=False,nativeSdkCompiled=False,qualification=False,canService=False)
        raw=json.dumps(report,sort_keys=True,separators=(',',':')).encode();
        if len(raw)>65536:return 3
        with output.open('xb') as stream:stream.write(raw)
        return 0 if result.wasSuccessful() and report['sourceUnchanged'] else 1
    child=subprocess.Popen([sys.executable,'-I','-B',str(Path(__file__).resolve()),'--numeric-child',str(output)],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env={'PATH':'/usr/bin:/bin','PYTHONUTF8':'1'},close_fds=True)
    deadline=time.monotonic()+60
    while child.poll() is None and time.monotonic()<deadline:time.sleep(.02)
    if child.poll() is None:
        print(json.dumps(dict(childExited=False,verificationPassed=False,forcedCleanup=False,preservationRequired=True)));return 124
    if not output.is_file() or not 0<output.stat().st_size<=65536:return 3
    value=json.loads(output.read_bytes());print(json.dumps({k:value[k]for k in ('tests','failures','errors','skipped','elapsedMs','sourceUnchanged','actualWindowsExecuted','nativeSdkCompiled','qualification','canService')}));return child.returncode
if __name__=='__main__':raise SystemExit(main())
