"""Independent parser unit inputs authored here; never native fixture/renderer success evidence."""
import copy,html,io,json,re,sys,tempfile,unittest,zipfile
from pathlib import Path
HERE=Path(__file__).resolve().parents[1]/'e2e/structured_cli_mcp'
sys.path.insert(0,str(HERE))
import structured_oracle as oracle

def authored_section(e):
    def t(value,style='0'):return '<run charPrIDRef="'+style+'"><t>'+html.escape(value)+'</t></run>'
    def field(name,value,i):
        # The memo's internal paragraph is metadata, never a visible cell paragraph.
        return '<run charPrIDRef="0"><ctrl><fieldBegin type="CLICK_HERE" id="'+str(i)+'" name="'+name+'"><memo><subList><p>'+t('NOT-VALUE')+'</p></subList></memo></fieldBegin></ctrl><t>'+value+'</t><ctrl><fieldEnd beginIDRef="'+str(i)+'"/></ctrl></run>'
    cells=[]
    for row in range(2):
        for col in range(2):
            key=f'{row},{col}';value=e['cells'][key]
            content=t('CELL-R1-C1|')+field('ITEM','I-CELL',3) if key=='1,1' else t(value,'1' if key=='0,1' else '0')
            cells.append('<tc><subList><p>'+content+'</p></subList><cellAddr rowAddr="'+str(row)+'" colAddr="'+str(col)+'"/><cellSpan rowSpan="1" colSpan="1"/></tc>')
    return '<sec><p>'+t(e['body'])+'<pagePr width="59528" height="84189"/></p><p>'+t(e['tail'])+'</p><p>'+t('CUSTOMER:')+field('CUSTOMER','C-INIT',1)+'</p><p>'+t('ITEM:')+field('ITEM','I-BODY',2)+'</p><p><tbl rowCnt="2" colCnt="2">'+''.join(cells)+'</tbl></p><p><pic><sz width="11339" height="5669"/><pos horzRelTo="PAPER" vertRelTo="PAPER" horzOffset="8504" vertOffset="28346"/><img binaryItemIDRef="image1"/></pic></p></sec>'

def authored_zip(path,e,section=None,png=None,extra=None,header=None):
    with zipfile.ZipFile(path,'w') as z:
        z.writestr('mimetype',b'application/hwp+zip',compress_type=zipfile.ZIP_STORED)
        z.writestr('Contents/section0.xml',section or authored_section(e))
        z.writestr('Contents/header.xml',header or '<head><charPr id="0" textColor="#000000"/><charPr id="1" textColor="#123456"><italic/></charPr></head>')
        z.writestr('Contents/content.hpf','<package><manifest><item id="image1" href="BinData/image1.png"/></manifest></package>')
        z.writestr('BinData/image1.png',png or oracle.checkerboard())
        if extra:z.writestr(*extra)

class ScopedXmlTests(unittest.TestCase):
    def setUp(self):self.e=json.loads((HERE/'expected.json').read_bytes())
    def test_saved_structure_keeps_table_picture_and_body_style_ownership(self):
        original=authored_section(self.e)
        moved_table=re.sub(r'<p>(<tbl.*?</tbl>)</p><p>(<pic.*?</pic>)</p>',r'<p>\2</p><p>\1</p>',original)
        picture=re.search(r'<pic>.*?</pic>',original).group()
        moved_picture=original.replace(picture,'').replace('<sec><p>','<sec><p>'+picture,1)
        restyled_body=original.replace('<run charPrIDRef="0">','<run charPrIDRef="1">',1)
        for section in (moved_table,moved_picture,restyled_body):
            with self.subTest(section=section),tempfile.TemporaryDirectory() as t:
                before=Path(t)/'before.hwpx';after=Path(t)/'after.hwpx'
                authored_zip(before,self.e);authored_zip(after,self.e,section)
                baseline=oracle.inspect_hwpx(before,self.e)
                with self.assertRaises(ValueError):
                    value=oracle.inspect_hwpx(after,self.e)
                    oracle.compare_structure(baseline,value)
    def test_original_fixture_rejects_shifted_controls_and_body_style(self):
        original=authored_section(self.e)
        moved_table=re.sub(r'<p>(<tbl.*?</tbl>)</p><p>(<pic.*?</pic>)</p>',r'<p>\2</p><p>\1</p>',original)
        restyled_body=original.replace('<run charPrIDRef="0">','<run charPrIDRef="1">',1)
        for section in (moved_table,restyled_body):
            with self.subTest(section=section),tempfile.TemporaryDirectory() as t:
                path=Path(t)/'input.hwpx';authored_zip(path,self.e,section)
                with self.assertRaises(ValueError):oracle.verify_original(oracle.inspect_hwpx(path,self.e),self.e)
    def test_table_or_picture_nested_in_textbox_is_not_a_body_control(self):
        original=authored_section(self.e)
        for tag in ('tbl','pic'):
            control=re.search('<'+tag+r'.*?</'+tag+'>',original).group()
            nested='<rect><drawText><subList><p>'+control+'</p></subList></drawText></rect>'
            with self.subTest(tag=tag),tempfile.TemporaryDirectory() as t:
                path=Path(t)/'nested.hwpx';authored_zip(path,self.e,original.replace(control,nested))
                with self.assertRaises(ValueError):oracle.verify_original(oracle.inspect_hwpx(path,self.e),self.e)
    def test_scoped_values_ignore_field_metadata_paragraphs(self):
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/'authored.hwpx';authored_zip(path,self.e);value=oracle.inspect_hwpx(path,self.e);oracle.verify_original(value,self.e)
            self.assertEqual(value['cells']['1,1'],'CELL-R1-C1|I-CELL');self.assertEqual(value['fields'][2]['value'],'I-CELL');self.assertNotIn('NOT-VALUE',value['body'])
    def test_duplicate_field_id_broken_end_and_cell_address_fail(self):
        section=authored_section(self.e)
        for bad in (section.replace('id="3"','id="2"'),section.replace('beginIDRef="3"','beginIDRef="77"'),section.replace('rowAddr="1" colAddr="1"','rowAddr="0" colAddr="0"'),section.replace('binaryItemIDRef="image1"','binaryItemIDRef="absent"'),section.replace('<sec>','<!DOCTYPE sec [<!ENTITY x "value">]><sec>')):
            with self.subTest(bad=bad),tempfile.TemporaryDirectory() as t:
                path=Path(t)/'bad.hwpx';authored_zip(path,self.e,bad)
                with self.assertRaises(ValueError):oracle.inspect_hwpx(path,self.e)
    def test_original_marker_field_or_style_loss_fails_manifest(self):
        original=authored_section(self.e)
        variants=[original.replace('CELL-R1-C0','WRONG-CELL'),original.replace('I-BODY','OTHER'),original.replace('charPrIDRef="1"','charPrIDRef="0"')]
        for bad in variants:
            with self.subTest(bad=bad),tempfile.TemporaryDirectory() as t:
                path=Path(t)/'bad.hwpx';authored_zip(path,self.e,bad);value=oracle.inspect_hwpx(path,self.e)
                with self.assertRaises(ValueError):oracle.verify_original(value,self.e)
    def test_duplicate_style_and_unsafe_zip_member_fail(self):
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/'bad.hwpx';authored_zip(path,self.e,header='<head><charPr id="0"/><charPr id="0"/></head>')
            with self.assertRaises(ValueError):oracle.inspect_hwpx(path,self.e)
            path.unlink();authored_zip(path,self.e,extra=('../escaped.xml','<x/>'))
            with self.assertRaises(ValueError):oracle.inspect_hwpx(path,self.e)
    def test_serialization_run_splits_do_not_change_semantic_style(self):
        original=authored_section(self.e);split=original.replace('<t>CELL-R0-C1</t>','<t>CELL-R0</t><t>-C1</t>')
        with tempfile.TemporaryDirectory() as t:
            a=Path(t)/'a.hwpx';b=Path(t)/'b.hwpx';authored_zip(a,self.e,original);authored_zip(b,self.e,split)
            before=oracle.inspect_hwpx(a,self.e);after=oracle.inspect_hwpx(b,self.e);oracle.compare_structure(before,after)

if __name__=='__main__':unittest.main()
