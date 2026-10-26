# One owned Writer mouse ordering experiment

Run40263228700 at8c73b4e failed Writer's original five-second focus gate before
IME observer installation. Focus entered the owned editor at0.422s; capture
remained through4.969s. Both original mouse inputs were accepted by SendInput;
acceptance does not establish delivery. No product correction is supported.

Pinned source bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1,
vcl/win/window/salframe.cxx, ImplHandleMouseMsg reposts buttondown while
mnFocusId is pending and explicitly notes the risk that up arrives first.
An earlier Calc capture trace had recapture before the observed up. That
contradicts this ordering explanation for that sequence, not for this Writer.

## Selected investigation

Reuse the existing native capture observer, with narrowly extended Python
controller module admission, for exactly one fresh
native ARM64 Writer case. Test whether an observed up is followed by a later
down and capture acquisition with no later up before the original deadline.
Do not run the IME compartment probe again or the three-case Calc cohort.
No new native fields, callbacks, observer capacity, stack capture, input,
activation, retries, timing allowances or preparation privileges are added.
The matched-plugin Calc cohort retains its existing selection contract.

The existing owner-push/first-attempt source checks, locked engine, unit/shell,
package, Korean readiness, privacy and fixture gates all precede this case.
The original observer preparation budget and five-second focus budget apply.
Confirmed cleanup of the retained original engine is required even on a
successful focus case. Forceful teardown never means graceful retirement.
All failure and prerequisite receipts retain the existing bounded contract.

## Interpretation and stop

Inspect every publication, rejection, overflow and deadline/cleanup receipt
before interpreting ordering. Hook call/return absence cannot prove that an
ordinary queued message was not dispatched. An untagged observed up is not
uniquely attributed to an injected event. Even a matching ordering sequence
supports the repost hypothesis; it does not prove the internal mnFocusId
branch or justify a product edit without a causal regression and review.

A complete eligible failure without down-after-up contradicts this ordering
hypothesis for that sequence. Nonreproduction, partial/overflow/rejected or
unconfirmed-cleanup evidence is inconclusive. Close after this one case;
no unchanged rerun. No engine rebuild, debugger, console probe, release or
main merge. Both architectures still require full final-code acceptance.

## Implementation and validation

Extend the existing focus runner with a fixed Writer selection of one case;
keep Calc at three. Reject other modules, non-native-ARM64 Writer and private
plugin cohort binding for Writer before preparation. Select ARM64-only focus
mode in CI, retaining x64 unit/shell validation and explicit nonacceptance.
Regression tests cover cardinality, module routing, cleanup failure, rejected
selections, and every workflow prerequisite. Run the full local suite and
independent review before push. This is diagnostic engineering, not an IME fix.
