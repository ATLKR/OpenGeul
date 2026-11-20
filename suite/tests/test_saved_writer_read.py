"""Bounded Writer save polls retain exact content oracles on one byte snapshot."""
import hashlib
import io
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'e2e'))
import lifecycle_smoke as lifecycle
import writer_style_smoke as style

class SavedWriterReadTests(unittest.TestCase):
    def payload(self,text='marker',heading=True):
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as package:
            package.writestr('word/document.xml','<w:document xmlns:w="'+style.WORD_NS+'"><w:body><w:p>'+('<w:pPr><w:pStyle w:val="Heading1"/></w:pPr>' if heading else '')+'<w:r><w:t>'+text+'</w:t><w:br/><w:tab/></w:r></w:p></w:body></w:document>')
        return stream.getvalue()
    def poll(self,call,reader):
        clock=[0.]
        with patch.object(Path,'read_bytes',side_effect=reader),patch.object(lifecycle.time,'monotonic',side_effect=lambda:clock[0]),patch.object(lifecycle.time,'sleep',side_effect=lambda seconds:clock.__setitem__(0,clock[0]+seconds)):
            return call()
    def test_byte_parser_same_hash_exact_marker_and_forbidden(self):
        payload=self.payload();evidence=lifecycle.writer_evidence_bytes(payload,('marker',))
        self.assertEqual(evidence['sha256'],hashlib.sha256(payload).hexdigest())
        self.assertEqual(evidence['bodyText'],'marker\n\t')
        for required,forbidden in ((('absent',),()),(('marker',),('marker',))):
            with self.assertRaises(AssertionError):lifecycle.writer_evidence_bytes(payload,required,forbidden)
        with self.assertRaises(AssertionError):lifecycle.writer_evidence_bytes(self.payload('marker marker'),('marker',))
    def test_style_denial_then_saved_bytes_and_persistent_denial(self):
        baseline=style.docx_style_evidence_bytes(self.payload(heading=False));record={}
        call=lambda:style.wait_saved_style(Path('owned.docx'),baseline,.3,record)
        saved=self.poll(call,[PermissionError(13,'denied'),self.payload()])
        self.assertEqual(saved['firstParagraphStyleId'],'Heading1');self.assertEqual(record['savedStyleRead']['attempts'],2)
        with self.assertRaises(AssertionError):self.poll(call,PermissionError(13,'denied'))
    def test_lifecycle_denial_then_exact_content_and_persistent_denial(self):
        case=object.__new__(lifecycle.Case);case.record={};case.api=SimpleNamespace(title=lambda hwnd:'saved')
        call=lambda:case.saved(1,Path('owned.docx'),('marker',),('forbidden',))
        saved=self.poll(call,[PermissionError(13,'denied'),self.payload()])
        self.assertEqual(saved['bodyText'],'marker\n\t')
        for reader in (PermissionError(13,'denied'),lambda:self.payload('marker marker'),lambda:self.payload('marker forbidden')):
            with self.assertRaises(AssertionError):self.poll(call,reader)

    def test_late_parser_cannot_accept_style_or_lifecycle_saved_bytes(self):
        payload=self.payload()
        baseline=style.docx_style_evidence_bytes(self.payload(heading=False))
        for kind in ('style','lifecycle'):
            with self.subTest(kind=kind):
                clock=[0.]
                case=object.__new__(lifecycle.Case);case.record={};case.api=SimpleNamespace(title=lambda hwnd:'saved')
                original=style.docx_style_evidence_bytes if kind=='style' else lifecycle.writer_evidence_bytes
                def parse(data,*args):
                    result=original(data,*args);clock[0]=35.;return result
                target=style if kind=='style' else lifecycle
                name='docx_style_evidence_bytes' if kind=='style' else 'writer_evidence_bytes'
                with patch.object(Path,'read_bytes',return_value=payload),patch.object(lifecycle.time,'monotonic',side_effect=lambda:clock[0]),patch.object(target,name,side_effect=parse):
                    with self.assertRaisesRegex(AssertionError,'save deadline expired'):
                        if kind=='style':style.wait_saved_style(Path('owned.docx'),baseline,35.,{})
                        else:case.saved(1,Path('owned.docx'),('marker',))

    def test_style_changed_wrong_text_or_style_is_immediately_fatal(self):
        baseline=style.docx_style_evidence_bytes(self.payload(heading=False))
        for payload in (self.payload('changed'),self.payload('changed',heading=False)):
            with self.subTest(payload=payload):
                with patch.object(Path,'read_bytes',return_value=payload) as read:
                    with self.assertRaises(AssertionError):
                        style.wait_saved_style(Path('owned.docx'),baseline,style.time.monotonic()+35,{})
                self.assertEqual(read.call_count,1)
