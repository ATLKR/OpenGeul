# E2E와 HWPX 저장 검증 범위

이 문서는 설정된 검증 범위를 설명합니다. 실행하지 않은 테스트가 통과했다는 주장이 아닙니다. 정확한 커밋의 Actions 실행과 `results.json`/JUnit 출력을 확인하세요.

## 릴리스 필수 검증

Windows 릴리스 워크플로는 공개 저장소의 표준 실행기만 사용합니다. 먼저 고정된 업스트림 소스에서 Windows x64 앱, CLI, 포터블 ZIP, 서명되지 않은 MSIX, 배포용 프런트엔드와 합성 테스트 자료를 빌드합니다. 이후 세 그룹이 이 출력물을 대상으로 병렬 실행됩니다.

| 검증 | 환경 | 설정된 검사 |
|---|---|---|
| 네이티브 앱 | x64 `windows-2025`, `windows-2022` 및 Windows 11 ARM64 | 실제 WebView2·네이티브 파일 대화상자의 환경별 UI 28개(기존 16개 보존) 및 별도 암호 안전성 8개 사례 |
| 배포용 브라우저 프런트엔드 | `ubuntu-24.04`의 Chromium, Firefox, WebKit | 실제 WASM 내보내기와 브라우저 다운로드를 사용하는 브라우저별 UI 테스트 14개(기존 10개 보존) |
| 설치 | `windows-2025` | 임시 테스트 인증서로 사본에 서명하고 선언된 VCLibs 프레임워크 의존성을 준비한 뒤, 패키지 식별자 아래 설치 앱 활성화·설치 CLI 실행·파일 연결 확인·제거 |
| WACK | 설치 동작 확인과 제거 후 `windows-2025`의 동일한 서명 후보 MSIX | 사용 가능한 Windows App Certification Kit 실행 후 실제 XML 결과·식별자·버전·전체 실행 상태 검증, 키트가 없으면 명시적으로 기록 |

현재 설정된 편집기 UI는 브라우저 14개 × 3환경과 native 28개 × 3환경, 총 126회입니다. 별도 암호·인쇄·MCP 검사와 합치지 않은 UI 수치입니다. `e2e/ui_contract.py`에 기대 case ID와 고정 수를 명시하며 발견된 suite 길이로 기대값을 다시 계산하지 않습니다. 실행 전 발견 ID가 canonical 명시 순서까지 정확히 일치해야 하고, 실행 후 JSON과 JUnit도 같은 순서여야 합니다. JSON의 개별 ID·중복 없음·모두 PASS·필수 oracle 판정·skip 없음·JUnit totals/ID/status/time 일치가 필수입니다. 명시한 실제 helper 파일의 SHA-256을 실행 전후 및 저장된 JSON/JUnit 재검증에 사용합니다. 단순 메타데이터 hash 기록으로 통과시키지 않습니다. 기존 필수 `native-e2e`, `native-e2e-arm64`, `browser-e2e` 작업 안에서 실행하므로 누락·실패가 기존 Source→Store gate에 전파됩니다.

기존 사례는 문서 열기, 확정 Unicode, HWPX 저장·재열기, 연속 3회 roundtrip, text undo/redo, 원본 변경 없는 확대, 누락 글꼴, 명시적 글꼴 도움말·자동 다운로드 방지와 toolbar 설정을 검사합니다. native 전용 기존 사례는 HWP/HWPX 변환, 저장 취소, HWP 저장, 다중 창 생성과 손상 파일 오류 복구를 유지합니다.

| 추가 필수 UI 사례 | 대상·독립 판정 |
|---|---|
| 2×2 표 작성·아래 줄 삽입 | 공통: 실제 toolbar/grid, 4셀 입력과 Tab 3회 → 3×2 XML·각 셀 marker 위치/횟수, Undo 2×2·Redo 3×2·재열기 |
| 그림 파일 배치와 history | 공통: 소유 32×16 PNG의 실제 file chooser·page bbox drag → pic/BinData 참조·40×20mm 크기·Pillow 전체 checkerboard, Undo/Redo·재열기 |
| 그림 배치 중 문서 교체 | 공통: A의 decode·placement 준비 완료 → 같은 Session 파일 메뉴로 B 열기 → B 클릭·저장 → 그림 0개·본문 정확 보존 |
| 찾기/바꾸기와 기본 서식 | 공통: 실제 모두 바꾸기·Undo/Redo, 선택 범위 굵게·14pt → 독립 XML의 charshape·전체 marker 범위 및 비선택 본문 서식·재열기 |
| 실제 clipboard 키보드·메뉴 | native 전용 2개: 실제 Windows Ctrl+C/X/V와 편집 메뉴, OS CF_UNICODETEXT 읽기·정확한 삭제 영역·Undo/Redo·저장·재열기 |
| 설치된 글꼴 선택 | native: 실제 글자 모양 대화상자의 감지된 로컬 글꼴 그룹에서 Arial 클릭 → 독립 fontRef·본문 범위·재열기·원본 SHA; 다운로드/설치 없음 |
| GUI PDF 기본·복합·취소 | native 전용 3개: 파일 → PDF 내보내기와 소유 picker. HWP/HWPX·Unicode, 명시 생성 2쪽·표·그림과 unsaved marker → PDF magic·A4·정확한 쪽 수·PDFium text/실제 ink·Pillow pattern. 원본 SHA·dirty·다음 편집/저장, 취소는 실제 picker에 기존 target 경로 입력·readback 후 Cancel → target SHA·부분 출력 없음 → 실제 Save As XML·새 GUI PDF 내보내기 성공으로 작업 잠금 해제 확인 |
| 최근 문서 선택·재시작·목록 비우기 | native: 변경 전에 실제 Windows/github-hosted/repository/Source job/run/attempt 1/checkout/native process 확인. 모든 recent path가 이 실행 소유 범위여야 선택/clear 허용. 실제 새 PID에서 목록 유지·선택·clear 후 재시작 빈 목록 |
| 실제 Windows Explorer DnD | native: 새 소유 folder/window의 HWND·PID·실제 선택 path와 제품 HWND·page bbox·입력점 소유권 확인 후 물리 mouse drag/drop. marker·Save As XML·원본 SHA·invalid drop 후 다음 편집/저장. 합성 DOM/Tauri event·argv open으로 대체하지 않음 |

GUI PDF는 **Print To PDF와 별도 제품 경로**입니다. 입력의 marker·dimension·pattern을 미리 정하며 GUI PDF나 CLI PDF·인쇄 goldens를 정답으로 사용하지 않습니다. 출력이 저장된 뒤 기본 viewer 열기가 실패한 경우는 별도 predicate로 기록하고 실제 PDF oracle는 계속 적용합니다. 새 2쪽 입력은 이 UI 사례의 소유 폴더에서 생성하므로 인쇄 job의 `print-multipage.hwpx`가 UI inputs에 있다고 가정하지 않습니다.

위 추가 사례는 2026-10-14에 구현한 **후속 승인 Source Actions의 필수 대상**이며, 아직 새 Windows/native3 또는 browser3 제품 실행을 하지 않았습니다. 오프라인 oracle/manifest negative unit의 PASS를 제품 UI 성공으로 승격하지 않습니다. 실제 OS clipboard 검증 대상은 Windows 제품의 native3입니다. 현재 Linux headless browser3의 OS clipboard/API 성공은 이 구성으로 검증하지 않으며, native clipboard를 browser mock/합성 event로 대신하지 않습니다. 최근 문서는 native RoamingAppData의 실제 profile을 사용하며 임시 WebView2 profile로 격리됐다고 주장하지 않습니다. local/self-hosted/다른 attempt 또는 outside-owned recent entry는 실패하며 목록을 지우지 않습니다. Explorer/글꼴/clipboard 환경이 준비되지 않아도 native 사례를 skip/PASS로 대체하지 않습니다.

과거 **Source105**의 원본은 UI 78회(공통 10 × browser3 + native16 × native3), 암호 24회, 인쇄 24회, MCP 85회로 총 **211회/49개 정의**입니다. 이는 당시 결과이며 현재 설정된 14/28 UI manifest의 실행 증거가 아닙니다. 기존 62/78 집계는 ARM64를 포함하기 전 2개 x64 환경의 UI/암호 합계였습니다. 과거 원본 receipt, Source22·optional WACK·인쇄 goldens는 바꾸지 않습니다.

암호 검사는 소스와 연결된 WASM이 작성한 소유 HWP/HWPX 입력의 잘못되거나 누락된 암호를 UI 사용 전에 독립 컨테이너/XML로 거부합니다. 실제 암호 재입력·취소와 다른 이름으로 저장 형식은 암호 원본 SHA를 보존해야 합니다. 미저장 문서 교체와 Alt+F4는 취소, 평문 저장 동의 취소, 안전한 다른 이름 저장 뒤 정리 전에 원래 PID의 정상 종료를 확인합니다. 새 native process에서 평문 출력을 다시 열어 편집하며 기존 암호·입력 소유권 gate를 유지합니다.

네이티브 회귀 테스트는 리비전 충돌, 외부 파일 변경, 잘못되거나 형식 표시가 틀린 바이트, 원자적 교체 실패, 임시 저장 파일 소유권과 미저장 상태 보존도 검사합니다. 프런트엔드 회귀 테스트는 두 직렬화 경로, 취소, 쓰기 실패, 동시 저장과 비동기 쓰기·정리 중 편집을 검사합니다. 기준 RED 검사는 원래의 HWPX 저장 거부를 의도적으로 재현한 뒤, 기능 패치를 적용하기 전에 원래 테스트를 복원합니다.

## 재현

로컬에서는 제품을 시작하지 않는 독립 oracle와 manifest negative 검사부터 실행합니다.

```bash
python -m unittest tests.test_ui_contract tests.test_supported_feature_oracle tests.test_hwpx_oracle tests.test_hop_integration -v
```

전체 `e2e/run.py` 실행은 승인된 Source Actions의 기존 필수 UI 작업에서 수행합니다. 워크플로가 제품/소유 fixture 경로, mode/browser/architecture와 실제 Source 식별자를 제공합니다. 최근 문서가 포함된 전체 native suite는 일반 로컬 profile이나 self-hosted 실행을 거부하며 이 조건을 환경 변수 위조로 우회하지 않습니다. WebView2 Runtime·실제 Windows 데스크톱과 Explorer가 필요합니다. `ensure-webview2.ps1`과 `msix-install.ps1`도 일반 사용자의 시스템을 변경하지 않도록 GitHub 밖의 실행을 거부합니다.

브라우저 작업은 배포용 프런트엔드를 루프백 7700에서 제공하고 고정한 Chromium/Firefox/WebKit에서 실행합니다. 페이지 생성·탐색 전에 `showOpenFilePicker`와 `showSaveFilePicker`의 가용성을 제거하여 세 엔진 모두 실제 공개 메뉴의 HTML 파일 선택기와 다운로드 대체 경로를 검사합니다. File System Access의 OS 열기·저장 대화상자는 이 브라우저 시험 범위에 포함되지 않습니다. clipboard 권한을 합성하거나 실제 OS clipboard 성공을 가정하지 않습니다.

## 증거와 보안

크기가 제한된 증거를 하루 보존합니다. 성공한 작업은 텍스트·JSON·JUnit을 최대 1 MiB, 실패한 작업은 스크린샷과 안전한 동작 기록 전용 추적을 포함해 최대 12 MiB 보관합니다. 사례별 진단보다 native3·browser3의 결과, 암호 테스트의 소스·실행 파일 식별 정보와 작은 합성 테스트 자료 메타데이터를 우선합니다. 실패 사례의 진단은 성공 사례보다 먼저 보존합니다. 누락 내용은 테스트 상태를 바꾸지 않고 기록합니다. 문서와 글꼴 파일은 제외하며 브라우저 프로필은 증거 디렉터리 밖에 둡니다. 추적의 네트워크·DOM 리소스 수집은 비활성화하여 설치된 글꼴 프로그램이 추적 리소스로 재배포되지 않게 합니다. 배포용 테스트 API, 비공개 문서, 서명 키, 인증서와 테스트 서명 MSIX는 함께 배포하지 않습니다. 다운로드한 포터블 편집기·CLI는 검증된 MSIX 안의 실행 파일과 정확히 일치해야 합니다.

실패, 건너뛰기, 예상 테스트 누락이나 설치 실패는 릴리스를 막습니다. 불안정한 결과를 숨기려고 테스트를 자동 재시도하지 않습니다. PR은 릴리스를 게시하지 않습니다. 주간 예약 실행은 테스트만 하며, main/tag/수동 게시도 모든 필수 검증을 통과해야 합니다.

설치 산출물에는 `installed-launch.json`, `installed-cli.json`, 설치 CLI 도움말, 등록된 프레임워크 출처와 `wack.json`이 포함됩니다. CLI 검사는 `Invoke-CommandInDesktopPackage`와 `PreventBreakaway`를 사용해 패키지 식별자를 확인하고 설치 CLI를 해당 패키지 그래프 안에서 실행합니다. 키트가 있으면 설치 패키지를 제거한 뒤 정확한 해시를 확인한 서명 MSIX에 `appcert reset`과 `appcert test -appxpackagepath ... -reportoutputpath ...`를 실행합니다. [Microsoft 명령줄 안내](https://learn.microsoft.com/en-us/windows/uwp/debug-test-perf/windows-app-certification-kit#validate-your-windows-app-using-the-windows-app-certification-kit-from-a-command-line)를 따릅니다. 검증을 통과하려면 후보 식별자·버전의 부분 실행이 아닌 최종 XML 보고서와 종료 코드 0이 필요합니다. Centennial 식별자는 포함된 AppxPackage 매니페스트에서 읽으며 프로그램 기록 및 비어 있지 않은 보고서 헤더와 일치해야 합니다. 모든 필수 테스트가 통과해야 합니다. 필수 경고·실패, XML 누락·형식 오류, 식별자·버전 불일치와 15분 시간 초과는 검증을 막습니다. [Microsoft의 Desktop Bridge 필수·선택 테스트 구분](https://learn.microsoft.com/en-us/windows/uwp/debug-test-perf/windows-desktop-bridge-app-tests#required-versus-optional-tests)에 따라 선택 항목에 문제가 있어도 `submissionCheckPassed=true`일 수 있지만, `status=warning`, `passed=false`, 원래 전체 결과와 발견 메시지는 증거에 유지합니다. 완전한 WACK PASS에는 여전히 모든 테스트 통과가 필요합니다. XML과 로그는 기존의 크기 제한 증거 산출물에 보관합니다. 키트가 없으면 `wack.json`에 `status=unavailable`, `passed=false`를 기록합니다. 설치가 통과하더라도 WACK은 미검증입니다. 소비자 Windows 10/11과 Partner Center 인증은 별도입니다.

## 한계

GitHub Windows 레이블은 현재 서버 실행기 이미지를 나타내며, 소비자 Windows 10/11 기기 전체 매트릭스가 아닙니다. 네이티브 테스트는 Windows UI Automation과 범위를 제한한 WebView2 CDP를 사용합니다. 관리자 권한 호스팅 실행에서는 실행 파일별 임시 레지스트리 설정을 사용할 수 있으며 정리 시 복원합니다. 폐기 가능한 GitHub 호스트로만 제한합니다. 브라우저 시험은 File System Access 열기·저장 API를 끈 실제 HTML 파일 선택기·다운로드 경로만 다루며, File System Access OS 대화상자와 네이티브 Windows 대화상자를 검증하지 않습니다. native 시험에서는 이 브라우저 조건을 적용하지 않고 실제 Tauri/Windows 파일 대화상자를 사용합니다. `insert_text`는 확정된 Unicode를 확인하며 실제 사용자의 Windows IME 조합 세션은 아닙니다. 실제 프린터, 접근성 장치, 합성 지원 형식 사례를 벗어나는 암호 문서, 복잡한 업무 서식, 모든 제3자 글꼴 권리와 Store 인증에는 추가 검증이 필요합니다. HWPX 지원은 고정된 직렬화기를 사용하며 지원하지 않는 원본 기능은 완벽하게 보존되지 않을 수 있습니다. 개발 빌드 평가 시 원본 파일을 유지하세요.

참고 자료: GitHub Actions 청구 문서와 Playwright 공식 WebView2 테스트 안내.
