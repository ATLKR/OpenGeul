# Base save-transition repair

Run 40247444167 at 967b47c failed paired acceptance. ARM64 Base pass one
rejected a successful menu receipt: start 4095.546, deadline 4100.546,
whose floating-point subtraction exceeds five by approximately 4.55e-13.
Replay now compares the original constructed deadline to start + 5. No
margin is added; the next representable value above that bound is rejected.

Base pass two observed a live original dialog followed by a zero native
class query after one input. The product trace reached save completion.
That trace alone does not prove exactly when the dialog disappeared.
The supported repair recognizes only a typed zero-class-query failure on
that original dialog, then requires a fresh bounded IsWindow false, the
original process generation and document, and the unchanged deadline.
A still-live dialog, a changed process or an expired deadline remains fatal.
There is no extra click, activation attempt, generic exception suppression
or delay. Later model/save assertions still determine product success.

Regression validation reproduced both pre-fix failures. All 103 focused
tests passed after the corrections. Independent review found no blocker.
The frozen full suite passed 2643 tests with 13 skips in 276.363 seconds;
all 857 recorded source/test/workflow inputs retained identical hashes.
These local results do not establish native Base or Office acceptance.

The preceding exact run passed both x64 GUI runs and x64 Korean IME but
failed lifecycle M input and final archive qualification. ARM64 also failed
Calc close choices, IME, both GUI runs and final archive qualification.
Those input/focus failures are not repaired by this change. Native validation
must retain all existing acceptance gates and cannot claim a causal IME fix
from a later nonreproduction. No console experiment or engine rebuild is added.
