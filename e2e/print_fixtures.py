"""Synthetic print cases, derived from the existing engine-generated table fixture."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from xml.dom import minidom
import zipfile
from table_height_fixtures import generate

TEXTS=[f'Row {i} Hg1234567' for i in range(5)]

def write_parts(path,parts):
    if path.exists():raise ValueError('Refusing to overwrite a print fixture')
    with zipfile.ZipFile(path,'w') as archive:
        for name,data in parts.items():
            archive.writestr(name,data,compress_type=zipfile.ZIP_STORED if name=='mimetype' else zipfile.ZIP_DEFLATED)

def build(folder:Path):
    generate(folder)
    cases=[]
    for spacing in (-300,0,600):
        source=folder/f'table-spacing-{spacing}.hwpx'
        with zipfile.ZipFile(source) as archive:
            parts={name:archive.read(name) for name in archive.namelist()}
        section=minidom.parseString(parts['Contents/section0.xml'])
        table=section.getElementsByTagName('hp:tbl')[0]
        for i,element in enumerate(table.getElementsByTagName('hp:t')):
            if i>=5:raise ValueError('Unexpected table text count')
            while element.firstChild:element.removeChild(element.firstChild)
            element.appendChild(section.createTextNode(TEXTS[i]))
        header=minidom.parseString(parts['Contents/header.xml'])
        for font in header.getElementsByTagName('hh:font'):
            font.setAttribute('face','Arial')
        parts['Contents/header.xml']=header.toxml(encoding='UTF-8')
        parts['Contents/section0.xml']=section.toxml(encoding='UTF-8')
        name=f'print-table-{spacing}.hwpx';write_parts(folder/name,parts)
        cases.append({'name':f'table-{spacing}','file':name,'pages':[{
            'size_pt':[595.28,841.86],'markers':TEXTS,'ink_pairs':[[TEXTS[0][:8],TEXTS[4][:8]]]}]})
    with zipfile.ZipFile(folder/'print-table-0.hwpx') as archive:
        parts={name:archive.read(name) for name in archive.namelist()}
    section=minidom.parseString(parts['Contents/section0.xml'])
    paragraphs=[n for n in section.documentElement.childNodes if n.nodeType==n.ELEMENT_NODE and n.tagName=='hp:p']
    first=paragraphs[0]
    for p in paragraphs[1:]:section.documentElement.removeChild(p)
    for run in list(first.getElementsByTagName('hp:run')):
        if not run.getElementsByTagName('hp:secPr'):run.parentNode.removeChild(run)
    for node in list(first.getElementsByTagName('hp:linesegarray')):node.parentNode.removeChild(node)
    for i in range(2):
        p=first if i==0 else section.createElement('hp:p')
        if i:
            for k,v in [('id',str(i)),('paraPrIDRef','0'),('styleIDRef','0'),('pageBreak','1'),('columnBreak','0'),('merged','0')]:p.setAttribute(k,v)
            section.documentElement.appendChild(p)
        run=section.createElement('hp:run');run.setAttribute('charPrIDRef','0')
        t=section.createElement('hp:t');t.appendChild(section.createTextNode(f'OpenGeul printed page {i+1} Hg 0123456789'))
        run.appendChild(t);p.appendChild(run)
    parts['Contents/section0.xml']=section.toxml(encoding='UTF-8')
    write_parts(folder/'print-multipage.hwpx',parts)
    cases.append({'name':'multipage','file':'print-multipage.hwpx','pages':[
        {'size_pt':[595.28,841.86],'markers':[f'OpenGeul printed page {i+1} Hg 0123456789']} for i in range(2)]})
    (folder/'print-cases.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return cases

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('folder',type=Path)
    build(p.parse_args().folder.resolve())
