"""Inspect real printer output using independent PDFium text AND raster checks.

This cannot certify a physical printer. It deliberately rejects image-only PDFs
for our searchable synthetic fixtures, and does not use OCR or the app renderer.
"""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
import pypdfium2 as pdfium

MAX_BYTES = 20_000_000
SCALE = 3


def _match(textpage, marker):
    if not isinstance(marker, str) or not marker:
        raise ValueError('Expected a nonempty marker')
    search = textpage.search(marker, match_case=True)
    try:
        first = search.get_next()
        if first is None or search.get_next() is not None:
            raise ValueError(f'Expected exactly one marker: {marker!r}')
        return first
    finally:
        search.close()


def _box(textpage, match):
    boxes = [textpage.get_charbox(i) for i in range(match[0], match[0] + match[1])]
    boxes = [b for b in boxes if b[2] > b[0] and b[3] > b[1]]
    if not boxes:
        raise ValueError('Empty marker bounds')
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def _ink(image, box, width, height):
    left, bottom, right, top = box
    if not all(math.isfinite(x) for x in box) or min(left, bottom) < -0.5 or right > width + .5 or top > height + .5:
        raise ValueError(f'Marker outside page bounds: {box}')
    crop = image.crop((math.floor(left*SCALE), math.floor((height-top)*SCALE),
                       math.ceil(right*SCALE), math.ceil((height-bottom)*SCALE))).convert('L')
    if not crop.width or not crop.height:
        raise ValueError('Empty ink region')
    dark = sum(crop.histogram()[:160])
    return dark, crop.width * crop.height


def inspect_pdf(path: Path, expectation: dict, output: Path) -> dict:
    pages = expectation.get('pages')
    if not isinstance(pages, list) or not 1 <= len(pages) <= 6:
        raise ValueError('Require one to six explicit expected pages')
    if path.is_symlink() or not path.is_file() or not 5 < path.stat().st_size <= MAX_BYTES:
        raise ValueError('Invalid or oversized PDF')
    data = path.read_bytes()
    if not data.startswith(b'%PDF-'):
        raise ValueError('Printer did not produce a PDF')
    output.mkdir(parents=True, exist_ok=True)
    result = {'sha256': hashlib.sha256(data).hexdigest(), 'pages': 0, 'checks': []}
    try:
        document = pdfium.PdfDocument(data)
    except Exception as exc:
        raise ValueError('Unreadable printer PDF') from exc
    try:
        if len(document) != len(pages):
            raise ValueError(f'Unexpected page count: {len(document)} != {len(pages)}')
        result['pages'] = len(document)
        for index, expected in enumerate(pages):
            if not expected.get('markers'):
                raise ValueError('Each page needs explicit markers')
            page = document[index]
            textpage = page.get_textpage()
            bitmap = None
            try:
                width, height = page.get_size()
                wanted = expected['size_pt']
                if len(wanted) != 2 or not all(isinstance(v,(int,float)) and math.isfinite(v) and 50 <= v <= 1200 for v in wanted):
                    raise ValueError('Invalid expected page size')
                if not all(math.isfinite(v) and 50 <= v <= 1200 for v in (width,height)) or abs(width-wanted[0]) > 2 or abs(height-wanted[1]) > 2:
                    raise ValueError(f'Unexpected page size: {(width,height)} vs {wanted}')
                bitmap = page.render(scale=SCALE)
                image = bitmap.to_pil().convert('RGB')
                image.save(output/f'page-{index+1}.png')
                checks = {'page': index+1, 'size_pt':[width,height], 'markers':[], 'ink_pairs':[]}
                for marker in expected['markers']:
                    bounds = _box(textpage, _match(textpage, marker))
                    ink, area = _ink(image, bounds, width, height)
                    if ink < 10 or ink/area < .015:
                        raise ValueError(f'Marker has no visible ink: {marker!r}')
                    checks['markers'].append({'text':marker,'bounds':bounds,'ink':ink})
                for reference, terminal in expected.get('ink_pairs', []):
                    counts = []
                    for marker in (reference, terminal):
                        match = _match(textpage, marker)
                        bounds = textpage.get_charbox(match[0]+match[1]-1)
                        counts.append(_ink(image, bounds, width, height)[0])
                    if reference[-1] != terminal[-1] or counts[0] < 10:
                        raise ValueError('Invalid reference glyph for clipping check')
                    ratio = counts[1]/counts[0]
                    if ratio < .85:
                        raise ValueError(f'Terminal glyph ink clipped: {terminal!r} ratio={ratio:.3f}')
                    checks['ink_pairs'].append({'reference':reference,'terminal':terminal,'ink_ratio':ratio})
                result['checks'].append(checks)
            finally:
                if bitmap is not None: bitmap.close()
                textpage.close()
                page.close()
    finally:
        document.close()
    (output/'inspection.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return result
