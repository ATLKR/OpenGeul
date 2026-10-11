# 라이선스 정책

OpenGeul이 작성한 코드는 MIT입니다. MIT 고지를 유지하면 상업적 이용, 수정과 재배포가 가능합니다. 기존 HOP와 rhwp의 저작권 고지는 유지합니다. 루트 MIT 라이선스는 다른 사람이 작성한 코드, 글꼴, 로고, 문서나 바이너리의 라이선스를 변경하지 않습니다.

이 프로젝트 정책은 향후 LibreOffice 연동을 명시적으로 허용하지만, 가져온 구성요소의 라이선스를 따라야 합니다. 가져온 MPL-2.0 소스와 수정본은 MPL-2.0을 유지하고, 필요한 경우 대응 소스를 제공해야 합니다. 다른 LibreOffice 구성요소와 의존성에는 추가 또는 다른 라이선스가 적용될 수 있습니다. 엔진·어댑터 경계를 우선하고 구성요소 출처, 변경 불가능한 리비전, 라이선스와 수정 내용을 기록합니다. 저장소가 MIT라는 이유로 LibreOffice에서 파생된 파일이 MIT라고 주장하지 않습니다.

현재 릴리스에는 LibreOffice, DOCX/XLSX/PPTX 엔진이나 Microsoft/Hancom Office 바이너리가 없습니다. 소프트웨어 라이선스는 일반적인 사용자 작성 문서의 소유권을 결정하지 않습니다.

의존성 목록은 실제 사용 범위보다 넓으며 법적 이용 허락을 확인한 결과가 아닙니다. 정식 지원 릴리스 전에 누락된 라이선스 원문과 선택적인 네이티브 Skia 의존성을 검토해야 합니다. 제3자 글꼴 프로그램은 배포하지 않습니다. 설치된 글꼴의 사용 권한과 PDF 포함 권한은 별개입니다.

함께 배포하는 `native-skia` CLI는 rust-skia `skia-safe`와 `skia-bindings` 0.153.3을 사용합니다. 각 Cargo 고지 디렉터리에 넣는 MIT 고지는 정확한 [0.153.3 소스 커밋](https://github.com/rust-skia/rust-skia/tree/b7f043e0b1e2a850e702245de811f01df1f6b0ff)에서 복사합니다. 수집기는 해당 커밋, 소스 URL과 SHA-256을 `inventory.json`에 기록합니다. 고지 누락, 바이트 변경, 실행 시점 메타데이터 누락이나 검토되지 않은 버전·라이선스는 거부합니다. 실제 사용 범위보다 넓게 수집한 다른 빌드·개발 기록의 누락 원문은 여전히 검토 대상입니다.

주요 참고 자료:
- https://www.libreoffice.org/licenses/
- https://www.mozilla.org/en-US/MPL/2.0/FAQ/
- https://learn.microsoft.com/en-us/typography/fonts/font-faq
