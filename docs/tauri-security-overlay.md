# Tauri 출처·채널 보안 수정

현재 후보는 HOP 0.5.3 / rhwp 0.9.0을 고정하고 Rust Tauri **2.12.5**, tauri-runtime-wry **2.12.3**을 사용합니다. 두 crate의 버전 번호가 같다고 가정하지 않습니다. 이전 Tauri 2.11.1의 출처 혼동 수정만으로 최신 후보가 안전하다고 판단하지 않습니다.

[GHSA-7gmj-67g7-phm9](https://github.com/advisories/GHSA-7gmj-67g7-phm9)는 Windows/Android의 공격자 도메인을 로컬 IPC 출처로 오인하는 문제를 2.11.1에서 수정했습니다. 별도의 [GHSA-w28w-mhc8-qvjv](https://github.com/tauri-apps/tauri/security/advisories/GHSA-w28w-mhc8-qvjv)는 2.11.5까지의 채널 fetch ACL 우회를 다루며 2.11.6 이상이 필요합니다. OpenGeul 자체에서 공격을 재현했다는 의미는 아닙니다.

`prepare_upstream.py`는 선언을 `tauri = "=2.12.5"`로 정확히 고정하고, HOP 0.5.3의 패키지 버전만 제품 버전으로 바꾼 잠금을 적용합니다. `native_activation.py`는 공식 원본 체크섬을 검증한 2.12.5/2.12.3 source vendor에 기존 Store restart 보호와 WinRT 대화상자 활성화 변경을 적용합니다. 프로세스 실행으로 돌아가는 대체 경로는 추가하지 않습니다. 원래 shim의 Windows 0.61과 새 runtime의 0.62 계열은 정확한 버전·레지스트리 체크섬으로 구분하고 두 family를 증명합니다.

`native_source_contract.py`의 고정 inventory는 실제 공식 원문 166개, 검토한 수정 5개와 shim 5개를 producer/consumer 양쪽에서 확인합니다. 새 Tauri 채널 코드는 WebView별 순차 payload ID를 사용하며 무작위 ID라고 설명하지 않습니다. 소유 WebView에 한정한 fetch, 일회 소비, 종료 정리와 stale instance 거부는 이 다운스트림 패치에서 변경하지 않았습니다. 원문과 패치 결과의 drift는 실패해야 합니다.

직접 활성화 회귀 13개, source contract 전송 회귀 12개와 실제 공식 원문 provision/capture/validate는 로컬에서 확인했습니다. Cargo 잠금 해석은 소스와 ABI를 사용하는 실제 Windows 실행을 대체하지 않습니다. 이전 2.11.1 검증 수치와 과거 Windows 산출물을 새 2.12.5 후보의 성공 증거로 재사용하지 않습니다. npm API/CLI는 HOP의 기존 2.10.1 잠금을 유지하므로 Tauri 도구 전체를 최신화했다는 주장을 하지 않습니다.

전체 의존성 선택과 남은 수용 게이트는 [2026-11-12 후보 기록](DEPENDENCY_UPDATE_2026-11-12.md)에 정리합니다. 실제 Windows 빌드·메뉴·단축키·포커스·접근성·저장/재열기·패키지 검증을 통과한 동일 commit의 새 바이너리로 최종 자격을 판단해야 합니다.
