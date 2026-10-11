# OpenGeul 개인정보 처리방침 / Privacy policy

적용 범위: OpenGeul 1.1.1–1.1.3(1.1.3은 개발 소스). 날짜: 2026-10-11.

## 한국어

OpenGeul은 사용자가 선택한 HWP/HWPX 문서를 PC에서 열고 편집하는 Windows 앱입니다. 문서 내용과 파일 경로에 개인정보가 포함될 수 있습니다. 앱은 문서를 읽고, 사용자가 지정한 위치에 문서와 PDF를 저장하며, 복사·잘라내기·붙여넣기 작업에 클립보드를 사용합니다. 인쇄를 요청하면 선택한 Windows 프린터로 출력 내용을 전달합니다.

최근 문서 목록은 최대 10개 파일의 이름과 전체 경로를 앱의 로컬 데이터 폴더에 저장합니다. 최근 문서 창의 **목록 비우기**로 지울 수 있습니다. **문서 이력 관리 → 현재 문서 저장**을 사용하면 문서 내용의 스냅샷, 파일 이름, 사용자가 지정한 이름과 저장 시각을 로컬 WebView 저장소에 보관합니다. 문서 이력 창의 **선택 삭제** 또는 **전체 비우기**로 지울 수 있습니다. 이 기능은 자동 저장이나 복구 기능이 아닙니다.

글꼴·화면·창 설정도 로컬에 저장합니다. 앱은 문서 표시와 PDF 내보내기에 설치된 글꼴 정보와 글꼴 파일을 읽습니다. Windows, WebView2 또는 앱의 진단 기능이 로컬 진단 정보를 남길 수 있습니다. 설정, 최근 문서 경로와 로컬 문서 이력에 별도의 앱 자체 암호화를 적용하지 않습니다. PC 사용자 계정과 저장장치의 보안 설정을 사용하세요.

암호 문서를 열어 처리하는 경우, 다른 이름으로 저장한 평문 파일, PDF, 인쇄물, 클립보드와 직접 저장한 문서 이력에는 암호가 해제된 내용이 포함될 수 있습니다. 원본 문서의 암호는 이 자료에 자동으로 유지되지 않습니다. 암호 원본을 보존하려면 다른 이름으로 저장할 때 별도 경로를 선택하세요.

함께 제공하는 명령줄 도구 `Tools/rhwp.exe`는 사용자가 지정한 문서, 글꼴 폴더와 문서 암호를 처리할 수 있습니다. 명령에 따라 문서 내용과 메타데이터를 파일 또는 표준 출력으로 내보냅니다. 사용자가 로컬 표준 입출력 방식의 MCP 서버를 실행하면 연결한 MCP 클라이언트로 문서 데이터를 전달할 수 있습니다. 도구를 연결한 클라이언트와 출력 파일의 접근 권한을 확인하세요.

이 버전에는 OpenGeul 계정 로그인, 광고, 분석용 추적(Telemetry) 또는 개발자 서버로 문서를 업로드하는 기능이 없습니다. **글꼴 도움말**의 다운로드 링크를 누르면 외부 글꼴 사이트를 기본 브라우저로 엽니다. 해당 사이트, Microsoft Store, Windows와 WebView2의 동작에는 각 제공자의 개인정보 처리방침이 적용됩니다. 사용자가 선택한 네트워크 경로, 클라우드 동기화 폴더와 네트워크 프린터는 해당 서비스로 데이터를 전달할 수 있습니다.

1.1.1–1.1.2에서는 앱 자체의 백그라운드 업데이트 확인이 비활성화되어 있습니다. 1.1.3 개발 소스는 새 Store 공개 버전을 기본으로 확인하며, 앱 시작 시와 실행 중 매시간 고정 주소 [공개 버전 JSON](https://opengeul.allenlim.net/api/store-release.json)을 HTTPS GET으로 읽습니다. **파일 → Store 업데이트 자동 확인**에서 끄면 예정된 자동 요청을 중단합니다. 이미 시작한 요청은 서버에 도착할 수 있습니다. 꺼진 상태에서도 **파일 → Store 업데이트 확인**으로 직접 조회할 수 있습니다. 새 버전 안내에서 사용자가 선택하면 고정 Microsoft Store 상품 페이지를 열며 다운로드·설치·종료·재시작을 강제하지 않습니다.

버전 조회에 문서 내용·파일 경로·비밀번호·클립보드·사용자 식별자를 추가하지 않습니다. 자동 확인 설정과 **나중에**로 숨긴 버전은 앱의 로컬 설정에 보관합니다. 이 요청을 제공하는 Cloudflare는 연결 IP, 접속 시각과 HTTPS 요청 정보를 처리할 수 있으며 [Cloudflare 개인정보 처리방침](https://www.cloudflare.com/privacypolicy/)이 적용됩니다. 문서 작업 결과를 수집하는 Telemetry와는 별개입니다. 미래 Telemetry 설계 문서를 준비했지만 이 버전에는 수집 코드·SDK·수집 서버를 넣지 않습니다.

문의는 [allenlim@allenlim.net](mailto:allenlim@allenlim.net) 또는 [OpenGeul 지원 페이지](https://opengeul.allenlim.net/#support)를 이용하세요. 공개 문의에 개인정보가 포함된 문서나 진단 정보를 첨부하지 마세요.

## English

OpenGeul is a Windows application that opens and edits HWP/HWPX documents on your PC. Document contents and file paths may contain personal information. The application reads documents you open, writes documents and PDFs to locations you choose, uses the clipboard for copy, cut and paste, and sends rendered content to your chosen Windows printer when you print.

The recent-document list stores the names and full paths of up to 10 files in the application's local data folder. Clear it with **목록 비우기** in the recent-document dialog. If you use **문서 이력 관리 → 현재 문서 저장**, the application keeps document-content snapshots, source filenames, your labels and timestamps in local WebView storage. Remove them with **선택 삭제** or **전체 비우기** in the document-history dialog. This manual history feature is separate from autosave or recovery, which this version does not provide.

Font, view and window preferences are also stored locally. The application reads installed font information and font files for document rendering and PDF export. Windows, WebView2 or application diagnostics may retain local diagnostic information. The application does not apply its own encryption to preferences, recent-document paths or local document history. Use your PC account and storage security settings to protect them.

When you open and process a password-protected document, plaintext Save As files, PDFs, printed output, clipboard data and explicitly saved local history may contain decrypted content. The original document's password is not automatically retained in those outputs. Choose a separate Save As path to preserve the protected original.

The bundled command-line tool `Tools/rhwp.exe` can process documents, font folders and document passwords you specify. Depending on the command, it writes document contents and metadata to files or standard output. If you launch its local stdio MCP server, it can return document data to the MCP client you connect. Check access to that client and any output files.

This version has no OpenGeul account login, advertising, analytics telemetry or feature that uploads documents to a developer-operated server. Clicking a download link in **글꼴 도움말** opens an external font website in your default browser. Those websites, Microsoft Store, Windows and WebView2 have their own privacy policies. Network paths, cloud-synced folders and network printers you choose can send data through those services.

Versions 1.1.1–1.1.2 disable the application's background update check. Development source 1.1.3 checks the fixed [public version JSON](https://opengeul.allenlim.net/api/store-release.json) using HTTPS GET at startup and every hour while running. **파일 → Store 업데이트 자동 확인** disables scheduled requests; a request already started may still reach the server. **파일 → Store 업데이트 확인** performs a manual check even when automatic checks are off. Choosing the update notice opens the fixed Microsoft Store product page without forcing download, installation, exit or restart.

Version checks add no document content, paths, passwords, clipboard data or user identifiers. Automatic-check preferences and dismissed versions are stored locally. Cloudflare may process connection IP addresses, request times and HTTPS request information under [its privacy policy](https://www.cloudflare.com/privacypolicy/). This public version lookup is separate from telemetry of document operations. Future telemetry is documented for planning only; this version includes no telemetry collector, SDK or collection server.

Contact the developer at [allenlim@allenlim.net](mailto:allenlim@allenlim.net) or through [OpenGeul support](https://opengeul.allenlim.net/#support). Do not attach documents or diagnostics containing personal information to a public issue.
