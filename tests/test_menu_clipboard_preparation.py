"""Menu clipboard preparation rejects incomplete or forged input before writing.

The small source strings below contain reviewed replacement anchors. Patching
their input digests isolates the preparation boundary; it does not certify the
runtime behavior of these deliberately incomplete TypeScript/Rust fixtures.
"""
from pathlib import Path
from contextlib import ExitStack, contextmanager
import copy
import hashlib
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import menu_clipboard as m
import prepare_upstream as upstream


ENGINE = 'third_party/rhwp/rhwp-studio/src/engine/'
HANDLER = ENGINE+'input-handler.ts'
KEYBOARD = ENGINE+'input-handler-keyboard.ts'
LIB = 'apps/desktop/src-tauri/src/lib.rs'
WINDOWS = 'apps/desktop/src-tauri/src/windows.rs'
CONFIG = 'apps/desktop/src-tauri/tauri.windows.conf.json'
HELPER = ENGINE+'opengeul-menu-clipboard.ts'
SOURCE_KEYS = {HANDLER, KEYBOARD, LIB, WINDOWS, CONFIG}
HWPX_SUFFIX = '\n// miniature reviewed HWPX handler registrations\n'
REVIEWED_PINS = {
    HANDLER: '6b88aaae0cb18f742957733ed9f39264bd5345f5622348ce840e3eb89598155e',
    KEYBOARD: '6d9e30cd4398beefed92f86fda6e331ac0e5c0876424b620076a344bbc50de49',
}

HANDLER_SOURCE = """import { isBodyControl } from './picture-hit-policy';
import * as _keyboard from './input-handler-keyboard';

export class InputHandler {
  /** 붙이기 (커맨드 시스템용 — 컨텍스트 메뉴/도구 상자에서 호출) */
  performPaste(): boolean {
    if (this.editMode === 'form') return false;
    this.focusTextarea();
    return document.execCommand('paste');
  }
}
"""
KEYBOARD_SOURCE = r"""import { isBodyControl } from './picture-hit-policy';
import { InsertTextCommand, SplitParagraphCommand, SplitParagraphInCellCommand } from './command';

function pastePlainText(this: any, text: string, hasSelection: boolean): void {
  if (hasSelection) {
    this.deleteSelection({ deferRecord: true });
  }
  if (!text) return;

  const lines = text.split(/\r?\n/);
  for (let i = 0; i < lines.length; i++) {
    if (lines[i]) {
      this.executeOperation({ kind: 'command', command: new InsertTextCommand(this.cursor.getPosition(), lines[i]) });
    }
    if (i < lines.length - 1) {
      const position = this.cursor.getPosition();
      const command = this.cursor.isInCell()
        ? new SplitParagraphInCellCommand(position)
        : new SplitParagraphCommand(position);
      this.executeOperation({ kind: 'command', command });
    }
  }
}

export function captureAsyncClipboardContext(self: any): { isCurrent(): boolean; dispose(): void } {
  return self.clipboardContext;
}
"""
LIB_SOURCE = """use tauri::{AppHandle, Emitter, Manager};

pub fn run() {
    let app = tauri::Builder::default()
        .setup(|app| {
            #[cfg(target_os = "macos")]
            menu::install(app)?;
            #[cfg(not(target_os = "macos"))]
            app.set_menu(tauri::menu::Menu::new(app)?)?;
            #[cfg(not(target_os = "macos"))]
            queue_open_paths(app.handle(), startup_document_paths());
            if let Some(window) = app.get_webview_window("main") {
                windows::install_editor_window_minimum(&window);
                windows::attach_document_drop_handler(app.handle(), &window);
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build HOP desktop app");
}
"""
WINDOWS_SOURCE = """use tauri::{AppHandle, WebviewUrl, WebviewWindowBuilder};

pub fn create_editor_window_with_label(app: &AppHandle, label: &str) -> Result<(), String> {
    let builder = WebviewWindowBuilder::new(app, label, WebviewUrl::App("index.html".into()))
        .title("OpenGeul")
        .inner_size(1100.0, 760.0);
    #[cfg(windows)]
    let builder = builder.zoom_hotkeys_enabled(true);

    let window = builder
        .build()
        .map_err(|e| format!("새 창 생성 실패: {}", e))?;
    attach_document_drop_handler(app, &window);
    Ok(())
}
"""


def digest(data):
    return hashlib.sha256(data).hexdigest()


def files(root):
    return {str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob('*') if path.is_file()}


class MenuClipboardPreparationTests(unittest.TestCase):
    def fixture(self, root):
        config = {'app': {'windows': [{
            'label': 'main', 'title': 'OpenGeul', 'url': 'index.html',
            'width': 1280, 'height': 900, 'minWidth': 960, 'minHeight': 720,
            'zoomHotkeysEnabled': True,
        }]}, 'fixtureUnrelated': {'preserve': True}}
        texts = {HANDLER: HANDLER_SOURCE, KEYBOARD: KEYBOARD_SOURCE,
                 LIB: LIB_SOURCE, WINDOWS: WINDOWS_SOURCE,
                 CONFIG: json.dumps(config, indent=2)+'\n'}
        paths = set(texts)
        paths.update(ENGINE+name for name in upstream.ASYNC_CLIPBOARD_SOURCE_SHA256)
        paths.update('third_party/rhwp/rhwp-studio/src/'+name
                     for name in upstream.IMAGE_INSERTION_SOURCE_SHA256)
        paths.update(upstream.ASYNC_FONT_SOURCE_SHA256)
        for name in paths:
            path = root/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(texts.get(name, '// unchanged predecessor '+name+'\n'), encoding='utf-8')
        proofs = []
        for pins, prefix in (
                (upstream.ASYNC_CLIPBOARD_SOURCE_SHA256, ENGINE),
                (upstream.IMAGE_INSERTION_SOURCE_SHA256, 'third_party/rhwp/rhwp-studio/src/'),
                (upstream.ASYNC_FONT_SOURCE_SHA256, '')):
            proofs.append({'beforeSha256': dict(pins),
                           'afterSha256': {name: digest((root/(prefix+name)).read_bytes())
                                           for name in pins}})
        pins = {name: digest((root/name).read_bytes()) for name in REVIEWED_PINS}
        # Expected miniature bytes pin the preparation boundary. Runtime behavior
        # is checked by the helper tests, not these incomplete source snippets.
        prepared = dict(texts)
        prepared[HANDLER] = prepared[HANDLER].replace(m.HANDLER_IMPORT,
            m.HANDLER_IMPORT+"\nimport { performMenuPaste } from './opengeul-menu-clipboard';")
        prepared[HANDLER] = prepared[HANDLER].replace(m.OLD_MENU_PASTE, m.NEW_MENU_PASTE)
        prepared[KEYBOARD] = prepared[KEYBOARD].replace(m.OLD_PLAIN_PASTE, m.NEW_PLAIN_PASTE)
        prepared[LIB] = prepared[LIB].replace(m.LIB_ANCHOR, m.LIB_ANCHOR+m.MAIN_BUILDER)
        prepared[WINDOWS] = prepared[WINDOWS].replace(m.WINDOWS_ANCHOR, m.WINDOWS_BUILDER)
        final_config = copy.deepcopy(config)
        final_config['app']['windows'][0]['create'] = False
        prepared[CONFIG] = json.dumps(final_config, ensure_ascii=False, indent=2)+'\n'
        after = {name: digest(text.encode('utf-8')) for name, text in prepared.items()}
        if not hasattr(self, '_contracts'):
            self._contracts = {}
        self._contracts[root] = {
            'INPUT_NATIVE_SHA256': {name: digest((root/name).read_bytes()) for name in (LIB, WINDOWS, CONFIG)},
            'INPUT_NATIVE_CRLF_SHA256': {
                name: digest((root/name).read_bytes().replace(b'\n', b'\r\n'))
                for name in (LIB, WINDOWS, CONFIG)},
            'LIB_HWPX_INPUT_SHA256': digest((LIB_SOURCE+HWPX_SUFFIX).encode('utf-8')),
            'LIB_HWPX_CRLF_INPUT_SHA256': digest((LIB_SOURCE+HWPX_SUFFIX).replace('\n', '\r\n').encode('utf-8')),
            'PHASE_SOURCE_SHA256': {'prepared': after, 'hwpx': {
                **after, LIB: digest((prepared[LIB]+HWPX_SUFFIX).encode('utf-8'))}, 'hwpx-windows': {
                **after, LIB: digest((prepared[LIB]+HWPX_SUFFIX).replace('\n', '\r\n').encode('utf-8'))}},
        }
        return proofs, pins, config

    @contextmanager
    def fixture_pins(self, root, pins):
        with ExitStack() as stack:
            stack.enter_context(patch.object(m, 'INPUT_SOURCE_SHA256', pins))
            for name, value in self._contracts[root].items():
                stack.enter_context(patch.object(m, name, value))
            yield

    def contract_inputs(self, root):
        prepared_files = {name: digest((root/name).read_bytes()) for name in SOURCE_KEYS | {HELPER}}
        helpers = {name: digest((ROOT/name).read_bytes()) for name in
                   ('overlay/menu-clipboard.ts', 'scripts/prepare_hwpx.py')}
        return prepared_files, helpers

    def assert_rejected_unchanged(self, root, proofs, pins=None, exceptions=(ValueError,)):
        original_files = files(root)
        original_proofs = copy.deepcopy(proofs)
        if pins is None:
            with self.assertRaises(exceptions):
                m.apply(root, *proofs)
        else:
            with self.fixture_pins(root, pins):
                with self.assertRaises(exceptions):
                    m.apply(root, *proofs)
        self.assertEqual(files(root), original_files)
        self.assertEqual(proofs, original_proofs)

    def test_exported_input_pins_are_the_reviewed_final_engine_sources(self):
        self.assertEqual(m.INPUT_SOURCE_SHA256, REVIEWED_PINS)

    def test_unreviewed_engine_bytes_are_rejected_before_native_or_helper_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proofs, _, _ = self.fixture(root)
            self.assert_rejected_unchanged(root, proofs)

    def test_missing_input_is_rejected_before_any_write_or_proof_mutation(self):
        for name in SOURCE_KEYS:
            with self.subTest(file=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                proofs, pins, _ = self.fixture(root)
                (root/name).unlink()
                self.assert_rejected_unchanged(root, proofs, pins, (ValueError, FileNotFoundError))

    def test_all_predecessors_reject_incomplete_forged_and_extra_proof_fields(self):
        def change_before(proof):
            name = next(iter(proof['beforeSha256']))
            proof['beforeSha256'][name] = '0'*64

        def change_after(proof):
            name = next(iter(proof['afterSha256']))
            proof['afterSha256'][name] = '0'*64

        mutations = {
            'missing-before': lambda proof: proof.pop('beforeSha256'),
            'missing-after': lambda proof: proof.pop('afterSha256'),
            'extra-top-field': lambda proof: proof.update(unreviewed=True),
            'incomplete-before': lambda proof: proof['beforeSha256'].pop(next(iter(proof['beforeSha256']))),
            'incomplete-after': lambda proof: proof['afterSha256'].pop(next(iter(proof['afterSha256']))),
            'extra-before-key': lambda proof: proof['beforeSha256'].update(unreviewed='0'*64),
            'extra-after-key': lambda proof: proof['afterSha256'].update(unreviewed='0'*64),
            'forged-before': change_before,
            'forged-after': change_after,
        }
        for stage in range(3):
            for case, mutate in mutations.items():
                with self.subTest(stage=stage, case=case), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    proofs, pins, _ = self.fixture(root)
                    mutate(proofs[stage])
                    self.assert_rejected_unchanged(root, proofs, pins)

    def test_predecessor_actual_bytes_must_match_their_after_maps(self):
        for name in ('third_party/rhwp/rhwp-studio/src/command/commands/insert.ts',
                     'apps/studio-host/src/main.ts', 'apps/studio-host/src/ui/toolbar.ts'):
            with self.subTest(file=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                proofs, pins, _ = self.fixture(root)
                with (root/name).open('ab') as output:
                    output.write(b'// changed after predecessor proof\n')
                self.assert_rejected_unchanged(root, proofs, pins)

    def test_predecessor_maps_must_be_objects(self):
        for stage in range(3):
            for field in ('beforeSha256', 'afterSha256'):
                for invalid in (None, [], 'invalid'):
                    with self.subTest(stage=stage, field=field, invalid=invalid), tempfile.TemporaryDirectory() as directory:
                        root = Path(directory)
                        proofs, pins, _ = self.fixture(root)
                        proofs[stage][field] = invalid
                        self.assert_rejected_unchanged(root, proofs, pins)

    def test_reviewed_replacement_anchors_must_be_unique_and_present(self):
        for name, old, new in (
                (HANDLER, "return document.execCommand('paste');", "return false;"),
                (KEYBOARD, 'function pastePlainText(', 'function changedPastePlainText('),
                (LIB, '.setup(|app| {', '.setup(|changed| {'),
                (WINDOWS, 'let builder = builder.zoom_hotkeys_enabled(true);', 'let builder = builder;')):
            with self.subTest(file=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                proofs, pins, _ = self.fixture(root)
                path = root/name
                self.assertIn(old, path.read_text())
                path.write_text(path.read_text().replace(old, new), encoding='utf-8')
                if name in pins:
                    pins[name] = digest(path.read_bytes())
                    for proof, prefix in zip(proofs, (ENGINE, 'third_party/rhwp/rhwp-studio/src/', '')):
                        for key in proof['afterSha256']:
                            if prefix+key == name:
                                proof['afterSha256'][key] = pins[name]
                else:
                    self._contracts[root]['INPUT_NATIVE_SHA256'][name] = digest(path.read_bytes())
                self.assert_rejected_unchanged(root, proofs, pins)

    def test_duplicate_reviewed_anchors_are_rejected_before_any_write(self):
        for name in (HANDLER, KEYBOARD, LIB, WINDOWS):
            with self.subTest(file=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                proofs, pins, _ = self.fixture(root)
                path = root/name
                path.write_bytes(path.read_bytes()*2)
                if name in pins:
                    pins[name] = digest(path.read_bytes())
                    for proof, prefix in zip(proofs, (ENGINE, 'third_party/rhwp/rhwp-studio/src/', '')):
                        for key in proof['afterSha256']:
                            if prefix+key == name:
                                proof['afterSha256'][key] = pins[name]
                else:
                    self._contracts[root]['INPUT_NATIVE_SHA256'][name] = digest(path.read_bytes())
                self.assert_rejected_unchanged(root, proofs, pins)

    def test_invalid_windows_configuration_is_rejected_before_engine_writes(self):
        for case in ('invalid-json', 'missing-main', 'duplicate-main'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                proofs, pins, config = self.fixture(root)
                if case == 'invalid-json':
                    (root/CONFIG).write_text('{', encoding='utf-8')
                else:
                    config['app']['windows'] = ([] if case == 'missing-main'
                                                else config['app']['windows']*2)
                    (root/CONFIG).write_text(json.dumps(config), encoding='utf-8')
                self._contracts[root]['INPUT_NATIVE_SHA256'][CONFIG] = digest((root/CONFIG).read_bytes())
                self.assert_rejected_unchanged(root, proofs, pins)

    def test_changed_native_input_is_rejected_before_any_write(self):
        for name in (LIB, WINDOWS, CONFIG):
            with self.subTest(file=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                proofs, pins, _ = self.fixture(root)
                with (root/name).open('ab') as output:
                    output.write(b'\n')
                self.assert_rejected_unchanged(root, proofs, pins)

    def test_output_pin_mismatch_is_rejected_before_any_write_or_proof_mutation(self):
        for name in SOURCE_KEYS:
            with self.subTest(file=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                proofs, pins, _ = self.fixture(root)
                self._contracts[root]['PHASE_SOURCE_SHA256']['prepared'][name] = '0'*64
                self.assert_rejected_unchanged(root, proofs, pins)

    def test_existing_helper_is_rejected_before_any_source_or_proof_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proofs, pins, _ = self.fixture(root)
            (root/HELPER).write_bytes(b'// existing helper must remain unchanged\n')
            self.assert_rejected_unchanged(root, proofs, pins)

    def test_success_preserves_options_and_predecessor_keys_and_final_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proofs, pins, config = self.fixture(root)
            originals = files(root)
            old_proofs = copy.deepcopy(proofs)
            with self.fixture_pins(root, pins):
                proof = m.apply(root, *proofs)
                m.validate(root, proof)
            self.assertEqual(set(proof), {'beforeSha256', 'afterSha256', 'helperSha256', 'hwpxPatcherSha256'})
            self.assertIsNone(proof['hwpxPatcherSha256'])
            self.assertEqual(set(proof['beforeSha256']), SOURCE_KEYS)
            self.assertEqual(set(proof['afterSha256']), SOURCE_KEYS)
            self.assertEqual(proof['beforeSha256'], {name: digest(originals[name]) for name in SOURCE_KEYS})
            self.assertEqual(proof['afterSha256'], {name: digest((root/name).read_bytes()) for name in SOURCE_KEYS})
            self.assertEqual(proof['helperSha256'], digest((root/HELPER).read_bytes()))
            self.assertEqual((root/HELPER).read_bytes(), (ROOT/'overlay/menu-clipboard.ts').read_bytes())
            for previous, updated, prefix in zip(old_proofs, proofs, (ENGINE, 'third_party/rhwp/rhwp-studio/src/', '')):
                self.assertEqual(set(updated), set(previous))
                self.assertEqual(updated['beforeSha256'], previous['beforeSha256'])
                self.assertEqual(set(updated['afterSha256']), set(previous['afterSha256']))
                self.assertEqual(updated['afterSha256'], {
                    key: digest((root/(prefix+key)).read_bytes()) for key in previous['afterSha256']})
            for name in set(originals)-SOURCE_KEYS:
                self.assertEqual((root/name).read_bytes(), originals[name])
            expected_config = copy.deepcopy(config)
            expected_config['app']['windows'][0]['create'] = False
            self.assertEqual(json.loads((root/CONFIG).read_text()), expected_config)
            handler = (root/HANDLER).read_text()
            keyboard = (root/KEYBOARD).read_text()
            lib = (root/LIB).read_text()
            windows = (root/WINDOWS).read_text()
            self.assertIn("from './opengeul-menu-clipboard'", handler)
            self.assertNotIn("document.execCommand('paste')", handler)
            self.assertIn('Promise<boolean>', handler)
            self.assertIn("kind: 'snapshot'", keyboard)
            self.assertIn('pastePlainText', keyboard)
            self.assertIn('WebviewWindowBuilder::from_config', lib)
            self.assertIn('.enable_clipboard_access()', lib)
            self.assertIn('#[cfg(windows)]', lib)
            self.assertIn('.enable_clipboard_access()', windows)
            self.assertIn('#[cfg(windows)]', windows)
            self.assertIn('zoom_hotkeys_enabled(true)', windows)

    def test_apply_rejects_replay_without_further_source_or_proof_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proofs, pins, _ = self.fixture(root)
            with self.fixture_pins(root, pins):
                m.apply(root, *proofs)
            self.assert_rejected_unchanged(root, proofs, pins)

    def test_validation_rejects_tampered_final_source_or_helper(self):
        for name in SOURCE_KEYS | {HELPER}:
            with self.subTest(file=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                proofs, pins, _ = self.fixture(root)
                with self.fixture_pins(root, pins):
                    proof = m.apply(root, *proofs)
                    with (root/name).open('ab') as output:
                        output.write(b'// changed after menu preparation\n')
                    before = files(root)
                    old_proof = copy.deepcopy(proof)
                    with self.assertRaises(ValueError):
                        m.validate(root, proof)
                    self.assertEqual(files(root), before)
                    self.assertEqual(proof, old_proof)

    def test_validation_rejects_coordinated_final_bytes_and_ledger_forgery(self):
        for name in SOURCE_KEYS | {HELPER}:
            with self.subTest(file=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                proofs, pins, _ = self.fixture(root)
                with self.fixture_pins(root, pins):
                    proof = m.apply(root, *proofs)
                    with (root/name).open('ab') as output:
                        output.write(b'// forged final source and matching ledger\n')
                    if name == HELPER:
                        proof['helperSha256'] = digest((root/name).read_bytes())
                    else:
                        proof['afterSha256'][name] = digest((root/name).read_bytes())
                    before = files(root)
                    old_proof = copy.deepcopy(proof)
                    with self.assertRaises(ValueError):
                        m.validate(root, proof)
                    self.assertEqual(files(root), before)
                    self.assertEqual(proof, old_proof)

    def test_validation_rejects_incomplete_extra_and_forged_final_proof(self):
        mutations = {
            'missing-helper': lambda proof: proof.pop('helperSha256'),
            'missing-patcher': lambda proof: proof.pop('hwpxPatcherSha256'),
            'extra-field': lambda proof: proof.update(unreviewed=True),
            'missing-before-key': lambda proof: proof['beforeSha256'].pop(LIB),
            'missing-after-key': lambda proof: proof['afterSha256'].pop(WINDOWS),
            'extra-before-key': lambda proof: proof['beforeSha256'].update(unreviewed='0'*64),
            'extra-after-key': lambda proof: proof['afterSha256'].update(unreviewed='0'*64),
            'forged-engine-input': lambda proof: proof['beforeSha256'].update({HANDLER: '0'*64}),
            'invalid-native-input': lambda proof: proof['beforeSha256'].update({LIB: 'invalid'}),
            'forged-final-hash': lambda proof: proof['afterSha256'].update({KEYBOARD: '0'*64}),
            'forged-helper-hash': lambda proof: proof.update(helperSha256='0'*64),
            'invalid-helper-hash': lambda proof: proof.update(helperSha256=[]),
            'premature-patcher-hash': lambda proof: proof.update(hwpxPatcherSha256='0'*64),
        }
        for case, mutate in mutations.items():
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                proofs, pins, _ = self.fixture(root)
                with self.fixture_pins(root, pins):
                    proof = m.apply(root, *proofs)
                    mutate(proof)
                    before = files(root)
                    old_proof = copy.deepcopy(proof)
                    with self.assertRaises(ValueError):
                        m.validate(root, proof)
                    self.assertEqual(files(root), before)
                    self.assertEqual(proof, old_proof)

    def test_contract_requires_hwpx_phase_by_default_and_accepts_prepared_explicitly(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proofs, pins, _ = self.fixture(root)
            with self.fixture_pins(root, pins):
                proof = m.apply(root, *proofs)
                prepared, helpers = self.contract_inputs(root)
                m.validate_contract(proof, prepared, helpers, final=False)
                with self.assertRaises(ValueError):
                    m.validate_contract(proof, prepared, helpers)

    def test_hwpx_input_produces_the_reviewed_final_phase_and_patcher_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proofs, pins, _ = self.fixture(root)
            (root/LIB).write_text(LIB_SOURCE+HWPX_SUFFIX, encoding='utf-8')
            with self.fixture_pins(root, pins):
                proof = m.apply(root, *proofs)
                prepared, helpers = self.contract_inputs(root)
                m.validate(root, proof)
                m.validate_contract(proof, prepared, helpers)
                self.assertEqual(proof['afterSha256'], m.PHASE_SOURCE_SHA256['hwpx'])
                self.assertEqual(proof['beforeSha256'][LIB], m.LIB_HWPX_INPUT_SHA256)
                self.assertEqual(proof['hwpxPatcherSha256'], helpers['scripts/prepare_hwpx.py'])

    def test_exact_native_crlf_inputs_are_validated_before_normalizing_outputs_to_lf(self):
        for phase in ('prepared', 'hwpx'):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                proofs, pins, _ = self.fixture(root)
                if phase == 'hwpx':
                    (root/LIB).write_bytes((LIB_SOURCE+HWPX_SUFFIX).encode('utf-8'))
                for name in (LIB, WINDOWS, CONFIG):
                    path = root/name
                    path.write_bytes(path.read_bytes().replace(b'\n', b'\r\n'))
                original = files(root)
                with self.fixture_pins(root, pins):
                    proof = m.apply(root, *proofs)
                    m.validate(root, proof)
                    prepared, helpers = self.contract_inputs(root)
                    m.validate_contract(proof, prepared, helpers, final=phase == 'hwpx')
                    self.assertEqual(proof['afterSha256'], m.PHASE_SOURCE_SHA256[phase])
                    for name in (LIB, WINDOWS, CONFIG):
                        self.assertEqual(proof['beforeSha256'][name], digest(original[name]))
                        self.assertNotIn(b'\r', (root/name).read_bytes())

    def test_stray_cr_mixed_endings_and_unreviewed_crlf_variants_are_rejected(self):
        for name in SOURCE_KEYS:
            for variant in ('stray-cr', 'mixed-endings', 'extra-crlf'):
                with self.subTest(file=name, variant=variant), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    proofs, pins, _ = self.fixture(root)
                    path = root/name
                    data = path.read_bytes()
                    if variant == 'stray-cr': data = b'\r'+data
                    elif variant == 'mixed-endings': data = data.replace(b'\n', b'\r\n', 1)
                    else: data = data.replace(b'\n', b'\r\n')+b'\r\n'
                    path.write_bytes(data)
                    # Keep ledgers self-consistent to prove byte pins reject the
                    # variant before newline normalization can erase differences.
                    for proof, prefix in zip(proofs, (ENGINE, 'third_party/rhwp/rhwp-studio/src/', '')):
                        for key in proof['afterSha256']:
                            if prefix+key == name:
                                proof['afterSha256'][key] = digest(data)
                    self.assert_rejected_unchanged(root, proofs, pins)

    def test_refresh_hwpx_lib_accepts_only_the_exact_transition_without_writing_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proofs, pins, _ = self.fixture(root)
            with self.fixture_pins(root, pins):
                proof = m.apply(root, *proofs)
                old_proof = copy.deepcopy(proof)
                with (root/LIB).open('ab') as output:
                    output.write(HWPX_SUFFIX.encode('utf-8'))
                before = files(root)
                m.refresh_hwpx_lib(root, proof)
                self.assertEqual(files(root), before)
                self.assertEqual(proof['beforeSha256'], old_proof['beforeSha256'])
                self.assertEqual(proof['helperSha256'], old_proof['helperSha256'])
                self.assertEqual(set(proof), set(old_proof))
                self.assertEqual(proof['afterSha256'], m.PHASE_SOURCE_SHA256['hwpx'])
                prepared, helpers = self.contract_inputs(root)
                self.assertEqual(proof['hwpxPatcherSha256'], helpers['scripts/prepare_hwpx.py'])
                m.validate_contract(proof, prepared, helpers)
                unchanged = copy.deepcopy(proof)
                with self.assertRaises(ValueError):
                    m.refresh_hwpx_lib(root, proof)
                self.assertEqual(proof, unchanged)
                self.assertEqual(files(root), before)

    def test_refresh_accepts_the_reviewed_windows_crlf_hwpx_lib(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proofs, pins, _ = self.fixture(root)
            with self.fixture_pins(root, pins):
                proof = m.apply(root, *proofs)
                lib = (root/LIB).read_bytes()+HWPX_SUFFIX.encode('utf-8')
                (root/LIB).write_bytes(lib.replace(b'\n', b'\r\n'))
                before = files(root)
                m.refresh_hwpx_lib(root, proof)
                self.assertEqual(files(root), before)
                self.assertEqual(proof['afterSha256'], m.PHASE_SOURCE_SHA256['hwpx-windows'])
                prepared, helpers = self.contract_inputs(root)
                m.validate_contract(proof, prepared, helpers)
                m.validate(root, proof)
                self.assertIn(b'\r\n', (root/LIB).read_bytes())

    def test_refresh_rejects_wrong_lib_or_other_file_tamper_without_proof_mutation(self):
        for case in ('unchanged-lib', 'unreviewed-lib', 'changed-engine', 'changed-config', 'changed-helper', 'forged-proof'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                proofs, pins, _ = self.fixture(root)
                with self.fixture_pins(root, pins):
                    proof = m.apply(root, *proofs)
                    if case != 'unchanged-lib':
                        with (root/LIB).open('ab') as output:
                            output.write(HWPX_SUFFIX.encode('utf-8'))
                    if case in ('unreviewed-lib', 'changed-engine', 'changed-config', 'changed-helper'):
                        name = {'unreviewed-lib': LIB, 'changed-engine': KEYBOARD,
                                'changed-config': CONFIG, 'changed-helper': HELPER}[case]
                        with (root/name).open('ab') as output:
                            output.write(b'\n// unreviewed transition bytes\n')
                    elif case == 'forged-proof':
                        proof['afterSha256'][LIB] = '0'*64
                    before = files(root)
                    old_proof = copy.deepcopy(proof)
                    with self.assertRaises(ValueError):
                        m.refresh_hwpx_lib(root, proof)
                    self.assertEqual(files(root), before)
                    self.assertEqual(proof, old_proof)

    def test_contract_rejects_missing_malformed_and_forged_helper_and_patcher_values(self):
        for phase in ('prepared', 'hwpx'):
            for case in ('missing-helper', 'malformed-helper', 'forged-helper', 'missing-helper-file',
                         'forged-helper-file', 'missing-source', 'forged-source', 'missing-patcher',
                         'malformed-patcher', 'forged-patcher'):
                if phase == 'prepared' and case.endswith('patcher'):
                    continue
                with self.subTest(phase=phase, case=case), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    proofs, pins, _ = self.fixture(root)
                    if phase == 'hwpx':
                        (root/LIB).write_text(LIB_SOURCE+HWPX_SUFFIX, encoding='utf-8')
                    with self.fixture_pins(root, pins):
                        proof = m.apply(root, *proofs)
                        prepared, helpers = self.contract_inputs(root)
                        if case == 'missing-helper': helpers.pop('overlay/menu-clipboard.ts')
                        elif case == 'malformed-helper': helpers['overlay/menu-clipboard.ts'] = []
                        elif case == 'forged-helper': helpers['overlay/menu-clipboard.ts'] = '0'*64
                        elif case == 'missing-helper-file': prepared.pop(HELPER)
                        elif case == 'forged-helper-file': prepared[HELPER] = '0'*64
                        elif case == 'missing-source': prepared.pop(LIB)
                        elif case == 'forged-source': prepared[WINDOWS] = '0'*64
                        elif case == 'missing-patcher': helpers.pop('scripts/prepare_hwpx.py')
                        elif case == 'malformed-patcher': helpers['scripts/prepare_hwpx.py'] = None
                        elif case == 'forged-patcher': helpers['scripts/prepare_hwpx.py'] = '0'*64
                        before = files(root)
                        old = copy.deepcopy((proof, prepared, helpers))
                        with self.assertRaises(ValueError):
                            m.validate_contract(proof, prepared, helpers, final=phase == 'hwpx')
                        self.assertEqual((proof, prepared, helpers), old)
                        self.assertEqual(files(root), before)

    def test_contract_rejects_nonobject_arguments(self):
        for field in ('proof', 'prepared_files', 'helpers'):
            for invalid in (None, [], 'invalid'):
                with self.subTest(field=field, invalid=invalid), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    proofs, pins, _ = self.fixture(root)
                    with self.fixture_pins(root, pins):
                        proof = m.apply(root, *proofs)
                        prepared, helpers = self.contract_inputs(root)
                        arguments = {'proof': proof, 'prepared_files': prepared, 'helpers': helpers}
                        arguments[field] = invalid
                        before = files(root)
                        old = copy.deepcopy(arguments)
                        with self.assertRaises(ValueError):
                            m.validate_contract(**arguments, final=False)
                        self.assertEqual(arguments, old)
                        self.assertEqual(files(root), before)


if __name__ == '__main__':
    unittest.main()
