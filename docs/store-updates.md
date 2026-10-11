# Microsoft Store 업데이트 확인

OpenGeul은 기본으로 시작할 때와 앱이 열린 동안 마지막 확인에서 1시간마다 공개 버전을 확인합니다. 파일 메뉴의 **Store 업데이트 자동 확인**에서 끌 수 있으며, **Store 업데이트 확인**은 자동 확인을 꺼도 사용할 수 있습니다. 새 버전 알림은 문서 작업을 막지 않습니다. **나중에**를 선택한 버전은 다음 자동 확인에서 다시 알리지 않고, 사용자가 수동으로 확인하면 다시 볼 수 있습니다.

알림의 질문은 **Microsoft Store에서 업데이트하시겠습니까?**입니다. 사용자가 Store 열기를 선택하면 아래 고정 주소만 엽니다.

`https://apps.microsoft.com/detail/9PJH0T3PHRMF`

앱은 업데이트 파일을 다운로드하거나 설치하지 않으며 자동으로 종료·재시작하지 않습니다. 기존 업스트림 updater 플러그인 등록도 제거된 상태를 유지합니다. 설치는 Microsoft Store가 처리합니다.

## 공개 버전 조회 계약

네이티브 코드가 `https://opengeul.allenlim.net/api/store-release.json`에 GET 한 번을 보냅니다. 문서 내용, 사용자 식별자, 텔레메트리, 요청 본문, 쿼리 문자열을 붙이지 않습니다. HTTPS 인증서 검증을 사용하며 리디렉션을 따르지 않습니다. 연결 제한은 3초, 요청 전체 제한은 8초입니다. 응답의 실제 누적 바이트와 선언된 길이를 모두 확인하며 최대 8 KiB까지 허용합니다. 자동 확인 실패는 작업을 방해하지 않고 다음 주기에 재시도합니다. 수동 확인 실패만 한국어 오류와 재확인 동작을 제공합니다.

JSON은 UTF-8이어야 하며 다음 여섯 필드를 모두 포함해야 합니다. 추가 필드·중복 키·다른 타입은 거부합니다.

```json
{
  "formatVersion": 1,
  "appId": "9PJH0T3PHRMF",
  "status": "Published",
  "version": "1.1.1.0",
  "storeUrl": "https://apps.microsoft.com/detail/9PJH0T3PHRMF",
  "submissionId": "1152921505702042424"
}
```

`version`은 각 항목이 0~65535인 정규 네 부분 숫자 버전이며 불필요한 앞자리 0을 허용하지 않습니다. 네 부분을 숫자로 비교하여 현재 `CARGO_PKG_VERSION`에 `.0`을 붙인 값보다 클 때만 알립니다. 위 1.1.1.0 예시는 현재 1.1.3.0 후보에 알림을 만들지 않습니다. `submissionId`는 앞자리 0이 없는 1~25자리 숫자 문자열입니다. 앱 ID, Store 주소, `Published` 상태, 형식 버전은 고정값과 정확히 일치해야 합니다. Certification·Release·다른 앱 메타데이터는 업데이트 공지로 승격하지 않습니다. 이 메타데이터를 만드는 서버의 Store OAuth 조회는 공개 응답과 분리됩니다.

## 로컬 설정과 경합

설정은 로컬 `opengeul-updates.json`의 `autoCheck`와 `dismissedVersion`에 저장합니다. 새 파일이 없을 때만 기본 ON을 적용하고, 기존 JSON 손상이나 읽기 권한 오류가 있으면 자동 확인을 끕니다. 지연 자동 저장을 비활성화하고 명시적으로 저장한 결과를 확인합니다. 저장 실패 때 변경된 캐시는 이전값으로 되돌립니다. 수동 오류 알림 닫기는 기존에 무시한 버전을 해제하지 않습니다.

네트워크 대기 중 상태 잠금을 유지하지 않습니다. 상태 전이와 알림 발행은 같은 잠금 안에서 처리하므로 OFF·닫기 뒤 낡은 Available 이벤트가 뒤늦게 발행되지 않습니다. OFF로 바뀐 뒤 진행 중이던 자동 요청의 결과는 다시 ON으로 바뀌어도 무시합니다. 설정 변경은 타이머를 깨우며 마지막 실제 요청 시각에서 다음 1시간을 계산합니다.

## 검증 범위

`overlay/store-update-tests`는 앱에 복사하는 동일 Rust 정책·HTTP 모듈을 직접 컴파일합니다. 오프라인 잠금 검사에는 이전/같은/새 버전, 잘못된 공개 메타데이터, 크기 제한, 자동 OFF와 진행 중 요청, 버전별 닫기, 수동 오류·재시도, 동의한 고정 Store 링크, 상태/이벤트 순서, 설정 읽기·저장 실패와 실제 reqwest 로컬 HTTP fixture가 포함됩니다. TLS 버전은 rustls 0.23.45와 호환되는 rustls-webpki 0.103.14로 고정하며 reqwest 0.13.2의 기존 ring 경로를 사용합니다. 관련 rustls 보안 공지는 [GHSA-2mjx-qc3c-rqvc](https://github.com/rustls/rustls/security/advisories/GHSA-2mjx-qc3c-rqvc)입니다.

Linux의 정책·HTTP 검사나 Windows 대상 Cargo 메타데이터 해석만으로 전체 Windows 앱이 검증되었다고 판정하지 않습니다. 완성된 제품의 Windows 빌드, UI, 설치, 실제 배포된 공개 HTTPS endpoint와 Store 제출 검증은 해당 소스에 대한 별도 실제 CI 결과가 필요합니다.
