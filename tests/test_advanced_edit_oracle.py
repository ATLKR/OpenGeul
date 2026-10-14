import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'e2e'))
"""Offline policy tests of real owned containers and corrupt variants, not GUI."""
import ast
import hashlib
import io
import json
from pathlib import Path
import unittest
import zipfile
import xml.etree.ElementTree as E
from advanced_edit_oracle import (q,one,inspect_advanced_hwpx,assert_grid,assert_field,
    assert_equation,assert_notes,assert_page,assert_textbox,require_body,assert_population)
from supported_feature_oracle import inspect_supported_hwpx

HERE=Path(__file__).resolve().parents[1]/'e2e'
FIX=Path(__file__).resolve().parent/'fixtures'/'advanced-owned'
GRID={(r,c):((1,1),f'ADV-CELL-{r}{c}',(f'ADV-CELL-{r}{c}',)) for r in range(2) for c in range(2)}
MERGED={(0,0):((1,2),'ADV-CELL-00ADV-CELL-01',('ADV-CELL-00','ADV-CELL-01')),(1,0):GRID[(1,0)],(1,1):GRID[(1,1)]}
SPLIT={**GRID,(0,0):((1,1),'ADV-CELL-00ADV-CELL-01',('ADV-CELL-00','ADV-CELL-01')),(0,1):((1,1),'',('',))}


def inspect(name):return inspect_advanced_hwpx(FIX/(name+'.hwpx'))


def mutated(name,change):
    with zipfile.ZipFile(FIX/(name+'.hwpx')) as archive:
        parts={n:archive.read(n) for n in archive.namelist()}
    section=E.fromstring(parts['Contents/section0.xml']); change(section)
    parts['Contents/section0.xml']=E.tostring(section,encoding='utf-8',xml_declaration=True)
    data=io.BytesIO()
    with zipfile.ZipFile(data,'w') as archive:
        for name,raw in parts.items():archive.writestr(name,raw,compress_type=zipfile.ZIP_STORED if name=='mimetype' else zipfile.ZIP_DEFLATED)
    return inspect_advanced_hwpx(data.getvalue())


# Author-owned real prepared-WASM picture node, never personal source data.
# Source container 8058 bytes / SHA256
# 650e82a5f2d2b85459e802d2a57b50c9648fa56abdc45bbbcede63e6999dd4f8.
# insertPicture(0,0,10,'',owned 1x1 PNG,1000,1000,1,1,'png',description)
# was exported and reloaded by the fixed prepared production WASM; UI execution 0.
VALID_PICTURE_XML = '<ns0:pic xmlns:ns0="http://www.hancom.co.kr/hwpml/2011/paragraph" xmlns:ns1="http://www.hancom.co.kr/hwpml/2011/core" id="0" zOrder="1" numberingType="NONE" textWrap="SQUARE" textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" href="" groupLevel="0" instid="0" reverse="0"><ns0:offset x="0" y="0" /><ns0:orgSz width="1000" height="1000" /><ns0:curSz width="1000" height="1000" /><ns0:flip horizontal="0" vertical="0" /><ns0:rotationInfo angle="0" centerX="0" centerY="0" rotateimage="0" /><ns0:renderingInfo><ns1:transMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0" /><ns1:scaMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0" /><ns1:rotMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0" /></ns0:renderingInfo><ns0:imgRect><ns1:pt0 x="0" y="0" /><ns1:pt1 x="1000" y="0" /><ns1:pt2 x="1000" y="1000" /><ns1:pt3 x="0" y="1000" /></ns0:imgRect><ns0:imgClip left="0" right="75" top="0" bottom="75" /><ns0:inMargin left="0" right="0" top="0" bottom="0" /><ns0:imgDim dimwidth="75" dimheight="75" /><ns1:img binaryItemIDRef="image1" bright="0" contrast="0" effect="REAL_PIC" alpha="0" /><ns0:effects /><ns0:sz width="1000" widthRelTo="ABSOLUTE" height="1000" heightRelTo="ABSOLUTE" protect="0" /><ns0:pos treatAsChar="0" affectLSpacing="0" flowWithText="0" allowOverlap="0" holdAnchorAndSO="0" vertRelTo="PAPER" horzRelTo="PAPER" vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0" /><ns0:outMargin left="0" right="0" top="0" bottom="0" /><ns0:shapeComment>Author-owned 1x1 test pixel</ns0:shapeComment></ns0:pic>'

class AdvancedOracleTests(unittest.TestCase):
    def test_checkpoint_diagnostic_records_actual_owned_state_without_teaching_expectations(self):
        import advanced_edit_oracle as oracle
        import copy
        result=inspect('owned-field-filled')
        expected={'body_paragraphs':['FIELD-BODY-HEAD'],'pages':result['pages'],
                  'population':{'fields':1},'headers':[],'footers':[],'breaks':[]}
        original=copy.deepcopy(expected)
        result['paragraphs']['s0/body']=[''];result['body']=''
        record=oracle.checkpoint_diagnostic(result,phase='next-edit',saved_sha256='1'*64,
            input_sha256={'owned-field-filled.hwpx':'2'*64},helper_sha256={'advanced_edit_oracle.py':'3'*64},expected=expected)
        self.assertEqual(record['observed']['bodyParagraphs'],{'s0/body':['']})
        self.assertEqual(record['observed']['fields'][0]['value'],'ADV-VALUE')
        self.assertEqual(record['expectedCheckpoint'],original)
        self.assertEqual(expected,original)
        with self.assertRaisesRegex(ValueError,'body/paragraph'):
            oracle.assert_checkpoint(result,**expected)
        raw=json.dumps(record,ensure_ascii=False,indent=2).encode('utf-8')
        self.assertLessEqual(len(raw),64*1024)
        self.assertNotIn(b'Contents/section',raw);self.assertNotIn(b'base64',raw);self.assertNotIn(b'<hp:',raw)

    def test_checkpoint_diagnostic_has_a_hard_utf8_size_limit(self):
        import advanced_edit_oracle as oracle
        result=inspect('owned-nested')
        # Unexpected content is summarized under the fixed limit; expected state
        # remains the caller's declaration and is never read back from this JSON.
        result['paragraphs']['s0/body']=['가'*100000]
        for table in result['tables'].values():
            for cell in table['cells'].values():cell['paragraphs']=['가'*100000]
        record=oracle.checkpoint_diagnostic(result,phase='edited',saved_sha256='1'*64,
            input_sha256={},helper_sha256={},expected={'body_paragraphs':['']})
        self.assertLessEqual(len(json.dumps(record,ensure_ascii=False,indent=2).encode('utf-8')),64*1024)
        with self.assertRaisesRegex(ValueError,'metadata exceeds'):
            oracle.checkpoint_diagnostic(result,phase='edited',saved_sha256='1'*64,
                input_sha256={},helper_sha256={},expected={'body_paragraphs':['가'*100000]})

    def test_owned_package_provenance_is_immutable(self):
        provenance=json.loads((FIX/'provenance.json').read_text())
        for name,sha in provenance['generated'].items():
            self.assertEqual(hashlib.sha256((FIX/name).read_bytes()).hexdigest(),sha)

    def test_real_section_namespace_positive_and_wrong_namespace_negative(self):
        self.assertEqual(inspect('owned-blank')['body'],'')
        with self.assertRaisesRegex(ValueError,'namespace'):
            mutated('owned-blank',lambda root:setattr(root,'tag',q('sec')))

    def test_real_merge_and_split_anchor_text_and_full_occupancy(self):
        for name,wanted in [('owned-grid',GRID),('owned-merged',MERGED),('owned-split',SPLIT)]:
            table=assert_grid(inspect(name),'s0/body/t0',wanted)
            self.assertEqual((table['rows'],table['cols'],len(table['occupancy'])),(2,2,4))
        # Keep the existing simple rectangular oracle strict and unchanged.
        with self.assertRaisesRegex(ValueError,'dimensions'):
            inspect_supported_hwpx(FIX/'owned-merged.hwpx')

    def test_missing_coverage_overlap_outside_and_wrong_row_are_rejected(self):
        def cells(root):return list(root.iter(q('tc')))
        changes=[lambda root:one(cells(root)[0],'cellSpan').set('colSpan','1'),
                 lambda root:one(cells(root)[1],'cellAddr').set('rowAddr','0'),
                 lambda root:one(cells(root)[0],'cellSpan').set('colSpan','3'),
                 lambda root:one(cells(root)[0],'cellSpan').set('rowSpan','2')]
        for change in changes:
            with self.subTest(change=change),self.assertRaises(ValueError):mutated('owned-merged',change)

    def test_nested_ancestor_graph_keeps_outer_and_inner_text_separate(self):
        result=inspect('owned-nested')
        self.assertEqual(set(result['tables']),{'s0/body/t0','s0/body/t0/r0c0/t0'})
        for path,prefix in [('s0/body/t0','OUTER'),('s0/body/t0/r0c0/t0','INNER')]:
            expected={(r,c):((1,1),f'{prefix}-{r}{c}',(f'{prefix}-{r}{c}',)) for r in range(2) for c in range(2)}
            if prefix=='OUTER':expected[(0,0)]=((1,1),'OUTER-00',('OUTER-00',''))
            assert_grid(result,path,expected)
        def leak(root):
            texts=list(root.iter(q('t'))); texts[0].text='OUTER-00INNER-00'; texts[1].text=''
        bad=mutated('owned-nested',leak)
        with self.assertRaisesRegex(ValueError,'direct cell'):
            assert_grid(bad,'s0/body/t0',{(r,c):((1,1),f'OUTER-{r}{c}',(f'OUTER-{r}{c}','') if (r,c)==(0,0) else (f'OUTER-{r}{c}',)) for r in range(2) for c in range(2)})

    def test_field_value_guide_memo_and_body_ownership(self):
        for name,value in [('owned-field-guide',''),('owned-field-filled','ADV-VALUE')]:
            assert_field(inspect(name),name='ADV-NAME',guide='ADV-GUIDE',memo='ADV-MEMO',value=value,body=('FIELD-BODY-HEAD',))
        changes=[lambda root:next(root.iter(q('fieldEnd'))).set('beginIDRef','999'),
                 lambda root:next(root.iter(q('fieldBegin'))).set('id','x')]
        for change in changes:
            with self.assertRaises(ValueError):mutated('owned-field-filled',change)
        def duplicate_pair(root):
            import copy
            paragraph=root.findall(q('p'))[0]
            for run in list(paragraph.findall(q('run'))):paragraph.append(copy.deepcopy(run))
        with self.assertRaisesRegex(ValueError,'Duplicate field ID'):mutated('owned-field-filled',duplicate_pair)
        bad=mutated('owned-field-filled',lambda root:next(root.iter(q('stringParam'))).__setattr__('text','Clickhere:set:1:wrong'))
        with self.assertRaisesRegex(ValueError,'guide/memo'):
            assert_field(bad,name='ADV-NAME',guide='ADV-GUIDE',memo='ADV-MEMO',value='ADV-VALUE',body=('FIELD-BODY-HEAD',))

    def test_missing_duplicate_moved_markers_and_extra_controls_fail(self):
        for text in ('','FIELD-BODY-HEADFIELD-BODY-HEAD'):
            bad=mutated('owned-field-filled',lambda root:setattr(next(root.iter(q('t'))),'text',text))
            with self.assertRaisesRegex(ValueError,'Body marker'):require_body(bad,'FIELD-BODY-HEAD')
        result=inspect('owned-textbox')
        with self.assertRaisesRegex(ValueError,'Body marker'):require_body(result,'ADV-TEXTBOX')
        with self.assertRaisesRegex(ValueError,'population'):assert_population(result)

    def test_equation_script_reference_and_saved_geometry(self):
        result=inspect('owned-equation')
        eq=assert_equation(result,'x^2 + {1} over {2}',body=('EQUATION-BODY',),anchor=(0,13))
        self.assertEqual(eq['base_unit'],1000); self.assertGreater(min(eq['size']),100)
        bad=mutated('owned-equation',lambda root:next(root.iter(q('script'))).__setattr__('text','x^9'))
        with self.assertRaisesRegex(ValueError,'script'):assert_equation(bad,'x^2 + {1} over {2}',body=('EQUATION-BODY',))
        with self.assertRaisesRegex(ValueError,'reference'):assert_equation(result,'x^2 + {1} over {2}',body=('EQUATION-BODY',),anchor=(1,0))

    def test_note_kind_number_reference_and_direct_sublist_text(self):
        expected=[('footNote',' ADV-FOOTNOTE'),('endNote',' ADV-ENDNOTE')]
        assert_notes(inspect('owned-notes'),expected,body=('NOTE-BODY',),anchors=[(0,9),(0,9)])
        bad=mutated('owned-notes',lambda root:next(root.iter(q('footNote'))).set('number','2'))
        with self.assertRaisesRegex(ValueError,'number'):assert_notes(bad,expected,body=('NOTE-BODY',))
        result=inspect('owned-notes')
        with self.assertRaisesRegex(ValueError,'Body marker'):require_body(result,'ADV-FOOTNOTE')

    def test_page_hf_margins_and_break_ownership(self):
        verify=lambda r:assert_page(r,header='ADV-HEADER',footer='ADV-FOOTER',body=('PAGE-BODY-ONE','PAGE-BODY-TWO'))
        verify(inspect('owned-page'))
        changes=[lambda root:next(root.iter(q('margin'))).set('left','0'),
                 lambda root:next(root.iter(q('pagePr'))).set('landscape','WIDELY'),
                 lambda root:next(root.iter(q('header'))).set('applyPageType','ODD'),
                 lambda root:[p.set('pageBreak','0') for p in root.findall(q('p'))]]
        for change in changes:
            with self.assertRaises(ValueError):verify(mutated('owned-page',change))
        with self.assertRaisesRegex(ValueError,'Body marker'):require_body(inspect('owned-page'),'ADV-HEADER')

    def test_shape_is_independent_of_picture_or_table_and_body(self):
        result=inspect('owned-shape')
        assert_textbox(result,count=1,body=('SHAPE-BODY',),textbox=False)
        assert_textbox(inspect('owned-textbox'),count=1,text='ADV-TEXTBOX',body=('SHAPE-BODY',))
        with self.assertRaisesRegex(ValueError,'drawText'):assert_textbox(result,count=1,body=('SHAPE-BODY',))
        with self.assertRaises(ValueError):assert_textbox(result,count=0,body=('SHAPE-BODY',))
        bad=mutated('owned-shape',lambda root:next(root.iter(q('sz'))).set('width','1'))
        with self.assertRaisesRegex(ValueError,'physical'):assert_textbox(bad,count=1,body=('SHAPE-BODY',),textbox=False)

    def test_page_break_requires_each_body_marker_in_its_declared_paragraph(self):
        def moved(root):
            paras=root.findall(q('p'))
            first=next(paras[0].iter(q('t')))
            for node in paras[1].iter(q('t')):
                first.text=(first.text or '')+(node.text or '');node.text=''
        result=mutated('owned-page',moved)
        self.assertEqual(result['breaks'],[(0,1)])
        with self.assertRaisesRegex(ValueError,'paragraph'):
            assert_page(result,header='ADV-HEADER',footer='ADV-FOOTER',body=('PAGE-BODY-ONE','PAGE-BODY-TWO'))

    def test_note_text_cannot_hide_an_unexpected_paragraph_split(self):
        def split(root):
            import copy
            sub=one(next(root.iter(q('footNote'))),'subList');para=one(sub,'p')
            texts=list(para.iter(q('t')));text=''.join(n.text or '' for n in texts)
            for node in texts:node.text=''
            texts[0].text=text[:6]
            other=copy.deepcopy(para)
            for node in other.iter(q('t')):node.text=''
            next(other.iter(q('t'))).text=text[6:];sub.append(other)
        result=mutated('owned-notes',split)
        with self.assertRaisesRegex(ValueError,'paragraph'):
            assert_notes(result,[('footNote',' ADV-FOOTNOTE'),('endNote',' ADV-ENDNOTE')],body=('NOTE-BODY',),anchors=[(0,9),(0,9)])

    def test_equation_geometry_must_match_the_declared_10pt_script_frame(self):
        # Fixed layout intrinsic_size_hwp calculates 2712x2440 HU for both
        # x^2/x^3 + {1} over {2} at BaseUnit1000. Independent source inputs
        # exported by the prepared fixed WASM confirm those declared dimensions.
        for width,height in ((1,1),(2712,1),(1,2440),(2712,2441),(2713,2440)):
            def size(root):
                frame=one(next(root.iter(q('equation'))),'sz')
                frame.set('width',str(width));frame.set('height',str(height))
            result=mutated('owned-equation',size)
            with self.subTest(size=(width,height)),self.assertRaisesRegex(ValueError,'geometry'):
                assert_equation(result,'x^2 + {1} over {2}',body=('EQUATION-BODY',),anchor=(0,13))

    def test_real_picture_control_and_namespace_alias_cannot_hide_from_population(self):
        # XML namespace prefixes are aliases, not control identity. The copied
        # producer-verified picture is a real hp:pic rather than a renamed rect.
        for prefix in ('ns0','pictureAlias'):
            xml=VALID_PICTURE_XML.replace('ns0:',prefix+':').replace('xmlns:ns0=', 'xmlns:'+prefix+'=')
            def add(root):root.findall(q('p'))[0].findall(q('run'))[-1].append(E.fromstring(xml))
            with self.subTest(prefix=prefix),self.assertRaisesRegex(ValueError,'population'):
                assert_textbox(mutated('owned-textbox',add),count=1,text='ADV-TEXTBOX',body=('SHAPE-BODY',))

    def test_unknown_direct_control_cannot_silently_disappear(self):
        def add(root):
            ctrl=E.SubElement(root.findall(q('p'))[0].findall(q('run'))[-1],q('ctrl'))
            E.SubElement(ctrl,q('unrecognizedControl'))
        with self.assertRaisesRegex(ValueError,'population'):
            assert_textbox(mutated('owned-textbox',add),count=1,text='ADV-TEXTBOX',body=('SHAPE-BODY',))

    def test_body_marker_cannot_be_reassembled_across_paragraph_boundaries(self):
        def split(root):
            para=root.findall(q('p'))[0];node=next(para.iter(q('t')));text=node.text
            node.text=text[:6];other=E.SubElement(root,q('p'),dict(para.attrib))
            run=E.SubElement(other,q('run'),charPrIDRef='0');E.SubElement(run,q('t')).text=text[6:]
        result=mutated('owned-equation',split)
        with self.assertRaisesRegex(ValueError,'Body marker'):
            assert_equation(result,'x^2 + {1} over {2}',body=('EQUATION-BODY',),anchor=(0,6))

    def test_note_automatic_number_and_kind_are_preserved_in_the_direct_note(self):
        for attribute,value in (('num','2'),('numType','ENDNOTE')):
            result=mutated('owned-notes',lambda root:next(root.iter(q('autoNum'))).set(attribute,value))
            with self.subTest(attribute=attribute),self.assertRaisesRegex(ValueError,'automatic number'):
                assert_notes(result,[('footNote',' ADV-FOOTNOTE'),('endNote',' ADV-ENDNOTE')],body=('NOTE-BODY',),anchors=[(0,9),(0,9)])

    def test_history_checkpoint_preserves_body_other_controls_and_hf_text(self):
        import advanced_edit_oracle as oracle
        self.assertTrue(hasattr(oracle,'assert_checkpoint'),'Complete saved history checkpoint policy is missing')
        expected={'body_paragraphs':['PAGE-BODY-ONE','PAGE-BODY-TWO'],
                  'pages': [{'width':59528,'height':84189,'landscape':'NARROWLY',
                    'margin':{'left':4819,'right':5386,'top':3685,'bottom':6520,'header':2268,'footer':2551,'gutter':0}}],
                  'population':{'headers':1,'footers':1},'headers':['ADV-HEADER'],'footers':['ADV-FOOTER'],'breaks':[(0,1)]}
        oracle.assert_checkpoint(inspect('owned-page'),**expected)
        def lose_body(root):
            next(root.findall(q('p'))[0].iter(q('t'))).text=''
        def lose_header(root):
            next(one(next(root.iter(q('header'))),'subList').iter(q('t'))).text=''
        def duplicate_footer(root):
            import copy
            footer=next(root.iter(q('footer')))
            root.findall(q('p'))[0].findall(q('run'))[-1].append(copy.deepcopy(footer))
        for change in (lose_body,lose_header,duplicate_footer):
            with self.subTest(change=change),self.assertRaises(ValueError):
                oracle.assert_checkpoint(mutated('owned-page',change),**expected)
        # This is the former field-creation-Undo false pass: no fields remain,
        # but the saved body has disappeared too. A creation Undo must preserve it.
        empty=inspect('owned-blank')
        with self.assertRaises(ValueError):
            oracle.assert_checkpoint(empty,body_paragraphs=['FIELD-BODY-HEAD'],
                                     pages=empty['pages'],population={},headers=[],footers=[])

    def test_counter_outside_the_declared_note_is_an_extra_control(self):
        def add(root):
            run=root.findall(q('p'))[0].findall(q('run'))[-1]
            ctrl=E.SubElement(run,q('ctrl'));E.SubElement(ctrl,q('autoNum'),num='1',numType='FOOTNOTE')
        with self.assertRaisesRegex(ValueError,'population'):
            assert_textbox(mutated('owned-textbox',add),count=1,text='ADV-TEXTBOX',body=('SHAPE-BODY',))

    def test_history_checkpoint_preserves_unrelated_page_breaks(self):
        import advanced_edit_oracle as oracle
        result=mutated('owned-field-filled',lambda root:root.findall(q('p'))[0].set('pageBreak','1'))
        with self.assertRaisesRegex(ValueError,'page break'):
            oracle.assert_checkpoint(result,body_paragraphs=['FIELD-BODY-HEAD'],
                pages=inspect('owned-field-filled')['pages'],population={'fields':1})

    def test_grid_cell_paragraph_split_fails_even_with_a_preserved_body_checkpoint(self):
        import advanced_edit_oracle as oracle
        def split(root):
            import copy
            sub=one(next(root.iter(q('tc'))),'subList');para=one(sub,'p')
            node=next(para.iter(q('t')));text=node.text;node.text=text[:4]
            other=copy.deepcopy(para);next(other.iter(q('t'))).text=text[4:];sub.append(other)
        result=mutated('owned-grid',split)
        original=inspect('owned-grid')
        # Body/page/population equality alone cannot see a corrupted cell flow.
        oracle.assert_checkpoint(result,body_paragraphs=original['paragraphs']['s0/body'],
                                 pages=original['pages'],population={'tables':1})
        with self.assertRaisesRegex(ValueError,'paragraph'):
            assert_grid(result,'s0/body/t0',GRID)

    def test_seven_explicit_cases_and_checks_match_implemented_bindings(self):
        tree=ast.parse((HERE/'advanced_edit_cases.py').read_text())
        manifest=next(n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='ADVANCED_CHECKS' for t in n.targets))
        values=ast.literal_eval(manifest.value)
        klass=next(n for n in tree.body if isinstance(n,ast.ClassDef))
        methods={n.name for n in klass.body if isinstance(n,ast.FunctionDef) and n.name.startswith('test_')}
        self.assertEqual(len(values),7); self.assertEqual(set(values),methods)
        for checks in values.values():
            self.assertEqual(len(checks),len(set(checks)))
            self.assertTrue({'reopen','next-edit','source-sha'}<=set(checks))
        # No disabled-item bypass/private mutation hooks may silently creep in.
        source=(HERE/'advanced_edit_cases.py').read_text()
        for banned in ('force=True','__wasm','__inputHandler','__TAURI','dispatchEvent','invoke('):
            self.assertNotIn(banned,source)


if __name__=='__main__':unittest.main(verbosity=2)
