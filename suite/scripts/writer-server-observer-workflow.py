"""Exact owned context/source admission and closed numeric evidence checks."""
import argparse
import hashlib
import json
import math
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
MARKER='[opengeul-writer-observer-9dea-run]'
REQUEST='suite/config/writer-server-observer-9dea/run-request.json'
KEYS=('GITHUB_REPOSITORY','GITHUB_ACTOR','GITHUB_ACTOR_ID','GITHUB_TRIGGERING_ACTOR','GITHUB_EVENT_NAME',
    'GITHUB_RUN_ATTEMPT','GITHUB_REF','GITHUB_SHA','GITHUB_WORKFLOW_SHA','GITHUB_WORKFLOW_REF',
    'WRITER_OBSERVER_ENABLED','WRITER_OBSERVER_SUITE_HEAD','GITHUB_REPOSITORY_OWNER','WRITER_OBSERVER_PHASE_SECONDS')


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


def _sha(value):
    return type(value) is str and re.fullmatch('[0-9a-f]{40}',value) is not None and value!='0'*40


def require_push_context(values,event):
    expected={'GITHUB_REPOSITORY':'ATLKR/OpenGeul','GITHUB_REPOSITORY_OWNER':'ATLKR',
        'GITHUB_ACTOR':'ATLKR','GITHUB_ACTOR_ID':'65988341','GITHUB_TRIGGERING_ACTOR':'ATLKR',
        'GITHUB_EVENT_NAME':'push','GITHUB_RUN_ATTEMPT':'1','GITHUB_REF':'refs/heads/'+BRANCH,
        'GITHUB_WORKFLOW_REF':WORKFLOW}
    try:
        head=values['GITHUB_SHA']
        if (not _sha(head) or any(values.get(k)!=v for k,v in expected.items()) or
                values['GITHUB_WORKFLOW_SHA']!=head or
                event['repository']['full_name']!='ATLKR/OpenGeul' or
                type(event['repository']['id']) is not int or event['repository']['id']!=1405493151 or
                event['repository']['private'] is not False or event['sender']['login']!='ATLKR' or
                type(event['sender']['id']) is not int or event['sender']['id']!=65988341 or
                event['sender']['type']!='User' or event['ref']!='refs/heads/'+BRANCH or
                not _sha(event['before']) or event['before']==head or event['after']!=head or
                any(event[k] is not False for k in ('created','deleted','forced')) or
                type(event['commits']) is not list or len(event['commits'])!=1 or
                event['commits'][0]['id']!=head or event['head_commit']['id']!=head or
                event['head_commit']['message'] not in (MARKER,MARKER+'\n')):raise Rejected()
        return True
    except Exception:raise Rejected() from None


def phase_seconds(value):
    if type(value) is not str or re.fullmatch('[1-9][0-9]{0,3}',value) is None:raise Rejected()
    phase=int(value)
    if not 6<=phase<=1200:raise Rejected()
    return phase


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


def _source_admission(root,head,event=None):
    # Same 30-second static source-admission bound/size limits as the existing
    # Suite static mode; this is not the launch P or runtime S budget.
    start=last=time.monotonic();deadline=start+30
    def check():
        nonlocal last
        now=time.monotonic()
        if not math.isfinite(now) or not math.isfinite(start) or now<last or now>=deadline:raise Rejected()
        last=now;return deadline-now
    def git(*args):
        with tempfile.TemporaryFile() as output:
            subprocess.run(['git','--no-replace-objects',*args],cwd=root,stdin=subprocess.DEVNULL,
                stdout=output,stderr=subprocess.DEVNULL,check=True,timeout=check())
            check()
            if output.tell()>1048576:raise Rejected()
            output.seek(0);return output.read(1048577)
    try:
        if not _sha(head) or git('rev-parse','HEAD')!=(head+'\n').encode():raise Rejected()
        rows=git('ls-tree','-rz','--full-tree',head);phase=None
        if event is not None:
            parent=event['before']
            if not _sha(parent) or event['after']!=head:raise Rejected()
            def commit(sha):
                if git('cat-file','-t',sha)!=b'commit\n':raise Rejected()
                raw=git('cat-file','commit',sha);headers,message=raw.split(b'\n\n',1)
                trees=[x[5:] for x in headers.split(b'\n') if x.startswith(b'tree ')]
                parents=[x[7:] for x in headers.split(b'\n') if x.startswith(b'parent ')]
                if len(trees)!=1 or not _sha(trees[0].decode('ascii')):raise Rejected()
                return parents,message
            parents,message=commit(head)
            if parents!=[parent.encode()] or message!=(MARKER+'\n').encode():raise Rejected()
            commit(parent)
            before=git('ls-tree','-rz','--full-tree',parent)
            def tree(raw):
                if not raw or not raw.endswith(b'\0'):raise Rejected()
                result=[]
                for item in raw[:-1].split(b'\0'):
                    check();metadata,name=item.split(b'\t',1);mode,kind,blob=metadata.split(b' ')
                    if not _sha(blob.decode('ascii')):raise Rejected()
                    if name.lower()==REQUEST.encode().lower() and name!=REQUEST.encode():raise Rejected()
                    result.append((item,mode,kind,blob,name))
                return result
            old=tree(before);new=tree(rows)
            requests=[row for row in new if row[4]==REQUEST.encode()]
            if (any(row[4]==REQUEST.encode() for row in old) or len(requests)!=1 or
                    requests[0][1:3]!=(b'100644',b'blob') or
                    [row[0] for row in new if row[4]!=REQUEST.encode()]!=[row[0] for row in old]):raise Rejected()
            blob=requests[0][3].decode('ascii');size=git('cat-file','-s',blob)
            if re.fullmatch(b'[0-9]+\n',size) is None or not 0<int(size)<=1024:raise Rejected()
            raw=git('cat-file','blob',blob);check()
            if len(raw)!=int(size):raise Rejected()
            request=_decode_json(raw)
            if (type(request) is not dict or set(request)!={'schemaVersion','kind','reviewedParentCommit','phaseSeconds'} or
                    type(request['schemaVersion']) is not int or request['schemaVersion']!=1 or
                    request['kind']!='writer-server-observer-run-request' or request['reviewedParentCommit']!=parent or
                    type(request['phaseSeconds']) is not int or not 6<=request['phaseSeconds']<=1200):raise Rejected()
            phase=request['phaseSeconds'];check()
        git('diff','--cached','--quiet','HEAD','--');git('diff','--quiet','HEAD','--')
        return verify_tracked_rows(root,rows,check=check),phase
    except Exception:raise Rejected() from None


def verify_source(root,head):
    return _source_admission(root,head)[0]


def verify_request_source(root,head,event):
    count,phase=_source_admission(root,head,event)
    if type(phase) is not int:raise Rejected()
    return count,phase


def _decode_json(raw):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise Rejected()
            result[key]=value
        return result
    return json.loads(raw.decode('utf-8'),object_pairs_hook=pairs)


def _json(path,limit):
    with Path(path).open('rb') as stream:raw=stream.read(limit+1)
    if len(raw)>limit:raise Rejected()
    return _decode_json(raw)


def write_phase_output(path,phase):
    try:
        if type(phase) is not int or not 6<=phase<=1200:raise Rejected()
        path=Path(path)
        if '..' in path.parts:raise Rejected()
        before=_regular(path)
        if before.st_nlink!=1 or before.st_size!=0:raise Rejected()
        identity=lambda row:(row.st_dev,row.st_ino,row.st_mode,row.st_nlink,row.st_size)
        fd=os.open(path,os.O_WRONLY|os.O_APPEND|getattr(os,'O_NOFOLLOW',0))
        try:
            if identity(os.fstat(fd))!=identity(before):raise Rejected()
            raw=('phase_seconds='+str(phase)+'\n').encode('ascii')
            if os.write(fd,raw)!=len(raw):raise Rejected()
            after=os.fstat(fd);named=_regular(path)
            if (identity(after)!=identity(named) or identity(after)[:4]!=identity(before)[:4] or
                    after.st_size!=len(raw)):raise Rejected()
        finally:os.close(fd)
    except Exception:raise Rejected() from None


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
            event=_json(os.environ.get('GITHUB_EVENT_PATH'),1048576)
            if values['GITHUB_EVENT_NAME']=='push':
                require_push_context(values,event);receipt['stageCode']=1
                count,phase=verify_request_source(Path.cwd(),values['GITHUB_SHA'],event)
            else:
                require_context(values,event);receipt['stageCode']=1
                phase=phase_seconds(values['WRITER_OBSERVER_PHASE_SECONDS'])
                count=verify_source(Path.cwd(),values['GITHUB_SHA'])
            receipt['sourceFileCount']=count
            write_phase_output(os.environ.get('GITHUB_OUTPUT'),phase)
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
