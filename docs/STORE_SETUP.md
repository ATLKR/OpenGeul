# Microsoft Store 패키징과 API 제출

공식 상품은 **OpenGeul**, Store ID는 **9PJH0T3PHRMF**입니다.
[공식 Store 페이지](https://apps.microsoft.com/detail/9PJH0T3PHRMF).
2026-10-11 읽기 전용 실행 38177123896에서 사용자 직접 공개 후 초기 제출
1152921505702042424의 Published/Manual·1.1.1.0과 대기 제출 없음이 확인됐습니다.
이 관측은 다음 패키지의 생성·업로드·인증 성공을 뜻하지 않습니다.

## 검증된 원본에서 패키징

main의 store-package.yml을 GitHub API로 실행합니다.

    gh workflow run store-package.yml --ref main -f release_tag=<tag>

모든 소스 릴리스 게이트를 통과한 기존 태그를 선택하세요. Store 재패키징에서
런타임 수정을 끼워 넣지 않습니다. 기본 동작은 파일 생성만이며 실제 제출은
기본적으로 비활성화돼 있습니다.

opengeul-store-<run ID> 파일을 하루 안에 내려받아 검증된 Store MSIX 원본을
보관하세요. 파일 생성은 Store 제출 교체가 아닙니다. 무료 가격·기존 시장
가용성·연령 등급을 유지하고 소개·화면·선언을 검토합니다. Store는 인증과
공개를 거쳐 배포 서명을 제공합니다.

패키지의 지원 인터페이스 언어는 한국어입니다. 소개·기능·변경 내용도 한국어를
우선합니다. 각 소개의 첫 문장에 Microsoft Edge WebView2 런타임 필요를
명시하고, 암호 원본 일반 저장 차단·평문 저장 전 확인·자동 저장/복구 미지원과
원본을 보존할 별도 경로를 설명하세요.
지원 [allenlim@allenlim.net](mailto:allenlim@allenlim.net),
[웹사이트](https://opengeul.allenlim.net),
[개인정보 처리방침](https://opengeul.allenlim.net/privacy.html)을
지원되는 소개 본문에 포함하세요. 제출 API가 무시하는 privacyPolicy,
supportContact, websiteUrl 필드로 전용 Partner Center 설정이 바뀐다고
주장하지 않습니다. 문서화되지 않은 defaultLanguage 필드를 만들어 넣지 않습니다.

2026-10-12 사용자 요청의 고객용 연락처는 `allenlim@allenlim.net`, 홈페이지는
`https://opengeul.allenlim.net`입니다. 그날 공개 카탈로그의 홈페이지는 GitHub
저장소, 지원 URI는 GitHub Issues였으며 해당 전용 속성을 API로 갱신했다고
기록하지 않습니다. 최신 공식 제출 API 문서도 두 필드를 폐기된 값으로 명시하며
값을 보내도 무시하고 Partner Center의 Properties에서 변경하도록 안내합니다.
소개 본문과 앱 제품 정보에 연락처를 표시하는 수정은 전용 Store 버튼 수정과
별개로 검증합니다.

새 소스 실행의 msix-install 증거를 확인하세요. installed-launch.json의
후보 패키지 식별자와 설치 디렉터리에서 실행한 CLI 도움말이 일치해야 합니다.
wack.json·wack.xml도 확인합니다. 도구 없음은 미검증, 필수 실패·부분 보고서·
식별자 불일치는 차단 조건입니다. WACK 통과는 Partner Center 인증이 아닙니다.

워크플로는 원본 해시, MSIX/포터블 전체 파일 일치, 태그·소스·실행과 필수 게이트를
검증합니다. 실제 Partner Center 식별자로 매니페스트를 바꾸고 MakeAppx로
재패키징한 뒤 모든 실행 파일·DLL·리소스·고지를 원본과 대조합니다.
원본 소스 증거, Store 재패키징 증거, SHA-256 목록을 포함하며 재컴파일하거나
Store 인증을 하지 않습니다. 같은 실제 네이티브 실행 파일로 합성 문서를
표시한 OpenGeul-editor.png와 screenshot-provenance.json도 보관합니다.

파일만 만드는 패키징에는 서명 비밀키·Store API 키가 필요하지 않습니다.
개발 태그는 검토할 패키지를 만들 수 있지만 자동 제출 경로에 사용할 수 없습니다.
최초 미공개 제출은 지원되는 취소·복구 경로 없이 삭제하지 않습니다. 공개판이
없는 상태에서 기준 제출을 만들려고 오래된 버전을 자동 공개하지 않습니다.
고정한 Name·Publisher CN과 표시 이름 **Allen Taewon Lim**을 유지합니다.

## 안정 버전의 API 제출

config/product.json과 일치하는 정식 vX.Y.Z 태그의 push 빌드가 전체 게이트를
통과해야 합니다. 릴리스 작업은 GitHub 원본을 보존·생성하고 main의 Store
워크플로를 명시적으로 실행합니다. GITHUB_TOKEN이 만든 릴리스·태그 이벤트는
일반적으로 다른 Actions를 시작하지 않으므로 이 dispatch가 필요합니다.
하위 작업은 소스 완료를 최대 10분 기다리고 소스·실행·해시·런타임을 다시
검증합니다. main·개발 태그는 자동 Store 인증을 요청하지 않습니다.
submit_to_store 수동 입력도 검증된 정식 태그 push를 요구하며 기본값은 false입니다.

제출기는 실제 Published 기준 제출을 확인한 뒤에만 새 제출을 생성합니다.
원본 소개·연령 등급·무료 가격·시장 설정을 보존하고 승인한 한국어 소개 변경은
검토된 텍스트 필드에만 적용합니다. NotAvailable은 이용 불가 시장으로 유지하며
Free·Base로 바꾸지 않습니다. 유료·알 수 없는 가격은 제출을 차단합니다.
사용자의 2026-10-12 지시에 따라 새 제출은 `targetPublishMode=Immediate`로
설정해 인증 통과 후 자동 공개합니다. 기존 Published 기준 제출은 `Manual`과
`Immediate`를 읽을 수 있지만, 새 요청의 PUT 응답·커밋 직전 GET·같은 SID의
처리 결과에서는 `Immediate`를 확인합니다. 알 수 없는 공개 방식이나 예약 공개는
차단합니다. 이미 인증·공개 처리 중인 수동 요청을 다시 커밋하거나 삭제하지 않습니다.

Entra 앱에는 Partner Center Manager 접근이 필요합니다.
STORE_CLIENT_SECRET은 GitHub Actions secrets에 보관하고 Proton Pass에
백업합니다. 저장소 변수 STORE_APP_ID=9PJH0T3PHRMF, STORE_TENANT_ID,
STORE_CLIENT_ID를 사용합니다. 인증 정보는 검증 파일과 실제 화면을 먼저
보관한 다음 제출 단계에만 전달합니다. 선택 verify_store_api는 OAuth와
고정 앱 GET만 수행합니다. 토큰·비밀키·서명된 업로드 URL을 로그·파일·Issue에
넣지 않습니다.

같은 앱의 제출은 하나의 동시 실행 그룹에서 처리하며 진행 중인 거래를
취소하지 않습니다. 버전은 숫자로 비교하고 직전 상태를 다시 읽습니다.
같은 요청이 처리 중이면 재사용합니다. 다른 대기 제출을 교체할 때는 정확한
ID와 시도 기록을 남기고, 빈 본문의 성공 DELETE·대기 제출 없음·삭제 ID의
404를 확인합니다. 거절·404·시간 초과·불명확한 응답·다른 제출 등장 시
중단하고 새 제출을 만들지 않습니다. 공개 기준 제출은 삭제하지 않습니다.

메타데이터 응답과 커밋 직전 조회가 의도한 패키지 이름·업로드/삭제 상태·최소
요구 사항·소개·가격·인증 후 자동 공개 방식과 일치해야 합니다.
단일 신뢰된 GitHub Actions 봇 Issue에 변경 시도·확정을 기록합니다.
결과 불명 삭제·생성은 다음 후보도 차단합니다. 커밋 응답이 끊기면 같은 ID를
GET으로 확인하고 커밋을 반복하지 않습니다. 실패는 Issue·Actions 오류로
남기되 GitHub 릴리스와 검증 파일을 보존합니다. 알 수 없는 결과를 확인하기
전에 거래 기록을 지우지 마세요.

검증한 MSIX의 ZIP을 업로드하고 인증 처리를 요청합니다. 접수 성공과 Microsoft의
인증·공개 완료는 구분하며 이번 제출은 인증 후 자동 공개합니다. 공개 배지는
실제 `Published` 상태를 확인한 뒤에만 갱신합니다. API로 만든 제출은 계속
API로 편집해야 합니다. Partner Center에서 수정하면 후속 API 변경·커밋이
막힐 수 있습니다. Microsoft CLI의 publish --noCommit도 기존 초안을 먼저
삭제할 수 있으므로 단순한 사전 초안 확인만으로 동시 변경을 보호하지 못합니다.

근거:
[제출 생성·업로드](https://learn.microsoft.com/en-us/windows/uwp/monetize/manage-app-submissions),
[삭제 계약](https://learn.microsoft.com/en-us/windows/uwp/monetize/delete-an-app-submission),
[최초 공개](https://learn.microsoft.com/en-us/windows/apps/publish/msstore-dev-cli/overview),
[워크플로 실행](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow),
[Store 제출 조건](https://learn.microsoft.com/en-us/windows/uwp/monetize/create-and-manage-submissions-using-windows-store-services),
[Microsoft CLI 초안 동작](https://github.com/microsoft/msstore-cli/blob/v0.4.3/MSStore.CLI/Helpers/IStorePackagedAPIExtensions.cs).
