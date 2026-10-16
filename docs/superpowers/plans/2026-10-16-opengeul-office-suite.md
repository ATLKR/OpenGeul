# OpenGeul Office Suite Implementation Plan

> **For agentic workers:** Use independent worktrees and task-scoped tests; coordinate shared interfaces before integration.

**Goal:** OpenGeul 이름을 가진 실제 Office 편집기들을 공유 런타임과 Windows native Suite 창으로 제공한다.

**Architecture:** 독립 Suite shell과 UNO 작업자가 Office 엔진을 네이티브 자식 창으로 연결한다.
브랜딩·런타임 준비와 패키징은 기존 HWP 릴리스 경로와 분리한다.

**Tech Stack:** C#/.NET 8 Windows Forms, Python 3/pyuno, LibreOffice GUI, JSON, PowerShell, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-16-opengeul-office-suite.md`

## Global Constraints

- 제품군 OpenGeul Office; 모듈 HWP/Writer/Calc/Impress/Draw/Math/Base.
- Office 문서는 Suite 소유 HWND 안에서 편집하며 외부 stock 앱 실행으로 대체하지 않는다.
- 기존 HWP 제품·릴리스 계약·Store 설정은 보존한다.
- 법적 고지·UNO 서비스/필터 ID는 보존하고 사용자 설치/프로필은 수정하지 않는다.
- 공식 배포 입력의 버전·SHA256과 수정 파일·대응 소스를 별도 provenance에 기록한다.
- x64를 먼저 검증하며 ARM64·실제 IME·전체 호환성을 미확인 상태에서 통과로 표현하지 않는다.

## Review Focus

- 리사이즈·작업자 종료 중 다른 문서 창이나 사용자 LibreOffice 프로세스를 조작하지 않는다.
- dirty 문서의 닫기 취소/저장 실패는 문서를 보존한다.
- 공백·한글·특수 문자가 든 로컬 경로는 shell 문자열 해석 없이 전달한다.
- stock 프로필·XML 내부 식별자·라이선스는 브랜딩 치환으로 변형하지 않는다.
- 실패한 변환/저장을 완료로 보고하거나 기존 파일을 무조건 덮어쓰지 않는다.

### Task 1: Suite manifest와 런타임 브랜딩

**Files:** `suite/config/product.json`, `suite/branding/`, `suite/runtime_branding.py`, `suite/tests/test_branding.py`.
**Produces:** manifest schemaVersion=1, modules keyed `hwp,writer,calc,impress,draw,math,base`;
`brand_runtime(source: Path, destination: Path, manifest: dict) -> dict` copies into a fresh directory,
sets OpenGeul product/factory names and isolated profile, preserves legal files and returns a receipt.

- [ ] 테스트를 먼저 작성하고 누락된 브랜딩·원본 불변·기존 출력 거부·license 보존의 실패를 관측한다.
- [ ] 실제 registry/ini/zip 설정을 구조적으로 바꾸고 manifest/receipt를 생성한다.
- [ ] synthetic runtime과 실제 로컬 런타임에서 검증한다. Windows GUI 확인은 별도로 남긴다.
- [ ] 관련 파일만 커밋한다.

### Task 2: 격리된 UNO 작업자와 내장 문서 세션

**Files:** `suite/worker/office_worker.py`, `suite/worker/session.py`, `suite/tests/test_worker.py`.
**Consumes:** manifest modules, runtime `program/soffice.exe` and `program/python.exe`.
**Produces:** JSON Lines request `{id,command,args}` and response `{id,ok,result}` / `{id,ok:false,error}`.
Commands: `attach` (parentHwnd,module,width,height,path?), `resize`, `status` (modified,title),
`save` (path?,filter?), `close` (discard false unless shell explicitly chose discard), `shutdown`.
Worker startup CLI: `--runtime PATH`; stdin/stdout carry protocol only. Attach creates an owned
office process/profile/pipe and UNO Frame under the supplied HWND. No TCP UNO endpoint.

- [ ] パーサ/状態遷移/close cancel/save failure/ローカルパスとfilter allowlist testsを先に失敗させる。
- [ ] UNO importsを遅延し実際のWindows frame、private process、owned cleanupを実装する。
- [ ] real local engine editing proofとWindows-only child frame proofを区別して記録する。
- [ ] 関連ファイルだけをコミットする。

### Task 3: OpenGeul native Suite shell

**Files:** `suite/shell/*.cs`, `suite/shell/OpenGeul.Office.csproj`, shell tests.
**Consumes:** manifest; layout `Office/` runtime, `worker/` files, optional `HWP/OpenGeul.exe`.
**Produces:** `OpenGeul.Office.exe`; home module tiles/open dialog, Office forms with native Panel HWND,
worker JSON protocol, resize synchronization, close save/discard/cancel and worker errors.

- [ ] module routingとclose decisionsのテストを先に失敗させる。
- [ ] thin Windows shellを実装する。文書操作はworkerに委ねる。
- [ ] .NET Windows cross buildと可能なheadless testsを実行する。
- [ ] 関連ファイルだけをコミットする。

### Task 4: 固定入力・Windows検証・開発パッケージ

**Files:** `suite/config/runtime.lock.json`, `suite/scripts/`, `suite/e2e/`, Suite workflow,
Suite docs and `docs/VERIFICATION.md` with explicit development status.
**Consumes:** Tasks 1–3, official runtime + optional verified existing HWP component.

- [ ] payload検証の欠落・改変・混在architecture・source/license欠落を失敗させる。
- [ ] fresh-path extraction/build/branding/inventory/zipとsource bundleを実装する。
- [ ] Windows x64で実際のowned child HWNDとWriter/Calc/Impress入力・保存・再開を検証する。
- [ ] 既存HWPのpolicy/単体検査を実行し、全差分の独立レビューを受ける。
- [ ] 確認済み成果物と未完のGUI/IME/ARM64/公開配布項目を区別して報告する。
