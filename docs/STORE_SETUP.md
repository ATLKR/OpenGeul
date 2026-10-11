# Store packaging

Run **Actions → OpenGeul Store package → Run workflow** on `main` and select an
existing release tag.
The known validated release is `v1.1.1-dev.29.1`, from commit
`56ca88331a2fdba47bcc6e7ec27ad433df89fe72` and successful run `37747244144`.

Download `opengeul-store-<run ID>` within one day and upload its
`OpenGeul_1.1.1.0_x64_store-unsigned.msix` in Partner Center. The reserved product
is **OpenGeul**, Store ID **9PJH0T3PHRMF**. Set its price to **Free** in Pricing and
availability. Complete the listing, screenshots, age ratings, declarations and
certification before publishing. Store distribution supplies trusted signing.

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
The workflow generates an artifact; upload, certification and publication take
place in Partner Center.

For future submission API automation, first publish the manual Store submission.
Associate an Entra application with Partner Center and give it the Manager role.
Store its `STORE_CLIENT_SECRET` in GitHub Actions secrets and back it up in Proton
Pass. Record `STORE_APP_ID=9PJH0T3PHRMF`, `STORE_TENANT_ID` and `STORE_CLIENT_ID`
as repository variables. Only the optional API validation job uses these
credentials. Submission upload automation can be added after setup is complete.
The optional `verify_store_api` input runs a separate read-only check: obtain an
OAuth access token and GET the reserved application. It verifies the app identity
without creating, editing, deleting or committing a submission. The token and
secret are never written to files or printed.

API-created submissions must continue to be edited through the API; changing
them in Partner Center can prevent subsequent API changes or commits. Microsoft
CLI `publish --noCommit` leaves a draft but can first delete an existing draft,
so an earlier draft check alone cannot protect concurrent edits.

Sources: [Store submission prerequisites](https://learn.microsoft.com/en-us/windows/uwp/monetize/create-and-manage-submissions-using-windows-store-services),
[Microsoft CLI draft behavior](https://github.com/microsoft/msstore-cli/blob/v0.4.3/MSStore.CLI/Helpers/IStorePackagedAPIExtensions.cs).
