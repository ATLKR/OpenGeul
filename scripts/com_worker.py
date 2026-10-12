"""원 CLI 파서·프로세스 격리를 보존하는 Windows COM 작업자 경계 추가."""
from pathlib import Path
import argparse
import hashlib
import json
import tomllib

ROOT = Path(__file__).resolve().parents[1]
FIXED_CLSID = 'c6c4d247-b4f0-563d-a649-4765796e3164'
FILES = ('mod.rs', 'wire.rs', 'windows.rs')
OLD_TRANSPORT = '''    let mut cmd = std::process::Command::new(exe);
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
ENTRY = '''fn main() {
    #[cfg(windows)]
    match opengeul_com_worker::serve_if_requested(cli_entry) {
        Ok(true) => return,
        Ok(false) => {},
        Err(_) => process::exit(EXIT_RUNTIME),
    }
    cli_entry(env::args().collect());
}

fn cli_entry(raw_args: Vec<String>) {
'''

def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()

def replace_once(text: str, before: str, after: str) -> str:
    if text.count(before) != 1:
        raise ValueError('검토한 CLI 원본 경계가 없거나 중복됩니다')
    return text.replace(before, after, 1)

def apply(source: Path) -> dict:
    core = source/'third_party/rhwp'
    directory = core/'src/opengeul_com_worker'
    marker = core/'.opengeul-com-worker.json'
    if directory.exists() or directory.is_symlink() or marker.exists():
        raise ValueError('기존 COM 작업자 소스와 적용 기록을 덮어쓰지 않습니다')
    paths = {name: core/name for name in ('src/main.rs', 'src/mcp_serve.rs', 'Cargo.toml')}
    for path in paths.values():
        if not path.is_file() or path.is_symlink():
            raise ValueError('CLI 원본은 일반 파일이어야 합니다')
    texts = {name: path.read_text(encoding='utf-8') for name, path in paths.items()}
    if texts['src/main.rs'].count('fn main()') != 1:
        raise ValueError('CLI main 경계가 변경되었습니다')
    main = replace_once(texts['src/main.rs'], 'mod mcp_serve;', 'mod mcp_serve;\n#[cfg(windows)]\nmod opengeul_com_worker;')
    main = replace_once(main, 'fn main() {\n    let raw_args: Vec<String> = env::args().collect();\n', ENTRY)
    windows = '''    #[cfg(windows)]
    let output = match crate::opengeul_com_worker::run_cli(&exe, &cli_args,
        stdin_payload.as_deref().map(str::as_bytes)) {
        Ok(output) => output,
        Err(error) => return tool_error(format!("CLI 실행 실패: {error}")),
    };
    #[cfg(not(windows))]
    let output = {
'''+OLD_TRANSPORT+'''        output
    };
'''
    mcp = replace_once(texts['src/mcp_serve.rs'], OLD_TRANSPORT, windows)
    manifest = tomllib.loads(texts['Cargo.toml'])
    if 'cfg(windows)' in manifest.get('target', {}):
        raise ValueError('업스트림 Windows 의존성 경계가 변경되었습니다')
    native = tomllib.loads((ROOT/'overlay/com-worker/Cargo.toml').read_text(encoding='utf-8'))['target']['cfg(windows)']['dependencies']
    dependencies = '\n\n# OpenGeul 소유 COM 작업자: 표준 Windows 활성화, 직접 프로세스 실행 없음.\n[target.\'cfg(windows)\'.dependencies]\n'
    dependencies += 'windows-core = "=0.61.2"\n'
    dependencies += 'windows = { version = "=0.61.3", features = '+json.dumps(native['windows']['features'])+' }\n'
    cargo = texts['Cargo.toml']+dependencies
    tomllib.loads(cargo)  # 모든 입력과 TOML 경계를 검증한 뒤에만 쓰기를 시작한다.
    copies = {}
    for name in FILES:
        path=ROOT/'overlay/com-worker/src'/name
        if not path.is_file() or path.is_symlink():
            raise ValueError('검토한 COM 작업자 Rust 원문이 없습니다')
        copies['src/opengeul_com_worker/'+name]=path.read_bytes()
    changed = {'src/main.rs': main, 'src/mcp_serve.rs': mcp, 'Cargo.toml': cargo}
    ledger = {'formatVersion': 1, 'fixedClsid': FIXED_CLSID, 'helperSha256': sha(Path(__file__).read_bytes()),
              'originalFiles': {name: sha(path.read_bytes()) for name,path in paths.items()},
              'patchedFiles': {name: sha(text.encode()) for name,text in changed.items()},
              'copiedFiles': {name: sha(data) for name,data in copies.items()},
              'windowsDependencies': native, 'qualification': False}
    directory.mkdir()
    for name,data in copies.items(): (core/name).write_bytes(data)
    for name,text in changed.items(): paths[name].write_text(text,encoding='utf-8',newline='\n')
    marker.write_text(json.dumps(ledger,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    return ledger

if __name__ == '__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('source',type=Path)
    args=parser.parse_args(); apply(args.source)
    print('COM 작업자 소스 경계를 준비했습니다. Windows 실행과 전체 WACK 검증은 별도입니다.')
