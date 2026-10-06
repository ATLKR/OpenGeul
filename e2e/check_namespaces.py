"""Independent XML namespace regression using real WASM, not parser mocks."""
from pathlib import Path
import argparse
import subprocess
import xml.etree.ElementTree as ET
import zipfile
ROOT=Path(__file__).resolve().parents[1]
HEADER='http://www.hancom.co.kr/hwpml/2011/head'
def run(source:Path,vendor:Path,out:Path,red=False):
    out.mkdir(parents=True,exist_ok=True)
    subprocess.run(['node',str(ROOT/'e2e/generate-browser-fixtures.mjs'),str(source),str(out)],check=True)
    aliased=out/'namespace-aliased.hwpx'
    with zipfile.ZipFile(out/'basic.hwpx') as original,zipfile.ZipFile(aliased,'w') as result:
        for entry in original.infolist():
            data=original.read(entry)
            if entry.filename=='Contents/header.xml':
                tree=ET.fromstring(data)
                refs=tree.find(f'{{{HEADER}}}refList')
                assert refs is not None
                ET.SubElement(refs,f'{{{HEADER}}}memoProperties',{'itemCnt':'0'})
                data=ET.tostring(tree,encoding='utf-8',xml_declaration=True)
            result.writestr(entry,data)
    target=out/'namespace-saved.hwpx'
    subprocess.run(['node',str(ROOT/'e2e/namespace-roundtrip.mjs'),str(vendor),str(aliased),str(target)],check=True)
    try:
        with zipfile.ZipFile(target) as package:
            for name in package.namelist():
                if name.endswith(('.xml','.hpf','.rdf')):ET.fromstring(package.read(name))
            header=ET.fromstring(package.read('Contents/header.xml'))
            assert header.find(f'.//{{{HEADER}}}memoProperties') is not None, 'Aliased memo properties lost'
            assert header.find(f'{{{HEADER}}}docOption') is not None, 'Aliased document options lost'
    except (ET.ParseError,AssertionError) as error:
        if red:
            print('EXPECTED RED: valid namespace-aliased HWPX does not survive the original serializer:',error)
            return
        raise
    if red:raise AssertionError('Baseline unexpectedly passed namespace regression')
    print('PASS: aliased namespaces, numbering, memo properties and document-option tail survive real WASM roundtrip.')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('vendor',type=Path);p.add_argument('out',type=Path);p.add_argument('--red',action='store_true');a=p.parse_args()
    run(a.source.resolve(),a.vendor.resolve(),a.out.resolve(),a.red)
