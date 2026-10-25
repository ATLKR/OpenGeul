# OpenGeul Office 개발판

OpenGeul Office는 한 제품군 안에서 서로 다른 문서 엔진을 사용하는 Windows Suite입니다.
이 디렉터리는 **0.2.0-dev 개발 소스**이며 기존 OpenGeul HWP Store 상품이나 정규
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

기본 Tabbed 화면에서는 문서를 열기 전에 모듈의 기존 도구 모음에서 중복된
`.uno:StyleApply` 콤보 컨트롤만 전용 프로필의 메모리 설정에서 제외합니다.
탭·메뉴·키보드의 스타일 명령은 유지하며 설치 파일이나 사용자 설정에 저장하지 않습니다.
이 처리는 기본 Tabbed 화면을 대상으로 하며 다른 Notebookbar 배치나 문서에 포함된
사용자 도구 모음 전체에 대한 보장은 아닙니다.

## 개발 패키지 사용

검증된 ZIP 전체를 새 폴더에 풀고 `OpenGeul.Office.exe`를 실행합니다. 시작 화면에서
모듈을 선택하거나 파일 열기를 사용합니다. 아키텍처별 패키지에 .NET 런타임을 포함합니다.
직전 0.1.1-dev x64 검증과 현재 소스의 실제 Windows 검증 결과는 구분해서 확인하세요.
HWP 편집기는 Windows WebView2 런타임이 필요합니다. 사용자 LibreOffice 설치나 프로필,
파일 연결, Store 업데이트 설정은 변경하지 않습니다. 설치·등록·업데이트를 수행하는
정식 installer가 아닌 portable 개발 패키지입니다.

Office 문서 창은 Suite가 만든 Panel HWND 아래의 UNO 프레임에서 편집합니다. 창마다
전용 프로필·로컬 파이프·작업자를 쓰며 TCP UNO 서버는 열지 않습니다. 저장하지 않은
문서를 닫을 때 저장·저장하지 않음·취소를 선택할 수 있습니다. 저장 실패나 취소는
문서 창을 유지합니다. Calc의 저장/Ctrl+S는 현재 셀의 일반 동기 입력을 처리하는
native 저장 경로를 사용합니다. Calc는 Ctrl+W 등으로 닫을 때 입력을 처리한 뒤
변경 표시와 관계없이 항상 저장·저장하지 않음·취소를 묻습니다. 저장은 저장 후 닫고,
저장하지 않음은 파일을 덮어쓰지 않고 닫으며, 취소는 같은 문서 창을 유지합니다.
Enter를 먼저 누르지 않은 A1 일반 영문 입력은 실제 x64 Windows에서 Ctrl+S와
Ctrl+W 뒤 세 선택을 각각 실행해 저장 파일과 독립 재열기로 검증했습니다.
이 검증은 비동기 유효성 검사·수식 수정 대화상자·모든 IME 조합의 입력 완료를
보장하지 않습니다. 갑작스러운 shell/운영체제 실패 후의 복구와 자동 저장은 별도
개발 과제입니다. 개발판에서는 원본을 보관하고 중요한 저장 결과를 확인하세요.

Base는 데이터베이스 URL·현재 연결·등록된 드라이버와 Java 사용/실행 상태를 확인해 표시합니다.
새 Base 문서는 내장 Firebird를 사용하고, 처음 저장할 때 실제 보관할 파일 경로를 선택합니다.
확인을 위해 새 연결을 만들거나 Java VM을 시작하지 않습니다. JDBC/구형 HSQLDB 등에 필요한
외부 Java·드라이버·서버는 함께 제공하지 않으며 단순히 창을 열었다는 이유로 연결
준비가 완료됐다고 표시하지 않습니다. 원격 데이터베이스에 자동으로 연결하지 않습니다.

## Windows에서 빌드

PowerShell 7, Python 3.12 이상, .NET 8 SDK, Git과 인터넷 연결이 필요합니다.
Suite는 .NET Windows Desktop 8.0.32와 고정한 Office 26.8.1.1 x64 입력을 사용합니다.
공식 배포의 SHA256과 HWP 원본 개발 패키지의 SHA256은 아키텍처별
`config/runtime.lock.json`과 `config/runtime.arm64.lock.json`에 고정되어 있습니다. 새 작업 폴더와 새 출력 경로를 사용해야 합니다.

```powershell
python -m unittest discover -s suite/tests -v
dotnet run --project suite/shell-tests/OpenGeul.Office.Tests.csproj -c Release
./suite/scripts/build-suite.ps1 -Architecture x64
```

기본 x64 빌드는 MSI를 관리자 설치 이미지로 **추출**하며 사용자 PC에 LibreOffice를
설치하지 않습니다. MSI의 원래 cabinet에서 선택한 아키텍처의 정확한 File ID를 찾아 VC++ 구성 요소를 app-local로
준비합니다. 서로 다른 아키텍처나 기존 출력과 충돌하면 거부합니다. Office 런타임은
공유하므로 모듈마다 전체 엔진을 중복 배포하지 않습니다.
ARM64 소스 빌드 ZIP의 인증 다운로드·입력 경로와 빌드 기한·실패 증거는
[엔진 빌드 안내](engine-build/README.md#build-deadlines-and-authenticated-ingestion)를 참고하세요.

출력 ZIP에는 제품 설정, 모든 파일의 inventory, 런타임 입력·브랜딩 증거, 정확한
소스 커밋의 ZIP과 제3자 고지가 들어갑니다. 다음은 현재 0.2.0-dev 개발판 경로의
예시이며, 실제로 검증할 압축 해제 폴더를 지정하면 패키지 전체를 다시 검사합니다.

```powershell
python suite/scripts/verify-suite.py dist/OpenGeul-Office-0.2.0-dev-windows-x64
```

## 검증을 읽는 방법

`.github/workflows/office-suite.yml`은 Suite 전용이며 기존 HWP 릴리스 gate를 완화하지
않습니다. 단위 검사·C# 교차 빌드와 실제 Windows GUI 검사는 서로 다른 증거입니다.
`e2e/engine_smoke.py`는 실제 엔진의 생성·저장·재열기를 검사하고,
`e2e/windows_smoke.py`는 실제 native 자식 창·키보드 입력·저장을 검사합니다.
일반 GUI·수명 검사에서 영문 편집 표식은 US 키보드의 스캔 코드로 입력하며,
대소문자·입력 버퍼·삽입 개수·포커스·키보드 배열을 기록합니다. 별도 Unicode
`VK_PACKET` 주입 진단에서는 저장 전 문자 누락이 재현됐습니다. 그 자동화 경로의
문제가 해결됐다는 주장은 하지 않으며 원본 진단과 실패 기록을 보존합니다.
이후 고정한 20회 물리 스캔 코드 진단에서도 관찰 없는 대조군 10·12번에서 각각
첫 표식의 L과 두 번째 표식의 C가 누락됐습니다. 저장된 XML과 독립 UNO 읽기 모두
누락을 확인했으며 원인은 확정되지 않았습니다. 수명 검사에는 소유한 Writer 프레임의
전체 본문을 독립 기준 본문과 누적 표식에 정확히 대조하는 읽기 전용 완료 절차를
추가했습니다. 입력 전부터 관찰기 정상 종료까지 하나의 12초 기한을 적용하고,
관찰기·엔진의 원래 프로세스 세대와 핸들을 확인한 뒤 기존 저장·닫기 검사를 계속합니다.
이는 검사기의 동기화·판정 보완이며 과거 물리 입력 누락의 원인 규명이나 해결 증거가 아닙니다.
이 영문 키 입력 검사를 한국어 IME 조합 전체 통과로 해석하지 않습니다.
Calc GUI 입력도 독립 XLSX 기준의 A1 전체 문자열·숫자·수식·계산 결과를 읽기 전용으로
대조합니다. 원래 Enter 입력 뒤 모델 반영과 관찰기 정상 종료를 같은 12초 기한 안에
확인한 다음 원래 저장 검사를 진행합니다. 선택 셀이나 편집 버퍼를 읽지 않고 고정한
첫 시트의 A1/B1/C1/D1만 읽습니다. 이 절차가 과거 Calc 저장 확인 실패의 원인 규명이나
제품 수정 증거를 뜻하지는 않습니다. 진단을 켠 실행에서는 저장 명령 수신·UI 처리·
작업자 요청·응답의 제한된 기록을 보존하며 문서 내용은 진단 기록에 넣지 않습니다.
한국어 UI를 기본 선택하며 네 모듈의 원본 번역에서 빠진 탭 표시 66개를 한국어로 제공합니다.
`e2e/korean_ui_smoke.py`는 실제 Office 창의 VCL 접근성 객체와 화면에서 한국어 탭을 확인합니다.
검사기는 정확히 소유한 엔진의 실행 파일·생성 시각·HWND를 전후 검증하고,
그 프로세스의 비공개 파이프로 실제 탭 역할·부모 객체·자식 인덱스·표시 영역을 읽습니다.
Windows UIA/MSAA 기록은 별도 진단이며 OS 화면 읽기 프로그램 지원 인증을 뜻하지 않습니다.
`e2e/korean_ime_smoke.py`는 실제 Microsoft IME의 조합 메시지·백스페이스·저장·UNO 재열기를
확인합니다. IME 활성화 전 영문 준비 표식도 같은 물리 스캔 코드 검사기로 입력하고,
원래 0.04초 간격·전체 입력 버퍼·삽입 개수·소유 포커스·US 배열·중립 보조 키를 확인합니다.
이는 준비 입력의 증거 보완이며 이전 Impress 영문 표식 첫 글자 누락의 원인 규명이나 제품 수정 주장이 아닙니다.
`e2e/lifecycle_smoke.py`는 저장·취소·실패·창 복원·HWP 실행의 7개 시나리오,
`e2e/startup_smoke.py`는 독립된 문서 초기화와 프로세스 종료 40회를 검사합니다.
`e2e/writer_style_smoke.py`는 실제 Ctrl+1 입력·Suite 저장·독립 UNO 재열기로
제목 1 스타일과 본문 보존을 검사합니다. 모든 전용 프로필의 진단 기록은 완전한 보존과
파일 해시를 확인하고, 네이티브 크래시 덤프가 있으면 전달을 막습니다.
워크플로는 새 문서 집합으로 전체 13개 GUI 검사와 6개 문서의 의미 재검증을 두 번 실행합니다.
실패 기록은 보존하며 하나라도 실패하면 배포 ZIP 업로드를 수행하지 않습니다.
ARM64 엔진의 완전한 제품 검증, 전체 WACK/Store, 실제 프린터와 모든 문서의 호환성은
각각 실제 실행 증거로 판단합니다. 공식 ARM64 Office 입력에는 내장 Firebird가 빠져 있어
그 입력만으로 전체 Base 지원이나 ARM64 Suite 배포 준비 완료를 주장하지 않습니다.
완전 네이티브 Base를 위한 소스 빌드와 별도 엔진 검증 경로를 사용합니다.

Suite CI의 한국어 입력 환경은 `scripts/ensure-korean-ime.ps1`로 준비합니다.
실제 Windows Server 2025 x64 호스트에서만 Microsoft 공식 미디어의 고정한 CAB와
구성 정보를 받아 오프라인 원본으로 설치합니다. Windows Update 정책은 바꾸지 않으며,
설치 상태·재시작 필요 여부·등록된 입력기와 Microsoft 서명을 직접 확인합니다.
이 준비 결과와 실제 편집기에서의 IME 조합 결과는 구분해서 기록합니다.
원본 로그는 단계별로 보존하고, 입력기 설치용 CAB는 전달 패키지에 포함하지 않습니다.

`work/opengeul-office-arm64`의 native31 privacy 준비는 저장소 소유자의 실제 push와
일치하는 소스·워크플로 커밋, 최초 실행(`GITHUB_RUN_ATTEMPT=1`)만 허용합니다.
실패한 작업을 재실행하기 전에 이 실행 조건을 확인해야 합니다. attempt 2 이상은
준비 단계에서 거부되며, 남아 있는 Windows privacy 화면 때문에 뒤의 GUI 검사도
실패할 수 있습니다. 그런 실행을 원래 제품 오류의 재현이나 해소 증거로 사용하지 않습니다.
수정·회귀 검사 후 정상 owner-push 경로에서 정확한 새 커밋을 검증하고, 이전 실패와
아키텍처별 성공 증거를 함께 보존합니다. 조건을 우회하는 빈 커밋이나 실행 값 위장은 하지 않습니다.

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

## 기능별 엔진 E2E

`e2e/office_feature_smoke.py`는 제품 설정의 Office 형식 15개를 각각 생성·저장하고
별도의 소유 프로세스·프로필에서 다시 열어 비교합니다. Writer 표와 문자 서식,
Calc 시트·수식 재계산, Impress 슬라이드, Draw 도형, Math 수식, Base 트랜잭션의
심화 사례 6개를 더해 고정한 21개 사례를 실행합니다. TXT/CSV는 텍스트·값 중심의
명시한 보존 범위로 판정합니다. 실패·누락·중복 사례와 비정상 종료는 통과할 수 없습니다.

이는 실제 엔진 기능 검사이며 물리적 GUI 입력 검사를 대신하지 않습니다.
`config/feature-catalog.json`은 시험별 판정 범위를 기록합니다. 해당 실행의
`office-features.json`과 원본 문서를 확인해야 실제 통과로 볼 수 있습니다.

### Bounded CI navigation diagnosis

`office-suite.yml` has an explicit `OPENGEUL_SUITE_RUN_MODE`. The temporary
`navigation-diagnostic` mode keeps the same owner-push/first-attempt privacy
admission and runs only the original Impress navigation plus PRE semantic
check after normal native preparation. It records owned-thread queue removal,
window-procedure entry/return and the existing UNO caret observation. No keys
are retried and no deadline or semantic assertion changes. Evidence is named
`opengeul-suite-navigation-diagnostic-<arch>-<run>-<attempt>`.

The mode deliberately ends with a non-acceptance failure after evidence upload;
it cannot deliver packages or establish IME success. Missing/overflowed trace
rows are inconclusive. Window-procedure return does not prove a particular
application shortcut handler ran. A substantive corrective commit must select
`acceptance` and pass every normal gate on both architectures before delivery.
Do not use an unchanged rerun or an empty commit to evade first-attempt admission.

`ime-mode-diagnostic` runs the original Calc IME case once per native architecture
with `--diagnose-ime-mode calc`. Bounded read-only snapshots compare existing
thread-local TSF compartments with IMM at the same owned message observations,
under the original setup deadline. The experiment can provide evidence distinguishing
a TSF mode reset from TSF/IMM disagreement; sequential reads are not an atomic
snapshot and do not identify the changing caller. It never
reopens mode, resends a key or creates a missing compartment. Separate
`opengeul-suite-ime-mode-diagnostic-<arch>-<run>-<attempt>` evidence and deliberate
nonacceptance failure prevent package qualification. Original acceptance gates
and first-attempt admission remain mandatory.

`focus-diagnostic` runs three fresh Calc instances with `--diagnose-focus calc`
to observe capture ordering around each original click and Ctrl+F6. Each case
keeps its five-second focus-entry budget and stops keyboard input before
navigation or IME. A QPC marker taken after readiness identifies later passive
capture observations within the remainder of that same original budget; it does
not timestamp the original readiness decision.
Native recording is bounded by that original deadline; at expiry or after a
failure only already-recorded local evidence is copied, with no further target
query or input. Owned process teardown and retained engine exit are required
before the next fresh case; forced cleanup is not graceful-shutdown evidence.
The intentionally incomplete keyboard session and any primary failure are
retained. Queue removal is not proof of handler execution. Separate
`opengeul-suite-focus-diagnostic-<arch>-<run>-<attempt>` evidence cannot qualify
acceptance or package delivery.

`sal-offset-mapping` performs file-only analysis of the observed ARM64 SAL return
offset. Both architectures retain native unit and shell checks. Exact owner-push,
first-attempt, HEAD and tracked-byte admission precedes the existing authenticated
ARM64 engine fetch. The bounded parser reads only the locked `program/sal3.dll`
member as data; it does not launch Office or prepare a desktop/IME session.
Only `.work/suite-sal-offset-mapping/receipt.json` is uploaded, never the engine
archive or DLL. A deliberate terminal failure prevents package qualification.
Existing GUI modes retain their preparation, privacy and acceptance gates.
