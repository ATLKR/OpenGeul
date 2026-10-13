"""Observe an owner-deleted draft and reconcile one journal; Store GET only."""
import argparse, copy, hashlib, json, os, re, subprocess, urllib.error, urllib.request
from pathlib import Path
import store_submit as w

REF='refs/heads/diagnostic/store-owner-delete-reconcile-113'
PENDING=w.ADOPTION_PENDING_ID;PUBLISHED=w.ADOPTION_BASELINE_ID;SEMANTIC_SHA=w.RECOVERY_DRAFT_SHA256
EXPECTED=dict(w._recovery_claim(),phase='delete_attempted',deleted_id=PENDING)
ISSUE='issues/20'
RUNS='actions/workflows/store-package.yml/runs?branch=diagnostic/store-owner-delete-reconcile-113&event=workflow_dispatch&per_page=100'
MAX_RESPONSE=1024*1024

def require(value):
    if not value:raise ValueError('External deletion reconciliation guard mismatch')

def pairs(items):
    result={}
    for key,value in items:require(key not in result);result[key]=value
    return result

def decode(raw):
    require(isinstance(raw,bytes)and 0<len(raw)<=MAX_RESPONSE)
    value=json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('Nonfinite JSON')))
    require(isinstance(value,dict));return value

def gh(method,path,data=None):
    require((method=='GET'and path in{ISSUE,RUNS})or(method=='PATCH'and path==ISSUE))
    command=['gh','api','--method',method,'repos/ATLKR/OpenGeul/'+path]
    if data is not None:command+=['--input','-']
    result=subprocess.run(command,input=json.dumps(data).encode()if data is not None else None,capture_output=True,timeout=30)
    require(result.returncode==0);return decode(result.stdout)

def scope(value):
    require(os.getenv('GITHUB_REPOSITORY')=='ATLKR/OpenGeul'and os.getenv('GITHUB_EVENT_NAME')=='workflow_dispatch'
        and os.getenv('GITHUB_REF')==REF and os.getenv('GITHUB_ACTOR')=='ATLKR'and os.getenv('GITHUB_TRIGGERING_ACTOR')=='ATLKR'
        and os.getenv('GITHUB_JOB')=='reconcile'and os.getenv('GITHUB_RUN_ATTEMPT')=='1'
        and os.getenv('GITHUB_WORKFLOW_REF')=='ATLKR/OpenGeul/.github/workflows/store-package.yml@'+REF
        and os.getenv('CONFIRM_OWNER_DELETED_PENDING_ID')==PENDING
        and re.fullmatch('[0-9a-f]{40}',os.getenv('GITHUB_SHA',''))and re.fullmatch('[1-9][0-9]{0,24}',os.getenv('GITHUB_RUN_ID','')))
    runs=value.get('workflow_runs');count=value.get('total_count')
    require(type(count)is int and 0<count<100 and isinstance(runs,list)and len(runs)==count and all(isinstance(r,dict)for r in runs))
    matches=[r for r in runs if r.get('head_sha')==os.getenv('GITHUB_SHA')];require(len(matches)==1);run=matches[0]
    require(type(run.get('id'))is int and str(run['id'])==os.getenv('GITHUB_RUN_ID')and type(run.get('run_attempt'))is int and run['run_attempt']==1
        and run.get('head_branch')==REF.removeprefix('refs/heads/')and run.get('event')=='workflow_dispatch'
        and run.get('path')=='.github/workflows/store-package.yml')
    owner={'login':'ATLKR','type':'User','id':65988341}
    require(all(isinstance(run.get(k),dict)and all(run[k].get(f)==v for f,v in owner.items())for k in('actor','triggering_actor')))

def journal(issue):
    require(w._owned_journal(issue)and issue.get('number')==20 and issue.get('id')==5819766913 and issue.get('state')=='open')
    body=issue.get('body');require(isinstance(body,str)and body.count(w.JOURNAL)==1 and len(body.encode())<=64*1024)
    text,end=body.split(w.JOURNAL,1)[1].split('\n-->',1);require(not end.strip())
    state=decode(text.encode());require(w._journal_state(body)==state);return state

def write(path,value):
    raw=(json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode();require(len(raw)<=128*1024)
    with os.fdopen(os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'wb')as output:
        output.write(raw);output.flush();os.fsync(output.fileno())

def reconcile(opener,token,github,directory,result=None):
    directory=Path(directory);require(not directory.exists()and not directory.is_symlink());directory.mkdir()
    if result is None:result={}
    result.update(storeMutationsAttempted=False,journalPatchAttempted=False,journalUpdateAcknowledged=False,storeGets=[])
    def get(path,allow404=False):
        require(path in{'','submissions/'+PENDING,'submissions/'+PUBLISHED})
        request=urllib.request.Request(w.BASE+('/'+path if path else''),method='GET',headers={'Authorization':'Bearer '+token,'Accept':'application/json'})
        try:
            with opener.open(request,timeout=30)as response:
                require(response.status==200);raw=response.read(MAX_RESPONSE+1)
        except urllib.error.HTTPError as error:
            result['storeGets'].append({'pathRole':'old-pending'if allow404 else'guard-get','httpStatus':error.code});error.close()
            require(allow404 and error.code==404);return None
        value=decode(raw);result['storeGets'].append({'pathRole':'app'if not path else'published'if path.endswith(PUBLISHED)else'old-pending',
            'httpStatus':200,'responseSha256':hashlib.sha256(raw).hexdigest()});return value
    def observe():
        app=get('');require(app.get('id')==w.STORE_APP_ID and app.get('packageIdentityName')==w.STORE_IDENTITY['name']
            and 'pendingApplicationSubmission'in app and app['pendingApplicationSubmission']is None
            and isinstance(app.get('lastPublishedApplicationSubmission'),dict)and app['lastPublishedApplicationSubmission'].get('id')==PUBLISHED)
        require(get('submissions/'+PENDING,True)is None);baseline=get('submissions/'+PUBLISHED)
        require(baseline.get('id')==PUBLISHED and baseline.get('status')=='Published'and w.draft_semantic_sha256(baseline)==SEMANTIC_SHA
            and baseline.get('targetPublishMode')=='Manual'and baseline.get('fileUploadUrl')in(None,''))
        w._free(baseline);w._no_mandatory_update(baseline);packages=baseline.get('applicationPackages')
        require(isinstance(packages,list)and len(packages)==1 and isinstance(packages[0],dict)
            and packages[0].get('version')=='1.1.1.0'and packages[0].get('architecture','').lower()=='x64'and packages[0].get('fileStatus')=='Uploaded')
    try:
        original=github('GET',ISSUE);prior=journal(original);require(prior==EXPECTED);observe()
        history={'prior_journal':copy.deepcopy(prior),'api_deletion_acknowledged':False,'owner_confirmed_dashboard_deletion':True,
            'owner':'ATLKR','confirmation':'Explicit user confirmation: dashboard deletion of unpublished Submission 2',
            'fresh_readonly_execution':{'run_id':os.getenv('GITHUB_RUN_ID'),'head':os.getenv('GITHUB_SHA'),'attempt':os.getenv('GITHUB_RUN_ATTEMPT')},
            'old_sid_http_status':404,'published_sid':PUBLISHED,'published_semantic_sha256':SEMANTIC_SHA,
            'previous_api_failure':{'run_id':'38326193947','http_status':400,'code':'InvalidOperation',
                'response_sha256':'7750d2e08a377a473c0c1eda61a42971dfc9313232d6b88a60a993f083e8f4d3'},
            'prior_issue_snapshot_sha256':'9518b11fb301aa79362021a3752e1899f48fdf1de6efa68b00d1a518682fafe5'}
        state={k:v for k,v in prior.items()if not k.startswith(('adopted_','adoption_'))}
        state.update(phase='delete_confirmed',submission_id=None,externally_deleted_clone=history)
        body=w._journal_body(state,warning='Owner dashboard deletion observed by GET; prior API DELETE failed with HTTP400 and was not acknowledged')
        require(w._journal_state(body)==state);result['newJournalState']=state
        write(directory/'external-delete-observation.json',result);observe()
        current=github('GET',ISSUE);require(journal(current)==prior and current['body']==original['body'])
        result['journalPatchAttempted']=True
        changed=github('PATCH',ISSUE,{'body':body,'state':'open'});require(journal(changed)==state and changed['body']==body)
        fresh=github('GET',ISSUE);require(journal(fresh)==state and fresh['body']==body)
        result['journalUpdateAcknowledged']=True
    except Exception:result['verificationFailure']=True
    write(directory/'journal-reconciliation.json',result);return result

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output-dir',type=Path,required=True);args=parser.parse_args()
    result={'storeMutationsAttempted':False,'journalPatchAttempted':False,'journalUpdateAcknowledged':False}
    try:
        require(not args.output_dir.exists()and not args.output_dir.is_symlink());scope(gh('GET',RUNS))
        opener,token=w.authenticate();reconcile(opener,token,gh,args.output_dir,result)
    except Exception:result['verificationFailure']=True
    print(json.dumps({k:result[k]for k in('storeMutationsAttempted','journalPatchAttempted','journalUpdateAcknowledged')},sort_keys=True))
    return 0 if result['journalUpdateAcknowledged']else 1

if __name__=='__main__':raise SystemExit(main())
