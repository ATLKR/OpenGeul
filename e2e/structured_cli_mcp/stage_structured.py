"""Draft native stage, requiring an observed Source-built generator and immutable source copy.

Not executed in this Linux draft. Workflow build remains a mandatory authority:
--expected-generator-sha256 must come from the same Source job's built binary.
"""
import argparse,hashlib,json,subprocess,sys
from pathlib import Path
import structured_oracle as oracle
HERE=Path(__file__).resolve().parent
ROOT=next(p for p in HERE.parents if (p/'config/upstream.lock.json').is_file())
sys.path[:0]=[str(ROOT/'e2e'),str(ROOT/'scripts')]
from mcp_worker import current_binding,strict_json,WorkerWatch
from native_architecture import verify_process,verify_host,verify_executable
import windows_components as components
from valid_companion import helpers,verify_generation

INPUTS=('structured.hwp','structured.hwpx','checkerboard.png','generation.json')
TRANSPORT_KEYS={'formatVersion','repository','sourceCommit','sourceRun','runAttempt','architecture',
                'editorProvenanceSha256','sourceContractSha256','generatorSha256','inputSha256','helperSha256'}

def require(value,message):
    if not value:raise ValueError(message)
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def input_hashes(folder):
    files,directories=components.tree(Path(folder),16*1024*1024)
    require(not directories and set(files)==set(INPUTS),'Exactly four regular owned structured input files are required')
    return {name:files[name]['sha256'] for name in INPUTS}

def verify_transport(value,package,binding,architecture,folder,helper_map):
    require(type(value) is dict and set(value)==TRANSPORT_KEYS and type(value['formatVersion']) is int and value['formatVersion']==1,
            'Exact structured editor input binding is required')
    require(value['repository']=='ATLKR/OpenGeul' and value['architecture']==architecture and
            all(value[key]==expected for key,expected in binding.items()),'Structured input source/run/attempt/architecture differs')
    require(package.get('repository')=='ATLKR/OpenGeul' and package.get('architecture')==architecture and
            package.get('commit')==binding['sourceCommit'] and package.get('runId')==binding['sourceRun'],
            'Structured input package source differs')
    provenance=package.get('windowsComponents',{})
    require(all(provenance.get(key)==expected for key,expected in
            {'repository':'ATLKR/OpenGeul','commit':binding['sourceCommit'],'runId':binding['sourceRun'],'runAttempt':binding['runAttempt']}.items()),
            'Structured input component source differs')
    editor=provenance.get('components',{}).get('editor',{})
    require(value['editorProvenanceSha256']==editor.get('provenanceSha256') and
            value['sourceContractSha256']==provenance.get('sourceContractSha256') and
            value['helperSha256']==helper_map and value['inputSha256']==input_hashes(folder),
            'Structured input differs from externally bound editor/source/helpers/bytes')
    for key in ('editorProvenanceSha256','sourceContractSha256','generatorSha256'):
        require(type(value[key]) is str and components.SHA.fullmatch(value[key]),'Structured input SHA differs')
    return value['generatorSha256']

def generate(a):
    binding=current_binding();verify_host(a.architecture);verify_executable(a.generator_exe,a.architecture)
    components.regular(a.generator_exe)
    require(digest(a.generator_exe)==a.expected_generator_sha256,'Built same-job native generator SHA differs')
    components._ancestors(a.prepared_source)
    source=a.prepared_source;_,contract=components.source_contract(source,components.configured())
    relative='apps/desktop/src-tauri/examples/opengeul-structured-fixtures.rs';copied=source/relative
    components.regular(copied)
    require(copied.is_file() and not copied.is_symlink() and digest(copied)==digest(HERE/'generate_structured.rs'),'Prepared native target differs from owned generator')
    expected=strict_json((HERE/'expected.json').read_bytes());components.fresh(a.out);a.out.mkdir(parents=True)
    (a.out/'checkerboard.png').write_bytes(oracle.checkerboard())
    native=None;process=None
    try:
        process=subprocess.Popen([str(a.generator_exe.resolve()),str(a.out.resolve())],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,cwd=source/'apps/desktop/src-tauri')
        native=verify_process(process.pid,a.generator_exe,a.architecture,handle=int(process._handle));watch=WorkerWatch(native,a.generator_exe,a.expected_generator_sha256,a.architecture,context='portable');native['createdFileTime']=watch.created(int(process._handle))
        raw,_=process.communicate(timeout=60);require(process.returncode==0 and len(raw)<=65536,'Actual native structured generator failed');reply=strict_json(raw)
        require(reply=={'generated':True,'files':['structured.hwp','structured.hwpx'],'table':{'section':0,'paragraph':4,'control':0}},'Explicit native generator output differs')
        require((a.out/'structured.hwp').read_bytes().startswith(bytes.fromhex('d0cf11e0a1b11ae1')) and (a.out/'structured.hwp').stat().st_size<=oracle.CAP,'Generated HWP CFB missing/unbounded')
        original=oracle.inspect_hwpx(a.out/'structured.hwpx',expected);oracle.verify_original(original,expected)
        # No preflight native outcome is represented as CLI/MCP feature success.
        proof={'formatVersion':1,**binding,'architecture':a.architecture,'sourceContractSha256':hashlib.sha256(components.encoded(contract)).hexdigest(),'generatorSha256':digest(HERE/'generate_structured.rs'),'stageSha256':digest(Path(__file__)),'oracleSha256':digest(HERE/'structured_oracle.py'),'definitionSha256':digest(HERE/'expected.json'),'lockSha256':digest(ROOT/'config/upstream.lock.json'),'preparedGeneratorSha256':digest(copied),'generatorNative':native,'generatorExitCode':process.returncode,'stdoutSha256':hashlib.sha256(raw).hexdigest(),'stdoutBytes':len(raw),'inputs':{n:digest(a.out/n) for n in ('structured.hwp','structured.hwpx','checkerboard.png')},'independentOriginalVerified':True}
        (a.out/'generation.json').write_text(json.dumps(proof,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8')
        input_hashes(a.out)
    finally:
        if process and process.poll() is None:process.kill();process.wait(timeout=10)
def seal(a):
    binding=current_binding();verify_host(a.architecture)
    components.regular(a.generator_exe);verify_executable(a.generator_exe,a.architecture)
    editor=components.validate_component(a.editor_component,'editor',components.identity(),components.configured(),architecture=a.architecture)
    require(editor['runAttempt']==binding['runAttempt'],'Structured fixtures require this exact editor attempt')
    source_hash=hashlib.sha256(components.encoded(editor['source'])).hexdigest()
    hashes=input_hashes(a.fixtures);helper_map=helpers();generator_hash=digest(a.generator_exe)
    generation=strict_json((a.fixtures/'generation.json').read_bytes())
    verify_generation(generation,binding,helper_map,a.architecture,generator_hash,hashes,source_hash)
    value={'formatVersion':1,'repository':'ATLKR/OpenGeul',**binding,'architecture':a.architecture,
           'editorProvenanceSha256':digest(a.editor_component/'provenance.json'),'sourceContractSha256':source_hash,
           'generatorSha256':generator_hash,'inputSha256':hashes,'helperSha256':helper_map}
    components.fresh(a.out)
    with a.out.open('xb') as stream:stream.write(components.encoded(value))

def main():
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='command',required=True)
    g=sub.add_parser('generate');g.add_argument('--generator-exe',type=Path,required=True);g.add_argument('--expected-generator-sha256',required=True);g.add_argument('--prepared-source',type=Path,required=True);g.add_argument('--architecture',choices=('x64','arm64'),required=True);g.add_argument('--out',type=Path,required=True)
    s=sub.add_parser('seal');s.add_argument('--generator-exe',type=Path,required=True);s.add_argument('--editor-component',type=Path,required=True);s.add_argument('--fixtures',type=Path,required=True);s.add_argument('--architecture',choices=('x64','arm64'),required=True);s.add_argument('--out',type=Path,required=True)
    a=p.parse_args();(generate if a.command=='generate' else seal)(a)

if __name__=='__main__':
    try:main()
    except Exception:raise SystemExit('Owned structured fixture generation/sealing failed; no native success is claimed.') from None
