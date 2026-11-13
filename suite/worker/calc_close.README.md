# Calc close preparation

Calc's public model modified flag does not include all active input-buffer state.
The Suite therefore starts an explicit `prepare-close` transaction before its
Save/Discard/Cancel decision. Periodic `status` remains read-only.

For the retained owned Calc frame, `prepare_calc_close` dispatches
`.uno:AcceptFormula` exactly once through `DispatchHelper` with
`OnMainThread=True`. It checks the same document/controller/frame/native child
before and after. It performs no store, Save, native picker or interactive native
close. Untitled and read-only documents still use the existing Suite Save flow
after the user chooses Save. A preparation error leaves the document attached.

Every Calc close now asks Save/Discard/Cancel, including when its model remains
clean after preparation. The close-decision `modified=True` is conservative;
`nativeModified` and `closePreparation.nativeModifiedBefore/After` preserve the
actual flags. `pendingInputAbsenceVerified` and `asyncValidationQualified` remain
false. This is an intentional change in close UX to prioritize retained data.
Cancel keeps the same document attached; Discard authorizes closing without
another preparation or store. The helper does not decide or execute those
choices.

The exact LibreOffice 26.8.1.1 source shows the limits:

- [AcceptFormula submits only an existing active edit view](https://github.com/LibreOffice/core/blob/libreoffice-26.8.1.1/sc/source/ui/view/cellsh3.cxx#L991).
  The slot supplies no semantic return item or `Done()` result.
- [EnterHandler can start asynchronous validation](https://github.com/LibreOffice/core/blob/libreoffice-26.8.1.1/sc/source/ui/app/inputhdl.cxx#L3277),
  and [formula correction can also return before its callback](https://github.com/LibreOffice/core/blob/libreoffice-26.8.1.1/sc/source/ui/view/viewfunc.cxx#L615).
- [Dispatch result construction reports slot execution](https://github.com/LibreOffice/core/blob/libreoffice-26.8.1.1/sfx2/source/control/unoctitm.cxx#L737),
  rather than input-buffer acceptance, validation completion or a user veto.

Original run `39014594506` observed `status.modified=false` followed by
`close:true` without a Suite prompt in all three close probes; disk bytes stayed
at the baseline. Model snapshots plus OS input-insertion counts do not alone
prove the actual editor buffer contained the marker, so that evidence is
reported as an unsafe close path. Independently proving pending-buffer loss
requires a read-only editor-buffer receipt. The physical probe still uses one
Ctrl+W, no Enter and no intervening focus action or mutation.

Integration keeps one explicit preparation boundary: the worker's `prepare-close`
RPC calls this helper for Calc and ordinary status for other modules; the shell
calls `PrepareCloseAsync` before presenting its existing choices. The ordinary
`status` RPC and status timer must never invoke preparation. Existing generated
Calc GUI cases must opt into an exact owned-prompt action after their single
WM_CLOSE. A saved-copy cleanup must freeze its verified path/cells/hash before
close and verify the same bytes afterward; a new blank case needs explicit
generated-blank proof. Unexpected, foreign or ambiguous prompts must fail.

Portable tests exercise the command and ownership boundaries. They do not prove
native Windows input acceptance or asynchronous validation correctness.
