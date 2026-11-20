"""Publish only the producer's closed supplemental metadata; never acceptance."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

MAX_BYTES=32768
MODULES=('writer','calc','impress','draw','math','base')
STAGES=frozenset(('case-setup', 'engine-start', 'desktop-lease', 'owned-members', 'load-saved', 'base-create', 'base-initialize', 'base-configure', 'base-store-new', 'load-factory', 'populate', 'verify-generated', 'base-store', 'store-new', 'close-before-reopen', 'observe-saved', 'verify-saved', 'cleanup-proof', 'final-file-read', 'final-document-close', 'engine-cleanup', 'graceful engine exit', 'retain owned members', 'fixture desktop lifetime release', 'desktop termination', 'owned job exit', 'owned job recovery', 'private job handle close', 'private profile removal', 'private profile retained', 'retained member handle close', 'lifetime diagnostics', 'graceful exit proof', 'unknown'))
CATEGORIES=frozenset(('AssertionError', 'RuntimeError', 'ValueError', 'TypeError', 'OSError', 'PermissionError', 'FileNotFoundError', 'FileExistsError', 'TimeoutError', 'AttributeError', 'KeyError', 'DisposedException', 'IOException', 'CloseVetoException', 'NoConnectException', 'IllegalArgumentException', 'DeploymentException', 'unknown'))
SOURCES=('.work/suite-engine/engine-failure-summary.json',
         '.work/suite-engine-2/engine-failure-summary.json')
OUTPUTS=('.work/suite-engine-summary-first','.work/suite-engine-summary-repeated')


def need(value):
    if not value:raise ValueError('Closed supplemental summary rejected')


def pairs(items):
    result={}
    for key,value in items:
        need(key not in result)
        result[key]=value
    return result


def reject_constant(_):raise ValueError('Closed supplemental summary rejected')


def uint32(value):return type(value) is int and 0<=value<2**32


def error(row):
    need(type(row) is dict and set(row)=={'stage','category'})
    need(type(row['stage']) is str and row['stage'] in STAGES)
    need(type(row['category']) is str and row['category'] in CATEGORIES)


def validate_bytes(raw):
    need(type(raw) is bytes and 0<len(raw)<=MAX_BYTES)
    row=json.loads(raw.decode('utf-8'),object_pairs_hook=pairs,parse_constant=reject_constant)
    need(type(row) is dict and set(row)=={'schemaVersion','kind','acceptanceEligible','passed','cases'})
    need(type(row['schemaVersion']) is int and row['schemaVersion']==1)
    need(row['kind']=='engine-failure-summary' and row['acceptanceEligible'] is False and type(row['passed']) is bool)
    need(type(row['cases']) is list and len(row['cases'])==6)
    for module,case in zip(MODULES,row['cases']):
        need(type(case) is dict and set(case)=={'module','status','failure','finalizationFailures','cleanupErrorCount','cleanup'})
        need(case['module']==module and type(case['status']) is str and case['status'] in ('passed','failed'))
        if case['failure'] is not None:error(case['failure'])
        need(type(case['finalizationFailures']) is list and len(case['finalizationFailures'])<=2)
        for value in case['finalizationFailures']:error(value)
        need(uint32(case['cleanupErrorCount']))
        cleanup=case['cleanup']
        need(type(cleanup) is dict and set(cleanup)=={'gracefulQualified','forcedTermination','jobEmptyVerified','launcherExitCode','errors','errorsTruncated'})
        for key in ('gracefulQualified','forcedTermination','jobEmptyVerified'):
            need(cleanup[key] is None or type(cleanup[key]) is bool)
        need(cleanup['launcherExitCode'] is None or uint32(cleanup['launcherExitCode']))
        need(type(cleanup['errors']) is list and len(cleanup['errors'])<=16 and type(cleanup['errorsTruncated']) is bool)
        need(not cleanup['errorsTruncated'] or len(cleanup['errors'])==16)
        for value in cleanup['errors']:error(value)
    need(row['passed']==all(case['status']=='passed' for case in row['cases']))
    return row


def plain(path):
    leaf=None
    for item in (path,*path.parents):
        info=item.lstat()
        need(not stat.S_ISLNK(info.st_mode) and not (getattr(info,'st_file_attributes',0)&0x400))
        if leaf is None:leaf=info
    return leaf


def identity(info):return (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns)


def read_summary(path):
    selected=plain(path)
    need(stat.S_ISREG(selected.st_mode) and 0<selected.st_size<=MAX_BYTES)
    with path.open('rb') as stream:
        before=os.fstat(stream.fileno())
        need(stat.S_ISREG(before.st_mode) and identity(selected)==identity(before))
        raw=stream.read(MAX_BYTES+1)
        need(len(raw)==before.st_size and len(raw)<=MAX_BYTES and stream.read(1)==b'')
        after=os.fstat(stream.fileno())
        current=plain(path)
        need(stat.S_ISREG(current.st_mode) and
             identity(selected)==identity(before)==identity(after)==identity(current))
    validate_bytes(raw)
    return raw


def words(hexadecimal):return [int(hexadecimal[i:i+8],16) for i in range(0,len(hexadecimal),8)]


def binding(env,architecture,ordinal,raw):
    required={'GITHUB_ACTIONS':'true','RUNNER_ENVIRONMENT':'github-hosted','RUNNER_OS':'Windows',
              'GITHUB_REPOSITORY':'ATLKR/OpenGeul','GITHUB_JOB':'windows-suite'}
    need(all(env.get(key)==value for key,value in required.items()))
    source=env.get('GITHUB_SHA');run=env.get('GITHUB_RUN_ID');attempt=env.get('GITHUB_RUN_ATTEMPT')
    need(type(source) is str and re.fullmatch('[0-9a-f]{40}',source) is not None)
    need(type(run) is str and re.fullmatch('[1-9][0-9]{0,19}',run) is not None and int(run)<2**64)
    need(type(attempt) is str and re.fullmatch('[1-9][0-9]{0,9}',attempt) is not None and int(attempt)<2**32)
    need(architecture in ('x64','arm64'))
    # These are declared CI metadata, not checkout or source authority proof.
    return {'schemaVersion':1,'diagnosticOnly':1,'acceptanceEligible':0,'sourceBindingKindCode':1,
        'sourceCommitWords':words(source),'runId':int(run),'attempt':int(attempt),
        'architectureCode':{'x64':1,'arm64':2}[architecture],'ordinal':ordinal,
        'summaryBytes':len(raw),'summarySha256Words':words(hashlib.sha256(raw).hexdigest()),
        'summaryValidated':1,'sourceAuthorityQualified':0,'checkoutVerified':0,
        'productInputVerified':0,'sourceQualified':0,'storeQualified':0}


def publish(root,ordinal,architecture,env):
    need(type(ordinal) is int and ordinal in (1,2))
    root=Path(root).absolute()
    raw=read_summary(root/SOURCES[ordinal-1])
    receipt=binding(env,architecture,ordinal,raw)
    output=root/OUTPUTS[ordinal-1]
    plain(output.parent)
    output.mkdir()  # Exclusive: preserve stale/partial evidence and reject reuse.
    plain(output)
    with (output/'engine-failure-summary.json').open('xb') as stream:stream.write(raw)
    encoded=json.dumps(receipt,separators=(',',':'),allow_nan=False).encode('ascii')+b'\n'
    need(len(encoded)<=4096)
    with (output/'binding.numeric.json').open('xb') as stream:stream.write(encoded)
    return receipt


def main(argv=None):
    try:
        args=sys.argv[1:] if argv is None else argv
        need(len(args)==4 and args[0]=='--ordinal' and args[1] in ('1','2') and
             args[2]=='--architecture' and args[3] in ('x64','arm64'))
        receipt=publish(Path(__file__).resolve().parents[2],int(args[1]),args[3],os.environ)
        print(json.dumps(receipt,separators=(',',':'),allow_nan=False))
        return 0
    except (ValueError,TypeError):code=1
    except OSError:code=2
    except BaseException:code=3
    print(json.dumps({'schemaVersion':1,'diagnosticOnly':1,'acceptanceEligible':0,'errorCode':code},separators=(',',':')))
    return 1


if __name__=='__main__':raise SystemExit(main())
