"""Fixed reviewed raster references for virtual drivers that outline text.

References are synthetic output snapshots, NOT font files. Tests never generate
or accept their own baseline. PDFium is independent of the application renderer.
"""
from __future__ import annotations
import base64
import hashlib
import io
import json
import math
from pathlib import Path
from PIL import Image,ImageChops,ImageFilter
import pypdfium2 as pdfium
SCALE=3
REFERENCE=Path(__file__).with_name('print-goldens.json')
def mask(image):return image.convert('L').point(lambda x:255 if x<160 else 0)
def count(image):return image.histogram()[255]
def compare_ink(actual,reference):
    if actual.size!=reference.size:raise ValueError('Raster canvas dimensions changed')
    a,r=mask(actual),mask(reference);n=count(r)
    if n<100:raise ValueError('A blank reference cannot validate a print')
    missing=ImageChops.subtract(r,a.filter(ImageFilter.MaxFilter(3)))
    added=ImageChops.subtract(a,r.filter(ImageFilter.MaxFilter(3)))
    m,e=count(missing),count(added)
    if m>n*.02 or e>n*.02:raise ValueError(f'Printed ink differs: missing={m}/{n}, added={e}/{n}')
    for y in range(0,r.height,24):
        for x in range(0,r.width,24):
            box=(x,y,min(x+24,r.width),min(y+24,r.height))
            expected=count(r.crop(box));lost=count(missing.crop(box));extra=count(added.crop(box))
            if lost>max(4,expected*.10) or extra>max(4,expected*.10):
                raise ValueError(f'Local printed glyph/line mismatch at {box}: missing={lost}, added={extra}')
    return {'referenceInk':n,'missing':m,'added':e,'tolerancePixels':1,'tilePixels':24}
def load_reference(case):
    if not REFERENCE.is_file() or REFERENCE.stat().st_size>1_000_000:raise ValueError('Missing or oversized reviewed printer reference')
    book=json.loads(REFERENCE.read_text(encoding='utf-8'))
    if book.get('schema')!=1 or book.get('scale')!=SCALE or case not in book.get('cases',{}):raise ValueError('No reviewed print reference for this scenario')
    return book,book['cases'][case]
def inspect_print_pdf(path,expectation,output,case):
    book,refs=load_reference(case);pages=expectation.get('pages')
    if not isinstance(pages,list) or not 1<=len(pages)<=6 or len(refs)!=len(pages):raise ValueError('Expected pages/reference count mismatch')
    if path.is_symlink() or not path.is_file() or not 5<path.stat().st_size<=20_000_000:raise ValueError('Invalid printer PDF')
    data=path.read_bytes()
    if not data.startswith(b'%PDF-'):raise ValueError('Output is not PDF')
    output.mkdir(parents=True,exist_ok=True)
    result={'sha256':hashlib.sha256(data).hexdigest(),'mode':'reviewed-raster','referenceRun':book['sourceRun'],'referenceCommit':book['productCommit'],'checks':[]}
    with pdfium.PdfDocument(data) as document:
        if len(document)!=len(pages):raise ValueError('Unexpected printed page count')
        for i,(expected,ref) in enumerate(zip(pages,refs)):
            page=document[i];bitmap=None
            try:
                dimensions=page.get_size();wanted=expected['size_pt']
                if len(wanted)!=2 or not all(isinstance(v,(int,float)) and math.isfinite(v) and 50<=v<=1200 for v in (*dimensions,*wanted)):raise ValueError('Invalid paper dimensions')
                if any(abs(a-b)>1 for a,b in zip(dimensions,wanted)):raise ValueError(f'Incorrect paper size: {dimensions} != {wanted}')
                encoded=base64.b64decode(ref['pngBase64'],validate=True)
                if len(encoded)>200_000 or hashlib.sha256(encoded).hexdigest()!=ref['sha256']:raise ValueError('Invalid reviewed image hash')
                image=Image.open(io.BytesIO(encoded))
                if image.format!='PNG' or image.width>3601 or image.height>3601:raise ValueError('Invalid reviewed reference image')
                bitmap=page.render(scale=SCALE);actual=bitmap.to_pil().convert('L');actual.save(output/f'page-{i+1}.png')
                if abs(actual.width-image.width)>1 or abs(actual.height-image.height)>1:raise ValueError('Raster canvas dimensions changed')
                aligned=Image.new('L',image.size,255);aligned.paste(actual,(0,0))
                check=compare_ink(aligned,image);check.update(page=i+1,size_pt=dimensions,referenceSha256=ref['sha256']);result['checks'].append(check)
            finally:
                if bitmap is not None:bitmap.close()
                page.close()
    (output/'inspection.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    return result
