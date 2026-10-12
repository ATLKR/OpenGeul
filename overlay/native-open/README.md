# Windows 기본 앱·폴더 활성화

OpenGeul의 Windows 배포는 문서 위치, 내보낸 PDF, 공식 글꼴 링크,
Microsoft Store 링크를 Windows의 WinRT `Launcher` 계약으로 엽니다.
HOP의 `commands.rs`와 `open::that(...) -> io::Result<()>` 호출 형태는 유지합니다.
비 Windows 배포는 기존 `open` 5.3.3을 사용합니다.

파일·폴더와 소유 창이 있는 링크는 표시 중인 OpenGeul 소유 HWND를 확인한 뒤
`LauncherOptions` 또는 `FolderLauncherOptions`의 `IInitializeWithWindow`에 연결합니다.
별도 STA 스레드에서 WinRT를 호출하며, 비동기 결과를 기다리는 동안 COM과 창
메시지를 처리합니다. 호출자가 STA이면 작업 완료 대기에도 같은 처리를 적용하므로
기본 앱 선택 창이 앱 UI의 정지를 기다리는 교착을 피합니다.

메인 창 생성 전 WebView 설치 도움말처럼 URI에 소유 창이 없는 경우에는
공식적으로 지원되는 데스크톱 `LaunchUriAsync`의 MTA 호출을 사용합니다.
파일·폴더에는 이 예외를 적용하지 않습니다. 다른 프로세스의 창을 소유 창으로
사용하지 않고, 파일 경로는 `OsString`과 UTF-16로 보존합니다.

API가 `false`를 반환하거나 취소·HRESULT 오류가 발생하면 호출자에게 오류를
반환합니다. 성공은 Windows가 요청을 수락했다는 뜻이며 외부 앱의 문서 렌더링
완료를 의미하지 않습니다. 제품에서 사용하는 `http`, `https`, `ms-windows-store`
URI만 지원합니다. 셸 명령, 실행 파일 직접 실행, 재시작 대체 경로는 없습니다.

Tauri의 로컬 소스 패치는 Windows의 `opengeul-store-no-restart` 기능에서 앱 자체
재시작을 거부합니다. 제품의 업데이트 메뉴는 이미 Store에서 업데이트하도록
안내하며, 정상 종료·창 닫기 경로는 원본대로 유지합니다. Tauri 오류 대화상자의
도움말 링크도 실제 대화상자 HWND와 이 활성화 경로를 사용합니다.

원본 크레이트는 기존 Cargo.lock의 SHA-256으로 검증하며 패치 전후 전체 파일
목록을 준비 증명에 기록합니다. Python 검증은 소스 준비의 무결성만 검사합니다.
Rust 단위 테스트, x64·ARM64의 실제 앱 실행과 기본 앱·폴더 열기, 실제 WACK
전체 통과는 Windows CI에서 별도로 확인해야 합니다.

공식 계약:

- [LaunchUriAsync](https://learn.microsoft.com/en-us/uwp/api/windows.system.launcher.launchuriasync)
- [LaunchFileAsync](https://learn.microsoft.com/en-us/uwp/api/windows.system.launcher.launchfileasync)
- [LaunchFolderAsync](https://learn.microsoft.com/en-us/uwp/api/windows.system.launcher.launchfolderasync)
- [LauncherOptions의 소유 HWND](https://learn.microsoft.com/en-us/uwp/api/windows.system.launcheroptions)
- [FolderLauncherOptions의 소유 HWND](https://learn.microsoft.com/en-us/uwp/api/windows.system.folderlauncheroptions)
