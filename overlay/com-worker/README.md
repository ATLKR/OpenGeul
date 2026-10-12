# Windows COM 문서 작업자

이 오버레이는 MCP의 문서 작업을 원 CLI와 별도 프로세스에서 실행한다. Windows에서는 COM SCM이 소유 local-server EXE를 활성화하고, 포터블과 MSIX가 동일한 `Tools/rhwp.exe`를 사용한다. 직접 `Command::spawn`, 실행 API 동적 탐색, in-process 문서 작업으로 대체하지 않는다. Windows 외 운영체제의 원래 `Command` 경로는 유지한다.

## 소스 적용 경계

`scripts/com_worker.py.apply(HOP_SOURCE)`는 검토한 rhwp의 `main.rs`, `mcp_serve.rs`, `Cargo.toml` 경계를 각각 정확히 한 번 변환한다. `src/opengeul_com_worker`에 이 디렉터리의 Rust 원문 세 개를 복사하고 `.opengeul-com-worker.json`에 원본·변환·복사·helper SHA256을 기록한다. 기존 적용 기록·모듈·Windows 의존성은 덮어쓰지 않는다. 두 제품 Cargo.lock은 별도 잠금 통합 단계에서 관리한다. 이 독립 Cargo 프로젝트는 같은 원문을 검사하며 제품에 새 path crate를 추가하지 않는다.

원 `main` 본문은 `cli_entry(Vec<String>)`로 옮긴다. 일반 CLI는 원래 `env::args()`를 전달하고, 작업자는 main thread에서 인증된 argv를 전달한다. 전역 암호 옵션 선검사·password TLS·batch 규칙·help·직접 `process::exit` 순서를 유지한다. MCP 인자 검증과 stdout/exit 판정은 원문 그대로다. stdout이 있는 exit 1/3이나 비JSON 텍스트도 원래 의미를 유지하고, stdout이 없으면 stderr와 종료 코드를 반환한다.

## 활성화와 권한

- MSIX는 고정 CLSID `c6c4d247-b4f0-563d-a649-4765796e3164`를 `com:ExeServer`로 선언한다. Executable은 `Tools\rhwp.exe`, Arguments는 `--opengeul-com-worker --clsid c6c4d247-b4f0-563d-a649-4765796e3164`다. 기본 시스템 COM 정책을 사용하며 광범위 launch DACL을 추가하지 않는다.
- 포터블은 매 작업의 fresh CLSID를 등록한다. 표준 사용자는 HKCU, elevated token은 HKLM의 64비트 `Software\Classes\CLSID`를 사용한다. COM의 관리자/UAC 비활성 HKCU 무시 규칙 때문에 HKCU만 사용한다고 가정하지 않는다. 기존 merged-view key 또는 생성 경합에서 발견한 기존 key는 수정하지 않는다.
- `REGCLS_SINGLEUSE`와 atomic 단일 작업 승인을 함께 적용한다. `IDispatch`의 primitive BSTR metadata를 사용하므로 새 custom IID의 proxy/stub에 의존하지 않는다. `Begin`은 보호 헤더 실행 전에 응답한다.
- COM은 packet privacy, caller identify, 기본 activate-as-activator 금지를 요청한다. 자기 EXE의 검증한 fresh 등록 또는 현재 패키지의 고정 class를 활성화하는 한 호출에만 공식 `CLSCTX_ENABLE_AAA` 예외를 적용한다. fresh 등록은 호출 직전에 현재 부모 PID·생성 시간·hive·owner·값·key shape·ServerExecutable을 다시 확인한다. 프로세스의 `EOAC_DISABLE_AAA`와 custom marshaling 금지는 유지하고 임의 CLSID·remote·in-process 활성화를 허용하지 않는다. worker는 실제 호출 토큰과 부모 프로세스의 사용자 SID·로그온 SID·integrity RID·elevation이 자기 토큰과 모두 같아야 작업을 받는다. 같은 사용자 이름만으로 elevated 작업을 허용하지 않는다.

## 보호 채널과 종료

Bootstrap은 버전·fresh 작업 GUID·nonce·부모/worker PID만 담는다. 문서 경로·암호·전체 환경을 argv나 registry에 넣지 않는다. 세 named pipe는 first instance, remote-client 거부, 같은 로그온의 제한된 read/write DACL과 현재 integrity의 mandatory label을 사용한다. 부모는 실제 세 pipe client PID, own EXE 경로, 프로세스 생성 시간, 토큰과 아키텍처, nonce ACK를 확인한 뒤에만 worker에 종료 가능한 job handle을 붙인다. worker도 세 pipe server PID와 부모 image/token을 검증한다. 제품 경로·PE·SHA·native 실행 여부와 준비 소스 binding은 실제 Windows 검증 영수증에서 별도로 대조한다.

인증 후에 argv·cwd·원본 UTF16 환경 블록을 최대 1 MiB의 typed JSON 헤더로 전달한다. 이 상한은 새 private header에 대한 상한이다. 기존 MCP protocol frame이나 stdout이 제한되어 있었다고 주장하지 않는다. 환경의 `=C:` 항목과 Unicode를 유지한다. SCM 프로세스 생성 시 loader 환경 자체가 부모에게서 상속되는 것은 아니며, CLI dispatch 전에 Win32 환경/cwd를 설정한다.

worker는 Win32와 CRT stdin/stdout/stderr를 연결하기 전 Rust stdio를 사용하지 않는다. raw `ReadFile`로 길이와 헤더만 정확히 소비하고 남은 stdin payload와 EOF를 원 CLI에 전달한다. 부모 MCP protocol stdin은 상속하지 않는다. stdout/stderr는 동시에 회수하고 owned process handle의 실제 종료 코드를 반환한다. Job Object의 kill-on-close는 인증한 작업자에만 적용한다. 작업자의 exit/crash가 부모 MCP의 다음 호출을 종료시키지 않아야 한다.

## 임시 등록 정리와 한계

소유 marker는 공개 CLSID, 부모 PID와 부모 생성 시간을 기록한다. 정상·오류 회수는 exact key의 marker·값·개수·실행 경로가 일치할 때만 삭제한다. 알 수 없는 값 또는 변경된 등록을 삭제하지 않는다. 고정 MSIX CLSID는 삭제 대상이 아니다.

부모는 3개 pipe와 nonce ACK를 인증한 즉시 portable key를 삭제하며 CLI 작업 전체 동안 등록을 유지하지 않는다. 작업자는 살아 있는 소유 부모의 image/token/creation time을 검증한 등록만 맡아, `Begin` 이전 부모 종료도 관찰하고 해당 key를 회수한다. **부모가 SCM 활성화 전에 강제 종료되거나 worker가 소유 부모를 검증하기 전에 부모가 사라지는 창에는 orphan key가 남을 수 있다.** reboot 또는 모든 강제 종료에서 자동 정리가 보장된다고 주장하지 않는다. 추가 정리 구현은 기존 key 보존과 소유 증거를 유지해야 한다.

## 현재 검증 범위

Linux의 실제 wire 검사와 Python 소스 변환 검사, Rust 1.93.1의 x64/ARM64 Windows `cargo check --all-targets --locked --offline`를 별도로 기록한다. 타입 검사 통과는 COM 호출 실행이나 WACK PASS를 뜻하지 않는다.

제품으로 복사하지 않는 `tests/transport_windows.rs`는 Windows에서 같은 EXE의 SCM worker를 이용하여 Unicode argv, password-stdin 바이트/EOF, 입력 없는 EOF, exit 1/3, 비JSON stdout, stderr, 실제 abort 후 다음 작업, cwd/합성 환경과 실제 worker PID·native machine·작업 시작 전 임시 key 삭제를 검사한다. Windows-only 단위 검사는 등록 충돌·변경 marker 보존·부분 등록 회수·고정 CLSID 삭제 배제·부모 PID 종료 배제·활성화 직전 소유 등록 검증을 검사한다. Linux에서는 이 Windows 실행 검사를 실행하지 않았다고 명시한다.

첫 실제 x64 진단에서는 등록 5개·wire 8개가 통과했지만 첫 `run_cli`가 OS 오류 5로 실패했다. 해당 원본 오류에는 operation 이름이 없어 실패 API를 직접 입증하지 않는다. 기본 LaunchingUser와 AAA 금지의 공식 계약 충돌을 근거로 위 per-call 후보를 마련했으며, 후보의 실제 Windows 통과는 새 실행으로 증명해야 한다. 이후 CoCreateInstance·proxy blanket 오류는 사용자 입력 없이 고정 operation 이름·HRESULT·원래 I/O 오류 종류를 기록한다.

표준 사용자/HKCU, 관리자/UAC 비활성/HKLM, 실제 설치된 MSIX fixed CLSID와 package identity, x64/ARM64 native 실행, 실제 MCP 도구의 성공·암호·부분 batch·ir-diff exit 3·오류·worker 강제 종료 후 부모 생존, 등록 강제 종료 정리 제어와 새 전체 WACK 결과는 후속 Windows 실행 증거가 필요하다. 이 문서는 그 결과를 대신하지 않는다.

## 공식 근거

- [LocalServer32와 ServerExecutable](https://learn.microsoft.com/en-us/windows/win32/com/localserver32)
- [MSIX com:ExeServer](https://learn.microsoft.com/en-us/uwp/schemas/appxpackage/uapmanifestschema/element-com-exeserver)
- [HKCR merged view와 관리자 COM 규칙](https://learn.microsoft.com/en-us/windows/win32/sysinfo/merged-view-of-hkey-classes-root)
- [REGCLS_SINGLEUSE](https://learn.microsoft.com/en-us/windows/win32/api/combaseapi/ne-combaseapi-regcls)
- [LaunchingUser 기본 신원](https://learn.microsoft.com/en-us/windows/win32/com/launching-user)
- [CLSCTX_ENABLE_AAA의 호출별 예외](https://learn.microsoft.com/en-us/windows/win32/api/wtypesbase/ne-wtypesbase-clsctx)
- [인터페이스 marshaling](https://learn.microsoft.com/en-us/windows/win32/com/interface-marshaling)
- [Named pipe 보안과 권한](https://learn.microsoft.com/en-us/windows/win32/ipc/named-pipe-security-and-access-rights)
- [실제 pipe client PID](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-getnamedpipeclientprocessid)
