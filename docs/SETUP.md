# CI/CD setup

Canonical repository: ATLKR/OpenGeul. Standard hosted Windows/Linux runners only; no paid larger runners. Public standard runner execution is free under current GitHub policy; execution/concurrency/storage limits still apply. Artifacts expire after three days; prerelease assets remain until removed.

No signing secrets are required. Settings → Actions must allow the pinned GitHub actions. Default token permissions can remain read-only; only the release job requests contents:write. Pull requests never get a publishing token or Store secrets. Protect main/version tags after initial bring-up.

Main pushes run tests, compile the complete Windows editor and CLI, pack/unpack/inspect MSIX, upload artifacts, and publish an unsigned prerelease after build success. Pull requests test/build only. Manual main runs work. Version tags must match config/product.json. All releases remain development prereleases until signing, clean-machine UX, document fidelity and dependency-license review are complete.

For Store later: reserve the name, use exact Partner Center identity fields, build with `-Store -IdentityFile <local JSON>`, and complete the first submission and declarations manually. Store automation is deferred. Never put PFX/client secrets in this repository. Store signing and GitHub-hosted unsigned releases are separate.

References:
https://docs.github.com/en/billing/concepts/product-billing/github-actions
https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/msix/app-package-requirements
https://learn.microsoft.com/en-us/windows/msix/package/sign-msix-package-guide
