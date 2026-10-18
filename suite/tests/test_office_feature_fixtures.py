"""Fixture-construction regressions; these model UNO boundaries, not engine proof.

The text model distinguishes CR paragraphs from LF line breaks. The shape model
applies the documented TextAutoGrow behavior when content/font metrics change.
Actual Windows save/reopen remains the independent 21-case qualification gate.
"""
import copy
from types import SimpleNamespace
import unittest

from suite.tests.test_office_feature_smoke import smoke


WEIGHTS = ('CharWeight', 'CharWeightAsian', 'CharWeightComplex')


class Enumeration:
    def __init__(self, values): self.values = iter(values); self.next = next(self.values, None)
    def hasMoreElements(self): return self.next is not None
    def nextElement(self):
        value = self.next; self.next = next(self.values, None); return value


class Collection:
    def __init__(self, values=()): self.values = list(values)
    def getCount(self): return len(self.values)
    def getByIndex(self, index): return self.values[index]
    def add(self, value): self.values.append(value)
    def remove(self, value): self.values.remove(value)
    def insertNewByIndex(self, index): self.values.insert(index, Collection())


class TextShape:
    def __init__(self):
        self.text = ''; self.position = [0, 0]; self.size = [0, 0]
        self.properties = dict(TextAutoGrowHeight=True, TextAutoGrowWidth=False)
    def _layout(self):
        if self.properties['TextAutoGrowHeight']:
            self.size[1] = 400 + len(self.text) * 31
        if self.properties['TextAutoGrowWidth']:
            self.size[0] = 400 + len(self.text) * 200
    def setPosition(self, point): self.position = [point.X, point.Y]
    def setSize(self, size): self.size = [size.Width, size.Height]
    def setString(self, value): self.text = value; self._layout()
    def getString(self): return self.text
    def getShapeType(self): return 'com.sun.star.drawing.TextShape'
    def getPosition(self): return SimpleNamespace(X=self.position[0], Y=self.position[1])
    def getSize(self): return SimpleNamespace(Width=self.size[0], Height=self.size[1])
    def setPropertyValue(self, name, value): self.properties[name] = value; self._layout()
    def getPropertyValue(self, name): return self.properties[name]


class Presentation:
    def __init__(self): self.pages = Collection([Collection()])
    def getDrawPages(self): return self.pages
    def createInstance(self, service): return TextShape()


class Cursor:
    def __init__(self, text): self.text = text; self.anchor = self.position = 0
    def _move(self, value, select):
        if not select: self.anchor = value
        self.position = value
    def gotoStart(self, select): self._move(0, select)
    def gotoEnd(self, select): self._move(len(self.text.value), select)
    def goRight(self, count, select): self._move(self.position + count, select)
    def setPropertyValue(self, name, value):
        for index in range(min(self.anchor, self.position), max(self.anchor, self.position)):
            self.text.weights[index][name] = value


class Paragraph:
    def __init__(self, text, start, end): self.text = text; self.start = start; self.end = end
    def supportsService(self, name): return name == 'com.sun.star.text.Paragraph'
    def getString(self): return self.text.value[self.start:self.end]
    def createEnumeration(self):
        return Enumeration([SimpleNamespace(getString=lambda c=c: c,
                            getPropertyValue=lambda name, w=w: w[name])
                            for c, w in zip(self.text.value[self.start:self.end],
                                            self.text.weights[self.start:self.end])])


class WriterText:
    def __init__(self, document): self.document = document; self.value = ''; self.weights = []
    def setString(self, value):
        self.value = value
        # A non-normal inherited document style must not alter deliberate fixtures.
        self.weights = [dict.fromkeys(WEIGHTS, 175.0) for _ in value]
    def getString(self): return self.value.replace('\r', '\n')
    def createTextCursor(self): return Cursor(self)
    def createEnumeration(self):
        paragraphs = []; start = 0
        for part in self.value.split('\r'):
            paragraphs.append(Paragraph(self, start, start + len(part))); start += len(part) + 1
        return Enumeration(paragraphs)
    def insertControlCharacter(self, cursor, control, absorb):
        assert control == 0 and absorb is False
        position = cursor.position
        self.value = self.value[:position] + '\r' + self.value[position:]
        inherited = self.weights[position - 1].copy() if position else dict.fromkeys(WEIGHTS, 100.0)
        self.weights.insert(position, inherited); cursor.gotoEnd(False)
    def insertTextContent(self, cursor, table, absorb): self.document.tables.add(table)


class Table:
    def initialize(self, rows, columns):
        self.rows, self.columns = rows, columns; self.cells = {}
    def getCellByName(self, name):
        if name not in self.cells:
            self.cells[name] = SimpleNamespace(value='')
            cell = self.cells[name]
            cell.setString = lambda value: setattr(cell, 'value', value)
            cell.getString = lambda: cell.value
        return self.cells[name]
    def getRows(self): return Collection(range(self.rows))
    def getColumns(self): return Collection(range(self.columns))
    def getCellNames(self): return tuple(self.cells)


class Writer:
    def __init__(self): self.tables = Collection(); self.text = WriterText(self)
    def getText(self): return self.text
    def getTextTables(self): return self.tables
    def createInstance(self, service): return Table()


class Cell:
    def __init__(self, document): self.document = document; self.value = 0; self.formula = ''; self.text = ''
    def setString(self, value): self.text = value
    def getString(self): return self.text
    def setValue(self, value): self.value = value
    def setFormula(self, value): self.formula = value
    def getFormula(self): return self.formula
    def getValue(self):
        inputs = self.document.sheets.getByName('Inputs')
        if self.formula == '=SUM(InputValues)': return inputs.cells['B2'].value + inputs.cells['C2'].value
        if self.formula in ('=Inputs.B2*2', '=$Inputs.B2*2'): return inputs.cells['B2'].value * 2
        return self.value


class Sheet:
    def __init__(self, document, name): self.document = document; self.name = name; self.cells = {}
    def setName(self, name): self.name = name
    def getCellRangeByName(self, name):
        if name not in self.cells: self.cells[name] = Cell(self.document)
        return self.cells[name]


class Sheets(Collection):
    def __init__(self, document): self.document = document; super().__init__([Sheet(document, 'Sheet1')])
    def insertNewByName(self, name, index): self.values.insert(index, Sheet(self.document, name))
    def getByName(self, name): return next(sheet for sheet in self.values if sheet.name == name)
    def getElementNames(self): return tuple(sheet.name for sheet in self.values)


class Calc:
    def __init__(self): self.sheets = Sheets(self); self.named_ranges = {}
    def getSheets(self): return self.sheets
    def calculateAll(self): pass  # Cell.getValue evaluates each dependent expression.
    def getPropertyValue(self, name):
        def add(name, reference, address, flags):
            assert reference == '$Inputs.$B$2:$C$2'
            self.named_ranges[name] = SimpleNamespace(Sheet=address.Sheet, StartColumn=1,
                StartRow=1, EndColumn=2, EndRow=1)
        return SimpleNamespace(addNewByName=add, getByName=lambda name: SimpleNamespace(
            getReferredCells=lambda: SimpleNamespace(getRangeAddress=lambda: self.named_ranges[name])))


class FixtureConstructionTests(unittest.TestCase):
    def setUp(self):
        self.cases = {case['id']: case for case in smoke.case_specs()}
        self.engine = SimpleNamespace(uno=SimpleNamespace(createUnoStruct=lambda name: SimpleNamespace(),
            Enum=lambda name, value: SimpleNamespace(typeName=name, value=value)))

    def test_writer_deliberately_creates_two_paragraphs_and_normalizes_each_script_weight(self):
        case, document = self.cases['rich-writer'], Writer()
        smoke.populate(self.engine, case, document)
        self.assertIn('\rPlain paragraph', document.text.value)
        self.assertNotIn('\n', document.text.value)
        self.assertEqual(smoke.expected(case), smoke.observe(case, document))

    def test_every_impress_fixture_keeps_exact_geometry_after_text_and_font_layout(self):
        for case in (case for case in self.cases.values() if case['module'] == 'impress'):
            with self.subTest(case=case['id']):
                document = Presentation()
                smoke.populate(self.engine, case, document)
                self.assertEqual(smoke.expected(case), smoke.observe(case, document))
                for page in document.pages.values:
                    for shape in page.values:
                        self.assertIs(False, shape.properties['TextAutoGrowHeight'])
                        self.assertIs(False, shape.properties['TextAutoGrowWidth'])
                        self.assertEqual('NONE', shape.properties['TextFitToSize'].value)
                        for name in ('CharHeight', 'CharHeightAsian', 'CharHeightComplex'):
                            self.assertEqual(12.0, shape.properties[name])

    def test_calc_starts_with_exact_absolute_sheet_reference_and_preserves_recalculation(self):
        case, document = self.cases['rich-calc'], Calc()
        checkpoints = smoke.populate(self.engine, case, document)
        observed = smoke.observe(case, document)
        self.assertEqual('=$Inputs.B2*2', observed['dependentFormula'])
        self.assertEqual('=$Inputs.B2*2', smoke.expected(case)['dependentFormula'])
        self.assertEqual(dict(initialSum=42, changedPrecedent=30, recalculatedSum=55), checkpoints)
        self.assertEqual(60, observed['dependentValue'])
        smoke.validate_observation(case, observed)
        for wrong in ('=Inputs.B2*2', '=$Inputs.$B$2*2', '=$Inputs.B3*2', '=60'):
            bad = copy.deepcopy(observed); bad['dependentFormula'] = wrong
            with self.subTest(formula=wrong), self.assertRaises(AssertionError):
                smoke.validate_observation(case, bad)


if __name__ == '__main__': unittest.main()
