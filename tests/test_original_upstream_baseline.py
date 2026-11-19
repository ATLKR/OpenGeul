"""Original HOP authentication must precede the separate rhwp upgrade."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import posixpath
import sys
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import prepare_upstream as prepare

HOP='c298160120c9ffbfca7e72f13dc2e7060ddff7fe'
BASELINE='c9095c5f67632e6721e800ccc7fb43ea49d26682'


class OriginalUpstreamBaselineTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.source=Path(temp.name)/'original';self.source.mkdir()
        self.lock=json.loads((ROOT/'config/upstream.lock.json').read_bytes())
        self.raw={
            'config/rhwp-upstream.json':(ROOT/'tests/fixtures/upstream-baseline/rhwp-upstream.original.json').read_bytes(),
            'tests/rhwp-baseline.test.mjs':b'// synthetic unchanged baseline test\n',
            'tests/rhwp-boundary.test.mjs':b'// synthetic unchanged boundary test\n',
        }
        for name,raw in self.raw.items():
            path=self.source/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
        pins={name:hashlib.sha256(raw).hexdigest() for name,raw in self.raw.items()}
        patcher=mock.patch.object(prepare,'BASELINE_SOURCE_SHA256',pins,create=True)
        patcher.start();self.addCleanup(patcher.stop)

    def selected(self):
        function=getattr(prepare,'original_baseline_rhwp',None)
        self.assertTrue(callable(function))
        return function(self.source,self.lock)

    def test_baseline_uses_original_commit_while_current_lock_stays_new(self):
        before=dict(self.raw)
        selected=self.selected()
        self.assertEqual(selected['commit'],BASELINE)
        self.assertEqual(selected['version'],'0.9.0')
        self.assertEqual(selected['repository'],self.lock['rhwp']['repository'])
        self.assertNotEqual(selected['commit'],self.lock['rhwp']['commit'])
        for name,raw in before.items():self.assertEqual((self.source/name).read_bytes(),raw)

    def test_changed_config_or_original_test_is_rejected_without_writes(self):
        for name,raw in self.raw.items():
            path=self.source/name;path.write_bytes(raw+b' ')
            with self.subTest(source=name),self.assertRaises(ValueError):self.selected()
            self.assertEqual(path.read_bytes(),raw+b' ')
            path.write_bytes(raw)

    def test_baseline_requires_the_pinned_hop_and_same_upstream_repository(self):
        for field in ['hop','rhwp']:
            original=self.lock[field].copy()
            self.lock[field]['commit' if field=='hop' else 'repository']='unrelated'
            with self.subTest(role=field),self.assertRaises(ValueError):self.selected()
            self.lock[field]=original

    def test_hardlink_and_symlink_baseline_inputs_are_rejected(self):
        import os
        path=self.source/'config/rhwp-upstream.json';raw=path.read_bytes()
        other=self.source/'same-public-input.json';other.write_bytes(raw)
        path.unlink();os.link(other,path)
        with self.assertRaises(ValueError):self.selected()
        path.unlink();path.symlink_to(other)
        with self.assertRaises(ValueError):self.selected()

    def test_baseline_main_selects_old_source_without_product_patch(self):
        source=self.source.parent/'fresh'
        calls=[]
        def git(*args,cwd):
            if args[:2]==('git','init'):
                for name,raw in self.raw.items():
                    path=source/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
            if args[:3]==('git','rev-parse','HEAD'):
                return BASELINE if cwd==source/'third_party/rhwp' else HOP
            return ''
        with mock.patch.object(sys,'argv',['prepare_upstream.py','--baseline-only','--directory',str(source)]), \
             mock.patch.object(prepare.os,'environ',{}), \
             mock.patch.object(prepare,'run',side_effect=git), \
             mock.patch.object(prepare,'checkout_original_baseline',side_effect=lambda *args:calls.append(args)), \
             mock.patch.object(prepare,'checkout_rhwp') as current_checkout, \
             mock.patch.object(prepare,'port_windows_contract_test') as port, \
             mock.patch.object(prepare,'pin_package_manager'), \
             mock.patch.object(prepare,'pin_frontend_dependencies') as frontend, \
             mock.patch.object(prepare,'patch') as product, \
             mock.patch.object(prepare,'print',create=True):
            prepare.main()
        self.assertEqual(calls,[(source/'third_party/rhwp',self.lock['rhwp']['repository'],BASELINE)])
        port.assert_called_once_with(source)
        frontend.assert_called_once_with(source,baseline=True)
        product.assert_not_called()
        current_checkout.assert_not_called()

    def test_baseline_checkout_keeps_node_and_font_trees_without_current_rust_restoration(self):
        calls=[]
        checked_roots=[];selected_roots=[]
        # c909 pdf-open.ts imports this real cross-root module. A reduced
        # synthetic body tests retained-path resolution without executing PDF IO.
        importer=PurePosixPath('rhwp-studio/src/core/pdf-open.ts')
        shared=PurePosixPath(posixpath.normpath(str(importer.parent/'../../../rhwp-shared/pdf/import-session.js')))
        self.assertEqual(shared,PurePosixPath('rhwp-shared/pdf/import-session.js'))
        fixture={str(importer):b"import '../../../rhwp-shared/pdf/import-session.js';\n",
                 str(shared):b'export const syntheticImportSession = true;\n'}
        def git(*args,cwd):
            calls.append(args)
            if args[:3]==('git','rev-parse','FETCH_HEAD'):return BASELINE
            if args[:3]==('git','cat-file','-t'):
                root=args[3].removeprefix('FETCH_HEAD:')
                self.assertIn(root,('rhwp-studio','rhwp-shared','ttfs'))
                checked_roots.append(root);return 'tree'
            if args[:3]==('git','sparse-checkout','set'):
                selected_roots.extend(args[3:])
                for name,raw in fixture.items():
                    if PurePosixPath(name).parts[0] in args[3:]:
                        target=destination/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
            return ''
        destination=self.source.parent/'original-rhwp'
        with mock.patch.object(prepare,'run',side_effect=git),mock.patch.object(prepare,'restore_compile_inputs') as restore:
            prepare.checkout_original_baseline(destination,self.lock['rhwp']['repository'],BASELINE)
        self.assertTrue((destination/str(shared)).is_file(),'Baseline studio must retain its actual cross-root import target')
        self.assertEqual(checked_roots,selected_roots)
        self.assertEqual(selected_roots,['rhwp-studio','rhwp-shared','ttfs'])
        self.assertIn(('git','fetch','--filter=blob:none','--depth=1','origin',BASELINE),calls)
        restore.assert_not_called()
        (destination/'owned.txt').write_bytes(b'synthetic original input')
        with mock.patch.object(prepare,'run') as git,self.assertRaises(ValueError):
            prepare.checkout_original_baseline(destination,self.lock['rhwp']['repository'],BASELINE)
        git.assert_not_called()
        self.assertEqual((destination/'owned.txt').read_bytes(),b'synthetic original input')

    def test_current_patch_cannot_consume_the_original_baseline_tree(self):
        def git(*args,cwd):return BASELINE if cwd==self.source/'third_party/rhwp' else HOP
        with mock.patch.object(sys,'argv',['prepare_upstream.py','--patch-only','--directory',str(self.source)]), \
             mock.patch.object(prepare,'run',side_effect=git),mock.patch.object(prepare,'patch') as patch:
            with self.assertRaises(ValueError):prepare.main()
        patch.assert_not_called()

    def test_baseline_cannot_reuse_current_default_or_another_mode(self):
        for args in [['--baseline-only'],['--baseline-only','--fetch-only'],['--baseline-only','--patch-only']]:
            with self.subTest(mode=len(args)),mock.patch.object(sys,'argv',['prepare_upstream.py',*args]):
                with self.assertRaises((ValueError,SystemExit)):prepare.main()

    def test_windows_build_runs_original_tests_before_current_fetch_and_keeps_red_probe(self):
        source=(ROOT/'scripts/build-msix.ps1').read_text()
        baseline=source.index('python scripts/prepare_upstream.py --baseline-only --directory $baselineSource')
        push=source.index('Push-Location $baselineSource',baseline)
        original=source.index('pnpm run test:upstream',push)
        current=source.index('python scripts/prepare_upstream.py --fetch-only',original)
        red=source.index('python scripts/prepare_hwpx.py $source --red-probe',current)
        patch=source.index('python scripts/prepare_upstream.py --patch-only',red)
        self.assertLess(baseline,push);self.assertLess(original,current);self.assertLess(current,red);self.assertLess(red,patch)
        self.assertEqual(source.count('pnpm run test:upstream'),1)
        self.assertEqual(source.count('pnpm install --frozen-lockfile'),2)
        self.assertIn('pnpm run test:studio',source[original:current])
        self.assertIn('pnpm run test:studio',source[patch:])


if __name__=='__main__':unittest.main()
