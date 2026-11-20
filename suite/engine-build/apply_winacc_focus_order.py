"""Apply the locked WinAcc focus-order correction to an authenticated LO tree.

The normal source driver currently builds ARM64. This Windows common-source
correction is neither x64 build proof nor complete engine or GUI qualification.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
from pathlib import Path
import stat

HERE=Path(__file__).resolve().parent
CORE='bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1'
SOURCE='winaccessibility/source/service/AccObjectWinManager.cxx'
SOURCES={SOURCE,'winaccessibility/source/service/AccObject.cxx',
    'winaccessibility/source/UAccCOM/MAccessible.cxx'}


def _directory(path):
    for part in (path,*path.parents):
        item=part.lstat()
        if not stat.S_ISDIR(item.st_mode) or getattr(item,'st_file_attributes',0)&0x400:
            raise ValueError('WinAcc source patch requires regular owned directories')


def _regular(path,size=None):
    _directory(path.parent);item=path.lstat()
    if (not stat.S_ISREG(item.st_mode) or item.st_nlink!=1
            or getattr(item,'st_file_attributes',0)&0x400 or not 0<item.st_size<=1024*1024
            or size is not None and item.st_size!=size):
        raise ValueError('WinAcc source patch requires an exact regular file')
    return path.read_bytes()


def install(source:Path,evidence:Path,core_commit:str):
    lock=json.loads(_regular(HERE/'source-build.json').decode())
    pin=lock['winAccFocusOrder']
    if (lock['schemaVersion']!=1 or core_commit!=CORE or pin['coreCommit']!=CORE
            or pin['path']!=SOURCE or len(pin['sources'])!=3
            or {item['path'] for item in pin['sources']}!=SOURCES):
        raise ValueError('WinAcc source patch differs from the pinned core and source plan')
    source=Path(source).absolute();evidence=Path(evidence).absolute()
    _directory(source);_directory(evidence)
    source=source.resolve(strict=True);evidence=evidence.resolve(strict=True)
    if source==evidence or source in evidence.parents or evidence in source.parents:
        raise ValueError('WinAcc source patch evidence must be outside the source tree')
    inputs={}
    for item in pin['sources']:
        raw=_regular(source/item['path'],item['size'])
        if hashlib.sha256(raw).hexdigest()!=item['sha256']:
            raise ValueError('WinAcc source SHA256 differs from the pinned core')
        inputs[item['path']]=raw
    original=inputs[SOURCE]
    if len(original)!=pin['beforeBytes'] or hashlib.sha256(original).hexdigest()!=pin['sha256']:
        raise ValueError('WinAcc focus manager before SHA256 differs from its lock')
    moved=b'        pAccObjNew->setFocus();\n'
    previous=b'            pAccObjOld->unsetFocus();\n'
    if original.count(moved)!=1 or original.count(previous)!=1:
        raise ValueError('WinAcc exact focus call sites differ')
    changed=original.replace(moved,b'',1).replace(previous,previous+moved,1)
    if len(changed)!=pin['afterBytes'] or hashlib.sha256(changed).hexdigest()!=pin['afterSha256']:
        raise ValueError('WinAcc focus manager after SHA256 differs from its lock')
    name=pin['patch']['filename']
    if name!='winacc-focus-order.patch' or pin['patch']['strip']!=1:
        raise ValueError('WinAcc source patch filename or strip differs')
    patch=_regular(HERE/name,pin['patch']['size'])
    if hashlib.sha256(patch).hexdigest()!=pin['patch']['sha256']:
        raise ValueError('WinAcc source patch SHA256 differs from its lock')
    expected=''.join(difflib.unified_diff(original.decode().splitlines(True),changed.decode().splitlines(True),
        fromfile='a/'+SOURCE,tofile='b/'+SOURCE)).encode()
    if patch!=expected:
        raise ValueError('WinAcc source patch payload differs from the exact one-call move')
    retained={'original':evidence/'original-AccObjectWinManager.cxx',
        'effective':evidence/'effective-AccObjectWinManager.cxx','patch':evidence/name}
    if any(path.exists() or path.is_symlink() for path in retained.values()):
        raise ValueError('WinAcc source patch evidence already exists')
    for key,raw in (('original',original),('effective',changed),('patch',patch)):
        with retained[key].open('xb') as stream:stream.write(raw)
    target=source/SOURCE
    if _regular(target,pin['beforeBytes'])!=original:
        raise ValueError('WinAcc original source changed before write')
    target.write_bytes(changed)
    if _regular(target,pin['afterBytes'])!=changed:
        raise ValueError('WinAcc effective source changed after write')
    files=[]
    for item in pin['sources']:
        after=changed if item['path']==SOURCE else inputs[item['path']]
        if _regular(source/item['path'],len(after))!=after:
            raise ValueError('WinAcc source dependency changed after write')
        files.append({'path':item['path'],'beforeBytes':len(inputs[item['path']]),'afterBytes':len(after),
            'beforeSha256':item['sha256'],'afterSha256':hashlib.sha256(after).hexdigest()})
    return {'schemaVersion':1,'kind':'winacc-focus-order-source-patch','passed':True,'coreCommit':CORE,
        'path':SOURCE,'beforeSha256':pin['sha256'],'afterSha256':pin['afterSha256'],
        'patchSha256':pin['patch']['sha256'],'sourceFiles':files,
        'evidence':{key:str(path) for key,path in retained.items()},
        'nativeBuildVerified':False,'guiVerified':False,'currentCiRootCauseConfirmed':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--libreoffice-source',type=Path,required=True)
    parser.add_argument('--evidence-directory',type=Path,required=True)
    parser.add_argument('--core-commit',required=True)
    args=parser.parse_args()
    try:result=install(args.libreoffice_source,args.evidence_directory,args.core_commit)
    except (ValueError,OSError,KeyError,TypeError):
        print(json.dumps({'schemaVersion':1,'passed':False,'errorCode':1}))
        return 1
    print(json.dumps(result,indent=2));return 0


if __name__=='__main__':raise SystemExit(main())
