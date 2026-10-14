# 지원 기능 정확성 개선 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 지원 기능의 실제 사용자 흐름을 검증하고, 재현된 문서 변경 결함을 수정하여 다음 후보를 준비합니다.

**Architecture:** 현재 HOP/rhwp 구조와 OpenGeul overlay를 유지합니다. 지연 작업은 원래 문서·편집 문맥과 연결하고, 검증 실패는 비밀을 노출하지 않는 고정 코드로 구분합니다. 기능별 성공은 실제 실행한 경로의 증거로만 판단합니다.

**Tech Stack:** TypeScript, Rust, Python, 고정 HOP 0.4.5·rhwp 0.8.7, Windows x64·ARM64 및 소스 빌드 WASM.

**Spec:** 사용자의 2026-10-14 지시: 계속 개선하며 지원 목표 기능은 모두 동작해야 합니다. 기존 README의 지원 범위와 실제 제공 UI·CLI/MCP 기능을 검증 기준으로 사용합니다.

## Global Constraints

- 정규 `v1.1.4` 태그 `131ccbf3ac10a82e1d6785b4c906fb836b912e73`, 공개 릴리스 `411579723`의 22개 자산과 기존 Store 제출을 변경하지 않습니다.
- Store 작업은 공식 API와 승인된 Actions만 사용합니다. 실패 job만 재실행하거나 CI 환경·ref를 위조하지 않습니다.
- 필수·선택 WACK, x64·ARM64 native, MCP 실패 격리, 인쇄·PDF 기준과 입력 소유권을 유지합니다.
- Telemetry, 자동 복구·저장, WebView 없는 화면과 Office 연동 연구는 새 지원 기능으로 광고하지 않습니다.
- 비밀값·OAuth·다운로드 SAS·예외 본문·URL을 로그나 저장소에 기록하지 않습니다.
- 새 제품 변경은 공개된 1.1.4와 구분되는 다음 후보에 포함합니다. 공개 파일이나 태그를 덮어쓰지 않습니다.

## Review Focus

- 이미지·RTF·비동기 클립보드 작업 중 문서 전환·종료·선택 또는 편집 변경으로 다른 문서가 바뀌는 경로.
- 표·그림·찾기/바꾸기·클립보드·끌어놓기·최근 문서의 UI 동작과 실제 저장 결과 사이의 차이.
- GUI PDF 내보내기와 인쇄 PDF의 서로 다른 실행 경로, 실패 뒤 기존 파일과 문서 보존.
- MCP 세션·workspace와 무상태 worker 경로의 지원 범위 및 실제 실행 검사의 공백.
- QA 자료 준비 실패가 ARM 제품 검사를 실행하지 않았는데 검증 성공으로 기록되거나 비밀이 출력되는 경로.

---

### Task 1: 비동기 붙여넣기 문서 변경 방지

**Files:** `scripts/prepare_upstream.py`, 기존 clipboard overlay/test wiring, 새 실제 엔진 회귀 검사.

**Interfaces:** 기존 pinned `InputHandler.onPaste`, 문서·편집 문맥과 `SnapshotCommand`/`CommandHistory`를 사용합니다. 준비 변환이 고정 upstream 계약을 확인한 뒤 최소 수정을 적용해야 합니다.

- [x] 실제 pinned handler와 native WASM에서 A 이미지 읽기 대기 → B 문서 전환 → B 텍스트 선택 → A 작업 완료 시 B 텍스트가 지워지는 결함을 회귀 검사로 RED 확인합니다.
- [x] 실제 제품의 문서·선택 상태 변경 경계를 대조하고 모든 비동기 clipboard 이미지/RTF 변환 뒤 원래 문맥이 유효할 때만 변경합니다.
- [x] 문서 전환·종료·같은 문서의 편집/선택 변경은 취소하고, 바뀌지 않은 문서의 정상 이미지 붙여넣기·undo/redo·저장을 유지합니다.
- [x] 회귀 검사와 기존 clipboard/editor 검사, 준비 변환 계약을 실행하고 독립 검토합니다.

### Task 1B: 그림 파일 삽입의 문서 소유권과 배치 해제

**증거:** 실제 pinned insertCommands·InputHandler·finishImagePlacement·native WASM/History에서 정상 대조와 세 가지 경합을 재현했습니다. A의 그림 바이트 읽기 또는 decode 대기 중 B로 교체하거나, 배치 모드 준비가 끝난 뒤 B로 교체하면 다음 클릭이 B에 그림을 삽입합니다.

- [x] 파일 선택·바이트 읽기·이미지 decode와 그림 배치를 원래 문서의 identity/generation/lifecycle에 결합합니다.
- [x] 문서 교체·deactivate·dispose 뒤 대기 작업과 이미 켜진 배치를 취소합니다. 정상 그림 삽입·단일 undo/redo·저장·재열기는 유지합니다.
- [x] 실제 command/placement/native WASM regression을 RED→GREEN으로 확인하고 소스 준비·component 계약에 수정 파일을 강하게 결합합니다.
- [x] 새 구현자와 독립 검토로 확인합니다. 원본 tag/공개 파일/Store 제출은 보존합니다.

### Task 1C: 비동기 설치 글꼴 읽기의 선택 소유권

**증거:** actual HOP Toolbar.applyFontSelection → installed-only loadWebFonts → local-fonts → desktop-local-fonts의 list_local_fonts/read_local_font/FontFace.load 경계를 확인했습니다. FIRST 선택에서 읽기를 시작해 SECOND로 선택을 바꾸면 SECOND에만 글꼴과 undo가 적용됩니다. native 외부 경계만 통제했으며 실제 formatter/native WASM을 사용했습니다.

- [x] 설치 글꼴 읽기 완료 뒤 원래 문서·선택·편집 문맥이 유효할 때만 서식을 적용합니다. 최신 font request의 기존 취소 계약을 유지합니다.
- [x] 정상 본문·셀·개체 선택, 문서 교체·종료·선택 변경/복귀와 layout-only 완료를 회귀 검사합니다.
- [x] prepared toolbar 소스와 ledger 계약을 강하게 결합하고 기존 installed-only/no-font-download 및 undo/redo·저장을 유지합니다.
- [x] 실제 원본 RED→GREEN과 독립 검토를 마친 뒤 Task3 사용자 흐름 검사로 연결합니다.

### Task 2: QA 자료 다운로드 실패의 안전한 진단

**Files:** `scripts/mcp_qa_download.py`, `tests/test_mcp_qa_download.py`.

**Interfaces:** Source/Store/PR 검증, bounded GET, 원자료 ZIP 검산과 원자적 no-replace 게시를 유지합니다. stderr에 고정 stage/code·허용된 숫자형 오류 힌트만 남깁니다.

- [x] 현재 범용 오류가 HTTP·크기·시간 제한·원자료 검증·게시 실패를 구분하지 못하는 경로를 RED 검사로 확인합니다.
- [x] 허용 목록 기반 진단을 추가합니다. URL·본문·인증·예외 문자열·파일명·traceback은 출력하지 않습니다.
- [x] 유일하고 유효한 HTTP 숫자 힌트만 기록하며, 제한 초과·모호한 힌트·예외적 오류는 기존 실패로 유지합니다. 자동 재시도는 추가하지 않습니다.
- [x] `installed`·`mcp-qa`·origin 디렉터리에 진단 파일을 선행 생성하지 않습니다. 원래 exit1·상한·목적지 보존을 검사합니다.
- [x] 기존 전체 QA 계약 검사와 원자료 snapshot 순수 재현을 실행하고 독립 검토합니다.

### Task 3: 지원 기능별 실제 검증 확대

**Files:** `e2e/test_editor.py`, `e2e/test_hop_followups.py`, `e2e/mcp_worker.py`, 해당 검증 계약과 기능 범위 문서.

- [x] 기능별 지원·현재 실행 증거·빠진 사용자 흐름을 목록화합니다. 같은 테스트의 환경별 반복 횟수를 기능 수로 세지 않습니다.
- [x] 문서 간 비동기 붙여넣기와 그림·글꼴 결함을 수정하고, 클립보드·표·이미지·최근 문서·끌어놓기·GUI PDF·MCP의 필수 실행 사례를 구현하고 독립 검토했습니다. 실제 Windows·브라우저 실행은 Task 4에서 확인합니다.
- [ ] UI 조작 이후 실제 HWP/HWPX/PDF 내용·문서 보존을 검사합니다. 테스트 hook만 성공시키거나 인쇄 PDF를 GUI export의 근거로 사용하지 않습니다.
- [x] 실행하지 못한 목표 기능은 성공 표시하지 않고 남은 실행 경로를 기록합니다.

### Task 4: 후보 전체 검증과 기록

- [ ] 최종 후보의 필수 사전 검사 두 묶음과 준비된 TypeScript/Rust 검사를 실행합니다.
- [ ] 미해결 데이터 손실·주요 기능 결함을 독립 검토하고 수정합니다.
- [ ] 새 후보에서 Windows x64·ARM64·브라우저·설치·MCP·인쇄·양쪽 전체 WACK를 실제 실행합니다.
- [ ] 제품 버전과 공개 파일·사이트 안내는 해당 후보 전체 성공 이후 확정합니다. 이전 1.1.4와 Store82 실패 증거는 보존합니다.
