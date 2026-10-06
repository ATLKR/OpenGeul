"""Only a manually reviewed whole-page fingerprint may add a runtime variant."""
import importlib.util,json
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[2]
class ReviewedVariantTests(unittest.TestCase):
    def setUp(self):
        s=importlib.util.spec_from_file_location('variants',ROOT/'e2e/print_raster.py')
        self.m=importlib.util.module_from_spec(s);s.loader.exec_module(self.m)
        self.assertTrue(callable(getattr(self.m,'match_reference',None)),'Missing exact reviewed-variant matcher')
        self.ref={'pixels':[1786,2526],'ink':123,'bbox':[1,1,50,50],'maskSha256':'a'*64}
        self.alt={**self.ref,'maskSha256':'b'*64,'ink':122}
        self.book={'reviewedVariants':[{'id':'win25-glyph4','case':'table-0','page':1,'fingerprint':self.alt,'sourceRun':37445818877,'sourceArtifact':11403760205,'review':'Complete digit outline, independent operator inspection'}]}
    def match(self,value,case='table-0',page=1):return self.m.match_reference(value,self.ref,self.book,case,page)
    def test_original_reference_remains_exact(self):self.assertEqual(self.match(self.ref),'canonical')
    def test_explicit_reviewed_variant_passes(self):self.assertEqual(self.match(self.alt),'win25-glyph4')
    def test_unknown_pixel_hash_does_not_pass(self):
        with self.assertRaises(ValueError):self.match({**self.alt,'maskSha256':'c'*64})
    def test_correct_hash_with_wrong_bounds_does_not_pass(self):
        with self.assertRaises(ValueError):self.match({**self.alt,'bbox':[2,1,50,50]})
    def test_variant_cannot_apply_to_other_case_or_page(self):
        for c,p in [('table-600',1),('table-0',2)]:
            with self.assertRaises(ValueError):self.match(self.alt,c,p)
    def test_variant_without_review_or_provenance_is_rejected(self):
        for key in ('review','sourceRun','sourceArtifact'):
            original=self.book['reviewedVariants'][0].pop(key)
            with self.assertRaises(ValueError):self.match(self.alt)
            self.book['reviewedVariants'][0][key]=original
    def test_ambiguous_exact_variants_are_rejected(self):
        self.book['reviewedVariants'].append({**self.book['reviewedVariants'][0],'id':'duplicate'})
        with self.assertRaises(ValueError):self.match(self.alt)
    def test_no_variants_is_still_strict(self):
        self.book={}
        with self.assertRaises(ValueError):self.match(self.alt)
if __name__=='__main__':unittest.main()
