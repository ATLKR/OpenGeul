import io
from pathlib import Path
import sys
import unittest
import warnings
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'e2e'))
from hwpx_oracle import inspect_hwpx


def package(text='계약서 &amp; &lt;금액&gt; Ω', *, mime=b'application/hwp+zip', omit=(), extra=(), compression=zipfile.ZIP_STORED):
    data=io.BytesIO()
    entries=[('mimetype',mime), ('Contents/header.xml',b'<head/>'),
        ('Contents/content.hpf',b'<package><manifest><item href="section0.xml"/></manifest></package>'),
        ('Contents/section0.xml',f'<hp:sec xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"><hp:p><hp:run><hp:t>{text}</hp:t></hp:run></hp:p></hp:sec>'.encode())]
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        with zipfile.ZipFile(data,'w') as archive:
            for name,value in entries+list(extra):
                if name not in omit: archive.writestr(name,value,compress_type=compression)
    return data.getvalue()

class OracleTests(unittest.TestCase):
    def test_real_xml_text_is_unescaped_and_unicode_is_preserved(self):
        result=inspect_hwpx(package())
        self.assertEqual(result['text'], '계약서 & <금액> Ω')
        self.assertEqual(result['sections'],1)
    def test_empty_text_is_valid(self): self.assertEqual(inspect_hwpx(package(''))['text'],'')
    def test_text_runs_are_joined(self):
        self.assertEqual(inspect_hwpx(package('a</hp:t><hp:t>b'))['text'],'ab')
    def test_file_signature_does_not_define_the_format(self):
        for value in (b'',b'PK\x03\x04broken',b'\xd0\xcf\x11\xe0broken'):
            with self.subTest(value=value),self.assertRaises(ValueError):inspect_hwpx(value)
    def test_required_members(self):
        for name in ('mimetype','Contents/header.xml','Contents/content.hpf','Contents/section0.xml'):
            with self.subTest(name=name),self.assertRaises(ValueError):inspect_hwpx(package(omit=(name,)))
    def test_wrong_mime(self):
        with self.assertRaises(ValueError):inspect_hwpx(package(mime=b'application/zip'))
    def test_compressed_mime(self):
        with self.assertRaises(ValueError):inspect_hwpx(package(compression=zipfile.ZIP_DEFLATED))
    def test_duplicate_member(self):
        with self.assertRaises(ValueError):inspect_hwpx(package(extra=[('Contents/header.xml',b'<head/>')]))
    def test_unsafe_names(self):
        for name in ('../out','/root','C:/out','a\\b','Contents/../bad','a//b','a/./b'):
            with self.subTest(name=name),self.assertRaises(ValueError):inspect_hwpx(package(extra=[(name,b'x')]))
    def test_dtd_and_entity_are_rejected(self):
        with self.assertRaises(ValueError):inspect_hwpx(package(extra=[('attack.xml',b'<!DOCTYPE doc [<!ENTITY x "bad">]><doc>&x;</doc>')]))
    def test_bad_xml(self):
        with self.assertRaises(ValueError):inspect_hwpx(package('<unclosed>'))
    def test_total_uncompressed_size_limit(self):
        with self.assertRaises(ValueError):inspect_hwpx(package(),max_bytes=20)
    def test_missing_manifest_section(self):
        value=package(omit=('Contents/content.hpf',),extra=[('Contents/other.hpf',b'<package/>')])
        with self.assertRaises(ValueError):inspect_hwpx(value)
    def test_binary_counts_are_reported(self):
        self.assertEqual(inspect_hwpx(package(extra=[('BinData/a.png',b'own synthetic bytes')]))['binary_parts'],1)

if __name__=='__main__':unittest.main()
