"""소유 CLI 소스에 COM 작업자 경계만 추가하는 변환 회귀 검사."""
from pathlib import Path
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT/'scripts/com_worker.py'
sys.path.insert(0, str(ROOT/'scripts'))

MAIN = '''use std::env;
mod mcp_serve;
fn main() {
    let raw_args: Vec<String> = env::args().collect();
    // Synthetic preserved auth/help/dispatch boundary.
    let args = strip_global_auth_options(raw_args);
    process::exit(dispatch(args));
}
// [#5511] 최상위 dispatch 끝 — 소유 모듈 이동과 무관한 characterization 경계다.
'''
TRANSPORT = '''    let mut cmd = std::process::Command::new(exe);
    cmd.args(&cli_args)
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped());
    // 자식 stdin 은 payload(password 또는 paths)를 흘릴 때만 파이프, 그 외에는
    // 항상 닫는다(null) — 어떤 자식도 서버의 프로토콜 stdin 을 상속해서는 안 된다.
    if stdin_payload.is_some() {
        cmd.stdin(std::process::Stdio::piped());
    } else {
        cmd.stdin(std::process::Stdio::null());
    }

    let mut child = match cmd.spawn() {
        Ok(c) => c,
        Err(e) => return tool_error(format!("CLI 실행 실패: {e}")),
    };
    if let (Some(payload), Some(mut stdin)) = (stdin_payload, child.stdin.take()) {
        let _ = stdin.write_all(payload.as_bytes());
        // drop 으로 stdin 닫힘 — password reader와 batch가 EOF를 본다.
    }
    let output = match child.wait_with_output() {
        Ok(o) => o,
        Err(e) => return tool_error(format!("CLI 종료 대기 실패: {e}")),
    };
'''
MCP = '''fn run_cli_tool() {
    // Synthetic preserved profile/args/password/stdin validation.
    let stdin_payload = private_stdin();
'''+TRANSPORT+'''
    let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
    let code = output.status.code().unwrap_or(-1);
    if stdout.is_empty() {
        let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
        return tool_error(format!("종료 코드 {code}: {stderr}"));
    }
    tool_ok_text(stdout)
}
'''


class ComWorkerSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.source = Path(self.tmp.name)/'hop'
        self.core = self.source/'third_party/rhwp'
        (self.core/'src').mkdir(parents=True)
        (self.core/'src/main.rs').write_text(MAIN)
        (self.core/'src/mcp_serve.rs').write_text(MCP)
        (self.core/'Cargo.toml').write_text('[package]\nname="rhwp"\nversion="0.8.7"\nedition="2021"\n[dependencies]\nserde="1"\nserde_json="1"\n')

    def helper(self):
        self.assertTrue(HELPER.is_file(), 'COM 작업자 소스 변환 helper가 필요합니다')
        spec = importlib.util.spec_from_file_location('com_worker', HELPER)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        return module

    def test_typed_entry_and_windows_transport_preserve_original_dispatch_and_nonwindows_worker(self):
        helper = self.helper()
        ledger = helper.apply(self.source)
        main = (self.core/'src/main.rs').read_text()
        self.assertIn('fn cli_entry(raw_args: Vec<String>) {', main)
        self.assertIn('serve_if_requested(cli_entry)', main)
        self.assertIn('cli_entry(env::args().collect());', main)
        self.assertIn(MAIN.split('    let raw_args: Vec<String> = env::args().collect();\n',1)[1], main)
        mcp = (self.core/'src/mcp_serve.rs').read_text()
        self.assertIn('opengeul_com_worker::run_cli(&exe, &cli_args,', mcp)
        self.assertIn('#[cfg(not(windows))]', mcp)
        self.assertIn(TRANSPORT, mcp)
        self.assertEqual(mcp.split('    let stdout = ',1)[1], MCP.split('    let stdout = ',1)[1])
        self.assertEqual(ledger['originalFiles']['src/main.rs'], hashlib.sha256(MAIN.encode()).hexdigest())
        self.assertEqual(ledger['patchedFiles']['src/main.rs'], hashlib.sha256(main.encode()).hexdigest())
        self.assertEqual(ledger['fixedClsid'], 'c6c4d247-b4f0-563d-a649-4765796e3164')
        self.assertFalse(ledger['qualification'])
        self.assertEqual(json.loads((self.core/'.opengeul-com-worker.json').read_text()), ledger)
        for name, sha in ledger['copiedFiles'].items():
            self.assertEqual(hashlib.sha256((self.core/name).read_bytes()).hexdigest(), sha)

    def test_malformed_or_duplicate_markers_fail_before_any_file_changes(self):
        helper = self.helper()
        originals = {p:p.read_bytes() for p in (self.core/'src').iterdir()}
        for name, bad in [('main.rs', MAIN.replace('fn main() {','fn other() {')),
                          ('main.rs', MAIN+'\nfn main() {}\n'),
                          ('mcp_serve.rs', MCP.replace('child.wait_with_output()', 'child.wait()'))]:
            path = self.core/'src'/name; path.write_text(bad)
            before = {p:p.read_bytes() for p in (self.core/'src').iterdir()}
            with self.subTest(name=name), self.assertRaises(ValueError): helper.apply(self.source)
            self.assertEqual(before, {p:p.read_bytes() for p in (self.core/'src').iterdir()})
            self.assertFalse((self.core/'src/opengeul_com_worker').exists())
            for p, data in originals.items(): p.write_bytes(data)

    def test_existing_worker_sources_or_second_application_are_never_overwritten(self):
        helper = self.helper()
        folder = self.core/'src/opengeul_com_worker'; folder.mkdir()
        sentinel = folder/'mod.rs'; sentinel.write_text('keep owned existing source')
        with self.assertRaises(ValueError): helper.apply(self.source)
        self.assertEqual(sentinel.read_text(), 'keep owned existing source')
        sentinel.unlink(); folder.rmdir()
        helper.apply(self.source)
        before = {p:p.read_bytes() for p in self.core.rglob('*') if p.is_file()}
        with self.assertRaises(ValueError): helper.apply(self.source)
        self.assertEqual(before, {p:p.read_bytes() for p in self.core.rglob('*') if p.is_file()})

    def test_existing_windows_dependencies_fail_before_any_source_or_lock_change(self):
        helper = self.helper()
        cargo = self.core/'Cargo.toml'
        cargo.write_text(cargo.read_text()+"\n[target.'cfg(windows)'.dependencies]\nwindows=\"0.62\"\n")
        lock = self.core/'Cargo.lock'; lock.write_text('existing pinned dependency lock\n')
        before = {p:p.read_bytes() for p in self.core.rglob('*') if p.is_file()}
        with self.assertRaises(ValueError): helper.apply(self.source)
        self.assertEqual(before, {p:p.read_bytes() for p in self.core.rglob('*') if p.is_file()})
        self.assertFalse((self.core/'src/opengeul_com_worker').exists())

    def test_unrelated_source_and_both_dependency_locks_are_preserved(self):
        helper = self.helper()
        desktop = self.source/'apps/desktop/src-tauri'; desktop.mkdir(parents=True)
        retained = [self.core/'Cargo.lock', self.core/'src/document_io.rs', desktop/'Cargo.lock']
        for path in retained: path.write_text('preserve '+path.name+'\n')
        before = {path:path.read_bytes() for path in retained}
        ledger = helper.apply(self.source)
        self.assertEqual(before, {path:path.read_bytes() for path in retained})
        self.assertEqual(set(ledger['patchedFiles']), {'src/main.rs','src/mcp_serve.rs','Cargo.toml'})
        self.assertEqual(set(ledger['copiedFiles']), {
            'src/opengeul_com_worker/mod.rs', 'src/opengeul_com_worker/wire.rs',
            'src/opengeul_com_worker/windows.rs'})


if __name__ == '__main__': unittest.main()
