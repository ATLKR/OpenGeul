"""Keep compatibility PDF root Forms in SVG units for PDFium text extraction.

The original normalized svg2pdf API remains available for nested SVG images.
All inputs are pinned before any write; font data and embedding policy are untouched.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPER = 'scripts/pdf_search_text.py'
CORE = 'third_party/rhwp/'
LIB = CORE + 'vendor/svg2pdf/src/lib.rs'
RENDER = CORE + 'vendor/svg2pdf/src/render/mod.rs'
PDF = CORE + 'src/renderer/pdf.rs'
PATCHES = CORE + 'vendor/svg2pdf/RHWP_PATCHES.md'
# PDF is pinned after the existing OpenGeul embedding/completeness guards.
SOURCE_SHA256 = {
    LIB: '15cc41eef2f9d65773a0f0dd2ddd8144331a8304e42425f90adc06ba137c4406',
    RENDER: '040df1fbe7fedd93b65dff234a6091243a61d59b02f92be3eeaf373bbef7cf35',
    PDF: '0d460d7e4944588f79f4ea9a9857598e21a4c10d76cd907067ff2077e5455a04',
    PATCHES: '87293452a2e13bbf6403a0fe07f679d2405e5a248df57a31bdbcde5f325b776c',
}
PRESERVED_SHA256 = {
    CORE + 'vendor/svg2pdf/LICENSE-APACHE': '62c7a1e35f56406896d7aa7ca52d0cc0d272ac022b5d2796e7d6905db8a3636a',
    CORE + 'vendor/svg2pdf/LICENSE-MIT': '508a77d2e7b51d98adeed32648ad124b7b30241a8e70b2e72c99f92d8e5874d1',
    CORE + 'vendor/svg2pdf/NOTICE': '74544feeaa2083014e5c62c4d3eda0e6dfb77f621310b5b602b074df199dcc20',
    CORE + 'tests/fixtures/fonts/RHWPExactKerningSmoke.LICENSE.md': 'd9f8802d5d5e5bb802041be5bbde1317ee38301c06b2fc9cc37d199eb53f9d64',
}
# Explicit reviewed output bytes, including the existing font-policy guards.
PATCHED_SHA256 = {
    LIB: 'dc33760dff462546dec8e47c896a6c278d9533758e21847eda0ddfd8386a5e02',
    RENDER: 'fadb08aa5901d5fb09642c95c37bf0de7b94fa87e23a34ab5c0c41820cd110ae',
    PDF: '84bb9980b3a42e42998872bc9112a1714ef82984a5981b59c51d148f90b9e804',
    PATCHES: '53e157001c4e24c15f72460d5564455d0f970067403f43e93f6a69a9d3993471',
}
SOURCE_FILES = tuple((*SOURCE_SHA256, *PRESERVED_SHA256))

ADDITIVE_API = '''
/// Convert a tree into a root Form retaining its SVG width and height.
///
/// Place this Form with a DPI transform (for example 72/96), rather than a
/// page-width/page-height transform. Keeping glyph bounds in SVG units avoids
/// PDFium pruning small separately positioned text inside a normalized Form.
/// `to_chunk` retains its original normalized 1x1 contract for image embedding.
pub fn to_chunk_with_svg_size(
    tree: &Tree,
    conversion_options: ConversionOptions,
) -> Result<(Chunk, Ref)> {
    let mut chunk = Chunk::new();
    let mut ctx = Context::new(tree, conversion_options)?;
    let x_ref = tree_to_xobject_with_svg_size(tree, &mut chunk, &mut ctx)?;
    ctx.write_global_objects(&mut chunk)?;
    Ok((chunk, x_ref))
}
'''

ROOT_FORM_API = '''pub fn tree_to_xobject(tree: &Tree, chunk: &mut Chunk, ctx: &mut Context) -> Result<Ref> {
    let size = tree.size();
    tree_to_xobject_with_matrix(
        tree, chunk, ctx,
        [1.0 / size.width(), 0.0, 0.0, 1.0 / size.height(), 0.0, 0.0],
    )
}

/// Root page Forms keep their text bounds in SVG units.
pub fn tree_to_xobject_with_svg_size(tree: &Tree, chunk: &mut Chunk, ctx: &mut Context) -> Result<Ref> {
    tree_to_xobject_with_matrix(tree, chunk, ctx, [1.0, 0.0, 0.0, 1.0, 0.0, 0.0])
}

fn tree_to_xobject_with_matrix(
    tree: &Tree, chunk: &mut Chunk, ctx: &mut Context, matrix: [f32; 6],
) -> Result<Ref> {'''

PROVENANCE = '''

## OpenGeul root page Form geometry

- OpenGeul adds `to_chunk_with_svg_size` for compatibility PDF page roots.
  The existing `to_chunk` 1x1 contract and nested SVG image conversion remain intact.
- Root Forms retain an identity Matrix and the original SVG BBox. rhwp places
  them with the same 72/96 DPI transform; final geometry, clipping, paints,
  font subsets and ToUnicode mappings remain unchanged.
- PDFium removes text objects whose Form-local width is <= 0.01 before applying
  the enclosing page transform. Normalizing an A4 page to 1x1 therefore erased
  ordinary small Latin letters and digits from search/extraction while retaining
  their raster. Keeping root coordinates in SVG units resolves this consumer defect.
- The regression uses upstream's original MIT `RHWPExactKerningSmoke` fixture
  in `tests/opengeul_pdf_policy.rs`. No font binaries or dependencies are added.
- Original LICENSE-APACHE, LICENSE-MIT, NOTICE and fixture license are preserved.
'''


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _replace(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise ValueError('PDF search text patch anchor mismatch')
    return text.replace(old, new, 1)


def patched_texts(texts: dict[str, str]) -> dict[str, str]:
    lib = _replace(texts[LIB],
        'use crate::render::{tree_to_stream, tree_to_xobject};',
        'use crate::render::{tree_to_stream, tree_to_xobject, tree_to_xobject_with_svg_size};')
    if 'pub fn to_chunk_with_svg_size(' in lib:
        raise ValueError('PDF search text API is already present')
    lib += ADDITIVE_API
    render = _replace(texts[RENDER],
        'pub fn tree_to_xobject(tree: &Tree, chunk: &mut Chunk, ctx: &mut Context) -> Result<Ref> {',
        ROOT_FORM_API)
    render = _replace(render,
        '    x_object.matrix([1.0 / bbox.width(), 0.0, 0.0, 1.0 / bbox.height(), 0.0, 0.0]);',
        '    x_object.matrix(matrix);')
    pdf = _replace(texts[PDF], '    svg2pdf::to_chunk(tree, conversion)',
        '    svg2pdf::to_chunk_with_svg_size(tree, conversion)')
    pdf = _replace(pdf,
        '        content.transform([pd.width, 0.0, 0.0, pd.height, 0.0, 0.0]);',
        '''        // Root Forms retain SVG coordinates; apply only the 96 DPI -> 72 pt scale.
        content.transform([0.75, 0.0, 0.0, 0.75, 0.0, 0.0]);''')
    return {LIB: lib, RENDER: render, PDF: pdf, PATCHES: texts[PATCHES] + PROVENANCE}


def apply(source: Path) -> dict:
    inputs = {name: (source/name).read_bytes() for name in SOURCE_SHA256}
    before = {name: digest(data) for name, data in inputs.items()}
    if before != SOURCE_SHA256:
        raise ValueError('PDF search text pinned source mismatch')
    preserved = {name: digest((source/name).read_bytes()) for name in PRESERVED_SHA256}
    if preserved != PRESERVED_SHA256:
        raise ValueError('PDF search text original license mismatch')
    texts = {name: data.decode('utf-8') for name, data in inputs.items()}
    outputs = {name: text.encode('utf-8') for name, text in patched_texts(texts).items()}
    after = {name: digest(data) for name, data in outputs.items()}
    if after != PATCHED_SHA256:
        raise ValueError('PDF search text reviewed output mismatch')
    # All source, license and output checks precede the first mutation.
    for name, data in outputs.items():
        (source/name).write_bytes(data)
    return {'formatVersion': 1, 'helperSha256': digest((ROOT/HELPER).read_bytes()),
            'beforeSha256': before, 'afterSha256': after, 'preservedSha256': preserved}


def validate(proof: dict, preparedFiles: dict, coreSourceFiles: dict, helpers: dict) -> None:
    if (not isinstance(proof, dict) or set(proof) != {'formatVersion', 'helperSha256',
            'beforeSha256', 'afterSha256', 'preservedSha256'}
            or type(proof['formatVersion']) is not int or proof['formatVersion'] != 1):
        raise ValueError('Invalid PDF search text source proof')
    if (not isinstance(proof['helperSha256'], str) or len(proof['helperSha256']) != 64
            or proof['helperSha256'] != helpers.get(HELPER)):
        raise ValueError('PDF search text helper mismatch')
    if proof['beforeSha256'] != SOURCE_SHA256 or proof['afterSha256'] != PATCHED_SHA256:
        raise ValueError('PDF search text pinned source proof mismatch')
    if proof['preservedSha256'] != PRESERVED_SHA256:
        raise ValueError('PDF search text original license proof mismatch')
    for name, expected in {**PATCHED_SHA256, **PRESERVED_SHA256}.items():
        if preparedFiles.get(name) != expected:
            raise ValueError('PDF search text prepared source hash mismatch: ' + name)
        if '/src/' in name and coreSourceFiles.get(name) != expected:
            raise ValueError('PDF search text complete source hash mismatch: ' + name)
