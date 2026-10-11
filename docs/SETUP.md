# CI/CD 초기 구성 기록

이 문서는 초기 구성 당시의 정책을 보존한 기록입니다. 최신 단계·보존 정책은 FREE_CI.md, 최신 Store 절차는 STORE_SETUP.md를 확인하세요.

기준 저장소는 ATLKR/OpenGeul입니다. 당시 표준 호스팅 Windows/Linux 실행기만 사용하고 유료 대형 실행기를 사용하지 않았습니다. 공개 저장소의 표준 실행은 GitHub 정책상 무료지만 실행·동시 실행·저장 공간 제한은 적용됩니다. 당시 산출물은 3일 후 만료됐고 사전 릴리스 자산은 삭제할 때까지 유지됐습니다.

서명 비밀정보는 필요하지 않았습니다. Settings → Actions에서 고정한 GitHub 액션을 허용해야 했습니다. 기본 토큰 권한은 읽기 전용으로 유지할 수 있고 릴리스 작업만 contents:write를 요청했습니다. 풀 리퀘스트에 게시 토큰이나 Store 비밀정보를 주지 않았습니다. 초기 가동 후 main·버전 태그 보호를 설정하는 계획이었습니다.

당시 main 푸시는 테스트, 전체 Windows 편집기·CLI 컴파일, MSIX 생성·해제·검사, 산출물 업로드를 수행하고 빌드 성공 후 서명되지 않은 사전 릴리스를 게시하도록 구성했습니다. 풀 리퀘스트는 테스트·빌드만 했습니다. 수동 main 실행도 지원했습니다. 버전 태그는 config/product.json과 일치해야 했습니다. 서명, 새 기기 UX, 문서 충실도와 의존성 라이선스 검토를 마칠 때까지 모든 릴리스를 개발 사전 릴리스로 취급했습니다. 이 초기 설명이 새 후보의 필수 검증을 대신하지 않습니다.

당시 Store 후속 계획은 이름을 예약하고 정확한 Partner Center 식별 필드를 사용해 `-Store -IdentityFile <local JSON>`로 빌드한 뒤 첫 제출과 신고 사항을 수동 완료하는 것이었습니다. Store 자동화는 보류 상태였습니다. PFX/client 비밀정보를 이 저장소에 넣지 않는 원칙은 유지합니다. Store 서명과 GitHub 호스팅의 서명되지 않은 릴리스는 별개입니다. 현재 Published 상태나 후속 자동화는 이 초기 기록이 아닌 최신 Store 문서의 근거를 따릅니다.

참고 자료:
https://docs.github.com/en/billing/concepts/product-billing/github-actions
https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/msix/app-package-requirements
https://learn.microsoft.com/en-us/windows/msix/package/sign-msix-package-guide
