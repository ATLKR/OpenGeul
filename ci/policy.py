"""Fail closed on non-public/paid-runner workflow drift; not a billing API.

An owner-set $0 stop-usage budget remains the account-level cost backstop.
This policy prevents accidental workflow changes; it is not a security boundary
against a repository writer who can replace both the workflows and this file.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re

RUNNERS = frozenset({'ubuntu-24.04', 'windows-2022', 'windows-2025'})
PUBLIC = 'github.event.repository.private == false'
ACTIONS = {
    'actions/checkout': 'fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09',
    'actions/setup-node': 'a0853c24544627f65ddf259abe73b1d18a591444',
    'actions/setup-python': 'ece7cb06caefa5fff74198d8649806c4678c61a1',
    'actions/upload-artifact': 'ea165f8d65b6e75b540449e92b4886f43607fa02',
}


def require_public(event):
    if event.get('repository', {}).get('private') is not False:
        raise ValueError('Only explicitly public repository events may run this CI')


def select_mode(event_name, inputs):
    if event_name not in ('push','pull_request','schedule','workflow_dispatch'):
        raise ValueError('Unsupported CI event')
    mode = inputs.get('mode', 'full') if event_name == 'workflow_dispatch' else 'full'
    if mode not in ('full','engine','checks'): raise ValueError('Invalid manual CI mode')
    return mode


def guarded(expression):
    if not isinstance(expression,str): return False
    text=expression.strip()
    if text.startswith('${{') and text.endswith('}}'):text=text[3:-2].strip()
    if text==PUBLIC:return True
    prefix=PUBLIC+' && ('
    if not text.startswith(prefix) or not text.endswith(')'):return False
    # A top-level OR must not be able to bypass the public-only predicate.
    depth=0;quote=False
    for char in text[len(prefix):-1]:
        if char=="'":quote=not quote
        elif not quote:
            if char=='(':depth+=1
            elif char==')':
                depth-=1
                if depth<0:return False
    return not quote and depth==0


def audit(workflow):
    events=workflow.get('on', {})
    if isinstance(events,str):events=[events]
    if not isinstance(events,(dict,list)) or any(e not in ('push','pull_request','workflow_dispatch','schedule') for e in events):
        raise ValueError('Unreviewed workflow trigger')
    jobs=workflow.get('jobs')
    if not isinstance(jobs,dict) or not jobs:raise ValueError('Missing jobs')
    for name,job in jobs.items():
        if not isinstance(job,dict) or not guarded(job.get('if')):
            raise ValueError(f'{name}: public-only guard is required BEFORE runner allocation')
        if str(job.get('continue-on-error','false')).lower()!='false':
            raise ValueError(f'{name}: job-level failure suppression is not permitted')
        if any(k in job for k in ('uses','snapshot','container','services')):
            raise ValueError(f'{name}: unreviewed reusable workflow, image or service')
        runner=job.get('runs-on')
        if runner=='${{ matrix.os }}':
            matrix=job.get('strategy',{}).get('matrix',{})
            if not isinstance(matrix,dict) or set(matrix) != {'os'} or not isinstance(matrix['os'],list) or not matrix['os']:
                raise ValueError(f'{name}: runner matrix must be explicit and static')
            candidates=matrix['os']
        else:candidates=[runner]
        if any(not isinstance(r,str) or r not in RUNNERS for r in candidates):
            raise ValueError(f'{name}: standard free runner allowlist violated')
        timeout=job.get('timeout-minutes')
        if not str(timeout).isdigit() or not 1<=int(timeout)<=120:
            raise ValueError(f'{name}: require a bounded timeout (1..120 minutes)')
        for step in job.get('steps',[]):
            if 'snapshot' in step or str(step.get('continue-on-error','false')).lower()!='false':
                raise ValueError(f'{name}: custom images or suppressed failures are not permitted')
            if 'uses' not in step:continue
            action,sep,sha=step['uses'].partition('@')
            if not sep or ACTIONS.get(action)!=sha:
                raise ValueError(f'{name}: unreviewed action or moving version: {action}')
            args=step.get('with',{})
            if 'cache' in args or str(args.get('package-manager-cache','false')).lower()!='false':
                raise ValueError(f'{name}: automatic cache is disabled until owner approves its quota')
            if str(args.get('lfs','false')).lower()!='false':raise ValueError('LFS usage is outside free CI policy')
            if action=='actions/upload-artifact' and str(args.get('retention-days'))!='1':
                raise ValueError(f'{name}: artifact retention must be one day')
    return True


def load_workflow(path):
    import yaml
    class StrictLoader(yaml.BaseLoader): pass
    def mapping(loader,node):
        pairs=loader.construct_pairs(node)
        result={}
        for key,value in pairs:
            if key in result:raise ValueError(f'Duplicate YAML key: {key}')
            result[key]=value
        return result
    StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,mapping)
    if path.stat().st_size>128*1024:raise ValueError('Workflow exceeds review limit')
    with path.open(encoding='utf-8') as stream:return yaml.load(stream,Loader=StrictLoader)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--event',action='store_true');args=parser.parse_args()
    paths=sorted((args.root/'.github/workflows').glob('*.y*ml'))
    if not paths:raise ValueError('No workflows found')
    for path in paths:audit(load_workflow(path))
    print(f'Checked {len(paths)} workflows: public + standard runners only; no caches/custom images/LFS.')
    if args.event:
        event=json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text(encoding='utf-8'))
        require_public(event);mode=select_mode(os.environ['GITHUB_EVENT_NAME'],event.get('inputs') or {})
        with open(os.environ['GITHUB_OUTPUT'],'a',encoding='utf-8') as stream:stream.write('mode='+mode+'\n')
        print('CI mode:',mode,'; only full runs are eligible for release.')
if __name__=='__main__':main()
