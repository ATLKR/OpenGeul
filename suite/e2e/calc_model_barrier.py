"""Exact, getter-only Calc completion policy; portable replay performs no I/O.

This synchronizes a new harness. It does not repair input, establish the cause
of the earlier failed run, or establish a product fix.
"""
from dataclasses import dataclass
import copy
import hashlib
import io
import json
import math
from pathlib import PurePosixPath
import re
import traceback
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET
import zipfile

from writer_model_barrier import (BINDING_KEYS, _binding, _path, require_original_shell,
                                  require_python_identity)

SERVICE='com.sun.star.sheet.SpreadsheetDocument'
GETTERS='calc-a1-b1-c1-d1-v1'
MARKER='UI-OpenGeul-calc'
MAX_SECONDS=12.0
MAX_READS=120
MAX_TEXT_BYTES=1024*1024
MAX_PACKAGE_BYTES=16*1024*1024
BASELINE_KEYS={'schemaVersion','sourceSha256','sourceBytes','worksheetPart','a1Text',
               'b1Value','c1Value','d1Formula','d1Value'}
NS={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
    'r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    'p':'http://schemas.openxmlformats.org/package/2006/relationships'}


def _json(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)


def _time(value):
    assert type(value) in (int,float) and math.isfinite(value) and value>=0,'Invalid bounded monotonic time'
    return float(value)


def _text(value):
    assert isinstance(value,str) and len(value.encode('utf-8'))<=MAX_TEXT_BYTES,'Invalid bounded exact Calc text'
    return value  # No newline, whitespace, case or Unicode normalization.


def _number(value,expected):
    assert type(value) in (int,float) and math.isfinite(value) and value==expected,'Calc numeric cell changed'
    return value


def _cells(observation):
    assert type(observation.get('sheetIndex')) is int and observation['sheetIndex']==0,'Calc getter selected another sheet'
    _text(observation.get('a1Text'))
    _number(observation.get('b1Value'),17);_number(observation.get('c1Value'),25);_number(observation.get('d1Value'),42)
    assert observation.get('d1Formula')=='=SUM(B1:C1)','Calc formula changed'
    assert type(observation.get('isModified')) is bool,'Missing typed modification state'


def _baseline(value):
    assert isinstance(value,dict) and set(value)==BASELINE_KEYS,'Incomplete independent Calc baseline'
    assert type(value['schemaVersion']) is int and value['schemaVersion']==1
    assert isinstance(value['sourceSha256'],str) and re.fullmatch('[a-f0-9]{64}',value['sourceSha256'])
    assert type(value['sourceBytes']) is int and 0<value['sourceBytes']<=MAX_PACKAGE_BYTES
    part=value['worksheetPart'];assert isinstance(part,str) and part.startswith('xl/') and '..' not in PurePosixPath(part).parts
    assert _text(value['a1Text']) and MARKER not in value['a1Text'],'UI marker is already present in baseline'
    _number(value['b1Value'],17);_number(value['c1Value'],25);_number(value['d1Value'],42)
    assert value['d1Formula']=='=SUM(B1:C1)','Calc baseline formula changed'
    return value


def baseline_from_ooxml(data):
    """Parse independent prelaunch bytes, resolving the first workbook sheet.

    File access belongs to the caller. No live observation can supply baseline.
    """
    assert isinstance(data,bytes) and 0<len(data)<=MAX_PACKAGE_BYTES
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names=archive.namelist()
        assert len(names)==len(set(names)),'Duplicate OOXML package member'
        assert all(not n.startswith(('/','\\')) and '\\' not in n and '..' not in PurePosixPath(n).parts for n in names),'Unsafe OOXML member'
        def xml(name):
            info=archive.getinfo(name)
            assert info.file_size<=2*1024*1024,'Calc XML exceeds parser bound'
            return ET.fromstring(archive.read(name))
        workbook=xml('xl/workbook.xml');sheets=workbook.findall('s:sheets/s:sheet',NS)
        assert sheets,'Workbook has no first sheet'
        relation=sheets[0].get('{'+NS['r']+'}id');assert relation
        matches=[r for r in xml('xl/_rels/workbook.xml.rels').findall('p:Relationship',NS) if r.get('Id')==relation]
        assert len(matches)==1,'First worksheet relationship is ambiguous'
        rel=matches[0];target=rel.get('Target','');uri=urlsplit(target)
        assert rel.get('Type')==NS['r']+'/worksheet' and rel.get('TargetMode','Internal')=='Internal'
        assert target and not any((uri.scheme,uri.netloc,uri.query,uri.fragment)) and '\\' not in target and '\x00' not in target
        assert '..' not in PurePosixPath(target).parts,'Worksheet target escapes package'
        part=str(PurePosixPath(target.lstrip('/')) if target.startswith('/') else PurePosixPath('xl')/target)
        assert part.startswith('xl/'),'Worksheet is outside workbook package'
        root=xml(part);cells=root.findall('s:sheetData/s:row/s:c',NS)
        assert len(cells)==4 and {c.get('r') for c in cells}=={'A1','B1','C1','D1'},'Unexpected baseline cells'
        cells={c.get('r'):c for c in cells};a1=cells['A1'];kind=a1.get('t')
        if kind=='s':
            entries=xml('xl/sharedStrings.xml').findall('s:si',NS)
            index=int(a1.findtext('s:v',default='',namespaces=NS));assert 0<=index<len(entries)
            text=''.join(n.text or '' for n in entries[index].findall('.//s:t',NS))
        else:
            assert kind=='inlineStr','Baseline A1 must be a string cell'
            text=''.join(n.text or '' for n in a1.findall('s:is//s:t',NS))
        values={}
        for address in ('B1','C1','D1'):
            cell=cells[address];assert cell.get('t','n')=='n'
            formula=cell.find('s:f',NS)
            assert (formula is not None)==(address=='D1'),'Baseline numeric/formula type changed'
            values[address]=float(cell.findtext('s:v',default='',namespaces=NS))
        formula=cells['D1'].findtext('s:f',default='',namespaces=NS)
        result=dict(schemaVersion=1,sourceSha256=hashlib.sha256(data).hexdigest(),sourceBytes=len(data),worksheetPart=part,
            a1Text=text,b1Value=values['B1'],c1Value=values['C1'],d1Formula='='+formula,d1Value=values['D1'])
        return copy.deepcopy(_baseline(result))


@dataclass(frozen=True)
class Expectation:
    suite_root:str
    baseline_json:str
    marker:str
    expected_url:str
    expected_a1:str
    started_at:float
    deadline:float
    binding_json:str
    before_input_json:str
    inventory_json:str
    inventory_sha256:str
    original_shell_json:str

    @property
    def baseline(self):return json.loads(self.baseline_json)
    @property
    def binding(self):return json.loads(self.binding_json)
    @property
    def inventory(self):return json.loads(self.inventory_json)
    def receipt(self):
        return dict(schemaVersion=1,suiteRoot=self.suite_root,baseline=self.baseline,marker=self.marker,
            expectedUrl=self.expected_url,expectedA1=self.expected_a1,startedAt=self.started_at,deadline=self.deadline,
            binding=self.binding,beforeInput=json.loads(self.before_input_json),inventorySha256=self.inventory_sha256,
            originalShell=json.loads(self.original_shell_json))


def freeze_expectation(binding,baseline,marker,before_input,*,suite_root,original_shell,inventory,
                       inventory_sha256,expected_url,started_at,timeout_seconds=MAX_SECONDS):
    start=_time(started_at)
    assert type(timeout_seconds) in (float,int) and math.isfinite(timeout_seconds) and 0<timeout_seconds<=MAX_SECONDS,'Invalid bounded completion budget'
    baseline=copy.deepcopy(_baseline(baseline));binding=_binding(copy.deepcopy(binding),suite_root)
    assert isinstance(expected_url,str) and expected_url and binding['documentUrl']==expected_url,'Calc URL differs from caller expectation'
    assert marker==MARKER,'Original exact Calc physical marker changed'
    require_original_shell(original_shell,binding,suite_root)
    _cells(before_input)
    plan=Expectation(str(_path(str(suite_root))),_json(baseline),marker,expected_url,baseline['a1Text']+marker,
        start,start+timeout_seconds,_json(binding),_json(before_input),_json(inventory),inventory_sha256,_json(original_shell))
    assert before_input.get('a1Text')==baseline['a1Text'] and before_input.get('isModified') is False,'Before-input model is not the independent clean baseline'
    assert validate_observation(plan,before_input,baseline['a1Text'])=='pending'
    return plan


def _retained(plan,observation):
    """Freeze raw observer/proxy/native identities across every accepted read."""
    frozen=json.loads(plan.before_input_json)
    for key in ('helperLaunch','systemConsoleHost'):
        assert observation[key]==frozen[key],'Original observer launch/console witness changed'
    for edge in ('before','after'):
        assert observation['unoSnapshots'][edge]['proxyIdentity']==frozen['unoSnapshots']['before']['proxyIdentity'],'Retained PyUNO context or type changed'
    for origin in ('controller','helper'):
        anchor=frozen['nativeSnapshots'][origin+'Before']
        for edge in ('Before','After'):
            row=observation['nativeSnapshots'][origin+edge]
            assert all(row[name]['handleValue']==anchor[name]['handleValue'] for name in ('shell','office')),'Original retained process HANDLE changed'
            assert row['officeCommandLine']==anchor['officeCommandLine'] and row['profileUrl']==anchor['profileUrl'],'Original Office transport/profile changed'
            assert row['profileDirectory']['witness']==anchor['profileDirectory']['witness'],'Retained profile directory witness changed'
    old=frozen['readerProcess'];current=observation['readerProcess']
    assert all(current[k]==old[k] for k in ('pid','creationTime','handleValue','jobHandleValue')),'Observer generation/HANDLE/job changed'
    assert _path(current['image'])==_path(old['image'])==_path(observation['pythonIdentity']['observed']['processImage'])


def validate_observation(plan,observation,previous_text):
    from writer_model_reader import require_owned_model_observation
    assert isinstance(plan,Expectation) and isinstance(observation,dict)
    require_owned_model_observation(observation,plan.binding,plan.suite_root,expected_service=SERVICE,getter_contract=GETTERS)
    assert plan.started_at<=_time(observation.get('readStartedAt'))<=_time(observation.get('readFinishedAt'))<=plan.deadline,'Calc read exceeded original absolute budget'
    require_python_identity(observation.get('pythonIdentity'),plan.suite_root,plan.inventory,plan.inventory_sha256)
    _retained(plan,observation)
    _cells(observation)
    prior=plan.baseline['a1Text'];previous=_text(previous_text);text=_text(observation.get('a1Text'))
    assert previous.startswith(prior) and plan.expected_a1.startswith(previous),'Invalid previous exact append prefix'
    assert text.startswith(prior) and plan.expected_a1.startswith(text),'Calc A1 changed baseline, dropped, duplicated or reordered input'
    assert len(text)>=len(previous),'Calc exact append prefix regressed'
    if text==plan.expected_a1:
        assert observation['isModified'] is True,'Completed Calc model is unexpectedly clean'
        return 'complete'
    return 'pending'


def await_completion(plan,reader,*,clock,pause,record,max_reads=MAX_READS-1):
    assert isinstance(record,dict) and 'state' not in record and 'error' not in record,'Completion receipt cannot be reused'
    assert type(max_reads) is int and 0<max_reads<MAX_READS,'Total read limit includes the before-input read'
    record.update(schemaVersion=1,kind='calc-model-completion',success=False,state='pending',
        expectation=plan.receipt(),deadline=plan.deadline,startedAt=plan.started_at,
        originalShell=json.loads(plan.original_shell_json),beforeInput=json.loads(plan.before_input_json),observations=[],
        originalPhysicalAsciiLossCauseEstablished=False,productFixEstablished=False)
    previous=plan.baseline['a1Text']
    try:
        for _ in range(max_reads):
            begin=_time(clock());assert begin<plan.deadline,'Calc model completion deadline expired'
            row={'startedAt':begin};record['observations'].append(row)
            try:observation=reader(plan.deadline);row['observation']=copy.deepcopy(observation)
            except BaseException as exc:row['error']=type(exc).__name__+': '+str(exc);raise
            finally:row['finishedAt']=_time(clock())
            assert begin<=_time(observation['readStartedAt'])<=_time(observation['readFinishedAt'])<=row['finishedAt']<=plan.deadline,'Calc raw read is outside original call budget'
            decision=validate_observation(plan,observation,previous);row['decision']=decision;previous=observation['a1Text']
            if decision=='complete':
                record.update(state='model-complete',success=True,modelEqualityAt=row['finishedAt']);return observation
            remaining=plan.deadline-_time(clock());assert remaining>0,'Calc model completion deadline expired'
            pause(min(.1,remaining))
        raise AssertionError('Calc model pending-read limit exceeded')
    except BaseException as exc:
        record.update(state='failed',success=False,error=type(exc).__name__+': '+str(exc),traceback=traceback.format_exc());raise


def finalize_completion(plan,record,cleanup,finished_at):
    from writer_model_reader import require_model_reader_cleanup
    assert record.get('state')=='model-complete' and record.get('success') is True
    try:
        require_model_reader_cleanup(cleanup,plan.binding,plan.deadline,expected_service=SERVICE,getter_contract=GETTERS)
        finished=_time(finished_at)
        assert _time(record['modelEqualityAt'])<=_time(cleanup['startedAt'])<=_time(cleanup['finishedAt'])<=finished<=plan.deadline,'Calc observer cleanup is outside original completion budget'
        frozen=json.loads(plan.before_input_json)
        for key in ('helperLaunch','systemConsoleHost'):assert cleanup[key]==frozen[key],'Cleanup changed observer launch/console witness'
        original=frozen['readerProcess'];members=[r for r in cleanup['readerMembers'] if r['pid']==original['pid']]
        assert len(members)==1 and cleanup['releaseAcknowledgement']['readerPid']==original['pid'],'Cleanup released another observer'
        member=members[0]
        assert all(member[k]==original[k] for k in ('creationTime','handleValue','jobHandleValue')),'Cleanup observer generation/HANDLE/job changed'
        assert _path(member['image'])==_path(original['image']) and cleanup['jobHandleValue']==original['jobHandleValue']
        anchor=frozen['nativeSnapshots']['controllerBefore']
        for edge in ('nativeBefore','nativeAfter'):
            raw=cleanup[edge]
            assert all(raw[name]['handleValue']==anchor[name]['handleValue'] for name in ('shell','office')),'Cleanup changed retained controller HANDLEs'
            assert raw['officeCommandLine']==anchor['officeCommandLine'] and raw['profileUrl']==anchor['profileUrl']
            assert raw['profileDirectory']['witness']==anchor['profileDirectory']['witness']
        helper=frozen['nativeSnapshots']['helperBefore'];ack=cleanup['releaseAcknowledgement']
        assert ack['profileDirectory']['witness']==helper['profileDirectory']['witness']
        expected={('shell',helper['shell']['handleValue']),('office',helper['office']['handleValue']),('profile-directory',helper['profileDirectory']['witness']['handleValue'])}
        assert {(r['kind'],r['handleValue']) for r in ack['observerHandleClosures']}==expected,'Cleanup closed another retained helper HANDLE'
        record.update(cleanup=copy.deepcopy(cleanup),finishedAt=finished,state='complete',success=True);return record
    except BaseException as exc:
        record.update(cleanup=copy.deepcopy(cleanup),state='failed',success=False,error=type(exc).__name__+': '+str(exc),traceback=traceback.format_exc());raise


def replay_completion(receipt,*,suite_root,inventory,inventory_sha256,binding,baseline,expected_url,marker=MARKER):
    """Pure raw replay using caller-supplied independent baseline/inventory/URL."""
    assert isinstance(receipt,dict) and type(receipt.get('schemaVersion')) is int and receipt['schemaVersion']==1
    assert receipt.get('kind')=='calc-model-completion' and receipt.get('state')=='complete' and receipt.get('success') is True
    assert receipt.get('originalPhysicalAsciiLossCauseEstablished') is False and receipt.get('productFixEstablished') is False
    raw=receipt['expectation'];start=_time(raw['startedAt']);deadline=_time(raw['deadline'])
    assert type(receipt.get('startedAt')) in (int,float) and receipt['startedAt']==start,'Top-level Calc start differs from frozen expectation'
    assert _json(receipt.get('originalShell'))==_json(raw['originalShell']),'Top-level original shell evidence differs from expectation'
    assert _json(receipt.get('beforeInput'))==_json(raw['beforeInput']),'Top-level before-input observation differs from expectation'
    plan=freeze_expectation(binding,baseline,marker,raw['beforeInput'],suite_root=suite_root,
        original_shell=raw['originalShell'],inventory=inventory,inventory_sha256=inventory_sha256,
        expected_url=expected_url,started_at=start,timeout_seconds=deadline-start)
    assert _json(raw)==_json(plan.receipt()) and receipt['deadline']==plan.deadline,'Calc frozen expectation changed'
    rows=receipt['observations'];assert isinstance(rows,list) and 0<len(rows)<MAX_READS
    previous=plan.baseline['a1Text'];last=_time(raw['beforeInput']['readFinishedAt'])
    for index,row in enumerate(rows):
        begin=_time(row['startedAt']);end=_time(row['finishedAt']);observation=row['observation']
        assert last<=begin<=_time(observation['readStartedAt'])<=_time(observation['readFinishedAt'])<=end<=plan.deadline
        decision=validate_observation(plan,observation,previous)
        assert row['decision']==decision and (decision=='complete') is (index==len(rows)-1),'Calc completion was premature or read after equality'
        previous=observation['a1Text'];last=end
    assert receipt['modelEqualityAt']==last
    replayed=dict(state='model-complete',success=True,modelEqualityAt=last)
    finalize_completion(plan,replayed,receipt['cleanup'],receipt['finishedAt'])
    from writer_model_reader import canonical_profile_projection
    native=raw['beforeInput']['nativeSnapshots']['controllerBefore']
    generation=copy.deepcopy(binding)
    generation.update(officeCommandLine=copy.deepcopy(native['officeCommandLine']),profileUrl=native['profileUrl'],
        canonicalProfile=canonical_profile_projection(native['profileDirectory']['witness'],native['profileUrl']))
    return dict(schemaVersion=1,kind='calc-model-case-replay',success=True,editCount=1,reads=len(rows),readCount=len(rows),
        frameGenerations=[generation],binding=copy.deepcopy(binding),expectedA1=plan.expected_a1,
        startedAt=start,finishedAt=receipt['finishedAt'],deadline=deadline,
        originalPhysicalAsciiLossCauseEstablished=False,productFixEstablished=False)
