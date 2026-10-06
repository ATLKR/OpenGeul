"""Own only one disposable Microsoft virtual queue; never select hardware."""
from __future__ import annotations
import os,re,subprocess,uuid
DRIVER='Microsoft Print To PDF'
PORT='PORTPROMPT:'
def require_host(env=None,platform=None):
    env=os.environ if env is None else env;platform=os.name if platform is None else platform
    if platform!='nt' or env.get('GITHUB_ACTIONS')!='true' or env.get('RUNNER_ENVIRONMENT')!='github-hosted':raise RuntimeError('Virtual-print E2E may only change disposable GitHub-hosted Windows runners')
def validate_queue(info,name):
    if not re.fullmatch(r'OpenGeul-CI-[0-9a-f]{32}',name):raise ValueError('Invalid owned queue name')
    if info.get('pPrinterName')!=name or info.get('pDriverName','').casefold()!=DRIVER.casefold() or info.get('pPortName')!=PORT:raise ValueError('Refusing a queue outside the owned local Microsoft PDF printer')
class VirtualQueue:
    def __init__(self):
        require_host()
        import win32print
        self.api=win32print;self.name='OpenGeul-CI-'+uuid.uuid4().hex;self.handle=None;self.created=False
    def __enter__(self):
        try:
            command="""$ErrorActionPreference='Stop'
if(Get-Printer -Name $env:OG_PRINT_QUEUE -ErrorAction SilentlyContinue){throw 'Queue collision'}
$driver=Get-PrinterDriver -Name 'Microsoft Print To PDF' -ErrorAction Stop
Add-Printer -Name $env:OG_PRINT_QUEUE -DriverName $driver.Name -PortName 'PORTPROMPT:' -KeepPrintedJobs
"""
            subprocess.run(['pwsh','-NoProfile','-NonInteractive','-Command',command],env={**os.environ,'OG_PRINT_QUEUE':self.name},check=True,timeout=45)
            self.created=True;self.handle=self.api.OpenPrinter(self.name,{'DesiredAccess':self.api.PRINTER_ALL_ACCESS})
            validate_queue(self.api.GetPrinter(self.handle,2),self.name)
            if self.jobs():raise RuntimeError('Fresh queue unexpectedly contains jobs')
            return self
        except BaseException:self.close();raise
    def jobs(self):
        validate_queue(self.api.GetPrinter(self.handle,2),self.name)
        return self.api.EnumJobs(self.handle,0,32,2)
    def close(self):
        if self.created:
            if self.handle is None:self.handle=self.api.OpenPrinter(self.name,{'DesiredAccess':self.api.PRINTER_ALL_ACCESS})
            try:
                validate_queue(self.api.GetPrinter(self.handle,2),self.name)
                for job in self.jobs():self.api.SetJob(self.handle,job['JobId'],0,None,self.api.JOB_CONTROL_DELETE)
                self.api.DeletePrinter(self.handle)
            finally:self.api.ClosePrinter(self.handle);self.handle=None;self.created=False
    def __exit__(self,*args):self.close()
