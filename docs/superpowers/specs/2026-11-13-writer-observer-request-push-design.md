# Owned Writer observer request push

The dedicated Writer diagnostic must execute reviewed code with an authenticated
producer input. It must remain separate from normal Suite acceptance and package
delivery. The current default branch has no `office-suite.yml`; GitHub documents
the default-branch prerequisite for manual dispatch. This preparation does not
claim that a dispatch request has actually failed.

## Approaches

- Keep manual dispatch alone: preserves the existing three-input contract but
  leaves its documented registration prerequisite unresolved.
- Bootstrap the workflow on main: touches the default branch and its existing
  publication path before this diagnostic needs either change.
- Add a request-only push on the existing dedicated branch: uses the same job,
  runner and permissions while independently fixing the reviewed code identity.

The third option is the implementation decision. The manual path remains intact.
No new runner, token, repository variable, permission or main change is required.

## Request and source identity

Let **R** contain the reviewed implementation, this trigger profile and the real,
authenticated 16-field producer input lock. R has no request file. Publish R to
`work/opengeul-office-native-writer-observer-suite-9dea` first. Its ordinary push
must not allocate the diagnostic job or count as diagnostic success.

Then publish **T**, whose only change is addition of the regular `100644` file
`suite/config/writer-server-observer-9dea/run-request.json`. Its exact schema is:

```json
{
  "schemaVersion": 1,
  "kind": "writer-server-observer-run-request",
  "reviewedParentCommit": "<the actual reviewed R>",
  "phaseSeconds": 900
}
```

This example is documentation, not a generated request or approved duration.
`reviewedParentCommit` must be a nonzero lowercase 40-digit Git SHA. The phase is
an explicit JSON integer in `6..1200`; booleans, strings and floats are rejected.
No placeholder producer lock or executable request is created during preparation.

The fixed marker is `[opengeul-writer-observer-9dea-run]`. A message prefix
selects a possible request before ARM allocation; it grants no authority. Final
admission requires the raw Git message to be exactly that marker plus its terminal
LF, and the event message to be the marker with or without that one terminal LF.
Extra body, whitespace or suffix is rejected. Admission must verify the exact public
repository, owner/actor, attempt 1, dedicated ref and workflow ref, then require:

- Actual checkout, `GITHUB_SHA`, workflow SHA, event `after` and head commit are T.
- Event `before` is R; creation, deletion and forced push are all exactly false;
  the complete commit list contains only T.
- The raw T commit has exactly one parent R and the canonical fixed request
  message. Read Git objects with replacement objects disabled; shallow traversal
  is not evidence of parent count. Checkout depth 2 supplies both objects.
- R has no request or case alias. Removing the one canonical new request row
  from T's complete tree leaves R's rows identical, including modes and object
  IDs. Other code, workflow, lock, path or mode changes are rejected.
- Parse only the bounded committed request blob, at most 1024 bytes. Reject duplicate/unknown keys,
  malformed values and aliases before reading an unadmitted filesystem path.
- Run the existing clean tracked-byte verification against T. Graph, request
  and tracked-source work share one original 30-second static admission budget.

T remains the execution and baseline provenance SHA. R is the approval parent;
neither is relabeled as the other. The producer lock, normal ARM baseline, two
DLL identities, ABI 2/IPC 1 and process/window generation checks remain unchanged.

## Phase and evidence

Only fully admitted context emits one fixed step output containing the validated
integer phase. The observation step consumes that output for both entry paths.
Missing, invalid or unwritable output fails before acquisition; there is no
default phase. No event, raw commit message or request body is logged. Existing
closed numeric context/report evidence and false qualification flags are retained.

This outer phase does not alter the runtime's 25-second work/30-second deadline,
retained-handle cleanup, report checks or intentional nonacceptance terminal step.
The input artifact, actual duration adequacy and Windows behavior require fresh
evidence. A source build or an all-skipped registration run cannot qualify a GUI.

## Operational constraints and references

Check same-ref activity before publishing R or T. Wait for R's nonexecuting run
to finish before T so concurrency does not cancel evidence. Keep normal Suite and
engine builds untouched. Do not merge main, publish a release or invoke Store.

[Manual execution prerequisite](https://docs.github.com/actions/managing-workflow-runs/manually-running-a-workflow)
and [push payload limitations](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#push)
explain why this route neither depends on default-branch registration nor uses
the omitted commit file-list attributes.
