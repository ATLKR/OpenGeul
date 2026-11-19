"""Original HOP authentication must precede the separate rhwp upgrade."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import posixpath
import os
import re
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
        with mock.patch.object(prepare,'run',side_effect=git),mock.patch.object(prepare,'restore_compile_inputs') as restore, \
             mock.patch.object(prepare,'restore_original_baseline_node_inputs') as node_inputs:
            prepare.checkout_original_baseline(destination,self.lock['rhwp']['repository'],BASELINE)
        node_inputs.assert_called_once_with(destination)
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



def create_baseline_fixture_alias(alias,package):
    if os.name=='nt':
        import subprocess
        for path in (alias,package):
            value=str(path)
            if (not path.is_absolute() or len(value)>32767
                    or any(char in value for char in '\0\r\n"&|<>^%!')):
                raise ValueError('Unsupported synthetic junction path')
        subprocess.run(['cmd.exe','/d','/c','mklink','/J',str(alias),str(package)],
                       check=True,capture_output=True,timeout=10)
        if getattr(alias.lstat(),'st_reparse_tag',None)!=0xA0000003:
            raise AssertionError('Synthetic baseline alias must be an actual directory junction')
    else:
        alias.symlink_to(os.path.relpath(package,alias.parent),target_is_directory=True)


class OriginalBaselineLiteralInputTests(unittest.TestCase):
    INPUT='assets/fonts/enclosed-pua-metrics.json'
    IMPORTER='rhwp-studio/src/core/enclosed-pua.ts'
    DATA=b'{"syntheticMetric":1}\n'

    def setUp(self):
        import subprocess
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.seed=self.root/'seed';self.seed.mkdir()
        self.git('init','--quiet',cwd=self.seed)
        files={self.IMPORTER:b"import metrics from '../../../assets/fonts/enclosed-pua-metrics.json' with { type: 'json' };\n",
               self.INPUT:self.DATA,'rhwp-shared/pdf/synthetic.js':b'export {};\n',
               'ttfs/synthetic.txt':b'synthetic font-tree input\n',
               'assets/fonts/unrelated.ttf':b'synthetic excluded font bytes\n'}
        for name,raw in files.items():
            path=self.seed/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
        self.commit()
        self.revision=self.git('rev-parse','HEAD',cwd=self.seed).strip()
        self.destination=self.root/'baseline'

    @staticmethod
    def git(*args,cwd):
        import subprocess
        return subprocess.run(['git','-c','core.autocrlf=false',*args],cwd=cwd,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',
            check=True,timeout=10).stdout

    def commit(self):
        self.git('add','.',cwd=self.seed)
        self.git('-c','user.name=Synthetic','-c','user.email=synthetic@example.invalid',
                 'commit','--quiet','-m','synthetic fixture',cwd=self.seed)

    def checkout(self,expected=None):
        def local_git(*args,cwd):
            if args[:2]==('git','fetch'):
                return self.git('fetch','--depth=1',str(self.seed),self.revision,cwd=cwd).strip()
            if args[:3]==('git','rev-parse','FETCH_HEAD'):
                # Fetch authorization has separate exact-pin tests; this fixture
                # exercises real local Git sparse/byte restoration without IO.
                return BASELINE
            return self.git(*args[1:],cwd=cwd).strip()
        blob=hashlib.sha1(('blob '+str(len(self.DATA))+'\0').encode()+self.DATA).hexdigest()
        pin={self.INPUT:(len(self.DATA),hashlib.sha256(self.DATA).hexdigest(),blob)}
        if expected is not None:pin[self.INPUT]=expected
        with mock.patch.object(prepare,'run',side_effect=local_git),              mock.patch.object(prepare,'BASELINE_NODE_INPUTS',pin,create=True):
            prepare.checkout_original_baseline(self.destination,
                'https://github.com/edwardkim/rhwp.git',BASELINE)

    def test_sparse_baseline_restores_the_literal_json_import_without_font_payload(self):
        self.checkout()
        importer=self.destination/self.IMPORTER
        relative=re.search(r"from '([^']+)'",importer.read_text()).group(1)
        target=(importer.parent/relative).resolve()
        self.assertEqual(target,self.destination/self.INPUT)
        self.assertTrue(target.is_file(),'Original studio literal JSON must survive sparse checkout')
        self.assertEqual(target.read_bytes(),self.DATA)
        self.assertEqual(json.loads(target.read_bytes()),{'syntheticMetric':1})
        self.assertFalse((self.destination/'assets/fonts/unrelated.ttf').exists())
        self.assertEqual((self.seed/self.INPUT).read_bytes(),self.DATA)

    def test_changed_literal_input_is_rejected_before_materialization(self):
        with self.assertRaises(ValueError):self.checkout(expected=(len(self.DATA),'0'*64,hashlib.sha1(('blob '+str(len(self.DATA))+'\0').encode()+self.DATA).hexdigest()))
        self.assertFalse((self.destination/self.INPUT).exists())

    def test_non_blob_literal_input_is_rejected_before_materialization(self):
        path=self.seed/self.INPUT;path.unlink();path.mkdir();(path/'synthetic.txt').write_bytes(b'not a JSON blob')
        self.commit();self.revision=self.git('rev-parse','HEAD',cwd=self.seed).strip()
        with self.assertRaises(ValueError):self.checkout()
        self.assertFalse((self.destination/self.INPUT).exists())


    def restore(self,destination=None):
        blob=hashlib.sha1(('blob '+str(len(self.DATA))+'\0').encode()+self.DATA).hexdigest()
        with mock.patch.object(prepare,'BASELINE_NODE_INPUTS',
                {self.INPUT:(len(self.DATA),hashlib.sha256(self.DATA).hexdigest(),blob)}):
            prepare.restore_original_baseline_node_inputs(destination or self.destination)

    def missing_input(self):
        self.checkout();target=self.destination/self.INPUT;target.unlink();return target

    def assert_rejected_without_changing(self,action,target,before):
        error=None
        try:action()
        except (ValueError,OSError) as exc:error=exc
        self.assertEqual(target.read_bytes(),before,'Synthetic original bytes must remain unchanged')
        self.assertIsNotNone(error,'Literal input restoration must reject this existing/aliased path')

    def test_existing_literal_target_is_rejected_without_truncation(self):
        target=self.missing_input();target.write_bytes(b'synthetic existing target')
        self.assert_rejected_without_changing(self.restore,target,b'synthetic existing target')

    def test_parent_alias_does_not_modify_the_other_directory(self):
        target=self.missing_input();target.parent.rmdir()
        other=self.root/'other';other.mkdir();sentinel=other/target.name;sentinel.write_bytes(b'synthetic parent sentinel')
        create_baseline_fixture_alias(target.parent,other)
        self.assert_rejected_without_changing(self.restore,sentinel,b'synthetic parent sentinel')

    def test_hardlinked_leaf_keeps_both_original_names_unchanged(self):
        target=self.missing_input();other=self.root/'hardlink-original';other.write_bytes(b'synthetic hardlink sentinel')
        os.link(other,target)
        self.assert_rejected_without_changing(self.restore,other,b'synthetic hardlink sentinel')
        self.assertEqual(target.read_bytes(),b'synthetic hardlink sentinel')

    def test_leaf_alias_keeps_the_original_target_unchanged(self):
        target=self.missing_input();other=self.root/'leaf-original'
        if os.name=='nt':
            other.mkdir();sentinel=other/'sentinel.txt';sentinel.write_bytes(b'synthetic leaf sentinel')
            create_baseline_fixture_alias(target,other)
        else:
            sentinel=other;sentinel.write_bytes(b'synthetic leaf sentinel');target.symlink_to(other)
        self.assert_rejected_without_changing(self.restore,sentinel,b'synthetic leaf sentinel')

    def test_destination_ancestor_alias_is_rejected_before_reading_git(self):
        self.missing_input();alias=self.root/'ancestor-alias';create_baseline_fixture_alias(alias,self.destination)
        with mock.patch.object(prepare,'run') as git, self.assertRaises(ValueError):self.restore(alias)
        git.assert_not_called()
        self.assertFalse((self.destination/self.INPUT).exists())

    def test_changed_parent_identity_after_blob_read_is_rejected(self):
        import subprocess
        target=self.missing_input();original=subprocess.check_output
        def changed(*args,**kwargs):
            data=original(*args,**kwargs)
            (self.destination/'assets').rename(self.destination/'original-assets')
            target.parent.mkdir(parents=True);target.write_bytes(b'synthetic replacement-parent sentinel')
            return data
        with mock.patch.object(prepare.subprocess,'check_output',side_effect=changed):
            self.assert_rejected_without_changing(self.restore,target,b'synthetic replacement-parent sentinel')
        self.assertFalse((self.destination/'original-assets/fonts'/target.name).exists())

    def test_exclusive_create_rejects_a_leaf_created_after_the_last_check(self):
        target=self.missing_input();original=Path.open;created=False
        def late_leaf(path,*args,**kwargs):
            nonlocal created
            mode=args[0] if args else kwargs.get('mode','r')
            if path==target and ('w' in mode or 'x' in mode) and not created:
                created=True
                with original(path,'wb') as stream:stream.write(b'synthetic late leaf sentinel')
            return original(path,*args,**kwargs)
        with mock.patch.object(Path,'open',late_leaf):
            self.assert_rejected_without_changing(self.restore,target,b'synthetic late leaf sentinel')
        self.assertTrue(created)

    def test_parent_escape_is_rejected_before_any_git_or_file_write(self):
        target=self.missing_input();sentinel=self.root/'outside.json';sentinel.write_bytes(b'synthetic outside sentinel')
        blob=hashlib.sha1(('blob '+str(len(self.DATA))+'\0').encode()+self.DATA).hexdigest()
        def git(*args,cwd):
            if args[:3]==('git','cat-file','-t'):return 'blob'
            if args[:3]==('git','cat-file','-s'):return str(len(self.DATA))
            return blob
        with mock.patch.object(prepare,'BASELINE_NODE_INPUTS',
                {'../outside.json':(len(self.DATA),hashlib.sha256(self.DATA).hexdigest(),blob)}), \
             mock.patch.object(prepare,'run',side_effect=git) as calls, \
             mock.patch.object(prepare.subprocess,'check_output',return_value=self.DATA):
            self.assert_rejected_without_changing(lambda:prepare.restore_original_baseline_node_inputs(self.destination),sentinel,b'synthetic outside sentinel')
        calls.assert_not_called()
        self.assertFalse(target.exists())

    def test_blob_read_failure_does_not_create_an_output_or_change_the_source(self):
        target=self.missing_input()
        with mock.patch.object(prepare.subprocess,'check_output',side_effect=OSError),self.assertRaises(OSError):self.restore()
        self.assertFalse(target.exists())
        self.assertEqual((self.seed/self.INPUT).read_bytes(),self.DATA)


if __name__=='__main__':unittest.main()
