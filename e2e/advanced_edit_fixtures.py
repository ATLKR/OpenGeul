"""Author-owned nested INPUT from two owned real WASM-exported grids.

XML authoring is for fixtures only; UI cases never invoke an engine/private bridge.
"""
import copy
import hashlib
import json
from pathlib import Path
import sys
import zipfile
import xml.etree.ElementTree as E
from advanced_edit_oracle import q, one, inspect_advanced_hwpx


def generate(folder):
    source = folder/'owned-grid.hwpx'
    with zipfile.ZipFile(source) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    section = E.fromstring(parts['Contents/section0.xml'])
    outer = next(section.iter(q('tbl')))
    inner = copy.deepcopy(outer)
    inner.set('id','2000002'); outer.set('id','2000001')
    for table, prefix, width, heights in ((outer,'OUTER',48000,(18000,6000)),
                                          (inner,'INNER',18000,(4000,4000))):
        one(table,'sz').set('width',str(width)); one(table,'sz').set('height',str(sum(heights)))
        for row in table.findall(q('tr')):
            for cell in row.findall(q('tc')):
                addr=one(cell,'cellAddr'); r,c=int(addr.get('rowAddr')),int(addr.get('colAddr'))
                one(cell,'cellSz').set('width',str(width//2)); one(cell,'cellSz').set('height',str(heights[r]))
                for n in cell.iter(q('t')): n.text=f'{prefix}-{r}{c}'
    cell=outer.find(f"{q('tr')}/{q('tc')}")
    sub=one(cell,'subList')
    paragraph=copy.deepcopy(one(sub,'p')); paragraph.set('id','500')
    for node in list(paragraph): paragraph.remove(node)
    run=E.SubElement(paragraph,q('run'),charPrIDRef='0'); run.append(inner)
    sub.append(paragraph)
    for paragraph in section.iter(q('p')):
        for lines in paragraph.findall(q('linesegarray')): paragraph.remove(lines)
    parts['Contents/section0.xml']=E.tostring(section,encoding='utf-8',xml_declaration=True)
    target=folder/'owned-nested.hwpx'
    if target.exists(): raise ValueError('Refusing to overwrite immutable nested source')
    with zipfile.ZipFile(target,'w') as archive:
        for name,data in parts.items():
            archive.writestr(name,data,compress_type=zipfile.ZIP_STORED if name=='mimetype' else zipfile.ZIP_DEFLATED)
    result=inspect_advanced_hwpx(target)
    assert set(result['tables'])=={'s0/body/t0','s0/body/t0/r0c0/t0'}
    provenance=json.loads((folder/'provenance.json').read_text())
    provenance['generated'][target.name]=hashlib.sha256(target.read_bytes()).hexdigest()
    provenance['nestedAuthoring']={'from':source.name,'sourceSha256':hashlib.sha256(source.read_bytes()).hexdigest(),
        'method':'owned XML nesting; no personal corpus','outerWidthHU':48000,'outerRowsHU':[18000,6000],
        'innerWidthHU':18000,'innerRowsHU':[4000,4000]}
    (folder/'provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
    return target

if __name__=='__main__': print(generate(Path(sys.argv[1])))
