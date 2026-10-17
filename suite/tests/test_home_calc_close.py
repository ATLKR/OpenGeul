"""Separate Home-only Calc cleanup authorization, never an arbitrary-file fallback."""
import copy
import importlib.util
from pathlib import Path
import unittest
import sys
import tempfile
from unittest.mock import patch
from types import SimpleNamespace
import hashlib

sys.path.insert(0,str(Path(__file__).resolve().parent))

SOURCE=Path(__file__).resolve().parents[1]/'e2e/home_calc_close.py'


class HomeCalcCloseContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert SOURCE.is_file(),'Separate physical-Home Calc cleanup provenance is required'
        spec=importlib.util.spec_from_file_location('home_calc_close_contract',SOURCE)
        cls.api=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.api)

    def test_format_cells_require_exact_unmodified_source_marker_and_csv_loss_contract(self):
        for extension in ('ods','xlsx','xls','csv'):
            value=dict(sheetIndex=0,a1Text='Engine-OpenGeul-calc 한글',b1Value=17,c1Value=25,d1Value=42,
                d1Formula='42' if extension=='csv' else '=SUM(B1:C1)',isModified=False)
            self.api.require_home_calc_cells(value,extension)
            for field,bad in [('sheetIndex',1),('a1Text','Feature-OpenGeul-calc 한글'),('b1Value',30),('c1Value',26),('d1Value',55),('d1Formula','=SUM(InputValues)'),('isModified',True)]:
                changed=dict(value,**{field:bad})
                with self.subTest(extension=extension,field=field),self.assertRaises(AssertionError):self.api.require_home_calc_cells(changed,extension)

    def test_blank_home_calc_requires_empty_a1_and_all_zero_cells(self):
        value=dict(sheetIndex=0,a1Text='',b1Value=0,c1Value=0,d1Formula='',d1Value=0,isModified=False)
        self.api.require_home_calc_cells(value,None)
        for field,bad in [('a1Text','user data'),('d1Formula','=1'),('b1Value',1),('isModified',0),('isModified',True)]:
            with self.subTest(field=field),self.assertRaises(AssertionError):self.api.require_home_calc_cells(dict(value,**{field:bad}),None)

    def test_readonly_context_keeps_actual_original_frame_reader_and_release_identity(self):
        import test_calc_model_barrier as calc
        import test_writer_model_barrier as writer
        import test_writer_model_reader as fixtures
        with tempfile.TemporaryDirectory() as directory:
            frame=calc.synthetic_frame(Path(directory)/'Suite','unused');url='file:///C:/owned/format-calc-csv.csv';frame.binding['documentUrl']=url
            observation=calc.observation(frame,'Engine-OpenGeul-calc 한글',0,.1)
            observation['d1Formula']='42'
            cleanup=fixtures.cleanup_fixture(frame.binding,str(frame.suite));cleanup['kind']='owned-calc-reader-cleanup'
            cleanup.update(startedAt=1.,finishedAt=1.1,deadline=12.);writer.retime_native_cleanup_fixture(cleanup)
            context=dict(startedAt=0.,deadline=12.,finishedAt=1.1,observation=observation,cleanup=cleanup,
                originalShell=writer.original_shell_fixture(frame.binding,frame.suite),inventory=frame.inventory,inventorySha256=frame.inventory_sha256)
            self.api.require_calc_reader_context(context,frame.suite,url,'csv')
            for reason in ('url','reader','helper-handle','profile','deadline','a1','contract'):
                value=copy.deepcopy(context)
                if reason=='url':value['observation']['bindingBefore']['documentUrl']='file:///C:/foreign.csv'
                elif reason=='reader':value['cleanup']['releaseAcknowledgement']['readerPid']=98
                elif reason=='helper-handle':value['cleanup']['releaseAcknowledgement']['observerHandleClosures'][0]['handleValue']+=1
                elif reason=='profile':value['cleanup']['nativeAfter']['profileDirectory']['witness']['handleValue']+=1
                elif reason=='deadline':value['finishedAt']=12.1
                elif reason=='a1':value['observation']['a1Text']='foreign'
                else:value['observation']['operations'].append('setString')
                with self.subTest(reason=reason),self.assertRaises(AssertionError):self.api.require_calc_reader_context(value,frame.suite,url,'csv')

    def test_actual_calc_observer_uses_one_read_and_same_budget_cleanup_even_after_failure(self):
        import test_calc_model_barrier as calc
        import test_writer_model_barrier as writer
        import test_writer_model_reader as fixtures
        import writer_model_reader
        import lifecycle_smoke
        for fails in (False,True):
            with self.subTest(fails=fails),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);frame=calc.synthetic_frame(root/'Suite','unused');source=root/'format-calc-csv.csv';source.write_bytes(b'owned')
                frame.binding['documentUrl']=source.as_uri();observed=calc.observation(frame,'Engine-OpenGeul-calc 한글',0,.1);observed['d1Formula']='42'
                cleanup=fixtures.cleanup_fixture(frame.binding,str(frame.suite));cleanup['kind']='owned-calc-reader-cleanup';cleanup.update(startedAt=1.,finishedAt=1.1,deadline=12.);writer.retime_native_cleanup_fixture(cleanup)
                clock=[0.];calls=[];shell=writer.original_shell_fixture(frame.binding,frame.suite)
                class Reader:
                    def __init__(self,*args,**kwargs):calls.append(('constructor',kwargs))
                    def start(self,deadline):
                        calls.append(('start',deadline));clock[0]=.1
                        if fails:raise OSError('original getter failure')
                        return copy.deepcopy(observed)
                    def close(self,deadline):calls.append(('close',deadline));clock[0]=1.1;return copy.deepcopy(cleanup)
                def retained(process,suite,raw):raw.update(copy.deepcopy(shell));return frame.binding['shellCreationTime']
                record={};attachment=dict(hwnd=frame.binding['suiteHwnd'],parent=frame.binding['parentHwnd'],child=frame.binding['childHwnd'],officePid=frame.binding['officePid'])
                with patch.object(writer_model_reader,'OwnedModelReader',Reader),patch.object(lifecycle_smoke,'retained_writer_shell',retained),patch.object(self.api.time,'monotonic',lambda:clock[0]):
                    if fails:
                        with self.assertRaisesRegex(OSError,'original getter failure'):self.api.observe_home_calc(frame.suite,root/'reader',SimpleNamespace(pid=77),attachment,source,'csv',record)
                    else:self.api.observe_home_calc(frame.suite,root/'reader',SimpleNamespace(pid=77),attachment,source,'csv',record)
                self.assertEqual([row for row in calls if row[0] in ('start','close')],[('start',12.),('close',12.)])
                kwargs=calls[0][1];self.assertEqual(kwargs['expected_url'],source.as_uri())
                self.assertEqual(kwargs['getter_contract'],'calc-a1-b1-c1-d1-v1')
                self.assertEqual(record['calcReader']['cleanup'],cleanup)

    def test_home_blank_token_cannot_authorize_cli_launch_changed_origin_or_recycled_engine(self):
        import test_calc_model_barrier as calc
        import test_writer_model_barrier as writer
        import test_writer_model_reader as fixtures
        import lifecycle_smoke
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);frame=calc.synthetic_frame(root/'Suite','unused');frame.binding['documentUrl']=''
            observation=calc.observation(frame,'',0,.1);observation.update(b1Value=0,c1Value=0,d1Formula='',d1Value=0)
            cleanup=fixtures.cleanup_fixture(frame.binding,str(frame.suite));cleanup['kind']='owned-calc-reader-cleanup'
            context=dict(success=True,startedAt=0.,deadline=12.,finishedAt=1.1,observation=observation,cleanup=cleanup,originalShell=writer.original_shell_fixture(frame.binding,frame.suite),inventory=frame.inventory,inventorySha256=frame.inventory_sha256)
            process=SimpleNamespace(pid=77,args=[str(frame.suite/'OpenGeul.Office.exe')],_handle=555,poll=lambda:None)
            bound=SimpleNamespace(pid=88,creation=222,handle=888,kernel=None,live=lambda:True)
            action=dict(homeHwnd=100,shellPid=77,home=dict(hwnd=100,pid=77,isWindow=True,rootHwnd=100,threadId=9,className='Home'),foreground=dict(hwnd=100,pid=77,isWindow=True,rootHwnd=100),
                candidates=[dict(name='OpenGeul Calc',pid=77,runtimeId=[42,100,1],nativeHwnd=101,nativeRoot=100,nativeLive=True,enabled=True,visible=True)],clicks=1,success=True,rawElementEquals=True)
            record=dict(case='tile-calc',kind='tile',module='calc',shellPid=77,homeHwnd=100,homeOnlyBeforeAction=[100],homeActions=[action],
                windowHwnd=11,parentHwnd=12,childHwnd=22,officePid=88,keyboardInputVerified=False,calcReader=context)
            api=SimpleNamespace(pid=lambda hwnd:77 if hwnd==11 else 88,user=SimpleNamespace(IsWindow=lambda hwnd:True,IsChild=lambda parent,child:parent==11 and child==22))
            def identity(kernel,handle):return ((frame.suite/('OpenGeul.Office.exe' if handle==555 else 'Office/program/soffice.bin')).resolve(),111 if handle==555 else bound.creation)
            with patch.object(lifecycle_smoke,'process_identity',identity):
                proof=self.api.freeze_home_calc_close(frame.suite,process,bound,record)
                self.api.verify_home_calc_close(api,proof,record)
                for reason in ('cli','origin','generation','frame'):
                    changed=copy.deepcopy(record)
                    if reason=='cli':process.args.append('--module')
                    elif reason=='origin':changed['homeActions'][0]['candidates'][0]['name']='foreign'
                    elif reason=='generation':bound.creation=223
                    else:changed['childHwnd']=99
                    with self.subTest(reason=reason),self.assertRaises(AssertionError):self.api.verify_home_calc_close(api,proof,changed)
                    process.args=[str(frame.suite/'OpenGeul.Office.exe')];bound.creation=222

    def test_generated_format_copy_must_join_fixed_case_saved_hash_original_and_report(self):
        import home_routing_smoke
        for extension in ('ods','xlsx','xls','csv'):
            with self.subTest(extension=extension),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);suite=root/'Suite';suite.mkdir();owned=root/'owned';owned.mkdir()
                feature=root/'features';originals=feature/'fixtures';originals.mkdir(parents=True)
                name=f'format-calc-{extension}.{extension}';data=('owned-'+extension).encode();original=originals/name;original.write_bytes(data)
                source=owned/name;source.write_bytes(data);report=feature/'office-features.json';report.write_bytes(b'source-bound passed21 report')
                descriptor=dict(case='format-calc-'+extension,module='calc',extension=extension,source=str(original),featuresRoot=str(feature),
                    sha256=hashlib.sha256(data).hexdigest(),bytes=len(data),featureReportSha256=hashlib.sha256(report.read_bytes()).hexdigest())
                with patch.object(home_routing_smoke,'load_feature_inputs',return_value={('calc',extension):copy.deepcopy(descriptor)}):
                    self.api.require_calc_source(suite,owned,source,descriptor)
                    alias=root/'alias';alias.symlink_to(owned,target_is_directory=True)
                    with self.assertRaises(AssertionError):self.api.require_calc_source(suite,alias,alias/name,descriptor)
                    for reason in ('bytes','case','name','report','original'):
                        changed=copy.deepcopy(descriptor);target=source
                        if reason=='bytes':source.write_bytes(b'changed')
                        elif reason=='case':changed['case']='rich-calc'
                        elif reason=='name':target=owned/('user.'+extension);target.write_bytes(data)
                        elif reason=='report':report.write_bytes(b'changed report')
                        else:original.write_bytes(b'changed original')
                        with self.subTest(reason=reason),self.assertRaises(AssertionError):self.api.require_calc_source(suite,owned,target,changed)
                        source.write_bytes(data);original.write_bytes(data);report.write_bytes(b'source-bound passed21 report')

    def test_one_close_accepts_clean_exit_or_exact_owned_prompt_without_reposting(self):
        import test_generated_calc_close as existing
        import generated_calc_close
        import lifecycle_smoke
        import windows_smoke
        for mode in ('clean','prompt','foreign','late'):
            with self.subTest(mode=mode):
                fixture=existing.GeneratedCalcCloseTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
                Desktop,accessible,buttons=fixture.boundary();clock=[0.]
                if mode=='clean':fixture.windows.request_close=lambda hwnd,pid:(fixture.closes.append((hwnd,pid)),fixture.live.clear())
                if mode=='foreign':fixture.owner=lambda hwnd,kind:999
                proof=SimpleNamespace(process=fixture.process,hwnd=10,child=20,source=None)
                def prompt(*args):
                    if mode=='late':clock[0]=21.
                    return buttons
                with patch.dict(sys.modules,{'pywinauto':SimpleNamespace(Desktop=Desktop)}),patch.object(self.api,'verify_home_calc_close'),patch.object(self.api.time,'monotonic',lambda:clock[0]), \
                    patch.object(generated_calc_close,'require_calc_prompt_buttons',side_effect=prompt),patch.object(lifecycle_smoke,'require_dialog_button_ancestry',return_value=[{'controlType':'Button'},{'controlType':'Window'}]), \
                    patch.object(windows_smoke,'wait_for',side_effect=lambda check,seconds=60:check() or (_ for _ in ()).throw(AssertionError('not ready'))):
                    if mode in ('clean','prompt'):self.api.close_home_calc(fixture.windows,proof,fixture.record)
                    else:
                        with self.assertRaises(AssertionError):self.api.close_home_calc(fixture.windows,proof,fixture.record)
                self.assertEqual(fixture.closes,[(10,7)])
                self.assertEqual(fixture.clicks,['discard'] if mode=='prompt' else [])


if __name__=='__main__':unittest.main()
