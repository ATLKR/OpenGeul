"""Select one reviewed npm graph; package scripts and installers run elsewhere."""
import hashlib
import json
import os
from pathlib import Path
import stat

ROOT=Path(__file__).resolve().parents[1]
PRISTINE_LOCK_SHA256='ed88ee7fcf037e64667c18fe2421f9010c543b066cdd423c47ad20235426cba2'
PREPARED_LOCK_SHA256='9625a90ccd967d8ad49716b8ed00b8fb61b5c78bd8bb81c1d9d02220bf4fcd14'
PREPARED_LOCK=ROOT/'overlay/frontend-pnpm-lock.txt'
NPM_TAURI_VERSION='2.12.4'
MAX_INPUT=128*1024
MANIFESTS=(('apps/desktop/package.json','hop-desktop','devDependencies','@tauri-apps/cli','^2.0.0'),
           ('apps/studio-host/package.json','@golbin/hop-studio-host','dependencies','@tauri-apps/api','^2.10.1'))


def _read(path):
    for part in (path,*path.parents):
        info=part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:
            raise ValueError('Reviewed npm inputs cannot have path aliases')
    info=path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or not 0<info.st_size<=MAX_INPUT:
        raise ValueError('Reviewed npm input type or size differs')
    def identity(value):
        return value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns,value.st_ctime_ns,value.st_nlink
    with path.open('rb') as stream:
        opened=os.fstat(stream.fileno())
        if identity(opened)!=identity(info):raise ValueError('Reviewed npm input identity differs')
        raw=stream.read(MAX_INPUT+1)
        after=os.fstat(stream.fileno())
    final=path.lstat()
    if (len(raw)!=info.st_size or len(raw)>MAX_INPUT or identity(after)!=identity(info)
            or identity(final)!=identity(info) or stat.S_ISLNK(final.st_mode)
            or getattr(final,'st_file_attributes',0)&0x400):
        raise ValueError('Reviewed npm input changed during read')
    return raw


def _pairs(rows):
    result={}
    for key,value in rows:
        if key in result:raise ValueError('Duplicate npm manifest key')
        result[key]=value
    return result


def pin_frontend_dependencies(source):
    source=Path(source)
    replacement=_read(PREPARED_LOCK)
    if hashlib.sha256(replacement).hexdigest()!=PREPARED_LOCK_SHA256:
        raise ValueError('Reviewed npm overlay bytes differ')
    original=_read(source/'pnpm-lock.yaml')
    digest=hashlib.sha256(original).hexdigest()
    if digest not in (PRISTINE_LOCK_SHA256,PREPARED_LOCK_SHA256):
        raise ValueError('Unreviewed upstream npm graph')
    manager=json.loads(_read(source/'package.json'),object_pairs_hook=_pairs)
    if type(manager) is not dict or manager.get('packageManager')!='pnpm@10.34.9':
        raise ValueError('Reviewed npm graph requires its pinned installer')
    outputs=[]
    for relative,name,field,package,prior in MANIFESTS:
        path=source/relative
        value=json.loads(_read(path),object_pairs_hook=_pairs)
        expected=prior if digest==PRISTINE_LOCK_SHA256 else NPM_TAURI_VERSION
        if (type(value) is not dict or value.get('name')!=name or type(value.get(field)) is not dict
                or value[field].get(package)!=expected):
            raise ValueError('Reviewed npm manifest role or dependency differs')
        value[field][package]=NPM_TAURI_VERSION
        outputs.append((path,(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf-8')))
    # Validate the entire pair before the first write. A reviewed repeat is byte-preserving.
    if digest==PREPARED_LOCK_SHA256:return
    for path,raw in outputs:path.write_bytes(raw)
    (source/'pnpm-lock.yaml').write_bytes(replacement)
