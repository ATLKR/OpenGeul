# 제3자 고지

OpenGeul은 HOP와 rhwp를 기반으로 한 독립적인 다운스트림 배포판입니다. OpenGeul이 새로 작성한 코드의 MIT 라이선스는 업스트림이나 의존성 라이선스를 대체하지 않습니다.

고정한 업스트림:
- HOP 소스: https://github.com/golbin/hop/tree/34bd15c97e0851627cb7f055042c5340198aeb7f
- rhwp 소스: https://github.com/edwardkim/rhwp/tree/1a76570e833917d15817415a53c09ad61ab3203f
- svg2pdf 0.13.0 벤더 패치: https://github.com/edwardkim/rhwp/tree/1a76570e833917d15817415a53c09ad61ab3203f/vendor/svg2pdf (업스트림 출처는 `RHWP_PATCHES.md`)

소스 발췌·파생 통합 코드를 포함한 HOP와 rhwp의 라이선스 원문:

```
MIT License

Copyright (c) 2025-2026 Edward Kim

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

Windows 빌드는 업스트림 LICENSE 파일을 복사하고 의존성 라이선스 원문을 Notices/Dependencies에 수집합니다. 목록은 의도적으로 실제 사용 범위보다 넓으며 사람이 검토해야 합니다. 완전한 SBOM이나 준수 인증이 아닙니다. 정식 지원 릴리스 전에 네이티브·실행 시점·전이 의존성, 생성한 WASM, CanvasKit, Skia, 리소스와 누락된 고지 원문을 확인해야 합니다.

native-Skia CLI는 rust-skia `skia-safe`와 `skia-bindings` 0.153.3을 포함합니다. 정확한 [MIT 라이선스 원문](notices/rust-skia-0.153.3-LICENSE.txt)은 업스트림 커밋 `b7f043e0b1e2a850e702245de811f01df1f6b0ff`에서 가져왔으며 SHA-256은 `4b33ed5b329a3a79eb1243fd91373c68b0ae0b9df7503bfc50d0c5253adf1b9a`입니다. 패키징은 각 crate 고지 디렉터리에 원문을 복사하고 의존성 목록에 출처를 기록합니다. 이 rust-skia 고지는 Google Skia나 다른 의존성 고지를 대체하지 않습니다.

이 저장소와 배포할 앱 내용물에는 글꼴 바이너리를 포함하지 않습니다. 배포자 링크를 제공해도 해당 글꼴의 재이용 허락을 부여하는 것은 아닙니다. 설치된 글꼴은 원래 라이선스를 유지합니다. 상표와 Store 정책은 소스 코드 라이선스와 별개입니다. 향후 LibreOffice 코드를 가져오면 해당 MPL 및 다른 라이선스를 유지합니다. docs/LICENSE_POLICY.md를 참고하세요.

## 제거한 다운스트림 백포트

이전 OpenGeul 소스는 FMsongX2의 HOP PR #101, 커밋 `f9bbe8dc66172a1959af1e388e6c28a5b597c5a6` (https://github.com/golbin/hop/pull/101)의 보조 키 없는 문자 단축키 수정을 적용했고, HOP 이슈 #97에 대응하는 도구 모음 글자 표시 설정을 제공했습니다. 이 기록의 배포판은 rhwp 0.8.7의 결과 기반 단축키 처리와 HOP 0.4.5의 원래 도구 모음 설정을 사용합니다. 중복된 다운스트림 구현은 제거했으며 회귀 검증은 유지합니다. 제한적인 설정 이전이 과거 OpenGeul의 글자 숨김 선택을 HOP의 저장 키로 옮깁니다. PR #101이 병합됐다는 주장은 아닙니다.

이전 OpenGeul 소스는 planet6897의 rhwp PR #6074, 커밋 `c7d3c66398acdb3c093fdea6fef573e14f771a6c` (https://github.com/edwardkim/rhwp/pull/6074)의 마지막 줄 음수 간격 제한을 좁은 범위로 적용했습니다. 이 작업은 PR #6076을 통해 업스트림에 반영됐고 고정한 rhwp 0.8.7 엔진에 포함되어 있습니다. 중복 소스 패치는 제거했으며 합성 네이티브·WASM 형태 회귀 테스트는 유지합니다. 위의 원래 rhwp MIT 고지는 계속 적용됩니다. 모든 HOP 표·인쇄 제보가 해결됐다는 뜻은 아닙니다.
