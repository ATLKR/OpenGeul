"""Run all original password cases with a reviewed helper against failed Source61 bytes."""
from __future__ import annotations
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('password61_inputs', ROOT/'probe/download-package61.py')
transport = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(transport)
NATIVE_SHA256 = '63259642f9df5c39dd5ee3aabf0e01a0ff3892f9fbf2021c8342db0860fe6651'
CASES = ['retry-cancel-hwp','retry-cancel-hwpx','save-hwp-to-hwp','save-hwp-to-hwpx',
         'save-hwpx-to-hwp','save-hwpx-to-hwpx','dirty-close-replacement-hwp','dirty-close-replacement-hwpx']

def require(condition, message):
    if not condition: raise ValueError(message)

def validate_context(root):
    receipt = transport.components.read_json(root/'evidence/source.json')
    expected = {'qualification':'native-password-diagnostic-only','diagnosticOnly':True,'qualifiedPackage':False,
                'sourceQualified':False,'fullSourceQualified':False,'sourceCommit':transport.SOURCE,
                'sourceRun':transport.RUN_ID,'producerAttempt':1,'producerConclusion':'failure'}
    require(all(type(receipt.get(k)) is type(v) and receipt.get(k)==v for k,v in expected.items()), 'Diagnostic source receipt differs')
    for role, record in transport.RUNTIMES.items():
        path=root/'runtime'/record['path'];transport.components.regular(path)
        require(path.stat().st_size==record['size'] and transport.components.sha(path)==record['sha256'], 'Diagnostic runtime differs')
    require(receipt.get('runtime')==transport.RUNTIMES, 'Diagnostic runtime receipt differs')
    for role,spec in transport.ARTIFACTS.items():
        row=receipt.get('artifacts',{}).get(role,{})
        require(all(row.get(k)==v for k,v in {'id':spec['id'],'name':spec['name'],'bytes':spec['size'],'sha256':spec['sha256']}.items()), 'Diagnostic artifact receipt differs')
    helper=root/'e2e/password/native.py'
    require(transport.components.sha(helper)==NATIVE_SHA256, 'Password helper is not the reviewed selector fix')
    commit=os.environ.get('GITHUB_SHA','');run=os.environ.get('GITHUB_RUN_ID','')
    attempt=os.environ.get('GITHUB_RUN_ATTEMPT','');runner=os.environ.get('DIAGNOSTIC_OS')
    require(os.environ.get('GITHUB_REPOSITORY')==transport.REPOSITORY
            and os.environ.get('GITHUB_REF')=='refs/heads/diagnostic/native-password-61'
            and os.environ.get('GITHUB_EVENT_NAME')=='workflow_dispatch'
            and re.fullmatch(r'[0-9a-f]{40}',commit) and commit!=transport.SOURCE
            and re.fullmatch(r'[1-9][0-9]*',run) and re.fullmatch(r'[1-9][0-9]*',attempt)
            and runner in ('windows-2022','windows-2025'), 'Diagnostic checkout/run binding differs')
    return {'diagnosticOnly':True,'sourceQualified':False,'fullSourceQualified':False,
            'compiledSourceCommit':transport.SOURCE,'sourceRun':transport.RUN_ID,'producerAttempt':1,
            'sourceRunConclusion':'failure','helperCommit':commit,'diagnosticRunId':run,'diagnosticRunAttempt':attempt,
            'runner':runner,'nativeHelperSha256':NATIVE_SHA256,
            'driverSha256':transport.components.sha(root/'e2e/driver.py'),
            'compiledRuntime':transport.RUNTIMES,'compiledArtifacts':receipt['artifacts']}

def load_native():
    spec=importlib.util.spec_from_file_location('source61_password_native',ROOT/'e2e/password/native.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def validate_results(value, code):
    require(value.get('sourceCommit')==transport.SOURCE and value.get('buildRunId')==str(transport.RUN_ID)
            and value.get('editorSha256')==transport.RUNTIMES['editor']['sha256']
            and value.get('cliSha256')==transport.RUNTIMES['cli']['sha256']
            and value.get('mode')=='native-password' and value.get('expectedTests')==8, 'Password result identity differs')
    rows=value.get('tests');require(isinstance(rows,list) and len(rows)==8
            and len({row.get('test') for row in rows})==8 and {row.get('test') for row in rows}==set(CASES)
            and all(row.get('status') in ('passed','failed') for row in rows), 'Original eight password cases are incomplete')
    passed=all(row['status']=='passed' for row in rows)
    require(type(value.get('success')) is bool and value['success']==passed and code==(0 if passed else 1), 'Password failure outcome differs')

def run(root=ROOT):
    root=Path(root).resolve();metadata=validate_context(root)
    output=root/'evidence/password-native';transport.components.fresh(output)
    envelope=root/'evidence/password-diagnostic.json';transport.components.fresh(envelope)
    envelope.write_text(json.dumps({**metadata,'status':'running'},indent=2)+'\n')
    args=SimpleNamespace(source_root=root,fixtures=root/'password-fixtures',exe=root/'runtime/OpenGeul.exe',
                         output=output,expected_source=transport.SOURCE,expected_run=str(transport.RUN_ID))
    try:
        code=load_native().Qualification(args).run()
        value=transport.components.read_json(output/'results.json');validate_results(value,code)
        value.update(diagnosticOnly=True,sourceQualified=False,fullSourceQualified=False,diagnostic=metadata)
        (output/'results.json').write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        envelope.write_text(json.dumps({**metadata,'status':'passed' if code==0 else 'failed','expectedTests':8,
                                       'passed':sum(row['status']=='passed' for row in value['tests'])},indent=2)+'\n')
        return code
    except Exception:
        envelope.write_text(json.dumps({**metadata,'status':'failed','reason':'Original password suite did not produce valid complete evidence'},indent=2)+'\n')
        raise

def main():
    try:return run()
    except Exception:
        print('Source61 password diagnostic failed.',file=sys.stderr);return 1

if __name__=='__main__':raise SystemExit(main())
