"""Portable PPTX boundary checks; no native Windows execution is claimed."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile

from suite.tests.test_office_feature_smoke import smoke, successful_cleanup

P = 'http://schemas.openxmlformats.org/presentationml/2006/main'
A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
REL = 'http://schemas.openxmlformats.org/package/2006/relationships'


def pptx_parts(case):
    """A small independent OOXML fixture with ordered presentation relationships."""
    pages = smoke.expected(case)['pages']
    presentation = ET.Element('{'+P+'}presentation')
    ids = ET.SubElement(presentation, '{'+P+'}sldIdLst')
    relations = ET.Element('{'+REL+'}Relationships')
    parts = {'[Content_Types].xml': b'<Types/>'}
    for index, shapes in enumerate(pages, 1):
        ET.SubElement(ids, '{'+P+'}sldId', {'id': str(index+255), '{'+R+'}id': 'rId'+str(index)})
        ET.SubElement(relations, '{'+REL+'}Relationship', {'Id': 'rId'+str(index),
                      'Type': R+'/slide', 'Target': 'slides/slide'+str(index)+'.xml'})
        slide = ET.Element('{'+P+'}sld')
        tree = ET.SubElement(ET.SubElement(slide, '{'+P+'}cSld'), '{'+P+'}spTree')
        ET.SubElement(tree, '{'+P+'}nvGrpSpPr'); ET.SubElement(tree, '{'+P+'}grpSpPr')
        for shape in shapes:
            s = ET.SubElement(tree, '{'+P+'}sp')
            nv = ET.SubElement(s, '{'+P+'}nvSpPr')
            ET.SubElement(nv, '{'+P+'}cNvSpPr', {'txBox': '1'})
            x = ET.SubElement(ET.SubElement(s, '{'+P+'}spPr'), '{'+A+'}xfrm')
            ET.SubElement(x, '{'+A+'}off', dict(zip(('x','y'), map(str, (n*360 for n in shape['position'])))))
            ET.SubElement(x, '{'+A+'}ext', dict(zip(('cx','cy'), map(str, (n*360 for n in shape['size'])))))
            body = ET.SubElement(s, '{'+P+'}txBody')
            paragraph = ET.SubElement(body, '{'+A+'}p')
            run = ET.SubElement(paragraph, '{'+A+'}r')
            ET.SubElement(run, '{'+A+'}t').text = shape['text']
        parts['ppt/slides/slide'+str(index)+'.xml'] = ET.tostring(slide)
    parts['ppt/presentation.xml'] = ET.tostring(presentation)
    parts['ppt/_rels/presentation.xml.rels'] = ET.tostring(relations)
    return parts


def write_pptx(path, parts):
    with zipfile.ZipFile(path, 'w') as package:
        for name, content in parts.items(): package.writestr(name, content)


def native_reopen(case):
    result = copy.deepcopy(smoke.expected(case))
    for page in result['pages']:
        for shape in page:
            shape['size'] = [value-1 for value in shape['size']]
            shape['shapeType'] = 'com.sun.star.drawing.CustomShape'
    return result


class PptxGeometryContractTests(unittest.TestCase):
    def setUp(self):
        self.cases = {c['id']: c for c in smoke.case_specs()}
        self.case = self.cases['rich-impress']
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def test_create_remains_exact_and_reopen_has_one_exact_documented_representation(self):
        for cid in ('format-impress-pptx','rich-impress'):
            case=self.cases[cid];authored=smoke.expected(case)
            self.assertEqual('com.sun.star.drawing.TextShape', authored['pages'][0][0]['shapeType'])
            smoke.validate_observation(case, authored, phase='create')
            smoke.validate_observation(case, native_reopen(case), phase='independent-reopen')
            self.assertEqual(authored, smoke.expected(case), 'The authored oracle was mutated')
        for cid in ('format-impress-odp', 'format-impress-ppt', 'rich-draw'):
            case = self.cases[cid]
            smoke.validate_observation(case, smoke.expected(case), phase='independent-reopen')

    def test_wrong_phase_scale_sign_delta_position_text_order_and_service_are_rejected(self):
        with self.assertRaises(AssertionError): smoke.validate_observation(self.case, native_reopen(self.case), phase='create')
        for delta in (-2, 0, 1):
            wrong = native_reopen(self.case)
            wrong['pages'][0][0]['size'][0] = smoke.expected(self.case)['pages'][0][0]['size'][0]+delta
            with self.subTest(delta=delta), self.assertRaises(AssertionError):
                smoke.validate_observation(self.case, wrong, phase='independent-reopen')
        for mutate in (lambda o:o['pages'][0][0]['position'].__setitem__(0,1001),
                       lambda o:o['pages'].reverse(),
                       lambda o:o['pages'][0][0].update(text='wrong'),
                       lambda o:o['pages'][0][0].update(shapeType='com.sun.star.drawing.RectangleShape')):
            wrong = native_reopen(self.case); mutate(wrong)
            with self.assertRaises(AssertionError): smoke.validate_observation(self.case, wrong, phase='independent-reopen')
        with self.assertRaises(ValueError): smoke.validate_observation(self.case, native_reopen(self.case), phase='invented')

    def test_saved_package_requires_authored_emu_geometry_and_relationship_slide_order(self):
        path = self.root/'generated.pptx'; write_pptx(path, pptx_parts(self.case))
        result = smoke.validate_container(self.case, path)
        self.assertTrue(result['exactAuthoredEmuVerified'])
        self.assertEqual([2160000,900000], result['pages'][0][0]['sizeEmu'])
        self.assertEqual([900000,720000], result['pages'][1][0]['positionEmu'])

    def test_saved_package_rejects_emu_changes_missing_duplicate_and_malformed_xml(self):
        base = pptx_parts(self.case); member = 'ppt/slides/slide1.xml'
        for reason in ('unit','scale','position','missing','duplicate','shape','text','order','malformed'):
            parts = dict(base)
            slide = ET.fromstring(parts[member]); x = slide.find('.//{'+A+'}xfrm')
            if reason == 'unit': x.find('{'+A+'}ext').set('cx','2159999')
            elif reason == 'scale': x.find('{'+A+'}ext').set('cx','6000')
            elif reason == 'position': x.find('{'+A+'}off').set('x','360001')
            elif reason == 'missing': x.remove(x.find('{'+A+'}ext'))
            elif reason == 'duplicate': x.append(copy.deepcopy(x.find('{'+A+'}ext')))
            elif reason == 'shape': ET.SubElement(slide.find('.//{'+P+'}spTree'),'{'+P+'}pic')
            elif reason == 'text': slide.find('.//{'+A+'}t').text='wrong'
            parts[member]=ET.tostring(slide)
            if reason == 'order':
                pres=ET.fromstring(parts['ppt/presentation.xml']); ids=pres.find('{'+P+'}sldIdLst'); ids[:]=list(reversed(list(ids)))
                parts['ppt/presentation.xml']=ET.tostring(pres)
            if reason == 'malformed': parts[member]=b'<broken'
            path=self.root/(reason+'.pptx'); write_pptx(path,parts)
            with self.subTest(reason=reason), self.assertRaises((ValueError,AssertionError,ET.ParseError)):
                smoke.validate_container(self.case,path)

    def test_catalogue_discloses_native_difference_and_cannot_claim_repeated_lossless_save(self):
        self.assertEqual(['native-reopen-bounds-minus-one-mm100'], self.case['lossBudget'])
        self.assertFalse(self.case['qualificationScope']['losslessRepeatedNativeEditSave'])
        self.assertFalse(self.case['qualificationScope']['universalGeometryPreservation'])
        self.assertEqual(-1,self.case['knownNativeGeometryDifference']['reopenSizeDeltaMm100'])
        self.assertTrue(all('libreoffice-26.8.1.1' in u for u in self.case['knownNativeGeometryDifference']['sources']))
        catalog=json.loads(smoke.CATALOG.read_text())
        for key in ('lossBudget','qualificationScope','knownNativeGeometryDifference'):
            bad=copy.deepcopy(catalog); case=next(c for c in bad['cases'] if c['id']==self.case['id']); case.pop(key)
            with self.assertRaises(ValueError): smoke.validate_catalog(bad)

    def test_raw_observations_and_package_proof_survive_success_or_native_failure(self):
        for correct in (True,False):
            output=self.root/str(correct); (output/'fixtures').mkdir(parents=True)
            suite=self.root/'suite';suite.mkdir(exist_ok=True)
            case=self.case
            class Engine:
                def __init__(self,suite): self.cleanup_errors=[];self.cleanup_evidence=successful_cleanup(suite)
                def start(self): pass
                def load(self,url): return object()
                def store_new(self,document,path,filter_name): write_pptx(path,pptx_parts(case))
                def close_document(self,document): pass
                def cleanup(self): pass
            reopened=native_reopen(case)
            if not correct: reopened['pages'][0][0]['size'][0]-=1
            with patch.object(smoke,'Engine',Engine),patch.object(smoke,'populate',return_value={}), \
                 patch.object(smoke,'observe',side_effect=[smoke.expected(case),reopened]), \
                 patch.object(smoke,'load_saved',return_value=object()):
                row=smoke.run_case(suite,output,case)
            self.assertEqual('passed' if correct else 'failed',row['status'],row)
            self.assertEqual(smoke.expected(case),row['createdObservation'])
            self.assertEqual(reopened,row['observed'])
            self.assertEqual(self.case['knownNativeGeometryDifference'],row['knownNativeGeometryDifference'])
            self.assertEqual('create',row['packageGeometryChecks'][0]['phase'])
            self.assertTrue(row['packageGeometryChecks'][0]['proof']['exactAuthoredEmuVerified'])


if __name__ == '__main__': unittest.main()
