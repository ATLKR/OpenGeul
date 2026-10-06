"""Outlined printer regression tests do not depend on text extraction or OCR."""
import importlib.util
from pathlib import Path
import unittest
from PIL import Image,ImageDraw
MODULE=Path(__file__).resolve().parents[1]/'print_raster.py'
class RasterTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(MODULE.exists(),'Missing outlined-print raster oracle')
        spec=importlib.util.spec_from_file_location('print_raster',MODULE)
        self.m=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.m)
        self.reference=Image.new('L',(200,240),255);draw=ImageDraw.Draw(self.reference)
        for y in (40,80,120,160):
            for x in (30,50,70,90,110):draw.rectangle((x,y,x+8,y+15),fill=0)
    def test_identical_print_passes(self):self.assertEqual(self.m.compare_ink(self.reference,self.reference)['missing'],0)
    def test_blank_fails(self):
        with self.assertRaises(ValueError):self.m.compare_ink(Image.new('L',self.reference.size,255),self.reference)
    def test_last_line_missing_fails(self):
        image=self.reference.copy();ImageDraw.Draw(image).rectangle((0,158,199,180),fill=255)
        with self.assertRaises(ValueError):self.m.compare_ink(image,self.reference)
    def test_partial_descender_clipping_fails(self):
        image=self.reference.copy();ImageDraw.Draw(image).rectangle((88,170,101,176),fill=255)
        with self.assertRaises(ValueError):self.m.compare_ink(image,self.reference)
    def test_added_output_fails(self):
        image=self.reference.copy();ImageDraw.Draw(image).rectangle((140,200,180,215),fill=0)
        with self.assertRaises(ValueError):self.m.compare_ink(image,self.reference)
    def test_one_pixel_translation_is_tolerated(self):
        image=Image.new('L',self.reference.size,255);image.paste(self.reference,(1,1));self.m.compare_ink(image,self.reference)
    def test_uniform_blank_reference_is_not_a_valid_baseline(self):
        image=Image.new('L',self.reference.size,255)
        with self.assertRaises(ValueError):self.m.compare_ink(image,image)
    def test_wrong_canvas_size_fails(self):
        with self.assertRaises(ValueError):self.m.compare_ink(Image.new('L',(199,240),255),self.reference)
if __name__=='__main__':unittest.main()
