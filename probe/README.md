# Candidate native password qualification

This separate diagnostic entrypoint preserves the production 16-case suite. Its package source/run defaults stay bound to `756116ff1fc094e8a1bdf2ecec6fcf3f6d3c4e17` / `38142625600`. The workflow must verify the exact source-run artifact origins and prepare the checksum-verified MSIX/portable runtime before executing it.

Run from the diagnostic checkout root:

```text
node probe/generate-password-fixtures.mjs wasm-input inputs/e2e-fixtures password-fixtures
python probe/password-native.py --source-root . --fixtures password-fixtures --exe runtime/OpenGeul.exe --output evidence/password-native
```

The generator uses task-owned synthetic text and public encrypted export APIs. It rejects missing or changed source provenance and all six missing or changed artifact hashes before loading the engine. No private documents, upstream sample documents, or font programs are inputs; its QA password is public synthetic data.

The native probe now requires eight passing cases. The original six cover wrong/correct retry, password-dialog cancellation preserving a prior document, direct Save denial and protected-source SHA retention, both input/output format Save As combinations with plaintext-consent cancel/accept, and fresh plaintext reopen/edit/save.

Two additional cases, one per encrypted input format, exercise a dirty protected document through real native replacement and Windows close dialogs. They select Cancel in the replacement confirmation and in a physical Alt+F4 close confirmation; choose Save during replacement but cancel the following plaintext consent; then choose Save during another physical close and explicitly accept plaintext consent. The original editor PID must exit with code zero before cleanup runs, and the saved plaintext must independently contain the original content and all edits. A fresh native process must reopen that output without a password and retain a further edit after direct Save. Each stage retains the protected-source checksum.

Cleanup's taskkill fallback is never counted as a normal close. The new cases do not cover choosing Discard, accepting a replacement safety save, closing while a password prompt is pending, or edits racing a staged save. Source tests cover those shared locks and selected safety branches with mocked services; they are separate evidence. Windows native results remain pending until this diagnostic runs against the final candidate package.

Direct Save of a protected original is blocked. Explicit Save As can select the original path and overwrite it with unprotected output after consent; this probe always uses a separate output path. Public copy should say Direct Save is blocked and recommend keeping the protected original. When the qualified release is offered, the guide/privacy copy should clarify that Save As, PDF/printing and manual local history can contain decrypted content. The old website guide remains scoped to its currently offered 1.1.1 binary until the download changes.
