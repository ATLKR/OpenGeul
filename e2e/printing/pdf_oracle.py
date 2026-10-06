"""Validate virtual-printer PDFs independently of rhwp; never extract font programs."""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
from pypdf import PdfReader
import pypdfium2 as pdfium


def inspect_printed_pdf(path: Path, expected: dict, evidence: Path) -> dict:
    pages_expected = expected.get('pages', [])
    assert 1 <= len(pages_expected) <= 6 and all(p and all(isinstance(t, str) and t for t in p) for p in pages_expected), 'Nonempty per-page markers required'
    assert path.is_file() and not path.is_symlink(), 'Missing printed file'
    assert 100 <= path.stat().st_size <= 20 * 1024 * 1024, 'Printed PDF outside size budget'
    assert path.read_bytes()[:5] == b'%PDF-', 'Output is not a PDF'
    reader = PdfReader(path, strict=True)
    assert not reader.is_encrypted, 'Unexpected encrypted output'
    assert len(reader.pages) == len(pages_expected), 'Unexpected page count (missing or extra/blank page)'
    evidence.mkdir(parents=True, exist_ok=True)
    report = {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'page_count': len(reader.pages), 'pages': []}
    document = pdfium.PdfDocument(path)
    try:
        for index, markers in enumerate(pages_expected):
            page = document[index]
            textpage = page.get_textpage()
            bitmap = None
            try:
                width, height = page.get_size()
                size = expected.get('size_pt', [595.276, 841.89])
                assert all(math.isfinite(v) and 10 <= v <= 2600 for v in (width, height)), 'Invalid page dimensions'
                assert abs(width-size[0]) <= 3 and abs(height-size[1]) <= 3, f'Wrong paper size: {(width, height)}'
                text = reader.pages[index].extract_text() or ''
                for forbidden in expected.get('forbidden', []):
                    assert forbidden not in text, f'Unexpected content: {forbidden}'
                bitmap = page.render(scale=2)
                image = bitmap.to_pil().convert('L')
                image.save(evidence / f'page-{index+1}.png')
                assert sum(image.histogram()[:200]) >= 20, 'Blank raster page'
                checks = []
                for marker in markers:
                    assert marker in text, f'Missing text on page {index+1}: {marker}'
                    search = textpage.search(marker, match_case=True)
                    try:
                        found = search.get_next()
                        assert found is not None, f'PDFium cannot locate {marker}'
                        start, count = found
                        assert search.get_next() is None, f'Duplicated marker {marker}'
                    finally:
                        search.close()
                    bounds = []
                    visible = 0
                    for char_index in range(start, start+count):
                        left, bottom, right, top = textpage.get_charbox(char_index)
                        assert all(math.isfinite(v) for v in (left, bottom, right, top)), 'Nonfinite glyph bounds'
                        assert -.5 <= left < right <= width+.5 and -.5 <= bottom < top <= height+.5, f'Glyph outside paper: {marker}'
                        # Ink-presence, not proof of pixel-perfect typography.
                        box = (max(0, math.floor(left*2)), max(0, math.floor((height-top)*2)),
                               min(image.width, math.ceil(right*2)), min(image.height, math.ceil((height-bottom)*2)))
                        if box[2] > box[0] and box[3] > box[1]:
                            ink = sum(image.crop(box).histogram()[:200])
                            assert ink > 0, f'Extractable but invisible/clipped glyph: {marker} at {char_index-start}'
                            visible += 1
                        bounds.append([round(v, 3) for v in (left, bottom, right, top)])
                    assert visible == count, f'Missing painted glyphs: {marker}'
                    checks.append({'marker': marker, 'glyphs': count, 'bounds': bounds})
                report['pages'].append({'size_pt': [width, height], 'markers': checks, 'text': text})
            finally:
                if bitmap is not None:
                    bitmap.close()
                textpage.close()
                page.close()
    finally:
        document.close()
    (evidence/'validation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report
