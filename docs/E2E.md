# E2E와 HWPX 저장 검증 범위

이 문서는 설정된 검증 범위를 설명합니다. 실행하지 않은 테스트가 통과했다는 주장이 아닙니다. 정확한 커밋의 Actions 실행과 `results.json`/JUnit 출력을 확인하세요.

## 릴리스 필수 검증

Windows 릴리스 워크플로는 공개 저장소의 표준 실행기만 사용합니다. 먼저 고정된 업스트림 소스에서 Windows x64 앱, CLI, 포터블 ZIP, 서명되지 않은 MSIX, 배포용 프런트엔드와 합성 테스트 자료를 빌드합니다. 이후 세 그룹이 이 출력물을 대상으로 병렬 실행됩니다.

| 검증 | 환경 | 설정된 검사 |
|---|---|---|
| 네이티브 앱 | `windows-2025`, `windows-2022` | 실제 WebView2 앱과 네이티브 파일 대화상자를 사용하는 OS별 편집기 UI 16개 및 암호 안전성 8개 사례 |
| 배포용 브라우저 프런트엔드 | `ubuntu-24.04`의 Chromium, Firefox, WebKit | 실제 WASM 내보내기와 브라우저 다운로드를 사용하는 브라우저별 UI 테스트 10개 |
| 설치 | `windows-2025` | 임시 테스트 인증서로 사본에 서명하고 선언된 VCLibs 프레임워크 의존성을 준비한 뒤, 패키지 식별자 아래 설치 앱 활성화·설치 CLI 실행·파일 연결 확인·제거 |
| WACK | 설치 동작 확인과 제거 후 `windows-2025`의 동일한 서명 후보 MSIX | 사용 가능한 Windows App Certification Kit 실행 후 실제 XML 결과·식별자·버전·전체 실행 상태 검증, 키트가 없으면 명시적으로 기록 |

기존 편집기 UI 시나리오 62회는 열기, 확정된 Unicode 입력, HWPX 편집·저장·재열기, 연속 3회 저장·재열기, 실행 취소·다시 실행, 원본 변경 없는 확대·축소, 누락 글꼴, 명시적인 글꼴 도움말과 자동 글꼴 다운로드 방지를 검사합니다. 네이티브 전용 시나리오는 HWP/HWPX 다른 이름으로 저장 변환, 네이티브 대화상자 취소, 기존 HWP 저장, 다중 창과 손상 파일 오류 복구를 추가합니다. 별도의 표준 라이브러리 ZIP/XML 판정기가 rhwp와 독립적으로 저장된 텍스트와 패키지 불변 조건을 확인합니다. 한컴과 픽셀 단위로 완전히 같음을 검증하는 테스트는 아닙니다.

Windows 이미지별 암호 안전성 8개 사례를 추가하면 편집기 UI 전체 실행은 78회입니다. 소스와 연결된 WASM은 이 작업에서 작성한 암호 HWP/HWPX 문서만 생성합니다. 독립적인 컨테이너·XML 대조 검사는 UI 사용 전에 잘못되거나 누락된 암호를 거부하고 평문 저장·재열기를 검증합니다. 실제 암호 재입력·취소와 두 가지 다른 이름으로 저장 형식은 암호 원본의 체크섬을 보존해야 합니다. 네이티브 미저장 문서 교체와 실제 Alt+F4 요청은 취소, 평문 저장 동의 취소, 안전한 다른 이름으로 저장 완료 후 정리 전에 원래 PID가 정상 종료하는지 확인합니다. 새 네이티브 프로세스에서 평문 출력을 다시 열고 편집합니다. 패키지의 소스·실행과 기록된 재빌드 엔진은 현재 워크플로와 일치해야 하며, 기존 16개 테스트도 유지합니다.

네이티브 회귀 테스트는 리비전 충돌, 외부 파일 변경, 잘못되거나 형식 표시가 틀린 바이트, 원자적 교체 실패, 임시 저장 파일 소유권과 미저장 상태 보존도 검사합니다. 프런트엔드 회귀 테스트는 두 직렬화 경로, 취소, 쓰기 실패, 동시 저장과 비동기 쓰기·정리 중 편집을 검사합니다. 기준 RED 검사는 원래의 HWPX 저장 거부를 의도적으로 재현한 뒤, 기능 패치를 적용하기 전에 원래 테스트를 복원합니다.

## 재현

Windows 개발 빌드 후 실행합니다.

```powershell
python -m pip install -r e2e/requirements.txt
python e2e/prepare_payload.py dist .work/e2e-runtime
$env:E2E_MODE='native'
$env:E2E_EXE=(Resolve-Path .work/e2e-runtime/OpenGeul.exe).Path
$env:E2E_FIXTURES=(Resolve-Path .work/e2e-fixtures).Path
$env:E2E_OUTPUT=Join-Path $pwd '.work/evidence'
python e2e/run.py
```

WebView2 Runtime이 설치되어 있어야 합니다. `ensure-webview2.ps1`과 `msix-install.ps1`은 의도적으로 GitHub 밖의 실행을 거부합니다. 일반 사용자의 시스템이 아닌 폐기 가능한 테스트 호스트를 준비하거나 일시적으로 변경하기 때문입니다. 브라우저 테스트는 `.work/hop/apps/studio-host/dist`를 루프백 포트 7700에서 제공하고 `E2E_MODE=browser`와 `E2E_BROWSER=chromium|firefox|webkit`를 설정한 뒤, 먼저 고정된 Playwright 브라우저를 설치합니다.

## 증거와 보안

크기가 제한된 증거를 하루 보존합니다. 성공한 작업은 텍스트·JSON·JUnit을 최대 1 MiB, 실패한 작업은 스크린샷과 안전한 동작 기록 전용 추적을 포함해 최대 12 MiB 보관합니다. 사례별 진단보다 두 네이티브 테스트의 결과, 암호 테스트의 소스·실행 파일 식별 정보와 작은 합성 테스트 자료 메타데이터를 우선합니다. 실패 사례의 진단은 성공 사례보다 먼저 보존합니다. 누락 내용은 테스트 상태를 바꾸지 않고 기록합니다. 문서와 글꼴 파일은 제외하며 브라우저 프로필은 증거 디렉터리 밖에 둡니다. 추적의 네트워크·DOM 리소스 수집은 비활성화하여 설치된 글꼴 프로그램이 추적 리소스로 재배포되지 않게 합니다. 배포용 테스트 API, 비공개 문서, 서명 키, 인증서와 테스트 서명 MSIX는 함께 배포하지 않습니다. 다운로드한 포터블 편집기·CLI는 검증된 MSIX 안의 실행 파일과 정확히 일치해야 합니다.

실패, 건너뛰기, 예상 테스트 누락이나 설치 실패는 릴리스를 막습니다. 불안정한 결과를 숨기려고 테스트를 자동 재시도하지 않습니다. PR은 릴리스를 게시하지 않습니다. 주간 예약 실행은 테스트만 하며, main/tag/수동 게시도 모든 필수 검증을 통과해야 합니다.

설치 산출물에는 `installed-launch.json`, `installed-cli.json`, 설치 CLI 도움말, 등록된 프레임워크 출처와 `wack.json`이 포함됩니다. CLI 검사는 `Invoke-CommandInDesktopPackage`와 `PreventBreakaway`를 사용해 패키지 식별자를 확인하고 설치 CLI를 해당 패키지 그래프 안에서 실행합니다. 키트가 있으면 설치 패키지를 제거한 뒤 정확한 해시를 확인한 서명 MSIX에 `appcert reset`과 `appcert test -appxpackagepath ... -reportoutputpath ...`를 실행합니다. [Microsoft 명령줄 안내](https://learn.microsoft.com/en-us/windows/uwp/debug-test-perf/windows-app-certification-kit#validate-your-windows-app-using-the-windows-app-certification-kit-from-a-command-line)를 따릅니다. 검증을 통과하려면 후보 식별자·버전의 부분 실행이 아닌 최종 XML 보고서와 종료 코드 0이 필요합니다. Centennial 식별자는 포함된 AppxPackage 매니페스트에서 읽으며 프로그램 기록 및 비어 있지 않은 보고서 헤더와 일치해야 합니다. 모든 필수 테스트가 통과해야 합니다. 필수 경고·실패, XML 누락·형식 오류, 식별자·버전 불일치와 15분 시간 초과는 검증을 막습니다. [Microsoft의 Desktop Bridge 필수·선택 테스트 구분](https://learn.microsoft.com/en-us/windows/uwp/debug-test-perf/windows-desktop-bridge-app-tests#required-versus-optional-tests)에 따라 선택 항목에 문제가 있어도 `submissionCheckPassed=true`일 수 있지만, `status=warning`, `passed=false`, 원래 전체 결과와 발견 메시지는 증거에 유지합니다. 완전한 WACK PASS에는 여전히 모든 테스트 통과가 필요합니다. XML과 로그는 기존의 크기 제한 증거 산출물에 보관합니다. 키트가 없으면 `wack.json`에 `status=unavailable`, `passed=false`를 기록합니다. 설치가 통과하더라도 WACK은 미검증입니다. 소비자 Windows 10/11과 Partner Center 인증은 별도입니다.

## 한계

GitHub Windows 레이블은 현재 서버 실행기 이미지를 나타내며, 소비자 Windows 10/11 기기 전체 매트릭스가 아닙니다. 네이티브 테스트는 Windows UI Automation과 범위를 제한한 WebView2 CDP를 사용합니다. 관리자 권한 호스팅 실행에서는 실행 파일별 임시 레지스트리 설정을 사용할 수 있으며 정리 시 복원합니다. 폐기 가능한 GitHub 호스트로만 제한합니다. 브라우저 테스트는 실제 브라우저 간 다운로드 대체 경로를 검사하려고 File System Access 파일 선택기를 명시적으로 끕니다. 네이티브 Windows 대화상자를 검증하지는 않습니다. `insert_text`는 확정된 Unicode를 확인하며 실제 사용자의 Windows IME 조합 세션은 아닙니다. 실제 프린터, 접근성 장치, 합성 지원 형식 사례를 벗어나는 암호 문서, 복잡한 업무 서식, 모든 제3자 글꼴 권리와 Store 인증에는 추가 검증이 필요합니다. HWPX 지원은 고정된 직렬화기를 사용하며 지원하지 않는 원본 기능은 완벽하게 보존되지 않을 수 있습니다. 개발 빌드 평가 시 원본 파일을 유지하세요.

참고 자료: GitHub Actions 청구 문서와 Playwright 공식 WebView2 테스트 안내.
