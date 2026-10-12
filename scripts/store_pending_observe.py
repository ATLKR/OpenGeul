"""고정 앱의 현재 대기 제출·공개 기준을 GET만 수행해 제한 필드로 기록한다."""
from __future__ import annotations
import argparse, hashlib, json, os
from pathlib import Path
import re, urllib.error, urllib.request
from check_store_api import authenticate

APP_ID='9PJH0T3PHRMF'
IDENTITY='57904TaewonLiodLim.OpenGeul'
BASE='https://manage.devcenter.microsoft.com/v1.0/my/applications/'+APP_ID
REF='refs/heads/diagnostic/store-pending-113'
MAX_RESPONSE=1024*1024
MAX_OUTPUT=128*1024
SEMANTIC_EXCLUDED={'id','status','statusDetails','fileUploadUrl','friendlyName'}
STATUSES={'None','Canceled','PendingCommit','CommitStarted','CommitFailed','PendingPublication','Publishing','Published','PublishFailed','PreProcessing','PreProcessingFailed','Certification','CertificationFailed','Release','ReleaseFailed','InProgress'}

def require(value):
    if not value: raise ValueError('고정 앱·제출 또는 응답 계약 불일치')

def pairs(items):
    result={}
    for key,value in items:
        require(key not in result); result[key]=value
    return result

def decode(raw):
    require(isinstance(raw,bytes) and 0<len(raw)<=MAX_RESPONSE)
    value=json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('비정규 숫자')))
    require(isinstance(value,dict)); return value

def sid(value):
    require(isinstance(value,str) and re.fullmatch(r'[1-9][0-9]{0,24}',value)); return value

def reference(value):
    if value is None: return None
    require(isinstance(value,dict)); return sid(value.get('id'))

def fingerprint(value):
    raw=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()

def draft_semantic_fingerprint(value):
    require(isinstance(value,dict))
    return fingerprint({key:item for key,item in value.items() if key not in SEMANTIC_EXCLUDED})

def summary(value,expected):
    require(value.get('id')==expected and value.get('status') in STATUSES)
    require(value.get('targetPublishMode') in {'Immediate','Manual','SpecificDate'})
    packages=value.get('applicationPackages'); require(isinstance(packages,list) and len(packages)<=128)
    selected=[]
    for package in packages:
        require(isinstance(package,dict)); version=package.get('version'); architecture=package.get('architecture')
        state=package.get('fileStatus'); require(state in {'None','PendingUpload','Uploaded','PendingDelete','Deleted','Invalid'})
        if state=='Uploaded': require(version is not None and architecture is not None)
        if version is not None: require(isinstance(version,str) and re.fullmatch(r'(?:0|[1-9][0-9]{0,4})(?:\.(?:0|[1-9][0-9]{0,4})){3}',version) and all(int(x)<=65535 for x in version.split('.')))
        if architecture is not None: require(isinstance(architecture,str) and architecture.isascii() and architecture.lower() in {'x86','x64','arm','arm64','neutral'})
        selected.append({'version':version,'architecture':architecture.lower() if architecture is not None else None,'fileStatus':state})
    pricing=value.get('pricing'); require(isinstance(pricing,dict))
    price=pricing.get('priceId'); require(price=='Free' or isinstance(price,str) and re.fullmatch(r'Tier[1-9][0-9]*',price))
    overrides=pricing.get('marketSpecificPricings'); require(isinstance(overrides,dict))
    available_free=price=='Free' and all(isinstance(p,str) and p in {'Free','Base','NotAvailable'} for p in overrides.values())
    upload_destination=value.get('fileUploadUrl'); require(upload_destination is None or isinstance(upload_destination,str))
    fields=('applicationPackages','listings','pricing','packageDeliveryOptions','notesForCertification','targetPublishMode','targetPublishDate')
    return {'id':expected,'status':value['status'],'targetPublishMode':value['targetPublishMode'],'freeBasePrice':price=='Free',
            'availableMarketsFree':available_free,'packageCount':len(selected),'packages':selected,'uploadDestinationPresent':bool(upload_destination),
            'draftContentSha256':draft_semantic_fingerprint(value),'apiFieldSha256':{field:fingerprint(value[field]) for field in fields if field in value},
            'fingerprintFormat':'canonical UTF-8 JSON: sorted keys, compact separators, ensure_ascii=False; raw values/URLs never emitted'}

def observe(opener,token,expected_pending_id=''):
    def get(endpoint):
        require(endpoint==BASE or re.fullmatch(re.escape(BASE)+r'/submissions/[1-9][0-9]{0,24}',endpoint))
        request=urllib.request.Request(endpoint,headers={'Authorization':'Bearer '+token,'Accept':'application/json'},method='GET')
        with opener.open(request,timeout=30) as response: raw=response.read(MAX_RESPONSE+1)
        return decode(raw)
    app=get(BASE)
    require(app.get('id')==APP_ID and app.get('packageIdentityName')==IDENTITY)
    pending=reference(app.get('pendingApplicationSubmission')); published=reference(app.get('lastPublishedApplicationSubmission'))
    if expected_pending_id: require(pending==sid(expected_pending_id))
    require(pending is None or pending!=published)
    pending_record=summary(get(BASE+'/submissions/'+pending),pending) if pending else None
    published_record=summary(get(BASE+'/submissions/'+published),published) if published else None
    return {'observation':'read-only','appId':APP_ID,'packageIdentityName':IDENTITY,'pendingReferenceId':pending,'publishedReferenceId':published,
            'pendingSubmission':pending_record,'publishedSubmission':published_record,'appReferenceMatchesSubmissionDetails':True,
            'automationJournalOwnershipAsserted':False,'storeMutationsAttempted':False,
            'scope':'고정 앱의 현재 참조와 상세 ID 결합만 확인. journal 소유권 또는 수정·삭제 적합성을 주장하지 않음'}

def main():
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--output',type=Path,required=True); parser.add_argument('--expected-pending-id',default='')
    args=parser.parse_args(); stage='workflow-scope'
    try:
        require(os.environ.get('GITHUB_REPOSITORY')=='ATLKR/OpenGeul' and os.environ.get('GITHUB_EVENT_NAME')=='workflow_dispatch' and os.environ.get('GITHUB_REF')==REF)
        stage='authentication'; opener,token=authenticate()
        stage='fixed-application-and-reference-gets'; result=observe(opener,token,args.expected_pending_id); code=0
    except Exception as error:
        result={'observation':'unverified','stage':stage,'httpStatus':error.code if isinstance(error,urllib.error.HTTPError) else None,
                'reason':'인증 또는 응답 검증 실패. 비밀·URL·응답 본문은 기록하지 않았습니다','storeMutationsAttempted':False}; code=1
    raw=(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode(); require(len(raw)<=MAX_OUTPUT)
    require(not args.output.exists() and not args.output.is_symlink())
    with args.output.open('xb') as output: output.write(raw)
    print(raw.decode(),end=''); return code

if __name__=='__main__': raise SystemExit(main())
