# Calc uncommitted-input close probe

This separate GUI probe measures current behavior. It does not change product
close code or the existing Ctrl+S/explicit-Enter cases.

```powershell
python suite/e2e/calc_close_probe.py --suite .work/suite --fixtures .work/engine/fixtures --output .work/calc-close-probe
```

Use a fresh passing `engine_smoke.py` fixture set. The original source XLSX must
still match its engine baseline SHA256. The probe edits three separate owned
copies and attempts every case even if earlier cases fail. Evidence must be in a
new local directory outside the Suite payload and input fixture tree.

Each case physically sends Ctrl+Home, F2, Ctrl+End and a distinct ASCII suffix.
It sends no Enter. A bounded getter-only observer must then prove A1 still equals
the original clean model, with B1=17, C1=25 and D1=`SUM(B1:C1)`=42. The observer
must fully exit before one physical Ctrl+W. There is no intervening focus action,
input acceptance, model setter or completion barrier. Read-only focus checks do
not move focus.

The existing Suite-owned Calc prompt must offer all three exact Save, Discard
and Cancel buttons. Native owner/PID, caption, UIA ancestry and live native roots
are checked through the existing lifecycle helpers before clicking a choice.
An absent, foreign or unexpected prompt fails; it is not dismissed or replaced.

- **Save:** close normally, then require the exact original A1 plus marker and
  unchanged neighboring values/formula in saved OOXML and a fresh read-only
  packaged-engine reopen.
- **Discard:** close normally and preserve the copied workbook bytes exactly.
  A fresh read-only packaged-engine reopen must retain the original values.
- **Cancel:** preserve the original native window/process generations and URL,
  and prove the workbook bytes are unchanged. A second getter-only observer must
  find the full typed marker in A1 and a dirty model, with neighboring values and
  formula intact. No later Save is used to manufacture this proof. Cleanup then
  requests an owned close and explicitly chooses Discard; the copied file must
  remain byte-for-byte unchanged through cleanup and a read-only fresh reopen.
  If the marker remains only in an unreadable edit buffer after cancellation,
  retention is unproved and the case fails; that alone does not establish loss.


`results.json` requires all three cases exactly once and every outcome proof.
Per-case JSON, screenshots, original pending-model observations, observer
cleanup, close trace rows and independent reopen records survive failures.
Only the test's launched processes and generated copies are eligible for failure
cleanup. A failure record can distinguish an editor that closed before the
expected prompt from a shortcut that left it open; neither is silently repaired.

The source finding is conditional. In pinned LibreOffice 26.8.1.1,
`XCloseable.close()` can invoke Calc view `PrepareClose(false)`, which may accept
an existing input buffer after Suite has checked the model modification flag.
That path does not itself show the document save-choice prompt. Actual Ctrl+W
or focus handling may commit earlier and protect the document; this probe must
establish reachability before a broader close change. This is not evidence that
a historical run lost data.

Relevant pinned source:

- [Controller close listener calls view PrepareClose(false)](https://github.com/LibreOffice/core/blob/bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1/sfx2/source/view/sfxbasecontroller.cxx#L331-L342).
- [Calc view accepts current input during PrepareClose](https://github.com/LibreOffice/core/blob/bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1/sc/source/ui/view/tabvwsh4.cxx#L293-L328).
- [Model close proceeds through listeners to disposal](https://github.com/LibreOffice/core/blob/bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1/sfx2/source/doc/sfxbasemodel.cxx#L1490-L1548).

Portable unit checks validate these probe oracles. They provide no Windows GUI
result, no IME coverage and no universal asynchronous formula/validation proof.

The pending-input setup now requires a read-only A1 selection receipt after
Ctrl+Home, then the exact original text and full typed marker from the same
temporary in-cell accessibility editor. The model must still contain the
original A1 value with `isModified == false`. The observer uses LibreOffice
26.8.1.1's explicitly removable `XVclWindowPeer.XAccessible` test property;
this is an E2E-only receipt, not a production pending-input API. Missing or
ambiguous editors, foreign paths, changed identities, and text mismatches fail
before Ctrl+W. The unsafe formula-bar UI-test text getter is never called.
