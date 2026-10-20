"""Twenty-one finite packaged Windows engine cases; no native GUI claims.

Every case creates only generated data in a fresh owned output, closes its private
engine/profile, then reopens through a second owned engine. Portable unit tests
exercise validators and execution boundaries, never Windows product success.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
import traceback
import xml.etree.ElementTree as ET
import zipfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import engine_smoke as baseline
from engine_smoke import Engine
from base_read_lifetime import (call as lifetime_call, close_resources, observe_database,
    preserve_cleanup_errors, read_rows)

CATALOG = Path(__file__).resolve().parents[1] / 'config/feature-catalog.json'
FORMATS = (
    ('writer', 'odt', 'writer8'), ('writer', 'docx', 'Office Open XML Text'),
    ('writer', 'doc', 'MS Word 97'), ('writer', 'rtf', 'Rich Text Format'), ('writer', 'txt', 'Text'),
    ('calc', 'ods', 'calc8'), ('calc', 'xlsx', 'Calc MS Excel 2007 XML'),
    ('calc', 'xls', 'MS Excel 97'), ('calc', 'csv', 'Text - txt - csv (StarCalc)'),
    ('impress', 'odp', 'impress8'), ('impress', 'pptx', 'Impress MS PowerPoint 2007 XML'),
    ('impress', 'ppt', 'MS PowerPoint 97'), ('draw', 'odg', 'draw8'),
    ('math', 'odf', 'math8'), ('base', 'odb', 'StarOffice XML (Base)'),
)
RICH_FORMATS = (('writer', 'docx'), ('calc', 'xlsx'), ('impress', 'pptx'),
                ('draw', 'odg'), ('math', 'odf'), ('base', 'odb'))
EXPECTED_IDS = tuple('format-' + m + '-' + e for m, e, _ in FORMATS) + tuple('rich-' + m for m, _ in RICH_FORMATS)
# Writer's encoding token and Calc's character-set76 both explicitly select UTF-8.
# CSV: comma, double quote, UTF-8, first row1, no column overrides, locale0,
# unquoted values, detect numbers, full numeric values, no formula import/export.
TEXT_OPTIONS = 'UTF8,LF,,,false,false'
CSV_OPTIONS = '44,34,76,1,,0,false,true,false,false,false,0,false,false'
RICH_FORMULA = 'sqrt {a^2 + b^2} = c'
ODF_MIMETYPES = {'odt': 'text', 'ods': 'spreadsheet', 'odp': 'presentation',
                 'odg': 'graphics', 'odf': 'formula', 'odb': 'base'}
PPTX_LOSS = ['native-reopen-bounds-minus-one-mm100']
PPTX_SCOPE = dict(authoredAndSavedGeometry='exact authored mm100 and OOXML EMU extents',
                  nativeReopenGeometry='exact native bounds conversion, no tolerance',
                  losslessRepeatedNativeEditSave=False, universalGeometryPreservation=False)
PPTX_NATIVE_DIFFERENCE = dict(
    kind='native-closed-open-rectangle-bounds', unit='mm100', reopenSizeDeltaMm100=-1,
    authoredShapeType='com.sun.star.drawing.TextShape',
    reopenedShapeType='com.sun.star.drawing.CustomShape',
    sources=[
        'https://github.com/LibreOffice/core/blob/libreoffice-26.8.1.1/oox/source/ppt/pptshapegroupcontext.cxx#L108',
        'https://github.com/LibreOffice/core/blob/libreoffice-26.8.1.1/oox/source/drawingml/shape.cxx#L1118',
        'https://github.com/LibreOffice/core/blob/libreoffice-26.8.1.1/svx/source/svdraw/svdoashp.cxx#L3032',
        'https://github.com/LibreOffice/core/blob/libreoffice-26.8.1.1/include/tools/gen.hxx#L593',
        'https://github.com/LibreOffice/core/blob/libreoffice-26.8.1.1/svx/source/unodraw/unoshape.cxx#L1069'])


def is_pptx(case):
    return case['module'] == 'impress' and case['extension'] == 'pptx'


def marker(module):
    return 'Feature-OpenGeul-' + module + ' 한글'


def validate_catalog(catalog):
    cases = catalog.get('cases', [])
    if (catalog.get('schemaVersion') != 1 or catalog.get('expectedCaseCount') != 21
            or catalog.get('guiVerified') is not False or catalog.get('officeReplacementCertified') is not False
            or tuple(c.get('id') for c in cases) != EXPECTED_IDS):
        raise ValueError('The reviewed fifteen-format/six-rich case catalog is required')
    mapping = {(m, e): f for m, e, f in FORMATS}
    for case in cases:
        module, extension = case.get('module'), case.get('extension')
        if case.get('filter') != mapping.get((module, extension)) or case.get('guiVerified') is not False:
            raise ValueError('Catalog filter/module/GUI contract changed')
        expected_id = ('format-' + module + '-' + extension) if case.get('kind') == 'format' else 'rich-' + module
        if case['id'] != expected_id or case.get('kind') not in ('format', 'rich'):
            raise ValueError('Catalog case kind changed')
        if case['kind'] == 'rich' and (module, extension) not in RICH_FORMATS:
            raise ValueError('Catalog rich representative format changed')
        loss = PPTX_LOSS if is_pptx(case) else ['formula-expression', 'formatting', 'extra-sheets'] if extension == 'csv' else ['formatting', 'structure'] if extension == 'txt' else []
        if case.get('lossBudget') != loss:
            raise ValueError('Catalog loss budget changed')
        if is_pptx(case) and (case.get('qualificationScope') != PPTX_SCOPE or
                             case.get('knownNativeGeometryDifference') != PPTX_NATIVE_DIFFERENCE):
            raise ValueError('PPTX native geometry limitation must remain explicit')
    return cases


def case_specs():
    return validate_catalog(json.loads(CATALOG.read_text(encoding='utf-8')))


def validate_modules(modules):
    for module, factory in baseline.FACTORIES.items():
        expected_filters = {e: f for m, e, f in FORMATS if m == module}
        actual = modules.get(module, {})
        if actual.get('factory') != factory or actual.get('filters') != expected_filters or set(actual.get('extensions', [])) != set(expected_filters):
            raise ValueError('Packaged manifest differs from fixed advertised formats: ' + module)


def _shape(text, position, size, color=None):
    result = dict(text=text, position=position, size=size)
    if color is not None: result['color'] = color
    return result


def base_rows(rich=False):
    if rich:
        return [dict(id=1, text=marker('base') + ' updated', amount=55),
                dict(id=3, text=marker('base') + ' inserted', amount=13)]
    return [dict(id=1, text=baseline.marker('base'), amount=42)]


def expected(case):
    module, rich = case['module'], case['kind'] == 'rich'
    if module == 'writer':
        if not rich: return dict(text=baseline.marker(module))
        return dict(paragraphs=[dict(text=marker(module) + ' bold', bold=True, weights=[150, 150, 150]),
                                dict(text='Plain paragraph', bold=False, weights=[100, 100, 100])],
                    tables=[dict(rows=2, columns=2, cells={'A1': 'cell-a1', 'B1': 'cell-b1', 'A2': 'cell-a2', 'B2': 'cell-b2'})])
    if module == 'calc':
        if case['extension'] == 'csv': return dict(text=baseline.marker(module), values=[17, 25, 42])
        if not rich: return dict(text=baseline.marker(module), inputs=[17, 25], formula='=SUM(B1:C1)', value=42)
        return dict(sheetNames=['Inputs', 'Summary'], text=marker(module), inputs=[30, 25],
                    namedRange=[0, 1, 1, 2, 1], formula='=SUM(InputValues)', value=55,
                    dependentFormula='=$Inputs.B2*2', dependentValue=60)
    if module in ('impress', 'draw'):
        if not rich:
            if case['extension'] == 'ppt':
                # Binary PPT stores geometry on a 576-DPI grid. These exact
                # inch-based coordinates avoid pretending its rounding is loss.
                return dict(pages=[[_shape(baseline.marker(module), [2540, 2540], [20320, 6350])]])
            result = dict(pages=[[_shape(baseline.marker(module), [2500, 2500] if module == 'impress' else [1000, 1000],
                                        [20000, 6000] if module == 'impress' else [6000, 2500])]])
        else:
            colors = [0x2266AA, 0xCC5500] if module == 'draw' else [None, None]
            result = dict(pages=[[_shape(marker(module) + '-page-' + str(index + 1), [1000 + index * 1500, 1200 + index * 800],
                                       [6000 + index * 1000, 2500 + index * 500], colors[index])] for index in range(2)])
        if is_pptx(case):
            for page in result['pages']:
                for shape in page: shape['shapeType'] = PPTX_NATIVE_DIFFERENCE['authoredShapeType']
        return result
    if module == 'math': return dict(formula=''.join((RICH_FORMULA if rich else baseline.FORMULA).split()))
    if module == 'base': return dict(databaseUrl='sdbc:embedded:firebird', rows=base_rows(rich))
    raise ValueError('Unknown module')


def validate_observation(case, observed, phase='create'):
    if phase not in ('create', 'independent-reopen'): raise ValueError('Unknown semantic observation phase')
    wanted = expected(case)
    if is_pptx(case) and phase == 'independent-reopen':
        # Preserve the authored oracle and raw observations. Upstream imports
        # extent into a closed Rectangle, while XShape.getSize exposes open size.
        # The separate package proof still requires exact authored EMU extents.
        for page in wanted['pages']:
            for shape in page:
                shape['size'] = [value - 1 for value in shape['size']]
                shape['shapeType'] = PPTX_NATIVE_DIFFERENCE['reopenedShapeType']
    assert observed == wanted, 'Persisted semantics differ for ' + case['id'] + ': expected ' + repr(wanted) + '; observed ' + repr(observed)
    return observed


def _fix_impress_geometry(engine, shape, wanted):
    # Attaching text to a new Impress TextShape can auto-shrink its height.
    # Disable content-driven sizing before setting the final exact geometry.
    shape.setPropertyValue('TextAutoGrowHeight', False)
    shape.setPropertyValue('TextAutoGrowWidth', False)
    shape.setPropertyValue('TextFitToSize', engine.uno.Enum('com.sun.star.drawing.TextFitToSizeType', 'NONE'))
    for name in ('CharHeight', 'CharHeightAsian', 'CharHeightComplex'):
        shape.setPropertyValue(name, 12.0)
    point = engine.uno.createUnoStruct('com.sun.star.awt.Point')
    point.X, point.Y = wanted['position']
    size = engine.uno.createUnoStruct('com.sun.star.awt.Size')
    size.Width, size.Height = wanted['size']
    shape.setPosition(point)
    shape.setSize(size)


def _normal_text(value):
    return value.replace('\r\n', '\n').replace('\r', '\n').rstrip('\n')


def _rows(connection, diagnostics=None):
    return read_rows(connection, diagnostics)


def _base_crud(document, diagnostics=None):
    connection = lifetime_call(diagnostics, 'connection.open-isolated', lambda: document.DataSource.getIsolatedConnection('', ''))
    primary = None
    try:
        connection.setAutoCommit(False)
        connection.createStatement().execute('CREATE TABLE "OPENGEUL_SMOKE" ("ID" INTEGER NOT NULL PRIMARY KEY, "TEXT_VALUE" VARCHAR(128), "AMOUNT" INTEGER)')
        def insert(id, text, amount):
            statement = connection.prepareStatement('INSERT INTO "OPENGEUL_SMOKE" VALUES (?, ?, ?)')
            statement.setInt(1, id); statement.setString(2, text); statement.setInt(3, amount)
            statement.executeUpdate()
        insert(1, marker('base'), 42)
        insert(2, 'delete-me', 9)
        connection.commit()
        initial = _rows(connection, diagnostics)
        assert initial == [dict(id=1, text=marker('base'), amount=42), dict(id=2, text='delete-me', amount=9)], 'Initial CRUD fixture is wrong'
        update = connection.prepareStatement('UPDATE "OPENGEUL_SMOKE" SET "TEXT_VALUE"=?, "AMOUNT"=? WHERE "ID"=1')
        update.setString(1, marker('base') + ' updated'); update.setInt(2, 55)
        assert update.executeUpdate() == 1, 'UPDATE did not change one row'
        insert(3, marker('base') + ' inserted', 13)
        assert connection.createStatement().executeUpdate('DELETE FROM "OPENGEUL_SMOKE" WHERE "ID"=2') == 1, 'DELETE did not remove one row'
        connection.commit()
        committed = _rows(connection, diagnostics)
        assert committed == base_rows(True), 'Committed CRUD state is wrong'
        connection.createStatement().executeUpdate('UPDATE "OPENGEUL_SMOKE" SET "AMOUNT"=999 WHERE "ID"=1')
        connection.createStatement().executeUpdate('DELETE FROM "OPENGEUL_SMOKE" WHERE "ID"=3')
        insert(4, 'rollback-me', 99)
        connection.rollback()
        rolled_back = _rows(connection, diagnostics)
        assert rolled_back == committed, 'ROLLBACK did not restore committed state'
        return dict(initialRows=initial, committedRows=committed, rolledBackRows=rolled_back)
    except BaseException as exc:
        primary = exc
        raise
    finally:
        close_resources([('connection.close', connection.close)], primary, diagnostics)


def populate(engine, case, document):
    module = case['module']
    if case['kind'] == 'format':
        baseline.populate(engine, module, document)
        if module == 'impress':
            shape = document.getDrawPages().getByIndex(0).getByIndex(0)
            _fix_impress_geometry(engine, shape, expected(case)['pages'][0][0])
        return {}
    if module == 'writer':
        first = marker(module) + ' bold'
        text = document.getText()
        # XTextRange.setString treats CR as a paragraph boundary; LF is an
        # in-paragraph line break and cannot satisfy the two-paragraph fixture.
        text.setString(first + '\rPlain paragraph')
        cursor = text.createTextCursor()
        cursor.gotoStart(False); cursor.gotoEnd(True)
        for name in ('CharWeight', 'CharWeightAsian', 'CharWeightComplex'):
            cursor.setPropertyValue(name, 100.0)
        cursor.gotoStart(False); cursor.goRight(len(first), True)
        for name in ('CharWeight', 'CharWeightAsian', 'CharWeightComplex'):
            cursor.setPropertyValue(name, 150.0)
        assert _writer_paragraphs(text) == expected(case)['paragraphs'], 'Writer fixture must contain separate uniformly bold and normal paragraphs'
        cursor.gotoEnd(False)
        text.insertControlCharacter(cursor, 0, False)  # PARAGRAPH_BREAK
        table = document.createInstance('com.sun.star.text.TextTable')
        table.initialize(2, 2)
        text.insertTextContent(cursor, table, False)
        for name, value in expected(case)['tables'][0]['cells'].items(): table.getCellByName(name).setString(value)
    elif module == 'calc':
        sheets = document.getSheets()
        inputs = sheets.getByIndex(0); inputs.setName('Inputs')
        sheets.insertNewByName('Summary', 1)
        inputs.getCellRangeByName('B2').setValue(17)
        inputs.getCellRangeByName('C2').setValue(25)
        address = engine.uno.createUnoStruct('com.sun.star.table.CellAddress')
        address.Sheet, address.Column, address.Row = 0, 1, 1
        document.getPropertyValue('NamedRanges').addNewByName('InputValues', '$Inputs.$B$2:$C$2', address, 0)
        summary = sheets.getByName('Summary')
        summary.getCellRangeByName('A1').setString(marker(module))
        summary.getCellRangeByName('B1').setFormula('=SUM(InputValues)')
        # XLSX preserves this deliberately absolute sheet reference verbatim.
        summary.getCellRangeByName('B2').setFormula('=$Inputs.B2*2')
        document.calculateAll()
        assert summary.getCellRangeByName('B1').getValue() == 42, 'Initial named-range SUM is wrong'
        inputs.getCellRangeByName('B2').setValue(30)
        document.calculateAll()
        assert summary.getCellRangeByName('B1').getValue() == 55, 'SUM did not recalculate after precedent change'
        return dict(initialSum=42, changedPrecedent=30, recalculatedSum=55)
    elif module in ('impress', 'draw'):
        pages = document.getDrawPages()
        while pages.getCount() > 1: pages.remove(pages.getByIndex(pages.getCount()-1))
        pages.insertNewByIndex(1)
        for index, wanted in enumerate(expected(case)['pages']):
            page = pages.getByIndex(index)
            while page.getCount(): page.remove(page.getByIndex(0))
            shape = baseline._shape(engine, document, page,
                'com.sun.star.drawing.TextShape' if module == 'impress' else 'com.sun.star.drawing.RectangleShape',
                wanted[0]['text'], wanted[0]['position'], wanted[0]['size'])
            if module == 'impress': _fix_impress_geometry(engine, shape, wanted[0])
            if module == 'draw': shape.setPropertyValue('FillColor', wanted[0]['color'])
    elif module == 'math': document.setPropertyValue('Formula', RICH_FORMULA)
    elif module == 'base': return _base_crud(document, getattr(engine, 'lifetime_diagnostics', None))
    return {}


def writer_paragraph(paragraph):
    """A mixed or heavy run cannot satisfy the uniform normal/bold contract."""
    weights = []
    portions = paragraph.createEnumeration()
    while portions.hasMoreElements():
        portion = portions.nextElement()
        if portion.getString():
            weights.append([portion.getPropertyValue(name) for name in
                            ('CharWeight', 'CharWeightAsian', 'CharWeightComplex')])
    uniform = weights[0] if weights and all(value == weights[0] for value in weights) else None
    return dict(text=paragraph.getString(), bold=uniform == [150, 150, 150], weights=uniform)


def _writer_paragraphs(text):
    paragraphs = []
    items = text.createEnumeration()
    while items.hasMoreElements():
        item = items.nextElement()
        if item.supportsService('com.sun.star.text.Paragraph') and item.getString():
            paragraphs.append(writer_paragraph(item))
    return paragraphs


def observe(case, document, diagnostics=None):
    module, rich = case['module'], case['kind'] == 'rich'
    if module == 'writer':
        if not rich: return dict(text=_normal_text(document.getText().getString()))
        paragraphs = _writer_paragraphs(document.getText())
        tables = document.getTextTables()
        result = []
        for index in range(tables.getCount()):
            table = tables.getByIndex(index)
            result.append(dict(rows=table.getRows().getCount(), columns=table.getColumns().getCount(),
                               cells={name: table.getCellByName(name).getString() for name in table.getCellNames()}))
        return dict(paragraphs=paragraphs, tables=result)
    if module == 'calc':
        document.calculateAll()
        sheets = document.getSheets()
        if not rich:
            sheet = sheets.getByIndex(0)
            result = dict(text=sheet.getCellRangeByName('A1').getString())
            if case['extension'] == 'csv':
                result['values'] = [sheet.getCellRangeByName(name).getValue() for name in ('B1', 'C1', 'D1')]
            else:
                result.update(inputs=[sheet.getCellRangeByName(name).getValue() for name in ('B1', 'C1')],
                              formula=sheet.getCellRangeByName('D1').getFormula(), value=sheet.getCellRangeByName('D1').getValue())
            return result
        inputs, summary = sheets.getByName('Inputs'), sheets.getByName('Summary')
        area = document.getPropertyValue('NamedRanges').getByName('InputValues').getReferredCells().getRangeAddress()
        return dict(sheetNames=list(sheets.getElementNames()), text=summary.getCellRangeByName('A1').getString(),
                    inputs=[inputs.getCellRangeByName(name).getValue() for name in ('B2', 'C2')],
                    namedRange=[area.Sheet, area.StartColumn, area.StartRow, area.EndColumn, area.EndRow],
                    formula=summary.getCellRangeByName('B1').getFormula(), value=summary.getCellRangeByName('B1').getValue(),
                    dependentFormula=summary.getCellRangeByName('B2').getFormula(), dependentValue=summary.getCellRangeByName('B2').getValue())
    if module in ('impress', 'draw'):
        pages = document.getDrawPages()
        result = []
        for index in range(pages.getCount()):
            page = pages.getByIndex(index)
            shapes = []
            for number in range(page.getCount()):
                shape = page.getByIndex(number)
                position, size = shape.getPosition(), shape.getSize()
                observed = _shape(shape.getString(), [position.X, position.Y], [size.Width, size.Height])
                if is_pptx(case): observed['shapeType'] = shape.getShapeType()
                if rich and module == 'draw': observed['color'] = shape.getPropertyValue('FillColor')
                shapes.append(observed)
            result.append(shapes)
        return dict(pages=result)
    if module == 'math': return dict(formula=''.join(document.getPropertyValue('Formula').split()))
    if module == 'base':
        return observe_database(document, diagnostics)
    raise ValueError('Unknown module')


def validate_flat_bytes(case, path):
    text = path.read_bytes().decode('utf-8-sig')
    if case['extension'] == 'txt':
        assert _normal_text(text) == baseline.marker('writer'), 'TXT lost exact UTF-8 text'
    elif case['extension'] == 'csv':
        rows = list(csv.reader(text.splitlines(), delimiter=',', quotechar='"'))
        assert rows == [[baseline.marker('calc'), '17', '25', '42']], 'CSV must contain exact displayed values in comma-delimited UTF-8'


def validate_pptx_geometry(case, package):
    """Read the saved OOXML independently of UNO, in relationship slide order."""
    p = '{http://schemas.openxmlformats.org/presentationml/2006/main}'
    a = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
    r = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
    rel = '{http://schemas.openxmlformats.org/package/2006/relationships}'
    names = package.namelist()
    assert len(names) == len(set(names)), 'PPTX contains duplicate package members'

    def xml(name, root):
        info = package.getinfo(name)
        assert info.file_size <= 1048576, 'Generated PPTX XML exceeds its bounded fixture size'
        data = package.read(name)
        assert b'<!DOCTYPE' not in data and b'<!ENTITY' not in data, 'Unexpected PPTX XML declarations'
        tree = ET.fromstring(data)
        assert tree.tag == root, 'Unexpected PPTX XML root'
        return tree

    def one(parent, tag):
        children = parent.findall(tag)
        assert len(children) == 1, 'PPTX geometry element missing or duplicated: ' + tag
        return children[0]

    presentation = xml('ppt/presentation.xml', p+'presentation')
    ids = list(one(presentation, p+'sldIdLst'))
    assert all(node.tag == p+'sldId' for node in ids), 'Unexpected PPTX slide-list entry'
    refs = [node.get(r+'id') for node in ids]
    assert None not in refs and len(refs) == len(set(refs)), 'PPTX slide references are missing or duplicated'
    relationships = xml('ppt/_rels/presentation.xml.rels', rel+'Relationships')
    targets = {}
    for node in relationships:
        assert node.tag == rel+'Relationship', 'Unexpected PPTX relationship element'
        if node.get('Type') != r[1:-1]+'/slide': continue
        rid, target = node.get('Id'), node.get('Target')
        assert rid and rid not in targets and node.get('TargetMode') is None, 'Invalid PPTX slide relationship'
        assert target and re.fullmatch(r'slides/slide[1-9][0-9]*\.xml', target), 'Unexpected PPTX slide target'
        targets[rid] = 'ppt/'+target
    assert set(refs) == set(targets), 'PPTX slide relationships differ from presentation order'
    assert set(targets.values()) == {name for name in names if re.fullmatch(r'ppt/slides/slide[1-9][0-9]*\.xml', name)}, 'PPTX has missing or unreferenced slides'
    pages = []
    for rid in refs:
        slide = xml(targets[rid], p+'sld')
        tree = one(one(slide, p+'cSld'), p+'spTree')
        assert all(node.tag in (p+'nvGrpSpPr', p+'grpSpPr', p+'sp') for node in tree), 'Unexpected PPTX shape kind'
        shapes = []
        for node in tree.findall(p+'sp'):
            nonvisual = one(one(node, p+'nvSpPr'), p+'cNvSpPr')
            assert nonvisual.get('txBox') == '1', 'PPTX fixture is not the authored text box'
            transform = one(one(node, p+'spPr'), a+'xfrm')
            assert not transform.attrib, 'Unexpected PPTX rotation or flipping'
            assert len(transform) == 2, 'Unexpected PPTX transform children'
            off, ext = one(transform, a+'off'), one(transform, a+'ext')
            assert set(off.attrib) == {'x','y'} and set(ext.attrib) == {'cx','cy'}, 'Malformed PPTX geometry attributes'
            coordinates = [off.get('x'), off.get('y'), ext.get('cx'), ext.get('cy')]
            assert all(re.fullmatch(r'-?(?:0|[1-9][0-9]*)', value) for value in coordinates), 'PPTX geometry is not an exact integer'
            body = one(node, p+'txBody')
            paragraphs = body.findall(a+'p')
            assert len(paragraphs) == 1 and not paragraphs[0].findall('.//'+a+'br'), 'Unexpected PPTX paragraph or line break'
            text = ''.join(part.text or '' for part in paragraphs[0].iter(a+'t'))
            shapes.append(dict(text=text, positionEmu=list(map(int, coordinates[:2])), sizeEmu=list(map(int, coordinates[2:]))))
        pages.append(shapes)
    wanted = dict(pages=[[dict(text=s['text'], positionEmu=[n*360 for n in s['position']],
                              sizeEmu=[n*360 for n in s['size']]) for s in page] for page in expected(case)['pages']])
    assert dict(pages=pages) == wanted, 'Saved PPTX differs from exact authored text/order/EMU geometry'
    return dict(exactAuthoredEmuVerified=True, unit='EMU', pages=pages)


def validate_container(case, path):
    ext = case['extension']
    data = path.read_bytes()
    assert data, 'Saved document is empty'
    if ext in ('txt', 'csv'):
        validate_flat_bytes(case, path)
    elif ext in ('doc', 'xls', 'ppt'):
        assert data.startswith(bytes.fromhex('d0cf11e0a1b11ae1')), 'Legacy Office output is not an OLE compound document'
    elif ext == 'rtf':
        assert data.startswith(b'{\\rtf'), 'RTF output is not RTF'
    else:
        with zipfile.ZipFile(path) as package:
            assert package.testzip() is None, 'Saved package has a corrupt member'
            if ext in ODF_MIMETYPES:
                wanted = ('application/vnd.oasis.opendocument.' + ODF_MIMETYPES[ext]).encode()
                assert package.read('mimetype') == wanted, 'ODF package type does not match its extension'
                assert 'content.xml' in package.namelist(), 'ODF content.xml is missing'
            else:
                main = {'docx': 'word/document.xml', 'xlsx': 'xl/workbook.xml', 'pptx': 'ppt/presentation.xml'}[ext]
                assert main in package.namelist() and '[Content_Types].xml' in package.namelist(), 'OOXML package type does not match its extension'
                if is_pptx(case): return validate_pptx_geometry(case, package)


def _filter_options(case):
    if case['extension'] == 'txt': return TEXT_OPTIONS
    if case['extension'] == 'csv': return CSV_OPTIONS
    return None


def store_new(engine, case, document, path):
    options = _filter_options(case)
    if options is None:
        engine.store_new(document, path, case['filter'])
        return
    if path.exists(): raise FileExistsError('Generated target already exists')
    from dispatch import make_interaction_handler
    properties = [('FilterName', case['filter']), ('FilterOptions', options), ('Overwrite', False),
                  ('InteractionHandler', make_interaction_handler())]
    document.storeAsURL(path.as_uri(), tuple(engine.prop(name, value) for name, value in properties))


def load_saved(engine, case, path):
    from dispatch import make_interaction_handler
    properties = [('Hidden', True), ('ReadOnly', True), ('MacroExecutionMode', 0),
                  ('UpdateDocMode', 0), ('PickListEntry', False), ('AsTemplate', False),
                  ('FilterName', case['filter']), ('InteractionHandler', make_interaction_handler())]
    options = _filter_options(case)
    if options is not None: properties.append(('FilterOptions', options))
    document = engine.desktop.loadComponentFromURL(path.as_uri(), '_blank', 0,
                                                  tuple(engine.prop(name, value) for name, value in properties))
    if document is None: raise RuntimeError('Independent engine returned no document')
    return document


def _unlinked_ancestors(path):
    for item in (path, *path.parents):
        if item.is_symlink() or getattr(item, 'is_junction', lambda: False)():
            raise ValueError('Linked Suite/evidence ancestors are not accepted')


def prepare_output(suite, output):
    if any(str(path).startswith(('\\\\', '//')) for path in (suite, output)):
        raise ValueError('Only local Suite and evidence paths are accepted')
    _unlinked_ancestors(suite); _unlinked_ancestors(output)
    suite, output = suite.resolve(), output.resolve()
    if suite == output or suite in output.parents:
        raise ValueError('Evidence must be outside the Suite payload')
    if not suite.is_dir(): raise ValueError('Packaged Suite directory is missing')
    output.mkdir(parents=True, exist_ok=False)
    (output / 'fixtures').mkdir()
    return suite, output


def fixture_path(output, case):
    if case['id'] not in EXPECTED_IDS or not any(case == known for known in case_specs()):
        raise ValueError('Only fixed reviewed cases may generate fixtures')
    folder = output / 'fixtures'
    _unlinked_ancestors(folder)
    path = folder / (case['id'] + '.' + case['extension'])
    _unlinked_ancestors(path)
    if path.exists(): raise FileExistsError('Never overwrite an existing generated fixture')
    if path.resolve().parent != folder.resolve(): raise ValueError('Fixture escaped its owned directory')
    return path.resolve()


def _error(exc):
    return dict(type=type(exc).__name__, message=str(exc), traceback=traceback.format_exc())


def run_case(suite, output, case):
    record = dict(case=case['id'], module=case['module'], extension=case['extension'], filter=case['filter'],
                  status='failed', guiVerified=False, independentReopenVerified=False, stage='fixture',
                  lossBudget=case['lossBudget'], expected=expected(case))
    if is_pptx(case):
        record.update(knownNativeGeometryDifference=case['knownNativeGeometryDifference'],
                      qualificationScope=case['qualificationScope'])
    started = time.monotonic()
    engines = []
    path = None
    try:
        path = fixture_path(output, case)
        record['fixture'] = str(path)
        for phase in ('create', 'independent-reopen'):
            record['stage'] = phase
            engine, document = Engine(suite), None
            engine.base_lifetime_enabled = case['module'] == 'base'
            diagnostics = getattr(engine, 'lifetime_diagnostics', None) if case['module'] == 'base' else None
            phase_error = None
            phase_cleanup_errors = []
            engines.append(engine)
            try:
                engine.start()
                if phase == 'create':
                    if case['module'] == 'base':
                        document = engine.service('com.sun.star.sdb.OfficeDatabaseDocument')
                        document.initNew()
                        document.DataSource.setPropertyValue('URL', 'sdbc:embedded:firebird')
                        store_new(engine, case, document, path)
                    else:
                        document = engine.load(baseline.FACTORIES[case['module']])
                    record['creationCheckpoints'] = populate(engine, case, document)
                    record['createdObservation'] = observe(case, document, diagnostics) if diagnostics is not None else observe(case, document)
                    validate_observation(case, record['createdObservation'], phase=phase)
                    if case['module'] == 'base': document.store()
                    else: store_new(engine, case, document, path)
                else:
                    document = load_saved(engine, case, path)
                    record['observed'] = observe(case, document, diagnostics) if diagnostics is not None else observe(case, document)
                    validate_observation(case, record['observed'], phase=phase)
                    record['independentReopenVerified'] = True
            except Exception as exc:
                phase_error = exc
                raise
            finally:
                try: engine.close_document(document)
                except Exception as exc:
                    engine.cleanup_errors.append('generated document: ' + str(exc))
                    phase_cleanup_errors.append(('generated document', exc))
                try: engine.cleanup()
                except Exception as exc:
                    engine.cleanup_errors.append('owned cleanup: ' + str(exc))
                    phase_cleanup_errors.append(('owned cleanup', exc))
                cleanup = getattr(engine, 'cleanup_evidence', None)
                record.setdefault('engineCleanups', []).append(dict(phase=phase, evidence=cleanup))
                if engine.cleanup_errors:
                    problem = RuntimeError('Owned engine cleanup failed: ' + '; '.join(engine.cleanup_errors))
                    preserve_cleanup_errors(phase_error, phase_cleanup_errors + [('owned cleanup', problem)])
                else:
                    try: baseline.validate_cleanup_evidence(cleanup)
                    except Exception as exc: preserve_cleanup_errors(phase_error, [('owned cleanup proof', exc)])
            # Firebird finalizes its embedded backup during close; hash only after
            # each model and owned process have fully disposed.
            package_proof = validate_container(case, path)
            if is_pptx(case): record.setdefault('packageGeometryChecks', []).append(dict(phase=phase, proof=package_proof))
            if phase == 'create': record['createdSha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        final = path.read_bytes()
        digest = hashlib.sha256(final).hexdigest()
        unchanged = digest == record['createdSha256']
        record['reopenBytesUnchanged'] = unchanged
        if case['module'] != 'base': assert unchanged, 'Read-only reopen changed saved document bytes'
        record.update(status='passed', stage='complete', sha256=digest, bytes=len(final))
    except Exception as exc:
        record['error'] = _error(exc)
        record.pop('sha256', None); record.pop('bytes', None)
    finally:
        errors = [error for engine in engines for error in engine.cleanup_errors]
        if errors: record.update(status='failed', cleanupErrors=errors)
        record['elapsedSeconds'] = round(time.monotonic() - started, 3)
    return record


def summarize(records, suite):
    counts = Counter(row.get('case') for row in records)
    missing = [name for name in EXPECTED_IDS if counts[name] == 0]
    duplicate = [name for name, count in counts.items() if count > 1]
    unknown = [name for name in counts if name not in EXPECTED_IDS]
    modules = {'format-' + m + '-' + e: m for m, e, _ in FORMATS}
    modules.update({'rich-' + m: m for m, _ in RICH_FORMATS})
    failed = [row.get('case') for row in records if row.get('status') != 'passed'
              or row.get('module') != modules.get(row.get('case')) or row.get('error') or row.get('cleanupErrors')
              or row.get('guiVerified') is not False or row.get('independentReopenVerified') is not True
              or not isinstance(row.get('sha256'), str) or re.fullmatch('[0-9a-f]{64}', row['sha256']) is None
              or type(row.get('bytes')) is not int or row['bytes'] <= 0]
    order_matches = tuple(row.get('case') for row in records) == EXPECTED_IDS
    passed = len(records) == 21 and order_matches and not (missing or duplicate or unknown or failed)
    return dict(schemaVersion=1, kind='office-engine-features', suite=str(suite), passed=passed,
                guiVerified=False, expectedCaseCount=21, completedCaseCount=len(records),
                canonicalOrderVerified=order_matches, missingCases=missing, duplicateCases=duplicate,
                unknownCases=unknown, failedCases=failed, cases=records)


def run_all(cases, run, output, suite):
    records = []
    # The output directory belongs solely to this invocation. Rewrite only this
    # invocation's aggregate, so interruption retains every completed case.
    aggregate = output / 'office-features.json'
    if aggregate.exists(): raise FileExistsError('Feature report already exists')
    baseline.write_json(aggregate, summarize(records, suite))
    for case in cases:
        try: result = run(case)
        except Exception as exc:
            result = dict(case=case['id'], module=case['module'], status='failed', guiVerified=False,
                          independentReopenVerified=False, stage='case-setup', error=_error(exc))
        records.append(result)
        baseline.write_json(output / (case['id'] + '.json'), result)
        report = summarize(records, suite)
        temporary = output / 'office-features.pending.json'
        baseline.write_json(temporary, report)
        os.replace(temporary, aggregate)
        print(case['id'] + ': ' + result['status'], flush=True)
    return summarize(records, suite)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if not __debug__: raise RuntimeError('Do not disable semantic assertions with Python -O')
        cases = case_specs()
        manifest = json.loads((args.suite / 'suite-product.json').read_text(encoding='utf-8-sig'))
        if manifest.get('schemaVersion') != 1: raise ValueError('Unsupported manifest schema')
        validate_modules(manifest['modules'])
        suite, output = prepare_output(args.suite, args.output)
        report = run_all(cases, lambda case: run_case(suite, output, case), output, suite)
        return 0 if report['passed'] else 1
    except Exception as exc:
        print(type(exc).__name__ + ': ' + str(exc), file=sys.stderr, flush=True)
        return 2


if __name__ == '__main__': raise SystemExit(main())
