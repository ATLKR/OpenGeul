"""Fail-closed HOP #94 zoom adaptation; the Node suite executes the real host function."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('hop_zoom_patcher', ROOT/'scripts/prepare_hop_fixes.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
LOAD = '    inputHandler?.deactivate();\n    await canvasView?.loadDocument();\n    toolbar?.setEnabled(true);'

class DesktopZoomPatchTests(unittest.TestCase):
    def transform(self, text):
        self.assertTrue(callable(getattr(module, 'patch_desktop_zoom', None)), 'Missing desktop zoom transform')
        return module.patch_desktop_zoom(text)

    def test_restores_zoom_after_the_await_and_before_editor_activation(self):
        source = '// untouched before\n'+LOAD+'\n// untouched after\n'
        result = self.transform(source)
        self.assertIn('isTauriRuntime() ? canvasView?.getViewportManager().getZoom() : undefined', result)
        self.assertLess(result.index('const desktopZoom'), result.index('await canvasView?.loadDocument()'))
        self.assertLess(result.index('await canvasView?.loadDocument()'), result.index('.setZoom(desktopZoom)'))
        self.assertLess(result.index('.setZoom(desktopZoom)'), result.index('toolbar?.setEnabled(true)'))
        self.assertEqual(result.count('await canvasView?.loadDocument()'), 1)
        self.assertTrue(result.startswith('// untouched before\n'))
        self.assertTrue(result.endswith('\n// untouched after\n'))

    def test_missing_or_duplicated_anchor_fails(self):
        for source in ('', LOAD+LOAD, LOAD.replace('loadDocument()', 'loadDocument(false)')):
            with self.subTest(source=source[:30]):
                self.assertTrue(callable(getattr(module, 'patch_desktop_zoom', None)))
                with self.assertRaises(ValueError): module.patch_desktop_zoom(source)

    def test_existing_zoom_patch_or_name_collision_is_rejected(self):
        for source in ('const desktopZoom = 1;\n'+LOAD, self.transform(LOAD)):
            with self.assertRaises(ValueError): module.patch_desktop_zoom(source)

    def run_fixture(self, invalid_main=False):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); source=root/'hop'; host=source/'apps/studio-host'
            (host/'src/command').mkdir(parents=True)
            keyboard=host/'src/command/shortcut-map.ts'
            keyboard.write_text('...upstreamDefaultShortcuts.filter(([shortcut]) => !hopShortcutKeys.has(shortcutKey(shortcut))),\nexport function matchShortcut() {}\n')
            main=host/'src/main.ts'; original='not the reviewed source' if invalid_main else LOAD
            main.write_text(original)
            markup='<span class="md-shortcut">P</span> title="개체 속성 (P)"\n<script type="module" src="/src/main.ts"></script>'
            (host/'index.html').write_text(markup)
            overlay=root/'overlay/hop-fixes'; overlay.mkdir(parents=True)
            for name in ('toolbar-preferences.ts', 'toolbar-labels.ts', 'toolbar-labels.css'):
                (overlay/name).write_text('// existing toolbar fixture\n')
            ledger=source/'.opengeul-overlay.json'; ledger.write_text('{"existing":"preserved"}')
            before={p:p.read_bytes() for p in (main,keyboard,host/'index.html',ledger)}
            with patch.object(module, 'ROOT', root):
                if invalid_main:
                    with self.assertRaises(ValueError):module.patch(source)
                    for p,data in before.items():self.assertEqual(p.read_bytes(),data)
                    return
                module.patch(source)
            self.assertIn('.setZoom(desktopZoom)', main.read_text())
            state=json.loads(ledger.read_text())
            self.assertEqual(state['existing'],'preserved')
            self.assertTrue(state['toolbarLabelPreference']['defaultVisible'])
            self.assertEqual(state['hopBackports'][0]['issues'],[95,100])
            evidence=state['desktopZoomPreservation']
            self.assertEqual(evidence['issue'],94)
            self.assertEqual(evidence['beforeSha256'],hashlib.sha256(original.encode()).hexdigest())
            self.assertEqual(evidence['afterSha256'],hashlib.sha256(main.read_bytes()).hexdigest())
            self.assertEqual(evidence['upstreamCommit'],'2b1189b3079045481134864d9ccb02ca535ea6bb')

    def test_actual_patch_entrypoint_installs_fix_and_keeps_previous_provenance(self):self.run_fixture()
    def test_invalid_main_fails_before_mutating_existing_backports(self):self.run_fixture(invalid_main=True)

if __name__=='__main__':unittest.main()
