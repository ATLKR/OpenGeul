"""Five generated Windows engine PDF exports, independently verified with pypdf.

Two explicit processes keep pypdf out of the product payload:
  Office/program/python.exe pdf_export_smoke.py --produce --suite SUITE --output FRESH
  TOOLING/python.exe pdf_export_smoke.py --verify --suite SUITE --output FRESH

Install the pinned pure-Python wheel in the E2E tooling environment only, with
pip --require-hashes and the PYPDF_WHEEL_SHA256 below. This checks engine PDF
export only; it makes no GUI or physical printing claim. Never pass user files.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import re
import stat
import sys
import time
import traceback
import unicodedata

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import engine_smoke as baseline

PYPDF_VERSION = '6.21.0'
PYPDF_WHEEL_SHA256 = '3aec619699dacb1b73f57e87d9adaa4424814517b2cc028de20adba5a37af4c4'
PYPDF_METADATA = 'https://pypi.org/pypi/pypdf/6.21.0/json'
PRODUCTION_REPORT = 'pdf-production.json'
VERIFICATION_REPORT = 'pdf-verification.json'
FONT = 'Malgun Gothic'
MAX_PDF_BYTES = 20 * 1024 * 1024
FORMATS = (('writer', 'odt', 'writer8', 2), ('calc', 'ods', 'calc8', 1),
           ('impress', 'odp', 'impress8', 2), ('draw', 'odg', 'draw8', 1),
           ('math', 'odf', 'math8', 1))


def case_specs():
    return [dict(module=module, extension=extension, sourceFilter=source_filter,
                 filter=module + '_pdf_Export', pageCount=count,
                 pageMarkers=[['OPENGEULPDF' + module.upper() + str(page), '한글검증' + str(page)]
                              for page in range(1, count + 1)])
            for module, extension, source_filter, count in FORMATS]


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _error(exc):
    result = dict(type=type(exc).__name__, message=str(exc), traceback=traceback.format_exc())
    if hasattr(exc, 'job_census'):
        result['jobCensus'] = exc.job_census
    return result


def _unlinked(path):
    for item in [path] + list(path.parents):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        _require(not stat.S_ISLNK(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400,
                 'Linked evidence or payload ancestors are not accepted: ' + str(item))


def _paths(suite, output, create=False):
    for path in (suite, output):
        _require(not str(path).startswith(('\\\\', '//')), 'Only local payload/evidence paths are accepted')
        _unlinked(path)
    suite, output = suite.resolve(), output.resolve()
    _require(suite != output and suite not in output.parents, 'Evidence must be outside the Suite payload')
    if create:
        _require(suite.is_dir(), 'Packaged Suite directory is missing')
        output.mkdir(parents=True, exist_ok=False)
        (output / 'exports').mkdir()
        (output / 'sources').mkdir()
    else:
        _require(output.is_dir(), 'Owned PDF production output is missing')
    return suite, output


def _read(path, limit=MAX_PDF_BYTES):
    _unlinked(path)
    before = path.lstat()
    _require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= limit, 'Expected a bounded nonempty regular file: ' + str(path))
    data = path.read_bytes()
    after = path.lstat()
    _require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
             (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns), 'Evidence changed while reading')
    return data


def _image(path):
    return os.path.normcase(str(Path(path).resolve()))


def _engine_identity(suite):
    from writer_style_smoke import _packaged_identity_file
    inventory_file, data = _packaged_identity_file(suite, 'suite-inventory.json')
    inventory = json.loads(data)
    _require(inventory.get('schemaVersion') == 1, 'Engine inventory schema is missing')
    files = {}
    for relative in ('Office/program/soffice.exe', 'Office/program/soffice.bin'):
        observed, _ = _packaged_identity_file(suite, relative)
        expected = inventory.get('files', {}).get(relative, {})
        _require(type(expected.get('size')) is int and expected['size'] > 0
                 and observed['size'] == expected['size'] and observed['sha256'] == expected.get('sha256'),
                 'Packaged engine bytes differ from inventory: ' + relative)
        files[relative] = observed
    return dict(schemaVersion=1, inventorySha256=inventory_file['sha256'], files=files)


def _validate_job_evidence(suite, evidence):
    _require(isinstance(evidence, dict) and type(evidence.get('jobHandleValue')) is int
             and evidence['jobHandleValue'] > 0 and evidence.get('jobEmptyVerified') is True
             and evidence.get('finalJobPids') == [], 'Private engine job exit is unverified')
    initial, final = evidence.get('initial', []), evidence.get('final', [])
    expected = _image(suite / 'Office/program/soffice.bin')
    _require(any(isinstance(row.get('image'), str) and _image(row['image']) == expected
                 and row.get('alive') is True for row in initial), 'Owned UNO engine image differs from the exact packaged engine image')
    def identities(rows):
        result = set()
        for row in rows:
            _require(not row.get('error') and type(row.get('pid')) is int and row['pid'] > 0
                     and type(row.get('creationTime')) is int and row['creationTime'] > 0
                     and isinstance(row.get('image'), str) and type(row.get('alive')) is bool
                     and type(row.get('exitCode')) is int, 'Retained owned member identity/state is incomplete')
            result.add((row['pid'], row['creationTime'], _image(row['image'])))
        _require(len(result) == len(rows), 'Duplicate retained owned process identity')
        return result
    _require(identities(initial) <= identities(final) and all(row['alive'] is False for row in final),
             'Owned engine member generation changed or remained alive')


class Engine(baseline.Engine):
    """Retain the private job until every child exits, before deleting its profile."""
    def __init__(self, suite):
        super().__init__(suite)
        self.witness = None
        self.owned_job_evidence = dict(jobEmptyVerified=False)

    def _capture(self):
        if self.witness is None:
            self.witness = self.process.open_diagnostic_witnesses()
            self.owned_job_evidence['jobHandleValue'] = int(self.process.job)
        rows = self.witness.snapshot()
        _require(all(not row.get('error') and type(row.get('alive')) is bool for row in rows),
                 'Retained private-job member observation failed')
        self.owned_job_evidence.setdefault('initial', rows)
        return rows

    def start(self):
        super().start()
        rows = self._capture()
        expected = _image(self.runtime / 'program/soffice.bin')
        _require(any(_image(row['image']) == expected and row['alive'] for row in rows),
                 'Owned UNO engine image differs from the packaged engine image')

    def _empty(self, timeout):
        deadline = time.monotonic() + timeout
        # Each pass discovers members created before termination. The entire
        # wait shares one deadline; the census is bounded by the reused helper.
        for attempt in range(3):
            rows = self._capture()
            pids = self.witness.api.job_pids(self.process.job)
            self.owned_job_evidence.update(final=rows, finalJobPids=pids)
            if not pids and all(row['alive'] is False for row in rows):
                self.owned_job_evidence['jobEmptyVerified'] = True
                return True
            for handle, identity in self.witness.members.values():
                remaining = max(0, int((deadline - time.monotonic()) * 1000))
                waited = self.witness.api.wait_for(handle, remaining)
                _require(waited in (0, 258), 'Retained owned process wait failed')
            if time.monotonic() >= deadline:
                break
        rows = self._capture()
        pids = self.witness.api.job_pids(self.process.job)
        self.owned_job_evidence.update(final=rows, finalJobPids=pids)
        empty = not pids and all(row['alive'] is False for row in rows)
        self.owned_job_evidence['jobEmptyVerified'] = empty
        return empty

    def cleanup(self):
        dead = self.process is None
        if self.desktop is not None:
            try:
                self.desktop.terminate()
            except Exception as exc:
                self.cleanup_errors.append('desktop termination: ' + str(exc))
        if self.process is not None:
            try:
                dead = self._empty(5)
                self.owned_job_evidence['shutdown'] = 'graceful' if dead else 'forced-private-job-termination'
                if not dead:
                    self.process.terminate()  # Only the job created by Engine.start.
                    dead = self._empty(5)
                _require(dead, 'Private Office job or retained child remained alive')
            except Exception as exc:
                self.cleanup_errors.append('owned job cleanup: ' + str(exc))
                try:
                    self.process.terminate()
                    dead = self._empty(5)
                except Exception as later:
                    self.cleanup_errors.append('owned job final termination: ' + str(later))
            if dead:
                try:
                    self.process.close()
                except Exception as exc:
                    self.cleanup_errors.append('owned job handle close: ' + str(exc))
        if self.profile is not None:
            if dead:
                try:
                    self.profile.cleanup()
                except Exception as exc:
                    self.cleanup_errors.append('private profile removal: ' + str(exc))
            else:
                self.cleanup_errors.append('Kept unproved private profile and job: ' + self.profile.name)
        if self.witness is not None:
            try:
                self.witness.close()
            except Exception as exc:
                self.cleanup_errors.append('retained member handle close: ' + str(exc))


def _write(path, value, replace=False):
    target = path.with_name(path.name + '.pending') if replace else path
    with target.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    if replace:
        os.replace(target, path)  # Only the report created by this invocation.


def _normal(text):
    return ''.join(unicodedata.normalize('NFC', text).split())


def _reader():
    import pypdf
    _require(pypdf.__version__ == PYPDF_VERSION, 'E2E verifier requires exactly pypdf==' + PYPDF_VERSION)
    return pypdf.PdfReader


def verify_exports(output, production):
    """Parse actual page streams; producer expectations never choose the oracle."""
    report = dict(schemaVersion=1, kind='engine-pdf-export-verification', passed=False,
                  guiVerified=False, physicalPrintingVerified=False, cases=[],
                  verifier=dict(package='pypdf', version=PYPDF_VERSION,
                                wheelSha256=PYPDF_WHEEL_SHA256, metadataUrl=PYPDF_METADATA))
    try:
        _require(production.get('schemaVersion') == 1 and production.get('kind') == 'engine-pdf-export-production'
                 and production.get('passed') is True and production.get('guiVerified') is False
                 and production.get('physicalPrintingVerified') is False and not production.get('error'),
                 'Complete successful engine-only production is required')
        specs, records = case_specs(), production.get('cases')
        _require(isinstance(records, list) and [row.get('module') for row in records] == [case['module'] for case in specs],
                 'Exactly five canonical cases are required; duplicate, missing, unknown or reordered cases fail')
        reader = _reader()
        for case, produced in zip(specs, records):
            row = dict(module=case['module'], status='failed', expected=case)
            report['cases'].append(row)
            try:
                relative = 'exports/' + case['module'] + '.pdf'
                _require(produced.get('status') == 'passed' and produced.get('ownedEngineClosed') is True
                         and produced.get('filter') == case['filter'] and produced.get('expected') == case
                         and produced.get('relativePath') == relative and not produced.get('error')
                         and not produced.get('cleanupErrors') and produced.get('guiVerified') is False
                         and produced.get('physicalPrintingVerified') is False, 'Fixed case contract or owned engine cleanup is unverified')
                data = _read(Path(output) / relative)
                digest = hashlib.sha256(data).hexdigest()
                _require(type(produced.get('bytes')) is int and produced['bytes'] == len(data)
                         and isinstance(produced.get('sha256'), str) and re.fullmatch('[a-f0-9]{64}', produced['sha256'])
                         and produced['sha256'] == digest, 'PDF bytes differ from the closed engine production hash')
                row.update(sha256=digest, bytes=len(data), relativePath=relative)
                _require(data.startswith(b'%PDF-'), 'PDF header is missing')
                pdf = reader(BytesIO(data), strict=True)
                _require(not pdf.is_encrypted, 'Generated PDF must not be encrypted')
                row['pageCount'] = len(pdf.pages)
                _require(row['pageCount'] == case['pageCount'], 'PDF page count differs from the deliberate fixture pagination')
                row['pageText'] = [page.extract_text() or '' for page in pdf.pages]
                normalized = [_normal(text) for text in row['pageText']]
                _require(all(len(text) <= 100000 for text in normalized), 'Extracted PDF text exceeds the bounded fixture')
                for index, markers in enumerate(case['pageMarkers']):
                    for marker in markers:
                        _require(normalized[index].count(_normal(marker)) == 1,
                                 'PDF page ' + str(index + 1) + ' marker is missing or duplicated: ' + marker)
                        _require(all(_normal(marker) not in text for page, text in enumerate(normalized) if page != index),
                                 'PDF marker appeared on the wrong page: ' + marker)
                row['status'] = 'passed'
            except Exception as exc:
                row['error'] = _error(exc)
        report['passed'] = len(report['cases']) == 5 and all(row['status'] == 'passed' for row in report['cases'])
    except Exception as exc:
        report['error'] = _error(exc)
    return report


def _verify_identity(suite, production):
    from writer_style_smoke import require_packaged_python
    _require(production.get('suite') == str(suite), 'Producer described another Suite payload')
    identity = production.get('pythonIdentity', {})
    actual = require_packaged_python(suite, identity.get('observed', {}))
    _require(actual == identity, 'Packaged producer Python identity changed')
    _require(_engine_identity(suite) == production.get('engineIdentity'), 'Packaged engine inventory identity changed')
    _require(hashlib.sha256(_read(suite / 'suite-product.json')).hexdigest() == production.get('productSha256'),
             'Packaged Suite manifest changed after production')
    for record in production.get('cases', []):
        _validate_job_evidence(suite, record.get('ownedJobEvidence'))


def _interaction_handler():
    from dispatch import make_interaction_handler
    return make_interaction_handler()


def _require_font(engine):
    device = engine.service('com.sun.star.awt.Toolkit').createScreenCompatibleDevice(1, 1)
    _require(any(font.Name.casefold() == FONT.casefold() for font in device.getFontDescriptors()),
             'Required Korean fixture font is missing: ' + FONT)


def _font(target):
    target.setPropertyValue('CharFontName', FONT)
    target.setPropertyValue('CharFontNameAsian', FONT)
    target.setPropertyValue('CharHeight', 14.0)
    target.setPropertyValue('CharHeightAsian', 14.0)


def _formula(case):
    return '"' + case['pageMarkers'][0][0] + '" newline "' + case['pageMarkers'][0][1] + '" newline a + b = 42'


def _populate(engine, case, document):
    module = case['module']
    if module == 'writer':
        text = document.getText()
        text.setString('\n'.join(' '.join(markers) for markers in case['pageMarkers']))
        cursor = text.createTextCursor()
        cursor.gotoEnd(True)
        _font(cursor)
        cursor.gotoStart(False)
        cursor.gotoNextParagraph(False)
        cursor.setPropertyValue('BreakType', engine.uno.Enum('com.sun.star.style.BreakType', 'PAGE_BEFORE'))
        style = document.getStyleFamilies().getByName('PageStyles').getByName('Standard')
        for name, value in [('Width', 21000), ('Height', 29700), ('LeftMargin', 2000), ('RightMargin', 2000),
                            ('TopMargin', 2000), ('BottomMargin', 2000)]:
            style.setPropertyValue(name, value)
    elif module == 'calc':
        sheets = document.getSheets()
        while sheets.getCount() > 1:
            sheets.removeByName(sheets.getElementNames()[-1])
        sheet = sheets.getByIndex(0)
        sheet.getCellRangeByName('A1').setString(case['pageMarkers'][0][0])
        sheet.getCellRangeByName('A2').setString(case['pageMarkers'][0][1])
        sheet.getCellRangeByName('B3').setValue(17)
        sheet.getCellRangeByName('C3').setValue(25)
        sheet.getCellRangeByName('D3').setFormula('=SUM(B3:C3)')
        area = sheet.getCellRangeByName('A1:D3')
        _font(area)
        sheet.getColumns().getByIndex(0).setPropertyValue('Width', 16000)
        sheet.setPrintAreas((area.getRangeAddress(),))
        style = document.getStyleFamilies().getByName('PageStyles').getByName(sheet.getPropertyValue('PageStyle'))
        style.setPropertyValue('ScaleToPagesX', 1)
        style.setPropertyValue('ScaleToPagesY', 1)
        document.calculateAll()
    elif module in ('impress', 'draw'):
        pages = document.getDrawPages()
        while pages.getCount() > 1:
            pages.remove(pages.getByIndex(pages.getCount() - 1))
        while pages.getCount() < case['pageCount']:
            pages.insertNewByIndex(pages.getCount())
        for index, markers in enumerate(case['pageMarkers']):
            page = pages.getByIndex(index)
            while page.getCount():
                page.remove(page.getByIndex(0))
            page.setPropertyValue('Width', 28000)
            page.setPropertyValue('Height', 21000)
            shape = baseline._shape(engine, document, page, 'com.sun.star.drawing.TextShape',
                                    '\n'.join(markers), (1500, 1500), (24000, 7000))
            cursor = shape.getText().createTextCursor()
            cursor.gotoEnd(True)
            _font(cursor)
    elif module == 'math':
        document.setPropertyValue('FontNameText', FONT)
        document.setPropertyValue('BaseFontHeight', 14)
        document.setPropertyValue('Formula', _formula(case))


def _validate_model(case, document):
    module = case['module']
    if module == 'writer':
        text = document.getText().getString()
    elif module == 'calc':
        document.calculateAll()
        sheet = document.getSheets().getByIndex(0)
        text = sheet.getCellRangeByName('A1').getString() + sheet.getCellRangeByName('A2').getString()
        _require(sheet.getCellRangeByName('D3').getFormula() == '=SUM(B3:C3)'
                 and sheet.getCellRangeByName('D3').getValue() == 42, 'Generated spreadsheet formula/result changed')
    elif module in ('impress', 'draw'):
        pages = document.getDrawPages()
        _require(pages.getCount() == case['pageCount'], 'Generated slide/drawing pagination changed')
        text = '\n'.join(pages.getByIndex(index).getByIndex(0).getString() for index in range(pages.getCount()))
    else:
        _require(_normal(document.getPropertyValue('Formula')) == _normal(_formula(case)), 'Generated Math formula changed')
        return
    for markers in case['pageMarkers']:
        for marker in markers:
            _require(_normal(marker) in _normal(text), 'Generated native source marker changed: ' + marker)


def run_case(suite, output, case):
    """Only fixed private sources are saved/reopened; storeToURL never owns the PDF."""
    record = dict(module=case['module'], filter=case['filter'], expected=case, status='failed',
                  guiVerified=False, physicalPrintingVerified=False, ownedEngineClosed=False,
                  relativePath='exports/' + case['module'] + '.pdf')
    engine, document = None, None
    started = time.monotonic()
    try:
        _require(case in case_specs(), 'Only the five reviewed generated PDF fixtures may run')
        source = output / 'sources' / (case['module'] + '.' + case['extension'])
        path = output / record['relativePath']
        for target in (source, path):
            _unlinked(target)
            _require(not target.exists(), 'Never overwrite an existing generated source/export')
        engine = Engine(suite)
        engine.start()
        _require_font(engine)
        document = engine.load(baseline.FACTORIES[case['module']])
        _populate(engine, case, document)
        _validate_model(case, document)
        engine.store_new(document, source, case['sourceFilter'])
        engine.close_document(document)
        document = None
        document = engine.load(source.as_uri())
        _validate_model(case, document)
        original_url = document.getURL()
        _require(original_url == source.as_uri(), 'Reopened source URL differs from the private fixture')
        options = [('ExportNotesPages', False), ('ExportOnlyNotesPages', False),
                   ('ExportHiddenSlides', False), ('SinglePageSheets', False)]
        document.storeToURL(path.as_uri(), (
            engine.prop('FilterName', case['filter']), engine.prop('Overwrite', False),
            engine.prop('FilterData', tuple(engine.prop(name, value) for name, value in options)),
            engine.prop('InteractionHandler', _interaction_handler())))
        _require(document.getURL() == original_url, 'PDF export replaced ownership of the private native source')
        record['status'] = 'passed'
    except Exception as exc:
        record['error'] = _error(exc)
    finally:
        if engine is not None:
            try:
                engine.close_document(document)
            except Exception as exc:
                engine.cleanup_errors.append('generated document close: ' + str(exc))
            try:
                engine.cleanup()
            except Exception as exc:
                engine.cleanup_errors.append('owned engine cleanup: ' + str(exc))
            if engine.cleanup_errors:
                record.update(status='failed', cleanupErrors=engine.cleanup_errors)
            else:
                record['ownedEngineClosed'] = True
            record['ownedJobEvidence'] = getattr(engine, 'owned_job_evidence', None)
        if record['status'] == 'passed':
            try:
                _validate_job_evidence(suite, record['ownedJobEvidence'])
                data = _read(path)
                _require(data.startswith(b'%PDF-'), 'Engine did not produce a PDF header')
                record.update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), source=str(source), configuredFont=FONT)
            except Exception as exc:
                record.update(status='failed', error=_error(exc))
        record['elapsedSeconds'] = round(time.monotonic() - started, 3)
    return record


def _produce(suite, output):
    report = dict(schemaVersion=1, kind='engine-pdf-export-production', suite=str(suite), passed=False,
                  guiVerified=False, physicalPrintingVerified=False, cases=[])
    _write(output / PRODUCTION_REPORT, report)
    try:
        _require(os.name == 'nt', 'Real packaged Windows PDF export is required; portable verification is not product proof')
        from writer_style_smoke import observe_packaged_python, require_packaged_python
        report['pythonIdentity'] = require_packaged_python(suite, observe_packaged_python())
        report['engineIdentity'] = _engine_identity(suite)
        manifest_data = _read(suite / 'suite-product.json')
        report['productSha256'] = hashlib.sha256(manifest_data).hexdigest()
        manifest = json.loads(manifest_data)
        _require(manifest.get('schemaVersion') == 1, 'A complete packaged Suite manifest is required')
        for case in case_specs():
            module = manifest.get('modules', {}).get(case['module'], {})
            _require(module.get('factory') == baseline.FACTORIES[case['module']]
                     and module.get('filters', {}).get(case['extension']) == case['sourceFilter'],
                     'Packaged module differs from the fixed generated source: ' + case['module'])
        for case in case_specs():
            record = run_case(suite, output, case)
            report['cases'].append(record)
            _write(output / ('pdf-' + case['module'] + '.json'), record)
            _write(output / PRODUCTION_REPORT, report, replace=True)
            print(case['module'] + ': ' + record['status'], flush=True)
        report['passed'] = len(report['cases']) == 5 and all(row['status'] == 'passed' for row in report['cases'])
    except Exception as exc:
        report['error'] = _error(exc)
        print(report['error']['type'] + ': ' + report['error']['message'], file=sys.stderr, flush=True)
    _write(output / PRODUCTION_REPORT, report, replace=True)
    return 0 if report['passed'] else 1


class _Tee:
    def __init__(self, terminal, log):
        self.terminal, self.log = terminal, log

    def write(self, value):
        self.terminal.write(value)
        self.log.write(value)
        self.flush()
        return len(value)

    def flush(self):
        self.terminal.flush()
        self.log.flush()


def _verify(suite, output):
    report = dict(schemaVersion=1, kind='engine-pdf-export-verification', passed=False,
                  guiVerified=False, physicalPrintingVerified=False, cases=[])
    try:
        data = _read(output / PRODUCTION_REPORT)
        report['productionReportSha256'] = hashlib.sha256(data).hexdigest()
        production = json.loads(data)
        identity_error = None
        try:
            _verify_identity(suite, production)
        except Exception as exc:
            identity_error = _error(exc)
        report.update(verify_exports(output, production))
        report['identityVerified'] = identity_error is None
        if identity_error is not None:
            report.update(passed=False, identityError=identity_error)
        report['pythonIdentity'] = production.get('pythonIdentity')
        report['engineIdentity'] = production.get('engineIdentity')
        report['suite'] = str(suite)
    except Exception as exc:
        report['error'] = _error(exc)
    for row in report['cases']:
        print(row['module'] + ': ' + row['status'], flush=True)
    if report.get('error'):
        print(report['error']['type'] + ': ' + report['error']['message'], file=sys.stderr, flush=True)
    if report.get('identityError'):
        print(report['identityError']['type'] + ': ' + report['identityError']['message'], file=sys.stderr, flush=True)
    _write(output / VERIFICATION_REPORT, report)
    return 0 if report['passed'] else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--produce', action='store_true')
    mode.add_argument('--verify', action='store_true')
    parser.add_argument('--suite', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        _require(__debug__, 'Do not disable imported packaged identity assertions with Python -O')
        suite, output = _paths(args.suite, args.output, create=args.produce)
        name = PRODUCTION_REPORT if args.produce else VERIFICATION_REPORT
        _require(not (output / name).exists(), 'Evidence already exists; never overwrite a prior run')
        log_name = 'pdf-production.log' if args.produce else 'pdf-verification.log'
        with (output / log_name).open('x', encoding='utf-8', newline='\n') as log:
            with redirect_stdout(_Tee(sys.stdout, log)), redirect_stderr(_Tee(sys.stderr, log)):
                return _produce(suite, output) if args.produce else _verify(suite, output)
    except Exception as exc:
        print(type(exc).__name__ + ': ' + str(exc), file=sys.stderr, flush=True)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
