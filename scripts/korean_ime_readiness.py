"""Fail-closed hosted Korean setup policy. Preparation never qualifies product input."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path, PureWindowsPath
import re
import subprocess

CAPABILITY='Language.Basic~~~ko-KR~0.0.1.0'
SCOPE='current-user configured; target HWND/thread unverified'
GUID=r'\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}'

def need(condition,message):
    if not condition:raise ValueError(message)

def host_binding(env,expected_head,actual_head,*,platform):
    required={'GITHUB_ACTIONS':'true','RUNNER_ENVIRONMENT':'github-hosted','RUNNER_OS':'Windows',
              'GITHUB_REPOSITORY':'ATLKR/OpenGeul','GITHUB_RUN_ATTEMPT':'1'}
    need(platform=='nt' and all(env.get(k)==v for k,v in required.items()),'Hosted Windows Source binding is required')
    need(isinstance(expected_head,str) and re.fullmatch('[0-9a-f]{40}',expected_head)
         and expected_head==actual_head==env.get('GITHUB_SHA'),'Actual checkout/Source SHA mismatch')
    need(re.fullmatch('[1-9][0-9]{0,19}',env.get('GITHUB_RUN_ID','')),'Invalid actual Source run')
    job=env.get('GITHUB_JOB');arch=env.get('E2E_ARCHITECTURE')
    need((job,arch) in (('native-e2e','x64'),('native-e2e-arm64','arm64')),'Actual native Source job/architecture is required')
    return {'sourceCommit':expected_head,'sourceRun':env['GITHUB_RUN_ID'],'runAttempt':'1',
            'repository':'ATLKR/OpenGeul','job':job,'architecture':arch}

def validate_record(row,binding):
    fields={'formatVersion','source','nativeMachine','controllerMachine','systemDirectory','capabilityName',
            'capabilityBefore','capabilityAfter','restartNeeded','userLanguageConfigured','defaultInputTip',
            'configuredInputTips','profile','profileScope','productInputVerified','sourceQualified'}
    need(isinstance(row,dict) and set(row)==fields and type(row['formatVersion']) is int
         and row['formatVersion']==1 and row['source']==binding,'Readiness record/source contract mismatch')
    expected_machine={'x64':0x8664,'arm64':0xAA64}.get(binding.get('architecture'))
    need(type(row['nativeMachine']) is int and row['nativeMachine']==expected_machine
         and type(row['controllerMachine']) is int
         and row['controllerMachine'] in ((0,0x8664) if expected_machine==0xAA64 else (0,)),
         'Actual OS native/controller architecture mismatch')
    need(row['capabilityName']==CAPABILITY and row['capabilityBefore'] in ('NotPresent','Installed')
         and row['capabilityAfter']=='Installed' and row['restartNeeded'] is False,'Korean capability is not actually ready without a restart')
    need(row['userLanguageConfigured'] is True and isinstance(row['configuredInputTips'],list)
         and 1<=len(row['configuredInputTips'])<=64,'Current-user Korean language/profile is missing')
    p=row['profile'];pfields={'inputTip','providerClsid','profileGuid','languageId','registered','registryView','component'}
    need(isinstance(p,dict) and set(p)==pfields,'Actual registered Korean profile is missing')
    tip=p['inputTip'];match=re.fullmatch('0412:('+GUID+')('+GUID+')',tip) if isinstance(tip,str) else None
    need(match is not None and match.group(1).upper()==str(p['providerClsid']).upper()
         and match.group(2).upper()==str(p['profileGuid']).upper() and p['languageId']==0x0412
         and p['registered'] is True and p['registryView']=='Registry64'
         and tip==row['defaultInputTip'] and tip in row['configuredInputTips'],'Input tip does not bind the actual native registered provider/profile')
    c=p['component'];cfields={'path','bytes','sha256','machine','signatureStatus','signerSubject'}
    need(isinstance(c,dict) and set(c)==cfields,'Actual Microsoft profile component is missing')
    directory=PureWindowsPath(row['systemDirectory']) if isinstance(row['systemDirectory'],str) else PureWindowsPath()
    path=PureWindowsPath(c['path']) if isinstance(c['path'],str) else PureWindowsPath()
    need(directory.is_absolute() and re.fullmatch('[A-Za-z]:',directory.drive) and path.is_absolute()
         and path.drive.lower()==directory.drive.lower() and '..' not in path.parts
         and path.is_relative_to(directory) and path.suffix.lower() in ('.dll','.ime'),'Profile component is outside the actual native system directory')
    need(type(c['bytes']) is int and 0<c['bytes']<=64*1024*1024 and re.fullmatch('[0-9a-f]{64}',c.get('sha256',''))
         and type(c['machine']) is int and c['machine']==expected_machine,'Profile component bytes/native PE identity mismatch')
    need(c['signatureStatus']=='Valid' and isinstance(c['signerSubject'],str)
         and re.search(r'(?:^|,\s*)O=Microsoft Corporation(?:,|$)',c['signerSubject']),'Profile component is not genuinely Microsoft-signed')
    need(row['profileScope']==SCOPE and row['productInputVerified'] is False and row['sourceQualified'] is False,
         'Setup/controller observations cannot qualify actual target app input')
    return dict(row)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--expected-source',required=True)
    parser.add_argument('--source-root',default='.');parser.add_argument('--guard',action='store_true')
    parser.add_argument('--record',type=Path);args=parser.parse_args()
    root=Path(args.source_root).resolve()
    actual=subprocess.run(['git','rev-parse','HEAD'],cwd=root,check=True,capture_output=True,text=True,timeout=10).stdout.strip()
    binding=host_binding(os.environ,args.expected_source,actual,platform=os.name)
    if args.guard:print(json.dumps(binding,separators=(',',':')));return
    need(args.record is not None,'Actual readiness record is required')
    record=args.record.resolve();need(record.is_relative_to(root) and record.stat().st_size<=32768,'Readiness record path/size is outside its bound')
    validate_record(json.loads(record.read_bytes()),binding)
    print('Actual Korean hosted setup validated; target HWND/thread input remains unqualified.')

if __name__=='__main__':main()
