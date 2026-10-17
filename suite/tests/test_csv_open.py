"""Exercise the real attach/load boundary with fake UNO, not a GUI/CSV parser."""
from contextlib import ExitStack
import importlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch


SUITE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SUITE / 'worker'))
CSV_FILTER = 'Text - txt - csv (StarCalc)'


class CsvOpenTests(unittest.TestCase):
    def setUp(self):
        self.native = importlib.import_module('native')
        self.modules = json.loads((SUITE / 'config/product.json').read_text(encoding='utf-8'))['modules']
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()

    def attach(self, module, path, load_mode='accepted'):
        self.calls, self.loads = [], []
        self.aborted, self.approved = [], []
        peer = NS(setProperty=lambda *a: None, getProperty=lambda *a: module['displayName'],
                  setPosSize=lambda *a: None, getWindowHandle=lambda *a: 456,
                  setVisible=lambda value: self.calls.append(('visible', value)))
        frame = NS(initialize=lambda *a: None, setName=lambda *a: None,
                   registerDispatchProviderInterceptor=lambda *a: None,
                   activate=lambda: self.calls.append(('activate',)))

        def load(url, target, flags, properties):
            props = {p.Name: p.Value for p in properties}
            self.loads.append((url, target, flags, props))
            self.calls.append(('load',))
            # SfxObjectShell::HandleFilter requests options when absent. The
            # real abort-only handler must still reject any such request.
            if load_mode == 'csv-options' and props.get('FilterName') == CSV_FILTER and props.get('FilterOptions'):
                return object()
            if load_mode in ('csv-options', 'interaction'):
                abort = NS(select=lambda: self.aborted.append(True))
                approve = NS(select=lambda: self.approved.append(True))
                props['InteractionHandler'].handle(NS(getContinuations=lambda: (
                    NS(queryInterface=lambda kind: approve if kind == 'Approve' else None),
                    NS(queryInterface=lambda kind: abort if kind == 'Abort' else None))))
                return None
            return None if load_mode == 'none' else object()

        services = {
            'com.sun.star.frame.Desktop': NS(
                getFrames=lambda: NS(append=lambda value: self.calls.append(('append', value))),
                loadComponentFromURL=load),
            'com.sun.star.awt.Toolkit': NS(createSystemChild=lambda *a: peer),
            'com.sun.star.frame.Frame': frame,
        }
        context = NS(ServiceManager=NS(createInstanceWithContext=lambda name, ctx: services[name]))
        uno = NS(Any=lambda kind, value: (kind, value), createUnoStruct=lambda name: NS(),
                 getTypeByName=lambda name: 'Abort' if name.endswith('XInteractionAbort') else name)
        windows = NS(validate_parent=lambda hwnd: self.calls.append(('parent', hwnd)),
                     validate_child=lambda child, parent: self.calls.append(('child', child, parent)))
        backend = self.native.UnoBackend(self.root, window_api=windows, uno_loader=lambda: uno,
                                        connector=lambda *a: context)
        backend._start_runtime = lambda: None
        backend._isolate_legacy_style_controls = lambda *a: self.calls.append(('isolate',))
        backend._bootstrap_ui = lambda *a: self.calls.append(('bootstrap',))
        with ExitStack() as stack:
            stack.enter_context(patch.dict(sys.modules, {
                'uno': uno, 'unohelper': NS(Base=type('UnoBase', (), {})),
                'com.sun.star.task': NS(XInteractionHandler=type('XInteractionHandler', (), {})),
            }))
            stack.enter_context(patch.object(self.native, 'make_interceptor', return_value=object()))
            transaction = stack.enter_context(patch('calc_save.CalcSaveTransaction'))
            result = backend.attach(123, module, 640, 480, path)
            if module['factory'] == 'private:factory/scalc':
                transaction.assert_called_once_with(backend, module['filters'], path, 123, 456)
            else:
                transaction.assert_not_called()
        return result

    def test_csv_load_uses_native_detection_without_changing_source_or_ownership(self):
        samples = (
            ('ordinary.csv', b'Name,Amount\nAlice,17\n'),
            ('quoted.CSV', b'Name;Amount\n"A;B";25\n'),
            ('korean.CsV', '\uc774\ub984\t\uac12\n\ud55c\uae00\t42\n'.encode('cp949')),
            ('unicode.csv', 'Name|Amount\n\ud55c\uae00|42\n'.encode('utf-16')),
        )
        for name, data in samples:
            with self.subTest(name=name):
                path = self.root / name
                path.write_bytes(data)
                result = self.attach(self.modules['calc'], path, 'csv-options')
                self.assertEqual({'parentHwnd': 123, 'childHwnd': 456}, result)
                url, target, flags, props = self.loads[0]
                self.assertEqual(path.as_uri(), url)
                self.assertTrue(target.startswith('OpenGeul_'))
                self.assertEqual(4, flags)
                self.assertEqual(CSV_FILTER, props['FilterName'])
                # Detection is delegated to LO; these bytes are deliberately
                # not parsed here and do not claim real-engine charset coverage.
                tokens = props['FilterOptions'].split(',')
                self.assertEqual(['DETECT', '34', 'DETECT', '1', '', '0', 'false', 'false'], tokens)
                self.assertEqual(data, path.read_bytes())
                self.assertEqual([], self.aborted + self.approved)
                self.assertEqual(0, props['MacroExecutionMode'])
                self.assertEqual(0, props['UpdateDocMode'])
                self.assertIs(False, props['ReadOnly'])
                self.assertIs(True, props['Hidden'])
                self.assertIs(False, props['PickListEntry'])
                self.assertLess(self.calls.index(('bootstrap',)), self.calls.index(('load',)))
                self.assertLess(self.calls.index(('load',)), self.calls.index(('child', 456, 123)))
                self.assertLess(self.calls.index(('child', 456, 123)), self.calls.index(('visible', True)))
                self.assertLess(self.calls.index(('visible', True)), self.calls.index(('activate',)))

    def test_other_formats_factories_and_new_calc_keep_the_original_load_properties(self):
        cases = [('calc', suffix) for suffix in ('ods', 'xlsx', 'xls')]
        cases += [('writer', 'txt'), ('writer', 'csv'), ('base', 'odb'), ('calc', None)]
        for module_name, extension in cases:
            with self.subTest(module=module_name, extension=extension):
                path = None if extension is None else self.root / ('original.' + extension)
                if path is not None:
                    path.write_bytes(b'unchanged owned source')
                self.attach(self.modules[module_name], path)
                props = self.loads[0][3]
                self.assertEqual({'MacroExecutionMode', 'UpdateDocMode', 'ReadOnly', 'Hidden',
                                  'PickListEntry', 'InteractionHandler'}, set(props))
                if path is not None:
                    self.assertEqual(b'unchanged owned source', path.read_bytes())

    def test_csv_load_failure_and_unexpected_interactions_remain_fail_closed(self):
        path = self.root / 'rejected.csv'
        path.write_bytes(b'unchanged source')
        for mode in ('none', 'interaction'):
            with self.subTest(mode=mode):
                with self.assertRaises(self.native.WorkerError) as caught:
                    self.attach(self.modules['calc'], path, mode)
                self.assertEqual('open_failed', caught.exception.code)
                self.assertNotIn(('visible', True), self.calls)
                self.assertNotIn(('child', 456, 123), self.calls)
                self.assertEqual([], self.approved)
                self.assertEqual([True] if mode == 'interaction' else [], self.aborted)
                self.assertEqual(b'unchanged source', path.read_bytes())


if __name__ == '__main__':
    unittest.main()
