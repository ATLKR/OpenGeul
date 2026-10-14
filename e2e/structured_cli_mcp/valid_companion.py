"""Draft portable-only valid structured CLI/MCP companion. No installed33 changes.

Contract-unit tests are not native evidence. main requires real Windows hosted
Source binding, native exe/process observations and owned prevalidated fixtures.
"""
from __future__ import annotations
import argparse,copy,hashlib,json,os,re,shutil,subprocess,sys,tempfile,time
from pathlib import Path,PureWindowsPath
import structured_oracle as oracle
HERE=Path(__file__).resolve().parent
ROOT=next((p for p in HERE.parents if (p/'config/upstream.lock.json').is_file()),None)
if ROOT:sys.path[:0]=[str(ROOT/'e2e'),str(ROOT/'scripts')]
SCOPE='Representative valid structured CLI/MCP categories; COM isolation remains the separate original mandatory suite; not all public tools/installed qualification'
CATEGORIES=('read','search','fields','table','text','session','render','roundtrip')
CASE_IDS=tuple(fmt+'-'+name for fmt in ('hwp','hwpx') for name in CATEGORIES)
REQUIRED_TOOLS={'hwp_info','hwp_export_tables','hwp_fields','hwp_open','hwp_close','hwp_doc_info','hwp_doc_tables','hwp_doc_fields','hwp_doc_tree','hwp_search','hwp_doc_search','hwp_fill_fields','hwp_set_cell','hwp_insert_text','hwp_doc_set_cell','hwp_doc_fill_fields','hwp_doc_save','hwp_doc_render_page','hwp_export_svg','hwp_export_pdf','hwp_convert_hwp5','hwp_convert_hwpx','hwp_ir_diff'}
COMMON_HELPERS=('e2e/mcp_worker.py','e2e/native_architecture.py','e2e/hwpx_oracle.py','scripts/windows_arch.py','config/upstream.lock.json')
DRAFT_HELPERS=('valid_companion.py','structured_oracle.py','generate_structured.rs','stage_structured.py','expected.json')
CASE_CHECKS={
 'read':('typedInventory','tableCellsMatched','fieldsMatched','treeBound','sourceImmutable'),
 'search':('addressesMatched','paginationComplete','noMatchZero','emptyQueryRejected','sourceImmutable'),
 'fields':('dryRunNoOutput','filledCountThree','scopedFields','cliVerify','sourceImmutable'),
 'table':('targetCellOnly','othersPreserved','invalidCellRejected','cliVerify','sourceImmutable'),
 'text':('unicodeOffsets','insertedScalarCount','onlyTargetBody','emptyInsertRejected','sourceImmutable'),
 'session':('twoEditsAccumulated','otherHandleImmutable','keepStylePreserved','reopenedPersisted','saveVerified','sourceImmutable'),
 'render':('svgImageBound','pngPixels','pdfTextAndPixels','ownedOutputs','guardedSvgPdf','sourceImmutable'),
 'roundtrip':('hwpCfb','hwpxZipXml','semanticPreserved','verifyIdentical','cliMcpBoth','sourceImmutable')}
BASE_CALLS={
 'read':('stateless-info','stateless-tables','stateless-fields','open','info','tables','fields','tree','cli-info','cli-tables','cli-fields','close'),
 'search':('open','search','cli-search','first-window','last-window','zero-match','empty-query','negative-ping','close'),
 'fields':('dry-run','fill','cli-fill','output-fields','cli-output-fields'),
 'table':('inventory','set-cell','cli-set-cell','invalid-cell','negative-ping'),
 'text':('insert','cli-insert','empty-insert','negative-ping'),
 'session':('open','inventory','other-open','set-cell','fill-field','tables','fields','other-tables','other-fields','save','close','other-close','reopen','reopen-tables','reopen-fields','reopen-close'),
 'render':('open','doc-svg','close','export-svg','cli-svg','export-pdf','cli-pdf','cli-png'),
 'roundtrip':('seed-base','seed-mcp','seed-cli','to-hwp','to-hwpx','ir-diff','cli-to-hwp','cli-to-hwpx','cli-ir-diff','open','info','tables','fields','close')}

def require(value,message):
    if not value:raise ValueError(message)
def failure_record(error):
    if type(error) is oracle.PdfValidationError:
        value={'failureClass':'validation'}
        if type(error.code) is str and error.code in oracle.PDF_FAILURE_CODES:value['failureCode']=error.code
        return value
    kinds={ValueError:'validation',AssertionError:'assertion',OSError:'os-error',subprocess.TimeoutExpired:'timeout'}
    return {'failureClass':kinds.get(type(error),'unexpected')}
def partial_receipt(proof):
    return {**{key:value for key,value in proof.items() if not key.startswith('_')},'passed':False}
def retain_partial(client,proof,out):
    try:
        if client:
            proof['framesSent']=client.frames_sent;proof['framesReceived']=client.frames_received
            try:client.close()
            finally:proof['serverExited']=client.process.poll() is not None
    finally:
        (Path(out)/'structured-result.json').write_bytes(canonical(partial_receipt(proof))+b'\n')
def integer(v,lo=0,hi=2**31-1):require(type(v) is int and lo<=v<=hi,'Required bounded integer differs');return v
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
def sha(value):require(type(value) is str and re.fullmatch('[0-9a-f]{64}',value),'Required SHA256 differs');return value
def native_binding():
    from mcp_worker import current_binding
    return current_binding()
def helpers():
    require(ROOT is not None,'Exact source checkout is required')
    paths={name:ROOT/name for name in COMMON_HELPERS};paths.update({name:HERE/name for name in DRAFT_HELPERS})
    require(all(p.is_file() and not p.is_symlink() for p in paths.values()),'Required companion helper missing')
    return {name:digest(p) for name,p in paths.items()}
def verify_ir(value):
    require(type(value) is dict and value.get('identical') is True and type(value.get('diffCount')) is int and value['diffCount']==0,'Real supported-fixture IR verification failed')
def source_match(value,source):require(value.get('source')==str(source),'Returned source/docId differs')
def version(value):require(value.get('schemaVersion')=='1.0','Pinned envelope schemaVersion differs')
def verify_search(value,source,expected,offsets,*,last=False,zero=False,paragraph_context=False):
    version(value);source_match(value,source);require(value.get('query')==('OWNED-NO-MATCH' if zero else expected['query']) and value.get('caseSensitive') is True,'Search query/case mode differs')
    count=integer(value.get('matchCount'));total=integer(value.get('totalMatchCount'));omitted=integer(value.get('omittedCount'))
    require(count==len(offsets) and total==(0 if zero else 2) and omitted==total-count and type(value.get('truncated')) is bool and value['truncated']==(count<total),'Search counts/window semantics differ')
    rows=value.get('matches');require(type(rows) is list and len(rows)==count,'Search matches are incomplete')
    for row,offset in zip(rows,offsets):
        require(type(row) is dict and all(type(row.get(k)) is int for k in ('section','paragraph','charOffset','length','page')) and row['section']==expected['search']['section'] and row['paragraph']==expected['search']['paragraph'] and row['charOffset']==offset and row['length']==len(expected['query']) and row['page']==0,'Search address does not match independent body position')
        # GrepMatch.text is the containing paragraph, not the matched substring.
        # Positions use Unicode scalars; the authored emoji makes UTF-16 offsets
        # observably different. This short fixture fits the public 40-char context.
        text=row.get('text');context=row.get('context')
        require(type(text) is str and text==expected['body'] and
                text[offset:offset+row['length']]==expected['query'] and
                type(context) is str and context==expected['body'],
                'Search paragraph, scalar substring or exact context differs')
        require(not {'cell','textbox','equation','nestedDepth'} & set(row),
                'Expected body search unexpectedly reports a nested owner')
        if paragraph_context:
            require(row.get('contextBefore')==[] and row.get('contextAfter')==[expected['tail']],
                    'Stateless search surrounding paragraph inventory differs')
        else:
            require(not {'contextBefore','contextAfter'} & set(row),
                    'Session search unexpectedly includes unrequested paragraph context')
    if last or zero:require('nextOffset' not in value,'Final search window incorrectly advertises another window')
def verify_tables(value,source,expected):
    version(value);source_match(value,source);require(type(value.get('tableCount')) is int and value['tableCount']==1,'One actual table is required')
    tables=value.get('tables');require(type(tables) is list and len(tables)==1,'Actual table inventory differs');table=tables[0]
    require(all(type(table.get(k)) is int for k in ('index','rows','cols','cellCount','section','paragraph','control')) and table['index']==0 and table['rows']==table['cols']==2 and table['cellCount']==4 and table['section']==0 and table['paragraph']==4 and table['control']==0,'Table grid/address types differ')
    values={};require(type(table.get('cells')) is list and len(table['cells'])==4,'Four typed actual cells required')
    for cell in table['cells']:
        require(all(type(cell.get(k)) is int for k in ('row','col','rowSpan','colSpan')) and cell['rowSpan']==cell['colSpan']==1 and type(cell.get('text')) is str and type(cell.get('isHeader')) is bool,'Cell schema/span/header differs')
        key=f"{cell['row']},{cell['col']}";require(key not in values,'Duplicate table cell');values[key]=cell['text']
    require(values==expected['cells'],'Actual cell markers differ');return table['index']
def verify_fields(value,source,expected):
    version(value);source_match(value,source);require(type(value.get('fieldCount')) is int and value['fieldCount']==3,'Three actual fields are required')
    rows=value.get('fields');require(type(rows) is list and len(rows)==3 and type(value.get('textSecurity')) is dict,'Field inventory/security differs');ids=[]
    for row,wanted in zip(rows,expected['fields']):
        require(row.get('name')==wanted['name'] and row.get('value')==wanted['value'] and row.get('fieldType')=='ClickHere','Field name/value/type differs')
        ids.append(integer(row.get('fieldId'),1));loc=row.get('location');require(type(loc) is dict and type(loc.get('section')) is int and loc['section']==0 and type(loc.get('paragraph')) is int and type(loc.get('nested')) is list,'Field location schema differs')
        if wanted['container']=='body':require(loc['paragraph']==wanted['paragraph'] and loc['nested']==[],'Body field position differs')
        else:require(len(loc['nested'])==1 and loc['nested'][0].get('kind')=='tableCell' and loc['nested'][0].get('cell')==wanted['row']*2+wanted['col'],'Cell field scope differs')
    require(len(ids)==len(set(ids)),'Field identifiers duplicate')
def verify_info(value,fmt,source):
    version(value);source_match(value,source)
    require(value.get('format')==('hwp5' if fmt=='hwp' else 'hwpx') and type(value.get('pageCount')) is int and value['pageCount']==1 and type(value.get('paraCount')) is int and value['paraCount']>=6 and type(value.get('sections')) is int and value['sections']==1,'Valid document info differs')
def verify_fill(value,source,*,count,dry=False):
    version(value)
    if 'source' in value:source_match(value,source)
    require(type(value.get('filledCount')) is int and value['filledCount']==count and all(value.get(k)==[] for k in ('notFound','ambiguous','confusable')),'Actual fill count/ambiguity differs')
    require(type(value.get('filled')) is list and len(value['filled'])==count,'Filled field records differ')
    if 'dryRun' in value:require(value['dryRun'] is dry,'Dry-run bool differs')
    if dry:require(value.get('dryRun') is True and value.get('changedPages') is None,'Dry-run must report no written changed pages')
    if dry:require(not {'output','outputFormat','verify'} & set(value),'Dry-run unexpectedly reported an output')
def output_record(value,source,output,fmt,*,verified=False,conversion=False):
    version(value)
    if 'source' in value:source_match(value,source)
    require(value.get('output')==str(output) and output.is_file() and not output.is_symlink() and 0<output.stat().st_size<=oracle.CAP,'Fresh actual output/path missing')
    require(value.get('format' if conversion else 'outputFormat')==('hwp5' if fmt=='hwp' else 'hwpx'),'Actual output format differs')
    if conversion or verified and 'docId' in value:require('bytes' in value,'Required actual output byte count missing')
    if 'bytes' in value:require(type(value['bytes']) is int and value['bytes']==output.stat().st_size,'Output byte count differs')
    if verified:verify_ir(value.get('verify'))
def changed_pages(value):
    pages=value.get('changedPages');require(type(pages) is list and pages==[0] and all(type(v) is int for v in pages),'Expected actual changed page zero')

def call_inventory(fmt,category):
    names=list(BASE_CALLS[category])
    if fmt=='hwp' and category in ('fields','table','text'):names+=['oracle-mcp','oracle-cli']
    if fmt=='hwp' and category=='session':names+=['oracle-session']
    return tuple(names)
def svg_output(value,source,cwd,expected_path):
    version(value);source_match(value,source)
    require(value.get('format')=='svg' and value.get('backend')=='layer' and value.get('outputDir')=='output' and all(type(value.get(k)) is int for k in ('pageCount','renderedCount','overflowCellLines')) and value['pageCount']==value['renderedCount']==1 and value['overflowCellLines']==0 and type(value.get('pages')) is list and len(value['pages'])==1,'Actual SVG page/backend/output/overflow manifest differs')
    item=value['pages'][0];require(type(item) is dict and type(item.get('path')) is str,'Actual SVG file path missing')
    path=Path(item['path']);path=(path if path.is_absolute() else Path(cwd)/path).resolve();expected_path=Path(expected_path).resolve()
    require(path==expected_path and path.is_relative_to(Path(cwd).resolve()) and path.is_file() and not path.is_symlink() and type(item.get('page')) is int and item['page']==0 and type(item.get('bytes')) is int and item['bytes']==path.stat().st_size and type(item.get('overflowCellLines')) is int and item['overflowCellLines']==0,'SVG output path escapes owned cwd or actual page/bytes differs')
    return path

def evidence_file(root,relative):
    require(type(relative) is str and relative and '\\' not in relative and not relative.startswith('/') and ':' not in relative and all(p not in ('','..','.') for p in relative.split('/')),'Unsafe evidence relative path')
    root=Path(root).resolve();path=root/relative
    require(path.resolve().is_relative_to(root) and path.is_file() and not path.is_symlink() and all(not p.is_symlink() for p in path.parents if p!=root.parent),'Owned preserved evidence missing or escaped')
    return path

def expected_channel(name):
    return 'cli' if name.startswith(('cli-','oracle-')) or name in ('preflight-hwp','seed-base','seed-cli') else 'mcp'

def verify_case_inventory(case,inputs):
    require(type(case) is dict and set(case)=={'id','status','checks','calls','sourceBeforeSha256','sourceAfterSha256','artifacts','elapsedMs'} and case['id'] in CASE_IDS,'Explicit required category record differs')
    fmt,category=case['id'].split('-',1)
    require(case['status']=='passed' and type(case['checks']) is dict and set(case['checks'])==set(CASE_CHECKS[category]) and all(v is True for v in case['checks'].values()),'Category completion/check inventory differs')
    require(case['sourceBeforeSha256']==case['sourceAfterSha256']==inputs['structured.'+fmt],'Original category input bytes changed')
    wanted=call_inventory(fmt,category);require(type(case['calls']) is list and tuple(c.get('name') for c in case['calls'])==wanted,'Required subcalls missing/failed/reordered')
    integer(case['elapsedMs']);require(type(case['artifacts']) is list and tuple(a.get('kind') for a in case['artifacts'])==artifact_inventory(fmt,category),'Required actual artifact inventory differs')
    return fmt,category

def expected_operation(name,category=None):
    common={'initialize':'initialize','tools-list':'tools/list','open':'hwp_open','other-open':'hwp_open','reopen':'hwp_open','close':'hwp_close','other-close':'hwp_close','reopen-close':'hwp_close','info':'hwp_doc_info','tables':'hwp_doc_tables','fields':'hwp_doc_fields','tree':'hwp_doc_tree','other-tables':'hwp_doc_tables','other-fields':'hwp_doc_fields','reopen-tables':'hwp_doc_tables','reopen-fields':'hwp_doc_fields','stateless-info':'hwp_info','stateless-tables':'hwp_export_tables','stateless-fields':'hwp_fields','search':'hwp_search','first-window':'hwp_doc_search','last-window':'hwp_doc_search','zero-match':'hwp_doc_search','empty-query':'hwp_doc_search','negative-ping':'ping','dry-run':'hwp_fill_fields','fill':'hwp_fill_fields','output-fields':'hwp_fields','invalid-cell':'hwp_set_cell','insert':'hwp_insert_text','empty-insert':'hwp_insert_text','fill-field':'hwp_doc_fill_fields','save':'hwp_doc_save','doc-svg':'hwp_doc_render_page','export-svg':'hwp_export_svg','export-pdf':'hwp_export_pdf','to-hwp':'hwp_convert_hwp5','to-hwpx':'hwp_convert_hwpx','ir-diff':'hwp_ir_diff','seed-mcp':'hwp_insert_text'}
    cli={'cli-info':'info','cli-tables':'export-tables','cli-fields':'fields','cli-search':'search','cli-fill':'edit fill-fields','cli-set-cell':'edit set-cell','cli-insert':'edit insert-text','cli-output-fields':'fields','cli-svg':'export-svg','cli-pdf':'export-pdf','cli-png':'export-png','cli-to-hwp':'convert','cli-to-hwpx':'export-hwpx','cli-ir-diff':'ir-diff','seed-base':'export-hwpx','seed-cli':'edit insert-text','preflight-hwp':'export-hwpx'}
    if name.startswith('oracle-'):return 'export-hwpx'
    if name=='inventory':return 'hwp_doc_tables' if category=='session' else 'hwp_export_tables'
    if name=='set-cell':return 'hwp_doc_set_cell' if category=='session' else 'hwp_set_cell'
    require(name in common or name in cli,'Unknown explicit subcall');return (cli if name in cli else common)[name]

def artifact_inventory(fmt,category):
    if category in ('read','search'):return ()
    if category in ('fields','table','text'):return ('hwp-cfb','hwpx-structure')*2 if fmt=='hwp' else ('hwpx-structure',)*2
    if category=='session':return ('hwp-cfb','hwpx-structure') if fmt=='hwp' else ('hwpx-structure',)
    if category=='render':return ('svg','svg','svg','pdf','pdf','png')
    if category=='roundtrip':return ('hwp-cfb','hwp-cfb','hwpx-structure','hwpx-structure')
    raise ValueError('Unknown required artifact inventory')

def verify_cell_edit(value,old,new,table,row,col):
    require(value.get('oldText')==old and value.get('newText')==new and value.get('overflow')==[] and value.get('keepStyle') is False and all(type(value.get(k)) is int and value[k]==v for k,v in (('table',table),('row',row),('col',col))),'Actual targeted cell envelope differs');changed_pages(value)

def verify_insert(value,ins):
    require(type(value.get('insertedChars')) is int and value['insertedChars']==len(ins['text']) and value.get('text')==ins['text'] and all(type(value.get(k)) is int and value[k]==ins[k] for k in ('section','paragraph','offset')) and value.get('dryRun') is False,'Actual Unicode insertion address/count differs');changed_pages(value)

def verify_generation(generation,binding,helper_map,architecture,expected_generator,inputs,expected_source_contract=None):
    keys={'formatVersion','sourceCommit','sourceRun','runAttempt','architecture','sourceContractSha256','generatorSha256','stageSha256','oracleSha256','definitionSha256','lockSha256','preparedGeneratorSha256','generatorNative','generatorExitCode','stdoutSha256','stdoutBytes','inputs','independentOriginalVerified'}
    require(type(generation) is dict and set(generation)==keys and type(generation['formatVersion']) is int and generation['formatVersion']==1 and all(generation[k]==v for k,v in binding.items()) and generation['architecture']==architecture and generation['independentOriginalVerified'] is True and type(generation['generatorExitCode']) is int and generation['generatorExitCode']==0,'Explicit native generator/source binding differs')
    for key,helper in (('generatorSha256','generate_structured.rs'),('preparedGeneratorSha256','generate_structured.rs'),('stageSha256','stage_structured.py'),('oracleSha256','structured_oracle.py'),('definitionSha256','expected.json'),('lockSha256','config/upstream.lock.json')):require(generation[key]==helper_map[helper],'Actual generator/prepared helper/definition bytes differ')
    require(generation['inputs']=={k:v for k,v in inputs.items() if k!='generation.json'},'Native generated input bytes differ')
    require(generation['sourceContractSha256']==sha(expected_source_contract),'Generator prepared source graph differs from the package')
    sha(generation['stdoutSha256']);integer(generation['stdoutBytes'],1,65536);sha(expected_generator)
    verify_native(generation['generatorNative'],binding,expected_generator,architecture)
    require(generation['generatorNative'].get('helperSha256')==helper_map['e2e/native_architecture.py'],'Generator native observer helper differs')

def validate_arguments(args,schema,*,root=True):
    require(type(schema) is dict,'Actual public input schema missing')
    kind=schema.get('type');types={'object':dict,'array':list,'string':str,'boolean':bool,'integer':int,'number':(int,float)}
    if kind in types:require(type(args) in (types[kind] if isinstance(types[kind],tuple) else (types[kind],)),'Public argument type differs')
    if 'enum' in schema:require(args in schema['enum'],'Public argument enum differs')
    if type(args) is dict:
        props=schema.get('properties',{});require(set(schema.get('required',[]))<=set(args),'Required public argument absent')
        if root:require(set(args)<=set(props),'Undeclared public tool argument supplied')
        for key,value in args.items():
            if key in props:validate_arguments(value,props[key],root=False)
            elif type(schema.get('additionalProperties')) is dict:validate_arguments(value,schema['additionalProperties'],root=False)
            elif schema.get('additionalProperties') is False:raise ValueError('Additional public property disallowed')
    if type(args) is list:
        for value in args:validate_arguments(value,schema.get('items',{}),root=False)
    if type(args) in (int,float):
        if 'minimum' in schema:require(args>=schema['minimum'],'Public argument below minimum')
        if 'maximum' in schema:require(args<=schema['maximum'],'Public argument above maximum')
    if type(args) is str:
        if 'minLength' in schema:require(len(args)>=schema['minLength'],'Public argument below minimum length')

def validate_tool_arguments(name,operation,args,schema):
    selected={'empty-query':('hwp_doc_search','query'),'empty-insert':('hwp_insert_text','text')}
    if name in selected:
        expected,property_name=selected[name]
        require(operation==expected and type(args) is dict and args.get(property_name)=='' and type(args.get(property_name)) is str,
                'Declared negative operation/value differs')
        schema=copy.deepcopy(schema)
        property_schema=schema.get('properties',{}).get(property_name)
        require(type(property_schema) is dict and property_schema.get('type')=='string','Declared negative public string schema missing')
        property_schema.pop('minLength',None)
    validate_arguments(args,schema)

def negative_result(response):
    result=response.get('result');require(type(result) is dict and result.get('isError') is True and type(result.get('content')) is list and len(result['content'])==1 and result['content'][0].get('type')=='text' and type(result['content'][0].get('text')) is str and result['content'][0]['text'],'Actual negative public tool error missing');return result

def verify_native(value,binding,cli_hash,architecture,*,alive=False):
    require(type(value) is dict and value.get('native') is True and value.get('architecture')==architecture and value.get('sha256')==cli_hash,'Actual native executable/process differs')
    machine={'x64':0x8664,'arm64':0xaa64}[architecture]
    require(type(value.get('processId')) is int and value['processId']>0 and all(type(value.get(k)) is int and value[k]==v for k,v in (('peMachine',machine),('processMachine',0),('nativeMachine',machine))),'Native PID/machine differs')
    require(all(value.get(k)==v for k,v in binding.items()),'Native source/run/attempt differs')
    require(type(value.get('createdFileTime')) is int and value['createdFileTime']>0 and PureWindowsPath(value.get('imagePath','')).is_absolute(),'Native birth/path proof missing')
    require(value.get('packageFullName') is None,'Portable observer used a packaged process')
    if 'helperSha256' in value:require(value['helperSha256']==helpers()['e2e/native_architecture.py'],'Actual native observer helper differs')
    if alive:require(value.get('runningAtInspection') is True,'Server was not alive at actual inspection')
def revalidate_semantics(proof,root,expected):
    """Re-read preserved bytes; completion flags never replace real typed/output checks."""
    from mcp_worker import strict_json,tool_records
    baseline={'hwp':oracle.inspect_hwpx(evidence_file(root,proof['preflightArtifact']['path']),expected),'hwpx':oracle.inspect_hwpx(evidence_file(root,'inputs/structured.hwpx'),expected)}
    for value in baseline.values():oracle.verify_original(value,expected)
    setup={c['name']:strict_json(evidence_file(root,c['responseFile']).read_bytes()) for c in proof['setup']}
    initialize=setup['initialize'].get('result',{});lock=strict_json((ROOT/'config/upstream.lock.json').read_bytes());require(initialize.get('protocolVersion')=='2025-06-18' and initialize.get('serverInfo',{}).get('name')=='rhwp' and initialize['serverInfo'].get('version')==lock['rhwp']['version'],'Re-read actual initialize differs')
    definitions=setup['tools-list'].get('result',{}).get('tools');require(type(definitions) is list,'Re-read actual tools-list missing');schemas={t['name']:t['inputSchema'] for t in definitions};require(len(schemas)==len(definitions) and REQUIRED_TOOLS<=set(schemas),'Re-read actual public schema inventory differs')
    doc_ids=set()
    for case in proof['cases']:
        fmt,category=case['id'].split('-',1);records={};handles={}
        for call in case['calls']:
            request=strict_json(evidence_file(root,call['requestFile']).read_bytes());args=request['arguments'];operation=call['operation'];raw=evidence_file(root,call['responseFile']).read_bytes()
            if call['channel']=='mcp':
                response=strict_json(raw)
                if operation=='ping':require(response.get('result')=={},'Re-read negative recovery ping differs');continue
                validate_tool_arguments(call['name'],operation,args,schemas[operation])
                if call['name'] in ('empty-query','invalid-cell','empty-insert'):
                    negative_result(response)
                    require((call['name']=='empty-query' and args.get('query')=='') or (call['name']=='invalid-cell' and type(args.get('row')) is int and args['row']==2) or (call['name']=='empty-insert' and args.get('text')==''),'Required selected negative boundary differs');continue
                values=tool_records(response);require(len(values)==1,'Re-read single positive envelope required');value=values[0]
                if operation=='hwp_open':
                    doc=value.get('docId');require(type(doc) is str and doc and doc not in doc_ids and value.get('source')==args['path'] and type(value.get('pageCount')) is int and value['pageCount']==1,'Re-read actual open handle/source differs');doc_ids.add(doc);handles[call['name']]=doc
                elif operation=='hwp_close':require(value.get('docId')==args.get('docId') and value.get('closed') is True,'Re-read actual close differs')
                if 'docId' in args:
                    handle=handles.get('other-open') if call['name'].startswith('other-') else handles.get('reopen') if call['name'].startswith('reopen-') else handles.get('open')
                    require(args['docId']==handle,'Actual document operation used another/unopened handle')
                source=args.get('path',args.get('docId'))
            else:
                require(type(args) is list and args and all(type(a) is str for a in args),'Re-read direct CLI argv differs')
                if call['name']=='cli-png':require(args[0]=='export-png' and '-o' in args and args[-4:]==['-p','0','--dpi','96'],'Actual PNG public folder/page/DPI argv differs');continue
                value=strict_json(raw);require(type(value) is dict,'Re-read typed CLI envelope missing');source=args[2] if args[0]=='edit' else args[1]
            records[call['name']]=(args,value)
            if operation in ('hwp_info','hwp_doc_info','info'):verify_info(value,'hwpx' if category=='roundtrip' else fmt,source)
            elif operation in ('hwp_export_tables','hwp_doc_tables','export-tables'):
                wanted=copy.deepcopy(expected)
                if category=='session' and call['name'] in ('tables','reopen-tables'):wanted['cells']['0,1']='SESSION-CELL'
                verify_tables(value,source,wanted)
            elif operation in ('hwp_fields','hwp_doc_fields','fields'):
                wanted=copy.deepcopy(expected)
                if category=='fields' and call['name'] in ('output-fields','cli-output-fields'):
                    for f,v in zip(wanted['fields'],('고객-한글-Ω','FIRST','SECOND')):f['value']=v
                if category=='session' and call['name'] in ('fields','reopen-fields'):wanted['fields'][0]['value']='SESSION-FIELD'
                verify_fields(value,source,wanted)
            elif operation in ('hwp_search','hwp_doc_search','search'):
                offsets=expected['search']['offsets'];zero=call['name']=='zero-match'
                if call['name']=='first-window':offsets=offsets[:1];require(type(value.get('nextOffset')) is int and value['nextOffset']==1,'Re-read first pagination offset differs')
                elif call['name']=='last-window':offsets=offsets[1:];require(args.get('offset')==1 and type(args.get('offset')) is int,'Re-read actual second window request differs')
                elif zero:offsets=[]
                verify_search(value,source,expected,offsets,last=call['name'] in ('search','cli-search','last-window'),zero=zero,
                              paragraph_context=call['name'] in ('search','cli-search'))
            elif operation in ('hwp_fill_fields','hwp_doc_fill_fields','edit fill-fields'):
                verify_fill(value,source,count=1 if category=='session' else 3,dry=call['name']=='dry-run')
                if category=='session':require(value.get('docId')==source,'Re-read session field handle differs')
            elif operation in ('hwp_set_cell','hwp_doc_set_cell','edit set-cell'):
                if category=='session':require(value.get('docId')==source and value.get('oldText')==expected['cells']['0,1'] and value.get('newText')=='SESSION-CELL' and value.get('keepStyle') is True and value.get('overflow')==[],'Re-read session styled cell differs');changed_pages(value)
                else:verify_cell_edit(value,expected['cells']['1,0'],'CELL-EDIT-한글',0,1,0)
            elif operation in ('hwp_insert_text','edit insert-text'):verify_insert(value,expected['insert'])
            elif operation in ('hwp_ir_diff','ir-diff'):verify_ir(value)
            if 'verify' in value and (call['channel']=='cli' or operation in ('hwp_convert_hwp5','hwp_convert_hwpx','hwp_doc_save')):verify_ir(value['verify'])
        artifacts=case['artifacts'];xml=[]
        for a in artifacts:
            path=evidence_file(root,a['path'])
            if a['kind']=='hwpx-structure':xml.append(oracle.inspect_hwpx(path,expected))
            elif a['kind']=='hwp-cfb':require(path.read_bytes().startswith(bytes.fromhex('d0cf11e0a1b11ae1')),'Re-read native HWP CFB signature differs')
            elif a['kind']=='svg':oracle.inspect_svg(path,expected)
            elif a['kind']=='png':oracle.inspect_png(path,expected)
            elif a['kind']=='pdf':oracle.inspect_pdf(path,expected)
        allowed={}
        if category=='fields':allowed={'fields':{0:'고객-한글-Ω',1:'FIRST',2:'SECOND'}}
        elif category=='table':allowed={'cells':{'1,0':'CELL-EDIT-한글'}}
        elif category=='text' or category=='roundtrip':allowed={'insert':expected['insert']}
        elif category=='session':allowed={'cells':{'0,1':'SESSION-CELL'},'fields':{0:'SESSION-FIELD'},'keep_style':True}
        for value in xml:oracle.compare_structure(baseline[fmt],value,**allowed)
        if category=='render':
            require(records['export-pdf'][1].get('backend')==records['cli-pdf'][1].get('backend')=='svg','Re-read PDF used blocked direct backend')
        if category=='roundtrip':
            for name in ('to-hwp','to-hwpx','cli-to-hwp','cli-to-hwpx'):
                value=records[name][1];verify_ir(value.get('verify'));require(type(value.get('bytes')) is int and value['bytes']>0,'Re-read conversion actual bytes differ')

def verify_receipt(proof,binding,expected_helpers,*,expected_cli=None,expected_inputs=None,evidence_root=None,expected_transport=None):
    keys={'formatVersion','context','scope','passed','skippedCases','architecture','sourceCommit','sourceRun','runAttempt','cliSha256','helperSha256','inputSha256','generationSha256','generatorSha256','transportArtifact','preflight','preflightArtifact','server','worker','setup','cases','framesSent','framesReceived','serverExited','parentInstalled33Unchanged','qaInventoryUnchanged','fullFeatureCoverage'}
    require(type(proof) is dict and set(proof)==keys,'Complete separate structured receipt fields required')
    require(proof['formatVersion']==1 and type(proof['formatVersion']) is int and proof['context']=='portable' and proof['scope']==SCOPE and proof['passed'] is True and type(proof['skippedCases']) is int and proof['skippedCases']==0 and proof['fullFeatureCoverage'] is False and proof['parentInstalled33Unchanged'] is True and proof['qaInventoryUnchanged'] is True,'Portable valid coverage completion/scope differs')
    require(type(binding) is dict and set(binding)=={'sourceCommit','sourceRun','runAttempt'} and type(binding['sourceCommit']) is str and re.fullmatch('[0-9a-f]{40}',binding['sourceCommit']) and all(type(binding[k]) is str and re.fullmatch('[1-9][0-9]{0,19}',binding[k]) for k in ('sourceRun','runAttempt')),'Required external source/run/attempt missing')
    require(type(expected_helpers) is dict and set(expected_helpers)==set(COMMON_HELPERS+DRAFT_HELPERS),'Exact external helper map missing')
    for value in expected_helpers.values():sha(value)
    require(all(proof[k]==v for k,v in binding.items()) and proof['helperSha256']==expected_helpers,'Source/helper bindings differ')
    cli_hash=sha(proof['cliSha256']);require(cli_hash==expected_cli and proof['inputSha256']==expected_inputs and evidence_root is not None,'Externally re-read CLI/input/evidence bindings required');arch=proof['architecture'];require(arch in ('x64','arm64'),'Native architecture missing')
    require(type(proof['inputSha256']) is dict and set(proof['inputSha256'])=={'structured.hwp','structured.hwpx','checkerboard.png','generation.json'},'Exact original input bindings missing')
    for value in proof['inputSha256'].values():sha(value)
    require(proof['generationSha256']==proof['inputSha256']['generation.json'],'Native input generator receipt differs')
    from mcp_worker import strict_json
    require(type(expected_transport) is dict and proof['generatorSha256']==expected_transport.get('generatorSha256') and
            proof['inputSha256']==expected_transport.get('inputSha256'),'External generator/input transport binding is required')
    transport=proof['transportArtifact'];require(type(transport) is dict and set(transport)=={'path','sha256','bytes'},'Retained external transport binding missing')
    transport_path=evidence_file(evidence_root,transport['path'])
    require(digest(transport_path)==sha(transport['sha256']) and transport_path.stat().st_size==integer(transport['bytes'],1,65536) and
            strict_json(transport_path.read_bytes())==expected_transport,'Retained external transport binding differs')
    generation=strict_json(evidence_file(evidence_root,'inputs/generation.json').read_bytes());verify_generation(generation,binding,expected_helpers,arch,proof['generatorSha256'],proof['inputSha256'],expected_transport.get('sourceContractSha256'))
    for name,value in proof['inputSha256'].items():require(digest(evidence_file(evidence_root,'inputs/'+name))==value,'Preserved immutable input SHA differs')
    artifact=proof['preflightArtifact'];require(type(artifact) is dict and set(artifact)=={'path','sha256','bytes'} and digest(evidence_file(evidence_root,artifact['path']))==sha(artifact['sha256']) and evidence_file(evidence_root,artifact['path']).stat().st_size==integer(artifact['bytes'],1,oracle.CAP),'Preserved independent CFB-to-XML preflight differs')
    verify_native(proof['server'],binding,cli_hash,arch,alive=True)
    require(proof['worker'] is None,'Companion does not independently qualify COM worker isolation; original mandatory33 does')
    require(proof['serverExited'] is True,'Owned companion server termination unobserved')
    cases=proof['cases'];require(type(cases) is list and len(cases)==16 and tuple(c.get('id') for c in cases)==CASE_IDS,'Exact sixteen positive valid categories required')
    setup=proof['setup'];require(type(setup) is list and [c.get('name') for c in setup]==['initialize','tools-list'],'Actual setup bindings missing')
    next_id=1;hashes=[]
    def check_call(call,name,category=None):
        nonlocal next_id
        require(type(call) is dict and call.get('name')==name and call.get('passed') is True and call.get('channel')==expected_channel(name),'Required actual subcall missing/failed/reordered')
        sha(call.get('responseSha256'));integer(call.get('responseBytes'),0 if call['channel']=='cli' else 1,2*1024*1024)
        require(set(call)==({'name','channel','requestId','responseSha256','responseBytes','passed','operation','requestSha256','requestBytes','requestFile','responseFile'}|({'serverProcessId'} if call['channel']=='mcp' else {'native','exitCode','stderrSha256','stderrBytes','stderrFile'})),'Exact actual subcall binding fields differ')
        for prefix in ('request','response')+(() if call['channel']=='mcp' else ('stderr',)):
            blob=evidence_file(evidence_root,call.get(prefix+'File'));require(blob.stat().st_size==integer(call.get(prefix+'Bytes'),0,2*1024*1024) and digest(blob)==sha(call.get(prefix+'Sha256')),'Preserved original call byte binding differs')
        from mcp_worker import strict_json
        request=strict_json(evidence_file(evidence_root,call['requestFile']).read_bytes())
        require(request.get('operation')==call['operation'] and type(request.get('arguments')) in (list,dict),'Actual public operation/argument proof differs')
        require(call['operation']==expected_operation(name,category),'Required public tool/CLI operation differs')
        if call['channel']=='mcp':
            require(type(call.get('requestId')) is int and call['requestId']==next_id and call.get('serverProcessId')==proof['server']['processId'],'Actual MCP request/server ID differs');next_id+=1;hashes.append(call['responseSha256'])
            response=strict_json(evidence_file(evidence_root,call['responseFile']).read_bytes());require(response.get('id')==call['requestId'] and type(response.get('id')) is int and response.get('jsonrpc')=='2.0','Preserved actual response ID differs')
        else:
            require(call.get('requestId') is None and type(call.get('exitCode')) is int and call['exitCode']==0,'Actual CLI call/exit differs');verify_native(call.get('native'),binding,cli_hash,arch)
    preflight=proof['preflight'];require(type(preflight) is list and len(preflight)==1,'Observed HWP preflight CLI proof required');check_call(preflight[0],'preflight-hwp')
    for call,name in zip(setup,('initialize','tools-list')):check_call(call,name)
    for case in cases:
        fmt,category=verify_case_inventory(case,proof['inputSha256']);wanted=call_inventory(fmt,category)
        for call,name in zip(case['calls'],wanted):check_call(call,name,category)
        integer(case['elapsedMs']);require(type(case['artifacts']) is list and tuple(a.get('kind') for a in case['artifacts'])==artifact_inventory(fmt,category),'Exact independent artifact proofs missing')
        if category in ('fields','table','text','session','render','roundtrip'):require(case['artifacts'],'Actual independent outputs were not inspected')
        for artifact in case['artifacts']:
            require(type(artifact) is dict and set(artifact)=={'kind','path','sha256','bytes','independentPassed','details'} and artifact.get('independentPassed') is True and type(artifact.get('bytes')) is int and artifact['bytes']>0 and sha(artifact.get('sha256')),'Independent artifact binding missing')
            path=evidence_file(evidence_root,artifact['path']);require(path.stat().st_size==artifact['bytes'] and digest(path)==artifact['sha256'],'Preserved independent artifact bytes differ')
    require(type(proof['framesReceived']) is int and proof['framesReceived']==next_id-1 and type(proof['framesSent']) is int and proof['framesSent']==next_id,'Actual fixed call manifest/frame counts differ')
    require(len(hashes)==len(set(hashes)),'Duplicate MCP response hashes')
    from mcp_worker import strict_json
    revalidate_semantics(proof,evidence_root,strict_json((HERE/'expected.json').read_bytes()))
    return proof

class Suite:
    def __init__(self,exe,architecture,binding,work,expected,server,watch,proof):
        from mcp_worker import sha as file_sha
        self.exe,self.arch,self.binding,self.work,self.expected,self.client,self.watch,self.proof=exe,architecture,binding,work,expected,server,watch,proof
        self.case=None;self.root_hash=file_sha(exe);self.proof_root=Path(proof.pop('_evidenceRoot'));self.counter=0;self.schemas={t['name']:t['inputSchema'] for t in proof.pop('_toolDefinitions')}
    def preserve(self,name,raw):
        folder=self.proof_root/'calls'/self.case.get('id','preflight');folder.mkdir(parents=True,exist_ok=True)
        path=folder/(str(self.counter)+'-'+name);self.counter+=1
        require(not path.exists(),'Original call evidence already exists');path.write_bytes(raw);return str(path.relative_to(self.proof_root))
    def record(self,row,operation,arguments,raw,stderr=None):
        request=canonical({'operation':operation,'arguments':arguments})
        row.update(operation=operation,requestSha256=hashlib.sha256(request).hexdigest(),requestBytes=len(request),requestFile=self.preserve(row['name']+'-request.json',request),responseFile=self.preserve(row['name']+('-response.json' if row['channel']=='mcp' else '-stdout.log'),raw))
        if stderr is not None:row.update(stderrSha256=hashlib.sha256(stderr).hexdigest(),stderrBytes=len(stderr),stderrFile=self.preserve(row['name']+'-stderr.log',stderr))
        self.case['calls'].append(row)
    def cli(self,name,args,cwd,*,json_output=True):
        from native_architecture import verify_process
        from mcp_worker import strict_json
        p=subprocess.Popen([str(self.exe),*args],cwd=cwd,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        try:
            native=verify_process(p.pid,self.exe,self.arch,handle=int(p._handle));native['createdFileTime']=self.watch.created(int(p._handle))
            raw,stderr=p.communicate(input=b'',timeout=60)
            require(len(raw)<=2*1024*1024 and len(stderr)<=2*1024*1024,'Unbounded direct CLI response')
            row={'name':name,'channel':'cli','requestId':None,'responseSha256':hashlib.sha256(raw).hexdigest(),'responseBytes':len(raw),'exitCode':p.returncode,'native':native,'passed':p.returncode==0}
            operation=' '.join(args[:2]) if args[0]=='edit' else args[0]
            self.record(row,operation,args,raw,stderr)
            require(p.returncode==0,'Direct public CLI command failed')
            return strict_json(raw) if json_output else None
        finally:
            if p.poll() is None:p.kill();p.wait(timeout=10)
    def tool(self,name,tool,args,*,error=False):
        from mcp_worker import tool_records,result_receipt
        validate_tool_arguments(name,tool,args,self.schemas[tool]);response=self.client.request('tools/call',{'name':tool,'arguments':args})
        row=result_receipt(name,response,{});row.pop('checks');row.update(channel='mcp',serverProcessId=self.client.process.pid,passed=True)
        self.record(row,tool,args,canonical(response))
        if error:
            return negative_result(response)
        rows=tool_records(response);require(len(rows)==1,'Single public structured envelope required')
        # Stateless handlers return only after their one-shot worker has exited.
        # COM isolation is qualified by the separate unchanged mandatory33 suite;
        # this companion binds actual server/CLI processes and document results.
        return rows[0]
    def ping(self,name):
        from mcp_worker import result_receipt
        response=self.client.request('ping');row=result_receipt(name,response,{});row.pop('checks');row.update(channel='mcp',serverProcessId=self.client.process.pid,passed=True);self.record(row,'ping',{},canonical(response));require(response.get('result')=={} and self.client.process.poll() is None,'Same-server negative follow-up ping failed')
    def open(self,name,path):
        value=self.tool(name,'hwp_open',{'path':str(path)});doc=value.get('docId');require(type(doc) is str and doc and value.get('source')==str(path) and type(value.get('pageCount')) is int and value['pageCount']==1,'Actual opened document handle/source differs');return doc
    def close(self,name,doc):
        value=self.tool(name,'hwp_close',{'docId':doc});require(value.get('docId')==doc and value.get('closed') is True,'Actual document close failed')
    def artifact(self,path,kind,details):
        directory=self.proof_root/'artifacts'/self.case.get('id','preflight');directory.mkdir(parents=True,exist_ok=True);saved=directory/(str(len(self.case['artifacts']))+path.suffix);require(not saved.exists(),'Original artifact exists');shutil.copyfile(path,saved)
        self.case['artifacts'].append({'path':str(saved.relative_to(self.proof_root)),'kind':kind,'sha256':digest(path),'bytes':path.stat().st_size,'independentPassed':True,'details':details})
    def validate_pdf(self,value,source,path):
        # Retain the actual owned output before any manifest or PDFium assertion.
        # A failed capture is evidence only; success still requires every oracle.
        from windows_components import regular,_ancestors
        with oracle.pdf_phase('pdf-retain'):
            path=Path(path);regular(path)
            require(path.resolve().is_relative_to(Path(self.work).resolve()) and
                    path.suffix=='.pdf' and self.case['id'] in ('hwp-render','hwpx-render'),
                    'PDF output is outside the current owned render case')
            before=path.stat();require(0<before.st_size<=oracle.CAP,'PDF output is unbounded')
            with path.open('rb') as stream:raw=stream.read(oracle.CAP+1)
            after=path.stat();regular(path)
            require(len(raw)==before.st_size and
                    (before.st_size,before.st_mtime_ns,before.st_dev,before.st_ino)==
                    (after.st_size,after.st_mtime_ns,after.st_dev,after.st_ino),
                    'PDF output changed during evidence capture')
            directory=self.proof_root/'artifacts'/self.case['id'];_ancestors(directory)
            directory.mkdir(parents=True,exist_ok=True);_ancestors(directory)
            saved=directory/(str(len(self.case['artifacts']))+'.pdf')
            with saved.open('xb') as stream:stream.write(raw)
            regular(saved);captured_sha=hashlib.sha256(raw).hexdigest()
            require(saved.stat().st_size==len(raw) and digest(saved)==captured_sha,
                    'Retained PDF bytes differ from the actual output')
            artifact={'path':str(saved.relative_to(self.proof_root)),'kind':'pdf',
                      'sha256':captured_sha,'bytes':len(raw),'independentPassed':False,'details':{}}
            self.case['artifacts'].append(artifact)
        with oracle.pdf_phase('pdf-manifest'):
            version(value);source_match(value,source)
            require(value.get('format')=='pdf' and all(type(value.get(k)) is int for k in ('bytes','pageCount','renderedCount')) and value.get('backend')=='svg' and value.get('output')==str(path) and value.get('bytes')==len(raw) and value.get('pageCount')==value.get('renderedCount')==1,'Guarded SVG PDF actual manifest differs')
        details=oracle.inspect_pdf(saved,self.expected)
        with oracle.pdf_phase('pdf-retain'):
            regular(saved);require(saved.stat().st_size==len(raw) and digest(saved)==captured_sha,
                                   'Retained PDF bytes changed during validation')
        artifact.update(independentPassed=True,details=details)
    def structure(self,label,path):
        if path.suffix=='.hwp':
            require(path.read_bytes().startswith(bytes.fromhex('d0cf11e0a1b11ae1')),'Actual HWP CFB signature missing')
            xml=path.with_name(path.stem+'-'+label+'.hwpx');require(not xml.exists(),'Oracle output must be fresh')
            value=self.cli(label,['export-hwpx',str(path),str(xml),'--verify','--json'],path.parent);output_record(value,path,xml,'hwpx',verified=True,conversion=True)
        else:xml=path
        value=oracle.inspect_hwpx(xml,self.expected);self.artifact(path,'hwp-cfb' if path.suffix=='.hwp' else 'hwpx-structure',{'structureSha256':hashlib.sha256(canonical(value)).hexdigest(),'structure':value,'xmlSha256':digest(xml),'tableCells':4,'fields':3,'pictures':1})
        if xml!=path:self.artifact(xml,'hwpx-structure',{'structureSha256':hashlib.sha256(canonical(value)).hexdigest(),'structure':value})
        return value
    def execute_case(self,fmt,category,fixtures,baseline):
        require({n:digest(fixtures/n) for n in self.proof['inputSha256']}==self.proof['inputSha256'],'Original fixture changed before category');started=time.monotonic();folder=self.work/(fmt+'-'+category);folder.mkdir();source=folder/('input.'+fmt);shutil.copyfile(fixtures/('structured.'+fmt),source);before=digest(source)
        self.case={'id':fmt+'-'+category,'status':'running','checks':{},'calls':[],'sourceBeforeSha256':before,'sourceAfterSha256':before,'artifacts':[],'elapsedMs':0}
        self.proof['cases'].append(self.case);expected=copy.deepcopy(self.expected);table=0
        if category=='read':
            verify_info(self.tool('stateless-info','hwp_info',{'path':str(source)}),fmt,source)
            verify_tables(self.tool('stateless-tables','hwp_export_tables',{'path':str(source)}),source,expected);verify_fields(self.tool('stateless-fields','hwp_fields',{'path':str(source)}),source,expected)
            doc=self.open('open',source);verify_info(self.tool('info','hwp_doc_info',{'docId':doc}),fmt,doc)
            table=verify_tables(self.tool('tables','hwp_doc_tables',{'docId':doc}),doc,expected);verify_fields(self.tool('fields','hwp_doc_fields',{'docId':doc}),doc,expected)
            tree=self.tool('tree','hwp_doc_tree',{'docId':doc});nodes=tree.get('nodes',{});require(tree.get('docId')==doc and tree.get('pageCount')==1 and nodes.get('pages')==['p0'] and len(nodes.get('tables',[]))==1 and nodes['tables'][0].get('nodeId')=='t0' and len(nodes.get('cells',[]))==4 and all('sec[0]/para[' in n.get('nodePath','') and '/cell[' in n['nodePath'] for n in nodes['cells']),'Public tree/actual cells are not bound')
            verify_info(self.cli('cli-info',['info',str(source),'--json'],folder),fmt,source);verify_tables(self.cli('cli-tables',['export-tables',str(source),'--json'],folder),source,expected);verify_fields(self.cli('cli-fields',['fields',str(source),'--json'],folder),source,expected);self.close('close',doc)
        elif category=='search':
            doc=self.open('open',source);offsets=expected['search']['offsets']
            value=self.tool('search','hwp_search',{'path':str(source),'query':expected['query'],'context':1});verify_search(value,source,expected,offsets,last=True,paragraph_context=True)
            require(all(type(row.get('contextBefore')) is list and type(row.get('contextAfter')) is list for row in value['matches']),'Actual search context paragraph arrays missing')
            verify_search(self.cli('cli-search',['search',str(source),'--json','--context','1','--',expected['query']],folder),source,expected,offsets,last=True,paragraph_context=True)
            first=self.tool('first-window','hwp_doc_search',{'docId':doc,'query':expected['query'],'maxMatches':1});verify_search(first,doc,expected,[offsets[0]]);require(type(first.get('nextOffset')) is int and first['nextOffset']==1,'Actual first search nextOffset differs')
            last=self.tool('last-window','hwp_doc_search',{'docId':doc,'query':expected['query'],'maxMatches':1,'offset':first['nextOffset']});verify_search(last,doc,expected,[offsets[1]],last=True)
            verify_search(self.tool('zero-match','hwp_doc_search',{'docId':doc,'query':'OWNED-NO-MATCH'}),doc,expected,[],zero=True)
            self.tool('empty-query','hwp_doc_search',{'docId':doc,'query':''},error=True);self.ping('negative-ping');self.close('close',doc)
        elif category in ('fields','table','text'):
            mcpout=folder/('mcp.'+fmt);cliout=folder/('cli.'+fmt)
            if category=='fields':
                data={'CUSTOMER':'고객-한글-Ω','ITEM[0]':'FIRST','ITEM[1]':'SECOND'}
                verify_fill(self.tool('dry-run','hwp_fill_fields',{'path':str(source),'data':data,'output':str(mcpout),'dryRun':True}),source,count=3,dry=True);require(not mcpout.exists() and digest(source)==before,'Dry-run modified disk')
                value=self.tool('fill','hwp_fill_fields',{'path':str(source),'data':data,'output':str(mcpout)});verify_fill(value,source,count=3);changed_pages(value);output_record(value,source,mcpout,fmt)
                value=self.cli('cli-fill',['edit','fill-fields',str(source),'--data',json.dumps(data,ensure_ascii=False),'-o',str(cliout),'--verify','--json'],folder);verify_fill(value,source,count=3);changed_pages(value);output_record(value,source,cliout,fmt,verified=True)
                changed=copy.deepcopy(expected)
                for field,new in zip(changed['fields'],data.values()):field['value']=new
                verify_fields(self.tool('output-fields','hwp_fields',{'path':str(mcpout)}),mcpout,changed);verify_fields(self.cli('cli-output-fields',['fields',str(cliout),'--json'],folder),cliout,changed)
                allowed={'fields':{0:data['CUSTOMER'],1:data['ITEM[0]'],2:data['ITEM[1]']}}
            elif category=='table':
                table=verify_tables(self.tool('inventory','hwp_export_tables',{'path':str(source)}),source,expected)
                value=self.tool('set-cell','hwp_set_cell',{'path':str(source),'table':table,'row':1,'col':0,'text':'CELL-EDIT-한글','output':str(mcpout)});verify_cell_edit(value,expected['cells']['1,0'],'CELL-EDIT-한글',table,1,0);output_record(value,source,mcpout,fmt)
                value=self.cli('cli-set-cell',['edit','set-cell',str(source),'--table',str(table),'--row','1','--col','0','--text','CELL-EDIT-한글','-o',str(cliout),'--verify','--json'],folder);verify_cell_edit(value,expected['cells']['1,0'],'CELL-EDIT-한글',table,1,0);output_record(value,source,cliout,fmt,verified=True)
                bad=folder/('invalid.'+fmt);self.tool('invalid-cell','hwp_set_cell',{'path':str(source),'table':table,'row':2,'col':0,'text':'UNEXPECTED','output':str(bad)},error=True);require(not bad.exists(),'Invalid cell wrote an output');self.ping('negative-ping');allowed={'cells':{'1,0':'CELL-EDIT-한글'}}
            else:
                ins=expected['insert'];args={'path':str(source),'section':ins['section'],'paragraph':ins['paragraph'],'offset':ins['offset'],'text':ins['text'],'output':str(mcpout)}
                value=self.tool('insert','hwp_insert_text',args);verify_insert(value,ins);output_record(value,source,mcpout,fmt)
                value=self.cli('cli-insert',['edit','insert-text',str(source),'--section','0','--para','0','--offset',str(ins['offset']),'--text',ins['text'],'-o',str(cliout),'--verify','--json'],folder);verify_insert(value,ins);output_record(value,source,cliout,fmt,verified=True)
                bad=folder/('empty.'+fmt);self.tool('empty-insert','hwp_insert_text',{**args,'text':'','output':str(bad)},error=True);require(not bad.exists(),'Empty insert wrote an output');self.ping('negative-ping');allowed={'insert':ins}
            oracle.compare_structure(baseline,self.structure('oracle-mcp',mcpout),**allowed);oracle.compare_structure(baseline,self.structure('oracle-cli',cliout),**allowed)
        elif category=='session':
            doc=self.open('open',source);table=verify_tables(self.tool('inventory','hwp_doc_tables',{'docId':doc}),doc,expected);other=self.open('other-open',source);require(doc!=other,'Other original handle was reused');output=folder/('session.'+fmt)
            value=self.tool('set-cell','hwp_doc_set_cell',{'docId':doc,'table':table,'row':0,'col':1,'text':'SESSION-CELL','keepStyle':True});require(value.get('docId')==doc and value.get('oldText')==expected['cells']['0,1'] and value.get('newText')=='SESSION-CELL' and value.get('overflow')==[] and value.get('keepStyle') is True,'Session cell edit/style envelope differs');changed_pages(value)
            value=self.tool('fill-field','hwp_doc_fill_fields',{'docId':doc,'data':{'CUSTOMER':'SESSION-FIELD'}});require(value.get('docId')==doc,'Session fill used another docId');verify_fill(value,doc,count=1);changed_pages(value)
            changed=copy.deepcopy(expected);changed['cells']['0,1']='SESSION-CELL';changed['fields'][0]['value']='SESSION-FIELD'
            verify_tables(self.tool('tables','hwp_doc_tables',{'docId':doc}),doc,changed);verify_fields(self.tool('fields','hwp_doc_fields',{'docId':doc}),doc,changed)
            verify_tables(self.tool('other-tables','hwp_doc_tables',{'docId':other}),other,expected);verify_fields(self.tool('other-fields','hwp_doc_fields',{'docId':other}),other,expected)
            require(not output.exists() and digest(source)==before,'Session edited the disk before save')
            value=self.tool('save','hwp_doc_save',{'docId':doc,'output':str(output),'verify':True});require(value.get('docId')==doc,'Session save docId differs');output_record(value,doc,output,fmt,verified=True)
            self.close('close',doc);self.close('other-close',other);again=self.open('reopen',output);verify_tables(self.tool('reopen-tables','hwp_doc_tables',{'docId':again}),again,changed);verify_fields(self.tool('reopen-fields','hwp_doc_fields',{'docId':again}),again,changed);self.close('reopen-close',again)
            oracle.compare_structure(baseline,self.structure('oracle-session',output),cells={'0,1':'SESSION-CELL'},fields={0:'SESSION-FIELD'},keep_style=True)
        elif category=='render':
            doc=self.open('open',source);svg=folder/'session.svg';value=self.tool('doc-svg','hwp_doc_render_page',{'docId':doc,'page':0,'output':str(svg)});require(value.get('docId')==doc and type(value.get('page')) is int and value['page']==0 and value.get('output')==str(svg) and value.get('bytes')==svg.stat().st_size,'Actual session SVG path/page/bytes differ');self.artifact(svg,'svg',oracle.inspect_svg(svg,expected));self.close('close',doc)
            for name,channel in (('export-svg','mcp'),('cli-svg','cli')):
                child=folder/name;child.mkdir();owned=child/(fmt+'-render-'+name+'.'+fmt);shutil.copyfile(source,owned)
                cwd=self.work if channel=='mcp' else child;output_dir=cwd/'output';expected_path=output_dir/(owned.stem+'.svg')
                prior={p.name:digest(p) for p in output_dir.iterdir()} if output_dir.exists() else {};require(not expected_path.exists(),'SVG must allocate a fresh uniquely named owned file')
                value=self.tool(name,'hwp_export_svg',{'path':str(owned)}) if channel=='mcp' else self.cli(name,['export-svg',str(owned),'--json'],child)
                path=svg_output(value,owned,cwd,expected_path)
                after={p.name:digest(p) for p in output_dir.iterdir()};require(set(after)==set(prior)|{path.name} and all(after[k]==v for k,v in prior.items()),'SVG renderer changed another owned output')
                self.artifact(path,'svg',oracle.inspect_svg(path,expected));require(digest(owned)==before,'SVG renderer edited owned input')
            for name,channel in (('export-pdf','mcp'),('cli-pdf','cli')):
                path=folder/(name+'.pdf');value=self.tool(name,'hwp_export_pdf',{'path':str(source),'output':str(path)}) if channel=='mcp' else self.cli(name,['export-pdf',str(source),'-o',str(path),'--json'],folder)
                self.validate_pdf(value,source,path)
            pngdir=folder/'png';self.cli('cli-png',['export-png',str(source),'-o',str(pngdir),'-p','0','--dpi','96'],folder,json_output=False);pngs=list(pngdir.glob('*.png'));require(len(pngs)==1,'Direct PNG handler must produce one real page file');self.artifact(pngs[0],'png',oracle.inspect_png(pngs[0],expected))
        elif category=='roundtrip':
            # Fresh edited HWpx seeds per branch; only this category chains conversions.
            base=folder/'seed-base.hwpx';seed=folder/'edited.hwpx';cseed=folder/'cli-edited.hwpx';ins=expected['insert']
            value=self.cli('seed-base',['export-hwpx',str(source),str(base),'--verify','--json'],folder);output_record(value,source,base,'hwpx',verified=True,conversion=True)
            args={'path':str(base),'section':ins['section'],'paragraph':ins['paragraph'],'offset':ins['offset'],'text':ins['text'],'output':str(seed)}
            value=self.tool('seed-mcp','hwp_insert_text',args);verify_insert(value,ins);output_record(value,base,seed,'hwpx')
            value=self.cli('seed-cli',['edit','insert-text',str(base),'--section','0','--para','0','--offset',str(ins['offset']),'--text',ins['text'],'-o',str(cseed),'--verify','--json'],folder);verify_insert(value,ins);output_record(value,base,cseed,'hwpx',verified=True)
            oracle.compare_structure(baseline,oracle.inspect_hwpx(seed,expected),insert=ins);oracle.compare_structure(baseline,oracle.inspect_hwpx(cseed,expected),insert=ins)
            seed_before,cseed_before=digest(seed),digest(cseed)
            hwp=folder/'round.hwp';hwpx=folder/'round.hwpx';chwp=folder/'cli-round.hwp';chwpx=folder/'cli-round.hwpx'
            for name,tool,src,out,kind in (('to-hwp','hwp_convert_hwp5',seed,hwp,'hwp'),('to-hwpx','hwp_convert_hwpx',hwp,hwpx,'hwpx')):
                old=digest(src);value=self.tool(name,tool,{'path':str(src),'output':str(out)});output_record(value,src,out,kind,verified=True,conversion=True);require(digest(src)==old,'MCP conversion mutated input')
                if kind=='hwp':require(out.read_bytes().startswith(bytes.fromhex('d0cf11e0a1b11ae1')),'Conversion did not produce CFB')
            verify_ir(self.tool('ir-diff','hwp_ir_diff',{'a':str(seed),'b':str(hwpx)}))
            for name,cmd,src,out,kind in (('cli-to-hwp','convert',cseed,chwp,'hwp'),('cli-to-hwpx','export-hwpx',chwp,chwpx,'hwpx')):
                old=digest(src);value=self.cli(name,[cmd,str(src),str(out),'--verify','--json'],folder);output_record(value,src,out,kind,verified=True,conversion=True);require(digest(src)==old,'CLI conversion mutated input')
            verify_ir(self.cli('cli-ir-diff',['ir-diff',str(cseed),str(chwpx),'--json'],folder))
            doc=self.open('open',hwpx);verify_info(self.tool('info','hwp_doc_info',{'docId':doc}),'hwpx',doc);verify_tables(self.tool('tables','hwp_doc_tables',{'docId':doc}),doc,expected);verify_fields(self.tool('fields','hwp_doc_fields',{'docId':doc}),doc,expected);self.close('close',doc)
            self.artifact(hwp,'hwp-cfb',{'signature':True});self.artifact(chwp,'hwp-cfb',{'signature':chwp.read_bytes().startswith(bytes.fromhex('d0cf11e0a1b11ae1'))});require(chwp.read_bytes().startswith(bytes.fromhex('d0cf11e0a1b11ae1')),'CLI roundtrip HWP missing CFB')
            oracle.compare_structure(baseline,self.structure('oracle-round-mcp',hwpx),insert=ins);oracle.compare_structure(baseline,self.structure('oracle-round-cli',chwpx),insert=ins)
            require(digest(seed)==seed_before and digest(cseed)==cseed_before,'Roundtrip changed its edited immutable seed')
        require(digest(source)==before,'Valid category mutated its original owned source')
        require({n:digest(fixtures/n) for n in self.proof['inputSha256']}==self.proof['inputSha256'],'Original fixture changed after category');self.case['sourceAfterSha256']=digest(source);self.case['checks']={k:True for k in CASE_CHECKS[category]};self.case['elapsedMs']=round((time.monotonic()-started)*1000);self.case['status']='passed'


def main():
    from mcp_worker import McpClient,WorkerWatch,private_runtime,result_receipt
    from native_architecture import verify_executable,verify_host,verify_process
    parser=argparse.ArgumentParser();parser.add_argument('--exe',type=Path,required=True);parser.add_argument('--architecture',choices=('x64','arm64'),required=True);parser.add_argument('--expected-sha256',required=True);parser.add_argument('--binding',type=Path,required=True);parser.add_argument('--package-provenance',type=Path,required=True);parser.add_argument('--fixtures',type=Path,required=True);parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    import windows_components as components
    from stage_structured import input_hashes,verify_transport
    binding=native_binding();components.fresh(args.out);args.out.mkdir(parents=True)
    (args.out/'structured-result.json').write_bytes(canonical({'formatVersion':1,'context':'portable','scope':SCOPE,**binding,
        'architecture':args.architecture,'passed':False,'skippedCases':16,'cases':[],'failureClass':'setup','fullFeatureCoverage':False})+b'\n')
    helper_map=helpers();sha(args.expected_sha256);components.regular(args.exe);require(digest(args.exe)==args.expected_sha256,'Source package CLI bytes differ');verify_executable(args.exe,args.architecture);verify_host(args.architecture)
    require(args.fixtures.is_dir() and not args.fixtures.is_symlink(),'Owned original fixture directory required');fixture=args.fixtures.resolve();required=('structured.hwp','structured.hwpx','checkerboard.png','generation.json');require(all((fixture/n).is_file() and not (fixture/n).is_symlink() for n in required),'Owned generated structured inputs are mandatory')
    from mcp_worker import strict_json
    components.regular(args.binding);components.regular(args.package_provenance)
    transport=strict_json(args.binding.read_bytes());package=strict_json(args.package_provenance.read_bytes())
    generator_hash=verify_transport(transport,package,binding,args.architecture,args.fixtures,helper_map)
    require(package['windowsComponents']['components']['cli']['sha256']==args.expected_sha256,'CLI expectation differs from source package provenance')
    definition=strict_json((HERE/'expected.json').read_bytes());generation=strict_json((fixture/'generation.json').read_bytes())
    hashes=input_hashes(args.fixtures);verify_generation(generation,binding,helper_map,args.architecture,generator_hash,hashes,transport['sourceContractSha256'])
    oracle.image_pattern((fixture/'checkerboard.png').read_bytes(),definition);baseline_xml=oracle.inspect_hwpx(fixture/'structured.hwpx',definition);oracle.verify_original(baseline_xml,definition)
    saved_inputs=args.out/'inputs';saved_inputs.mkdir()
    for name in required:shutil.copyfile(fixture/name,saved_inputs/name)
    shutil.copyfile(args.binding,args.out/'input-binding.json')
    proof={'formatVersion':1,'context':'portable','scope':SCOPE,'passed':False,'skippedCases':0,'architecture':args.architecture,**binding,'cliSha256':args.expected_sha256,'helperSha256':helper_map,'inputSha256':hashes,'generationSha256':hashes['generation.json'],'generatorSha256':generator_hash,'transportArtifact':{'path':'input-binding.json','sha256':digest(args.out/'input-binding.json'),'bytes':(args.out/'input-binding.json').stat().st_size},'preflight':[],'preflightArtifact':None,'_evidenceRoot':str(args.out.resolve()),'server':None,'worker':None,'setup':[],'cases':[],'framesSent':0,'framesReceived':0,'serverExited':False,'parentInstalled33Unchanged':True,'qaInventoryUnchanged':True,'fullFeatureCoverage':False}
    with tempfile.TemporaryDirectory(prefix='opengeul-structured-') as temp:
        work=Path(temp);exe=private_runtime(args.exe.resolve(),work/'runtime');client=None
        try:
            client=McpClient([str(exe),'mcp-serve'],cwd=work);native=verify_process(client.process.pid,exe,args.architecture,handle=int(client.process._handle));watch=WorkerWatch(native,exe,args.expected_sha256,args.architecture,context='portable');native['createdFileTime']=watch.created(int(client.process._handle));proof['server']=native
            for name,method,params in (('initialize','initialize',{'protocolVersion':'2025-06-18','capabilities':{},'clientInfo':{'name':'OpenGeul structured companion','version':'1'}}),('tools-list','tools/list',{})):
                response=client.request(method,params)
                if method=='initialize':
                    value=response.get('result',{});lock=json.loads((ROOT/'config/upstream.lock.json').read_bytes());require(value.get('protocolVersion')=='2025-06-18' and value.get('serverInfo',{}).get('name')=='rhwp' and value['serverInfo'].get('version')==lock['rhwp']['version'],'Actual companion initialize differs');client.notify('notifications/initialized')
                else:
                    definitions=response.get('result',{}).get('tools',[]);proof['_toolDefinitions']=definitions;names=[t.get('name') for t in definitions];require(REQUIRED_TOOLS<=set(names) and len(names)==len(set(names)),'Actual public structured tools missing/duplicate')
                row=result_receipt(name,response,{});row.pop('checks');row.update(channel='mcp',serverProcessId=client.process.pid,passed=True);raw=canonical(response);request=canonical({'operation':method,'arguments':params});folder=args.out/'calls';folder.mkdir(exist_ok=True);rp=folder/(name+'-request.json');sp=folder/(name+'-response.json');rp.write_bytes(request);sp.write_bytes(raw);row.update(operation=method,requestSha256=hashlib.sha256(request).hexdigest(),requestBytes=len(request),requestFile=str(rp.relative_to(args.out)),responseFile=str(sp.relative_to(args.out)));proof['setup'].append(row)
            suite=Suite(exe,args.architecture,binding,work,definition,client,watch,proof)
            # CFB is independently converted to XML and checked against the same definition;
            # the converter's output never defines expected markers/styles/geometry.
            suite.case={'calls':proof['preflight'],'artifacts':[]};hwp=fixture/'structured.hwp';xml=work/'preflight-hwp.hwpx';value=suite.cli('preflight-hwp',['export-hwpx',str(hwp),str(xml),'--verify','--json'],work);output_record(value,hwp,xml,'hwpx',verified=True,conversion=True);baseline_hwp=oracle.inspect_hwpx(xml,definition);oracle.verify_original(baseline_hwp,definition);preserved=args.out/'preflight-hwp.hwpx';shutil.copyfile(xml,preserved);proof['preflightArtifact']={'path':preserved.name,'sha256':digest(preserved),'bytes':preserved.stat().st_size}
            for fmt in ('hwp','hwpx'):
                baseline=baseline_hwp if fmt=='hwp' else baseline_xml
                for category in CATEGORIES:
                    try:suite.execute_case(fmt,category,fixture,baseline)
                    except Exception as error:
                        if suite.case and suite.case.get('id')==fmt+'-'+category:suite.case.update(status='failed',**failure_record(error))
                        else:proof['cases'].append({'id':fmt+'-'+category,'status':'failed',**failure_record(error)})
                    finally:require({n:digest(fixture/n) for n in required}==hashes,'Original fixture changed during failed category')
            proof['framesSent']=client.frames_sent;proof['framesReceived']=client.frames_received;require(all(digest(fixture/n)==hashes[n] for n in required),'Companion suite changed an original fixture')
        finally:
            # Failure is bounded original evidence, never replaced by a unit mock PASS.
            retain_partial(client,proof,args.out)
    proof['passed']=all(c.get('status')=='passed' for c in proof['cases']) and len(proof['cases'])==16
    require(digest(args.exe)==args.expected_sha256 and {n:digest(fixture/n) for n in required}==hashes,'Re-read product/input identity changed')
    verify_receipt(proof,binding,helper_map,expected_cli=digest(args.exe),expected_inputs=hashes,evidence_root=args.out,expected_transport=transport)
    serialized=strict_json(canonical(proof));verify_receipt(serialized,binding,helpers(),expected_cli=digest(args.exe),expected_inputs={n:digest(fixture/n) for n in required},evidence_root=args.out,expected_transport=strict_json(args.binding.read_bytes()));require(helper_map==helpers(),'Companion helpers changed during execution')
    (args.out/'structured-result.json').write_bytes(canonical(proof)+b'\n');print(json.dumps({'passed':True,'context':'portable','validCategories':8,'formats':2,'caseCount':16,'fullFeatureCoverage':False}))

if __name__=='__main__':
    try:main()
    except Exception:raise SystemExit('Structured portable companion failed; no installed/full-feature success is claimed.') from None
