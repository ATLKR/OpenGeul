# 다음 후보 품질 개선 실행 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. 진행 상황은 아래 체크박스에 기록합니다.

**Goal:** 저장·종료의 재현된 결함을 수정하고 Windows 인쇄 CI를 실제 관측에 근거해 복구합니다.

**Architecture:** 기존 overlay와 준비 스크립트에 최소 수정을 적용합니다. 문서 저장, 종료 처리, Windows 인쇄는 독립적으로 검토하고 검증된 변경을 같은 후보에 통합합니다.

**Tech Stack:** Python, TypeScript, Rust, Windows Win32, GitHub Actions.

**Spec:** `docs/NEXT_RELEASE_GOAL.md`와 사용자의 계속 개선 요청.

## Global Constraints

- 제출된 정규 `v1.1.3`·Source87·공개 파일 22개를 보존합니다.
- Store는 API만 사용하고 무료 가격·인증 후 자동 공개를 유지합니다.
- MCP 서버의 별도 작업자와 실패 격리를 유지합니다.
- Windows x64·ARM64, 전체 WACK, 문서 출력 기준과 창 소유권 검사를 유지합니다.
- Telemetry 수집 코드는 다음 후보에 포함하지 않습니다.
- 공개 저장소의 표준 무료 러너를 사용하고 캐시·유료 러너·강제 푸시를 도입하지 않습니다.
- 정규 1.1.4의 전체 Source와 별도 Store 신원 검증을 완료했습니다. 이전 처리 중 제출을 보존하며 새 API 접수는 대기합니다.

## Review Focus

- 저장 검증 도중 외부에서 바뀐 파일은 보존하고 덮어쓰기를 중단해야 합니다.
- 네이티브 창 닫기가 두 번 실패해도 사용자 안내와 종료 취소가 수행돼야 합니다.
- 자동 확인을 끈 뒤 도착하는 업데이트 응답은 뒤늦은 자동 알림을 만들지 않아야 합니다.
- 인쇄 버튼 좌표에 다른 창이 있으면 물리 입력이 발생하지 않아야 합니다.
- 처리 중인 Store 제출을 삭제하거나 미확정 업로드·접수를 반복하지 않아야 합니다.

### Task 1: 인쇄 실패의 실제 Windows 관측

**Files:** `ci/native_print_hit_diagnostic.py`, `.github/workflows/store-package.yml`의 진단 브랜치.
**Interfaces:** `click_owned_print_preferences(...)`, 원래 `runner-ready.py`의 `binding(env)`.

- [x] Source100의 실제 인쇄 실패와 CI83의 성공을 별도로 확인합니다.
- [x] 허용된 `diagnostic/arm-runner-ready71 / store-package.yml / observe / ATLKR / attempt1` 계약과 이전 이력을 보존합니다.
- [x] 실제 실행 Store74를 한 번 시작합니다. 제품·Store 쓰기와 Preferences 물리 입력은 금지합니다.
- [x] 원본 ZIP의 서버 SHA·CRC와 hit HWND, 부모, 버튼 관계, DPI를 검산합니다.
- [x] 관측한 원인을 재현하는 회귀를 먼저 실패시킨 뒤 필요한 인쇄 guard만 수정합니다.
- [x] 정상 owned 입력과 외부 창 거부를 함께 검증하고 실제 PDF 기준 검사를 실행합니다. (Source87 바이너리의 진단: x64 두 환경 8/8, 최종 ARM64 8/8; 새 후보 검증은 Task 4에서 별도 수행)

### Task 2: 종료의 이중 네이티브 실패 복구

**Files:** `scripts/prepare_hwpx.py`의 기존 desktop-events 통합 패치, 해당 TypeScript 회귀 검사.
**Interfaces:** pinned `confirmAndDestroyWindow()`의 기존 `onCancel`과 사용자 메시지 경계.

- [x] 원래 함수에서 native destroy가 두 번 거부될 때 취소와 메시지가 누락되는 경계를 재현합니다.
- [x] `confirm=true / unsaved=false / destroy reject twice` 회귀로 실패를 확인합니다.
- [x] fallback 실패를 처리하고 메시지 한 번·종료 취소 한 번·정상 promise 완료를 보장합니다.
- [x] 정상 종료·사용자 취소·실패 후 재시도를 검증하고 독립 검토합니다.

### Task 3: 저장·업데이트·MCP 독립 검토

**Files:** 현행 overlay와 준비된 HOP의 실제 파일 처리 경계 및 해당 회귀 검사.
**Interfaces:** 기존 파일 snapshot·저장 검증·업데이트 generation·MCP worker 수명 계약.

- [x] 실제 production method에서 파일 검증 도중 외부 변경을 주입해 원본 보존 여부를 확인합니다.
- [x] 새 문서를 비동기로 읽는 동안 현재 문서에 생긴 편집을 보존하고 교체를 중단합니다.
- [x] 암호 대기 후에도 WASM 교체 직전에 확인하고, 수정한 document-open 소스를 전체 계약과 준비 ledger에 결합합니다.
- [x] 결함이 재현되면 같은 동작의 실패 회귀를 먼저 만들고 최소 수정합니다.
- [x] 자동 확인 OFF·종료·동시 수동 확인과 worker 실패·정리 경계를 검토합니다.
- [x] 확정된 결함만 통합하고 검토 범위의 한계를 기록합니다.

### Task 4: 통합과 새 후보 검증

**Files:** 통합한 변경, `docs/NEXT_RELEASE_GOAL.md`, `docs/VERIFICATION.md`.

- [x] 변경별 RED→GREEN과 독립 검토를 확인하고 충돌을 해결합니다.
- [x] 필수 로컬 검사 두 묶음과 변경 경계의 Rust·TypeScript 검사를 실행합니다. (최종 제품 소스 `2259590`: CI229·제품898, 총1,127개와 CI86 통과; 독립 검토의 미해결 Critical·Important 0개)
- [x] 같은 새 후보에서 실제 Windows x64·ARM64·인쇄·설치·MCP·전체 WACK를 실행합니다. (Source104 `38373538189`·시도1: 전체22 성공, 두 WACK 각각 필수13·선택11 PASS)
- [x] 전체 실행 성공과 원본 파일·해시를 확인한 뒤 서명 없는 릴리스 후보를 확정합니다. (`v1.1.4-dev.104.1`, 릴리스411525213, 공개22자산의 서버 SHA256·원본 바이트 검산 완료)
- [x] 정규 `v1.1.4`·`131ccbf`의 Source105 `38381387804`·시도1 전체22 성공과 공개22자산 원본 바이트를 검산합니다.
- [x] 단일 자동 Store80 `38387455631`·시도1의 5개 신원 검증 게이트·양쪽 전체 WACK13+11·ARM64 설치MCP17을 확인합니다.
- [x] 자산22개를 유지한 GitHub stable·latest 승격과 website main `a5378df`의 실제7경로 배포·본문해시를 확인합니다.
- [ ] 1.1.4 API 접수와 실제 결과를 확인합니다. Store80은 기존SID `1152921505702110055` 처리 중 보호 guard로 BLOCKED·Store 제출 변경0이며, 전체 journal 상태와 이력을 보존했습니다. 시간별 조건 조회 후속 작업을 활성화했으며 접수 완료로 표시하지 않습니다.

검토 결과가 실제 결함을 보여주지 않으면 임의의 기능이나 추측 최적화를 추가하지 않습니다. 새 실패는 원본 증거를 보존하고 원인을 확인한 뒤 다음 수정으로 진행합니다.

### Task 5: 새 후보의 ARM64 인쇄 전경 복구와 입력 보호

**실제 근거:** Source102 `38362034518`·`d5e3016`·시도 1은 19개 작업 성공,
ARM64 인쇄·WebKit 실패, 릴리스 건너뛰기의 전체 실패입니다. 새 제품의 ARM64
설치·MCP·전체 WACK는 통과했습니다. table-600은 A4 설정 이후 여백 옵션을
기다리는 동안 외부 WSL 터미널로 전경이 바뀌었습니다. page-range는 설정과
Preferences를 통과했으나 Print 이후 Save 창을 관측하지 못했습니다.
두 실패 시 화면에 외부 창이 있었고 page-range 클릭 순간의 전경·hit 정보는
없으므로 같은 원인으로 확정하지 않습니다.

**Files:** `e2e/preview_settings.py`, `e2e/print_focus.py`의 preview 경계,
새 native Print 입력 helper, `e2e/virtual_print.py`와 해당 회귀 검사.

- [x] 전경 상실·여백 popup 부재와 명시적 collapsed 상태의 복구 조건을 configure_preview에서 먼저 재현합니다. (실제 실패의 collapsed 숫자는 미수집)
- [x] 같은 소유 dropdown의 확정된 전경 상실·닫힘에만 기존 제한 시간 안에서
  한 번의 명시적 소유 창 복구를 수행합니다. read-only 관찰은 입력하지 않습니다.
- [x] native Print는 실제 앱·WebView process handle, 창·버튼·전경·좌표를
  결합한 뒤 한 번만 물리 입력합니다. 다른 창·PID 재사용·좌표 변경은 거부합니다.
- [x] 원본 소유권·PDF·스풀러·페이지 기준과 제한 시간을 유지하고 독립 검토합니다. (자체 팝업 오분류와 UIA 상태 조회 사이 전경 변경도 별도 RED→GREEN)
- [x] 통합한 새 후보에서 전체 Windows 소스·설치·MCP·인쇄·전체 WACK를 다시 검증합니다. (정규 Source105 전체22 성공; 실제 인쇄24/24, PDF21개·24페이지 기존 기준 대조)

Source105의 `previewRecoveryCount`는 24건 모두 0입니다. 실제 복구 분기의
실행이나 Source102 원래 실패와 같은 원인의 해결을 주장하지 않습니다.
Source105의 실제 Release 병렬도는 x64 편집기4·CLI12, ARM64 편집기·CLI
각각8개이며 Source104 선택값과 구분합니다. 속도 향상은 보장하지 않습니다.

동일 소스·입력 22개를 사용한 Source103의 브라우저 전용 진단에서는 세
브라우저가 각각 10/10 통과했습니다. 최초 WebKit target crash의 원인은 아직
미확정이며 수정 완료로 표시하지 않습니다. 브라우저 진단의 성공을 새 최종
후보의 전체 소스 성공으로 대체하지 않습니다.
