"""고정 초안·공개 기준·상태의 오류/경고만 GET으로 제한 관찰한다."""
from __future__ import annotations
import argparse, base64, hashlib, json, os
from pathlib import Path
import re, unicodedata, urllib.error, urllib.parse, urllib.request
from check_store_api import authenticate
from store_pending_observe import APP_ID, IDENTITY, BASE, REF, STATUSES, decode, require, reference, draft_semantic_fingerprint

PENDING='1152921505702100805'
PUBLISHED='1152921505702042424'
MAX_RESPONSE=1024*1024
MAX_OUTPUT=128*1024
MAX_ITEMS=16
MAX_MESSAGE=1024

class GetFailure(ValueError):
    def __init__(self,diagnostic):
        self.diagnostic=diagnostic
        super().__init__('고정 GET 응답 실패; 제한된 진단만 보존')

def sanitize(value,secrets):
    value=re.sub(r'\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))','',value)
    value=''.join(c for c in value if not unicodedata.category(c).startswith('C'))
    for secret in sorted(set(s for s in secrets if isinstance(s,str)and s),key=len,reverse=True):
        forms={secret,urllib.parse.quote(secret,safe=''),base64.b64encode(secret.encode()).decode()}
        for form in sorted(forms,key=len,reverse=True):value=value.replace(form,'[redacted]')
    value=re.sub(r'(?i)(?:https?|ftp|file|data):[^\s<>"\']+','[redacted-url]',value)
    value=re.sub(r'(?i)https?%3a(?:%2f){2}[^\s<>"\']+','[redacted-url]',value)
    value=re.sub(r'(?i)\bbearer\s+[^\s<>"\']+','[redacted-auth]',value)
    value=re.sub(r'(?i)\b(?:authorization|access_token|token|client_secret|password|sig)\s*[=:]\s*[^\s<>"\']+','[redacted-auth]',value)
    value=re.sub(r'\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b','[redacted-auth]',value)
    return value

def item(value,secrets):
    require(isinstance(value,dict))
    code=value.get('code',value.get('errorCode'))
    safe_code=None
    if isinstance(code,str)and re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{0,127}',code)and sanitize(code,secrets)==code:
        safe_code=code
    text=value.get('message',value.get('details'))
    require(text is None or isinstance(text,str))
    selected={'code':safe_code,'message':None,'messageTruncated':False}
    if text is not None:
        clean=sanitize(text,secrets).encode('utf-8');selected['message']=clean[:MAX_MESSAGE].decode('utf-8',errors='ignore')
        selected['messageTruncated']=len(clean)>MAX_MESSAGE
    return selected

def details(value,secrets):
    if value is None:return {'presence':'null','errors':[],'warnings':[]}
    require(isinstance(value,dict))
    selected={'presence':'object'}
    for key in('errors','warnings'):
        collection=value.get(key)
        require(collection is None or isinstance(collection,list))
        selected[key]=[item(v,secrets)for v in(collection or[])[:MAX_ITEMS]]
        selected[key+'Omitted']=max(0,len(collection or[])-MAX_ITEMS)
        selected[key+'Present']=key in value
    return selected

def observe(opener,token,secrets=()):
    secrets=tuple(secrets)+(token,)
    allowed={BASE,BASE+'/submissions/'+PENDING,BASE+'/submissions/'+PUBLISHED,BASE+'/submissions/'+PENDING+'/status'}
    receipts=[]
    def get(endpoint,role):
        require(endpoint in allowed)
        request=urllib.request.Request(endpoint,headers={'Authorization':'Bearer '+token,'Accept':'application/json'},method='GET')
        try:
            with opener.open(request,timeout=20)as response:
                require(response.status==200);raw=response.read(MAX_RESPONSE+1)
        except urllib.error.HTTPError as error:
            raw=error.read(MAX_RESPONSE+1);diagnostic={'role':role,'httpStatus':error.code,'responseBytes':len(raw),'responseSha256':hashlib.sha256(raw).hexdigest(),'errors':[]}
            if 0<len(raw)<=MAX_RESPONSE:
                try:
                    parsed=decode(raw);body=parsed.get('error',parsed)
                    if isinstance(body,dict):diagnostic['errors']=[item(body,secrets)]
                except(ValueError,TypeError):pass
            raise GetFailure(diagnostic)from None
        value=decode(raw);receipts.append({'role':role,'httpStatus':200,'responseBytes':len(raw),'responseSha256':hashlib.sha256(raw).hexdigest()})
        return value
    app=get(BASE,'app')
    require(app.get('id')==APP_ID and app.get('packageIdentityName')==IDENTITY)
    require(reference(app.get('pendingApplicationSubmission'))==PENDING and reference(app.get('lastPublishedApplicationSubmission'))==PUBLISHED)
    pending=get(BASE+'/submissions/'+PENDING,'pending')
    require(pending.get('id')==PENDING and pending.get('status')in STATUSES)
    published=get(BASE+'/submissions/'+PUBLISHED,'published')
    require(published.get('id')==PUBLISHED and published.get('status')=='Published')
    status=get(BASE+'/submissions/'+PENDING+'/status','pending-status')
    require(status.get('status')in STATUSES)
    def project(value):
        selected={'status':value['status'],'details':details(value.get('statusDetails'),secrets),'statusDetailsPresent':'statusDetails'in value}
        if value.get('id')is not None:selected['id']=value['id']
        return selected
    return {'observation':'read-only-status-diagnostics','appId':APP_ID,'pendingId':PENDING,'publishedId':PUBLISHED,
        'pending':project(pending),'published':project(published),'pendingStatus':project(status),
        'pendingSemanticSha256':draft_semantic_fingerprint(pending),'publishedSemanticSha256':draft_semantic_fingerprint(published),
        'gets':receipts,'storeMutationsAttempted':False,'wholeStoreQualified':False,'storeSubmitted':False,
        'scope':'현재 오류/경고의 제한된 GET projection만 관찰. 과거 DELETE 응답 원문 복원 또는 쓰기 적합성 증명이 아님'}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    stage='workflow-scope'
    try:
        require(os.getenv('GITHUB_REPOSITORY')=='ATLKR/OpenGeul'and os.getenv('GITHUB_EVENT_NAME')=='workflow_dispatch'
            and os.getenv('GITHUB_REF')==REF and os.getenv('GITHUB_RUN_ATTEMPT')=='1'and os.getenv('GITHUB_ACTOR')=='ATLKR'
            and os.getenv('GITHUB_JOB')=='observe'and os.getenv('GITHUB_WORKFLOW_REF')=='ATLKR/OpenGeul/.github/workflows/store-package.yml@'+REF)
        stage='authentication';opener,token=authenticate()
        secrets=[v for k,v in os.environ.items()if re.search(r'(?i)(SECRET|TOKEN|PASSWORD|(?:^|_)KEY(?:_|$))',k)]
        stage='fixed-reference-detail-and-status-gets';result=observe(opener,token,secrets);code=0
    except Exception as error:
        result={'observation':'unverified','stage':stage,'reason':'고정 GET/응답 검증 실패; 원문·URL·비밀은 출력하지 않음','storeMutationsAttempted':False,'wholeStoreQualified':False,'storeSubmitted':False}
        if isinstance(error,GetFailure):result['getFailure']=error.diagnostic
        code=1
    result['execution']={'commit':os.getenv('GITHUB_SHA'),'runId':os.getenv('GITHUB_RUN_ID'),'attempt':os.getenv('GITHUB_RUN_ATTEMPT')}
    raw=(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode('utf-8');require(len(raw)<=MAX_OUTPUT)
    require(not args.output.exists()and not args.output.is_symlink())
    with args.output.open('xb')as output:output.write(raw)
    print(json.dumps({'observation':result['observation'],'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'storeMutationsAttempted':False},sort_keys=True))
    return code

if __name__=='__main__':raise SystemExit(main())
