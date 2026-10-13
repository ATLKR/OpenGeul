"""검증된 Store70 원본 쌍과 소유 초안 하나만 별도 운영 실행에서 재개한다."""
from __future__ import annotations
import argparse
import hashlib
import io
import os
from pathlib import Path
import re
import stat
import zipfile

import store_submit as submission
from mcp_qa_download import GitHub, _page

RUN = '38337436070'
HEAD = '31073ee6359e507c3b17ecb2e779acad37480494'
BRANCH = 'diagnostic/store70-resume'
SID = '1152921505702110055'
BASELINE = '1152921505702042424'
ARTIFACT = 11786290181
ZIP_SIZE = 59743268
ZIP_SHA = '6609ed3d28ad58b642024f43a2e1a5fbdad8fa9ccda1fdb32efe48893500e238'
PAIR = {'x64':'e0529ef15edb1bfb046a1e4dd309896d9c371ac7619a505e7db8ab24b911d444',
        'arm64':'3182c80fe3c8d402b351e72bc664edb72c91894fa96b8a030b36ea23135fbbb3'}
SOURCE = {'version':'1.1.3','sourceCommit':'859f676167b258a7a6a57ecdfcb0e224338de01a',
          'sourceRunId':'38294374822','sourceRunAttempt':'1','sourceReleaseId':410953892,
          'sourceAssetFingerprintSha256':'fa5e0d0857d7e5d3331c731d408cea0aad9656f55ae25e68b70c4504c01cd11e'}
GATES = {'package':115100603292,'verify-api':115100603597,'Store WACK (x64)':115100973087,
         'store-native-arm64':115100973311,'Store WACK (arm64)':115102310654,'qualify':115102942299,
         'submit':115103065907}
NAMES = {'source-provenance.json','store-provenance.json','SHA256SUMS.txt','store-qualification.json',
         'OpenGeul-editor.png','screenshot-provenance.json'} | {
    f'OpenGeul_1.1.3.0_{a}_store-unsigned.msix' for a in PAIR} | {
    f'{stem}-{a}{suffix}' for a in PAIR for stem,suffix in (
        ('AppxManifest','.xml'),('install','.json'),('installed-cli','.json'),
        ('installed-launch','.json'),('wack','.xml'),('wack','.json'),('wack-context','.json'))}


def require(value, reason):
    if not value: raise submission.SubmissionBlocked(reason)


def caller(backend=None):
    require(os.getenv('GITHUB_REPOSITORY') == submission.REPOSITORY
        and os.getenv('GITHUB_REF') == 'refs/heads/' + BRANCH
        and os.getenv('GITHUB_EVENT_NAME') == 'workflow_dispatch'
        and os.getenv('GITHUB_JOB') == 'resume-store70'
        and os.getenv('GITHUB_ACTIONS') == 'true' and os.getenv('RUNNER_ENVIRONMENT') == 'github-hosted'
        and os.getenv('GITHUB_ACTOR') == 'ATLKR' and os.getenv('GITHUB_TRIGGERING_ACTOR') == 'ATLKR'
        and os.getenv('GITHUB_RUN_ATTEMPT') == '1'
        and os.getenv('STORE_ADOPT_PENDING','false') == 'false'
        and os.getenv('STORE_RECOVER_PENDING','false') == 'false', 'Only the fixed owned Store70 resume operator may write')
    run_id = submission._id(os.getenv('GITHUB_RUN_ID')); sha = os.getenv('GITHUB_SHA')
    require(run_id != RUN and isinstance(sha,str) and re.fullmatch('[0-9a-f]{40}',sha), 'Invalid separate operator identity')
    value = (backend or GitHub()).get('actions/runs/' + run_id)
    require(type(value.get('id')) is int and str(value['id']) == run_id and value.get('head_sha') == sha
        and type(value.get('run_attempt')) is int and value['run_attempt'] == 1
        and value.get('event') == 'workflow_dispatch' and value.get('head_branch') == BRANCH
        and value.get('path') == '.github/workflows/store-package.yml'
        and value.get('repository',{}).get('full_name') == submission.REPOSITORY
        and value.get('repository',{}).get('private') is False
        and value.get('status') == 'in_progress' and value.get('conclusion') is None
        and all(value.get(k,{}).get('login') == 'ATLKR' and value[k].get('type') == 'User'
                for k in ('actor','triggering_actor')), 'The resume caller API identity changed')


def origin(backend=None):
    api = backend or GitHub(); run = api.get('actions/runs/' + RUN)
    require(type(run.get('id')) is int and str(run['id']) == RUN and run.get('head_sha') == HEAD
        and type(run.get('run_attempt')) is int and run['run_attempt'] == 1
        and run.get('event') == 'workflow_dispatch' and run.get('head_branch') == 'main'
        and run.get('path') == '.github/workflows/store-package.yml'
        and run.get('repository',{}).get('full_name') == submission.REPOSITORY
        and run.get('repository',{}).get('private') is False
        and run.get('status') == 'completed' and run.get('conclusion') == 'failure'
        and all(run.get(k,{}).get('login') == 'ATLKR' and run[k].get('type') == 'User'
                for k in ('actor','triggering_actor')), 'Original Store70 run changed')
    jobs = _page(api.get(f'actions/runs/{RUN}/attempts/1/jobs?per_page=100'), 'jobs')
    require(len(jobs) == len(GATES) and {j.get('name') for j in jobs} == set(GATES), 'Original Store70 job inventory changed')
    for job in jobs:
        require(type(job.get('id')) is int and job['id'] == GATES[job['name']]
            and str(job.get('run_id')) == RUN and job.get('head_sha') == HEAD
            and type(job.get('run_attempt')) is int and job['run_attempt'] == 1
            and job.get('status') == 'completed'
            and job.get('conclusion') == ('failure' if job['name'] == 'submit' else 'success'), 'Original Store70 gate changed')
    artifact = api.get('actions/artifacts/' + str(ARTIFACT))
    require(type(artifact.get('id')) is int and artifact['id'] == ARTIFACT
        and artifact.get('name') == 'opengeul-store-qualified-' + RUN
        and type(artifact.get('size_in_bytes')) is int and artifact['size_in_bytes'] == ZIP_SIZE
        and artifact.get('digest') == 'sha256:' + ZIP_SHA and artifact.get('expired') is False
        and artifact.get('workflow_run',{}).get('id') == int(RUN)
        and artifact['workflow_run'].get('head_sha') == HEAD, 'Original qualified Store70 artifact changed')
    return api


def zip_entries(raw):
    require(isinstance(raw,bytes) and len(raw) == ZIP_SIZE and hashlib.sha256(raw).hexdigest() == ZIP_SHA,
            'Original qualified Store70 ZIP digest changed')
    archive = zipfile.ZipFile(io.BytesIO(raw)); entries = archive.infolist()
    require(len(entries) == 22 and {e.filename for e in entries} == NAMES
        and sum(e.file_size for e in entries) <= submission.LIMIT
        and all(not e.is_dir() and stat.S_IFMT(e.external_attr >> 16) in (0,stat.S_IFREG)
                and not e.flag_bits & 1 and not e.external_attr & 0x400
                and 0 < e.file_size <= submission.LIMIT for e in entries)
        and archive.testzip() is None, 'Original qualified ZIP inventory is unsafe or incomplete')
    return archive


def producer(details, directory):
    origin()
    require(all(details.get(k) == v for k,v in SOURCE.items()) and details.get('repackageCommit') == HEAD
        and str(details.get('repackageRunId')) == RUN and set(details.get('architectures',{})) == set(PAIR)
        and all(details['architectures'][a].get('sha256') == h for a,h in PAIR.items()), 'Resume cannot substitute the original Source87/Store70 pair')
    with zip_entries((directory.parent / '.work/store70-qualified.zip').read_bytes()) as archive:
        require({p.name for p in directory.iterdir()} == NAMES, 'Qualified Store70 files changed')
        for entry in archive.infolist():
            path = directory / entry.filename
            require(path.is_file() and not path.is_symlink() and path.stat().st_size == entry.file_size
                and hashlib.sha256(path.read_bytes()).digest() == hashlib.sha256(archive.read(entry)).digest(), 'Downloaded qualified Store70 bytes changed')
    return {'GITHUB_REPOSITORY':submission.REPOSITORY,'GITHUB_SHA':HEAD,'GITHUB_RUN_ID':RUN,'GITHUB_RUN_ATTEMPT':'1'}


def journal_guard(state, details, body):
    require(state.get('tag') == 'v1.1.3' and state.get('submission_id') == SID
        and state.get('phase') in {'draft_ready','commit_attempted','submitted'}
        and submission._journal_matches(state,details), 'Resume requires the same owned SID and full pair journal')
    if 'resume_upload_state' in state:
        require(state['resume_upload_state'] in {'attempted','acknowledged'}
            and state.get('resume_upload_sha256') == hashlib.sha256(body).hexdigest()
            and state.get('resume_producer_run_id') == RUN, 'Resume upload ownership changed')
        require(not (state['phase'] == 'draft_ready' and state['resume_upload_state'] == 'attempted'),
                'An earlier upload has no acknowledgment; read-only reconciliation is required')


def api_guard(method, path, seen):
    read = {'',f'submissions/{BASELINE}',f'submissions/{SID}',f'submissions/{SID}/status'}
    require(method == 'GET' and path in read or method == 'PUT' and path == f'submissions/{SID}'
        or method == 'POST' and path == f'submissions/{SID}/commit', 'Resume cannot create, delete or retarget any Store submission')
    if method != 'GET':
        require((method,path) not in seen, 'The resume operator never repeats an in-flight mutation')
        seen.add((method,path))


def download(directory):
    caller(); api = origin()
    require(not directory.exists() and directory.parent.is_dir(), 'Resume output must be fresh')
    target = directory.parent / '.work/store70-qualified.zip'
    require(not target.exists(), 'Original ZIP may not be overwritten')
    raw = api._bytes('actions/artifacts/' + str(ARTIFACT) + '/zip', submission.LIMIT)
    with zip_entries(raw) as archive:
        target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(raw); directory.mkdir()
        for entry in archive.infolist(): (directory / entry.filename).write_bytes(archive.read(entry))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--download',type=Path,required=True)
    try: download(parser.parse_args().download)
    except (ValueError, OSError, KeyError, TypeError, zipfile.BadZipFile):
        raise SystemExit('Store70 원본 검증/수신 실패. 인증 값과 응답 내용은 출력하지 않습니다.') from None
