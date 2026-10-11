# rhwp 0.8.7 print reference review

The exact print references are reviewed against the owned synthetic documents
from [run 38142625600](https://github.com/ATLKR/OpenGeul/actions/runs/38142625600),
source `756116ff1fc094e8a1bdf2ecec6fcf3f6d3c4e17`. Both Windows versions printed
through the real Microsoft Print To PDF dialog. All eight output pages retain
the expected A4 portrait media, page counts, table rows, Korean/Latin content,
page markers and unchanged source files. Range output equals the second
multipage page.

Independent review reproduced all eight generated native source hashes by
changing only ZIP DOS timestamps and the central-directory host byte of the
controlled documents. Names, compressed member data, CRCs and document content
remain identical; the fixture generator scripts are unchanged.

The review compared the same fixture bytes with old rhwp 0.8.4 WASM
`f059bddbb553223ee9ceb01e2b9e4cd8856301dc366f41310ad6f4cddbfb07f8`
and the source-built rhwp 0.8.7 WASM
`d5455ff80f61af65dfab5cbe2f2058bc377e5d44f7c97dd7e586f0edaaa6d5da`.
The changed native masks agree with these source and geometry controls:

- The [border conversion correction](https://github.com/edwardkim/rhwp/blob/1a76570e833917d15817415a53c09ad61ab3203f/src/renderer/layout/border_rendering.rs#L1298)
  quantizes the 0.12 mm table border to 0.48 CSS px instead of 0.5. Table text
  positions and advances remain unchanged, while all four strokes become
  thinner. The negative/zero-spacing cell geometry stays unchanged.
- The [+600 final-line correction](https://github.com/edwardkim/rhwp/blob/1a76570e833917d15817415a53c09ad61ab3203f/src/renderer/height_measurer.rs#L3178)
  removes spacing after the last nonblank line. Five 1,000-unit lines, four
  600-unit gaps and 282 units of padding give
  `(5*1000 + 4*600 + 282)*96/7200 = 102.4267` CSS px. The removed 8 CSS px
  predicts the observed 18 raster px reduction at 216 DPI. All 65 table glyph
  outlines remain, and terminal descenders stay inside the border.
- The [HCR Batang metric correction](https://github.com/edwardkim/rhwp/blob/1a76570e833917d15817415a53c09ad61ab3203f/src/renderer/layout/text_measurement.rs#L2192)
  replaces inflated ASCII advances with the font's own metrics. Both basic
  documents retain their 30 text elements and requested primary font. The
  controlled right edge moves by -3.88 CSS px, predicting the native -9 raster
  px width change.
- Fitting paragraphs without stored line segments now use the
  [frame baseline](https://github.com/edwardkim/rhwp/blob/1a76570e833917d15817415a53c09ad61ab3203f/src/renderer/composer/line_breaking.rs#L3065).
  The change from 0.8 to 0.85 of the 10 pt font predicts +0.6667 CSS px
  (+1.5 raster px, aligned to the observed +2). Both multipage controls retain
  the same 32 text elements and advances.

The Windows 2022 and 2025 masks match apart from the previously reviewed
eight-pixel digit-4 crossbar variant in `table-0`, at `[479,388,490,389]`.
Its exact whole-page fingerprint is separately recorded. The matcher,
216-DPI scale, threshold, page/media/spooler/source checks and zero generic
pixel tolerance remain unchanged. CI does not regenerate references.

The prior pristine WASM lacks OpenGeul's old negative-spacing backport;
its -300 height is not the previous production height. Installed font binary
hashes were not recorded, so the review does not claim font file identity.
The native PDFs outline text; the raster and source controls supply the
regression evidence. This does not certify a physical printer or Hancom parity.
