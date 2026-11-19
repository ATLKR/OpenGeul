"""Select one reviewed npm graph; package scripts and installers run elsewhere."""
import hashlib
import json
import os
from pathlib import Path
import stat

ROOT=Path(__file__).resolve().parents[1]
PRISTINE_LOCK_SHA256='ed88ee7fcf037e64667c18fe2421f9010c543b066cdd423c47ad20235426cba2'
BASELINE_LOCK_SHA256='9625a90ccd967d8ad49716b8ed00b8fb61b5c78bd8bb81c1d9d02220bf4fcd14'
BASELINE_LOCK=ROOT/'overlay/baseline-pnpm-lock.txt'
PREPARED_LOCK_SHA256='b3d461da3ad8f7c9667f3cc9c1bb3a3cfb0be056b473bdd9690e029aaf44e3e0'
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
        # Windows Python3.12 path ctime is creation time; fstat ctime is change time.
        stamp=getattr(value,'st_birthtime_ns',None) if os.name=='nt' else value.st_ctime_ns
        if type(stamp) is not int:raise ValueError('Reviewed npm input timestamp unavailable')
        return value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns,stamp,value.st_nlink
    with path.open('rb') as stream:
        opened=os.fstat(stream.fileno())
        if identity(opened)!=identity(info):raise ValueError('Reviewed npm input identity differs')
        raw=stream.read(MAX_INPUT+1)
        after=os.fstat(stream.fileno())
    final=path.lstat()
    if (len(raw)!=info.st_size or len(raw)>MAX_INPUT or identity(after)!=identity(opened)
            or after.st_ctime_ns!=opened.st_ctime_ns or final.st_ctime_ns!=info.st_ctime_ns
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


def pin_frontend_dependencies(source,*,baseline=False):
    if type(baseline) is not bool:raise ValueError('Select a named frontend source phase')
    source=Path(source)
    selected_lock=BASELINE_LOCK if baseline else PREPARED_LOCK
    selected_digest=BASELINE_LOCK_SHA256 if baseline else PREPARED_LOCK_SHA256
    replacement=_read(selected_lock)
    if hashlib.sha256(replacement).hexdigest()!=selected_digest:
        raise ValueError('Reviewed npm overlay bytes differ')
    original=_read(source/'pnpm-lock.yaml')
    digest=hashlib.sha256(original).hexdigest()
    if digest not in (PRISTINE_LOCK_SHA256,selected_digest):
        raise ValueError('Unreviewed upstream npm graph')
    manager=json.loads(_read(source/'package.json'),object_pairs_hook=_pairs)
    if type(manager) is not dict or manager.get('packageManager')!='pnpm@10.34.9':
        raise ValueError('Reviewed npm graph requires its pinned installer')
    upstream=json.loads(_read(source/'third_party/rhwp/rhwp-studio/package.json'),object_pairs_hook=_pairs)
    version,vite=('0.9.0','^8.3.5') if baseline else ('0.9.1','^8.3.8')
    if (type(upstream) is not dict or upstream.get('name')!='rhwp-studio' or upstream.get('version')!=version
            or type(upstream.get('dependencies')) is not dict or type(upstream.get('devDependencies')) is not dict
            or upstream['dependencies'].get('@noble/hashes')!='^2.4.0'
            or upstream['dependencies'].get('canvaskit-wasm')!='^0.42.0'
            or upstream['devDependencies'].get('typescript')!='^7.0.2'
            or upstream['devDependencies'].get('vite')!=vite
            or type(manager.get('dependencies')) is not dict
            or manager['dependencies'].get('@noble/hashes')!=upstream['dependencies']['@noble/hashes']):
        raise ValueError('Imported rhwp frontend contract differs')
    outputs=[]
    for relative,name,field,package,prior in MANIFESTS:
        path=source/relative
        value=json.loads(_read(path),object_pairs_hook=_pairs)
        expected=prior if digest==PRISTINE_LOCK_SHA256 else NPM_TAURI_VERSION
        if (type(value) is not dict or value.get('name')!=name or type(value.get(field)) is not dict
                or value[field].get(package)!=expected):
            raise ValueError('Reviewed npm manifest role or dependency differs')
        value[field][package]=NPM_TAURI_VERSION
        if name=='@golbin/hop-studio-host':
            dependencies=value.get('devDependencies')
            prior_vite='^8.3.5' if digest==PRISTINE_LOCK_SHA256 else vite
            if (type(dependencies) is not dict or dependencies.get('vite')!=prior_vite
                    or dependencies.get('typescript')!=upstream['devDependencies']['typescript']
                    or dependencies.get('canvaskit-wasm')!=upstream['dependencies']['canvaskit-wasm']):
                raise ValueError('Host frontend contract differs')
            dependencies['vite']=vite
        outputs.append((path,(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf-8')))
    # Validate the entire pair before the first write. A reviewed repeat is byte-preserving.
    if digest==selected_digest:return
    for path,raw in outputs:path.write_bytes(raw)
    (source/'pnpm-lock.yaml').write_bytes(replacement)
