# Windows 기본 앱 활성화 진단

이 도구는 제품의 `open::that`와 `open::that_with_owner`를 실제 호출하는 별도 진단입니다.
제품 MSIX와 준비 HOP 소스에 포함하지 않습니다. 제품 shim의 소스 5개도 수정하지 않습니다.

Windows x64 또는 ARM64의 실제 native runner에서 해당 target으로 빌드합니다.

```powershell
cargo build --locked --manifest-path overlay/native-open-probe/Cargo.toml --target x86_64-pc-windows-msvc
python e2e/native_activation_probe.py --binary overlay/native-open-probe/target/x86_64-pc-windows-msvc/debug/opengeul-native-open-probe.exe --architecture x64 --output-dir .work/activation-x64
```

ARM64는 target을 `aarch64-pc-windows-msvc`, architecture를 `arm64`로 변경합니다.
`CARGO_TARGET_DIR`를 지정했다면 해당 경로의 실행 파일을 전달합니다.
기본 실행은 private 임시 폴더의 읽기 전용 한글 TXT 파일과 폴더만 기본 앱으로 엽니다.
파일은 명시적인 소유 HWND, 폴더는 제품의 자동 소유 창 발견 경로를 사용합니다.
각 probe는 STA 창을 만들고, controller가 실제 native PID·실행 파일·표시 중인 HWND
소유권을 확인한 뒤 GO를 보내야 활성화를 시작합니다. 제품의 STA 완료 대기를 그대로 사용합니다.

URI 진단은 기본 비활성입니다. `--include-uri`를 직접 지정한 경우에만 공식 글꼴 페이지
`https://opengeul.allenlim.net/fonts`를 소유 STA 창과 창 없는 MTA에서 각각 엽니다.
이 옵션은 실제 기본 브라우저를 실행할 수 있습니다. Store 제출·갱신에는 사용하지 않습니다.

`ready`의 `observationPhase: before-activation`은 호출 전 실제 창·COM 관측입니다.
`result`의 같은 공통 필드는 해당 요청을 식별하는 동일한 시작 전 snapshot이며 사후 창 관측이 아닙니다.
그 뒤 `outcome`, signed `hresult`, 오류와 소요 시간은 제품 API가 실제 반환한 결과입니다.
`accepted`는 Windows가 활성화를 수락했다는 뜻입니다. 외부 앱의 문서 렌더링, 설치 MSIX의
앱 identity, GUI 전체 동작 또는 WACK 통과를 증명하지 않습니다.

연결 앱 없음·취소·API 오류·시간 초과·잘못된 native target은 성공으로 처리하지 않습니다.
실패 출력도 보존하며 controller는 자신이 시작한 probe만 종료합니다. Explorer·연결 앱·브라우저는
종료하지 않습니다. `result.json`과 각 모드의 원래 stdout/stderr가 지정한 새 output 폴더에 남습니다.
실제 실행이 가능한 대화형 Windows desktop과 연결 앱이 필요합니다. Linux 교차 타입 검사와 Python
계약 테스트만으로는 실제 Windows 활성화가 검증되지 않습니다.
