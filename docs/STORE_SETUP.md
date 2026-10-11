# Store packaging

Run **Actions → OpenGeul Store package → Run workflow** on `main` and select an
existing release tag that contains the current runtime and notice fixes and has
passed its full source workflow. Older releases do not gain these fixes through
Store repackaging.

Download `opengeul-store-<run ID>` within one day and upload its
`OpenGeul_<version>_x64_store-unsigned.msix` in Partner Center. The reserved product
is **OpenGeul**, Store ID **9PJH0T3PHRMF**. Set its price to **Free** in Pricing and
availability. Complete the listing, screenshots, age ratings, declarations and
certification before publishing. Store distribution supplies trusted signing.

Declare Korean as the package's supported UI language. An English Store listing
may explain that the interface is Korean. Put the Microsoft Edge WebView2 Runtime
requirement in the first sentence of each listing. Disclose that Direct Save of
encrypted documents is blocked, Save As requires explicit consent to create an
unencrypted file, and autosave/recovery is not provided. Recommend a separate
output path to preserve the protected original.
Use support email [allenlim@allenlim.net](mailto:allenlim@allenlim.net) and product
website [opengeul.allenlim.net](https://opengeul.allenlim.net).

Before replacing a Store package, inspect the new source run's `msix-install`
artifact. `installed-launch.json` must identify the candidate package and CLI
help must come from its installed directory. Review `wack.json` and `wack.xml`:
an unavailable kit is explicitly unverified, and an available kit's failure or
incomplete/mismatched report blocks the source installation gate. WACK passing
does not establish Partner Center certification.

The workflow verifies the original release checksums, full MSIX/portable parity,
tag/source/run identity, and every required source release gate. It changes the
manifest to the actual Partner Center identity, uses Windows SDK MakeAppx, and
compares every executable, DLL, resource and notice against the original MSIX.
The output includes original source provenance, Store repackage provenance and
SHA-256 checksums. It does not recompile the application or certify it for Store.
The same artifact also includes `OpenGeul-editor.png`, a screenshot of the actual
native Windows editor with synthetic text, and `screenshot-provenance.json`.
Capture uses the unchanged packaged executable and existing Windows GUI tools;
it does not fabricate the UI or resize an existing image.

Packaging and the first manual upload need no signing secret or API key.
The manual workflow defaults to artifact-only packaging, so development tags can
still supply the first reviewed Partner Center upload. The Store publisher display
name is **Allen Taewon Lim**; the reserved package Name and Publisher CN stay fixed.

## Automatic stable updates

Push a canonical tag such as `v1.1.2` that matches `config/product.json`. Its full
source workflow must pass every release gate. The release job preserves or creates
the GitHub release and explicitly dispatches the Store workflow on `main`. The
child waits at most ten minutes for source completion and independently verifies
tag, commit, run, checksums and unchanged runtime before packaging. This dispatch
is required because release/tag events created by `GITHUB_TOKEN` do not normally
start another workflow. Development tags and main pushes do not request Store
certification. Manual `submit_to_store` also requires a validated stable tag-push
source; its default is false.

The automatic submitter requires a verified published baseline before deleting
any pending submission. Initial-submission replacement needs a separately
established supported path; this guard does not authorize publishing an older
package to create a baseline. The submitter preserves the
baseline listings, age ratings and Free pricing, including regional overrides.
`NotAvailable` market overrides are preserved as unavailable; they are not
converted to Free or Base. Paid or unknown override values still block submission.
Unsupported or paid pricing blocks replacement. A first-publication warning
leaves the original submission, GitHub release and new package artifact intact.

The Entra application needs Partner Center Manager access. Keep its
`STORE_CLIENT_SECRET` in GitHub Actions secrets and back it up in Proton Pass.
Set repository variables `STORE_APP_ID=9PJH0T3PHRMF`, `STORE_TENANT_ID` and
`STORE_CLIENT_ID`. The submission step receives these credentials after the
verified package and native screenshot artifact have been saved. The optional
`verify_store_api` job obtains an OAuth token and GETs the fixed application;
it does not change Store state. Tokens, secrets and signed upload URLs are never
printed or included in artifacts or Issues.

All Store workflows for this app use one concurrency group, without canceling a
running transaction. They reject older queued versions using numeric comparisons
and fresh Store state. A matching submission already processing is reused. To
replace a different pending submission, the submitter records the exact ID,
requires an empty-body successful DELETE response, then confirms no pending
submission remains and the deleted ID is unreadable. A refusal, 404, timeout,
unknown acknowledgment or conflicting submission stops replacement. The new
submission is created only after those checks succeed.
The metadata acknowledgment and fresh draft readback must match the intended
package filenames, upload/delete states and minimum requirements before commit.

A single GitHub Issue journals attempted and confirmed writes across tags.
An unresolved deletion or creation attempt blocks later candidates too. A commit
response lost in transit is reconciled by GET of the recorded submission; commit
is not blindly retried. Failures open/update the Issue, mention `@ATLKR`, and fail
the Actions step while keeping the release and package. Email delivery follows
your GitHub Issue and Actions notification settings. Inspect the Issue and Partner
Center to reconcile an uncertain operation before changing its recorded state.

The pipeline uploads a ZIP containing the verified Store MSIX and requests
certification. Its success means Store ingestion accepted the request, not that
Microsoft certified or published the app. Package artifacts expire after one day.

API-created submissions must continue to be edited through the API; changing
them in Partner Center can prevent subsequent API changes or commits. Microsoft
CLI `publish --noCommit` leaves a draft but can first delete an existing draft,
so an earlier draft check alone cannot protect concurrent edits.

Sources: [Submission creation and upload](https://learn.microsoft.com/en-us/windows/uwp/monetize/manage-app-submissions),
[Deletion contract](https://learn.microsoft.com/en-us/windows/uwp/monetize/delete-an-app-submission),
[First publication](https://learn.microsoft.com/en-us/windows/apps/publish/msstore-dev-cli/overview),
[Workflow dispatch](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow),
[Store submission prerequisites](https://learn.microsoft.com/en-us/windows/uwp/monetize/create-and-manage-submissions-using-windows-store-services),
[Microsoft CLI draft behavior](https://github.com/microsoft/msstore-cli/blob/v0.4.3/MSStore.CLI/Helpers/IStorePackagedAPIExtensions.cs).
