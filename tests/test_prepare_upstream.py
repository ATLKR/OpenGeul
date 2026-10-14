"""Generated native build inputs must declare DPI awareness before any HWND exists."""
from pathlib import Path
import json
import json
import re
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import prepare_upstream


class PrepareNativeManifestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.source = Path(self.tmp.name)
        # 이 fixture는 Windows manifest/dependency 생성 경계만 다룬다.
        # 실제 Store UI/bridge 연결은 별도의 준비 소스에서 TypeScript로 검증한다.
        integration = patch.object(prepare_upstream, 'install_store_updates')
        integration.start()
        self.addCleanup(integration.stop)
        clipboard = patch.object(prepare_upstream, 'install_async_clipboard_guard')
        self.clipboard = clipboard.start()
        self.clipboard.return_value = {'testFixture': 'async clipboard'}
        self.addCleanup(clipboard.stop)
        image = patch.object(prepare_upstream, 'install_image_insertion_guard')
        self.image = image.start()
        self.image.return_value = {'testFixture': 'image insertion'}
        self.addCleanup(image.stop)
        font = patch.object(prepare_upstream, 'install_async_font_selection_guard')
        self.font = font.start()
        self.font.return_value = {'testFixture': 'font selection', 'afterSha256': {}}
        self.addCleanup(font.stop)
        font_validation = patch.object(prepare_upstream, 'validate_async_font_selection_proof')
        font_validation.start()
        self.addCleanup(font_validation.stop)
        # These additive feature modules have their own real pinned-source tests;
        # this manifest fixture checks their place in the shared preparation path.
        pdf_search = patch.object(prepare_upstream, 'apply_pdf_search_text', create=True)
        self.pdf_search = pdf_search.start()
        self.pdf_search.return_value = {'testFixture': 'PDF searchable coordinates'}
        self.addCleanup(pdf_search.stop)
        menu_clipboard = patch.object(prepare_upstream, 'apply_menu_clipboard', create=True)
        self.menu_clipboard = menu_clipboard.start()
        self.menu_clipboard.return_value = {'testFixture': 'menu clipboard'}
        self.addCleanup(menu_clipboard.stop)
        shape_creation = patch.object(prepare_upstream, 'apply_shape_creation_history')
        self.shape_creation = shape_creation.start()
        self.shape_creation.return_value = {'testFixture': 'shape creation history'}
        self.addCleanup(shape_creation.stop)
        # 전체 vendor/shim 무결성은 test_native_activation에서 별도로 검사한다.
        activation = patch.object(prepare_upstream, 'apply_native_activation')
        self.activation = activation.start()
        self.activation.return_value = {'formatVersion': 1, 'testFixture': True}
        self.addCleanup(activation.stop)
        worker = patch.object(prepare_upstream, 'apply_com_worker')
        self.worker = worker.start()
        self.worker.return_value = {'formatVersion': 1, 'testFixture': 'COM'}
        self.addCleanup(worker.stop)
        self.native = self.source / 'apps/desktop/src-tauri'
        files = {
            'apps/studio-host/src/main.ts': '// manifest-only source fixture\n',
            'apps/desktop/src-tauri/build.rs': 'fn main() {\n    tauri_build::build();\n}\n',
            'apps/desktop/src-tauri/Cargo.toml': '[package]\nname = "hop-desktop"\nversion = "0.4.5"\n[dependencies]\ntauri = { version = "2", features = [] }\n',
            'apps/desktop/src-tauri/Cargo.lock': 'version = 4\n[[package]]\nname = "hop-desktop"\nversion = "0.4.5"\n[[package]]\nname = "tauri"\nversion = "2.10.3"\n',
            'apps/desktop/src-tauri/tauri.conf.json': '{}',
            'apps/desktop/src-tauri/tauri.windows.conf.json': '{}',
            'package.json': '{}', 'apps/desktop/package.json': '{}',
            'apps/desktop/src-tauri/src/lib.rs': 'mod app_quit;\npub fn run() {\n        .plugin(tauri_plugin_updater::Builder::new().build())\n tauri::generate_handler![]\n}\n',
            'apps/desktop/src-tauri/src/font_catalog.rs': '''use tauri::{AppHandle, Manager};
pub fn pdf_font_dirs(app: &AppHandle) -> Vec<PathBuf> {
    let mut dirs = Vec::new();
    if let Ok(resource_dir) = app.path().resource_dir() {
        dirs.push(resource_dir.join("fonts/pdf"));
    }
    dirs.extend(desktop_extra_font_dirs());
    dedupe_existing_dirs(dirs)
}
    let allowed_roots = desktop_extra_font_dirs();
''',
            'apps/studio-host/index.html': '<title>HOP</title><link href="/favicon.ico"></body>',
            'apps/studio-host/src/core/font-catalog.ts': '// upstream catalog\n',
            'apps/studio-host/src/host/toolbar-labels.ts': "  try { return localStorage.getItem(STORAGE_KEY) !== 'hidden'; }\n",
            'apps/studio-host/src/ui/about-dialog.ts': '''import { AboutDialog as UpstreamAboutDialog } from '@/upstream/ui';

export class AboutDialog extends UpstreamAboutDialog {
  protected override createBody(): HTMLElement {
    const body = super.createBody();
    const version = body.querySelector('.about-version');

    const hopVersion = document.createElement('div');
    hopVersion.className = 'about-hop-version';
    hopVersion.textContent = `HOP ${__HOP_VERSION__}`;

    if (version?.parentNode) {
      version.parentNode.insertBefore(hopVersion, version.nextSibling);
    } else {
      body.appendChild(hopVersion);
    }

    return body;
  }
}
''',
            'third_party/rhwp/rhwp-studio/src/ui/about-dialog.ts': "titleEn.textContent = 'HWP/HWPX Compatible Module for Rust';\nversion.textContent = `Version ${__APP_VERSION__}`;\n",
            'third_party/rhwp/rhwp-studio/src/ui/compare-dialog.ts': 'L: ${this.escape(leftPreview)} / R: ${this.escape(rightPreview)}\n',
            'third_party/rhwp/rhwp-studio/src/ui/history-dialog.ts': 'L: ${this.escape(leftText)} / R: ${this.escape(rightText)}\n',
            'third_party/rhwp/src/renderer/pdf.rs': '''/// Native PDF implementation selected by callers such as `export-pdf`.
    let fontdb = create_fontdb(export_options);
    crate::renderer::font_paths::load_into_fontdb(&mut fontdb, &options.font_paths);
        let Some((chunk, svg_ref)) =
            convert_page_chunk(&tree, export_options.embed_text, page_index, &mut to_chunk)?
        else {
            continue;
        };
WARN: 페이지 1 — 이 페이지만 건너뛰고 PDF 를 계속합니다.
WARN: 페이지 2 — 이 페이지만 건너뛰고 PDF 를 계속합니다.
pub fn layer_trees_to_pdf_with_links(
    layer_trees: &[crate::paint::PageLayerTree],
    links: &[Vec<super::hyperlinks::PdfLink>],
    options: &DirectPdfExportOptions,
) -> Result<Vec<u8>, String> {
''',
            'apps/desktop/rhwp-adapter/src/lib.rs': '"Noto Sans KR".to_string()\n' * 3,
        }
        for name in ('commands.rs', 'state.rs', 'pdf_export.rs', 'pending_open.rs', 'app_quit.rs', 'recent_documents.rs', 'windows.rs'):
            files['apps/desktop/src-tauri/src/' + name] = '// preserved native source\n'
        files['apps/studio-host/hop-overrides.ts'] = '// preserved overrides\n'
        for name, text in files.items():
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            # The pinned Git checkout uses LF, including the byte-guarded About source.
            path.write_text(text, encoding='utf-8', newline='\n')

    def test_preparation_emits_the_manifest_used_by_the_native_build(self):
        prepare_upstream.patch(self.source, '1.1.2')
        manifest = self.native / 'windows-app-manifest.xml'
        self.assertTrue(manifest.is_file(), 'Preparation did not emit the native Windows manifest')
        build = (self.native / 'build.rs').read_text(encoding='utf-8')
        included = re.search(r'\.app_manifest\(include_str!\("([^"]+)"\)\)', build)
        self.assertIsNotNone(included, 'Native build does not consume the generated application manifest')
        self.assertEqual(self.native / included.group(1), manifest)
        rendered = ''.join(f' {line.strip()} ' for line in manifest.read_text(encoding='utf-8').splitlines())
        doc = ET.fromstring(rendered)
        self.assertEqual(doc.findtext('.//{http://schemas.microsoft.com/SMI/2005/WindowsSettings}dpiAware'), 'true/pm')
        self.assertEqual(doc.findtext('.//{http://schemas.microsoft.com/SMI/2016/WindowsSettings}dpiAwareness'), 'PerMonitorV2')
        self.assertEqual(doc[0].tag, '{urn:schemas-microsoft-com:asm.v1}assemblyIdentity')
        self.assertEqual(doc[0].attrib, {'type': 'win32', 'name': 'AllenLabs.OpenGeul',
            'version': '1.1.2.0', 'processorArchitecture': '*'})
        controls = doc.find('{urn:schemas-microsoft-com:asm.v1}dependency/{urn:schemas-microsoft-com:asm.v1}dependentAssembly/{urn:schemas-microsoft-com:asm.v1}assemblyIdentity')
        self.assertEqual(controls.attrib, {'type': 'win32', 'name': 'Microsoft.Windows.Common-Controls',
            'version': '6.0.0.0', 'processorArchitecture': '*', 'publicKeyToken': '6595b64144ccf1df', 'language': '*'})
        self.assertIsNone(doc.find('.//{urn:schemas-microsoft-com:asm.v3}requestedExecutionLevel'))

    def test_generated_desktop_excludes_known_tauri_origin_confusion_versions(self):
        # GHSA-7gmj-67g7-phm9: 영향 범위 2.0.0~2.11.0, 첫 수정 버전 2.11.1.
        # 준비 단계가 업스트림의 취약 잠금 파일로 돌아가면 이 회귀가 실패해야 한다.
        prepare_upstream.patch(self.source, '1.1.2')
        manifest = tomllib.loads((self.native / 'Cargo.toml').read_text(encoding='utf-8'))
        lock = tomllib.loads((self.native / 'Cargo.lock').read_text(encoding='utf-8'))
        selected = [p for p in lock['package'] if p['name'] == 'tauri']
        self.assertEqual(len(selected), 1)
        version = tuple(map(int, selected[0]['version'].split('.')))
        self.assertGreaterEqual(version, (2, 11, 1), '생성된 잠금 파일에 알려진 Tauri 취약 버전이 남았습니다')
        self.assertEqual(version[0], 2, '검토되지 않은 메이저 버전을 선택했습니다')
        self.assertEqual(manifest['dependencies']['tauri']['version'], '=' + selected[0]['version'],
                         '선택한 보안 수정 버전을 정확히 고정해야 합니다')
        root = [p for p in lock['package'] if p['name'] == 'hop-desktop']
        self.assertEqual([p['version'] for p in root], ['1.1.2'])

    def test_generated_store_update_transport_pins_the_fixed_tls_version(self):
        # GHSA-2mjx-qc3c-rqvc의 첫 수정은 rustls 0.23.45다.
        prepare_upstream.patch(self.source, '1.1.2')
        manifest = tomllib.loads((self.native / 'Cargo.toml').read_text(encoding='utf-8'))
        lock = tomllib.loads((self.native / 'Cargo.lock').read_text(encoding='utf-8'))
        rustls = [p['version'] for p in lock['package'] if p['name'] == 'rustls']
        self.assertEqual(rustls, ['0.23.45'], '새 HTTPS 확인에 취약한 TLS 버전을 추가할 수 없습니다')
        self.assertEqual(manifest['dependencies']['reqwest']['version'], '=0.13.2')
        self.assertEqual(manifest['dependencies']['rustls']['version'], '=0.23.45')
        self.assertEqual(manifest['dependencies']['tokio']['version'], '=1.52.1')

    def test_preparation_installs_product_contact_and_actual_ui_regressions(self):
        prepare_upstream.patch(self.source, '1.1.3')
        self.clipboard.assert_called_once_with(self.source)
        self.image.assert_called_once_with(self.source, self.clipboard.return_value)
        self.font.assert_called_once_with(self.source, self.clipboard.return_value, self.image.return_value)
        ledger = json.loads((self.source/'.opengeul-overlay.json').read_text())
        self.assertEqual(ledger['imageInsertionGuard'], self.image.return_value)
        self.assertEqual(ledger['asyncFontSelectionGuard'], self.font.return_value)
        path = self.source/'apps/studio-host/src/ui/about-dialog.ts'
        self.assertIn('allenlim@allenlim.net', path.read_text(encoding='utf-8'))
        self.assertEqual(path.read_bytes(), (ROOT/'overlay/about-dialog.ts').read_bytes())
        self.assertEqual((self.source/'apps/studio-host/src/ui/about-dialog.test.ts').read_bytes(),
                         (ROOT/'overlay/about-dialog.test.ts').read_bytes())

    def test_searchable_pdf_and_menu_clipboard_are_in_the_final_preparation_path(self):
        observed = []
        def pdf_boundary(source):
            pdf = source/'third_party/rhwp/src/renderer/pdf.rs'
            self.assertIn('opengeul_pdf_guard::enforce', pdf.read_text())
            self.assertTrue((source/'third_party/rhwp/src/renderer/pdf/opengeul_font_policy.rs').is_file())
            observed.append('pdf')
            return self.pdf_search.return_value
        def clipboard_boundary(source, clipboard, image, font):
            self.assertEqual(observed, ['pdf'])
            self.assertNotIn('tauri_plugin_updater::Builder', (source/'apps/desktop/src-tauri/src/lib.rs').read_text())
            self.assertIn('apps/studio-host/src/main.ts', font['afterSha256'])
            observed.append('menu')
            return self.menu_clipboard.return_value
        def shape_boundary(source, clipboard, image, font, menu):
            self.assertEqual(observed, ['pdf', 'menu'])
            self.assertIs(menu, self.menu_clipboard.return_value)
            observed.append('shape')
            return self.shape_creation.return_value
        self.pdf_search.side_effect = pdf_boundary
        self.menu_clipboard.side_effect = clipboard_boundary
        self.shape_creation.side_effect = shape_boundary
        prepare_upstream.patch(self.source, '1.1.5')
        self.pdf_search.assert_called_once_with(self.source)
        self.menu_clipboard.assert_called_once_with(self.source, self.clipboard.return_value,
                                                  self.image.return_value, self.font.return_value)
        self.shape_creation.assert_called_once_with(self.source, self.clipboard.return_value,
            self.image.return_value, self.font.return_value, self.menu_clipboard.return_value)
        ledger = json.loads((self.source/'.opengeul-overlay.json').read_text())
        self.assertEqual(ledger['pdfSearchText'], self.pdf_search.return_value)
        self.assertEqual(ledger['menuClipboardPaste'], self.menu_clipboard.return_value)
        self.assertEqual(ledger['shapeCreationHistory'], self.shape_creation.return_value)
        self.assertEqual(observed, ['pdf', 'menu', 'shape'])

    def test_changed_upstream_about_is_rejected_without_overwrite(self):
        path = self.source/'apps/studio-host/src/ui/about-dialog.ts'
        changed = path.read_bytes() + b'// unreviewed upstream change\n'
        path.write_bytes(changed)
        with self.assertRaisesRegex(ValueError, 'product information source changed'):
            prepare_upstream.install_product_information(self.source)
        self.assertEqual(path.read_bytes(), changed)
        self.assertFalse(path.with_name('about-dialog.test.ts').exists())

    def test_upstream_hop_version_change_requires_reviewed_about_attribution(self):
        path = self.source/'apps/studio-host/src/ui/about-dialog.ts'
        original = path.read_bytes()
        read_text = Path.read_text
        def changed_lock(file, *args, **kwargs):
            text = read_text(file, *args, **kwargs)
            if file == ROOT/'config/upstream.lock.json':
                value = json.loads(text); value['hop']['version'] = '0.4.6'
                return json.dumps(value)
            return text
        with patch.object(Path, 'read_text', changed_lock), self.assertRaisesRegex(ValueError, 'HOP attribution version'):
            prepare_upstream.install_product_information(self.source)
        self.assertEqual(path.read_bytes(), original)

    def test_changed_upstream_build_script_is_rejected_without_overwrite(self):
        path = self.native / 'build.rs'
        changed = 'fn main() {\n    tauri_build::build(); // upstream changed\n}\n'
        path.write_text(changed, encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Upstream native build script changed'):
            prepare_upstream.patch(self.source, '1.1.2')
        self.assertEqual(path.read_text(encoding='utf-8'), changed)
        self.assertFalse((self.native / 'windows-app-manifest.xml').exists())

    def test_native_activation_prepares_the_same_locked_desktop_source(self):
        observed = []
        def activation(source):
            lock = tomllib.loads((source / 'apps/desktop/src-tauri/Cargo.lock').read_text(encoding='utf-8'))
            observed.extend(p['version'] for p in lock['package'] if p['name'] == 'hop-desktop')
            return {'formatVersion': 1, 'testFixture': True}
        self.activation.side_effect = activation
        prepare_upstream.patch(self.source, '1.1.2')
        self.activation.assert_called_once_with(self.source)
        self.assertEqual(observed, ['1.1.2'], 'Native source preparation must receive the final product lock')
        ledger = json.loads((self.source / '.opengeul-overlay.json').read_text(encoding='utf-8'))
        self.assertEqual(ledger['nativeActivation'], {'formatVersion': 1, 'testFixture': True})

    def test_com_lock_and_public_ledger_precede_native_source_capture(self):
        observed = []
        def worker(source):
            self.assertFalse((source / 'third_party/rhwp/Cargo.lock').exists())
            observed.append('COM')
            return {'formatVersion': 1, 'testFixture': 'COM'}
        def activation(source):
            self.assertEqual((source / 'third_party/rhwp/Cargo.lock').read_bytes(),
                             (prepare_upstream.ROOT / 'overlay/cli-cargo.lock.toml').read_bytes())
            observed.append('native')
            return {'formatVersion': 1, 'testFixture': True}
        self.worker.side_effect = worker
        self.activation.side_effect = activation
        prepare_upstream.patch(self.source, '1.1.3')
        self.assertEqual(observed, ['COM', 'native'])
        self.worker.assert_called_once_with(self.source)
        ledger = json.loads((self.source / '.opengeul-overlay.json').read_text(encoding='utf-8'))
        self.assertEqual(ledger['comWorker'], {'formatVersion': 1, 'testFixture': 'COM'})

    def test_windows_preparation_matches_editor_manifest_line_endings(self):
        manifest = self.native / 'Cargo.toml'
        manifest.write_bytes(b'[package]\r\nname = "hop-desktop"\r\nversion = "0.4.5"\r\n[dependencies]\r\ntauri = { version = "2", features = [] }\r\n')
        path_open = Path.open

        def windows_open(path, mode='r', buffering=-1, encoding=None, errors=None, newline=None):
            # Emulate Windows' default text-write translation on every test host.
            if 'w' in mode and 'b' not in mode and newline is None:
                newline = '\r\n'
            return path_open(path, mode, buffering, encoding, errors, newline)

        with patch.object(Path, 'open', windows_open):
            prepare_upstream.patch(self.source, '1.1.2')

        cli_input = manifest.read_bytes()
        editor_input = manifest.read_text(encoding='utf-8').encode('utf-8')
        self.assertEqual(cli_input, editor_input,
                         'Tauri rewrites the editor manifest with LF; CLI preparation must match')
        self.assertEqual(cli_input,
                         b'[package]\nname = "hop-desktop"\nversion = "1.1.2"\n[dependencies]\ntauri = { version = "=2.11.1", features = [] }\n'
                         + prepare_upstream.UPDATE_DEPENDENCIES.encode('utf-8'))


if __name__ == '__main__':
    unittest.main()
