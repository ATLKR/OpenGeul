"""Draft independent scoped ZIP/XML/Pillow/PDFium oracles; no rhwp calls."""
from __future__ import annotations
import base64,copy,hashlib,io,math,re,zipfile
from pathlib import Path,PurePosixPath
import xml.etree.ElementTree as ET
CAP=20*1024*1024

def require(value,message):
    if not value:raise ValueError(message)
def local(node):return node.tag.rsplit('}',1)[-1]
def sha(data):return hashlib.sha256(data).hexdigest()
def number(value):
    require(isinstance(value,str) and re.fullmatch(r'-?\d+(?:\.\d+)?',value),'Invalid XML number')
    result=float(value);require(math.isfinite(result),'Nonfinite XML number');return result

def checkerboard():
    from PIL import Image
    image=Image.new('RGB',(32,16));colors=((230,40,40),(30,80,220))
    for y in range(16):
        for x in range(32):image.putpixel((x,y),colors[(x//4+y//4)%2])
    out=io.BytesIO();image.save(out,format='PNG');return out.getvalue()

def image_pattern(raw,expected):
    from PIL import Image
    with Image.open(io.BytesIO(raw)) as img:
        img.load();image=img.convert('RGB')
    require(list(image.size)==expected['picturePixels'],'Wrong independent image dimensions')
    tile=expected['pictureTilePixels'];colors=expected['pictureColors']
    require(all(image.getpixel((x,y))==tuple(colors[(x//tile+y//tile)%2]) for y in range(image.height) for x in range(image.width)),
            'Wrong independent checkerboard pixel pattern')
    return {'sha256':sha(raw),'width':image.width,'height':image.height}

def inspect_hwpx(path,expected):
    raw=Path(path).read_bytes();require(0<len(raw)<=CAP and raw.startswith(b'PK\x03\x04'),'Bounded HWPX ZIP required')
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        entries=z.infolist();names=[e.filename for e in entries]
        require(entries and names[0]=='mimetype' and entries[0].compress_type==zipfile.ZIP_STORED and z.read('mimetype')==b'application/hwp+zip','Invalid first uncompressed mimetype')
        require(len(names)==len(set(names)) and sum(e.file_size for e in entries)<=CAP,'Duplicate/unbounded ZIP members')
        require(all(e.filename==e.orig_filename and not e.filename.startswith('/') and '\\' not in e.filename and ':' not in e.filename and all(p not in ('','..','.') for p in e.filename.split('/')) for e in entries),'Unsafe ZIP members')
        require({'Contents/section0.xml','Contents/header.xml','Contents/content.hpf'}<=set(names),'Missing HWPX structure')
        trees={}
        for name in names:
            if name.endswith(('.xml','.hpf','.rdf')):
                value=z.read(name);require(b'<!DOCTYPE' not in value.upper() and b'<!ENTITY' not in value.upper(),'XML entity declaration forbidden');trees[name]=ET.fromstring(value)
        sections=[n for n in names if re.fullmatch(r'Contents/section\d+\.xml',n)]
        require(sections==['Contents/section0.xml'],'Expected one explicit fixture section')
        section=trees[sections[0]];header=trees['Contents/header.xml'];parts={}
        for n in trees['Contents/content.hpf'].iter():
            if local(n)=='item':
                require(n.get('id') and n.get('id') not in parts,'Duplicate/missing package item ID');parts[n.get('id')]=n.get('href')
        styles={}
        for n in header.iter():
            if local(n)=='charPr':
                require(n.get('id') is not None and n.get('id') not in styles,'Duplicate/missing character style ID');styles[n.get('id')]={'italic':any(local(c)=='italic' for c in n),'textColor':n.get('textColor','#000000').upper()}
        fields=[];field_ids=set()
        def paragraph_text(paragraph,location):
            active=[];text=[];semantic=[]
            def walk(n,current_style=None):
                tag=local(n)
                if tag in ('tbl','pic'):return
                if tag=='fieldBegin':
                    require(n.get('name') in ('CUSTOMER','ITEM') and n.get('type')=='CLICK_HERE' and n.get('id') and n.get('id') not in field_ids,'Unexpected field type/name or duplicate ID');field_ids.add(n.get('id'))
                    active.append({'id':n.get('id'),'name':n.get('name'),'value':'',**location});return
                if tag=='fieldEnd':
                    require(active and n.get('beginIDRef')==active[-1]['id'],'Unbalanced field reference')
                    field=active.pop();field.pop('id');fields.append(field);return
                if tag=='t':
                    value=''.join(n.itertext());text.append(value)
                    if value:
                        require(current_style is not None,'Visible text has no resolved style')
                        if not semantic or semantic[-1]!=current_style:semantic.append(current_style)
                    for f in active:f['value']+=value
                    return
                if tag=='run' and n.get('charPrIDRef'):
                    require(n.get('charPrIDRef') in styles,'Dangling character style')
                    current_style=styles[n.get('charPrIDRef')]
                for child in n:walk(child,current_style)
            walk(paragraph);require(not active,'Unclosed field');return ''.join(text),semantic
        body=[];body_styles=[];cells={};cell_styles={};tables=[];table_owners=[];picture_owners={}
        for index,p in enumerate(n for n in section if local(n)=='p'):
            value,semantic=paragraph_text(p,{'container':'body','paragraph':index});body.append(value);body_styles.append(semantic)
            controls=[]
            def body_controls(node):
                for child in node:
                    tag=local(child)
                    if tag in ('tbl','pic'):controls.append(child)
                    elif tag in ('run','ctrl'):body_controls(child)
            body_controls(p)
            for control,node in enumerate(controls):
                owner={'section':0,'paragraph':index,'control':control}
                if local(node)=='pic':picture_owners[id(node)]=owner
            for table in p.iter():
                if local(table)!='tbl':continue
                require(table in controls,'A nested table is not a body control')
                table_owners.append({'section':0,'paragraph':index,'control':controls.index(table)})
                tables.append(table);require(table.get('rowCnt')=='2' and table.get('colCnt')=='2','Wrong table grid')
                for cell in table.iter():
                    if local(cell)!='tc':continue
                    addr=next((n for n in cell if local(n)=='cellAddr'),None);span=next((n for n in cell if local(n)=='cellSpan'),None)
                    require(addr is not None and span is not None and span.get('rowSpan')==span.get('colSpan')=='1','Missing/merged cell address')
                    row,col=int(addr.get('rowAddr')),int(addr.get('colAddr'));key=f'{row},{col}'
                    require(row in (0,1) and col in (0,1) and key not in cells,'Duplicate/out-of-range cell')
                    values=[];semantic=[]
                    sublist=next((n for n in cell if local(n)=='subList'),None);require(sublist is not None,'Cell paragraph subList missing')
                    for cp in sublist:
                        if local(cp)=='p':
                            value,sty=paragraph_text(cp,{'container':'cell','row':row,'col':col});values.append(value);semantic+=sty
                    cells[key]='\n'.join(values);cell_styles[key]=[sty for i,sty in enumerate(semantic) if i==0 or semantic[i-1]!=sty]
        require(len(tables)==1 and set(cells)=={'0,0','0,1','1,0','1,1'},'Expected exactly one complete 2x2 table')
        # Field order follows body then table document traversal, matching native inventory.
        fields.sort(key=lambda f:(0 if f['container']=='body' else 1,f.get('paragraph',99),f.get('row',0),f.get('col',0)))
        pictures=[]
        for pic in section.iter():
            if local(pic)!='pic':continue
            img=next((n for n in pic.iter() if local(n)=='img'),None);sz=next((n for n in pic if local(n)=='sz'),None);pos=next((n for n in pic if local(n)=='pos'),None)
            require(img is not None and sz is not None and pos is not None,'Missing picture image/geometry')
            ref=img.get('binaryItemIDRef');name=parts.get(ref)
            require(isinstance(name,str) and name.startswith('BinData/') and name in names,'Dangling BinData reference')
            proof=image_pattern(z.read(name),expected)
            require(id(pic) in picture_owners,'Picture is outside an owned body paragraph')
            proof.update(picture_owners[id(pic)])
            proof.update(sizeHu=[number(sz.get('width')),number(sz.get('height'))],positionHu=[number(pos.get('horzOffset')),number(pos.get('vertOffset'))])
            require(pos.get('horzRelTo')==pos.get('vertRelTo')=='PAPER','Picture must use explicit paper coordinates')
            wanted=expected['pictureMm'];require(all(abs(v-mm*7200/25.4)<=2 for v,mm in zip(proof['positionHu']+proof['sizeHu'],wanted)),'Picture geometry differs from predeclared rectangle')
            pictures.append(proof)
        require(len(pictures)==1,'Expected exactly one decoded picture')
        page=next((n for n in section.iter() if local(n)=='pagePr'),None)
        require(page is not None,'Missing explicit page geometry');page_hu=[number(page.get('width')),number(page.get('height'))]
        require(all(abs(v-mm*7200/25.4)<=3 for v,mm in zip(page_hu,expected['pageMm'])),'Expected A4 page geometry')
        return {'body':body,'bodyStyles':body_styles,'tableOwners':table_owners,'cells':cells,'fields':fields,'styles':cell_styles,'pictures':pictures,'pageHu':page_hu}

def verify_original(value,expected):
    require(value['body']==expected['bodyParagraphs'] and value['body'][0].count(expected['query'])==2,'Original explicit body/field paragraph inventory differs')
    require(value['cells']==expected['cells'] and value['fields']==expected['fields'],'Original cell/field manifest differs')
    require(value['tableOwners']==[expected['tableLocation']] and
            [{k:p[k] for k in ('section','paragraph','control')} for p in value['pictures']]==[expected['pictureLocation']],
            'Original table/picture ownership differs')
    require(value['bodyStyles']==[[expected['bodyStyle']] if text else [] for text in expected['bodyParagraphs']],
            'Original body semantic style differs')
    style=value['styles'].get(expected['styleCell']);require(style and all(s=={'italic':True,'textColor':'#123456'} for s in style),'Declared italic/color style missing')

def compare_structure(before,after,*,cells=None,fields=None,insert=None,keep_style=False):
    wanted=copy.deepcopy(before);cells=cells or {};fields=fields or {}
    for key,value in cells.items():
        require(key in wanted['cells'],'Target cell missing');wanted['cells'][key]=value
        if not keep_style and key in wanted['styles']:
            wanted['styles'][key]=[{'italic':False,'textColor':'#000000'}]
    for index,value in fields.items():
        field=wanted['fields'][index];old=field['value'];field['value']=value
        if field['container']=='body':
            para=field['paragraph'];require(wanted['body'][para].count(old)==1,'Unambiguous field scope required');wanted['body'][para]=wanted['body'][para].replace(old,value,1)
        else:
            key=f"{field['row']},{field['col']}";require(wanted['cells'][key].count(old)==1,'Unambiguous cell field scope required');wanted['cells'][key]=wanted['cells'][key].replace(old,value,1)
    if insert:
        p=insert['paragraph'];offset=insert['offset'];text=wanted['body'][p];wanted['body'][p]=text[:offset]+insert['text']+text[offset:]
    require(after==wanted,'Independent scoped structure/style/image/body preservation failed')

def inspect_svg(path,expected):
    raw=Path(path).read_bytes();require(0<len(raw)<=CAP and b'<!DOCTYPE' not in raw.upper() and b'<!ENTITY' not in raw.upper(),'Bounded safe SVG required')
    root=ET.fromstring(raw)
    for axis in ('width','height'):
        dimension=root.get(axis,'');match=re.fullmatch(r'(\d+(?:\.\d+)?)(?:px|pt|mm|cm|in)?',dimension);require(match and float(match.group(1))>0,'SVG explicit positive dimensions missing')
    require(root.tag=='{http://www.w3.org/2000/svg}svg','SVG namespace/root differs')
    box=root.get('viewBox','').split();require(len(box)==4,'SVG viewBox absent');box=[float(v) for v in box]
    require(all(math.isfinite(v) for v in box) and box[2]>0 and box[3]>0 and abs(box[2]/box[3]-210/297)<.01,'SVG positive A4 viewport differs')
    images=[]
    for node in root.iter():
        if local(node)=='image':
            href=node.get('href') or node.get('{http://www.w3.org/1999/xlink}href')
            require(isinstance(href,str) and href.startswith('data:image/png;base64,'),'SVG must embed its owned PNG')
            images.append(image_pattern(base64.b64decode(href.split(',',1)[1],validate=True),expected))
    require(len(images)==1,'SVG must contain exactly one actual owned checkerboard image')
    require(any(local(n) in ('path','text','rect','line') for n in root.iter()),'SVG has no real rendered primitives')
    return {'sha256':sha(raw),'bytes':len(raw),'imageSha256':images[0]['sha256'],'viewBox':box}

def raster_check(image,expected,scale):
    image=image.convert('RGB');w,h=image.size;require(abs(w-210/25.4*72*scale)<=3 and abs(h-297/25.4*72*scale)<=3,'Raster is not expected A4 size')
    gray=image.convert('L');require(sum(gray.histogram()[:180])>=500,'Blank or near-blank renderer raster')
    x,y,width,height=expected['pictureMm'];px=x/25.4*72*scale;py=y/25.4*72*scale;pw=width/25.4*72*scale;ph=height/25.4*72*scale
    cols=expected['picturePixels'][0]//4;rows=expected['picturePixels'][1]//4
    for row in range(rows):
        for col in range(cols):
            color=image.getpixel((round(px+(col+.5)*pw/cols),round(py+(row+.5)*ph/rows)))
            require(max(abs(a-b) for a,b in zip(color,expected['pictureColors'][(row+col)%2]))<45,'Checkerboard position/scale/colors absent from actual raster')
    return {'size':[w,h],'checkerboardSamples':rows*cols,'nonblank':True}

def inspect_png(path,expected):
    from PIL import Image
    raw=Path(path).read_bytes();require(0<len(raw)<=CAP and raw.startswith(b'\x89PNG\r\n\x1a\n'),'Actual bounded PNG required')
    with Image.open(io.BytesIO(raw)) as image:image.load();proof=raster_check(image,expected,96/72)
    return {'sha256':sha(raw),'bytes':len(raw),**proof}

def inspect_pdf(path,expected):
    import pypdfium2 as pdfium
    raw=Path(path).read_bytes();require(0<len(raw)<=CAP and raw.startswith(b'%PDF-') and b'%%EOF' in raw[-2048:],'Actual complete bounded PDF required')
    doc=pdfium.PdfDocument(raw)
    try:
        require(len(doc)==1,'Expected one rendered PDF page');page=doc[0];text=page.get_textpage();bitmap=None
        try:
            width,height=page.get_size();require(abs(width-210/25.4*72)<2 and abs(height-297/25.4*72)<2,'PDF paper size differs')
            value=text.get_text_range();markers=[expected['body'].split(' FIND-OWNED')[0],expected['tail'],*expected['cells'].values()]
            require(all(value.count(marker)==1 for marker in markers) and value.count(expected['query'])==2 and all(value.count(f['value'])==1 for f in expected['fields']),'PDF searchable body/table/field marker inventory differs')
            bitmap=page.render(scale=2);image=bitmap.to_pil().convert('RGB');proof=raster_check(image,expected,2)
            # Independently locate each unique cell marker through PDFium and require
            # visible ink in its text rectangle, beyond the checkerboard-only raster.
            cells=0
            for marker in expected['cells'].values():
                search=text.search(marker,match_case=True)
                try:
                    match=search.get_next();require(match is not None and search.get_next() is None,'PDF cell marker search is absent/duplicated');index,count=match
                    rectangles=text.count_rects(index,count);require(rectangles>0,'PDF cell marker has no real text geometry')
                    ink=0
                    for i in range(rectangles):
                        left,bottom,right,top=text.get_rect(i);require(0<=left<right<=width and 0<=bottom<top<=height,'PDF cell marker rectangle is out of page')
                        crop=image.crop((max(0,int(left*2)-1),max(0,int((height-top)*2)-1),min(image.width,math.ceil(right*2)+1),min(image.height,math.ceil((height-bottom)*2)+1))).convert('L');ink+=sum(crop.histogram()[:180])
                    require(ink>=5,'PDF table cell text is not visibly rendered');cells+=1
                finally:search.close()
            proof['visibleTableCellMarkers']=cells
            return {'sha256':sha(raw),'bytes':len(raw),'pageCount':1,'markers':len(markers),**proof}
        finally:
            if bitmap:bitmap.close()
            text.close();page.close()
    finally:doc.close()
