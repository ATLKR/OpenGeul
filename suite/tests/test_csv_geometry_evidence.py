"""Typed Win32 boundary tests; synthetic data is not native Windows evidence."""
import ctypes
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'e2e'))


class Function:
    def __init__(self, action): self.action = action
    def __call__(self, *args):
        # Assert each real caller has declared pointer-sized signatures.
        assert hasattr(self, 'argtypes') and hasattr(self, 'restype')
        return self.action(*args)


class Boundary:
    def __init__(self, module):
        self.m = module; self.context = 123; self.calls = []; self.denied = None; self.work_rect = [0,0,1024,768]
        self.parents = {11: 0, 12: 11, 22: 12, 33: 0}
        self.pids = {11: 77, 12: 77, 22: 88, 33: 99}
        self.rects = {11: [-10, -10, 1050, 800], 12: [0, 60, 1040, 750],
                      22: [0, 60, 1040, 750], 33: [0, 720, 1024, 768]}
        self.client = {11: [0, 0, 1040, 770], 12: [0, 0, 1040, 690], 22: [0, 0, 1040, 690], 33: [0, 0, 1024, 48]}
        self.origins = {11: [0, 20], 12: [0, 60], 22: [0, 60], 33: [0, 720]}
        self.user = NS(); self.shell = NS()
        actions = dict(SetThreadDpiAwarenessContext=self.set_context,
            GetThreadDpiAwarenessContext=lambda: self.context,
            AreDpiAwarenessContextsEqual=lambda a,b: self.number(a)==self.number(b),
            IsWindow=lambda h: h in self.parents, IsWindowVisible=lambda h: 1,
            GetWindowThreadProcessId=self.identity, GetParent=lambda h:self.parents[h],
            GetAncestor=lambda h,mode: 33 if h==33 else 11,
            IsChild=lambda parent,child:(parent,child) in ((11,12),(12,22),(11,22)),
            GetPropW=lambda h,name:12 if name.endswith('ParentHwnd') else 22,
            GetWindowRect=self.window_rect, GetClientRect=self.client_rect,
            ClientToScreen=self.to_screen, MonitorFromWindow=lambda h,flags:0x100000002,
            GetMonitorInfoW=self.monitor, GetDpiForWindow=lambda h:192,
            GetWindowPlacement=self.placement, GetPhysicalCursorPos=self.cursor,
            FindWindowW=lambda cls,title:33, GetClassNameW=self.class_name)
        for name, action in actions.items(): setattr(self.user, name, Function(action))
        self.shell.SHAppBarMessage=Function(self.appbar)
    @staticmethod
    def number(value): return value.value if hasattr(value,'value') else value
    def set_context(self, context):
        old=self.context; self.context=self.number(context); self.calls.append(('dpi',self.context)); return old
    def identity(self, hwnd, pointer):
        pointer._obj.value=self.pids[hwnd]; return hwnd+100
    def window_rect(self, hwnd, pointer):
        if self.denied==hwnd: return 0
        for key,value in zip(('left','top','right','bottom'),self.rects[hwnd]):setattr(pointer._obj,key,value)
        return 1
    def client_rect(self, hwnd, pointer):
        for key,value in zip(('left','top','right','bottom'),self.client[hwnd]):setattr(pointer._obj,key,value)
        return 1
    def to_screen(self, hwnd, pointer):
        pointer._obj.x+=self.origins[hwnd][0];pointer._obj.y+=self.origins[hwnd][1];return 1
    def monitor(self, handle, pointer):
        for field,values in (('rcMonitor',[0,0,1024,768]),('rcWork',self.work_rect)):
            for key,value in zip(('left','top','right','bottom'),values):setattr(getattr(pointer._obj,field),key,value)
        pointer._obj.dwFlags=1;return 1
    def placement(self, hwnd, pointer): pointer._obj.showCmd=1;return 1
    def cursor(self, pointer):pointer._obj.x=512;pointer._obj.y=767;return 1
    def class_name(self, hwnd, buffer, count):buffer.value='Shell_TrayWnd';return len(buffer.value)
    def appbar(self, operation, pointer):
        if operation==4:return 3  # auto-hide and always-on-top; workarea still full.
        pointer._obj.hWnd=33;pointer._obj.uEdge=3
        for key,value in zip(('left','top','right','bottom'),self.rects[33]):setattr(pointer._obj.rc,key,value)
        return 1


class GeometryContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path=Path(__file__).resolve().parents[1]/'e2e/csv_geometry_evidence.py'
        assert path.is_file(), 'The bounded geometry collector is required'
        spec=importlib.util.spec_from_file_location('csv_geometry_evidence',path)
        cls.m=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.m)
    def fixture(self, root):
        boundary=Boundary(self.m);probe=self.m.GeometryProbe(boundary.user,boundary.shell)
        expected=dict(shellPid=77,shellCreationTime=132000000000000001,shellHandleValue=555,
            officePid=88,officeCreationTime=132000000000000003,officeHandleValue=888,
            windowHwnd=11,parentHwnd=12,childHwnd=22)
        from PIL import Image
        wrapper=NS(handle=11,process_id=lambda:77,is_visible=lambda:True,
            rectangle=lambda:NS(left=-10,top=-10,right=1050,bottom=800),
            capture_as_image=lambda:boundary.calls.append(('capture',)) or Image.new('RGB',(2,3),'white'))
        path=root/'home-open-calc-csv-calc-post-getter.png'
        return boundary,probe,expected,wrapper,path
    def run_capture(self, root, mutate=None):
        b,p,e,w,path=self.fixture(root)
        if mutate:mutate(b,p,e,w)
        error=None
        try:self.m.capture_with_geometry(w,e,path,probe=p)
        except Exception as exc:error=exc
        receipt=json.loads(path.with_name(self.m.SIDECAR_NAME).read_bytes())
        return b,e,path,receipt,error
    def test_win32_signatures_preserve_pointer_width_and_fixed_structure_sizes(self):
        boundary=Boundary(self.m);self.m.GeometryProbe(boundary.user,boundary.shell)
        self.assertEqual(ctypes.sizeof(self.m.Point),8)
        self.assertEqual(ctypes.sizeof(self.m.Rect),16)
        self.assertEqual(ctypes.sizeof(self.m.MonitorInfo),40)
        self.assertEqual(ctypes.sizeof(self.m.WindowPlacement),44)
        self.assertEqual(boundary.user.GetWindowRect.argtypes,(ctypes.c_void_p,ctypes.POINTER(self.m.Rect)))
        for name in ('GetParent','GetAncestor','GetPropW','MonitorFromWindow','FindWindowW',
                     'SetThreadDpiAwarenessContext','GetThreadDpiAwarenessContext'):
            self.assertIs(getattr(boundary.user,name).restype,ctypes.c_void_p)
        self.assertIs(boundary.shell.SHAppBarMessage.restype,ctypes.c_size_t)
        self.assertEqual(boundary.user.GetWindowThreadProcessId.argtypes,
                         (ctypes.c_void_p,ctypes.POINTER(ctypes.c_uint32)))

    def test_physical_mapping_fixed_identity_monitor_workarea_and_exact_png(self):
        with tempfile.TemporaryDirectory() as directory:
            b,e,path,r,error=self.run_capture(Path(directory))
            self.assertIsNone(error);self.assertTrue(r['complete']);self.assertEqual(r['expectedBinding'],e)
            for edge in ('before','after'):
                row=r[edge]['windows'][1]
                self.assertEqual((row['hwnd'],row['pid'],row['tid'],row['parentHwnd'],row['rootHwnd']),(12,77,112,11,11))
                self.assertEqual(row['clientScreenRect'],[0,60,1040,750])
                self.assertEqual(row['monitor']['handle'],0x100000002)
                self.assertEqual(row['monitor']['workRect'],[0,0,1024,768])
            self.assertEqual(r['png'],dict(width=2,height=3,bytes=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
            from io import BytesIO
            from PIL import Image
            original=BytesIO();Image.new('RGB',(2,3),'white').save(original,format='PNG')
            self.assertEqual(path.read_bytes(),original.getvalue())
            self.assertEqual(r['nativeWrapperRectangle'],[-10,-10,1050,800])
            self.assertFalse(r['paintCompleteVerified']);self.assertFalse(r['gridVisibleVerified'])
            self.assertTrue(r['dpiScope']['restored']);self.assertEqual(b.context,123)
            self.assertEqual(b.calls.count(('capture',)),1)
    def test_autohide_and_large_invisible_outer_bounds_are_observations(self):
        with tempfile.TemporaryDirectory() as directory:
            _,_,_,r,error=self.run_capture(Path(directory))
            self.assertIsNone(error)
            self.assertEqual(r['before']['taskbar']['appBarState'],dict(raw=3,autoHide=True,alwaysOnTop=True))
            self.assertEqual(r['before']['windows'][0]['dpi'],192)
            self.assertNotIn('clipped',r);self.assertNotIn('fits',r)
    def test_monitor_workarea_is_queried_independently_of_monitor_and_taskbar(self):
        def mutate(b,p,e,w):b.work_rect=[0,0,1024,700]
        with tempfile.TemporaryDirectory() as directory:
            _,_,_,r,error=self.run_capture(Path(directory),mutate)
            self.assertIsNone(error)
            self.assertEqual(r['before']['windows'][0]['monitor']['workRect'],[0,0,1024,700])
            self.assertEqual(r['before']['taskbar']['windowRect'],[0,720,1024,768])

    def test_zero_appbar_state_is_valid_and_missing_taskbar_or_monitor_is_not(self):
        def zero(b,p,e,w):
            original=b.shell.SHAppBarMessage.action
            b.shell.SHAppBarMessage.action=lambda operation,data:0 if operation==4 else original(operation,data)
        with tempfile.TemporaryDirectory() as directory:
            _,_,_,r,error=self.run_capture(Path(directory),zero)
            self.assertIsNone(error)
            self.assertEqual(r['before']['taskbar']['appBarState'],dict(raw=0,autoHide=False,alwaysOnTop=False))
        for reason in ('taskbar','monitor','client'):
            def mutate(b,p,e,w):
                if reason=='taskbar':b.user.FindWindowW.action=lambda *args:0
                elif reason=='monitor':b.user.GetMonitorInfoW.action=lambda *args:0
                else:b.user.GetClientRect.action=lambda *args:0
            with self.subTest(reason=reason),tempfile.TemporaryDirectory() as directory:
                _,_,_,r,error=self.run_capture(Path(directory),mutate)
                self.assertIsNotNone(error);self.assertFalse(r['before']['complete'])
                self.assertFalse(r['complete']);self.assertTrue(r['dpiScope']['restored'])

    def test_dpi_verification_failure_restores_saved_token(self):
        def mutate(b,p,e,w):
            original=b.user.AreDpiAwarenessContextsEqual.action
            b.user.AreDpiAwarenessContextsEqual.action=lambda a,c:0 if b.number(c)==ctypes.c_void_p(-4).value else original(a,c)
        with tempfile.TemporaryDirectory() as directory:
            b,_,_,r,error=self.run_capture(Path(directory),mutate)
            self.assertIsNotNone(error);self.assertEqual(b.context,123)
            self.assertTrue(r['dpiScope']['restored']);self.assertFalse(r['dpiScope']['verified'])

    def test_post_read_query_failure_is_not_masked_by_png_save_failure(self):
        def mutate(b,p,e,w):
            def capture():
                b.pids[22]=89
                return NS(save=lambda *args,**kwargs:(_ for _ in ()).throw(OSError('PNG save failed')))
            w.capture_as_image=capture
        with tempfile.TemporaryDirectory() as directory:
            _,_,_,r,error=self.run_capture(Path(directory),mutate)
            self.assertIn('geometry snapshot is incomplete',str(error))
            self.assertTrue(any('PNG save failed' in row['error'] for row in r['cleanupErrors']))
            self.assertTrue(r['dpiScope']['restored'])

    def test_wrong_pid_parent_ancestor_export_or_query_denied_fails_with_partial_receipt(self):
        for reason in ('pid','parent','root','export','denied'):
            def mutate(b,p,e,w):
                if reason=='pid':b.pids[22]=89
                elif reason=='parent':b.parents[22]=11
                elif reason=='root':b.user.GetAncestor.action=lambda *args:999
                elif reason=='export':b.user.GetPropW.action=lambda *args:999
                else:b.denied=12
            with self.subTest(reason=reason),tempfile.TemporaryDirectory() as directory:
                b,_,path,r,error=self.run_capture(Path(directory),mutate)
                self.assertIsNotNone(error);self.assertFalse(r['complete']);self.assertTrue(r['errors'])
                self.assertIn('before',r);self.assertFalse(r['before']['complete'])
                self.assertEqual(b.context,123);self.assertTrue(r['dpiScope']['restored']);self.assertFalse(path.exists())
    def test_capture_identity_race_fails_and_retains_original_png_and_after_snapshot(self):
        def mutate(b,p,e,w):
            original=w.capture_as_image
            def capture():
                image=original();b.pids[22]=89;return image
            w.capture_as_image=capture
        with tempfile.TemporaryDirectory() as directory:
            b,_,path,r,error=self.run_capture(Path(directory),mutate)
            self.assertIsNotNone(error);self.assertTrue(path.is_file());self.assertIn('after',r)
            self.assertFalse(r['complete']);self.assertEqual(b.calls.count(('capture',)),1)
    def test_primary_capture_and_cleanup_errors_are_both_preserved(self):
        def mutate(b,p,e,w):
            w.capture_as_image=lambda:(_ for _ in ()).throw(ValueError('original image failure'))
            original=b.user.SetThreadDpiAwarenessContext.action
            b.user.SetThreadDpiAwarenessContext.action=lambda context:0 if b.number(context)==123 else original(context)
        with tempfile.TemporaryDirectory() as directory:
            _,_,_,r,error=self.run_capture(Path(directory),mutate)
            self.assertIsInstance(error,ValueError);self.assertIn('original image failure',str(error))
            self.assertFalse(r['dpiScope']['restored']);self.assertTrue(r['cleanupErrors'])
            self.assertIn('original image failure',r['errors'][0]['error'])
    def test_cleanup_failure_alone_fails_capture(self):
        def mutate(b,p,e,w):
            original=b.user.SetThreadDpiAwarenessContext.action
            b.user.SetThreadDpiAwarenessContext.action=lambda context:0 if b.number(context)==123 else original(context)
        with tempfile.TemporaryDirectory() as directory:
            _,_,path,r,error=self.run_capture(Path(directory),mutate)
            self.assertIsNotNone(error);self.assertTrue(path.is_file());self.assertFalse(r['complete'])
    def test_create_new_fixed_paths_reject_existing_links_and_aliases(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);b,p,e,w,path=self.fixture(root)
            for bad in (root/'arbitrary.png',root/'..'/'escape.png'):
                with self.assertRaises(AssertionError):self.m.capture_with_geometry(w,e,bad,probe=p)
            sidecar=path.with_name(self.m.SIDECAR_NAME);sidecar.write_text('keep original')
            with self.assertRaises(FileExistsError):self.m.capture_with_geometry(w,e,path,probe=p)
            self.assertEqual(sidecar.read_text(),'keep original');self.assertEqual(b.calls,[])
            sidecar.unlink();path.write_bytes(b'keep PNG')
            with self.assertRaises(AssertionError):self.m.capture_with_geometry(w,e,path,probe=p)
            self.assertEqual(path.read_bytes(),b'keep PNG');path.unlink()
            original=root/'original.json';original.write_text('original');sidecar.hardlink_to(original)
            with self.assertRaises(FileExistsError):self.m.capture_with_geometry(w,e,path,probe=p)
            self.assertEqual(original.read_text(),'original');sidecar.unlink()
            outside=root/'outside';outside.mkdir();linked=root/'linked';linked.symlink_to(outside,target_is_directory=True)
            with self.assertRaises(AssertionError):self.m.capture_with_geometry(w,e,linked/path.name,probe=p)
    def test_json_bound_and_optional_wrapper_rectangle(self):
        with self.assertRaises(AssertionError):self.m.receipt_bytes({'large':'x'*65536})
        def mutate(b,p,e,w):del w.rectangle
        with tempfile.TemporaryDirectory() as directory:
            _,_,_,r,error=self.run_capture(Path(directory),mutate)
            # Native wrapper rectangle is optional; no second image is requested.
            self.assertIsNone(error);self.assertIsNone(r['nativeWrapperRectangle']);self.assertTrue(r['complete'])
    def test_parent_admission_rejects_binding_image_dpi_or_completeness_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            _,expected,path,r,error=self.run_capture(Path(directory))
            self.assertIsNone(error)
            self.m.require_geometry_sidecar(path,expected,r['png'])
            import copy
            for reason in ('binding','image','dpi','complete','window-count'):
                altered=copy.deepcopy(r)
                if reason=='binding':altered['expectedBinding']['officeCreationTime']+=1
                elif reason=='image':altered['png']['sha256']='0'*64
                elif reason=='dpi':altered['dpiScope']['restored']=False
                elif reason=='complete':altered['after']['complete']=False
                else:altered['before']['windows'].append(altered['before']['windows'][0])
                path.with_name(self.m.SIDECAR_NAME).write_bytes(self.m.receipt_bytes(altered))
                with self.subTest(reason=reason),self.assertRaises(AssertionError):
                    self.m.require_geometry_sidecar(path,expected,r['png'])

    def assert_nested_rejected(self,path,expected,receipt,mutate):
        import copy
        altered=copy.deepcopy(receipt);mutate(altered)
        path.with_name(self.m.SIDECAR_NAME).write_bytes(self.m.receipt_bytes(altered))
        with self.assertRaises(AssertionError):self.m.require_geometry_sidecar(path,expected,receipt['png'])

    def test_parent_admission_requires_every_fixed_native_query_fact(self):
        with tempfile.TemporaryDirectory() as directory:
            _,expected,path,r,error=self.run_capture(Path(directory));self.assertIsNone(error)
            for edge in ('before','after'):
                snapshot=r[edge]
                paths=[(edge,'attachment'),(edge,'physicalCursor')]
                paths += [(edge,'attachment',key) for key in snapshot['attachment']]
                for node in [('windows',index) for index in range(3)]+[('taskbar',)]:
                    row=snapshot
                    for key in node:row=row[key]
                    prefix=(edge,*node)
                    paths += [(*prefix,key) for key in row if key not in ('complete','hwnd')]
                    for field in ('identityAfter','monitor','placement','appBarPosition','appBarState'):
                        if field in row:paths += [(*prefix,field,key) for key in row[field]]
                for keys in paths:
                    def remove(value):
                        for key in keys[:-1]:value=value[key]
                        del value[keys[-1]]
                    with self.subTest(missing=keys):self.assert_nested_rejected(path,expected,r,remove)

    def test_parent_admission_rejects_complete_only_native_skeletons(self):
        def skeleton(value):
            for edge in ('before','after'):
                value[edge]=dict(complete=True,errors=[],taskbar=dict(complete=True),
                    windows=[dict(hwnd=hwnd,complete=True) for hwnd in (11,12,22)])
        with tempfile.TemporaryDirectory() as directory:
            _,expected,path,r,error=self.run_capture(Path(directory));self.assertIsNone(error)
            self.assert_nested_rejected(path,expected,r,skeleton)

    def test_parent_admission_rejects_wrong_native_identity_types_shapes_and_states(self):
        cases=[(('windows',2,'pid'),89), (('windows',1,'parentHwnd'),0),
            (('windows',2,'rootHwnd'),22), (('windows',0,'role'),'child'),
            (('windows',0,'identityAfter','tid'),999), (('windows',0,'tid'),0),
            (('windows',0,'dpi'),0), (('windows',0,'dpi'),True),
            (('windows',0,'visible'),1), (('windows',0,'windowRect'),[0,0,1]),
            (('windows',0,'clientRect'),[0,0,1,2**31]),
            (('windows',0,'clientScreenRect'),[False,0,1,1]),
            (('windows',0,'monitor','handle'),0), (('windows',0,'monitor','flags'),True),
            (('windows',0,'monitor','rect'),[0,0,1024,2**32]),
            (('windows',0,'monitor','workRect'),[0,0,1024.0,768]),
            (('windows',0,'placement','showCmd'),False),
            (('windows',0,'placement','minPosition'),[0]),
            (('windows',0,'placement','normalRect'),[0,0,0,'0']),
            (('attachment','parentHwnd'),99), (('attachment','hostContainsChild'),1),
            (('physicalCursor',),[0,True]), (('physicalCursor',),[0,0,0]),
            (('taskbar','className'),'Other'), (('taskbar','pid'),0),
            (('taskbar','appBarPosition','hwnd'),11), (('taskbar','appBarPosition','edge'),4),
            (('taskbar','appBarPosition','rect'),[0,720,1024]),
            (('taskbar','appBarState','autoHide'),False),
            (('taskbar','appBarState','alwaysOnTop'),1)]
        with tempfile.TemporaryDirectory() as directory:
            _,expected,path,r,error=self.run_capture(Path(directory));self.assertIsNone(error)
            for keys,bad in cases:
                def mutate(value):
                    value=value['before']
                    for key in keys[:-1]:value=value[key]
                    value[keys[-1]]=bad
                with self.subTest(field=keys,bad=bad):self.assert_nested_rejected(path,expected,r,mutate)
            def bool_tid(value):
                for edge in ('before','after'):
                    value[edge]['windows'][0]['tid']=True
                    value[edge]['windows'][0]['identityAfter']['tid']=True
            self.assert_nested_rejected(path,expected,r,bool_tid)
            def bool_state(value):
                value['before']['taskbar']['appBarState']=dict(raw=True,autoHide=True,alwaysOnTop=False)
            self.assert_nested_rejected(path,expected,r,bool_state)

    def test_parent_admission_recomputes_target_and_taskbar_identity_cross_edges(self):
        cases=[(('windows',0,'windowRect'),[-11,-10,1050,800]),
            (('windows',1,'clientRect'),[0,0,1040,691]),
            (('windows',2,'clientScreenRect'),[0,61,1040,751]),
            (('windows',0,'dpi'),144), (('windows',0,'visible'),False),
            (('windows',0,'monitor','workRect'),[0,0,1024,700]),
            (('windows',0,'placement','showCmd'),3)]
        with tempfile.TemporaryDirectory() as directory:
            _,expected,path,r,error=self.run_capture(Path(directory));self.assertIsNone(error)
            for keys,bad in cases:
                def mutate(value):
                    value=value['after']
                    for key in keys[:-1]:value=value[key]
                    value[keys[-1]]=bad
                with self.subTest(changed=keys):self.assert_nested_rejected(path,expected,r,mutate)
            for node in (('windows',0),('taskbar',)):
                def changed_tid(value):
                    row=value['after']
                    for key in node:row=row[key]
                    row['tid']+=1;row['identityAfter']['tid']+=1
                with self.subTest(identity=node):self.assert_nested_rejected(path,expected,r,changed_tid)

    def test_parent_admission_allows_changing_cursor_and_taskbar_observations(self):
        with tempfile.TemporaryDirectory() as directory:
            _,expected,path,r,error=self.run_capture(Path(directory));self.assertIsNone(error)
            r['after']['physicalCursor']=[-10,100]
            taskbar=r['after']['taskbar'];taskbar['visible']=False
            taskbar['windowRect']=[0,766,1024,768]
            taskbar['clientRect']=[0,0,1024,2];taskbar['clientScreenRect']=[0,766,1024,768]
            taskbar['appBarPosition']['rect']=[0,766,1024,768]
            taskbar['appBarState']=dict(raw=0,autoHide=False,alwaysOnTop=False)
            taskbar['monitor']['workRect']=[0,0,1024,720]
            path.with_name(self.m.SIDECAR_NAME).write_bytes(self.m.receipt_bytes(r))
            self.assertIs(self.m.require_geometry_sidecar(path,expected,r['png'])['complete'],True)

    def test_intra_snapshot_tid_race_is_not_valid_geometry(self):
        def mutate(b,p,e,w):
            calls=[];original=b.user.GetWindowThreadProcessId.action
            def identity(hwnd,pid):
                value=original(hwnd,pid);calls.append(hwnd)
                return value+1 if hwnd==22 and calls.count(22)>1 else value
            b.user.GetWindowThreadProcessId.action=identity
        with tempfile.TemporaryDirectory() as directory:
            _,_,_,r,error=self.run_capture(Path(directory),mutate)
            self.assertIsNotNone(error);self.assertFalse(r['before']['complete'])


if __name__=='__main__':unittest.main()
