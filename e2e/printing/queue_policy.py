"""Fail-closed policy for disposable, owned Microsoft PDF queues only."""
import re

def validate_environment(env):
    if (env.get('GITHUB_ACTIONS'),env.get('RUNNER_ENVIRONMENT'),env.get('RUNNER_OS')) != ('true','github-hosted','Windows'):
        raise ValueError('Printer provisioning is restricted to disposable GitHub-hosted Windows runners')
    run=env.get('GITHUB_RUN_ID','')
    if not re.fullmatch(r'[0-9]{1,15}',run):raise ValueError('Invalid run ID')
    return 'OpenGeul-E2E-'+run

def validate_queue(record,name):
    if record.get('pPrinterName')!=name or not name.startswith('OpenGeul-E2E-'):
        raise ValueError('Not the owned test queue')
    if record.get('pDriverName')!='Microsoft Print To PDF' or record.get('pPortName')!='PORTPROMPT:':
        raise ValueError('Only the inbox PDF driver on the local prompt port is allowed')
    return True

def completed_job(jobs,previous):
    new=[j for j in jobs if j['JobId'] not in previous]
    if len(new)>1:raise AssertionError('Unexpected extra print jobs')
    if not new:return None
    status=new[0]['Status']
    if status & (2|64|512|1024):raise AssertionError(f'Print job failed: {status}')
    return new[0] if status & (128|4096) else None
