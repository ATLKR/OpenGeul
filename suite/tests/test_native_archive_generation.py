"""Read-only first-attachment metadata; no Windows input or model calls."""
from contextlib import ExitStack
import copy
import importlib.util
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


E2E = Path(__file__).resolve().parents[1]/'e2e'
sys.path.insert(0, str(E2E))


def load(name):
    spec = importlib.util.spec_from_file_location('archive_generation_'+name, E2E/(name+'.py'))
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result)
    return result


class NativeArchiveGenerationTests(unittest.TestCase):
    def setUp(self):
        self.native = load('windows_smoke')
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve(); self.events = []
        self.process = SimpleNamespace(pid=77, _handle=707, args=[str(self.root/'OpenGeul.Office.exe')],
            opengeul_suite_root=self.root, poll=lambda:None)
        self.attachment = dict(hwnd=11, parent=12, child=22, officePid=88)
        self.shell = dict(pid=77, handleValue=707, creationTime=100,
            image=str(self.root/'OpenGeul.Office.exe'), waitResult=258)
        self.engine = dict(pid=88, handleValue=808, creationTime=101,
            image=str(self.root/'Office/program/soffice.bin'), waitResult=258)
        self.pids = {11:77,12:77,22:88}
        self.api = SimpleNamespace(pid=lambda hwnd:self.pids[hwnd], attached=lambda process:(11,12,22),
            title=lambda hwnd:'OpenGeul Writer', windows=lambda pid:[],
            user=SimpleNamespace(IsWindow=lambda hwnd:hwnd in self.pids,
                IsChild=lambda parent,child:(parent,child) in ((11,12),(12,22)),
                GetAncestor=lambda hwnd,flag:11, GetForegroundWindow=lambda:11,
                GetPropW=lambda hwnd,name:12 if name.endswith('ParentHwnd') else 22))
        owner = self
        class Probe:
            close_result = True
            engine_reads = 0
            def process_snapshot(self, process):
                owner.events.append('shell-query'); return copy.deepcopy(owner.shell)
            def open_engine(self, pid):
                owner.events.append(('open',pid)); return 808
            def engine_snapshot(self, handle):
                self.engine_reads += 1
                owner.events.append(('engine-query',handle)); return copy.deepcopy(owner.engine)
            def close_engine(self, handle):
                owner.events.append(('close',handle)); return self.close_result
        self.probe = Probe()

    def capture(self):
        return self.native.capture_native_archive_generation(self.api,self.process,self.attachment,probe=self.probe)

    def test_original_attachment_projects_three_fields_and_closes_one_query_handle(self):
        result = self.capture()
        self.assertEqual(dict(pid=88,creationTime=101,image=self.engine['image']), result)
        self.assertEqual(1, self.events.count(('open',88)))
        self.assertEqual(1, self.events.count(('close',808)))
        self.assertEqual(2, self.events.count(('engine-query',808)))
        self.assertEqual(2, self.events.count('shell-query'))
        self.assertEqual(self.attachment, dict(hwnd=11,parent=12,child=22,officePid=88))

    def test_foreign_or_stale_engine_identity_fails_and_releases_the_query_handle(self):
        for key,value in (('pid',99),('handleValue',999),('creationTime',0),('creationTime',99),
                          ('creationTime',True),('image',str(self.root/'foreign.exe')),('waitResult',0)):
            with self.subTest(key=key,value=value):
                original = dict(self.engine); self.engine[key] = value; self.events.clear()
                try:
                    with self.assertRaises(AssertionError): self.capture()
                    self.assertEqual(1, self.events.count(('close',808)))
                finally: self.engine = original

    def test_foreign_attachment_rejects_before_opening_a_process(self):
        self.pids[12] = 99
        with self.assertRaises(AssertionError): self.capture()
        self.assertNotIn(('open',88), self.events)

    def test_attachment_or_generation_replacement_during_capture_cannot_pass(self):
        original = self.probe.engine_snapshot
        for target in ('attachment','engine','shell'):
            with self.subTest(target=target):
                self.probe.engine_reads=0; self.pids[22]=88; self.shell['creationTime']=100; self.events.clear()
                def snapshot(handle):
                    value = original(handle)
                    if self.probe.engine_reads == 2:
                        if target=='attachment': self.pids[22]=99
                        elif target=='engine': value['creationTime']+=1
                        else: self.shell['creationTime']+=1
                    return value
                self.probe.engine_snapshot = snapshot
                with self.assertRaises(AssertionError): self.capture()
                self.assertEqual(1, self.events.count(('close',808)))

    def test_helper_handle_close_failure_is_visible_without_masking_primary_failure(self):
        self.probe.close_result = False
        with self.assertRaisesRegex(AssertionError,'HANDLE close'): self.capture()
        self.assertEqual(1, self.events.count(('close',808)))
        first = RuntimeError('synthetic original identity failure'); self.events.clear()
        self.probe.engine_snapshot = lambda handle:(_ for _ in ()).throw(first)
        with self.assertRaises(RuntimeError) as caught: self.capture()
        self.assertIs(first, caught.exception)
        self.assertTrue(any('HANDLE close' in note for note in caught.exception.__notes__))
        self.assertEqual(1, self.events.count(('close',808)))

    def test_elapsed_metadata_bound_rejects_after_return_without_renewal_and_closes_handle(self):
        with patch.object(self.native.time,'monotonic',side_effect=(1.,7.)):
            with self.assertRaisesRegex(AssertionError,'metadata.*bound'): self.capture()
        self.assertEqual(1, self.events.count(('close',808)))

    def test_late_handle_release_cannot_admit_the_next_editor_action(self):
        clock = [1.]
        original = self.probe.close_engine
        def close(handle):
            result = original(handle); clock[0] = 7.; return result
        self.probe.close_engine = close
        with patch.object(self.native.time,'monotonic',side_effect=lambda:clock[0]):
            with self.assertRaisesRegex(AssertionError,'metadata.*bound'): self.capture()
        self.assertEqual(1, self.events.count(('close',808)))

    def desktop(self):
        window = SimpleNamespace(maximize=lambda:self.events.append('maximize'),
            capture_as_image=lambda:SimpleNamespace(save=lambda path:None))
        return SimpleNamespace(Desktop=lambda **kw:SimpleNamespace(
            window=lambda **kw:SimpleNamespace(wrapper_object=lambda:window)))

    def test_new_document_captures_original_generation_before_window_actions_or_close(self):
        with patch.dict(sys.modules, {'pywinauto':self.desktop()}), \
                patch('counted_editor_shortcuts.NativeShortcutProbe',return_value=self.probe), ExitStack() as stack:
            for name,value in (('launch_suite',lambda *a:self.process),('Windows',lambda:self.api),
                    ('verified_attachment',lambda *a:(11,12,22,88)),('activate_owned_suite',lambda *a:self.events.append('activate')),
                    ('close_document',lambda *a:self.events.append('document-close')),('close_home',lambda *a:None),
                    ('stop_owned_test_process',lambda *a:None)):
                stack.enter_context(patch.object(self.native,name,value))
            record = self.native.new_module(self.root,self.root,'writer')
        self.assertEqual(dict(pid=88,creationTime=101,image=self.engine['image']),record['nativeArchiveGeneration'])
        self.assertLess(self.events.index(('close',808)),self.events.index('maximize'))
        self.assertLess(self.events.index(('close',808)),self.events.index('document-close'))

    def test_lifecycle_only_explicit_clean_attachment_opens_metadata_witness(self):
        life = load('lifecycle_smoke')
        for retain in (False,True):
            with self.subTest(retain=retain):
                self.events.clear()
                case = object.__new__(life.Case); case.api=self.api; case.process=self.process; case.record={}
                with patch.dict(sys.modules,{'pywinauto':self.desktop()}), \
                        patch('counted_editor_shortcuts.NativeShortcutProbe',return_value=self.probe), \
                        patch.object(life.native,'activate_owned_suite',side_effect=lambda *a:self.events.append('activate')):
                    self.assertEqual((11,12,22),case.attach(retain_archive_generation=retain))
                attachment = case.record['attachments'][0]
                if retain:
                    self.assertEqual(dict(pid=88,creationTime=101,image=self.engine['image']),attachment['nativeArchiveGeneration'])
                    self.assertLess(self.events.index(('close',808)),self.events.index('maximize'))
                else:
                    self.assertNotIn('nativeArchiveGeneration',attachment)
                    self.assertNotIn(('open',88),self.events)

    def test_home_two_documents_marks_only_the_first_clean_attachment_for_metadata(self):
        life = load('lifecycle_smoke'); captures = []
        process = SimpleNamespace(pid=77,poll=lambda:None)
        api = SimpleNamespace(home=lambda process:5, require_foreground=lambda hwnd:None,
            request_close=lambda *a:None, title=lambda hwnd:'* OpenGeul Writer',
            user=SimpleNamespace(IsWindow=lambda hwnd:hwnd in (5,21,22)))
        def attach(*,previous=(),retain_archive_generation=False):
            captures.append(retain_archive_generation)
            return (11,12,13) if not previous else (21,23,22)
        case = SimpleNamespace(api=api,process=process,record={},folder=self.root,attach=attach,
            new_from_menu=lambda *a:None,edit=lambda *a:None,click_dialog=lambda *a:None,
            closed=lambda *a:None,shell_command=lambda *a:None,picker=lambda *a:99,
            saved=lambda *a:None,finish=lambda *a:None)
        button = SimpleNamespace(element_info=SimpleNamespace(name='OpenGeul Writer',process_id=77),click_input=lambda:None)
        desktop = SimpleNamespace(Desktop=lambda **kw:SimpleNamespace(window=lambda **kw:SimpleNamespace(
            descendants=lambda **kw:[button])))
        with patch.dict(sys.modules,{'pywinauto':desktop}), \
                patch.object(life.native,'activate_owned_suite'), \
                patch.object(life.native,'wait_for',side_effect=lambda check,*args:check()), \
                patch.object(life,'owned_target',return_value=self.root/'synthetic-owned.docx'):
            life.home_two_documents(case)
        self.assertEqual([True,False],captures)


if __name__ == '__main__': unittest.main()
