"""Bound CI evidence without suppressing test failures or losing their summaries.

Success: up to 1 MiB of text/JSON/JUnit. Failure: up to 12 MiB including pictures,
PDFs and safe bounded traces. Log all omissions. Never copy documents or fonts.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import zipfile
LIMITS={'success':1024*1024,'failure':12*1024*1024,'cancelled':12*1024*1024}
TEXT={'.json','.xml','.log','.txt'}
VISUAL={'.png','.pdf','.zip'}
FONT_SUFFIX={'.ttf','.otf','.ttc','.woff','.woff2','.eot'}
FONT_MAGIC=(b'OTTO',b'ttcf',b'wOFF',b'wOF2',b'\x00\x01\x00\x00')


def files(root):
    if root.is_symlink():raise ValueError('Symlinked input is forbidden')
    if not root.exists():return []
    if root.is_file():return [root]
    found=[]
    for folder,dirs,names in os.walk(root,followlinks=False):
        for name in dirs+names:
            if (Path(folder)/name).is_symlink():raise ValueError('Symlinked evidence is forbidden')
        found.extend(Path(folder)/name for name in names)
        if len(found)>10_000:raise ValueError('Too many evidence files')
    return sorted(found)


def measure(roots,limit):
    if not roots or any(not root.exists() for root in roots):raise ValueError('Missing artifact input')
    total=sum(p.stat().st_size for root in roots for p in files(root))
    if total>limit:raise ValueError(f'Artifact size {total} exceeds pre-upload cap {limit}')
    return total


def safe_trace(path):
    if path.name!='trace.zip':return False
    with zipfile.ZipFile(path) as archive:
        items=archive.infolist()
        if len(items)>2000 or sum(i.file_size for i in items)>32*1024*1024:return False
        for item in items:
            name=Path(item.filename)
            if name.suffix.lower() in FONT_SUFFIX|{'.pfx','.pem','.key'}:return False
            if item.is_dir():continue
            with archive.open(item) as stream:
                if stream.read(4) in FONT_MAGIC:return False
    return True


def pack(source,destination,status,limit=None):
    if status not in LIMITS:raise ValueError('Unknown job outcome; refusing to mislabel evidence')
    cap=LIMITS[status] if limit is None else limit
    if type(cap) is not int or cap<512:raise ValueError('Evidence cap too small')
    if destination.exists() or destination.is_symlink():raise ValueError('Refusing to overwrite bounded evidence')
    candidates=files(source);stage=None
    failed=set()
    for name in ('results.json','summary.json'):
        summary=source/name
        if summary.is_file() and summary.stat().st_size<=2*1024*1024:
            value=json.loads(summary.read_text(encoding='utf-8'))
            records=value.get('tests')
            if not isinstance(records,list):records=value.get('results',[])
            for row in records:
                if row.get('status') in ('failed','error','skipped') or row.get('passed') is False:
                    failed.add(str(row.get('test',row.get('name',''))).rsplit('.',1)[-1])
    # Root outcomes first, then failed-case diagnostics before successful traces.
    def rank(p):
        rel=p.relative_to(source)
        if len(rel.parts)==1 and p.name in ('results.json','summary.json','junit.xml'):return (0,0,rel.as_posix())
        is_failure=any(part in failed for part in rel.parts)
        group=1 if is_failure else 3
        kind=0 if p.suffix in TEXT else 1 if p.suffix in ('.png','.pdf') else 2
        return (group,kind,rel.as_posix())
    candidates.sort(key=rank)
    report={'status':status,'limitBytes':cap,'copied':[],'omitted':[],'omittedCount':0,'sourceBytes':sum(p.stat().st_size for p in candidates)}
    destination.parent.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix='.ci-evidence-',dir=destination.parent));used=0
    reserve=min(64*1024,cap//2)
    try:
        for path in candidates:
            rel=path.relative_to(source).as_posix();size=path.stat().st_size;suffix=path.suffix.lower();reason=None
            if suffix not in TEXT|VISUAL:reason='excluded type (documents, fonts and keys are never uploaded)'
            elif status=='success' and suffix not in TEXT:reason='success keeps summaries; visual data stays local'
            elif size>6*1024*1024 or used+size>cap-reserve:reason='evidence size cap'
            elif suffix=='.zip' and not safe_trace(path):reason='trace has unreviewed or excessive content'
            if reason:
                report['omittedCount']+=1
                if len(report['omitted'])<128:report['omitted'].append({'path':rel,'bytes':size,'reason':reason})
                continue
            with path.open('rb') as stream:
                if stream.read(4) in FONT_MAGIC:raise ValueError('Disguised font is not evidence')
            target=stage/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target)
            used+=size;report['copied'].append({'path':rel,'bytes':size})
        report['copiedBytes']=used
        (stage/'evidence-index.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        measure([stage],cap)
        stage.rename(destination)
    finally:
        if stage.exists():shutil.rmtree(stage)
    summary=f"Evidence ({status}): {used} / {report['sourceBytes']} raw bytes copied; {report['omittedCount']} files omitted. Test status is unchanged."
    print(summary)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a',encoding='utf-8') as stream:stream.write(summary+'\n')
    return report


def main():
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('pack');p.add_argument('source',type=Path);p.add_argument('destination',type=Path);p.add_argument('--status',required=True,choices=list(LIMITS))
    p=sub.add_parser('size');p.add_argument('--limit-mib',required=True,type=int);p.add_argument('paths',type=Path,nargs='+')
    args=parser.parse_args()
    if args.command=='pack':pack(args.source,args.destination,args.status)
    else:print('Pre-upload bytes:',measure(args.paths,args.limit_mib*1024*1024))
if __name__=='__main__':main()
