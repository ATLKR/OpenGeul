"""A private, retained-job PDF printer queue on disposable hosted Windows only."""
import os
import uuid


def require_host(environment):
    if environment.get('GITHUB_ACTIONS') != 'true' or environment.get('RUNNER_ENVIRONMENT') != 'github-hosted' or environment.get('RUNNER_OS') != 'Windows':
        raise RuntimeError('Virtual printer setup is restricted to disposable GitHub-hosted Windows runners')


class VirtualPrinter:
    def __init__(self, *, landscape=False):
        require_host(os.environ)
        import win32print
        self.api = win32print
        self.name = 'OpenGeul E2E PDF ' + uuid.uuid4().hex[:10]
        self.handle = None; self.previous = None; self.landscape = landscape

    def __enter__(self):
        api = self.api
        self.previous = api.GetDefaultPrinter()
        source = api.OpenPrinter('Microsoft Print to PDF')
        try: original = api.GetPrinter(source, 2)
        finally: api.ClosePrinter(source)
        if original['pDriverName'].lower() != 'microsoft print to pdf' or original['pPortName'] != 'PORTPROMPT:':
            raise RuntimeError('Expected inbox Microsoft PDF driver on PORTPROMPT:, not another printer')
        mode = original['pDevMode']
        mode.PaperSize = 9  # DMPAPER_A4
        mode.Orientation = 2 if self.landscape else 1
        mode.Fields |= 0x2 | 0x1  # DM_PAPERSIZE | DM_ORIENTATION
        try:
            self.handle = api.AddPrinter(None, 2, {'pPrinterName': self.name,
                'pPortName': 'PORTPROMPT:', 'pDriverName': original['pDriverName'],
                'pPrintProcessor': original['pPrintProcessor'], 'pDatatype': 'RAW', 'pDevMode': mode,
                'Attributes': api.PRINTER_ATTRIBUTE_LOCAL | api.PRINTER_ATTRIBUTE_KEEPPRINTEDJOBS})
            api.SetDefaultPrinter(self.name)
            if api.GetDefaultPrinter() != self.name: raise RuntimeError('Default printer did not select isolated queue')
            return self
        except BaseException:
            self.close(); raise

    def jobs(self):
        return [{key: item.get(key) for key in ('JobId', 'pDocument', 'Status', 'pStatus', 'TotalPages', 'PagesPrinted')}
                for item in self.api.EnumJobs(self.handle, 0, 100, 2)]

    def close(self):
        try:
            if self.previous: self.api.SetDefaultPrinter(self.previous)
        finally:
            if self.handle:
                handle, self.handle = self.handle, None
                try:
                    for item in self.api.EnumJobs(handle, 0, 100, 1):
                        self.api.SetJob(handle, item['JobId'], 0, None, self.api.JOB_CONTROL_DELETE)
                    self.api.DeletePrinter(handle)
                finally: self.api.ClosePrinter(handle)

    def __exit__(self, *args): self.close()
