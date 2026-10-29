# Writer OS accessibility numeric failure evidence

The paired Windows acceptance gate reaches Writer OS accessibility after the
original VCL and Korean tab checks. Its numeric notice currently identifies only
the coarse OS stage. The already completed, closed OS probe contains HRESULTs,
roles, interface support, and cleanup counters that distinguish those failures.

## Approach

Project that existing result into one fixed numeric vector on kind 1 schema 9.
Reusing the completed result avoids another native observation. Downloading a
broader evidence archive would expose unnecessary content; repeating the OS probe
could change timing and would not describe the original failure.

The vector contains every existing numeric OS result field except schemaVersion,
in the declared order of the pure summary module. Do not add measurements. Require
the exact Writer Korean UI case, scope 4, matching module/architecture, failed OS
stage, original parent failure source and frames, and matching positive retained
engine PID, creation time, and child HWND. Preserve the existing result's type,
range, reference/VARIANT balance constraints. Reject extra keys and booleans.

Keep legacy schemas 1 through 8 and all identifiers unchanged. Schema 9 must stay
within the existing 2048-byte case notice limit and opt-in/context envelope. A bad
or mismatched optional projection falls back to the original case notice; it must
not change the primary error, acceptance result, cleanup, process lifetime proof,
or emission count. Process reference release is not process death evidence.

The existing 45-second OS child watchdog, ownership checks, COM calls, VCL checks,
focus/input actions, and deployment isolation remain unchanged. Do not collect
accessibility names, values, document content, input text, paths, or raw errors.
This diagnostic does not qualify a product package or certify a screen reader.

## Verification

Exercise actual producer-to-decoder round trips for both architectures, distinct
root HRESULT/reference/role failures, all fixed numeric bounds, context and owner
rejection, malformed/extra data, legacy schemas, and maximum message size. Run
the configured Linux suite and independently review the final source. Freeze a
decoder from the committed source and collect a new normal Windows acceptance
run only after checking that no matching run is active.
