# Physical Home routing checks

`e2e/home_routing_smoke.py` adds a finite native Windows check beside the existing
thirteen GUI cases. It launches a fresh, argument-free owned Suite Home for each
case and exercises these 25 paths once:

* Six physical Office tile clicks: Writer, Calc, Impress, Draw, Math and Base.
* Home File Open followed by physical Escape, preserving the same empty Home.
* Home File Open for all seventeen supported extensions: HWP, HWPX, ODT, DOCX,
  DOC, RTF, TXT, ODS, XLSX, XLS, CSV, ODP, PPTX, PPT, ODG, ODF and ODB.
* Writer document File → Open to a second Impress document, then the second
  document's physical File → Close. The original Writer remains alive and keeps
  its exact body, URL, native generation and private profile identity.

Existing lifecycle coverage already physically invokes Writer File → New. This
addition preserves that baseline and does not repeat the same shared callback
for every module.

## Inputs and invocation

```powershell
python suite/e2e/home_fixture_inputs.py --suite <package> --output .work/e2e-fixtures
python suite/e2e/home_routing_smoke.py --suite <package> `
  --features .work/suite-office-features --hwp-fixtures .work/e2e-fixtures `
  --output .work/suite-home-routing
```

All twenty-one canonical feature cases must have passed against the same Suite.
The harness independently replays their observations and cleanup evidence and
rehashes the exact fifteen format fixtures before admitting fresh owned copies.
The separate reviewed fixture helper generates controlled HWPX, uses the current
inventory-bound packaged `rhwp.exe` to create genuine binary HWP and independently
reopens it to HWPX. Its bounded command outputs, exact markers and provenance are
replayed before and after the Home cases. External documents, renamed formats,
linked paths and overwrites are rejected.

## Native actions and ownership

Home buttons are selected through a raw bounded UIA census, exact accessible
names, one live native child and the original Home foreground. Each is physically
clicked once. The native Open dialog always belongs to the original Home HWND,
including when its callback came from a document's menu.

Open readiness reuses the strict Base collector with an explicit opt-in mode.
It keeps the original twenty-second absolute budget, raw FindAll/HRESULT evidence,
native continuity and exact filename Edit1001/Open Button1 bindings. The original
Base mode is unchanged. Only a ready owned picker receives the existing single
native filename Edit transaction; exact UIA/native readback is mandatory before
the one physical Open click. Cancel uses one physical Escape after the same
ownership/readiness gate. These filename messages do not edit document content.

New Office attachments must be the unique new HWND relative to every earlier
retained document. Parent/editor ancestry, separate Office PID and absence of
visible external Office windows are checked. The shared Open case retains two
separate documents; it never selects the first matching caption. Its File Close
action is not followed by another WM_CLOSE.

## Calc and shutdown admission

`e2e/home_calc_close.py` has a separate Home-only authorization. The original CLI
blank token and XLSX saved-copy token remain unchanged. A fresh physical Calc tile
requires empty A1, zero B1/C1/D1 and an empty formula. Generated ODS/XLSX/XLS require
the exact baseline marker, values 17/25/42 and `=SUM(B1:C1)`; CSV requires its stored
value `42`, matching the explicit formula-loss budget. All require `isModified`
to be exactly false before closing.

The one existing-frame getter uses the already-supported fixed Calc contract.
The original Popen HANDLE, retained Office HANDLE/generation, selected source
case, feature report, original/copy hashes, raw filename receipt and private
reader cleanup remain bound to the token. After one WM_CLOSE the harness accepts
either a clean close or the exact same-process, document-owned three-choice prompt
and one physical Discard. Foreign, duplicate, stale, late or uncertain surfaces
fail without another input. The shared Writer getters use the existing fixed
read-only Writer contract and the same owned-reader lifetime checks.

All Office and HWP processes are observed through retained native HANDLEs until
signaled. A separate actual GetExitCodeProcess call must return zero; actual
CloseHandle results are retained. HWP routing also requires the precise-clock
owned child census, expected filename, WebView and post-load editor/toolbar.
Forced cleanup is recorded as failure and cannot qualify a case.

## Results and limits

`home-routing.json` preserves all twenty-five records, including failures.
`<case>-result.json`, stderr, screenshots, picker evidence, readonly-reader
receipts, HWP readiness JSONL and fresh fixtures remain under the output root.
Product native archives are isolated under `diagnostics/<case>/<archive>/`.
`native-integrity.json` independently validates every manifest member hash and
manifest-hashed product shutdown receipt, then joins each of the twenty-three
Office engines by PID, creation FILETIME and exact packaged image. Every private
job must end empty with normal zero exits and actual released resources. Missing,
incomplete, extra, forced or corrupt archives and crash dumps fail admission.
The product's raw `events.jsonl` is retained separately from its manifest file list.

The CLI exits zero only when every fixed case and the independent native gate
pass. Cases continue once after an earlier failure. This is a bounded routing and
owned cleanup check, not certification of arbitrary Office features, HWP/Word
conversion fidelity or every rendered pixel. Native attachment screenshots may
precede a complete repaint; structural and readonly observations provide the
stated gates. Local synthetic tests exercise source contracts and do not establish
successful Windows execution. Original keyboard-loss causes remain unresolved by
this addition.
