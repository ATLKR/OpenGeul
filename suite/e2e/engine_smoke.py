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
        if verify_ui:
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


class Engine:
    """One private profile, named pipe and owned Windows job per test case."""
    def __init__(self, suite):
        self.suite = suite
        self.runtime = suite / 'Office'
        self.process = self.profile = self.desktop = self.uno = None
        self.cleanup_errors = []

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
            # Only generated test documents reach this helper. Discarding during
            # failure cleanup is explicit; user documents are never loaded.
            document.setModified(False)
            document.close(False)

    def cleanup(self):
        if self.desktop is not None:
            try:
                self.desktop.terminate()
            except Exception as exc:
                self.cleanup_errors.append('desktop: ' + str(exc))
        dead = self.process is None
        if self.process is not None:
            try:
                try:
                    self.process.wait(timeout=5)
                except Exception:
                    self.process.terminate()  # Only our private Windows Job Object.
                    self.process.wait(timeout=5)
                dead = True
            except Exception as exc:
                self.cleanup_errors.append('owned process: ' + str(exc))
            if dead:
                self.process.close()
        if self.profile is not None and dead:
            try:
                self.profile.cleanup()
            except OSError as exc:
                self.cleanup_errors.append('private profile: ' + str(exc))
        elif self.profile is not None:
            self.cleanup_errors.append('Kept the live private profile: ' + self.profile.name)


def _shape(engine, document, page, service, text, position, size):
    shape = document.createInstance(service)
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
               (20000, 6000) if module == 'impress' else (6000, 2500))
    elif module == 'math':
        document.setPropertyValue('Formula', FORMULA)
    elif module == 'base':
        # XIsolatedConnection permits transaction control; pooled shared
        # connections deliberately reject setAutoCommit/commit/rollback.
        connection = document.DataSource.getIsolatedConnection('', '')
        try:
            connection.setAutoCommit(False)
            statement = connection.createStatement()
            statement.executeUpdate('CREATE TABLE "OPENGEUL_SMOKE" '
                                    '("ID" INTEGER NOT NULL PRIMARY KEY, "TEXT_VALUE" VARCHAR(128), "AMOUNT" INTEGER)')
            prepared = connection.prepareStatement('INSERT INTO "OPENGEUL_SMOKE" VALUES (?, ?, ?)')
            prepared.setInt(1, 1)
            prepared.setString(2, marker(module))
            prepared.setInt(3, 42)
            prepared.executeUpdate()
            connection.commit()
        finally:
            connection.close()


def observe(module, document):
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
        source = document.DataSource
        connection = source.getConnection('', '')
        try:
            result = connection.createStatement().executeQuery(
                'SELECT "ID", "TEXT_VALUE", "AMOUNT" FROM "OPENGEUL_SMOKE" ORDER BY "ID"')
            rows = []
            while result.next():
                rows.append({'id': result.getInt(1), 'text': result.getString(2), 'amount': result.getInt(3)})
            return {'rows': rows, 'databaseUrl': source.getPropertyValue('URL')}
        finally:
            connection.close()
    raise ValueError('Unknown test module: ' + module)


def run_case(suite, output, module, specification, verify_ui=False):
    path = fixture_path(output, module, must_exist=verify_ui)
    result = {'module': module, 'status': 'failed', 'fixture': str(path),
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
    if verify_ui:
        result['expected']['uiSuffix'] = 'UI-OpenGeul-' + module
    engine = Engine(suite)
    document = None
    started = time.monotonic()
    try:
        engine.start()
        if verify_ui:
            document = engine.load(path.as_uri())
        else:
            if module == 'base':
                # Direct service creation avoids the interactive database wizard.
                document = engine.service('com.sun.star.sdb.OfficeDatabaseDocument')
                document.initNew()
                document.DataSource.setPropertyValue('URL', 'sdbc:embedded:firebird')
                engine.store_new(document, path, specification['filters']['odb'])
            else:
                document = engine.load(specification['factory'])
            populate(engine, module, document)
            verify_content(module, observe(module, document))
            if module == 'base':
                document.store()
            else:
                extension = path.suffix.lstrip('.')
                engine.store_new(document, path, specification['filters'][extension])
            engine.close_document(document)
            document = None
            document = engine.load(path.as_uri())
        observed = observe(module, document)
        verify_content(module, observed, verify_ui)
        result.update(status='passed', observed=observed,
                      sha256=hashlib.sha256(path.read_bytes()).hexdigest(), bytes=path.stat().st_size)
    except Exception as exc:
        result['error'] = {'type': type(exc).__name__, 'message': str(exc),
                           'traceback': traceback.format_exc()}
    finally:
        try:
            engine.close_document(document)
        except Exception as exc:
            engine.cleanup_errors.append('generated document: ' + type(exc).__name__ + ': ' + str(exc))
        engine.cleanup()
        if engine.cleanup_errors:
            result['cleanupErrors'] = engine.cleanup_errors
            result['status'] = 'failed'
        result['elapsedSeconds'] = round(time.monotonic() - started, 3)
    return result


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
            if not set(UI_MODULES) <= passed:
                raise ValueError('Writer/Calc/Impress engine baseline must pass before GUI verification')
        else:
            (output / 'fixtures').mkdir(exist_ok=False)
        results = []
        for module in UI_MODULES if args.verify_ui else FILES:
            try:
                result = run_case(suite, output, module, modules[module], args.verify_ui)
            except Exception as exc:
                result = {'module': module, 'status': 'failed',
                          'error': {'type': type(exc).__name__, 'message': str(exc)}}
            results.append(result)
            write_json(output / (('ui-engine-' if args.verify_ui else 'engine-') + module + '.json'), result)
            print(module + ': ' + result['status'], flush=True)
        report = {'schemaVersion': 1, 'kind': 'ui-verification' if args.verify_ui else 'engine',
                  'suite': str(suite), 'passed': all(case['status'] == 'passed' for case in results),
                  'guiVerified': False, 'cases': results}
        write_json(output / report_name, report)
        return 0 if report['passed'] else 1
    except Exception as exc:
        print(type(exc).__name__ + ': ' + str(exc), file=sys.stderr, flush=True)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
