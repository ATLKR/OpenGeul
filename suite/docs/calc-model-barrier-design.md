# Read-only Calc model completion before the original save

This acceptance-harness change observes whether the original physical Calc edit
reached the same owned document model. It does not establish the cause of run
38988336192, repair input, or establish a product fix. That original run remains
failed; a new complete Windows run is required.

## Independent input and unchanged actions

`windows_smoke.document_case` reads the verified engine fixture once before
launch, writes those exact bytes exclusively to `calc-model-baseline.xlsx` in the
fresh case output, and retains their SHA-256 and size immediately. The snapshot
is outside the payload and generated fixture directory. A downstream auditor
must compare it to the independent engine baseline receipt, parse it afresh with
`baseline_from_ooxml(bytes)`, and pass that baseline to portable replay. Producer
observations and expectation JSON are not trusted baseline or inventory inputs.

The parser resolves the first `workbook.xml` sheet through its exact workbook
relationship; it does not assume `sheet1.xml`. It rejects external/escaped or
ambiguous relationships, duplicate package members, unexpected serialized cells,
wrong numeric/formula types and oversized input. A1 is preserved exactly. B1=17,
C1=25 and D1's formula `=SUM(B1:C1)` with cached value 42 are required.

After the original focus preparation, one reader starts before the original
`Ctrl+Home`, `F2`, `Ctrl+End` navigation. Its first observation must equal the
independent baseline and have `isModified=False`. The original 0.04-second ASCII
input, Enter and Ctrl+S remain single attempts, in that order. No input is
resent, no commit action is added, and no observer changes focus.

## Explicit getter and ownership contract

`OwnedModelReader(..., expected_service=SERVICE, getter_contract=GETTERS)` uses
the exact caller-selected pair:

- `SERVICE = com.sun.star.sheet.SpreadsheetDocument`
- `GETTERS = calc-a1-b1-c1-d1-v1`

Its fixed getters read sheet index zero, A1 `getString`, B1/C1 `getValue`, D1
`getFormula`/`getValue`, and document `isModified`. Active cell/current selection
is irrelevant because the original Enter can select A2. `calculateAll`, model
setters, dispatch, opening, saving, closing and focus changes are excluded.

The shared reader retains the original launched shell generation, owned editor
HWND/PID/creation time, private pipe, native profile DIRECTORY HANDLE/FileID,
same frame/controller/model proxy links, actual helper generation/private job,
and seven-role packaged Python identity. The caller selects the allowlisted
contract; a receipt cannot select its own service or operations. Existing Writer
public APIs, default observations and pure replay contracts remain unchanged.

Calc observations use `kind=existing-owned-calc-cells` and typed fields
`sheetIndex`, `a1Text`, `b1Value`, `c1Value`, `d1Formula`, `d1Value`, `isModified`,
alongside the original raw ownership/launch/profile/Python evidence. Bool is not
a numeric cell; nonfinite values fail. Exact A1 comparison performs no trimming,
case conversion, newline conversion or Unicode normalization.

## Completion and cleanup

After the original Enter, `calc_model_barrier` accepts pending only when A1 is a
monotonic exact ordered prefix of `baseline A1 + UI-OpenGeul-calc`, preserving the
entire baseline. Every read must preserve B1, C1, D1 and all identity/Python/time
invariants. A mismatch, regression or getter error fails immediately. Full exact
A1 equality also requires `isModified=True`.

One immutable 12-second deadline begins before reader startup and includes
navigation, original input, Enter, all reads and normal cleanup. At most 120
model reads are permitted including the initial baseline read. Equality alone
does not authorize Ctrl+S: the same observer must release its proxies and all
owned native handles, every private-job member must exit normally, and the job
must be empty within that same deadline. Forced helper cleanup remains failure.
Only after mandatory portable replay accepts this sealed completion does the
original Ctrl+S execute. Existing saved XML/hash/title, post-GUI UNO, native
ownership and normal document/home close gates remain mandatory.

If the original later save or close fails, the outer GUI case remains failed;
the already sealed model-completion receipt is preserved so the next audit can
distinguish a completed model boundary from a failed persistence boundary.

## Pure replay and evidence

`replay_completion(receipt, *, suite_root, inventory, inventory_sha256, binding,
baseline, expected_url, marker='UI-OpenGeul-calc')` requires caller-supplied trust
anchors and performs no filesystem, native or UNO work. It reconstructs the
expectation, replays exact ordered reads, validates normal same-reader cleanup,
and returns `kind=calc-model-case-replay`, one edit, read count, exact expected
A1 and a native generation/profile descriptor for independent archive joins.

The GUI record retains `calcModelBaseline`, singular `calcModelCompletion`,
`calcModelCompletionReplay` and `calcModelCompletionVerified`. Startup, read,
timeout, cleanup and evidence-write failures retain their original error and raw
attempted evidence. `originalPhysicalAsciiLossCauseEstablished` and
`productFixEstablished` remain false.

Portable tests exercise real policy with synthetic typed receipts, exact XML
baseline parsing, prefix corruption, wrong controls/service/generation/Python,
normal-cleanup failures and trusted replay anchors. GUI orchestration tests
replace only physical boundaries and the observer context to prove the original
single input/Enter/save sequence, prelaunch baseline capture, cleanup-before-save
ordering, first-error retention and later-save-failure classification. These
tests cannot establish actual Windows acceptance.
