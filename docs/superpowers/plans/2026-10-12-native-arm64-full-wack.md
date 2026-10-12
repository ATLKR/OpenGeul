# Windows ARM64와 전체 WACK 통과 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox syntax for tracking.

**Goal:** 동일한 1.1.3 소스에서 x64·ARM64 제품과 전체 WACK을 검증하고 API로 한 Store submission을 접수한다.

**Architecture:** 아키텍처를 명시적으로 전달하고 동일 소스의 구성 요소·패키지·증거를 아키텍처별로 연결한다. OS 활성화와 CLI 작업자 계약을 개선한 뒤 전체 WACK을 강제한다. Store에는 MSIX 두 개와 묶인 재시도 상태를 사용한다.

**Tech Stack:** Python 3.12+, PowerShell 7, Rust 1.93.1, Tauri 2.11.1, WinRT, GitHub Actions 표준 Windows 러너, Partner Center API.

**Spec:** docs/superpowers/specs/2026-10-12-native-arm64-full-wack-design.md

## Global Constraints

- 정확한 아키텍처는 x64(0x8664)·arm64(0xAA64), 버전은 1.1.3/1.1.3.0이다.
- 기존 기능·출처·전체 런타임 일치·기준·허용 오차·무료 러너·수동 공개를 유지한다.
- 전체 WACK PASS 전에 정규 릴리스나 Store 제출을 실행하지 않는다.
- Telemetry 런타임을 추가하지 않는다. Store는 API로만 작업한다.

## Review Focus

- 잘못된 아키텍처의 구성 요소·DLL·매니페스트가 같은 버전으로 합쳐지는 경우.
- x64 에뮬레이션이나 검사 컨트롤러의 아키텍처를 제품 네이티브 증거로 바꾸는 경우.
- CLI 작업자 예외·암호/stdin·nonzero JSON 결과의 계약이 바뀌는 경우.
- 한 Store 패키지만 처리되거나 commit 응답이 불확실한 뒤 중복 제출하는 경우.
- 새 dual 공개판을 관측기가 거부하거나 과거·미공개 버전으로 배지가 회귀하는 경우.

### Task 1: 아키텍처 계약과 패키지 검증

**Files:** scripts/windows_arch.py, scripts/buildkit.py, scripts/releasekit.py, e2e/prepare_payload.py, tests/test_windows_arch.py, tests/test_buildkit.py, tests/test_releasekit.py, tests/test_payload_parity.py.

**Interfaces:** `require_architecture(value: str) -> str`, `target_triple(value: str) -> str`, `machine_for(value: str) -> int`; `manifest(identity, version, architecture='x64')`, `pe_machine(header, architecture='x64')`, `verify_msix(path, architecture='x64')`, `prepare(package, output, architecture='x64')`; `component_artifact_name(role, run_id, architecture='x64')`.

- [ ] 잘못된 PE·manifest·예상 아키텍처와 unknown/ARM64EC에 실패하는 검사를 먼저 작성·실행한다.
- [ ] 명시한 인터페이스로 x64 기본 계약과 ARM64 검증을 구현한다.
- [ ] 해당 검사와 전체 Python 검사 성공, 기존 x64 반례 유지, diff 검사를 확인하고 커밋한다.

### Task 2: 구성 요소·Windows ARM64 빌드와 실제 실행

**Files:** scripts/windows_components.py, scripts/build-msix.ps1, .github/workflows/msix.yml, ci/tests/, e2e/native/, e2e/msix_install.ps1, tests/test_windows_components.py.

**Interfaces:** Task 1의 architecture/target/machine 계약; 구성 요소 capture/combine에 명시한 architecture와 아키텍처별 artifact 이름·target을 전달한다.

- [ ] 혼합 target/PE/출처·ARM64EC 수용에 실패하는 검사를 먼저 작성·실행한다.
- [ ] 동일 소스와 공통 WASM에서 양쪽 GUI·CLI를 소스 빌드하고 각각 재포장한다.
- [ ] ARM64 실제 PID의 native 여부, 설치·제거·편집·암호·인쇄를 확인하고 x64 검사를 유지한다.
- [ ] 소스 준비에서는 컴파일·검사의 필수 원본을 보존하면서 대용량 참고 이미지의 불필요한 체크아웃을 피한다.

### Task 3: 정상 기능을 유지하는 WACK 수정과 전체 통과 게이트

**Files:** scripts/prepare_upstream.py, overlay/의 OS 활성화·검토한 의존성 패치, tests/, e2e/wack.ps1, e2e/wack_result.py.

**Interfaces:** OS URI·file·folder 활성화 실패를 Result로 반환하며 CLI 작업자 계약을 유지한다. `inspect`는 원문 판정을 보존하고 릴리스 실행기는 전체 `passed`를 강제한다.

- [ ] SDK 원문 분기·실제 호출 경로와 기능 계약을 바탕으로 수정 전 실패를 재현한다.
- [ ] 셸 호출과 불필요한 restart 경로를 정당한 OS/API·제품 범위로 수정한다. MCP 선택을 반영한다.
- [ ] unavailable/부분/경고/선택 FAIL이 릴리스 실행을 막는 검사를 RED→GREEN으로 확인한다.
- [ ] 동일 후보와 두 실제 Store identity 패키지의 전체 WACK 원문 PASS를 확인한다.

### Task 4: 양쪽 원본 출시·Store 제출·공개 관측

**Files:** scripts/releasekit.py, scripts/store_package.py, scripts/store_submit.py, scripts/store_release_status.py, .github/workflows/store-package.yml, tests/.

**Interfaces:** 아키텍처별 원본 MSIX·portable·출처·WACK을 동일 source/run/version에 묶는다. 두 package 해시 집합과 journal을 한 submission에 적용한다. 공개 JSON 6필드는 유지한다.

- [ ] 누락/중복/혼합 아키텍처·다른 소스·WACK 실패·부분 제출·재시도 불확실성·공개 회귀의 검사를 먼저 실행한다.
- [ ] 아키텍처별 bounded 원본, 두 Store MSIX, 배열 업로드와 journal을 구현하고 전체 관련 검사를 통과한다.
- [ ] canonical v1.1.3의 새 전체 검증·원본 바이트·양쪽 전체 WACK을 독립 검토한다.
- [ ] 실제 최신 Store 상태를 읽고 Free/Manual/Korean을 보존해 API로 제출한다. 접수 ID·상태·원본 출처를 기록한다.
