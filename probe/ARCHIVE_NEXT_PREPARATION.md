# 다음 Store 원본 보관 전송 준비

현재 상태는 **비실행 골격**이다. Source68의 관측 후보는
`b3c8b61d01731dc1e39357034d9c489a3ea829a9` / `38181680763` / attempt 1이며,
이 문서나 테스트가 소스 전체 성공·새 release·Store 패키지 합격을 증명하지 않는다.
실제 계약의 source/Store/archive ID·tag·digest·해시는 모두 `UNSET`이다.

`archive_next.py`의 bounded 전송 어댑터와 등록된 `store-package.yml`의 진단 브랜치
override를 준비했다. workflow job guard의 명시적 `false`로 runner/checkout도 시작하지 않는다.
CLI는 `ROOT_EXECUTION_AUTHORIZED = False`와 `CONTRACT_SHA256 = 'UNSET'`에서
계약 파일 읽기 또는 네트워크 접근 전에 거부한다. 실제 값과 root 허가를 검토하기 전에는
이 guard를 해제할 수 없다. 이번 테스트에서는 실제 Request 객체에 가짜 응답만 주입했다.

## 검토한 동작

- source run/job의 head는 `sourceCommit`, Store run/job/artifact의 head는
  `storeExecutionCommit`에 각각 연결한다. source 전체 SUCCESS, 원래 14개 필수 job과
  cleanup, Store package·verify-api SUCCESS 및 attempt별 완전한 job 목록을 요구한다.
- 실제 immutable Git 객체에서 조상 관계와 완전한 `--no-renames` diff를 검사한다.
  명시 승인된 기존 `website/` 파일의 수정과 정확한 전후 byte SHA만 허용한다.
  `docs/`, rename, 추가·삭제, 변경 목록 누락, 잘못된 조상 관계는 거부한다.
  원래 검증 helper 4개와 Store workflow·화면 캡처 코드의 양쪽 bytes도 고정한다.
- 기존 verifier가 만든 **실제 검증 완료 prepare plan의 원문 SHA**를 반드시 고정한다.
  원래 6개 source 자산 snapshot과 원래 7개 Store 파일의 크기·SHA를 그 plan에 연결한다.
  원본 ZIP digest·inventory·CRC, source/repackage/screenshot provenance와 GUI/runtime
  snapshot도 확인한다. 전체 MSIX·portable·manifest·producer·WASM 검증을 새 골격으로
  대체하지 않는다.
- 고정 source release/tag/snapshot 및 별도 archive draft 신원을 매 업로드 전 다시
  읽는다. 기존 정상 자산은 유지하고 누락된 원본만 공식 uploads 주소에 한 번씩 전송한다.
  source snapshot 변경·충돌·잘못된 서버 digest·모호한 응답이면 즉시 종료한다.
  publish/delete/tag 이동/source 자산 수정/Store API는 호출하지 않는다.
- 공식 `api.github.com`의 고정 metadata 경로와 별도 draft의 `uploads.github.com` 원본
  7개 경로만 허용한다. metadata는 2MiB, ZIP은 고정 크기+1바이트, 요청은 각각 60초로
  제한한다. artifact의 단일 HTTPS Azure Blob redirect만 허용하며 인증·cookie를 보내지
  않는다. 추가 redirect/재시도는 없다. 고정 archive tag GET의 404만 nullable이다.
  예외 문자열·인증 값·서명 URL을 출력하거나 영수증에 넣지 않는다.

## 실제 실행 전 남은 조건

1. Source68 전체 성공을 root가 확인하고 새 source release의 원본 6개 파일을 보존한다.
2. 이후 실제 Store packaging head와 원본 artifact/7개 파일을 독립 검증한다.
   서로 다른 두 head 사이의 website 변경은 완전한 목록과 전후 hash로 별도 승인한다.
3. 새 immutable source의 검증 helper 4개를 고정한 별도 verifier로 전체 runtime parity를
   검증하고 prepare plan·runtime snapshot·provenance의 실제 SHA를 계약에 채운다.
   원래 Source64 verifier/업로더/계약은 수정하거나 새 qualification에 재사용하지 않는다.
4. 별도 draft archive ID와 source tag/target을 root가 확인한 뒤 모든 새 계약 핀과
   정확한 diff를 재검토한다. 현재 테스트의 `9.8.7`, ID 101 등은 가짜 기록에만 있다.
5. 실제 이전 진단 metadata에서 확인한 actor `ATLKR`와 고정 ref/public/manual attempt 1,
   GH_TOKEN==GITHUB_TOKEN guard 및 10분 표준 Ubuntu workflow를 준비했다. root는 실제
   계약과 prepare plan을 검토한 뒤에만 계약 SHA·root 허가·workflow의 `false`를 바꿀 수
   있다. 전체 Git을 받되 submodule/LFS/cache는 사용하지 않는다. 현재 실행 허가는 없다.
6. 업로더가 서버의 원본 7개 digest를 확인해도 draft에서 끝낸다. 공개는 root의 별도
   fresh GET 검증 이후 단계다. 현재 source/archive/publication qualification은 모두 false다.

오프라인 테스트는 작은 합성 ZIP과 실제 임시 Git 저장소를 사용한다. 이는 실제
Windows 바이너리·Store 패키지·스크린샷을 검증했다는 뜻이 아니다.
