"""Independent PDFium checks on Windows printer output; never an app export oracle."""
from __future__ import annotations
import hashlib
import math
from pathlib import Path


def validate_report(report: dict, expected: dict) -> dict:
    assert len(expected['pageSize']) == 2, 'invalid expected paper size'
    pages = expected['pages']
    assert 0 < len(pages) <= 8, 'invalid expected page count'
    assert 'microsoft' in report.get('producer', '').lower() and 'pdf' in report['producer'].lower(), 'wrong printer producer'
    assert len(report['pages']) == len(pages), 'wrong printed page count'
    total = 0
    for number, (page, markers) in enumerate(zip(report['pages'], pages), 1):
        assert markers, 'empty expected page'
        assert len(page['size']) == 2, 'invalid paper dimensions'
        assert all(math.isfinite(v) and abs(v - w) < 2 for v, w in zip(page['size'], expected['pageSize'])), 'wrong paper size/orientation'
        assert page['inkPixels'] > 20, f'blank raster page {number}'
        for forbidden in expected.get('forbidden', []):
            assert forbidden not in page['text'], 'editor chrome leaked into print'
        for marker in markers:
            assert page['text'].count(marker) == 1, f'page {number}: missing/duplicate {marker}'
            value = page['markers'][marker]
            assert value['withinPage'], f'{marker} outside paper'
            assert value['inkPixels'] > 5, f'{marker} invisible despite extractable text'
            total += 1
    return {'pages': len(pages), 'markers': total}


def compare_terminal_ink(compressed: int, control: int) -> float:
    assert control > 20, 'invalid terminal control'
    ratio = compressed / control
    assert .90 <= ratio <= 1.10, f'terminal glyph raster differs: ink ratio {ratio:.3f}'
    return ratio


def inspect_pdf(path: Path, expected: dict, evidence: Path) -> dict:
    """Render at 144 dpi; count visible dark pixels inside each searched glyph box.

    Clipped/white text can still be extractable. A zero-spacing control compared
    with the compressed table adds a separate check for partial terminal glyph loss.
    No OCR, installed font copying or app-side PDF serializer is used.
    """
    import pypdfium2 as pdfium
    data = path.read_bytes()
    assert 100 < len(data) <= 20_000_000 and data.startswith(b'%PDF-'), 'invalid/oversized printer PDF'
    evidence.mkdir(parents=True, exist_ok=True)
    doc = pdfium.PdfDocument(data)
    try:
        assert len(doc) <= 8, 'unexpectedly many printer pages'
        report = {'sha256': hashlib.sha256(data).hexdigest(), 'producer': doc.get_metadata_value('Producer'), 'pages': []}
        for index in range(len(doc)):
            page = doc[index]
            textpage = page.get_textpage()
            bitmap = page.render(scale=2, grayscale=True)
            image = bitmap.to_pil().convert('L')
            try:
                image.save(evidence / f'page-{index+1}.png')
                width, height = page.get_size()
                row = {'size': [width, height], 'text': textpage.get_text_range(),
                       'inkPixels': sum(image.histogram()[:180]), 'markers': {}}
                for marker in expected['pages'][index] if index < len(expected['pages']) else []:
                    search = textpage.search(marker, match_case=True)
                    try: hit = search.get_next()
                    finally: search.close()
                    if hit is None: continue
                    start, count = hit
                    boxes = [textpage.get_charbox(i) for i in range(start, start+count)]
                    left = min(b[0] for b in boxes); bottom = min(b[1] for b in boxes)
                    right = max(b[2] for b in boxes); top = max(b[3] for b in boxes)
                    crop = image.crop((max(0, math.floor(left*2)), max(0, math.floor((height-top)*2)),
                                       min(image.width, math.ceil(right*2)), min(image.height, math.ceil((height-bottom)*2))))
                    row['markers'][marker] = {'box': [left, bottom, right, top],
                        'withinPage': 0 <= left < right <= width and 0 <= bottom < top <= height,
                        'inkPixels': sum(crop.histogram()[:180])}
                    crop.close()
                report['pages'].append(row)
            finally:
                image.close(); bitmap.close(); textpage.close(); page.close()
        validate_report(report, expected)
        return report
    finally: doc.close()
