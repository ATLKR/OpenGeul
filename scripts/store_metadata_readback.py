"""Explain Store70 metadata confirmation with fixed GETs and hashes only."""
import argparse, hashlib, json, os, re, subprocess, urllib.error, urllib.request
from pathlib import Path
import store_submit as w

REF='refs/heads/diagnostic/store-metadata-readback-70'
PENDING='1152921505702110055';PUBLISHED=w.ADOPTION_BASELINE_ID
MISSING=object();MAX_RESPONSE=1024*1024
KNOWN_KEYS=set(('id fileName fileStatus version architecture minimumDirectXVersion minimumSystemRam '
    'priceId trialPeriod marketSpecificPricings sales isAdvancedPricingModel '
    'baseListing platformOverrides title description features releaseNotes images keywords '
    'shortDescription licenseTerms copyrightAndTrademarkInfo supportContact websiteUrl privacyPolicyUrl '
    'imageType fileName description ').split())|{
    'ko-kr','en-us','en-gb','ja-jp','zh-cn','zh-tw','de-de','fr-fr','es-es','pt-br','it-it',
    'US','KR','GB','CA','AU','NZ','JP','CN','TW','HK','DE','FR','ES','IT','BR','IN','MX','NL','SE','NO','FI','DK'}
CANONICAL_FILES={'OpenGeul_1.1.3.0_'+arch+'_store-unsigned.msix'for arch in('x64','arm64')}

def require(value):
    if not value:raise ValueError('Fixed readback guard mismatch')

def pairs(items):
    value={}
    for key,item in items:require(key not in value);value[key]=item
    return value

def decode(raw):
    require(isinstance(raw,bytes)and 0<len(raw)<=MAX_RESPONSE)
    value=json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('Nonfinite JSON')))
    require(isinstance(value,dict));return value

def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def safe_key(key):
    return key if isinstance(key,str)and key in KNOWN_KEYS else'[key-sha256:'+digest(key)+']'

def shape(value):
    if value is MISSING:return {'present':False}
    result={'present':True,'type':type(value).__name__,'sha256':digest(value)}
    if isinstance(value,(str,list,dict)):result['length']=len(value)
    if isinstance(value,dict):result['keys']=[safe_key(k)for k in list(value)[:64]]
    return result

def differences(expected,actual,path,result,depth=0):
    if len(result)>=64 or expected==actual:return
    if isinstance(expected,dict)and isinstance(actual,dict)and depth<12:
        for key in sorted(set(expected)|set(actual))[:128]:
            differences(expected.get(key,MISSING),actual.get(key,MISSING),path+'.'+safe_key(key),result,depth+1)
    elif isinstance(expected,list)and isinstance(actual,list)and depth<12:
        for index in range(min(max(len(expected),len(actual)),128)):
            differences(expected[index]if index<len(expected)else MISSING,actual[index]if index<len(actual)else MISSING,
                        path+'['+str(index)+']',result,depth+1)
    else:result.append({'path':path,'expected':shape(expected),'actual':shape(actual)})

def expected_metadata(baseline,state):
    details={'formatVersion':2,'version':state['tag'][1:],'sourceReleaseId':int(state['release_id']),
             'sourceCommit':state['source_sha'],'sourceAssetFingerprintSha256':state['source_asset_fingerprint_sha256'],'architectures':{}}
    for arch in('x64','arm64'):
        details['architectures'][arch]={'sourceMsixSha256':state['source_msix_sha256_by_arch'][arch],
            'sha256':state['store_msix_sha256_by_arch'][arch],'package':'OpenGeul_'+w.package_version(details['version'])+'_'+arch+'_store-unsigned.msix'}
    metadata=w.apply_korean_listing(baseline);metadata['targetPublishMode']='Immediate'
    for package in metadata['applicationPackages']:package['fileStatus']='PendingDelete'
    for arch in('x64','arm64'):metadata['applicationPackages'].append({'fileName':details['architectures'][arch]['package'],
        'fileStatus':'PendingUpload','minimumDirectXVersion':'None','minimumSystemRam':'None'})
    notes=[line for line in metadata.get('notesForCertification','').splitlines()if not line.startswith(w.MARKER)]
    metadata['notesForCertification']='\n'.join(notes+[w._marker(details)])
    for field in('id','status','statusDetails','fileUploadUrl','friendlyName'):metadata.pop(field,None)
    return metadata,details

def packages_projection(value):
    if not isinstance(value,list):return []
    selected=[]
    for package in value[:16]:
        if not isinstance(package,dict):selected.append({'structure':shape(package)});continue
        entry={'structure':shape(package),'fields':{}}
        for field in('fileName','fileStatus','version','architecture','minimumDirectXVersion','minimumSystemRam'):
            raw=package.get(field,MISSING);entry['fields'][field]=shape(raw)
            valid=isinstance(raw,str)and(
                field=='fileName'and raw in CANONICAL_FILES
                or field=='version'and re.fullmatch(r'[0-9]{1,5}(?:\.[0-9]{1,5}){3}',raw)
                or field=='architecture'and raw.lower()in{'x86','x64','arm','arm64','neutral'}
                or field=='fileStatus'and raw in{'None','PendingDelete','PendingUpload','Uploaded','Deleted','Invalid'}
                or field=='minimumDirectXVersion'and raw in{'None','DirectX9','DirectX10','DirectX11','DirectX12'}
                or field=='minimumSystemRam'and raw in{'None','1GB','2GB','4GB','6GB','8GB','16GB','32GB'})
            if valid:entry[field]=raw
        selected.append(entry)
    return selected

def comparison(expected,actual,details,pending):
    notes=actual.get('notesForCertification');marker=isinstance(notes,str)and w._marker(details)in notes.splitlines()
    try:package_match=w._packages_match(actual,expected['applicationPackages'])
    except(KeyError,TypeError,ValueError):package_match=False
    result={'conditions':{'id':actual.get('id')==pending,'status':actual.get('status')=='PendingCommit','marker':marker,'packages':package_match,
        'pricing':actual.get('pricing')==expected['pricing'],'listings':actual.get('listings')==expected.get('listings')},'leafDifferences':[],
        'expectedPackages':packages_projection(expected.get('applicationPackages')),'actualPackages':packages_projection(actual.get('applicationPackages')),
        'expectedStructures':{key:shape(expected.get(key,MISSING))for key in('pricing','listings','notesForCertification')},
        'actualStructures':{key:shape(actual.get(key,MISSING))for key in('pricing','listings','notesForCertification')}}
    for field in('pricing','listings'):differences(expected.get(field,MISSING),actual.get(field,MISSING),field,result['leafDifferences'])
    result['leafDifferencesAtLimit']=len(result['leafDifferences'])>=64
    result['targetPublishMode']=actual.get('targetPublishMode')if actual.get('targetPublishMode')in{'Manual','Immediate','SpecificDate'}else None
    price=actual.get('pricing',{}).get('priceId')if isinstance(actual.get('pricing'),dict)else None
    result['priceId']=price if isinstance(price,str)and re.fullmatch(r'Free|Tier[1-9][0-9]{0,6}',price)else None
    return result

def observe(opener,token,state):
    require(state.get('app_id')==w.STORE_APP_ID and state.get('phase')=='draft_ready'and state.get('submission_id')==PENDING
        and state.get('baseline_id')==PUBLISHED and state.get('tag')=='v1.1.3'and state.get('source_sha')==w.ADOPTION_SOURCE['sourceCommit']
        and state.get('release_id')==str(w.ADOPTION_SOURCE['sourceReleaseId'])and state.get('run_id')==w.ADOPTION_SOURCE['sourceRunId']
        and state.get('source_asset_fingerprint_sha256')==w.ADOPTION_SOURCE['sourceAssetFingerprintSha256']
        and state.get('source_msix_sha256_by_arch')==w.RECOVERY_SOURCE_PAIR)
    receipts=[]
    def get(path):
        require(path in{'','submissions/'+PENDING,'submissions/'+PUBLISHED})
        request=urllib.request.Request(w.BASE+('/'+path if path else''),method='GET',headers={'Authorization':'Bearer '+token,'Accept':'application/json'})
        with opener.open(request,timeout=30)as response:require(response.status==200);raw=response.read(MAX_RESPONSE+1)
        value=decode(raw);receipts.append({'role':'app'if not path else'pending'if path.endswith(PENDING)else'published',
            'httpStatus':200,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()});return value
    app=get('');require(app.get('id')==w.STORE_APP_ID and app.get('packageIdentityName')==w.STORE_IDENTITY['name']
        and w._ref(app,'pendingApplicationSubmission')==PENDING and w._ref(app,'lastPublishedApplicationSubmission')==PUBLISHED)
    actual=get('submissions/'+PENDING);require(actual.get('id')==PENDING)
    baseline=get('submissions/'+PUBLISHED);require(baseline.get('id')==PUBLISHED and baseline.get('status')=='Published'
        and w.draft_semantic_sha256(baseline)==w.RECOVERY_DRAFT_SHA256)
    expected,details=expected_metadata(baseline,state)
    return {'appId':w.STORE_APP_ID,'pendingId':PENDING,'publishedId':PUBLISHED,'gets':receipts,'journalStateSha256':digest(state),
        'comparison':comparison(expected,actual,details,PENDING),'storeMutationsAttempted':False,'journalMutationPerformed':False}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    result={'storeMutationsAttempted':False,'journalMutationPerformed':False}
    try:
        require(os.getenv('GITHUB_REPOSITORY')=='ATLKR/OpenGeul'and os.getenv('GITHUB_EVENT_NAME')=='workflow_dispatch'and os.getenv('GITHUB_REF')==REF
            and os.getenv('GITHUB_ACTOR')=='ATLKR'and os.getenv('GITHUB_TRIGGERING_ACTOR')=='ATLKR'and os.getenv('GITHUB_JOB')=='readback'
            and os.getenv('GITHUB_RUN_ATTEMPT')=='1'and os.getenv('EXPECTED_PENDING_ID')==PENDING
            and os.getenv('GITHUB_WORKFLOW_REF')=='ATLKR/OpenGeul/.github/workflows/store-package.yml@'+REF)
        response=subprocess.run(['gh','api','--method','GET','repos/ATLKR/OpenGeul/issues/20'],capture_output=True,timeout=30)
        require(response.returncode==0);issue=decode(response.stdout)
        require(w._owned_journal(issue)and issue.get('number')==20 and issue.get('id')==5819766913)
        body=issue['body'];require(body.count(w.JOURNAL)==1 and len(body.encode())<=64*1024)
        state=decode(body.split(w.JOURNAL,1)[1].split('\n-->',1)[0].encode());require(w._journal_state(body)==state)
        opener,token=w.authenticate();result=observe(opener,token,state)
    except Exception:result['verificationFailure']=True
    result['execution']={'runId':os.getenv('GITHUB_RUN_ID'),'head':os.getenv('GITHUB_SHA'),'attempt':os.getenv('GITHUB_RUN_ATTEMPT')}
    raw=(json.dumps(result,sort_keys=True,indent=2,ensure_ascii=False)+'\n').encode();require(len(raw)<=192*1024)
    with os.fdopen(os.open(args.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'wb')as output:output.write(raw)
    print(json.dumps({'verifiedReadOnly':not result.get('verificationFailure',False),'bytes':len(raw),'storeMutationsAttempted':False},sort_keys=True))
    return 1 if result.get('verificationFailure')else 0

if __name__=='__main__':raise SystemExit(main())
