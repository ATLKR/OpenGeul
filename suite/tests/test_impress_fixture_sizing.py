"""Generated fixed Impress fixture boundaries; no native-layout/cure claim."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest


E2E = Path(__file__).resolve().parents[1] / 'e2e'


def sibling(name):
    spec = importlib.util.spec_from_file_location('fixed_fixture_' + name, E2E / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


smoke = sibling('engine_smoke')
pdf = sibling('pdf_export_smoke')
TEXT = 'com.sun.star.drawing.TextShape'
RECTANGLE = 'com.sun.star.drawing.RectangleShape'
PROPERTIES = [('TextAutoGrowHeight', False), ('TextAutoGrowWidth', False),
              ('TextFitToSize', ('com.sun.star.drawing.TextFitToSizeType', 'NONE'))]


class FixtureShape:
    def __init__(self, events, *, failure=None):
        self.events = events
        self.properties = {}
        self.failure = failure
        self.position = self.size = self.text = None
        self.cursor = SimpleNamespace(gotoEnd=lambda selected: events.append(('cursor-end', selected)),
                                      setPropertyValue=lambda name, value: events.append(('cursor-property', name, value)))

    def setPropertyValue(self, name, value):
        self.events.append(('shape-property', name, value))
        if self.failure and name == self.failure[0]:
            raise self.failure[1]
        self.properties[name] = value

    def setPosition(self, value):
        self.position = (value.X, value.Y)
        self.events.append(('position', self.position))

    def setSize(self, value):
        self.size = (value.Width, value.Height)
        self.events.append(('size', self.size))

    def setString(self, value):
        self.text = value
        self.events.append(('text', value))

    def getText(self):
        return SimpleNamespace(createTextCursor=lambda: self.cursor)


class FixturePage:
    def __init__(self, events, objects=()):
        self.events = events
        self.objects = list(objects)

    def getCount(self): return len(self.objects)
    def getByIndex(self, index): return self.objects[index]
    def remove(self, shape): self.objects.remove(shape)
    def add(self, shape):
        self.events.append(('add', shape))
        self.objects.append(shape)
    def setPropertyValue(self, name, value):
        self.events.append(('page-property', name, value))


class FixtureDocument:
    def __init__(self, *, failure=None):
        self.events = []
        self.shapes = []
        self.pages = [FixturePage(self.events, [object()]), FixturePage(self.events)]
        self.failure = failure

    def createInstance(self, service):
        self.events.append(('create-shape', service))
        shape = FixtureShape(self.events, failure=self.failure)
        self.shapes.append(shape)
        return shape

    def getDrawPages(self):
        owner = self
        class Pages:
            def getCount(self): return len(owner.pages)
            def getByIndex(self, index): return owner.pages[index]
            def remove(self, page): owner.pages.remove(page)
            def insertNewByIndex(self, index): owner.pages.insert(index, FixturePage(owner.events))
        return Pages()


def engine(events, *, enum_failure=None):
    def enum(kind, value):
        events.append(('enum', kind, value))
        if enum_failure is not None:
            raise enum_failure
        return kind, value
    return SimpleNamespace(uno=SimpleNamespace(createUnoStruct=lambda _: SimpleNamespace(), Enum=enum))


class ImpressFixtureSizingTests(unittest.TestCase):
    def test_actual_impress_populate_sets_sizing_before_requested_geometry_and_text(self):
        document = FixtureDocument()
        smoke.populate(engine(document.events), 'impress', document)
        shape, = document.shapes
        self.assertEqual(list(shape.properties.items()), PROPERTIES)
        self.assertIs(shape.properties['TextAutoGrowHeight'], False)
        self.assertIs(shape.properties['TextAutoGrowWidth'], False)
        self.assertEqual((shape.position, shape.size, shape.text),
                         ((2500, 2500), (20000, 6000), smoke.marker('impress')))
        self.assertEqual(len(document.pages), 1)
        self.assertEqual(document.pages[0].objects, [shape])
        property_rows = [row for row in document.events if row[0] == 'shape-property']
        self.assertEqual(property_rows, [('shape-property', *item) for item in PROPERTIES])
        last_property = max(i for i, row in enumerate(document.events) if row[0] == 'shape-property')
        self.assertLess(last_property, next(i for i, row in enumerate(document.events) if row[0] == 'position'))
        self.assertLess(last_property, next(i for i, row in enumerate(document.events) if row[0] == 'size'))
        self.assertEqual([row[0] for row in document.events if row[0] in ('position', 'size', 'add', 'text')],
                         ['position', 'size', 'add', 'text'])

    def test_actual_helper_opt_in_returns_same_shape_without_font_or_dirty_flag_setters(self):
        document = FixtureDocument()
        page = document.pages[0]
        shape = smoke._shape(engine(document.events), document, page, TEXT, 'unchanged 한글',
                             (2500, 2500), (20000, 6000), fixed_text_frame=True)
        self.assertIs(shape, document.shapes[0])
        self.assertEqual(list(shape.properties.items()), PROPERTIES)
        self.assertEqual([row[1] for row in document.events if row[0] == 'shape-property'],
                         ['TextAutoGrowHeight', 'TextAutoGrowWidth', 'TextFitToSize'])

    def test_default_text_shape_retains_original_shared_helper_calls(self):
        document = FixtureDocument()
        page = document.pages[0]
        shape = smoke._shape(engine(document.events), document, page, TEXT, 'shared', (1, 2), (3, 4))
        self.assertEqual(shape.properties, {})
        self.assertEqual(document.events,
                         [('create-shape', TEXT), ('position', (1, 2)), ('size', (3, 4)),
                          ('add', shape), ('text', 'shared')])

    def test_draw_populate_keeps_original_rectangle_geometry_text_and_native_calls(self):
        document = FixtureDocument()
        smoke.populate(engine(document.events), 'draw', document)
        shape, = document.shapes
        self.assertEqual(shape.properties, {})
        self.assertEqual(document.events,
                         [('create-shape', RECTANGLE), ('position', (1000, 1000)),
                          ('size', (6000, 2500)), ('add', shape), ('text', smoke.marker('draw'))])

    def test_actual_shared_pdf_draw_and_impress_builders_do_not_opt_in(self):
        for module in ('draw', 'impress'):
            with self.subTest(module=module):
                document = FixtureDocument()
                case = next(value for value in pdf.case_specs() if value['module'] == module)
                pdf._populate(engine(document.events), case, document)
                self.assertEqual(len(document.shapes), case['pageCount'])
                self.assertTrue(all(shape.properties == {} for shape in document.shapes))
                self.assertFalse(any(row[0] in ('enum', 'shape-property') for row in document.events))
                self.assertTrue(all(shape.position == (1500, 1500) and shape.size == (24000, 7000)
                                    for shape in document.shapes))

    def test_each_required_property_failure_preserves_exception_before_geometry_or_text(self):
        for name, _ in PROPERTIES:
            with self.subTest(name=name):
                original = RuntimeError('sizing property unsupported: ' + name)
                document = FixtureDocument(failure=(name, original))
                with self.assertRaises(RuntimeError) as captured:
                    smoke.populate(engine(document.events), 'impress', document)
                self.assertIs(captured.exception, original)
                self.assertEqual(sum(row[:2] == ('shape-property', name) for row in document.events), 1)
                self.assertFalse(any(row[0] in ('position', 'size', 'add', 'text') for row in document.events))

    def test_enum_failure_is_not_swallowed_or_retried(self):
        original = RuntimeError('enum construction failed')
        document = FixtureDocument()
        with self.assertRaises(RuntimeError) as captured:
            smoke.populate(engine(document.events, enum_failure=original), 'impress', document)
        self.assertIs(captured.exception, original)
        self.assertEqual(sum(row[0] == 'enum' for row in document.events), 1)
        self.assertFalse(any(row[0] in ('position', 'size', 'add', 'text') for row in document.events))

    def test_nonboolean_or_nontext_opt_in_rejects_before_shape_creation(self):
        for service, selector in ((TEXT, 1), (TEXT, None), (RECTANGLE, True)):
            with self.subTest(service=service, selector=selector):
                document = FixtureDocument()
                with self.assertRaises(AssertionError):
                    smoke._shape(engine(document.events), document, document.pages[0], service,
                                 'unchanged', (1, 2), (3, 4), fixed_text_frame=selector)
                self.assertEqual(document.events, [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
