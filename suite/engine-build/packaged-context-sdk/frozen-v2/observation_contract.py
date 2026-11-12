"""Source-only read-only observation metadata, never runtime/phase authority.

Identifiers are 1..256 ASCII [A-Za-z0-9._-]. SID subauthorities are
canonical decimal DWORDs. Windows inputs use drive-absolute backslashes;
UNC/device/ADS, empty/dot/parent, trailing-dot/space and reserved DOS aliases
are rejected. The maximum is 1024 UTF-16 code units, not codepoints. Only
ASCII A-Z are folded for path equality; other characters are preserved and
Unicode case substitutions are unsupported. A typed native caller
must remove its own verified GetFinalPathName ``\\\\?\\X:\\`` prefix first.

Bundle roots contain runtime files only, not this project's docs/tests. The
caller supplies an independent exact file set and external manifest SHA.
These hashes identify source bytes, not an executable or installed package.
"""
from pathlib import Path
import hashlib
import json
import os
import re
import stat

AUTHORITY_FLAGS=('actualWindowsExecuted','qualification','canService',
    'originalHelperHandleKnown','controllerOwnershipKnown','durableLease',
    'watchdogVerified','osImplicitEffectsKnown','createdByThisRun','preexistingAdopted')
_SHA=re.compile(r'[0-9a-f]{64}\Z')
_FILE_ID=re.compile(r'[0-9a-f]{32}\Z')
_IDENTIFIER=re.compile(r'[A-Za-z0-9._-]{1,256}\Z')
_RESERVED=re.compile(r'(?:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\..*)?\Z',re.I)
_ROOTS=frozenset(('productLocalData','productRoamingData','localState'))
_LOCAL=frozenset(('productLocalData','productRoamingData'))
_CLOCK=frozenset(('startQpc','phaseDeadlineQpc','observerDeadlineQpc','qpcFrequency'))
_RECIPE=frozenset(('formatVersion','identifier','tauriConfigSha256','webviewManagerSha256',
                  'pathResolverSha256','appDirectoriesOverride','dataDirectory'))
_EXPECT=frozenset(('schemaVersion','kind','packageFullName','packageFamilyName','userSid',
                  'architecture','sourceRecipe','logicalPaths','clock','sourceBundleSha256'))
_COMMON=frozenset(('schemaVersion','kind','observationComplete','failureCode','simulationOnly',*AUTHORITY_FLAGS))
_SUCCESS=_COMMON|frozenset(('requestSha256','sourceBundleSha256','package','knownFolders',
    'directories','clock','allDirectoryHandlesHeldTogether','processGenerationRechecked'))
_DIRECTORY=frozenset(('logicalPath','finalPath','volumeSerial','fileId','creationFileTime',
    'desiredAccess','shareMode','openDisposition','reparse','handleRetainedDuringObservation','handleClosed'))
_UINT64=(1<<64)-1
_QPC_MAX=(1<<63)-1
_MAX_JSON=65536
_MAX_FILE=512*1024
_MAX_TOTAL=2*1024*1024
_ASCII_FOLD=str.maketrans('ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz')


class ContractError(ValueError):
    """Every error emitted below is a fixed code without observed values."""


def _require(condition,code):
    if not condition:raise ContractError(code)


def _keys(value,keys,code):
    _require(type(value) is dict and all(type(k) is str for k in value) and set(value)==keys,code)


def _integer(value,minimum=0,maximum=_UINT64):
    return type(value) is int and minimum<=value<=maximum


def _digest(value):
    return type(value) is str and _SHA.fullmatch(value) is not None


def _sid(value):
    if type(value) is not str or len(value)>256 or not value.startswith('S-1-5-'):return False
    parts=value[6:].split('-')
    return (1<=len(parts)<=15 and all(re.fullmatch(r'(?:0|[1-9][0-9]{0,9})',p)
            and int(p)<=0xffffffff for p in parts))


def _component(value):
    return (bool(value) and value not in ('.','..') and not value.endswith(('.', ' '))
            and _RESERVED.fullmatch(value) is None and not any(ord(c)<32 or ord(c)==127 or
            0xd800<=ord(c)<=0xdfff or c in '<>:"|?*' for c in value))


def _fold(value):return value.translate(_ASCII_FOLD)


def _windows_path(value,code):
    _require(type(value) is str and 3<=len(value)<=1024 and re.match(r'^[A-Za-z]:\\',value)
             and '/' not in value and ':' not in value[2:],code)
    try:units=len(value.encode('utf-16-le','strict'))//2
    except UnicodeError:raise ContractError(code) from None
    _require(units<=1024,code)
    _require(value[3:]=='' or all(_component(p) for p in value[3:].split('\\')),code)
    return _fold(value)


def _encoded(value,code):
    try:raw=json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('ascii')
    except (ValueError,TypeError,OverflowError,RecursionError):raise ContractError(code) from None
    _require(0<len(raw)<=_MAX_JSON,code)
    return raw


def _expectation(data):
    code='INVALID_EXPECTATION';_keys(data,_EXPECT,code)
    _require(type(data['schemaVersion']) is int and data['schemaVersion']==1 and
             type(data['kind']) is str and data['kind']=='source-only-packaged-context-expectation',code)
    _require(all(type(data[k]) is str and _IDENTIFIER.fullmatch(data[k]) for k in
                 ('packageFullName','packageFamilyName')) and _sid(data['userSid']) and
             type(data['architecture']) is str and data['architecture'] in ('x64','arm64'),code)
    recipe=data['sourceRecipe'];_keys(recipe,_RECIPE,code)
    _require(type(recipe['formatVersion']) is int and recipe['formatVersion']==1 and
             type(recipe['identifier']) is str and recipe['identifier']=='org.allenlabs.opengeul' and
             all(_digest(recipe[k]) for k in ('tauriConfigSha256','webviewManagerSha256','pathResolverSha256')) and
             recipe['appDirectoriesOverride'] is None and recipe['dataDirectory'] is None,code)
    paths=data['logicalPaths'];_keys(paths,_LOCAL,code)
    _require(len({_windows_path(value,code) for value in paths.values()})==2,code)
    clock=data['clock'];_keys(clock,_CLOCK,code)
    _require(all(_integer(v,1,_QPC_MAX) for v in clock.values()),code)
    start,phase,observer,frequency=(clock[k] for k in ('startQpc','phaseDeadlineQpc','observerDeadlineQpc','qpcFrequency'))
    _require(start<observer<=phase<=start+90*frequency and observer<=start+10*frequency,code)
    _require(_digest(data['sourceBundleSha256']),code)


class ExpectedObservation:
    """Immutable independent source-only request, not a capability or lease."""
    __slots__=('_canonical','_digest')

    def __init__(self):raise ContractError('EXPECTED_FACTORY_REQUIRED')

    def __setattr__(self,name,value):raise AttributeError('SOURCE_ONLY_EXPECTATION_IMMUTABLE')

    @classmethod
    def from_data(cls,value):
        try:
            _expectation(value);raw=_encoded(value,'INVALID_EXPECTATION')
            result=object.__new__(cls)
            object.__setattr__(result,'_canonical',raw)
            object.__setattr__(result,'_digest',hashlib.sha256(raw).hexdigest())
            return result
        except ContractError:raise
        except Exception:raise ContractError('INVALID_EXPECTATION') from None

    @property
    def sha256(self):return self._digest

    def to_data(self):return json.loads(self._canonical)


def _flags(record,code):
    _require(type(record['simulationOnly']) is bool,code)
    _require(all(record[k] is False for k in AUTHORITY_FLAGS),code)


def _observation(record,expected):
    code='INVALID_OBSERVATION'
    _require(type(expected) is ExpectedObservation,code)
    checked=ExpectedObservation.from_data(expected.to_data());request=checked.to_data()
    _require(type(record) is dict and type(record.get('kind')) is str,code)
    if record.get('kind')=='packaged-context-readonly-failure':
        _keys(record,_COMMON,code);_flags(record,code)
        _require(type(record['schemaVersion']) is int and record['schemaVersion']==1 and
                 _integer(record['failureCode'],1,31) and record['observationComplete'] is False,code)
        raise ContractError('OBSERVATION_INCOMPLETE')
    _keys(record,_SUCCESS,code);_flags(record,code)
    _require(type(record['schemaVersion']) is int and record['schemaVersion']==1 and
             record['kind']=='packaged-context-readonly-observation' and record['observationComplete'] is True and
             type(record['failureCode']) is int and record['failureCode']==0,code)
    _require(_digest(record['requestSha256']) and _digest(record['sourceBundleSha256']) and
             record['requestSha256']==checked.sha256 and record['sourceBundleSha256']==request['sourceBundleSha256'],code)
    package=record['package']
    _keys(package,frozenset(('fullName','familyName','userSid','pid','createdFileTime','nativeMachine','processMachine')),code)
    _require(all(type(package[key]) is str and package[key]==request[wanted] for key,wanted in
                 (('fullName','packageFullName'),('familyName','packageFamilyName'),('userSid','userSid'))),code)
    machine=34404 if request['architecture']=='x64' else 43620
    _require(_integer(package['pid'],1,0xffffffff) and _integer(package['createdFileTime'],1) and
             type(package['nativeMachine']) is int and package['nativeMachine']==machine and
             type(package['processMachine']) is int and package['processMachine']==0,code)
    known=record['knownFolders'];_keys(known,frozenset(('localAppData','roamingAppData')),code)
    for path in known.values():_windows_path(path,code)
    roots=record['directories'];_keys(roots,_ROOTS,code);identities=set()
    for name,directory in roots.items():
        _keys(directory,_DIRECTORY,code)
        logical=_windows_path(directory['logicalPath'],code);_windows_path(directory['finalPath'],code)
        if name in _LOCAL:
            folder='localAppData' if name=='productLocalData' else 'roamingAppData'
            root=known[folder];joined=root+('' if root.endswith('\\') else '\\')+request['sourceRecipe']['identifier']
            _require(logical==_windows_path(request['logicalPaths'][name],code)==_windows_path(joined,code),code)
        _require(_integer(directory['volumeSerial']) and type(directory['fileId']) is str and
                 _FILE_ID.fullmatch(directory['fileId']) and directory['fileId']!='0'*32 and
                 _integer(directory['creationFileTime'],1),code)
        _require(all(type(directory[key]) is int and directory[key]==value for key,value in
                     (('desiredAccess',128),('shareMode',7),('openDisposition',3))) and
                 directory['reparse'] is False and directory['handleRetainedDuringObservation'] is True and
                 directory['handleClosed'] is True,code)
        identities.add((directory['volumeSerial'],directory['fileId']))
    _require(len(identities)==3 and record['allDirectoryHandlesHeldTogether'] is True and
             record['processGenerationRechecked'] is True,code)
    clock=record['clock'];_keys(clock,frozenset(('startedQpc','finishedQpc','deadlineQpc','qpcFrequency')),code)
    _require(all(_integer(v,1,_QPC_MAX) for v in clock.values()),code)
    requested=request['clock']
    _require(clock['qpcFrequency']==requested['qpcFrequency'] and clock['deadlineQpc']==requested['observerDeadlineQpc'] and
             requested['startQpc']<=clock['startedQpc']<=clock['finishedQpc']<requested['observerDeadlineQpc'],code)
    return json.loads(_encoded(record,code))


def validate_observation(record,expected):
    """Return a copied complete metadata record; no native fact is attested."""
    try:return _observation(record,expected)
    except ContractError:raise
    except Exception:raise ContractError('INVALID_OBSERVATION') from None


def as_phase_witness(*args,**kwargs):
    raise ContractError('OBSERVATION_IS_NOT_PHASE_AUTHORITY')


def run_native(*args,**kwargs):
    raise ContractError('OWNED_LAUNCH_AND_WATCHDOG_UNVERIFIED')


def _bundle_path(value):
    code='INVALID_BUNDLE'
    _require(type(value) is str and 0<len(value)<=1024 and '\\' not in value and ':' not in value and
             not value.startswith('/') and all(_component(p) for p in value.split('/')),code)
    _require(len(value.encode('utf-8','strict'))<=1024,code)
    return value


def _pairs(values):
    result={}
    for key,value in values:
        _require(key not in result,'INVALID_BUNDLE');result[key]=value
    return result


def _constant(value):raise ContractError('INVALID_BUNDLE')


def _stat(path,*,directory=False):
    value=os.lstat(path)
    _require(not stat.S_ISLNK(value.st_mode) and not (getattr(value,'st_file_attributes',0)&0x400),'INVALID_BUNDLE')
    _require(stat.S_ISDIR(value.st_mode) if directory else stat.S_ISREG(value.st_mode),'INVALID_BUNDLE')
    if not directory:_require(value.st_nlink==1 and value.st_ino>0,'INVALID_BUNDLE')
    return value


def _directory_stamp(value):return value.st_dev,value.st_ino,stat.S_IFMT(value.st_mode)


def _file_stamp(value):
    return (value.st_dev,value.st_ino,value.st_mode,value.st_nlink,value.st_size,
            value.st_mtime_ns,value.st_ctime_ns,getattr(value,'st_file_attributes',0))


def _chain(root):
    return tuple((path,_directory_stamp(_stat(path,directory=True))) for path in (*reversed(root.parents),root))


def _inventory(root,expected_paths):
    allowed_dirs={part for name in expected_paths for part in Path(name).parents if str(part)!='.'}
    files={};directories={};pending=[root];entries=0
    while pending:
        directory=pending.pop();directories[str(directory.relative_to(root))]=_directory_stamp(_stat(directory,directory=True))
        names=set()
        with os.scandir(directory) as children:
            for child in children:
                entries+=1;_require(entries<=256,'INVALID_BUNDLE')
                _require(_fold(child.name) not in names,'INVALID_BUNDLE');names.add(_fold(child.name))
                path=directory/child.name;name=path.relative_to(root).as_posix();_bundle_path(name)
                info=os.lstat(path)
                if stat.S_ISDIR(info.st_mode):
                    _require(Path(name) in allowed_dirs,'INVALID_BUNDLE');_stat(path,directory=True);pending.append(path)
                else:
                    _require(name in expected_paths,'INVALID_BUNDLE');files[name]=_file_stamp(_stat(path))
        _require(len(files)<=16 and len(directories)<=256,'INVALID_BUNDLE')
    _require(set(files)==set(expected_paths),'INVALID_BUNDLE')
    return files,directories


def _read_member(path,expected_size):
    before=_stat(path);stamp=_file_stamp(before)
    _require(before.st_size==expected_size,'INVALID_BUNDLE')
    flags=os.O_RDONLY|getattr(os,'O_BINARY',0)|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_CLOEXEC',0)
    handle=os.open(path,flags)
    try:
        opened=os.fstat(handle)
        _require(_file_stamp(opened)==stamp and stat.S_ISREG(opened.st_mode) and opened.st_nlink==1,'INVALID_BUNDLE')
        digest=hashlib.sha256();count=0
        while True:
            data=os.read(handle,min(65536,expected_size+1-count))
            if not data:break
            count+=len(data);_require(count<=expected_size,'INVALID_BUNDLE');digest.update(data)
        _require(count==expected_size and _file_stamp(os.fstat(handle))==stamp and
                 _file_stamp(_stat(path))==stamp,'INVALID_BUNDLE')
        return digest.hexdigest()
    finally:os.close(handle)


def _bundle(root,raw,expected_sha256,expected_paths):
    code='INVALID_BUNDLE'
    _require(type(raw) is bytes and 0<len(raw)<=_MAX_JSON and _digest(expected_sha256),code)
    _require(hashlib.sha256(raw).hexdigest()==expected_sha256,'BUNDLE_BINDING_MISMATCH')
    _require(type(expected_paths) in (tuple,list,set,frozenset) and 1<=len(expected_paths)<=16,code)
    paths=tuple(_bundle_path(p) for p in expected_paths)
    _require(len({_fold(p) for p in paths})==len(paths),code)
    text=raw.decode('utf-8','strict');_require(not text.startswith('\ufeff'),code)
    value=json.loads(text,object_pairs_hook=_pairs,parse_constant=_constant)
    _keys(value,frozenset(('schemaVersion','kind','files')),code)
    _require(type(value['schemaVersion']) is int and value['schemaVersion']==1 and type(value['kind']) is str and
             value['kind']=='packaged-context-source-bundle' and type(value['files']) is list and 1<=len(value['files'])<=16,code)
    rows={};folded=set();total=0
    for row in value['files']:
        _keys(row,frozenset(('path','bytes','sha256')),code);name=_bundle_path(row['path'])
        _require(_fold(name) not in folded and _integer(row['bytes'],1,_MAX_FILE) and _digest(row['sha256']),code)
        folded.add(_fold(name));rows[name]=row;total+=row['bytes']
    _require(set(rows)==set(paths) and total<=_MAX_TOTAL,code)
    _require(isinstance(root,(str,Path)),code);root=Path(root)
    _require(root.is_absolute() and '..' not in root.parts,code)
    chain=_chain(root);inventory=_inventory(root,paths)
    for name,row in rows.items():_require(_read_member(root/name,row['bytes'])==row['sha256'],code)
    _require(_chain(root)==chain and _inventory(root,paths)==inventory,code)
    return json.loads(_encoded(value,code))


def validate_bundle(root,raw,expected_sha256,*,expected_paths):
    """Authenticate an exact runtime-only source bundle, not runtime authority."""
    try:return _bundle(root,raw,expected_sha256,expected_paths)
    except ContractError:raise
    except Exception:raise ContractError('INVALID_BUNDLE') from None
