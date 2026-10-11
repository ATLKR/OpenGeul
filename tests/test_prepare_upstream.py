"""Generated native build inputs must declare DPI awareness before any HWND exists."""
from pathlib import Path
import re
import sys
import tempfile
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
        self.native = self.source / 'apps/desktop/src-tauri'
        files = {
            'apps/desktop/src-tauri/build.rs': 'fn main() {\n    tauri_build::build();\n}\n',
            'apps/desktop/src-tauri/Cargo.toml': 'version = "0.4.5"\n',
            'apps/desktop/src-tauri/Cargo.lock': 'name = "hop-desktop"\nversion = "0.4.5"\n',
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
            'third_party/rhwp/src/renderer/pdf.rs': '''/// Native PDF implementation selected by callers such as `export-pdf`.
    let fontdb = create_fontdb(export_options);
    crate::renderer::font_paths::load_into_fontdb(&mut fontdb, &options.font_paths);
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
            path.write_text(text, encoding='utf-8')

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
            'version': '1.1.2.0', 'processorArchitecture': 'amd64'})
        controls = doc.find('{urn:schemas-microsoft-com:asm.v1}dependency/{urn:schemas-microsoft-com:asm.v1}dependentAssembly/{urn:schemas-microsoft-com:asm.v1}assemblyIdentity')
        self.assertEqual(controls.attrib, {'type': 'win32', 'name': 'Microsoft.Windows.Common-Controls',
            'version': '6.0.0.0', 'processorArchitecture': '*', 'publicKeyToken': '6595b64144ccf1df', 'language': '*'})
        self.assertIsNone(doc.find('.//{urn:schemas-microsoft-com:asm.v3}requestedExecutionLevel'))

    def test_changed_upstream_build_script_is_rejected_without_overwrite(self):
        path = self.native / 'build.rs'
        changed = 'fn main() {\n    tauri_build::build(); // upstream changed\n}\n'
        path.write_text(changed, encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Upstream native build script changed'):
            prepare_upstream.patch(self.source, '1.1.2')
        self.assertEqual(path.read_text(encoding='utf-8'), changed)
        self.assertFalse((self.native / 'windows-app-manifest.xml').exists())

    def test_windows_preparation_matches_editor_manifest_line_endings(self):
        manifest = self.native / 'Cargo.toml'
        manifest.write_bytes(b'[package]\r\nname = "hop-desktop"\r\nversion = "0.4.5"\r\n')
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
                         b'[package]\nname = "hop-desktop"\nversion = "1.1.2"\n')


if __name__ == '__main__':
    unittest.main()
