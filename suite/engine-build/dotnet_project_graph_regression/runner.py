"""Explicit Linux source regressions, never an engine/SDK qualification tool."""
import argparse
import contextlib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[2]
ASSET_PINS_SHA256='2568d2231716a39f93525232f4336e7cb7ff9c32a7536f0114631d60130cbcd5'

class ClosedParser(argparse.ArgumentParser):
    def error(self,message):raise ValueError()

class NumericResult(unittest.TestResult):
    def __init__(self):super().__init__();self.rows=[]
    def addFailure(self,test,error):
        self.failures.append((test,None));self.rows.append(dict(test=test.id(),failureCode=1))
    def addError(self,test,error):
        self.errors.append((test,None));self.rows.append(dict(test=test.id(),failureCode=2))
    def addSubTest(self,test,subtest,error):
        if error is not None:
            if issubclass(error[0],AssertionError):self.addFailure(test,error)
            else:self.addError(test,error)
    def addSkip(self,test,reason):self.skipped.append((test,None));self.rows.append(dict(test=test.id(),failureCode=3))

def regular(path,limit):
    for item in (path,*path.parents):
        if item.is_symlink():raise ValueError()
    info=path.stat()
    if not path.is_file() or info.st_nlink!=1 or not 0<info.st_size<=limit:raise ValueError()
    raw=path.read_bytes()
    if len(raw)!=info.st_size:raise ValueError()
    return raw

def verify_assets():
    raw=regular(HERE/'asset-pins.json',64*1024)
    if hashlib.sha256(raw).hexdigest()!=ASSET_PINS_SHA256:raise ValueError()
    value=json.loads(raw)
    if set(value)!={'schemaVersion','kind','files'} or value['schemaVersion']!=1 or value['kind']!='public-dotnet-source-regression-assets':raise ValueError()
    seen=set()
    for row in value['files']:
        rel=Path(row['path'])
        if rel.is_absolute() or '..' in rel.parts or row['path'] in seen:raise ValueError()
        seen.add(row['path']);data=regular(HERE/rel,1024*1024)
        if len(data)!=row['bytes'] or hashlib.sha256(data).hexdigest()!=row['sha256']:raise ValueError()

def assemble_sources(destination):
    value=json.loads(regular(HERE/'fixtures/recipe-originals.json',64*1024))
    for row in value['files']:
        name=Path(row['path']);rel=Path(row['source'])
        if name.is_absolute() or rel.is_absolute() or '..' in name.parts or '..' in rel.parts:raise ValueError()
        raw=regular(REPO/rel,1024*1024)
        if len(raw)!=row['bytes'] or hashlib.sha256(raw).hexdigest()!=row['sha256']:raise ValueError()
        output=destination/name;output.parent.mkdir(parents=True,exist_ok=True)
        with output.open('xb') as stream:stream.write(raw)

def main():
    parser=ClosedParser(prog='dotnet-source-regression',description=__doc__)
    parser.add_argument('--make',required=True,type=Path)
    parser.add_argument('--pwsh',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    if sys.platform!='linux':raise ValueError() # Other hosts require a separate path-adapter verification.
    make=args.make.resolve(strict=True);pwsh=args.pwsh.resolve(strict=True)
    if not make.is_file() or not pwsh.is_file():raise ValueError()
    output=args.output.absolute()
    if output.exists() or not output.parent.is_dir() or output.parent.resolve()!=output.parent:raise ValueError()
    # Replace the mapping itself. Never copy, enumerate or print parent values.
    os.environ={'PATH':str(make.parent)+':'+str(pwsh.parent)+':/usr/bin:/bin','PYTHONUTF8':'1'}
    verify_assets();result=NumericResult();suite=unittest.TestSuite();start=time.monotonic()
    with tempfile.TemporaryDirectory(prefix='dotnet-source-',dir=output.parent) as tmp:
        owned=Path(tmp).resolve();tempfile.tempdir=str(owned)
        source=owned/'pinned-input';source.mkdir();assemble_sources(source)
        with open(os.devnull,'w') as nul,contextlib.redirect_stdout(nul),contextlib.redirect_stderr(nul):
            for name in ('test_dotnet_project_graph_source','test_dotnet_project_graph_ps'):
                spec=importlib.util.spec_from_file_location(name,HERE/'tests'/(name+'.py'))
                module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
                module.MAKE=make;module.PWSH=pwsh;module.RECIPE_INPUT=source
                suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(module))
            suite.run(result)
        tempfile.tempdir=None
    value=dict(schemaVersion=1,kind='portable-dotnet-source-regression',testsRun=result.testsRun,
        failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped),rows=result.rows,
        elapsedMs=int((time.monotonic()-start)*1000),assetPinsSha256=ASSET_PINS_SHA256,
        syntheticFixtureTree=True,originalFileBytesPinned=True,sourceArchiveComplete=False,
        sdkExecuted=False,windowsProductExecuted=False,normalSourceFullExecuted=False,
        sourceFullQualified=False,acceptanceEligible=False,nativeGuiVerified=False)
    with output.open('x') as stream:json.dump(value,stream,sort_keys=True,indent=2);stream.write('\n')
    print(json.dumps({key:value[key] for key in ('testsRun','failures','errors','skipped','elapsedMs','sdkExecuted','sourceFullQualified')},separators=(',',':')))
    return 0 if result.testsRun==22 and not result.skipped and result.wasSuccessful() else 1

if __name__=='__main__':
    try:code=main()
    except SystemExit as status:
        code=0 if status.code==0 else 1
    except BaseException:
        print('{"regressionFailureCode":1}');code=1
    raise SystemExit(code)
