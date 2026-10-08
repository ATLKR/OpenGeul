"""Pure validation of observed Windows JOB_INFO_2 and per-job A4 settings.

PRINTED means delivery through this virtual driver, not physical output. Both
PDF geometry/raster inspection and this completed-spooler check are required.
Constants follow https://learn.microsoft.com/en-us/windows/win32/printdocs/job-info-2.
This specific Microsoft virtual driver reports page counts; zero/unknown counts
are not accepted as completed evidence for this narrowly scoped test.
"""
REQUIRED_CASES = ('table--300','table-0','table-600','multipage','basic-hwp','basic-hwpx','page-range','cancel')
PRINTED = 0x80
ERROR_FLAGS = 0x1 | 0x2 | 0x4 | 0x20 | 0x40 | 0x100 | 0x200 | 0x400
ACTIVE_FLAGS = 0x8 | 0x10 | 0x800


def validate_cases(cases: list[dict]) -> None:
    names = [c.get('name') for c in cases]
    if len(names) != len(REQUIRED_CASES) or set(names) != set(REQUIRED_CASES):
        raise ValueError('Every required print scenario must appear exactly once')


def completed_job(jobs: list[dict], queue: str, document: str, pages: int, media: dict) -> dict | None:
    if type(pages) is not int or not 1 <= pages <= 6: raise ValueError('Invalid expected page count')
    if not jobs: return None
    if len(jobs) != 1: raise ValueError('Expected exactly one owned spooler job')
    job = jobs[0]
    if (job.get('pPrinterName') != queue or type(job.get('JobId')) is not int or job['JobId'] <= 0
            or job.get('pDocument') not in {document, document+' - HOP', document+' - OpenGeul'}):
        raise ValueError('Spooler job does not belong to this print scenario')
    if job.get('pStatus') not in (None, '', 'Printed'):
        raise ValueError('Spooler reports a non-success textual status')
    status = job.get('Status')
    if type(status) is not int or status < 0: raise ValueError('Invalid spooler status')
    if status & ERROR_FLAGS: raise ValueError(f'Spooler error/paused/deleting status: {status}')
    if not status & PRINTED or status & ACTIVE_FLAGS: return None
    for field in ('TotalPages','PagesPrinted'):
        if type(job.get(field)) is not int or job[field] != pages:
            raise ValueError(f'Incorrect completed-spooler {field}: {job.get(field)} != {pages}')
    for field, expected in (('PaperSize',9),('PaperLength',2970),('PaperWidth',2100),('Orientation',1)):
        if type(media.get(field)) is not int or media[field] != expected:
            raise ValueError(f'Actual spooler media does not match A4 portrait: {field}')
    return job
