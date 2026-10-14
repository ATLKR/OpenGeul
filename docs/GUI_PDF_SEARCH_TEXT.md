# GUI PDF 검색 텍스트의 좌표 보존

GUI PDF는 `export_core_to_pdf` → `searchable_pdf_from_svg_pages` → rhwp의 SVG 호환 PDF 변환을 사용합니다. Windows 인쇄 경로와는 별개입니다. Source 107의 실제 Windows 2022·2025 GUI 산출물에서 PDFium은 한글과 일부 넓은 글자를 읽었지만 보이는 라틴 문자·숫자 대부분을 검색 텍스트에서 누락했습니다. ToUnicode와 글꼴 하위 집합은 온전했고 다른 PDF 판독기는 전체 텍스트를 추출했습니다.

원인은 `svg2pdf::to_chunk`의 1×1 Form 정규화였습니다. 예를 들어 A4 SVG의 Form Matrix는 약 `[1/793.7, 0, 0, 1/1122.5, 0, 0]`이고 rhwp는 페이지에서 다시 `[595.28, 0, 0, 841.86, 0, 0]`으로 확대했습니다. PDFium의 텍스트 수집기는 바깥쪽 확대를 적용하기 전에 Form 내부 폭이 0.01 이하인 글자 객체를 제거합니다. 따라서 래스터는 완전해도 검색·복사가 불완전했습니다.

`scripts/pdf_search_text.py`는 svg2pdf에 `to_chunk_with_svg_size`를 추가합니다. 페이지 루트 Form은 원래 SVG BBox와 identity Matrix를 유지하고 rhwp는 96 DPI에서 72 pt로 바꾸는 0.75 배율만 적용합니다. 최종 페이지 크기·도형·클리핑·글꼴 하위 집합·ToUnicode는 같은 좌표를 갖습니다. 기존 `to_chunk`의 1×1 계약과 중첩 SVG 그림은 계속 기존 함수를 사용합니다. 설치된 글꼴의 포함 권한 검사와 직접 Skia PDF 제한도 유지합니다.

준비 함수는 기존 PDF 가드를 적용해 LF로 기록한 뒤 호출합니다. 패처는 읽은 원문의 바이트 해시, 원래 라이선스·NOTICE의 바이트 해시, 검토한 출력의 고정 해시를 첫 쓰기 전에 검사합니다. 출력 소스도 LF로 기록하며 CRLF·CR 바이트 변경을 원문과 같다고 취급하지 않습니다. 배포 ledger의 `pdfSearchText` 증명은 helper 해시, 원문·출력 해시, 보존 라이선스 해시를 포함합니다. Source capture와 컴포넌트 join은 이 증명과 실제 소스 목록을 함께 검사합니다. 바꾼 출력과 ledger를 함께 다시 해시해도 검토한 출력 해시와 다르면 거부합니다.

`opengeul_pdf_policy`의 회귀는 업스트림의 원래 MIT `RHWPExactKerningSmoke.ttf`를 사용합니다. 메모리에서 포함 권한만 허용 값으로 바꾸고 작은 `AHTVWAHTVW` 글자를 개별 배치한 두 페이지를 실제 공개 PDF 변환 함수로 생성합니다. 정규화된 루트 Form이면 실패하고, 원래 SVG 단위의 Form과 0.75 페이지 배율·페이지 크기를 확인합니다. 글꼴 바이너리나 의존성을 추가하지 않습니다. 전체 네이티브 대상은 다음 명령으로 실행합니다.

```text
cargo test --locked --package rhwp --test opengeul_pdf_policy --features native-skia
```

원인 실험에서는 두 Windows 호스트의 원래 basic·cancel·two-page PDF를 별도 임시 사본에서 같은 좌표 변환으로 바꿨습니다. PDFium은 여덟 페이지의 전체 텍스트를 다시 읽었고 래스터는 1배·GUI oracle의 3배 모두 픽셀 차이 0이었습니다. 원래 실패 산출물과 exact marker oracle는 보존합니다. 이 실험은 새 Windows 실행의 대체 증명이 아니며, 새 Source·tag 실행에서도 실제 GUI PDF의 정확한 마커와 그림·표를 검증해야 합니다.

새로 컴파일한 변환기의 동일 글꼴·옵션·페이지 합성 자료는 별도로 비교했습니다. 기존 정규화 API는 이전 변환기와 픽셀 차이 0으로 누락을 재현했고, 새 API와 독립적인 identity Form·0.75 변환 사본은 서로 일치하며 전체 글자를 복구했습니다. 정규화 출력과 새 출력 사이에는 1배에서 가장자리 82픽셀, 3배의 4,455,000픽셀 중 228픽셀의 래스터 차이가 있으며 최대 채널 차이는 69입니다. 실제 글자 경계의 최대 차이는 0.000013768672943115234 pt이고 페이지 크기는 동일합니다. 역수 행렬의 부동소수점 반올림과 가장자리 처리의 차이를 기록하며 새 출력 전체에 픽셀 동일성을 주장하지 않습니다. 새 네이티브 기본 기능 빌드의 SVG PDF 정책 검사 7개와 공개 변환 함수의 두 페이지 텍스트는 통과했고, 실제 Windows GUI의 새 출력·3배 렌더 검증과 native-Skia 정책 대상은 전체 Source·tag 실행에서 확인해야 합니다.
