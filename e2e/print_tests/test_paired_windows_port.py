import copy
import contextlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / 'paired_print_windows.py'
sys.path.insert(0, str(FILE.parent))
if FILE.exists():
    spec = importlib.util.spec_from_file_location('paired_windows_candidate', FILE)
    api = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(api)
else:
    api = None
import paired_print_contract as core


class ReadRegularIdentityTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.path=Path(temporary.name)/'synthetic-stat-input'
        self.raw=b'SYNTHETIC-STAT-ONLY';self.path.write_bytes(self.raw)

    @contextlib.contextmanager
    def metadata(self,*,platform='nt',birth=1000,missing_birth=False,
                 before_change=None,open_change=None,after_change=None,final_change=None,distinct_ctime=True):
        path_lstat,fd_stat=Path.lstat,os.fstat
        counts=dict(path=0,handle=0)
        def changed(info,changes=None,*,handle=False):
            value={key:getattr(info,key) for key in
                ('st_dev','st_ino','st_mode','st_nlink','st_size','st_mtime_ns')}
            value.update(st_ctime_ns=2000 if handle and distinct_ctime else 1000,st_file_attributes=0)
            if not missing_birth:value['st_birthtime_ns']=birth
            value.update(changes or {});return SimpleNamespace(**value)
        def lstat(path,*args,**kwargs):
            info=path_lstat(path,*args,**kwargs)
            if path!=self.path:return info
            counts['path']+=1
            return changed(info,final_change if counts['path']>1 else before_change)
        def fstat(fd):
            counts['handle']+=1
            return changed(fd_stat(fd),open_change if counts['handle']==1 else after_change,handle=True)
        with mock.patch.object(api,'os',SimpleNamespace(name=platform,fstat=fstat)),mock.patch.object(Path,'lstat',lstat):
            yield counts

    def test_windows_same_file_allows_creation_and_change_time_to_differ(self):
        with self.metadata() as counts:
            try:data,_=api.read_regular(self.path,128)
            except core.Rejected:self.fail('Stable Windows creation/change times must be compatible')
        self.assertEqual(data,self.raw);self.assertEqual(counts,dict(path=2,handle=2))

    def test_windows_birth_time_is_mandatory_and_strictly_integer(self):
        cases=[dict(missing_birth=True)]+[dict(birth=value) for value in (None,True,1000.0,'1000')]
        for index,options in enumerate(cases):
            with self.subTest(caseNumber=index),self.metadata(distinct_ctime=False,**options),self.assertRaises(core.Rejected):
                api.read_regular(self.path,128)

    def test_windows_birth_time_must_match_across_and_within_apis(self):
        for index,phase in enumerate(('open_change','after_change','final_change')):
            with self.subTest(caseNumber=index),self.metadata(distinct_ctime=False,**{phase:{'st_birthtime_ns':1001}}),self.assertRaises(core.Rejected):
                api.read_regular(self.path,128)

    def test_each_windows_api_retains_its_own_change_time_stability(self):
        for index,phase in enumerate(('after_change','final_change')):
            changes={'st_ctime_ns':2001 if phase=='after_change' else 1001}
            with self.subTest(caseNumber=index),self.metadata(**{phase:changes}) as counts,self.assertRaises(core.Rejected):
                api.read_regular(self.path,128)
            self.assertEqual(counts['handle'],2)
            if phase=='final_change':self.assertEqual(counts['path'],2)

    def test_original_identity_alias_and_type_guards_remain_fail_closed(self):
        info=self.path.stat()
        changes=({'st_dev':info.st_dev+1},{'st_ino':info.st_ino+1},{'st_size':info.st_size+1},
            {'st_mtime_ns':info.st_mtime_ns+1},{'st_nlink':2},{'st_file_attributes':0x400},{'st_mode':0})
        for phase in ('open_change','after_change','final_change'):
            for index,change in enumerate(changes):
                with self.subTest(phaseCode=('open_change','after_change','final_change').index(phase),caseNumber=index), \
                     self.metadata(distinct_ctime=False,**{phase:change}),self.assertRaises(core.Rejected):
                    api.read_regular(self.path,128)

    def test_unix_keeps_ctime_identity_and_does_not_require_birth_time(self):
        with self.metadata(platform='posix',missing_birth=True,distinct_ctime=False):
            self.assertEqual(api.read_regular(self.path,128)[0],self.raw)
        with self.metadata(platform='posix',missing_birth=True),self.assertRaises(core.Rejected):
            api.read_regular(self.path,128)

    def test_original_size_and_time_caps_still_reject(self):
        with self.metadata(),self.assertRaises(core.Rejected):api.read_regular(self.path,len(self.raw)-1)
        ticks=iter((0,11))
        with self.metadata(),self.assertRaises(core.Rejected):api.read_regular(self.path,128,clock=lambda:next(ticks))


class FixedFontReadTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.fonts=self.root/'Fonts';self.fonts.mkdir()
        self.path=self.fonts/'arial.ttf';self.raw=b'SYNTHETIC-READONLY-OS-FONT';self.path.write_bytes(self.raw)

    @contextlib.contextmanager
    def windows_directory(self,*,same_private=False):
        import ctypes
        calls=dict(system=0,private=0)
        root=self.root
        class Getter:
            def __init__(self,key):self.key=key
            def __call__(self,buffer,cap):
                calls[self.key]+=1
                buffer.value=str(root if self.key=='system'or same_private else root/'private-windows')
                return len(buffer.value)
        kernel=SimpleNamespace(GetSystemWindowsDirectoryW=Getter('system'),GetWindowsDirectoryW=Getter('private'))
        with mock.patch.object(ctypes,'WinDLL',return_value=kernel,create=True):yield calls

    def metadata(self,**kwargs):return ReadRegularIdentityTests.metadata(self,**kwargs)

    def test_fixed_font_single_link_uses_only_system_windows_api(self):
        with self.windows_directory()as calls:result=api.sampled_fonts()
        self.assertEqual(calls,dict(system=1,private=0))
        self.assertTrue(result['files'][0]['present'])
        self.assertEqual(result['files'][0]['bytes'],len(self.raw))
        self.assertFalse(result['files'][1]['present'])

    def test_actual_two_link_font_is_read_but_default_reader_still_rejects(self):
        os.link(self.path,self.root/'font-alias')
        self.assertEqual(self.path.stat().st_nlink,2)
        with self.windows_directory(same_private=True):
            try:result=api.sampled_fonts()
            except core.Rejected:self.fail('Fixed stable two-link OS font should be sampled')
        self.assertTrue(result['files'][0]['present'])
        self.assertEqual(result['files'][0]['sha256'],__import__('hashlib').sha256(self.raw).hexdigest())
        with self.assertRaises(core.Rejected):api.read_regular(self.path,128)
        with self.assertRaises(core.Rejected):api.fingerprint_file(self.path)

    def test_font_read_keeps_four_stats_and_windows_time_domains(self):
        os.link(self.path,self.root/'font-alias')
        with self.metadata()as counts:
            result=api._font_fingerprint(self.path,self.fonts)
        self.assertEqual(result['bytes'],len(self.raw));self.assertEqual(counts,dict(path=2,handle=2))

    def test_link_count_changes_are_rejected_even_between_two_allowed_values(self):
        for original,changed in ((1,2),(2,1)):
            alias=self.root/'font-alias'
            if original==2:os.link(self.path,alias)
            for phase in ('open_change','after_change','final_change'):
                with self.subTest(original=original,phase=phase),self.metadata(**{phase:{'st_nlink':changed}}),self.assertRaises(core.Rejected):
                    api._font_fingerprint(self.path,self.fonts)
            if original==2:alias.unlink()

    def test_font_only_link_domain_is_exact_one_or_two_at_every_stat(self):
        for phase in ('before_change','open_change','after_change','final_change'):
            for value in (0,3,True,1.0,'2'):
                with self.subTest(phase=phase,valueType=type(value).__name__),self.metadata(**{phase:{'st_nlink':value}}),self.assertRaises(core.Rejected):
                    api._font_fingerprint(self.path,self.fonts)

    def test_font_read_rejects_reparse_mode_and_changed_original_identity(self):
        info=self.path.stat()
        changes=({'st_dev':info.st_dev+1},{'st_ino':info.st_ino+1},{'st_size':info.st_size+1},
            {'st_mtime_ns':info.st_mtime_ns+1},{'st_birthtime_ns':1001},
            {'st_file_attributes':0x400},{'st_mode':0})
        for phase in ('before_change','open_change','after_change','final_change'):
            for index,change in enumerate(changes):
                with self.subTest(phase=phase,change=index),self.metadata(**{phase:change}),self.assertRaises(core.Rejected):
                    api._font_fingerprint(self.path,self.fonts)

    def test_font_keeps_same_api_ctime_stability_and_mandatory_birthtime(self):
        for phase,value in (('after_change',2001),('final_change',1001)):
            with self.subTest(phase=phase),self.metadata(**{phase:{'st_ctime_ns':value}}),self.assertRaises(core.Rejected):
                api._font_fingerprint(self.path,self.fonts)
        with self.metadata(missing_birth=True),self.assertRaises(core.Rejected):api._font_fingerprint(self.path,self.fonts)

    def test_font_name_and_original_root_are_checked_before_filesystem_read(self):
        for path,root in ((self.fonts/'other.ttf',self.fonts),(self.root/'other'/'arial.ttf',self.fonts),
                (self.path,self.root/'OtherFonts'),(self.path,Path('Fonts'))):
            with self.subTest(caseNumber=(path.name=='arial.ttf')),\
                    mock.patch.object(Path,'lstat',side_effect=AssertionError('Stat reached')),\
                    mock.patch.object(Path,'open',side_effect=AssertionError('Open reached')),self.assertRaises(core.Rejected):
                api._font_fingerprint(path,root)

    def test_font_limits_remain_thirty_two_mib_and_ten_seconds(self):
        with self.metadata(before_change={'st_size':32*1024*1024+1}),\
                mock.patch.object(Path,'open',side_effect=AssertionError('Open reached')),self.assertRaises(core.Rejected):
            api._font_fingerprint(self.path,self.fonts)
        ticks=iter((0,11))
        with self.metadata(),mock.patch.object(api,'time',SimpleNamespace(monotonic=lambda:next(ticks))),self.assertRaises(core.Rejected):
            api._font_fingerprint(self.path,self.fonts)

    def test_font_parent_or_file_symlink_is_not_followed(self):
        target=self.root/'original-font';self.path.rename(target);self.path.symlink_to(target)
        with mock.patch.object(Path,'open',side_effect=AssertionError('Open reached')),self.assertRaises(core.Rejected):
            api._font_fingerprint(self.path,self.fonts)
        self.path.unlink();target.rename(self.path)
        alias=self.root/'alias-windows';alias.symlink_to(self.root,target_is_directory=True)
        with mock.patch.object(Path,'open',side_effect=AssertionError('Open reached')),self.assertRaises(core.Rejected):
            api._font_fingerprint(alias/'Fonts/arial.ttf',alias/'Fonts')

    def test_font_parent_reparse_bit_is_rejected_before_open(self):
        import stat
        original=Path.lstat
        def lstat(path,*args,**kwargs):
            if path==self.fonts:return SimpleNamespace(st_mode=stat.S_IFDIR|0o755,st_file_attributes=0x400)
            return original(path,*args,**kwargs)
        with mock.patch.object(Path,'lstat',lstat),\
                mock.patch.object(Path,'open',side_effect=AssertionError('Open reached')),self.assertRaises(core.Rejected):
            api._font_fingerprint(self.path,self.fonts)


class WindowsPortTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(api, 'Windows port absent')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.fixture = self.folder / 'synthetic.hwpx'
        self.fixture.write_bytes(b'SYNTHETIC-ONLY')
        self.exe = self.folder / 'OpenGeul.exe'
        self.exe.write_bytes(b'FIXED-EXE')
        from PIL import Image, ImageDraw
        from print_raster import fingerprint
        self.image = Image.new('L', (100, 120), 255)
        ImageDraw.Draw(self.image).rectangle((10, 10, 40, 30), fill=0)
        self.fingerprint = fingerprint(self.image)
        self.renderer = {'roleCode': 1, 'label': 'locked-hwp114',
                         'appSourceCommit': '1' * 40, 'executableSha256': api.fingerprint_file(self.exe)['sha256'],
                         'executableBytes': self.exe.stat().st_size,
                         'wasmSha256': '2' * 64, 'jsSha256': '3' * 64,
                         'harnessSourceCommit': '4' * 40, 'harnessRunId': 17, 'harnessRunAttempt': 1}
        fp = api.fingerprint_file(self.fixture)
        self.binding = {'caseCode': 1, 'sha256': fp['sha256'], 'bytes': fp['bytes']}
        self.primary = ValueError('SYNTHETIC-ORACLE-ONLY')
        self.events = []
        test = self

        class Lease:
            def __exit__(self, *args):
                test.events.append('sealed')
                return False
            def wait_retired(self):
                test.events.append('retired')
                return {'retainedRootExited': True, 'retainedWebviewCount': 2,
                        'retainedWebviewsExited': True}
            def close(self):
                test.events.append('closed')

        self.lease = Lease()
        self.runtime = {'mode': 'native', 'executableSha256': self.renderer['executableSha256'],
            'fixtureSha256': self.binding['sha256'],
            'nativeArchitecture': {'processId': 41, 'architecture': 'x64', 'peMachine': 0x8664,
                'processMachine': 0, 'nativeMachine': 0x8664, 'native': True,
                'runningAtInspection': True, 'sha256': self.renderer['executableSha256'],
                'bytes': self.renderer['executableBytes'], 'imagePath': str(self.exe),
                'helperSha256': '5' * 64, 'sourceCommit': '4' * 40,
                'sourceRun': '17', 'runAttempt': '1'}, 'webview2Native': {'rootProcessId': 41}}

        def printer(exe, fixture, case, folder, *, admission):
            from types import SimpleNamespace
            folder.mkdir(parents=True)
            (folder / 'session').mkdir()
            (folder / 'session/runtime.json').write_text(json.dumps(test.runtime))
            profile = test.folder / 'requested-owned-profile'
            profile.mkdir(exist_ok=True)
            session = SimpleNamespace(profile=str(profile), proc=SimpleNamespace(pid=41))
            observer = admission(session, folder)
            (folder / 'source-preservation.json').write_text(json.dumps(
                {'before': test.binding['sha256'], 'after': test.binding['sha256'], 'unchanged': True}))
            (folder / 'spooler.json').write_text(json.dumps({'queue': 'OpenGeul-CI-SYNTHETIC',
                'jobs': [{'JobId': 1, 'pPrinterName': 'OpenGeul-CI-SYNTHETIC',
                          'pDocument': 'synthetic.hwpx', 'pStatus': None, 'Status': 128,
                          'TotalPages': 1, 'PagesPrinted': 1}],
                'jobMedia': {'PaperSize': 9, 'PaperLength': 2970, 'PaperWidth': 2100, 'Orientation': 1}}))
            (folder / 'printed.pdf').write_bytes(b'%PDF-SYNTHETIC\n%%EOF')
            (folder / 'pdf-check').mkdir()
            test.image.save(folder / 'pdf-check/page-1.png')
            observer.__exit__(None, None, None)
            if test.fail_oracle:
                (folder / 'pdf-check/page-1-mismatch.json').write_text(json.dumps(
                    {'expected': {**test.fingerprint, 'ink': test.fingerprint['ink'] + 1},
                     'actual': test.fingerprint}))
                raise test.primary
            return {'sha256': api.fingerprint_file(folder / 'printed.pdf')['sha256'],
                    'checks': [{**test.fingerprint, 'page': 1, 'size_pt': [595.28, 841.86]}]}

        self.printer = printer
        self.fail_oracle = False

    def port(self, **kw):
        def raster(p, c):
            data, _ = api.read_regular(p, 8 * 1024 * 1024)
            import hashlib
            return {'raster': copy.deepcopy(self.fingerprint),
                    'pdfSha256': hashlib.sha256(data).hexdigest(), 'pdfBytes': len(data)}
        return api.WindowsPort({1: self.exe}, {1: {'name': 'table--300', 'path': self.fixture,
            'pages': [{'size_pt': [595.28, 841.86]}]}}, self.folder / 'private-attempts',
            printer=self.printer, lease_factory=lambda s, r: self.lease,
            raster_reader=raster,
            oracle_error=lambda e: e is self.primary,
            font_reader=lambda: {'scopeCode': 1, 'files': []}, native_helper_sha='5' * 64, **kw)

    def test_success_uses_real_print_signature_and_retained_barrier(self):
        value = self.port().print_case(self.renderer, self.binding)
        self.assertTrue(value['originalOraclePassed'])
        self.assertEqual(self.events, ['sealed', 'retired', 'closed'])
        self.assertEqual(value['fixtureBeforeSha256'], self.binding['sha256'])

    def test_original_oracle_error_is_retained_in_memory_and_never_relabelled(self):
        self.fail_oracle = True
        port = self.port()
        value = port.print_case(self.renderer, self.binding)
        self.assertFalse(value['originalOraclePassed'])
        self.assertEqual(value['primaryErrorCode'], 1)
        self.assertNotIn('SYNTHETIC-ORACLE', json.dumps(value))
        with self.assertRaises(ValueError) as caught:
            port.raise_original_oracle()
        self.assertIs(caught.exception, self.primary)

    def test_unknown_retirement_blocks_observation_and_next_role(self):
        def bad(): raise core.Rejected(15)
        self.lease.wait_retired = bad
        with self.assertRaises(core.Rejected): self.port().print_case(self.renderer, self.binding)

    def test_changed_original_fixture_prevents_all_inputs(self):
        self.fixture.write_bytes(b'CHANGED')
        with self.assertRaises(core.Rejected): self.port().print_case(self.renderer, self.binding)
        self.assertEqual(self.events, [])

    def test_wrong_binary_hash_prevents_all_inputs(self):
        self.renderer['executableSha256'] = '9' * 64
        with self.assertRaises(core.Rejected): self.port().print_case(self.renderer, self.binding)
        self.assertEqual(self.events, [])

    def test_spooler_and_source_proof_are_required_on_oracle_failure(self):
        self.fail_oracle = True
        original = self.printer
        def missing(*args, **kw):
            try: return original(*args, **kw)
            finally: (args[3] / 'spooler.json').unlink()
        self.printer = missing
        port = self.port()
        with self.assertRaises(ValueError) as caught: port.print_case(self.renderer, self.binding)
        self.assertIs(caught.exception, self.primary)

    def test_requested_profile_is_not_actual_selected_profile(self):
        port = self.port()
        port.print_case(self.renderer, self.binding)
        proof = port.profile_observations[0]
        self.assertFalse(proof['actualSelectedProfileKnown'])
        self.assertEqual(proof['scopeCode'], 1)
        self.assertNotIn('path', proof)

    def test_foreign_preexisting_work_directory_is_not_adopted(self):
        work = self.folder / 'private-attempts'
        work.mkdir()
        with self.assertRaises(core.Rejected): self.port()

    def test_duplicate_json_key_is_rejected_without_message(self):
        p = self.folder / 'duplicate.json'
        p.write_bytes(b'{"x":1,"x":2}')
        with self.assertRaises(core.Rejected): api.read_json(p)

    def test_hardlinked_evidence_is_rejected(self):
        import os
        other = self.folder / 'alias'
        os.link(self.fixture, other)
        with self.assertRaises(core.Rejected): api.fingerprint_file(self.fixture)

    def test_read_only_request_never_claims_profile_or_glyph_identity(self):
        self.assertEqual(api.PROFILE_SCOPE, 'requested-owned-profile')
        self.assertFalse(api.ACTUAL_PROFILE_KNOWN)

    def test_old_binary_keeps_current_harness_identity_not_old_compile_source(self):
        self.runtime['nativeArchitecture']['sourceCommit'] = self.renderer['appSourceCommit']
        with self.assertRaises(core.Rejected): self.port().print_case(self.renderer, self.binding)
        self.assertEqual(self.events, [])

    def test_actual_process_sample_must_match_the_independent_runtime_hash(self):
        self.runtime['nativeArchitecture']['sha256'] = '9' * 64
        with self.assertRaises(core.Rejected): self.port().print_case(self.renderer, self.binding)
        self.assertEqual(self.events, [])

    def test_actual_loaded_fixture_and_native_helper_are_bound(self):
        self.runtime['fixtureSha256'] = '9' * 64
        with self.assertRaises(core.Rejected): self.port().print_case(self.renderer, self.binding)
        self.assertEqual(self.events, [])

    def test_unwrapped_matcher_error_has_no_real_print_wrapper_authority(self):
        import print_raster
        ref = {'pixels': [100, 120], 'bbox': [1, 2, 60, 100], 'ink': 500, 'maskSha256': 'a' * 64}
        try:
            print_raster.match_reference({**ref, 'ink': 501}, ref, {}, 'synthetic', 1)
        except ValueError as error:
            self.assertFalse(api.is_ink_mismatch(error))
        else: self.fail('unchanged oracle failed to reject')

    def test_real_pdf_wrapper_and_its_exact_original_context_are_comparable(self):
        import print_raster
        from reportlab.pdfgen.canvas import Canvas
        from unittest import mock
        pdf = self.folder / 'synthetic.pdf'
        canvas = Canvas(str(pdf), pagesize=(595.28, 841.86))
        canvas.setFillColorRGB(0, 0, 0)
        canvas.rect(80, 700, 70, 30, fill=1)
        canvas.save()
        expected = api.read_single_raster(pdf, {'pages': [{'size_pt': [595.28, 841.86]}]})['raster']
        expected['maskSha256'] = '9' * 64
        book = self.folder / 'synthetic-reference.json'
        book.write_text(json.dumps({'schema': 1, 'scale': 3, 'sourceRun': 'synthetic-only',
            'productCommit': 'synthetic-only', 'cases': {'synthetic': [expected]}}))
        with mock.patch.object(print_raster, 'REFERENCE', book):
            try:
                print_raster.inspect_print_pdf(pdf, {'pages': [{'size_pt': [595.28, 841.86]}]},
                                              self.folder / 'synthetic-check', 'synthetic')
            except ValueError as error:
                self.assertIs(type(error.__context__), ValueError)
                self.assertTrue(api.is_ink_mismatch(error))
            else: self.fail('unchanged oracle failed to reject')

    def test_foreign_wrapper_with_real_matcher_context_has_no_authority(self):
        import print_raster
        ref = {'pixels': [100, 120], 'bbox': [1, 2, 60, 100], 'ink': 500, 'maskSha256': 'a' * 64}
        try:
            try: print_raster.match_reference({**ref, 'ink': 501}, ref, {}, 'synthetic', 1)
            except ValueError: raise ValueError('SYNTHETIC-FOREIGN-WRAPPER')
        except ValueError as error:
            self.assertFalse(api.is_ink_mismatch(error))

    def test_invalid_reference_metadata_is_not_a_comparable_ink_change(self):
        import print_raster
        try:
            print_raster.match_reference({}, {}, {'reviewedVariants': [None]}, 'synthetic', 1)
        except ValueError as error:
            self.assertFalse(api.is_ink_mismatch(error))
        else: self.fail('unchanged oracle failed to reject')

    def test_similar_error_text_without_original_source_frame_has_no_oracle_authority(self):
        self.assertFalse(api.is_ink_mismatch(ValueError('SYNTHETIC-SIMILAR-ONLY')))

    def test_pdf_swap_between_raster_buffer_and_artifact_hash_is_rejected(self):
        port = self.port()
        original = port.raster_reader
        def changed(path, case):
            result = original(path, case)
            path.write_bytes(b'%PDF-DIFFERENT\n%%EOF')
            return result
        port.raster_reader = changed
        with self.assertRaises(core.Rejected): port.print_case(self.renderer, self.binding)

    def test_stored_png_pixels_must_match_the_pdf_raster_not_only_dimensions(self):
        port = self.port()
        original = port.raster_reader
        def changed(path, case):
            from PIL import Image
            result = original(path, case)
            Image.new('L', (100, 120), 0).save(path.parent / 'pdf-check/page-1.png')
            return result
        port.raster_reader = changed
        with self.assertRaises(core.Rejected): port.print_case(self.renderer, self.binding)

    def test_successful_oracle_pdf_hash_must_match_the_same_raster_buffer(self):
        original = self.printer
        def wrong(*args, **kw):
            result = original(*args, **kw)
            result['sha256'] = '9' * 64
            return result
        self.printer = wrong
        with self.assertRaises(core.Rejected): self.port().print_case(self.renderer, self.binding)

    def test_failed_oracle_actual_mask_must_match_the_same_raster_buffer(self):
        self.fail_oracle = True
        original = self.printer
        def wrong(*args, **kw):
            try: return original(*args, **kw)
            finally:
                path = args[3] / 'pdf-check/page-1-mismatch.json'
                value = json.loads(path.read_bytes())
                value['actual']['ink'] += 1
                path.write_text(json.dumps(value))
        self.printer = wrong
        with self.assertRaises(ValueError) as caught: self.port().print_case(self.renderer, self.binding)
        self.assertIs(caught.exception, self.primary)


if __name__ == '__main__': unittest.main()
