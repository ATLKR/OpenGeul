"""Current caller pins use public package bytes and the actual solved lock."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import collect_notices as notices


def create_fixture_caller(alias,package):
    if os.name=='nt':
        # Match pnpm's directory junction, rather than a directory symlink.
        # Both arguments are paths inside this test's synthetic temporary tree.
        for path in (alias,package):
            value=str(path)
            if (not path.is_absolute() or len(value)>32767
                    or any(char in value for char in '\0\r\n"&|<>^%!')):
                raise ValueError('Unsupported synthetic junction path')
        subprocess.run(['cmd.exe','/d','/c','mklink','/J',str(alias),str(package)],
                       check=True,capture_output=True,timeout=10)
        if getattr(alias.lstat(),'st_reparse_tag',None)!=0xA0000003:
            raise AssertionError('Synthetic caller must be an actual directory junction')
    else:
        alias.symlink_to(os.path.relpath(package,alias.parent),target_is_directory=True)


class CurrentFrontendNoticeTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.source=Path(temp.name)/'source';store=self.source/'node_modules/.pnpm'
        self.package=store/'rolldown@1.2.19/node_modules/rolldown'
        self.caller=store/'vite@8.3.8/node_modules/vite'
        self.package.mkdir(parents=True);self.caller.mkdir(parents=True)
        fixture=ROOT/'tests/fixtures/current-frontend-notice'
        for name in ['package.json','LICENSE','THIRD-PARTY-LICENSE']:
            (self.package/name).write_bytes((fixture/('rolldown-1.2.19-'+name)).read_bytes())
        (self.caller/'package.json').write_bytes((fixture/'vite-8.3.8-package.json').read_bytes())
        self.alias=self.caller.parent/'rolldown'
        create_fixture_caller(self.alias,self.package)
        (self.source/'package.json').write_text(json.dumps({'packageManager':'pnpm@10.34.9'}))
        (self.source/'node_modules/.modules.yaml').write_text(json.dumps({'packageManager':'pnpm@10.34.9','layoutVersion':5,'nodeLinker':'isolated','virtualStoreDir':str(store) if os.name=='nt' else '.pnpm'}))
        for path in [self.source/'pnpm-lock.yaml',store/'lock.yaml']:
            path.write_bytes((ROOT/'overlay/frontend-pnpm-lock.txt').read_bytes())
        self.item={'name':'rolldown','version':'1.2.19','license':'MIT'}
        self.output=self.source.parent/'notice-output'

    def selected(self):
        return notices.reviewed_npm_notice_location(self.source,self.alias/'package.json',self.item)

    def test_exact_current_caller_and_package_select_regular_source_and_complete_notice(self):
        self.assertEqual(self.selected(),self.package)
        result=notices.collect_reviewed_notices('npm',self.item,self.package,self.output)
        self.assertEqual(len(result),1)
        self.assertFalse(result[0]['packageLicenseText'])
        self.assertEqual((self.output/result[0]['file']).read_bytes(),(self.package/'THIRD-PARTY-LICENSE').read_bytes())
        self.assertEqual(notices.collect(self.package,self.output),['LICENSE.txt'])
        self.assertEqual((self.output/'LICENSE.txt').read_bytes(),(self.package/'LICENSE').read_bytes())

    def test_original_baseline_lock_does_not_qualify_current_notice_selection(self):
        path=self.source/'pnpm-lock.yaml'
        path.write_bytes((ROOT/'overlay/baseline-pnpm-lock.txt').read_bytes())
        with self.assertRaises(ValueError):self.selected()
        self.assertFalse(self.output.exists())

    def test_changed_caller_or_package_manifest_is_rejected(self):
        for path in [self.caller/'package.json',self.package/'package.json']:
            raw=path.read_bytes();path.write_bytes(raw+b' ')
            with self.subTest(role=path.parent.name),self.assertRaises(ValueError):self.selected()
            self.assertFalse(self.output.exists());path.write_bytes(raw)

    def test_changed_additional_notice_is_rejected_before_output(self):
        path=self.package/'THIRD-PARTY-LICENSE';path.write_bytes(path.read_bytes()+b' ')
        self.assertEqual(self.selected(),self.package)
        with self.assertRaises(ValueError):notices.collect_reviewed_notices('npm',self.item,self.package,self.output)
        self.assertFalse(self.output.exists())


if __name__=='__main__':unittest.main()
