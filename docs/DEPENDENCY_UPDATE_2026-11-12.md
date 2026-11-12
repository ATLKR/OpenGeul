# 2026-11-12 의존성 후보

이 기록은 `work/opengeul-office-arm64`의 HWP 편집기 소스 후보를 다룹니다. 기존 HWP 배포판과 Suite가 고정한 HWP 입력은 보존합니다. LibreOffice 엔진의 기존 소스 자격, Suite의 Windows 검증 및 이 새 HWP 후보의 검증은 서로 다른 증거입니다. 제품 버전은 1.1.5를 유지하며 배포하거나 공개 릴리스하지 않습니다.

## 선택한 소스와 그래프

| 항목 | 이전 | 후보 |
|---|---|---|
| HOP | 0.4.5 / `34bd15c97e0851627cb7f055042c5340198aeb7f` | 0.5.3 / `c298160120c9ffbfca7e72f13dc2e7060ddff7fe` |
| rhwp | 0.8.7 / `1a76570e833917d15817415a53c09ad61ab3203f` | 0.9.0 / `c9095c5f67632e6721e800ccc7fb43ea49d26682` |
| pnpm | 10.33.0 | 10.34.9 |
| npm `@tauri-apps/api`·CLI | 2.10.1 | 2.12.4 |
| Tauri Rust | 2.11.1 | 2.12.5 |
| tauri-runtime-wry | 2.11.1 | 2.12.3 |
| reqwest | 0.13.2 | 0.13.5 |
| tokio | 1.52.1 | 1.54.1 |
| rustls | 0.23.45 | 0.23.46 |
| rust-skia | 0.153.3 | 0.156.0 / `ce6727ef251518df37bcfdde4865b71f7e3a4352` |

[HOP 0.5.3](https://github.com/golbin/hop/releases/tag/v0.5.3)의 gitlink가 바로 [rhwp 0.9.0](https://github.com/edwardkim/rhwp/releases/tag/v0.9.0)을 선택합니다. 둘을 임의의 개발 브랜치로 조합하지 않습니다. CLI 잠금은 이 rhwp 원본의 420개 패키지 정체성·체크섬·원래 의존성 연결을 보존하고, 기존 COM 작업자에 필요한 Windows 0.61 계열 9개만 추가합니다. 원래 선택적인 Windows 0.62 연결도 보존합니다. 데스크톱은 정확한 Tauri 보안 수정과 기존 WinRT 활성화 패치를 함께 적용한 769개 패키지를 잠급니다. 두 Windows 계열은 버전·체크섬으로 구분합니다.

Tauri 2.11.1은 출처 혼동 수정만 포함합니다. 별도의 [채널 fetch ACL 우회 권고](https://github.com/tauri-apps/tauri/security/advisories/GHSA-w28w-mhc8-qvjv)는 2.11.6 이상이 필요하므로 이 후보에서는 2.12.5로 이식했습니다. 채널의 소유 WebView 검사, 일회 소비와 종료 정리를 변경하지 않았습니다. [활성 보안 기록](tauri-security-overlay.md)을 따릅니다.

## 유지하거나 별도 검증하는 도구

Rust 고정값은 rhwp의 공식 1.93.1, Node는 기존 지원 계열 24를 유지합니다. 조사 당시 Rust stable은 1.99.1, Node 최신 LTS는 26.13.1이며 24 계열 최신 보안판은 24.22.3입니다. pnpm 전체 최신은 12.18.0이지만 이번에는 같은 10 계열을 선택했습니다. Rust 1.93.1과 1.99.1은 로컬 검사에서 구분해 기록합니다. 로컬 Node는 24.19.0이므로 24.22.3 실행 증거로 바꾸어 보고하지 않습니다.

HOP 원본 frozen lock의 npm `@tauri-apps/api`와 `@tauri-apps/cli`는 2.10.1입니다. 이번 후보는 [Tauri의 같은 minor 호환 지침](https://v2.tauri.app/develop/updating-dependencies/)에 따라 Rust 2.12.5와 npm 2.12.4를 함께 검증합니다. 최초 frozen install 전에 검토한 잠금 overlay와 두 manifest를 적용하고 notice selector의 전체 lock SHA도 함께 고정합니다. API·CLI 및 11개 platform package 외 나머지 98개 package block과 dialog/fs plugin 버전은 보존합니다. .NET·Pillow·PDF 검증 도구와 LibreOffice 엔진은 별도 작업 범위의 기록으로 확인합니다.

공식 메타데이터: [Rust stable](https://static.rust-lang.org/dist/channel-rust-stable.toml), [Node 배포](https://nodejs.org/dist/index.json), [pnpm 10](https://registry.npmjs.org/pnpm/latest-10), [Tauri](https://crates.io/api/v1/crates/tauri), [reqwest](https://docs.rs/crate/reqwest/0.13.5/source/Cargo.toml.orig), [Tokio](https://github.com/tokio-rs/tokio/blob/tokio-1.54.1/tokio/CHANGELOG.md), [rustls](https://docs.rs/rustls/0.23.46/rustls/).

## 보존한 동작과 소스 경계

비동기 clipboard·그림·설치 글꼴 선택의 문서/선택/수명 가드, 원자적 붙여넣기·도형 이력, 중첩 Home/End, 수식 대화상자 포커스, HWPX 네임스페이스·저장 보호를 새 소스에 재적용하고 전후 SHA를 고정합니다. 새 `clipPath` 노드는 자식의 실제 native 줄 소유권을 유지하여 탐색합니다. HOP의 native 제목 동기화에도 OpenGeul 이름과 원래 dirty·문서 표시를 유지합니다.

PDF의 새 공개 annotations 진입점도 같은 직접 PDF 포함 정책에서 거부합니다. 설치 글꼴 필터, 불완전한 페이지의 명시적 실패 및 검색 가능한 SVG/PDF 좌표 정책은 유지합니다. 새 저장 캐시·그림 이동 공통 파일을 source proof에 추가합니다. 전체 core parity는 `src`, `crates`, `vendor`와 root `build.rs`를 포함하며 기존 크기·파일 수 제한을 늘리지 않습니다.

rhwp가 Git에 배포하지 않은 선택적 vendor signatures unit-test 인증서 한 건은 정확한 root manifest/source SHA와 경로로만 비실행 대상임을 구분해 `.opengeul-compile-inputs.json`에 기록합니다. root workspace의 `--all-features`에도 그 vendor signatures 기능은 연결되지 않습니다. 인증서를 만들거나 일반적인 누락 include를 허용하지 않으며, 원문 한 바이트가 바뀌면 기존 누락 입력 실패가 유지됩니다.

## WASM과 PDF 가져오기

공식 HOP 0.5.3처럼 WASM은 `--no-default-features --features console_error_panic_hook,wasm-api`로 빌드합니다. 기존 HWP/HWPX 편집과 PDF 내보내기는 유지하며, 새 선택 기능인 PDF 가져오기를 자동으로 활성화하지 않습니다. 생성·설치·구성요소 소비자는 이 feature 선택을 담은 정확한 generator 증명을 요구합니다. `wasm-pack` 전용 옵션 뒤의 Cargo 인수 경계도 회귀로 확인합니다.

이 최소 그래프에서 `PdfEditorReopen` export가 없는 빌드 경고는 지원하는 PDF 가져오기 기능의 증거가 아닙니다. 실제 HOP 화면은 HWP/HWPX만 파일 선택기에 제시하고 PDF를 강제로 선택해도 명시적인 형식 오류를 표시합니다. 실제 브라우저 검사는 private 앱 API 없이 오류 전후 저장한 합성 HWPX를 독립 oracle로 비교합니다. 새로 빌드한 WASM과 원래 upstream WASM의 결과는 구분합니다.

## 패키지 증명 크기

실제 `src`·`crates`·`vendor`의 3,205개 원문 해시를 모두 유지한 source contract는 compact 482,626바이트입니다. 분리 전 실측에서는 새 고지 1,736개를 같은 provenance의 inline inventory에 더한 하한만 773,791바이트로, 런타임·CI 필드를 넣기 전부터 기존 512KiB 제한을 넘었습니다.

editor component v2는 payload 파일 목록만 별도 `payload-inventory.json`으로 전송하고, provenance가 정확한 경로·크기·SHA-256을 바인딩합니다. source contract와 모든 기존 의미 검증은 그대로입니다. CLI gzip v2도 유지합니다. 각 JSON의 512KiB, 전체 transport·복원 크기와 파일 수 제한을 늘리지 않습니다. 단일 bounded handle에서 파일 정체성·hardlink·reparse·크기·해시·UTF-8·중복 키·Windows 이름 충돌을 확인하고, 실제 payload 전체와 정확히 비교한 뒤 기존 source/PE 검사와 결합을 수행합니다. 큰 소스와 고지의 동시 입력, 누락·추가·변조·동일 바이트 경로 교체를 회귀로 검사합니다. 최종 Windows PE 및 실제 CI context가 있는 component capture의 크기는 실제 Windows 실행에서 확인해야 합니다.

## 확인한 로컬 실행

고정 Rust 1.93.1, wasm-pack 0.14.0과 대응 wasm-bindgen 0.2.127로 실제 소스 release WASM을 빌드했습니다. 최종 공통 HWP 저장 경계 수정본은 21,274,337바이트, SHA-256 `d4c813615e07d3dff71c543054478b9927d7e2a16122df8aaf0008f2817308bf`입니다. 이전 `f070f719…` 산출물과 검사는 수정 전 증거로 보존하며 재사용하지 않습니다. 이 새 바이너리로 Node 편집 회귀 241개, Studio 248개, TypeScript/Vite 빌드와 독립 XML namespace 왕복을 통과했습니다. Linux Chromium의 실제 production UI에서 HWPX를 열고 저장한 뒤 비지원 PDF 선택의 명시적 오류를 확인했으며, 다시 저장한 HWPX의 텍스트·구조는 독립 oracle에서 같았습니다. private 앱 API는 사용하지 않았습니다. 이는 Windows IME·접근성 수용을 대체하지 않습니다.

최신 reqwest/Tokio/rustls를 사용하는 전송 정책 Rust 검사 30개도 1.93.1에서 통과했습니다. 같은 source/compiler와 shipping default `native-skia` 그래프에서 저장 행 28개, PDF 정책 11개, 설치 글꼴 해석 11개를 모두 실행해 50개 통과, ignored/filter 0을 확인했습니다. 원래 실제 실패 5개와 추가 witness 실패 1개는 보존했습니다. 실제 누락된 공통 HWP `export_cache` 경계를 고쳤고, body의 실제 재흐름과 header/footer의 재흐름 없는 dirty 경계를 서로 다른 강한 증인으로 확인합니다. HWP와 HWPX의 원래 축 밖 fallback 차이도 유지합니다.

최종 제품 helper 수정 후 Python은 제품 1,575개/skip16, CI 261개/skip6로 실패·오류 없이 통과했습니다. 이후 Rust fixture의 최소 수정 뒤 component/source contract 163개, native-test 준비 4개와 native 입력 12개, 합계 179개를 다시 검사해 skip 없이 통과했습니다. 부모의 별도 전체 Suite 검사도 Linux에서 4,787개/skip18/실패0/오류0, HEAD·dirty scope·1,090개 파일 해시 전후 동일을 확인했습니다. 이 검사 뒤 최소 Rust fixture 변경의 관련 검사는 위 179개와 native 50개입니다.

표 geometry 입력은 정확한 합성 1×1 셀·5문단·스타일·수직 여백을 검사한 뒤, cache가 모두 없는 경우에만 원래 `Paragraph::new_empty`의 9개 속성으로 명시적 source cache를 만듭니다. 원래 기하 기대값은 바꾸지 않았습니다. 최종 실제 WASM에서 간격 -300/0/600의 열기·독립 재열기 6회가 통과했고 셀 높이는 54.4/70.4/102.4px입니다. namespace 왕복, 표 입력, 브라우저 검사에는 생성한 합성 문서만 사용했습니다.

실제 새 WASM에서 검토한 공개 vendor 글꼴 4개의 전체 바이트가 없음을 확인했지만, 모든 내장 글꼴 프로그램의 부재나 native CLI/Windows PE 검증으로 확대하지 않습니다. Linux 네이티브 CLI release 빌드·도움말·글꼴 잔류 검사는 별도로 진행 중이며, 새 HWP의 실제 Windows x64/ARM64·MSIX·IME·접근성·설치 검증은 아직 이 로컬 결과로 대신할 수 없습니다.

npm 2.12.4 후속 후보는 공개 Git blob으로 인증한 제품 frontend 부분 트리에 실제 준비 helper·namespace patch·현재 source-bound WASM을 적용해 Node 241개, Studio 248개와 TypeScript·Vite·frontend audit을 통과했습니다. 현재 runtime source 3,205개와의 바이트 일치도 확인했습니다. 이 부분 트리 검사는 전체 source parity나 새 Windows binary·전체 notice inventory·MSIX 수용 증거가 아닙니다. 해당 결과는 최종 같은 커밋의 CI에서 별도로 확인합니다.

## 고지와 남은 수용 게이트

실제 Cargo·pnpm 그래프의 고지 목록은 과포함 1,038개 기록이며, 본문이 없는 77개는 `requires-human-review` 상태로 남깁니다. 새 PDF vendor의 중첩 고지 6개를 정확한 package/version/path/SHA allowlist로 보완합니다. IJG 조건, DejaVu/Noto/fallback 글꼴 고지 및 test asset 출처도 원문 그대로 수집합니다. 이 inventory는 실제 바이너리 사용 범위보다 넓으며 법적 배포 허가 판정이 아닙니다. 새 CLI default PDF import의 bundled font 코드가 실제 최종 바이너리에 남는지는 별도 검사해야 합니다. 설치 글꼴 정책이나 payload 검사를 우회하지 않습니다. 기존 rust-skia 0.153.3 고지도 삭제하지 않습니다.

로컬 소스 준비·Python·Node·Studio·Rust 타입 및 native-Skia 정책 검사와 실제 Windows 빌드/실행·IME·접근성·설치/업데이트/복구는 별도 게이트입니다. 새 후보의 Windows/MSIX와 새 엔진의 최종 수용 결과가 없으면 출시 후보 완료로 표시하지 않습니다. 실행별 수치와 산출물은 해당 commit/run의 검증 보고에 연결해야 합니다.
