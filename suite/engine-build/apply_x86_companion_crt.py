"""Install two exact per-target CRT source choices; never qualify a native build."""
from pathlib import Path
import hashlib
import stat

CORE='9dea406ab7695df6325b11b0e19fdca8db4b7276'
CONDITION='WNT_X86_64_MSC'
PINS=[{'path': 'shell/Library_spsupp_x86.mk', 'size': 1444, 'sha256': '68a515669d5730ef7ce4d23def0c288110b259ba01e89aa3bb3275d33b496c56', 'afterSize': 1630, 'afterSha256': '5b1c4729b8861e72422ba08cc6d8af5b5adc69c721f5f877991c7c915fe486a3'}, {'path': 'extensions/Executable_twain32shim.mk', 'size': 1235, 'sha256': '9dfc8323e9d5af2611a9330fd67d7244a248825af1ce73aa7bd9ecdea1d674c4', 'afterSize': 1425, 'afterSha256': 'f669bc99d15f302aed5a6dd9af94c700ff9a0add204166a1e029d8f9093b1c61'}]

def _sha(raw):return hashlib.sha256(raw).hexdigest()

def _directory(path):
    for item in (path,*path.parents):
        s=item.lstat()
        if not stat.S_ISDIR(s.st_mode) or getattr(s,'st_file_attributes',0)&0x400:
            raise ValueError('x86-companion-crt-input')

def _read(path):
    _directory(path.parent);s=path.lstat()
    if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1 or getattr(s,'st_file_attributes',0)&0x400 or not 0<s.st_size<=512*1024:
        raise ValueError('x86-companion-crt-input')
    return path.read_bytes()

def descriptor(value):
    if type(value) is not dict or set(value)!={'condition','sources'} or value['condition']!=CONDITION or value['sources']!=PINS:
        raise ValueError('x86-companion-crt-input')
    for row in value['sources']:
        if type(row) is not dict or any(type(row[k]) is not int for k in ('size','afterSize')):
            raise ValueError('x86-companion-crt-input')
    return value

def addition(path):
    if path==PINS[0]['path']:api,target='Library','spsupp_x86'
    elif path==PINS[1]['path']:api,target='Executable','twain32shim'
    else:raise ValueError('x86-companion-crt-input')
    return ('\n# Keep this x86 OS-only companion independent of the packaged x64 CRT.\nifeq ($(OS)_$(CPUNAME)_$(COM),WNT_X86_64_MSC)\n$(eval $(call gb_'+api+'_add_cxxflags,'+target+',-MT -U_DLL))\nendif\n').encode()

def transform(original,pin):
    if pin not in PINS or type(pin.get('size')) is not int or type(pin.get('afterSize')) is not int:
        raise ValueError('x86-companion-crt-input')
    api,target=('Library','spsupp_x86')if pin['path']==PINS[0]['path']else('Executable','twain32shim')
    anchor=('$(eval $(call gb_'+api+'_set_x86,'+target+',YES))\n').encode()
    if type(original) is not bytes or len(original)!=pin['size'] or _sha(original)!=pin['sha256'] or original.count(anchor)!=1:
        raise ValueError('x86-companion-crt-input')
    result=original.replace(anchor,anchor+addition(pin['path']),1)
    if len(result)!=pin['afterSize'] or _sha(result)!=pin['afterSha256']:raise ValueError('x86-companion-crt-input')
    return result

def install(source,evidence,value):
    descriptor(value);source=Path(source).absolute();evidence=Path(evidence).absolute();_directory(source);_directory(evidence)
    if source==evidence or source in evidence.parents or evidence in source.parents:raise ValueError('x86-companion-crt-input')
    prepared=[]
    for pin in PINS:
        target=source/pin['path'];original=_read(target);effective=transform(original,pin)
        retained={side:evidence/(side+'-x64-'+Path(pin['path']).name)for side in ('original','effective')}
        if any(p.exists()or p.is_symlink()for p in retained.values()):raise ValueError('x86-companion-crt-input')
        prepared.append((pin,target,original,effective,retained))
    rows=[]
    for pin,target,original,effective,retained in prepared:
        for side,raw in [('original',original),('effective',effective)]:
            with retained[side].open('xb')as stream:stream.write(raw)
        target.write_bytes(effective)
        if _read(target)!=effective:raise ValueError('x86-companion-crt-output')
        rows.append(dict(path=pin['path'],beforeBytes=len(original),afterBytes=len(effective),beforeSha256=_sha(original),afterSha256=_sha(effective),evidence={side:str(path)for side,path in retained.items()}))
    return dict(schemaVersion=1,kind='windows-x64-x86-companion-static-runtime-source-hooks',coreCommit=CORE,architecture='x64',condition=CONDITION,recipes=rows,nativeBuildVerified=False,fullEngineQualified=False,acceptanceEligible=False,guiVerified=False)
