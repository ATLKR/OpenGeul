# 글꼴 설치와 이용 안내

OpenGeul은 설치된 Windows 시스템·사용자 글꼴을 사용합니다. Microsoft/한컴/유료 글꼴 파일을 앱에 함께 넣거나 다른 프로그램에서 추출해 공유하지 않습니다. 설치되어 있다는 사실만으로 모든 이용 권리가 확인되는 것은 아닙니다.

앱 메뉴의 **글꼴 도움말**에서 **Noto Sans KR** 또는 **Noto Serif KR**의 공식 페이지를 여세요. 공식 다운로드 ZIP을 풀고 글꼴과 함께 제공되는 라이선스를 보관하세요. .ttf 또는 .otf 파일을 설치하거나 **Windows 글꼴 설정 열기**를 누른 뒤 끌어놓습니다. 회사 정책에 따라 관리자에게 설치를 요청하며 보안 정책을 우회하지 않습니다. 작업 중인 문서를 저장하고 앱을 다시 시작한 뒤 **설치 확인**을 사용하세요. 이 감지는 라이선스 인증이 아닙니다.

공식 페이지:
- https://fonts.google.com/specimen/Noto+Sans+KR
- https://fonts.google.com/specimen/Noto+Serif+KR
- https://github.com/google/fonts/blob/main/ofl/notosanskr/OFL.txt
- https://github.com/google/fonts/blob/main/ofl/notoserifkr/OFL.txt

대체 글꼴의 글자 폭은 원래 문서와 다를 수 있습니다. 줄바꿈·표 높이·쪽 수·출력을 확인하고 원본을 보존하세요. 무료 다운로드와 기업 사용·재배포·PDF 포함 권리는 별도로 확인해야 합니다.

## PDF

SVG 호환 PDF 경로의 가드는 OpenType fsType이 0 또는 8일 때만 하위 집합 포함을 허용합니다. Print/Preview 전용, 하위 집합 금지, 비트맵 전용, 손상·미확인 메타데이터는 보수적으로 막습니다. Print/Preview 글꼴을 모든 경우에 포함하는 것이 불법이라는 뜻이 아니라 이 구현이 해당 조건을 충분히 보장하지 않는다는 뜻입니다. 거절되면 원본을 보존하고 복사본에서 허용된 글꼴로 변경하세요.

이 검사는 완전한 법적 판정이 아닙니다. CLI의 선택적 Skia direct PDF, 기존 문서 내 포함 글꼴, Windows 인쇄/PDF 드라이버는 별도 경로이며 추가 라이선스 검토가 필요합니다. 글꼴 메타데이터 조작이나 글자 윤곽 변환이 권리 문제를 자동 해결한다고 주장하지 않습니다.

근거:
- https://learn.microsoft.com/en-us/typography/fonts/font-faq
- https://learn.microsoft.com/en-us/typography/opentype/spec/os2#fstype
