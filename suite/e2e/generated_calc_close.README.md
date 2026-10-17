# Explicit cleanup of verified generated Calc copies

Calc's conservative close policy always presents Save/Discard/Cancel. Existing
GUI cases that have already proved their generated workbook's saved content can
use the opt-in `generated_calc_close` helper. It is not a fallback for close
failure, arbitrary user documents, unknown prompts or missing save evidence.

After the case's exact durable content check succeeds, replace its usual
`close_document` call for Calc only:

```python
from generated_calc_close import freeze_saved_calc_copy, close_saved_calc_copy

# owned_fixtures is this harness's generated directory. source must be its
# exact OpenGeul-calc.xlsx. expected_cells and saved_sha256 come from the
# case's successful independent OOXML checks before this cleanup boundary.
proof = freeze_saved_calc_copy(suite, owned_fixtures, source,
                               saved_sha256, expected_cells)
close_saved_calc_copy(api, process, hwnd, child, record, proof)
close_home(api, process, record)
```

Do not call `close_document` first: the helper posts the single owned WM_CLOSE.
It checks the same shell and embedded editor, exact native dialog owner/PID/
caption/class, exact Korean prompt text, all three unique enabled buttons and
the Discard button's UIA ancestry. Only then does it physically click Discard
once. The copy's hash and five exact cells are checked before close, again
before that choice, and after the document/editor windows close. Any mismatch
raises; there is no alternate prompt, second close or generic discard path.

The already-saved Calc branches of `windows_smoke`, `startup_smoke`,
`korean_ui_smoke` and `korean_ime_smoke` use this authorization. The separately
maintained `calc_save_smoke` adapter must pass its exact `persisted` hash/cells.
The common GUI close helper rejects Calc without a token before posting a close.
Preserve each case's existing save, native
attachment, independent reopen and post-close semantics checks. Other modules
keep their normal close path. The three-choice pending-input probe keeps its
existing Save/Discard/Cancel choices and single Ctrl+W boundary; this helper must
not be substituted there.

The new-blank Calc case uses a separate strongly bound token:

```python
from generated_calc_close import freeze_generated_blank_calc, close_generated_blank_calc
proof = freeze_generated_blank_calc(suite, api, process, hwnd, child, record)
close_generated_blank_calc(api, process, hwnd, child, record, proof)
```

It requires the actual Popen arguments to be exactly the Suite executable plus
`--module calc`, without a source file or other arguments. It accepts only the
known `new-calc` generated-document case (with no editing verified) or the fixed
startup plan's fresh-new Calc attempts. It retains native shell and engine
process handles, verifies executable paths/creation FILETIMEs, compares the
original Popen HANDLE, and rechecks the same embedded child and generations
before close and before clicking. Its handles are always released after the
decision; it requires the original engine to exit after close. The same exact
owned-dialog checks remain mandatory. A generic fileless window, modified case
kind, wrong source command or changed process generation cannot authorize it.
Do not infer blankness from the clean model flag. These are generated-process
ownership checks; actual Windows success remains a separate qualification.

Portable tests cover authorization, command counts and refusal boundaries.
Actual UI interaction still requires the focused Windows qualification.
