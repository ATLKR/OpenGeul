"""Exact reviewed visible-ink fingerprints for virtual drivers that outline text.

No OCR, embedded font or auto-generated reference. Thresholded PDFium rasters
are deterministic for the reviewed driver/font inputs. An unreviewed changed pixel fails. A bounded set of explicit whole-page
variants can record independently reviewed driver/font differences.
"""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
from PIL import ImageChops
import pypdfium2 as pdfium
SCALE=3
REFERENCE=Path(__file__).with_name('print-goldens.json')

def fingerprint(image):
    pixels=image.convert('L').point(lambda x:0 if x<160 else 255,mode='1')
    ink=ImageChops.invert(pixels)
    count=ink.histogram()[255]
    if count<100:raise ValueError('Blank or nearly blank print reference/output')
    return {'pixels':list(pixels.size),'ink':count,'bbox':list(ink.getbbox()),
            'maskSha256':hashlib.sha256(pixels.tobytes()).hexdigest()}

def compare_ink(actual,reference):
    a,r=fingerprint(actual),fingerprint(reference)
    if a!=r:raise ValueError(f'Printed ink changed: {a} != {r}')
    return {'missing':0,'added':0,**a}

def load_reference(case):
    if not REFERENCE.is_file() or REFERENCE.stat().st_size>100_000:raise ValueError('Missing or oversized reviewed printer reference')
    book=json.loads(REFERENCE.read_text(encoding='utf-8'))
    if book.get('schema')!=1 or book.get('scale')!=SCALE or case not in book.get('cases',{}):raise ValueError('No reviewed print reference for this scenario')
    return book,book['cases'][case]

def match_reference(actual, canonical, book, case, page):
    """Accept exact approved whole-page masks, never a runtime-generated baseline."""
    variants = book.get('reviewedVariants', [])
    if not isinstance(variants, list) or len(variants) > 4:
        raise ValueError('Invalid reviewed reference variants')
    eligible = []
    for variant in variants:
        if (not isinstance(variant, dict) or not isinstance(variant.get('id'), str)
                or not variant['id'] or not isinstance(variant.get('review'), str)
                or not variant['review'].strip()
                or type(variant.get('sourceRun')) is not int or variant['sourceRun'] <= 0
                or type(variant.get('sourceArtifact')) is not int or variant['sourceArtifact'] <= 0
                or type(variant.get('page')) is not int or not 1 <= variant['page'] <= 6
                or not isinstance(variant.get('case'), str)
                or not isinstance(variant.get('fingerprint'), dict)
                or set(variant['fingerprint']) != {'pixels', 'ink', 'bbox', 'maskSha256'}):
            raise ValueError('Reviewed variant requires explicit identity, provenance and review')
        if variant['case'] == case and variant['page'] == page:
            eligible.append(variant)
    matches = [v['id'] for v in eligible if actual == v['fingerprint']]
    if len(matches) > 1:
        raise ValueError('Ambiguous reviewed print variants')
    if actual == canonical:
        return 'canonical'
    if matches:
        return matches[0]
    raise ValueError('Printed ink fingerprint changed; explicit visual review required')


def inspect_print_pdf(path,expectation,output,case):
    book,refs=load_reference(case);pages=expectation.get('pages')
    if not isinstance(pages,list) or not 1<=len(pages)<=6 or len(refs)!=len(pages):raise ValueError('Expected pages/reference count mismatch')
    if path.is_symlink() or not path.is_file() or not 5<path.stat().st_size<=20_000_000:raise ValueError('Invalid printer PDF')
    data=path.read_bytes()
    if not data.startswith(b'%PDF-'):raise ValueError('Output is not PDF')
    output.mkdir(parents=True,exist_ok=True)
    result={'sha256':hashlib.sha256(data).hexdigest(),'mode':'reviewed-raster-fingerprint','referenceRun':book['sourceRun'],'referenceCommit':book['productCommit'],'checks':[]}
    with pdfium.PdfDocument(data) as document:
        if len(document)!=len(pages):raise ValueError('Unexpected printed page count')
        for i,(expected,ref) in enumerate(zip(pages,refs)):
            page=document[i];bitmap=None
            try:
                size=page.get_size();wanted=expected['size_pt']
                if len(wanted)!=2 or not all(isinstance(v,(int,float)) and math.isfinite(v) and 50<=v<=1200 for v in (*size,*wanted)):raise ValueError('Invalid paper dimensions')
                if any(abs(a-b)>1 for a,b in zip(size,wanted)):raise ValueError(f'Incorrect paper size: {size} != {wanted}')
                bitmap=page.render(scale=SCALE);image=bitmap.to_pil().convert('L');image.save(output/f'page-{i+1}.png')
                actual=fingerprint(image)
                try:
                    reference_id=match_reference(actual,ref,book,case,i+1)
                except ValueError:
                    (output/f'page-{i+1}-mismatch.json').write_text(json.dumps({'expected':ref,'actual':actual},indent=2),encoding='utf-8')
                    raise ValueError(f'Printed ink fingerprint changed on page {i+1}; explicit visual review required; expected={ref}; actual={actual}')
                result['checks'].append({'page':i+1,'size_pt':size,'referenceId':reference_id,**actual})
            finally:
                if bitmap is not None:bitmap.close()
                page.close()
    (output/'inspection.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    return result
