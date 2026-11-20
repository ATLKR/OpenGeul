# OpenGeul Office Suite 설계

## 승인된 목적

사용자는 OpenGeul을 Office Suite로 확장하고 LibreOffice Writer 등의 사용자 표시 이름을
OpenGeul로 대체하도록 요청했다. 이전 대화에서 HWP/HWPX와 Office 문서는 서로 다른
엔진을 쓰되 OpenGeul 창 안에서 직접 편집하는 방향을 선택했다. 이 문서는 해당 요청의
구현 기준이다. 기존 HWP 제품의 릴리스·Store 배포는 이번 변경의 대상이 아니다.

## 제품과 창

- 제품군: **OpenGeul Office**.
- 구성: **OpenGeul HWP**, **OpenGeul Writer**, **OpenGeul Calc**, **OpenGeul Impress**,
  **OpenGeul Draw**, **OpenGeul Math**, **OpenGeul Base**.
- 하나의 Suite 시작 창에서 새 문서와 파일 열기를 제공한다. Office 문서는 OpenGeul이
  소유하는 Windows 문서 창의 네이티브 패널 안에서 편집한다. 외부 stock LibreOffice를
  실행한 것을 내장 편집 완료로 취급하지 않는다.
- Writer/Calc/Impress/Draw는 런타임이 지원하는 Tabbed UI를 기본으로 한다.
  Math/Base는 고유 편집 UI를 유지한다. Windows x64를 첫 검증 대상으로 삼는다.

## 엔진·프로세스 경계

HWP/HWPX는 기존 검증된 OpenGeul 구성 요소를 그대로 사용한다. Office 문서는 하나의
공유 GUI 런타임을 사용하며 파일 형식을 자동으로 HWP 또는 ODT로 바꾸지 않는다.
Suite는 별도 native Windows shell을 갖는다. .NET WinForms는 실제 HWND를 제공하고,
런타임에 포함된 Python/pyuno 작업자가 UNO SystemChildFactory로 패널 HWND 아래에
문서 프레임을 생성한다. 이는 기존 HWP Tauri 코드와 검증 계약을 변경하지 않고도
Suite 소유 창에서 실제 편집을 제공한다. HWP 구성 요소는 자체 OpenGeul 편집 창을 쓴다.

각 Office 문서 창은 독립 작업자·임시 프로필·무작위 로컬 named pipe를 사용한다.
네트워크 UNO 리스너나 사용자 LibreOffice 프로필을 사용하지 않는다. 작업자 통신은
UTF-8 JSON Lines, 요청 id와 success/error 응답을 사용한다. 문서 경로는 로컬 파일만
허용하고 매크로와 외부 링크의 자동 실행을 비활성화한다. 입력·포커스·리사이즈는
네이티브 편집기가 담당한다. 종료는 modified 확인 후 저장/버리기/취소를 제공하며
취소하거나 저장이 실패하면 문서 창과 작업자를 유지한다.

## 브랜딩·공급망

표시 이름·제품 설정·기본 프로필·시작 화면·스플래시를 OpenGeul로 변경한다.
UNO 서비스·필터 ID·파일 형식 내부 식별자는 유지한다. LibreOffice라는 이름이 남는
라이선스·저작권·대응 소스 고지는 유지한다. 바이너리 서명이나 PE 메타데이터를 임의로
고쳐 원래 서명을 유효하다고 주장하지 않는다. 장기 소스 빌드용 product/vendor/branding
설정도 함께 제공한다.

런타임은 고정 버전·SHA256으로 확인한 공식 배포를 새 출력 디렉터리에 추출하고,
검토한 설정 파일만 변경한다. 원본 배포, 원래 라이선스, 대응 소스 위치와 수정 파일
해시를 기록한다. 사용자 런타임·설치·프로필은 수정하지 않는다. 개인 문서나 비밀키를
검증 자료에 넣지 않는다. Suite payload와 provenance는 기존 HWP와 별도로 관리한다.

## 파일과 오류 처리

Suite 시작 화면은 확장자를 모듈에 명시적으로 라우팅한다. 지원하지 않는 파일은
다른 엔진으로 추측해 열지 않는다. 열기 실패는 한국어로 표시하고 기존 파일을
변경하지 않는다. 저장은 현재 형식을 유지하고 다른 형식은 명시적인 Save As로만
선택한다. 저장 필터 allowlist를 사용하고 덮어쓰기는 UI에서 확인한다.
Base의 데이터베이스 연결과 Java 등 추가 의존성은 준비 상태를 실제 확인해 안내한다.

## 완료·검증 기준

1. 브랜딩·형식 라우팅·작업자 요청/오류/저장·종료 보호의 의미 있는 회귀 검사를 통과한다.
2. Windows shell이 실제 빌드된다. Office frame이 Suite 패널의 자식임을 실제 관측한다.
3. Writer DOCX, Calc XLSX, Impress PPTX의 생성→입력→저장→재열기와 저장 파일의
   내용을 확인한다. 엔진 수준 검사와 실제 GUI 입력 검사는 별도로 기록한다.
4. 모듈 표시 이름과 제품 설정을 확인하고, 대응 소스·라이선스·파일 inventory가
   포함된 Suite 패키지를 검증한다. 기존 HWP 정책/회귀 검사도 유지한다.
5. 로컬 환경의 headless alpha 런타임 결과를 stable Windows GUI·IME·ARM64 검증으로
   바꾸어 주장하지 않는다. 통과하지 않은 항목은 배포 완료로 표시하지 않는다.

## 배포와 복구

개발은 `work/opengeul-office-suite` 브랜치와 별도 Suite 빌드 경로에서 수행한다.
기존 HWP main·정규 태그·Store 상품·파일 연결·업데이트를 자동 교체하지 않는다.
초기 결과는 검토 가능한 개발 패키지/PR로 제공하고, 정식 게시에는 실제 Windows
편집·저장·닫기·설치/제거와 배포 고지 검증을 요구한다. 개발 패키지를 제거하면 기존
OpenGeul과 LibreOffice 설치는 그대로 남는다.
