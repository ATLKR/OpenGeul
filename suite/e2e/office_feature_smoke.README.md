# Finite Office format and module checks

`office_feature_smoke.py` runs fifteen advertised format cases and six richer
module cases with the packaged Windows UNO engine. Each case creates generated
data, closes its private engine, then reopens the saved file in an independent
private engine. This is engine coverage; it establishes neither physical GUI
editing nor complete Office replacement.

```powershell
& "$suite\Office\program\python.exe" "$repo\suite\e2e\office_feature_smoke.py" --suite $suite --output $freshEvidence
```

The output must be fresh and outside the payload. Each case retains its raw
creation and reopen observations, expected semantics, owned process cleanup,
fixture hashes and any exception. The canonical aggregate requires all 21 cases
in their reviewed order. Original failures remain original failures; a later
focused rerun is a separate result.

PPTX geometry has an explicit qualification limit. The two PPTX cases require:

- Raw creation `TextShape` text, position and size exactly match the authored
  values in hundredths of a millimetre (`mm100`).
- An independent XML parser follows presentation slide relationships and checks
  exact slide/shape order, text, `a:off` and `a:ext`. Every saved coordinate and
  extent must equal the authored value multiplied by 360 EMU, with no tolerance.
- Raw independent reopen `CustomShape` text, order and position remain exact.
  Each native width and height must equal authored size minus exactly one
  `mm100` unit (0.01 mm). Other differences fail. The report preserves the raw
  values and carries `knownNativeGeometryDifference` and `qualificationScope`;
  it does not add one to an observation or overwrite the authored expectation.
- Both private engine generations must exit normally with an empty owned job;
  a read-only reopen must leave the saved file bytes unchanged.

Original Windows run `39013921145` exposed this native bounds difference in both
PPTX cases, while their saved XML retained exact authored extents. The exact
LibreOffice 26.8.1.1 source explains the path:

- [PPTShapeGroupContext creates a native CustomShape for p:sp](https://github.com/LibreOffice/core/blob/libreoffice-26.8.1.1/oox/source/ppt/pptshapegroupcontext.cxx#L108).
- [OOXML extents become the transformation scale](https://github.com/LibreOffice/core/blob/libreoffice-26.8.1.1/oox/source/drawingml/shape.cxx#L1118),
  converted to mm100 and assigned through `Transformation`.
- [Native CustomShape transformation constructs a closed rectangle](https://github.com/LibreOffice/core/blob/libreoffice-26.8.1.1/svx/source/svdraw/svdoashp.cxx#L3032).
- [That rectangle constructor subtracts one from the right and bottom coordinates](https://github.com/LibreOffice/core/blob/libreoffice-26.8.1.1/include/tools/gen.hxx#L593),
  while [XShape.getSize returns the open width and height](https://github.com/LibreOffice/core/blob/libreoffice-26.8.1.1/svx/source/unodraw/unoshape.cxx#L1069).
- [PPTX export reads XShape.getSize](https://github.com/LibreOffice/core/blob/libreoffice-26.8.1.1/oox/source/export/drawingml.cxx#L2339).

This qualifies exact saved OOXML geometry plus the documented native reopen
representation. It does **not** certify lossless repeated native edit/save or
universal geometry preservation. The catalogue explicitly lists the native
bounds difference as a loss limitation. No engine or product fix is claimed.
ODP, binary PPT and the other module oracles are unchanged. TXT/CSV retain their
separate explicit formatting, structure and formula loss budgets.

Portable unit tests exercise parser, semantic and cleanup boundaries. They do
not execute the packaged Windows engine or establish new Windows success.
