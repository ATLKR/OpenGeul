# OpenGeul · 오픈글

HWP/HWPX 문서를 내 PC에서 열고 편집하는 무료 Windows 앱입니다.
[Microsoft Store에서 받기](https://apps.microsoft.com/detail/9PJH0T3PHRMF) ·
[웹사이트와 사용 안내](https://opengeul.allenlim.net) ·
[개발판과 검증 파일](https://github.com/ATLKR/OpenGeul/releases)

Store 공개판은 1.1.1입니다. 아래 설명은 개발 소스 기준이며 Store 공개판과
서명 없는 GitHub 개발판을 별도로 안내합니다.

## 지원 기능

HWP/HWPX 열기·편집·저장과 두 형식 사이의 다른 이름으로 저장을 지원합니다.
PDF 내보내기, Windows 인쇄, 끌어놓기, 여러 창, 최근 문서, 임시 파일을 통한
원자적 저장과 외부 변경 확인을 포함합니다. 표 배치와 마지막 줄 간격에 관한
업스트림 수정 및 합성 문서 회귀 검사, 일반 p/P 입력, 도구 모음 레이블 설정도
유지합니다.

인터페이스는 한국어입니다. 암호 원본의 일반 저장은 차단하고, 다른 이름으로
저장할 때 암호 없는 파일을 만들기 전에 확인합니다. 암호 원본을 보존하려면
다른 경로를 선택하세요. 자동 저장·복구와 LibreOffice/DOCX/XLSX/PPTX 연동은
제공하지 않습니다. 원본을 보관하고 중요한 저장·출력 결과를 확인하세요.

## 기반 소스와 라이선스

[HOP](https://github.com/golbin/hop)와 [rhwp](https://github.com/edwardkim/rhwp)를
기반으로 한 독립 배포입니다. OpenGeul 자체 코드는 **MIT**이며 업스트림과
의존성의 라이선스는 그대로 적용됩니다. 한컴, HOP, rhwp 및 The Document
Foundation과 제휴하거나 이들의 승인을 받은 제품은 아닙니다.

고정한 HOP 데스크톱 앱과 rhwp 편집기·엔진 전체를 소스에서 빌드합니다.
고급 변환·렌더링용 rhwp 명령줄 도구는 native-skia로 함께 빌드합니다.
소스 버전·커밋은 [upstream.lock.json](config/upstream.lock.json)에 기록하며,
준비 스크립트가 검토 가능한 확장 코드를 적용합니다. upstream/hop도 같은
커밋을 가리킵니다. 명령줄 기능·제한은 rhwp-help.txt 또는
Tools/rhwp.exe --help에서 확인하세요. 모든 문서의 완벽한 재현은 보장하지 않습니다.

## 개발판과 검증

[Actions](https://github.com/ATLKR/OpenGeul/actions)는 main 변경과 PR에서 정책
검사 및 Windows 빌드를 실행합니다. 모든 필수 검증을 통과한 허용된 main·버전
태그 빌드만 [개발판](https://github.com/ATLKR/OpenGeul/releases)을 게시합니다.
PR은 릴리스를 게시하지 않습니다. 수동 단계는 checks, engine, full이며
릴리스는 full 검증만 허용합니다. 무료 표준 러너와 파일 크기 제한·사용이 끝난
전송 파일 정리는 [무료 CI 안내](docs/FREE_CI.md)를 따릅니다.
서명 없는 GitHub 개발판 빌드에는 서명 비밀키·PAT·Store 계정이 필요하지 않습니다.

개발판에는 서명 없는 MSIX·포터블 ZIP, SHA-256 검증 목록, 소스·패키지 증거와
명령줄 도움말이 들어 있습니다. 서명 없는 MSIX는 신뢰된 일반 설치 파일이
아닙니다. 포터블 ZIP은 전체를 풀고 WebView2 런타임을 설치해야 합니다.
포터블 명령줄 도구에는 최신
[Microsoft Visual C++ v14 재배포 패키지(x64)](https://aka.ms/vc14/vc_redist.x64.exe)도
필요합니다. Windows와 조직의 보안 정책을 따라 사용하세요.

## 글꼴

글꼴 파일은 함께 배포하지 않습니다. 설치된 Windows 시스템·사용자 글꼴을
사용하며 **글꼴 도움말**에서 공식 Noto 페이지와 Windows 글꼴 설정을 엽니다.
앱은 글꼴을 몰래 설치하거나 다른 제품에서 추출하지 않습니다.
[글꼴 안내](docs/FONTS.md)를 확인하세요. 대체 글꼴은 줄바꿈·쪽 배치를 바꿀 수
있습니다. PDF 메타데이터 검사는 보호 장치이며 완전한 법적 심사는 아닙니다.

## Windows에서 빌드

PowerShell 7, Python 3.11 이상, Node 24/Corepack, Git, Rustup, Visual Studio C++
빌드 도구와 Windows SDK가 필요합니다. 깨끗한 작업 디렉터리를 사용하세요.
같은 OpenGeul 커밋에서 Linux의 scripts/build-wasm.sh가 만든 소스 검증 WASM을
Windows 빌드에 전달해야 합니다. Actions의 **OpenGeul Windows build and release**를
full로 실행하거나 해당 커밋의 검증된 WASM 디렉터리를 직접 지정하세요.

    ./scripts/build-msix.ps1 -WasmDirectory C:\path\to\verified-wasm

엔진·확장 코드 증거가 일치하지 않으면 빌드를 거절합니다. 준비 과정은 기존
.work/hop, .work/payload, dist를 덮어쓰지 않습니다. 작업을 보관한 뒤 다시
빌드하세요. 업스트림 계약 검사는 확장 적용 전에, 수정된 프런트엔드·네이티브
검사는 적용 후에 실행하며 핵심 문서 세션 소스의 변경도 기록합니다.

## 안내와 지원

[MIT 라이선스](LICENSE), [제3자 고지](THIRD_PARTY_NOTICES.md),
[라이선스 정책](docs/LICENSE_POLICY.md), [검증 기록](docs/VERIFICATION.md),
[설정 안내](docs/SETUP.md), [릴리스 체크리스트](docs/RELEASE_CHECKLIST.md)를
참고하세요. 향후 MPL 코드를 가져올 때도 해당 의무는 유지됩니다.

문의: [allenlim@allenlim.net](mailto:allenlim@allenlim.net).
버전과 오류 내용을 알려 주세요. 공개 문의에 개인 문서나 암호를 첨부하지 마세요.
