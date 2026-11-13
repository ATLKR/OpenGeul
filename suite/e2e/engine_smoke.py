"""Real Windows UNO round trips for generated OpenGeul Office fixtures.

Run with the packaged Office/program/python.exe. This is an engine test, not a
claim of GUI/IME validation. --verify-ui checks content after a separate GUI run.
"""
import sys

sys.dont_write_bytecode = True

import argparse
import hashlib
import json
import os
from pathlib import Path
import time
import traceback
import uuid

os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parent))
from base_read_lifetime import LifetimeTrace, call as lifetime_call, observe_database, resource_scope

FILES = {'writer': 'OpenGeul-writer.docx', 'calc': 'OpenGeul-calc.xlsx',
         'impress': 'OpenGeul-impress.pptx', 'draw': 'OpenGeul-draw.odg',
         'math': 'OpenGeul-math.odf', 'base': 'OpenGeul-base.odb'}
FACTORIES = {'writer': 'private:factory/swriter', 'calc': 'private:factory/scalc',
             'impress': 'private:factory/simpress', 'draw': 'private:factory/sdraw',
             'math': 'private:factory/smath', 'base': 'private:factory/sdatabase'}
UI_MODULES = ('writer', 'calc', 'impress')
FORMULA = 'sum from {i=1} to {4} i = 10'


def marker(module):
    return 'Engine-OpenGeul-' + module + ' 한글'


def fixture_path(output, module, must_exist=False):
    """Only the harness's fixed fixture names can be read or written."""
    folder = Path(output) / 'fixtures'
    path = folder / FILES[module]
    if folder.is_symlink() or path.is_symlink():
        raise ValueError('Fixture paths must not link to other documents')
    if path.resolve().parent != folder.resolve():
        raise ValueError('Fixture path escaped its owned directory')
    if must_exist and not path.is_file():
        raise ValueError('Generated fixture is missing: ' + str(path))
    return path.resolve()


def verify_content(module, observed, verify_ui=False):
    """Reject readable but semantically wrong round trips, including GUI no-ops."""
    if module in ('writer', 'calc', 'impress', 'draw'):
        text = observed.get('text', '')
        assert marker(module) in text, 'The persisted original marker is missing'
        if verify_ui and module in UI_MODULES:
            assert 'UI-OpenGeul-' + module in text, 'The GUI edit was not persisted'
    if module == 'calc':
        assert observed.get('formula') == '=SUM(B1:C1)', 'The spreadsheet formula was lost'
        assert observed.get('value') == 42, 'The spreadsheet formula result is wrong'
    elif module in ('impress', 'draw'):
        assert observed.get('pageCount') == 1, 'The generated page/slide count changed'
        if module == 'draw':
            assert observed.get('position') == [1000, 1000], 'The drawing shape moved'
            assert observed.get('size') == [6000, 2500], 'The drawing shape size changed'
    elif module == 'math':
        assert ''.join(observed.get('formula', '').split()) == ''.join(FORMULA.split()), 'The formula changed'
    elif module == 'base':
        assert observed.get('databaseUrl') == 'sdbc:embedded:firebird', 'The database is not embedded Firebird'
        assert observed.get('rows') == [{'id': 1, 'text': marker('base'), 'amount': 42}], 'The database row did not persist'
    elif module != 'writer':
        raise ValueError('Unknown test module: ' + module)


def validate_cleanup_evidence(evidence):
    """New qualification requires graceful exit of this job and retained members."""
    def require(condition, message):
        if not condition:
            raise ValueError(message)
    require(isinstance(evidence, dict) and evidence.get('schemaVersion') == 1
            and evidence.get('kind') == 'owned-engine-job-cleanup', 'Owned engine cleanup evidence is missing')
    require(evidence.get('gracefulQualified') is True and evidence.get('forcedTermination') is False
            and evidence.get('jobEmptyVerified') is True and evidence.get('finalJobPids') == []
            and evidence.get('launcherExitCode') == 0 and not evidence.get('errors'),
            'Graceful owned engine job exit is unverified')
    require(type(evidence.get('jobHandleValue')) is int and evidence['jobHandleValue'] > 0,
            'Original private engine job handle is missing')
    initial, final = evidence.get('initialMembers'), evidence.get('finalMembers')
    expected = evidence.get('expectedEngineImage')
    require(isinstance(initial, list) and initial and isinstance(final, list) and final
            and isinstance(expected, str) and expected, 'Actual owned engine observations are missing')
    image = lambda path: os.path.normcase(str(Path(path).resolve()))
    require(any(row.get('alive') is True and isinstance(row.get('image'), str)
                and image(row['image']) == image(expected) for row in initial),
            'Expected owned engine was not observed alive before shutdown')
    def identities(rows):
        result = set()
        for row in rows:
            require(not row.get('error') and all(type(row.get(key)) is int and row[key] > 0
                    for key in ('pid', 'creationTime', 'handleValue')) and isinstance(row.get('image'), str)
                    and type(row.get('alive')) is bool and type(row.get('exitCode')) is int,
                    'Retained owned member observation is incomplete')
            result.add((row['pid'], row['creationTime'], row['handleValue'], image(row['image'])))
        require(len(result) == len(rows), 'Duplicate retained member identity')
        return result
    require(identities(initial) <= identities(final)
            and all(row['alive'] is False and row['exitCode'] == 0 for row in final),
            'Retained member changed generation/handle, remained alive, or exited abnormally')
    return evidence


class Engine:
    """One private profile, named pipe and owned Windows job per test case."""
    def __init__(self, suite):
        self.suite = suite
        self.runtime = suite / 'Office'
        self.process = self.profile = self.desktop = self.uno = None
        self.cleanup_errors = []
        self._job_witness = None
        self.fixture_lifetime = None
        self.base_lifetime_enabled = False
        self.lifetime_diagnostics = LifetimeTrace()
        self.cleanup_evidence = dict(schemaVersion=1, kind='owned-engine-job-cleanup',
            expectedEngineImage=str(self.runtime / 'program/soffice.bin'), gracefulQualified=False,
            forcedTermination=False, jobEmptyVerified=False, initialMembers=[], finalMembers=[],
            finalJobPids=None, launcherExitCode=None, snapshots=[], errors=[],
            lifetimeDiagnostics=self.lifetime_diagnostics.receipt)

    def start(self):
        if os.name != 'nt':
            raise RuntimeError('This packaged UNO harness requires Windows; no Linux GUI proof is implied')
        program = self.runtime / 'program'
        if not all((program / name).is_file() for name in ('soffice.exe', 'python.exe')):
            raise RuntimeError('The packaged Windows GUI runtime is incomplete')
        worker = self.suite / 'worker'
        if not all((worker / name).is_file() for name in ('native.py', 'native_windows.py', 'session.py')):
            raise RuntimeError('The packaged worker implementation is missing')
        sys.path.insert(0, str(worker))
        import uno
        from native import PrivateProfile, connect_uno
        from native_windows import OwnedOfficeProcess
        self.uno = uno
        self.profile = PrivateProfile()
        pipe = 'OpenGeul_engine_smoke_' + uuid.uuid4().hex
        argv = [str(program / 'soffice.exe'), '--headless', '--nologo', '--nodefault',
                '--norestore', '--nofirststartwizard',
                '-env:UserInstallation=' + Path(self.profile.name).as_uri(),
                '--accept=pipe,name=' + pipe + ';urp;StarOffice.ServiceManager']
        self.process = OwnedOfficeProcess(argv, program)
        self.context = connect_uno(uno, pipe, self.process)
        self.desktop = self.service('com.sun.star.frame.Desktop')

    def service(self, name):
        return self.context.ServiceManager.createInstanceWithContext(name, self.context)

    def prop(self, name, value):
        prop = self.uno.createUnoStruct('com.sun.star.beans.PropertyValue')
        prop.Name, prop.Value = name, value
        return prop

    def load(self, url):
        # Every URL is either a manifest factory or our generated fixture path.
        from dispatch import make_interaction_handler
        props = tuple(self.prop(name, value) for name, value in (
            ('Hidden', True), ('ReadOnly', False), ('MacroExecutionMode', 0),
            ('UpdateDocMode', 0), ('PickListEntry', False), ('AsTemplate', False),
            ('InteractionHandler', make_interaction_handler())))
        document = self.desktop.loadComponentFromURL(url, '_blank', 0, props)
        if document is None:
            raise RuntimeError('The engine returned no document for ' + url)
        return document

    def store_new(self, document, path, filter_name):
        if path.exists():
            raise FileExistsError('A generated fixture already exists: ' + str(path))
        from dispatch import make_interaction_handler
        document.storeAsURL(path.as_uri(), (
            self.prop('FilterName', filter_name), self.prop('Overwrite', False),
            self.prop('InteractionHandler', make_interaction_handler())))
        if not path.is_file() or path.stat().st_size == 0:
            raise AssertionError('The engine did not create a nonempty saved file')

    def close_document(self, document):
        if document is not None:
            # Only generated test documents reach this helper.
            lease = getattr(self, 'fixture_lifetime', None)
            if lease is not None:
                lease.require_active()
            if self.base_lifetime_enabled:
                with resource_scope(self.lifetime_diagnostics) as own:
                    own('document.close', lambda: document.close(False))
                    lifetime_call(self.lifetime_diagnostics, 'document.setModified', lambda: document.setModified(False))
            elif lease is not None:
                self.lifetime_diagnostics.call('document.setModified', lambda: document.setModified(False))
                lease.require_active()
                self.lifetime_diagnostics.call('document.close', lambda: document.close(False))
            else:
                document.setModified(False)
                document.close(False)
            if lease is not None:
                lease.require_active()

    def acquire_fixture_lifetime(self):
        from fixture_desktop_lifetime import FixtureDesktopLease
        assert getattr(self, 'fixture_lifetime', None) is None, 'Fixture Desktop lifetime cannot restart'
        self.fixture_lifetime = FixtureDesktopLease(self.desktop, self.lifetime_diagnostics)
        self.cleanup_evidence['fixtureDesktopLifetime'] = self.fixture_lifetime.receipt
        self.fixture_lifetime.register()

    def _cleanup_error(self, stage, exc):
        self.cleanup_errors.append(stage + ': ' + type(exc).__name__ + ': ' + str(exc))
        self.cleanup_evidence['errors'].append(dict(stage=stage, type=type(exc).__name__,
            message=str(exc), winerror=getattr(exc, 'winerror', None), jobCensus=getattr(exc, 'job_census', None)))

    def _capture_members(self, phase):
        # Capture before requesting termination, including partial-start failures.
        # No handles are opened by start(), so existing Engine subclasses that
        # own their cleanup do not acquire extra hidden observer handles.
        if self._job_witness is None:
            self._job_witness = self.process.open_diagnostic_witnesses()
            self.cleanup_evidence['jobHandleValue'] = int(self.process.job)
        rows = self._job_witness.snapshot()
        handles = {pid: int(handle) for pid, (handle, identity) in self._job_witness.members.items()}
        rows = [dict(row, handleValue=handles.get(row.get('pid'))) for row in rows]
        self.cleanup_evidence['snapshots'].append(dict(phase=phase, members=rows))
        if any(row.get('error') or type(row.get('alive')) is not bool for row in rows):
            raise RuntimeError('Retained private-job member observation failed')
        if not self.cleanup_evidence['initialMembers']:
            self.cleanup_evidence['initialMembers'] = rows
        return rows

    def _wait_empty_job(self, phase, timeout=5):
        deadline = time.monotonic() + timeout
        # At most three discovery passes share one five-second wait budget.
        # Retained handles prove member exit; an independent empty census proves
        # no unobserved child remains in the still-open private job.
        for attempt in range(3):
            rows = self._capture_members(phase)
            pids = self._job_witness.api.job_pids(self.process.job)
            self.cleanup_evidence.update(finalMembers=rows, finalJobPids=pids)
            if not pids and all(row['alive'] is False for row in rows):
                self.cleanup_evidence['launcherExitCode'] = self.process.wait(timeout=0)
                self.cleanup_evidence['jobEmptyVerified'] = True
                return True
            for handle, identity in self._job_witness.members.values():
                remaining = max(0, int((deadline - time.monotonic()) * 1000))
                if self._job_witness.api.wait_for(handle, remaining) not in (0, 258):
                    raise RuntimeError('Retained owned process wait failed')
            if time.monotonic() >= deadline:
                break
        rows = self._capture_members(phase + '-final')
        pids = self._job_witness.api.job_pids(self.process.job)
        self.cleanup_evidence.update(finalMembers=rows, finalJobPids=pids)
        empty = not pids and all(row['alive'] is False for row in rows)
        if empty:
            self.cleanup_evidence['launcherExitCode'] = self.process.wait(timeout=0)
        self.cleanup_evidence['jobEmptyVerified'] = empty
        return empty

    def _force_owned_job(self):
        self.cleanup_evidence['forcedTermination'] = True
        self._cleanup_error('graceful engine exit', RuntimeError('Private Office job required forced termination; qualification failed'))
        self.process.terminate()  # Only the job created by this Engine.start().
        return self._wait_empty_job('forced-recovery')

    def cleanup(self):
        dead = self.process is None
        if self.process is not None:
            try:
                self._capture_members('before-desktop-termination')
            except Exception as exc:
                self._cleanup_error('retain owned members', exc)
        lease = getattr(self, 'fixture_lifetime', None)
        if lease is not None:
            try:
                lease.release()
            except Exception as exc:
                self._cleanup_error('fixture desktop lifetime release', exc)
        if self.desktop is not None:
            try:
                returned = self.lifetime_diagnostics.call('desktop.terminate', self.desktop.terminate, record_return=True)
                if type(returned) is not bool:
                    raise TypeError('Private desktop termination returned a non-boolean')
                if returned is False:
                    raise RuntimeError('Private desktop vetoed graceful termination')
            except Exception as exc:
                self._cleanup_error('desktop termination', exc)
        if self.process is not None:
            try:
                dead = self._wait_empty_job('graceful')
                if not dead:
                    dead = self._force_owned_job()
                if not dead:
                    raise RuntimeError('Owned job or retained child remained alive')
            except Exception as exc:
                self._cleanup_error('owned job exit', exc)
                if not self.cleanup_evidence['forcedTermination']:
                    try:
                        dead = self._force_owned_job()
                    except Exception as later:
                        self._cleanup_error('owned job recovery', later)
            if dead:
                try:
                    self.process.close()
                except Exception as exc:
                    self._cleanup_error('private job handle close', exc)
        if self.profile is not None:
            if dead:
                try:
                    self.profile.cleanup()
                except Exception as exc:
                    self._cleanup_error('private profile removal', exc)
            else:
                self._cleanup_error('private profile retained', RuntimeError('Kept unproved private profile/job: ' + self.profile.name))
        if self._job_witness is not None:
            try:
                self._job_witness.close()
            except Exception as exc:
                self._cleanup_error('retained member handle close', exc)
        try:
            self.lifetime_diagnostics.require_complete()
        except Exception as exc:
            self._cleanup_error('lifetime diagnostics', exc)
        if self.process is not None and dead and not self.cleanup_errors:
            self.cleanup_evidence['gracefulQualified'] = True
            try:
                validate_cleanup_evidence(self.cleanup_evidence)
            except Exception as exc:
                self.cleanup_evidence['gracefulQualified'] = False
                self._cleanup_error('graceful exit proof', exc)


def _shape(engine, document, page, service, text, position, size, *, fixed_text_frame=False):
    assert type(fixed_text_frame) is bool and (not fixed_text_frame or service == 'com.sun.star.drawing.TextShape'), \
        'Fixed generated frame requires an explicit boolean TextShape opt-in'
    shape = document.createInstance(service)
    if fixed_text_frame:
        # Keep the supplied fixture size stable when entering text edit.
        shape.setPropertyValue('TextAutoGrowHeight', False)
        shape.setPropertyValue('TextAutoGrowWidth', False)
        shape.setPropertyValue('TextFitToSize', engine.uno.Enum('com.sun.star.drawing.TextFitToSizeType', 'NONE'))
    point = engine.uno.createUnoStruct('com.sun.star.awt.Point')
    point.X, point.Y = position
    dimensions = engine.uno.createUnoStruct('com.sun.star.awt.Size')
    dimensions.Width, dimensions.Height = size
    shape.setPosition(point)
    shape.setSize(dimensions)
    page.add(shape)
    shape.setString(text)
    return shape


def populate(engine, module, document):
    if module == 'writer':
        document.getText().setString(marker(module) + '\n')
    elif module == 'calc':
        sheet = document.getSheets().getByIndex(0)
        sheet.setName('OpenGeul Smoke')
        sheet.getCellRangeByName('A1').setString(marker(module))
        sheet.getCellRangeByName('B1').setValue(17)
        sheet.getCellRangeByName('C1').setValue(25)
        sheet.getCellRangeByName('D1').setFormula('=SUM(B1:C1)')
        document.calculateAll()
    elif module in ('impress', 'draw'):
        pages = document.getDrawPages()
        while pages.getCount() > 1:
            pages.remove(pages.getByIndex(pages.getCount() - 1))
        page = pages.getByIndex(0)
        while page.getCount():
            page.remove(page.getByIndex(0))
        _shape(engine, document, page,
               'com.sun.star.drawing.TextShape' if module == 'impress' else 'com.sun.star.drawing.RectangleShape',
               marker(module), (2500, 2500) if module == 'impress' else (1000, 1000),
               (20000, 6000) if module == 'impress' else (6000, 2500),
               fixed_text_frame=(module == 'impress'))
    elif module == 'math':
        document.setPropertyValue('Formula', FORMULA)
    elif module == 'base':
        # XIsolatedConnection permits transaction control; pooled shared
        # connections deliberately reject setAutoCommit/commit/rollback.
        connection = document.DataSource.getIsolatedConnection('', '')
        try:
            connection.setAutoCommit(False)
            statement = connection.createStatement()
            # Firebird auto-commits DDL and disposes its statement handles.
            # executeUpdate would then query the disposed handle for a row
            # count. Use execute for DDL, and a fresh prepared DML statement.
            statement.execute('CREATE TABLE "OPENGEUL_SMOKE" '
                              '("ID" INTEGER NOT NULL PRIMARY KEY, "TEXT_VALUE" VARCHAR(128), "AMOUNT" INTEGER)')
            prepared = connection.prepareStatement('INSERT INTO "OPENGEUL_SMOKE" VALUES (?, ?, ?)')
            prepared.setInt(1, 1)
            prepared.setString(2, marker(module))
            prepared.setInt(3, 42)
            prepared.executeUpdate()
            connection.commit()
        finally:
            connection.close()


def observe(module, document, diagnostics=None):
    if module == 'writer':
        return {'text': document.getText().getString()}
    if module == 'calc':
        document.calculateAll()
        sheet = document.getSheets().getByIndex(0)
        return {'text': sheet.getCellRangeByName('A1').getString(),
                'formula': sheet.getCellRangeByName('D1').getFormula(),
                'value': sheet.getCellRangeByName('D1').getValue()}
    if module in ('impress', 'draw'):
        pages = document.getDrawPages()
        page = pages.getByIndex(0)
        texts = []
        for index in range(page.getCount()):
            shape = page.getByIndex(index)
            if hasattr(shape, 'getString'):
                texts.append(shape.getString())
        result = {'text': '\n'.join(texts), 'pageCount': pages.getCount(), 'shapeCount': page.getCount()}
        if module == 'draw':
            shape = page.getByIndex(0)
            position, size = shape.getPosition(), shape.getSize()
            result.update(position=[position.X, position.Y], size=[size.Width, size.Height])
        return result
    if module == 'math':
        return {'formula': document.getPropertyValue('Formula')}
    if module == 'base':
        return observe_database(document, diagnostics)
    raise ValueError('Unknown test module: ' + module)


def run_case(suite, output, module, specification, verify_ui=False):
    path = fixture_path(output, module, must_exist=verify_ui)
    result = {'module': module, 'status': 'failed', 'fixture': str(path), 'failureStage': None, 'finalizationFailures': [],
              'expected': {'marker': marker(module)} if module in ('writer', 'calc', 'impress', 'draw') else {}}
    if module == 'calc':
        result['expected'].update(formula='=SUM(B1:C1)', value=42)
    elif module in ('impress', 'draw'):
        result['expected']['pageCount'] = 1
        if module == 'draw':
            result['expected'].update(position=[1000, 1000], size=[6000, 2500])
    elif module == 'math':
        result['expected']['formula'] = FORMULA
    elif module == 'base':
        result['expected'].update(databaseUrl='sdbc:embedded:firebird',
                                  rows=[{'id': 1, 'text': marker('base'), 'amount': 42}])
    if verify_ui and module in UI_MODULES:
        result['expected']['uiSuffix'] = 'UI-OpenGeul-' + module
    engine = Engine(suite)
    engine.base_lifetime_enabled = module == 'base'
    diagnostics = getattr(engine, 'lifetime_diagnostics', None) if module == 'base' else None
    document = None
    started = time.monotonic()
    try:
        stage = 'engine-start'
        engine.start()
        stage = 'desktop-lease'
        engine.acquire_fixture_lifetime()
        from fixture_desktop_lifetime import require_fixture_members
        stage = 'owned-members'
        require_fixture_members(engine._capture_members('fixture-before-first-load'),
                                engine.cleanup_evidence['expectedEngineImage'])
        if verify_ui:
            stage = 'load-saved'
            document = engine.load(path.as_uri())
        else:
            if module == 'base':
                # Direct service creation avoids the interactive database wizard.
                stage = 'base-create'
                document = engine.service('com.sun.star.sdb.OfficeDatabaseDocument')
                stage = 'base-initialize'
                document.initNew()
                stage = 'base-configure'
                document.DataSource.setPropertyValue('URL', 'sdbc:embedded:firebird')
                stage = 'base-store-new'
                engine.store_new(document, path, specification['filters']['odb'])
            else:
                stage = 'load-factory'
                document = engine.load(specification['factory'])
            stage = 'populate'
            populate(engine, module, document)
            stage = 'verify-generated'
            verify_content(module, observe(module, document, diagnostics) if diagnostics is not None else observe(module, document))
            if module == 'base':
                stage = 'base-store'
                document.store()
            else:
                stage = 'store-new'
                extension = path.suffix.lstrip('.')
                engine.store_new(document, path, specification['filters'][extension])
            stage = 'close-before-reopen'
            engine.close_document(document)
            document = None
            stage = 'load-saved'
            document = engine.load(path.as_uri())
        stage = 'observe-saved'
        observed = observe(module, document, diagnostics) if diagnostics is not None else observe(module, document)
        stage = 'verify-saved'
        verify_content(module, observed, verify_ui)
        result.update(status='passed', observed=observed)
    except Exception as exc:
        result['failureStage'] = stage
        result['error'] = {'type': type(exc).__name__, 'message': str(exc),
                           'traceback': traceback.format_exc()}
    finally:
        try:
            engine.close_document(document)
        except Exception as exc:
            result['finalizationFailures'].append(dict(stage='final-document-close', type=type(exc).__name__))
            engine.cleanup_errors.append('generated document: ' + type(exc).__name__ + ': ' + str(exc))
        try: engine.cleanup()
        except Exception as exc:
            result['finalizationFailures'].append(dict(stage='engine-cleanup', type=type(exc).__name__))
            engine.cleanup_errors.append('owned cleanup: ' + type(exc).__name__ + ': ' + str(exc))
        result['engineCleanup'] = getattr(engine, 'cleanup_evidence', None)
        if engine.cleanup_errors:
            result['cleanupErrors'] = engine.cleanup_errors
            result['status'] = 'failed'
        if result['status'] == 'passed':
            try:
                stage = 'cleanup-proof'
                validate_cleanup_evidence(result['engineCleanup'])
                # Embedded Firebird persists its backup during disposal. Hash
                # only after model close and the owned process has exited.
                stage = 'final-file-read'
                final_bytes = path.read_bytes()
                result.update(sha256=hashlib.sha256(final_bytes).hexdigest(), bytes=len(final_bytes))
            except Exception as exc:
                result['failureStage'] = stage
                result['status'] = 'failed'
                result['error'] = {'type': type(exc).__name__, 'message': str(exc),
                                   'traceback': traceback.format_exc()}
        result['elapsedSeconds'] = round(time.monotonic() - started, 3)
    return result


# Closed metadata only: this receipt is safe to retain when full engine evidence
# is deliberately excluded from a bounded diagnostic artifact.
_FAILURE_STAGES = frozenset(('case-setup', 'engine-start', 'desktop-lease', 'owned-members',
    'load-saved', 'base-create', 'base-initialize', 'base-configure', 'base-store-new',
    'load-factory', 'populate', 'verify-generated', 'base-store', 'store-new',
    'close-before-reopen', 'observe-saved', 'verify-saved', 'cleanup-proof', 'final-file-read',
    'final-document-close', 'engine-cleanup', 'graceful engine exit', 'retain owned members',
    'fixture desktop lifetime release', 'desktop termination', 'owned job exit',
    'owned job recovery', 'private job handle close', 'private profile removal',
    'private profile retained', 'retained member handle close', 'lifetime diagnostics',
    'graceful exit proof'))
_ERROR_CATEGORIES = frozenset(('AssertionError', 'RuntimeError', 'ValueError', 'TypeError',
    'OSError', 'PermissionError', 'FileNotFoundError', 'FileExistsError', 'TimeoutError',
    'AttributeError', 'KeyError', 'DisposedException', 'IOException', 'CloseVetoException',
    'NoConnectException', 'IllegalArgumentException', 'DeploymentException'))


def failure_summary(results):
    assert [r['module'] for r in results] == list(FILES), 'Fixed six-module receipt required'
    def error(stage, value):
        return dict(stage=stage if stage in _FAILURE_STAGES else 'unknown',
                    category=value.get('type') if value.get('type') in _ERROR_CATEGORIES else 'unknown')
    cases = []
    for result in results:
        assert result['status'] in ('passed', 'failed')
        cleanup = result.get('engineCleanup') or {}
        errors = cleanup.get('errors') or []
        flags = {name: cleanup.get(name) if type(cleanup.get(name)) is bool else None
                 for name in ('gracefulQualified', 'forcedTermination', 'jobEmptyVerified')}
        code = cleanup.get('launcherExitCode')
        flags.update(launcherExitCode=code if type(code) is int and 0 <= code < 2**32 else None,
                     errors=[error(e.get('stage'), e) for e in errors[:16]], errorsTruncated=len(errors)>16)
        cases.append(dict(module=result['module'], status=result['status'],
            failure=error(result.get('failureStage'), result['error']) if result.get('error') else None,
            finalizationFailures=[error(e.get('stage'), e) for e in result.get('finalizationFailures', [])[:2]],
            cleanupErrorCount=len(result.get('cleanupErrors', [])), cleanup=flags))
    return dict(schemaVersion=1, kind='engine-failure-summary', acceptanceEligible=False,
                passed=all(r['status']=='passed' for r in results), cases=cases)


def write_json(path, value):
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--verify-ui', action='store_true', help='verify suffixes after separate actual GUI edits')
    args = parser.parse_args(argv)
    try:
        if not __debug__:
            raise RuntimeError('Do not disable the engine smoke assertions with Python -O')
        if args.suite.is_symlink() or args.output.is_symlink():
            raise ValueError('Suite/output directory links are not accepted')
        suite, output = args.suite.resolve(), args.output.resolve()
        if suite == output or suite in output.parents:
            raise ValueError('Evidence output must be outside the Suite payload')
        if str(suite).startswith(('\\\\', '//')) or str(output).startswith(('\\\\', '//')):
            raise ValueError('Use local Suite and evidence paths')
        manifest = json.loads((suite / 'suite-product.json').read_text(encoding='utf-8-sig'))
        modules = manifest['modules']
        if manifest.get('schemaVersion') != 1 or set(FILES) - set(modules):
            raise ValueError('The complete Suite manifest is required')
        for module, factory in FACTORIES.items():
            if modules[module].get('factory') != factory:
                raise ValueError('Only the fixed local factory for ' + module + ' can be tested')
        output.mkdir(parents=True, exist_ok=True)
        report_name = 'ui-engine-verification.json' if args.verify_ui else 'engine-smoke.json'
        if (output / report_name).exists():
            raise FileExistsError('Evidence already exists; use a fresh output directory')
        if args.verify_ui:
            baseline = json.loads((output / 'engine-smoke.json').read_text(encoding='utf-8'))
            passed = {case['module'] for case in baseline['cases'] if case['status'] == 'passed'}
            if not set(FILES) <= passed:
                raise ValueError('All six engine modules must pass before post-GUI verification')
        else:
            (output / 'fixtures').mkdir(exist_ok=False)
        results = []
        for module in FILES:
            try:
                result = run_case(suite, output, module, modules[module], args.verify_ui)
            except Exception as exc:
                result = {'module': module, 'status': 'failed', 'failureStage': 'case-setup',
                          'error': {'type': type(exc).__name__, 'message': str(exc)}}
            results.append(result)
            write_json(output / (('ui-engine-' if args.verify_ui else 'engine-') + module + '.json'), result)
            print(module + ': ' + result['status'], flush=True)
        report = {'schemaVersion': 1, 'kind': 'ui-verification' if args.verify_ui else 'engine',
                  'suite': str(suite), 'passed': all(case['status'] == 'passed' for case in results),
                  'guiVerified': False, 'cases': results}
        write_json(output / report_name, report)
        summary_name = ('ui-' if args.verify_ui else '') + 'engine-failure-summary.json'
        write_json(output / summary_name, failure_summary(results))
        return 0 if report['passed'] else 1
    except Exception as exc:
        print(type(exc).__name__ + ': ' + str(exc), file=sys.stderr, flush=True)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
