# WACK 패키지 입력 검증

설치 MSIX의 기본 동작 검사는 서명 후보의 패키지 식별자, 보이는 GUI, CLI와 등록된 HWP/HWPX 파일 형식을 확인합니다. 테스트 설치를 제거한 뒤 일반 Windows SDK App Certification Kit가 문서화된 `appcert test -appxpackagepath` 명령으로 동일한 서명 바이트를 분석합니다. 인증과 정리가 끝날 때까지 테스트 인증서를 신뢰 상태로 유지합니다. 서명 확인 뒤, WACK 직전과 직후에 서명 사본의 해시를 검사하며 서명되지 않은 릴리스 산출물도 변경 여부를 확인합니다.

Microsoft는 두 명령 모드를 [Windows App Certification Kit](https://learn.microsoft.com/en-us/windows/uwp/debug-test-perf/windows-app-certification-kit)에 설명합니다. 이 변경은 SDK 입력 모드만 바꾸며 후보 매니페스트, WindowsApps 권한, SDK 바이너리, 테스트 선택과 보고서 판정기는 바꾸지 않습니다. 설치 동작은 계속 별도로 검증합니다. WACK은 패키지 식별자의 디버깅 토큰 대신 일반 실행기 프로세스 문맥에서 실행합니다.

## 통제된 비교

진단 실행 [38141248234](https://github.com/ATLKR/OpenGeul/actions/runs/38141248234)은 소스 후보 `e9cf4310cfc67438db4b4e7a12d6fabd6de1bc19`에서 이전에 테스트한 진단 사본을 사용했으며 매니페스트를 추가 수정하지 않았습니다. 서명 입력 MSIX SHA-256은 `568092a6fe1bf6561565d0f25424a1babac809b988cebfa72ee903d67b7c595c`였고 실행 파일 SHA-256은 `e282955c8e460cb66270949e51e492162bce7cebb75ae62562043c05885f8490`로 유지됐습니다.

두 완전한 Centennial 보고서에는 같은 테스트 24개, 필수 13개와 선택 11개가 있었습니다. 전체 이름 모드는 필수 12개를 통과했으나 필수 DPI 경고가 있었습니다. 패키지 입력 모드는 DPI를 포함한 필수 13개를 모두 통과했습니다. 두 모드 모두 선택 항목의 차단 실행 파일 실패와 메시지 14개를 유지했습니다. 패키지 입력 보고서는 예상 개발 식별자와 `1.1.2.0`에 일치하고 `PARTIAL_RUN=FALSE`를 보고했으며 종료 코드 0으로 끝났습니다. 보고서 SHA-256은 `a04d58fbf1a60b27087dc4450142ebcc367e4120841fe7b7530930096faa5d71`입니다.

전체 이름 모드는 등록된 WindowsApps 실행 파일을, 패키지 입력 모드는 SDK의 임시 해제본을 분석했습니다. 이전의 동일 바이트 대조 검사에서는 네이티브 `CreateActCtxW`가 설치된 WindowsApps 경로에서만 접근 거부를 반환했고, 패키지 내용물과 길이가 같은 소유 사본 경로에서는 성공했습니다. SDK 내부의 정확한 접근 검사는 확인하지 못했습니다. 별도 패키지 식별자 디버깅 대조 검사는 환경 검증에서 실패했으므로 비교 근거로 사용하지 않습니다.

변경하지 않은 보고서 판정기는 이 보고서에 `submissionCheckPassed=true`, `passed=false`를 반환합니다. 필수 경고·실패, 부분 보고서와 식별자·버전 불일치는 계속 검증을 막습니다. 선택 항목의 문제는 표시된 상태로 유지합니다. 이 결과는 완전한 WACK PASS나 Microsoft Store 승인이 아닙니다.

이 진단 보고서는 업데이트한 HOP/rhwp 소스를 검증한 결과가 아닙니다. 각 최종 후보는 릴리스 전에 자체의 전체 Windows 빌드, 설치 기본 동작, 일반 패키지 입력 WACK, 편집기·가상 프린터 검증을 모두 수행해야 합니다.
