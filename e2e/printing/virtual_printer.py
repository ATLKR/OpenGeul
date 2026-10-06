"""A disposable Windows spooler queue; never provision a real or network printer."""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import time
from queue_policy import validate_environment, validate_queue, completed_job

def default_printer(api):
    try:return api.GetDefaultPrinter()
    except RuntimeError as error:
        # pywin32 reports the documented no-default-printer case this way.
        if str(error) == 'The default printer was not found.':return None
        raise

class VirtualPrinter:
    def __init__(self,evidence:Path):
        self.name=validate_environment(os.environ)
        self.evidence=evidence;self.evidence.mkdir(parents=True,exist_ok=True)
        self.handle=None;self.previous=None
    def __enter__(self):
        import win32print as api
        self.api=api
        if any(p['pPrinterName']==self.name for p in api.EnumPrinters(2,None,2)):
            raise ValueError('Refusing to modify a pre-existing test queue')
        self.previous=default_printer(api)
        try:
            self.handle=api.AddPrinter(None,2,{'pPrinterName':self.name,'pPortName':'PORTPROMPT:',
                'pDriverName':'Microsoft Print To PDF','pPrintProcessor':'winprint','pDatatype':'RAW',
                'Attributes':0x40|0x100})
            validate_queue(api.GetPrinter(self.handle,2),self.name)
            subprocess.run(['pwsh','-NoProfile','-NonInteractive','-Command',
                "Set-PrintConfiguration -PrinterName '"+self.name+"' -PaperSize A4 -ErrorAction Stop"],check=True,timeout=30)
            # Select the isolated queue explicitly in the real print UI; do not require
            # or set a global default on runner accounts that start without one.
            (self.evidence/'printer.json').write_text(json.dumps({'name':self.name,'driver':'Microsoft Print To PDF',
                'port':'PORTPROMPT:','keepPrintedJobs':True,'previousDefault':self.previous},indent=2),encoding='utf-8')
            return self
        except BaseException:
            self.close();raise
    def jobs(self):
        validate_queue(self.api.GetPrinter(self.handle,2),self.name)
        return self.api.EnumJobs(self.handle,0,100,1)
    def ids(self):return {j['JobId'] for j in self.jobs()}
    def wait_printed(self,previous,timeout=30):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            value=completed_job(self.jobs(),previous)
            if value:
                result={k:value.get(k) for k in ('JobId','pPrinterName','pDocument','Status','TotalPages','PagesPrinted')}
                if result['pPrinterName']!=self.name:raise AssertionError('Unexpected spool target')
                return result
            time.sleep(.1)
        raise AssertionError('No completed spool job on the isolated printer queue')
    def close(self):
        if self.handle is None:return
        try:
            if default_printer(self.api)==self.name and self.previous:
                self.api.SetDefaultPrinter(self.previous)
            for job in self.jobs():self.api.SetJob(self.handle,job['JobId'],0,None,5)
            self.api.DeletePrinter(self.handle)
        finally:
            self.api.ClosePrinter(self.handle);self.handle=None
        if any(p['pPrinterName']==self.name for p in self.api.EnumPrinters(2,None,2)):
            raise AssertionError('Temporary print queue was not removed')
        if default_printer(self.api)!=self.previous:raise AssertionError('Default printer was not restored')
        (self.evidence/'cleanup.json').write_text(json.dumps({'removed':self.name,'restoredDefault':self.previous}),encoding='utf-8')
    def __exit__(self,*args):self.close()
