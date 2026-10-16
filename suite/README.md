# OpenGeul Office 개발판

OpenGeul Office는 한 제품군 안에서 서로 다른 문서 엔진을 사용하는 Windows Suite입니다.
이 디렉터리는 **0.1.0-dev 개발 소스**이며 기존 OpenGeul HWP Store 상품이나 정규
릴리스를 교체하지 않습니다. 실제 Windows 검증 결과는 Suite workflow의 동일 소스
실행과 원본 evidence를 확인해야 합니다.

| 구성 | 지원 경로 | 화면 |
| --- | --- | --- |
| OpenGeul HWP | HWP, HWPX | 검증된 OpenGeul 1.1.4 편집기 |
| OpenGeul Writer | DOCX, DOC, ODT, RTF, TXT | Suite 창 안의 native Office 프레임 |
| OpenGeul Calc | XLSX, XLS, ODS, CSV | 같은 공유 런타임의 native 프레임 |
| OpenGeul Impress | PPTX, PPT, ODP | 같은 공유 런타임의 native 프레임 |
| OpenGeul Draw | ODG | 같은 공유 런타임의 native 프레임 |
| OpenGeul Math | ODF 수식 | 같은 공유 런타임의 native 프레임 |
| OpenGeul Base | ODB | 같은 공유 런타임의 native 프레임 |

Writer/Calc/Impress/Draw는 Tabbed UI를 기본 설정합니다. Math/Base에는 같은 Notebookbar를
강제로 적용하지 않습니다. HWP와 DOCX 사이에 자동 변환을 끼워 넣지 않으며, 일반 저장은
원래 형식을 유지하고 다른 형식은 **다른 이름으로 저장**에서 선택합니다. 모든 형식의
완전한 왕복 보존을 보장하지 않습니다.

## 개발 패키지 사용

검증된 ZIP 전체를 새 폴더에 풀고 `OpenGeul.Office.exe`를 실행합니다. 시작 화면에서
모듈을 선택하거나 파일 열기를 사용합니다. Windows x64용이며 .NET 런타임을 포함합니다.
HWP 편집기는 Windows WebView2 런타임이 필요합니다. 사용자 LibreOffice 설치나 프로필,
파일 연결, Store 업데이트 설정은 변경하지 않습니다. 설치·등록·업데이트를 수행하는
정식 installer가 아닌 portable 개발 패키지입니다.

Office 문서 창은 Suite가 만든 Panel HWND 아래의 UNO 프레임에서 편집합니다. 창마다
전용 프로필·로컬 파이프·작업자를 쓰며 TCP UNO 서버는 열지 않습니다. 저장하지 않은
문서를 닫을 때 저장·저장하지 않음·취소를 선택할 수 있습니다. 저장 실패나 취소는
문서 창을 유지합니다. 갑작스러운 shell/운영체제 실패 후의 복구와 자동 저장은 별도
개발 과제입니다. 개발판에서는 원본을 보관하고 중요한 저장 결과를 확인하세요.

Base는 데이터베이스 URL·현재 연결·등록된 드라이버와 Java 사용/실행 상태를 확인해 표시합니다.
새 Base 문서는 내장 Firebird를 사용하고, 처음 저장할 때 실제 보관할 파일 경로를 선택합니다.
확인을 위해 새 연결을 만들거나 Java VM을 시작하지 않습니다. JDBC/구형 HSQLDB 등에 필요한
외부 Java·드라이버·서버는 함께 제공하지 않으며 단순히 창을 열었다는 이유로 연결
준비가 완료됐다고 표시하지 않습니다. 원격 데이터베이스에 자동으로 연결하지 않습니다.

## Windows에서 빌드

PowerShell 7, Python 3.12 이상, .NET 8 SDK, Git과 인터넷 연결이 필요합니다.
Suite는 .NET Windows Desktop 8.0.32와 고정한 Office 26.8.1.1 x64 입력을 사용합니다.
공식 배포의 SHA256과 HWP 원본 개발 패키지의 SHA256은 `config/runtime.lock.json`에
고정되어 있습니다. 새 작업 폴더와 새 출력 경로를 사용해야 합니다.

```powershell
python -m unittest discover -s suite/tests -v
dotnet run --project suite/shell-tests/OpenGeul.Office.Tests.csproj -c Release
./suite/scripts/build-suite.ps1
```

빌드 스크립트는 MSI를 관리자 설치 이미지로 **추출**하며 사용자 PC에 LibreOffice를
설치하지 않습니다. MSI의 원래 cabinet에서 정확한 AMD64 File ID를 찾아 VC++ 구성 요소를 app-local로
준비합니다. 서로 다른 아키텍처나 기존 출력과 충돌하면 거부합니다. Office 런타임은
공유하므로 모듈마다 전체 엔진을 중복 배포하지 않습니다.

출력 ZIP에는 제품 설정, 모든 파일의 inventory, 런타임 입력·브랜딩 증거, 정확한
소스 커밋의 ZIP과 제3자 고지가 들어갑니다. 다음 명령은 패키지 전체를 다시 검사합니다.

```powershell
python suite/scripts/verify-suite.py dist/OpenGeul-Office-0.1.0-dev-windows-x64
```

## 검증을 읽는 방법

`.github/workflows/office-suite.yml`은 Suite 전용이며 기존 HWP 릴리스 gate를 완화하지
않습니다. 단위 검사·C# 교차 빌드와 실제 Windows GUI 검사는 서로 다른 증거입니다.
`e2e/engine_smoke.py`는 실제 엔진의 생성·저장·재열기를 검사하고,
`e2e/windows_smoke.py`는 실제 native 자식 창·키보드 입력·저장을 검사합니다.
영문 키 입력이나 Unicode SendInput 통과를 한국어 IME 조합 전체 통과로 해석하지 않습니다.
ARM64, 전체 WACK/Store, 실제 프린터와 모든 문서의 호환성도 별도 검증 대상입니다.

공식 런타임에 포함된 32비트 TWAIN 스캐너 도구와 SharePoint COM 구성 요소는 이
portable 개발판에서 지원하지 않습니다. TWAIN 도구에는 별도 32비트 DLL 격리가 필요하고,
SharePoint 구성 요소에는 별도 등록과 의존성이 필요합니다. 이 파일들을 원본 그대로
보존했다는 사실을 해당 기능의 지원·검증으로 해석하지 않습니다.

## 이름과 라이선스

사용자 제품 이름·모듈 표시·시작 화면·스플래시·기본 프로필은 OpenGeul로 바꿉니다.
내부 UNO·필터 식별자와 법적 고지는 유지합니다. 이 개발 패키지는 고정한 upstream
바이너리를 사용하며 PE의 원저작자/버전/서명 메타데이터를 다시 쓰지 않습니다.
원본 서명을 OpenGeul 서명이라고 설명하지 않습니다. 모든 Windows 실행 파일의 native
아이콘·버전 리소스까지 바꾸는 재빌드 설정은 `branding/`에 있습니다.

OpenGeul 추가 코드는 MIT이고 Office 엔진·.NET·HWP 구성 요소에는 각각의 라이선스가
적용됩니다. 패키지 `Notices/CORRESPONDING_SOURCE.md`와 원래 LICENSE/NOTICE를 참고하세요.
The Document Foundation·한컴과 제휴하거나 승인을 받은 제품은 아닙니다.
