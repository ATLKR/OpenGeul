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

def queue_definition(name):
    if not re.fullmatch(r'OpenGeul-E2E-[0-9]{1,15}',name):raise ValueError('Invalid owned queue name')
    # pywin32 requires the complete PRINTER_INFO_2 mapping, including nullable fields.
    return {'pServerName':None,'pPrinterName':name,'pShareName':None,'pPortName':'PORTPROMPT:',
        'pDriverName':'Microsoft Print To PDF','pComment':'OpenGeul synthetic CI output only',
        'pLocation':None,'pDevMode':None,'pSepFile':None,'pPrintProcessor':'winprint',
        'pDatatype':'RAW','pParameters':None,'pSecurityDescriptor':None,'Attributes':0x140,
        'Priority':1,'DefaultPriority':1,'StartTime':0,'UntilTime':0,'Status':0,'cJobs':0,'AveragePPM':0}
