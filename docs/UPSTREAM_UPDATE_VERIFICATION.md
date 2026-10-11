# HOP 0.4.5 / rhwp 0.8.7 통합 검증 기록

2026년 10월 11일 업데이트는 공식 HOP `v0.4.5` 릴리스를 `34bd15c97e0851627cb7f055042c5340198aeb7f`로, 정확한 rhwp `v0.8.7` 하위 모듈을 `1a76570e833917d15817415a53c09ad61ab3203f`로 고정했습니다. 저장소는 계속 `https://github.com/golbin/hop.git`와 `https://github.com/edwardkim/rhwp.git`입니다. HOP 기본 브랜치의 더 새로운 커밋은 릴리스 검증 문서를 추가하지만 이번 실행 코드 업데이트에 필요하지 않습니다. rhwp 릴리스의 후속 CLI 자산 재패키징은 소스 태그를 바꾸지 않았습니다. Rust 1.93.1과 pnpm 10.33.0 고정값도 유지합니다.

이 엔진은 이전 키보드, 도구 모음과 마지막 음수 간격 백포트를 대체합니다. 기여자 표시는 `THIRD_PARTY_NOTICES.md`에 유지하고 소스 패치와 표 패치 기록 요구는 제거했습니다. 제한적인 설정 이전은 HOP의 더 새로운 명시적 선택을 존중하면서 기존 OpenGeul의 도구 모음 숨김 설정을 보존합니다. 독립 표 판정식과 관찰한 수정 전 WASM 해시는 `TABLE_HEIGHT_VERIFICATION.md`에 기록합니다.

HWPX 임시 저장 오버레이는 업스트림의 공개 문서 작업 래퍼와 비공개 안전 저장 메서드를 유지합니다. 비공개 형식 대체 경로는 작업 잠금을 중첩해서 얻지 않습니다. 암호 문서의 동의는 선택한 HWP/HWPX 형식에 적용합니다. 취소하면 원래 문서와 암호 플래그를 유지하고, 평문 교체가 확정된 뒤에만 플래그를 해제합니다. 최종 조합 입력 보정은 rhwp의 새 셀 블록 IME 가드 뒤에서 실행합니다. 회귀 테스트는 실제 생성된 Studio 소스에서 동의, 미저장 문서의 안전 저장, 안전 저장 중 편집과 동시 열기·PDF·인쇄·닫기 시도를 검사합니다.

## PDF 정책 호출 경로

GUI는 `apps/desktop/src-tauri/src/pdf_export.rs::export_core_to_pdf` → `apps/desktop/rhwp-adapter/src/lib.rs::searchable_pdf_from_svg_pages` → `renderer/pdf.rs::svgs_to_pdf_with_options` 경로를 유지합니다. CLI는 `src/cli/outputs/pdf.rs`에서 `PdfBackend::default()`를 초기화하며 업스트림 기본 열거값은 `CompatibilitySvg`입니다. SVG 분기도 같은 변환 지점에 도달합니다. SVG 래퍼는 `svgs_to_pdf_with_links_and_to_chunk`에서 합쳐집니다. 여기서 OpenGeul은 변환 전에 실제 글꼴 데이터베이스를 필터링하고, 명시적으로 요청한 글꼴의 포함 메타데이터가 하위 집합 포함을 금지하면 거부합니다.

새 `--backend direct` 분기는 `render_pages_pdf_direct_native_with_profile_and_options`에 도달한 뒤 `DocumentCore` 구현과 `layer_trees_to_pdf_with_links`로 위임합니다. 공개 레이어 트리 PDF 함수 3개는 이 지점에서 합쳐집니다. Skia 렌더러는 자체 시스템 글꼴 관리자를 만들고 사용자 지정 글꼴 경로를 읽으며 포터블 글리프 실행의 글꼴 바이트도 사용할 수 있습니다. SVG 글꼴 데이터베이스나 사용자 지정 경로만 필터링해서는 이 경로에 같은 포함 정책을 강제할 수 없습니다. 따라서 OpenGeul은 SVG 백엔드를 권하는 명시적 오류로 선택적인 직접 PDF 변환 지점을 거부합니다. PNG 렌더러는 계속 사용할 수 있습니다. Skia 글꼴 리소스 필터를 독립 검증할 때까지 적용하는 제한된 호환 정책입니다.

네이티브 정책 테스트 대상은 업스트림의 기존 MIT 라이선스 결정적 테스트 자료 `RHWPExactKerningSmoke.ttf`를 사용합니다. 설치된 글꼴에 의존하지 않고 허용·제한 글꼴을 검사하려고 메모리 안의 OS/2 포함 비트와 글꼴 이름만 바꿉니다. 유효한 허용 SVG PDF, 제한 SVG 오류, 포터블 글리프 리소스를 포함한 직접 진입점 3개, 정상 기본 SVG 백엔드와 유지된 PNG 렌더링을 검사합니다. 이 저장소나 배포 앱에 글꼴 바이너리를 추가하지 않습니다. rhwp 0.8.7은 통합 테스트 자동 검색을 비활성화하므로 `prepare_native_tests.py`가 표·정책 대상 둘을 명시적으로 등록하고 소스 해시를 기록합니다. 테스트 파일을 복사하기만 하면 검색될 것이라고 가정하지 않습니다.

## 당시 로컬 검사와 남은 필수 검증

로컬 검사는 정확히 고정한 커밋의 격리된 부분 체크아웃 `.work/validation-hop`에 같은 다운스트림 변환을 순서대로 적용했습니다. 소스 검증이며 배포용 전체 체크아웃 파이프라인을 대신하지 않습니다. 기록한 명령은 다음과 같습니다. 명령과 원래 실행 주석을 그대로 보존합니다.

```text
python -m unittest discover -s tests -v                         # 220 passed
python -m unittest discover -s ci/tests -v                      # 84 passed
HOP_SOURCE="$PWD/.work/validation-hop" RHWP_SOURCE="$PWD/.work/validation-hop/third_party/rhwp" node --experimental-strip-types --loader ./tests/hop/loader.mjs --test tests/hop/*.test.mjs
                                                              # 33 keyboard/toolbar checks passed
node --experimental-strip-types --test tests/composition-final.test.mjs tests/save-format.test.mjs
                                                              # 22 passed
(cd .work/validation-hop && corepack pnpm run test:studio)        # 177 passed, 23 files
(cd .work/validation-hop && corepack pnpm run build:studio)       # passed
python scripts/buildkit.py frontend .work/validation-hop/apps/studio-host/dist
                                                              # font-file audit passed
node e2e/table_height.mjs verify .work/validation-hop/apps/studio-host/vendor/rhwp-core .work/table-fixtures
                                                              # 6 pristine cases passed
python scripts/prepare_native_tests.py .work/validation-hop/third_party/rhwp
                                                              # explicit targets registered
CARGO_HOME="$PWD/.work/cargo" RUSTUP_HOME="$PWD/.work/rustup" CARGO_TARGET_DIR="$PWD/.work/target-namespace-api" .work/cargo/bin/cargo test --manifest-path overlay/namespace-tests/Cargo.toml
                                                              # 7 passed against quick-xml 0.42.0
CARGO_HOME="$PWD/.work/cargo" RUSTUP_HOME="$PWD/.work/rustup" CARGO_TARGET_DIR="$PWD/.work/target-wasm-check" CARGO_BUILD_JOBS=2 CARGO_PROFILE_DEV_DEBUG=0 .work/cargo/bin/cargo check --manifest-path .work/native-policy-source/Cargo.toml --locked --target wasm32-unknown-unknown --lib
                                                              # production wasm32 Rust graph passed
LIBRARY_PATH="$PWD/.work/native-system-libs" CARGO_BUILD_JOBS=2 CARGO_HOME="$PWD/.work/cargo" RUSTUP_HOME="$PWD/.work/rustup" CARGO_TARGET_DIR="$PWD/.work/target-native-validation" .work/cargo/bin/cargo test --manifest-path .work/native-policy-source/Cargo.toml --locked --features native-skia --test opengeul_pdf_policy --config 'profile.dev.package.rhwp.debug=0' --config 'profile.test.package.rhwp.debug=0'
                                                              # 4 native policy checks passed
```

수정하지 않은 WASM의 원래 출처 기록은 정확한 rhwp 커밋을 가리키며 표 검사에 사용한 바이트와 일치합니다. 이 WASM에서도 네임스페이스 RED 대조군이 재현되므로 소스 빌드 네임스페이스 오버레이는 계속 필요합니다. 로컬 로그·해시 근거는 `.work/upgrade-evidence`에 있습니다. Git에서 제외한 이 파일은 이 작업 공간의 증거이며 릴리스 산출물이 아닙니다.

생성된 엔진 컴파일에서 네임스페이스 도우미의 추가 의존성 호환 문제를 발견했습니다. quick-xml 0.42는 속성 키를 문자열로 제공하지만 이전 도우미는 바이트 슬라이스를 기대했습니다. 변경하지 않은 도우미와 정확한 `quick-xml = "=0.42.0"`를 사용한 비공개 로컬 검사에서 `to_vec` 컴파일 오류를 재현했습니다(`namespace-api-red.log`). 배포용 도우미는 이제 키 문자열을 소유하고 문자열을 직접 비교합니다. XML 조각, QName 값과 이스케이프 동작은 유지합니다. 실제 독립 회귀 대상은 0.42.0으로 고정하고 별칭, 상속·기본 네임스페이스, 로컬 재연결, 정확한 바이트, 이스케이프된 URI와 잘못된 조각 사례 7개를 모두 통과했습니다(`namespace-api-green.log`). 생성된 네이티브·WASM 소스 사본과 네임스페이스 기록의 도우미 해시는 수정한 오버레이와 일치합니다. 배포용 wasm32 Rust 그래프는 `cargo check --locked --target wasm32-unknown-unknown --lib`를 통과했습니다(`wasm-compile-check.log`). 타입 컴파일 검사이며 필수 릴리스 WASM·브라우저 실행은 아닙니다.

Cargo의 부분 체크아웃 지문 처리 때문에 Git 메타데이터가 없는 검증 전용 소스 사본 `.work/native-policy-source`가 필요했습니다. 검사한 매니페스트, 잠금 파일, 파서 도우미·헤더, PDF 소스·가드, 테스트와 자료 해시는 생성한 트리와 일치합니다(`pdf-policy-source-hashes.json`). 부분 체크아웃은 정확히 고정한 컴파일 시점 서식 `saved/blank2010.hwp`도 가져왔으며 SHA-256은 `43f472751fafefb8c66b0f831660ebed51e443a46bebe44c75bba918154ce4c9`입니다. 배포용 준비는 기존의 전체 가져오기를 수행합니다. 네이티브 Skia를 컴파일한 뒤 시스템에 이미 있는 FreeType/fontconfig 실행 라이브러리를 작업 로컬 이름으로 연결했습니다. 시스템 파일이나 의존성 고정값은 바꾸지 않았습니다. 실제 PDF 대상은 테스트 4개를 모두 통과했습니다(`pdf-policy-native-final.log`). 허용 SVG 출력은 완전하고 검색 가능한 상태를 유지하고 제한 SVG 출력은 거부하며, 모든 직접 PDF 진입점은 안전하지 않은 포함을 거부하고 네이티브 PNG는 계속 사용할 수 있습니다. 표 대상은 native-Skia 그래프와 일치하는 기본 기능 배포 그래프에서 모두 통과했습니다.

최종 후보는 소스 빌드 WASM·브라우저 파이프라인, 네이티브 Rust 형태·글꼴 포함 정책 테스트, Windows 컴파일·단위 테스트, 설치 MSIX 동작, 암호 문서 UI, 편집기 UI 실행 78회와 모든 가상 프린터 비교를 통과해야 합니다. 기존 인쇄 기준은 유지합니다. 로컬 소스·프런트엔드 결과만으로 Windows UI, 인쇄와 WACK을 확인하지 않습니다. 업스트림의 변경하지 않은 Windows 빌드 스크립트만으로 별도 DPI 인증 검증을 해결하지 못합니다. 일반 SDK 패키지 입력 경로와 통제된 진단 근거는 `WACK_PACKAGE_INPUT.md`에 기록하며 업데이트한 소스도 자체의 전체 검증이 필요합니다.

rust-skia는 0.153.3, 소스 커밋 `b7f043e0b1e2a850e702245de811f01df1f6b0ff`이며 Cargo.lock은 각 crate의 정확한 체크섬을 유지합니다. MIT 라이선스 원문은 변경하지 않았습니다(1,123바이트, SHA-256 `4b33ed5b329a3a79eb1243fd91373c68b0ae0b9df7503bfc50d0c5253adf1b9a`). 버전을 갱신한 고지도 유지합니다.

당시 최종 배포용 네이티브 매트릭스는 릴리스 검증 전에 Windows 이미지별 추가 암호 사례 8개를 실행하도록 했습니다. 정확한 소스 바이트, 현재 워크플로 SHA·실행, 패키지 런타임 파일 해시와 소스에 연결된 재빌드 WASM이 실제 후보와 이 사례들을 묶습니다. 크기 제한 증거 수집기는 두 테스트의 결과와 암호 식별자·자료 메타데이터를 우선합니다. 압박 조건 회귀 테스트 2개에서 수정 전 중첩 요약과 실패 사례 누락을 재현했습니다. 업로드 증거에서 합성 문서 파일과 글꼴을 포함한 리소스는 계속 제외합니다. 필수 단계는 기존 네이티브 시나리오 16개와 릴리스·중간 산출물 정리 의존성을 유지합니다. 이 로컬 기록 작성 당시 Windows 결과는 최종 소스 실행 완료 전까지 미확인 상태였습니다. 이후 실행별 결과와 새 1.1.3 후보의 검증은 별도 근거로 확인해야 합니다.
