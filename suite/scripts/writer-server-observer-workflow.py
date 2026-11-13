"""Exact manual context/source admission and closed numeric evidence checks."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time

BRANCH='work/opengeul-office-native-writer-observer-suite-9dea'
WORKFLOW='ATLKR/OpenGeul/.github/workflows/office-suite.yml@refs/heads/'+BRANCH
KEYS=('GITHUB_REPOSITORY','GITHUB_ACTOR','GITHUB_ACTOR_ID','GITHUB_TRIGGERING_ACTOR','GITHUB_EVENT_NAME',
    'GITHUB_RUN_ATTEMPT','GITHUB_REF','GITHUB_SHA','GITHUB_WORKFLOW_SHA','GITHUB_WORKFLOW_REF',
    'WRITER_OBSERVER_ENABLED','WRITER_OBSERVER_SUITE_HEAD')


class Rejected(RuntimeError):
    def __init__(self):super().__init__('Writer workflow admission rejected')


def require_context(values,event):
    expected={'GITHUB_REPOSITORY':'ATLKR/OpenGeul','GITHUB_ACTOR':'ATLKR','GITHUB_ACTOR_ID':'65988341',
        'GITHUB_TRIGGERING_ACTOR':'ATLKR','GITHUB_EVENT_NAME':'workflow_dispatch','GITHUB_RUN_ATTEMPT':'1',
        'GITHUB_REF':'refs/heads/'+BRANCH,'GITHUB_WORKFLOW_REF':WORKFLOW,'WRITER_OBSERVER_ENABLED':'true'}
    try:
        head=values['GITHUB_SHA']
        if (not isinstance(head,str) or not re.fullmatch('[0-9a-f]{40}',head) or head=='0'*40 or
                any(values.get(key)!=value for key,value in expected.items()) or
                any(values.get(key)!=head for key in ('GITHUB_WORKFLOW_SHA','WRITER_OBSERVER_SUITE_HEAD')) or
                event['repository']['full_name']!='ATLKR/OpenGeul' or type(event['repository']['id']) is not int or
                event['repository']['id']!=1405493151 or event['repository']['private'] is not False or
                event['sender']['login']!='ATLKR' or type(event['sender']['id']) is not int or
                event['sender']['id']!=65988341 or event['sender']['type']!='User'):raise Rejected()
        return True
    except Exception:raise Rejected() from None


def _regular(path,*,directory=False):
    for part in (path,*path.parents):
        info=part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&1024:raise Rejected()
    info=path.stat()
    if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):raise Rejected()
    return info


def verify_tracked_rows(root,rows,*,check):
    try:
        root=Path(root);_regular(root,directory=True);count=total=0
        if type(rows) is not bytes or len(rows)>1048576:raise Rejected()
        for item in rows.split(b'\0'):
            check()
            if not item:continue
            metadata,name=item.split(b'\t',1);mode,kind,expected=metadata.split()
            relative=Path(os.fsdecode(name))
            if relative.is_absolute() or '..' in relative.parts:raise Rejected()
            path=root/relative
            if mode==b'160000':
                if kind!=b'commit' or path.is_symlink():raise Rejected()
                if path.exists():
                    _regular(path,directory=True)
                    if next(path.iterdir(),None) is not None:raise Rejected()
                continue
            info=_regular(path)
            if mode not in (b'100644',b'100755') or kind!=b'blob' or info.st_size>8388608:raise Rejected()
            total+=info.st_size;count+=1
            if total>67108864 or count>32768:raise Rejected()
            digest=hashlib.sha1(b'blob '+str(info.st_size).encode()+b'\0')
            with path.open('rb') as stream:
                opened=os.fstat(stream.fileno())
                if (opened.st_dev,opened.st_ino,opened.st_size)!=(info.st_dev,info.st_ino,info.st_size):raise Rejected()
                seen=0
                while True:
                    check();chunk=stream.read(min(1048576,info.st_size-seen+1));check()
                    if not chunk:break
                    seen+=len(chunk)
                    if seen>info.st_size:raise Rejected()
                    digest.update(chunk)
                if seen!=info.st_size:raise Rejected()
            after=_regular(path)
            if ((after.st_dev,after.st_ino,after.st_size)!=(info.st_dev,info.st_ino,info.st_size) or
                    digest.hexdigest().encode()!=expected):raise Rejected()
        check();return count
    except Exception:raise Rejected() from None


def verify_source(root,head):
    # Same 30-second static source-admission bound/size limits as the existing
    # Suite static mode; this is not the launch P or runtime S budget.
    start=last=time.monotonic();deadline=start+30
    def check():
        nonlocal last
        now=time.monotonic()
        if now<last or now>=deadline:raise Rejected()
        last=now;return deadline-now
    def git(*args):
        with tempfile.TemporaryFile() as output:
            subprocess.run(['git',*args],cwd=root,stdout=output,stderr=subprocess.DEVNULL,check=True,timeout=check())
            check()
            if output.tell()>1048576:raise Rejected()
            output.seek(0);return output.read(1048577)
    if git('rev-parse','HEAD').decode().strip()!=head:raise Rejected()
    git('diff','--cached','--quiet','HEAD','--');git('diff','--quiet','HEAD','--')
    return verify_tracked_rows(root,git('ls-tree','-rz','--full-tree','HEAD'),check=check)


def _json(path,limit):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise Rejected()
            result[key]=value
        return result
    with Path(path).open('rb') as stream:raw=stream.read(limit+1)
    if len(raw)>limit:raise Rejected()
    return json.loads(raw,object_pairs_hook=pairs)


def require_report(path):
    try:
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'e2e'))
        from writer_server_observer_runner import validate_public_report
        validate_public_report(_json(path,1048576));return True
    except Exception:raise Rejected() from None


class Parser(argparse.ArgumentParser):
    def error(self,message):raise Rejected()


def main(arguments=None):
    receipt={'schemaVersion':1,'stageCode':0,'passed':False,'sourceFileCount':0,'errorCode':0,
        'normalAcceptance':False,'fullEngineQualified':False,'acceptanceEligible':False,'guiVerified':False}
    output=None
    try:
        parser=Parser(add_help=False,allow_abbrev=False);parser.add_argument('mode',choices=('admit','validate-report'))
        parser.add_argument('--output');parser.add_argument('--input');args=parser.parse_args(arguments)
        if args.mode=='admit':
            output=args.output
            values={key:os.environ.get(key) for key in KEYS}
            require_context(values,_json(os.environ.get('GITHUB_EVENT_PATH'),1048576))
            receipt['stageCode']=1;receipt['sourceFileCount']=verify_source(Path.cwd(),values['GITHUB_SHA'])
        else:
            receipt['stageCode']=2;require_report(args.input)
        receipt['passed']=True
    except Exception:receipt['errorCode']=1
    if output is not None:
        try:
            fd=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'w',encoding='ascii') as stream:json.dump(receipt,stream,sort_keys=True)
        except Exception:receipt['passed']=False;receipt['errorCode']=2
    print(json.dumps(receipt,sort_keys=True));return 0 if receipt['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
