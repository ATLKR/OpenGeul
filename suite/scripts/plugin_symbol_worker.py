"""File-only system-symbol queries in one owned child, never in an editor hook."""
import argparse
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'e2e'))
import ascii_message_preparation as shared
from plugin_file_origin import FileApi

# A closed exit-code channel survives Job cleanup without exporting stderr,
# exception messages, paths or symbol names. Parent and child use the same file.
# The signature distinguishes these from ordinary cmd.exe launch failures.
FAILURE_BASE=0x4f470000
IDENTITY_FAILURE_BASE=0x4f480000
FAILURES=tuple(('ResolutionError',code) for code in '''
ambient-symbol-path concurrent-symbol-session fixed-pdb-name fixed-symbol-range
fixed-symbol-roundtrip fixed-symbol-unavailable loaded-symbol-identity local-fixed-drive
local-path-required module-information native-windows-required original-budget-required
pair-hash-mismatch pair-identity-mismatch pair-only-directory pdb-changed pdb-changed-under-lock
pdb-handle pdb-open receipt-size return-rva-bounds symbol-initialize symbol-load
symbol-name-bound symbol-options system-directory unsupported-local-path-encoding
verified-pair-required symbol-unload symbol-cleanup symbol-pdb-handle
image-bytes-mismatch image-handle image-changed-under-lock image-changed
symbol-image-handle symbol-file-open
'''.split())+tuple(('SymbolError',code) for code in '''
absolute-normal-path-required binary-bounds codeview-format codeview-name codeview-pdb-name
codeview-pointer codeview-size configuration-changed copy-identity debug-directory debug-rva
dll-pdb-identity-mismatch file-changed file-identity fixed-config-path fresh-output-required
linked-path managed-image msf-block msf-block-alias msf-directory-map-size msf-directory-shape
msf-directory-size msf-file-size msf-layout msf-stream-count msf-stream-size msf7-header
native-arm64-dll output-path pdb-info-size pdb-info-version pe-directories pe-headers
pe-signature pe-size-or-magic pe32plus read-size receipt-size regular-file-size
section-overlap section-range section-raw section-raw-overlap source-provenance
symbol-identity unique-codeview-required
'''.split())+tuple((category,'unclassified') for category in (
    'AssertionError','OSError','PermissionError','FileNotFoundError','ImportError',
    'ModuleNotFoundError','AttributeError','TypeError','ValueError','TimeoutError'))


def failure_exit_code(error):
    category=type(error).__name__
    if category=='ModuleIdentityError' and len(error.args)==1:
        value=error.args[0]
        if (type(value) is tuple and len(value)==2 and all(type(v) is int for v in value)
                and 0<value[0]<128 and 0<=value[1]<=9):
            return IDENTITY_FAILURE_BASE+(value[1]<<8)+value[0]
        return 1
    code=error.args[0] if len(error.args)==1 and type(error.args[0]) is str else None
    for index,(known_category,known_code) in enumerate(FAILURES):
        if category==known_category and (known_code=='unclassified' or code==known_code):
            return FAILURE_BASE+index+1
    return 1


def inherited_budget(request):
    started,work,deadline=(request[k] for k in ('startedAt','workDeadline','deadline'))
    assert all(type(v) in (float,int) and math.isfinite(v) and v>0 for v in (started,work,deadline))
    assert deadline==started+30 and work==deadline-3,'Inherited deadline changed'
    budget=shared._Budget.__new__(shared._Budget)
    budget.started=budget.last=started;budget.deadline=deadline;budget.work_deadline=work
    budget.now()
    return budget


def read_json(path,budget):
    budget.now();path=shared._absolute(path);budget.now()
    with path.open('rb') as stream:
        budget.now();raw=stream.read(65537);budget.now()
    assert 0<len(raw)<=65536,'Bounded worker JSON required'
    value=json.loads(raw);budget.now()
    assert type(value) is dict,'Worker JSON object required'
    return value


def stages(rows):
    # Do not publish the helper's raw command, path, image or exception text.
    result=[]
    for stage in rows[:1]:
        row={k:stage[k] for k in ('stage','startedAt','finishedAt','natural','queryCount',
            'droppedSamples','handlesClosed','forcedOwnedJobCleanup') if k in stage}
        row['cleanupErrorTypes']=[v['type'] for v in stage.get('cleanupErrors',[])[:4]]
        if 'error' in stage:row['errorType']=stage['error']['type']
        sample=stage.get('cleanupLastSample') or (stage.get('samples') or [None])[-1]
        if sample:
            row['root']={k:sample['root'][k] for k in ('waitResult','exitCode')}
            row['activeProcesses']=sample['activeProcesses'];row['accountingSucceeded']=sample['querySucceeded']
            observed=(stage.get('samples') or [sample])[-1]['root']
            code=observed['exitCode']
            if observed['waitResult']==0 and type(code) is int and FAILURE_BASE<code<=FAILURE_BASE+len(FAILURES):
                category,reason=FAILURES[code-FAILURE_BASE-1]
                row['childFailure']=dict(category=category,code=reason)
            elif observed['waitResult']==0 and type(code) is int and IDENTITY_FAILURE_BASE<code<IDENTITY_FAILURE_BASE+0xa00:
                offset=code-IDENTITY_FAILURE_BASE;mask=offset&255
                if 0<mask<128:
                    row['childFailure']=dict(category='ModuleIdentityError',mismatchMask=mask,symbolType=offset>>8)
        result.append(row)
    return result


def run(pair, *, mode, rvas=None, runtime=None):
    budget=shared._Budget();budget.now()
    assert mode in ('qualify','resolve')
    assert (rvas is None if mode=='qualify' else type(rvas) is list and 0<len(rvas)<=32 and all(type(v) is int and 4<=v<2**32 and v%4==0 for v in rvas))
    shared.native_arch.validate_native_architecture(shared.native_arch.observe_native_architecture(),'arm64');budget.now()
    pair=Path(os.path.abspath(pair));assert not str(pair).startswith(('\\\\','//')),'Local symbol directory required'
    FileApi(budget).preflight(str(pair));budget.now()
    pair=shared._absolute(pair);budget.now()
    folder=Path(tempfile.mkdtemp(prefix='opengeul-plugin-symbol-')).resolve()
    receipt=dict(schemaVersion=1,kind='owned-plugin-symbol-worker',mode=mode,success=False,
        acceptanceEligible=False,runtimeCallerProved=False,temporaryFilesRemoved=False,stages=[])
    internal={'stages':[]};primary=None
    try:
        request=dict(mode=mode,pair=str(pair),rvas=rvas,startedAt=budget.started,
            workDeadline=budget.work_deadline,deadline=budget.deadline)
        (folder/'request.json').write_text(json.dumps(request,allow_nan=False),encoding='utf-8');budget.now()
        script=folder/'compile.cmd'
        script.write_text('@echo off\n"%~1" -I "%~2" --child "%~3" >"%~4" 2>"%~5"\nexit /b %errorlevel%\n',encoding='ascii');budget.now()
        shared._run_stage(runtime or shared._Runtime(),folder,'symbol-'+mode,script,budget,internal,
            [Path(sys.executable).resolve(),Path(__file__).resolve(),folder/'request.json',folder/'stdout',folder/'stderr'])
        result=read_json(folder/'result.json',budget)
        assert result.get('kind')=='local-plugin-symbol-resolution' and result.get('complete') is True and result.get('cleanupComplete') is True
        assert result.get('acceptance') is False and result.get('runtimeCallerProved') is False
        if mode=='qualify':assert result.get('qualification',{}).get('roundTripMatched') is True
        # Child writes the adapter's deliberately path/name-free closed receipt.
        receipt['resolution']=result;receipt.update(success=True,finishedAt=budget.now())
    except BaseException as exc:
        primary=exc;receipt['errorType']=type(exc).__name__
        raise
    finally:
        receipt['stages']=stages(internal['stages'])
        try:
            shutil.rmtree(folder);assert not folder.exists();receipt['temporaryFilesRemoved']=True
            budget.now(cleanup=True)
        except BaseException as cleanup:
            receipt['success']=False;receipt['cleanupErrorType']=type(cleanup).__name__
            if primary is None:cleanup.symbolWorkerReceipt=receipt;raise
        if primary is not None:primary.symbolWorkerReceipt=receipt
    return receipt


def child(request_path):
    # Parent owns/monitors this exact process Job; import and file startup consumes
    # its original monotonic budget. Never construct a fresh child _Budget.
    with Path(request_path).open('rb') as stream:raw=stream.read(65537)
    assert 0<len(raw)<=65536
    request=json.loads(raw);budget=inherited_budget(request)
    assert request['mode'] in ('qualify','resolve')
    spec=importlib.util.spec_from_file_location('owned_plugin_resolution',Path(__file__).with_name('plugin_symbol_resolution.py'))
    adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter);budget.now()
    pair=adapter._path_syntax(request['pair']);runtime=adapter.NativeRuntime(budget)
    runtime.preflight_path(str(pair));budget.now()
    proof=json.loads(adapter.retention.read_regular(pair/'receipt.json',65536,budget=budget));budget.now()
    dll=adapter.retention.read_regular(pair/'vclplug_winlo.dll',adapter.retention.MAX_DLL,budget=budget)
    if request['mode']=='qualify':result=adapter.qualify(dll,pair/'vclplug_winlo.pdb',proof,budget,runtime=runtime)
    else:result=adapter.resolve(dll,pair/'vclplug_winlo.pdb',proof,request['rvas'],budget,runtime=runtime)
    budget.now();raw=json.dumps(result,allow_nan=False).encode();assert len(raw)<=65536
    with Path(request_path).with_name('result.json').open('xb') as stream:stream.write(raw)
    budget.now()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--child',type=Path,required=True)
    args=parser.parse_args()
    try:child(args.child)
    except BaseException as exc:
        raise SystemExit(failure_exit_code(exc))
