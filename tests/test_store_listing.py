"""Korean-first listing edits preserve every unrelated submission field."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
try:
    import store_listing
except ModuleNotFoundError:
    store_listing=None


class StoreListingTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(store_listing, 'The offline Korean listing helper is missing')
        self.text={'description':'오픈글은 HWP/HWPX 문서 편집기입니다.',
                   'features':['문서 열기와 저장'], 'releaseNotes':'암호 문서 처리를 개선했습니다.'}
        self.baseline={'id':'10','status':'Published','targetPublishMode':'Manual',
            'pricing':{'priceId':'Free','marketSpecificPricings':{'KR':'Base','CN':'NotAvailable'}},
            'ageRatings':{'ratings':['preserved']},'permissions':['preserved'],
            'visibility':'Public','listings':{}}
        for locale in ('ko-kr','en-us'):
            self.baseline['listings'][locale]={
                'baseListing':{'title':'OpenGeul','description':'Old description',
                    'features':['Old feature'],'releaseNotes':'Old notes','keywords':['HWP'],
                    'images':[{'id':'image1','fileName':'existing.png','fileStatus':'Uploaded'}],
                    'licenseTerms':'Existing license','websiteUrl':'https://github.com/ATLKR/OpenGeul'},
                'platformOverrides':{'Windows81':{'description':'Preserved platform text'}},
                'serverField':{'preserved':True}}

    def test_all_existing_locale_text_changes_preserve_exact_nontext_fields(self):
        original=copy.deepcopy(self.baseline)
        result=store_listing.apply_korean_listing(self.baseline,self.text)
        expected=copy.deepcopy(original)
        for locale in expected['listings']:
            expected['listings'][locale]['baseListing'].update(copy.deepcopy(self.text))
        self.assertEqual(result,expected)
        self.assertEqual(self.baseline,original)
        self.assertEqual(set(result['listings']),{'ko-kr','en-us'})
        self.assertNotIn('defaultLanguage',result)
        result['listings']['en-us']['baseListing']['images'][0]['id']='changed in caller'
        self.assertEqual(self.baseline,original)

    def test_korean_locale_is_required_without_silently_adding_new_languages(self):
        del self.baseline['listings']['ko-kr']
        original=copy.deepcopy(self.baseline)
        with self.assertRaises(ValueError):store_listing.apply_korean_listing(self.baseline,self.text)
        self.assertEqual(self.baseline,original)

    def test_malformed_locale_template_never_changes_input(self):
        for invalid in (None,{}, {'baseListing':None}):
            with self.subTest(template=invalid):
                baseline=copy.deepcopy(self.baseline);baseline['listings']['en-us']=invalid
                original=copy.deepcopy(baseline)
                with self.assertRaises(ValueError):store_listing.apply_korean_listing(baseline,self.text)
                self.assertEqual(baseline,original)

    def test_unsupported_fields_cannot_change_identity_availability_or_images(self):
        for key,value in [('defaultLanguage','ko-kr'),('title','Renamed'),('images',[]),
                          ('pricing',{'priceId':'Tier2'}),('targetPublishMode','Immediate')]:
            with self.subTest(key=key):
                text={**self.text,key:value};original=copy.deepcopy(self.baseline)
                with self.assertRaises(ValueError):store_listing.apply_korean_listing(self.baseline,text)
                self.assertEqual(self.baseline,original)

    def test_missing_empty_english_or_oversized_text_is_rejected(self):
        cases=[{k:v for k,v in self.text.items() if k!='releaseNotes'},
               {**self.text,'description':''},{**self.text,'description':'English-only description'},
               {**self.text,'description':'가'*10001},
               {**self.text,'features':['English-only feature']},
               {**self.text,'features':['한글']*21},
               {**self.text,'releaseNotes':'가'*1501}]
        for text in cases:
            with self.subTest(textKeys=list(text)):
                with self.assertRaises(ValueError):store_listing.apply_korean_listing(self.baseline,text)

    def test_explicit_plan_and_returned_features_have_no_shared_mutable_lists(self):
        original=copy.deepcopy(self.text)
        result=store_listing.apply_korean_listing(self.baseline,self.text)
        result['listings']['ko-kr']['baseListing']['features'].append('호출자가 추가')
        self.assertEqual(self.text,original)
        self.assertEqual(result['listings']['en-us']['baseListing']['features'],original['features'])

    def test_default_config_loads_valid_text_for_future_submission_only(self):
        text=store_listing.load_listing()
        result=store_listing.apply_korean_listing(self.baseline,text)
        self.assertEqual(set(text),{'description','features','releaseNotes'})
        self.assertEqual(result['listings']['en-us']['baseListing']['description'],text['description'])
        self.assertEqual(self.baseline['status'],'Published')

    def test_duplicate_json_and_excessive_config_bytes_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'listing.json'
            for data in ('{"description":"한글","description":"중복"}', ' '*65537):
                path.write_text(data)
                with self.assertRaises(ValueError):store_listing.load_listing(path)


if __name__=='__main__':unittest.main()
