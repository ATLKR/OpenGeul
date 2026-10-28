"""Synthetic original-case to producer shutdown joins; no Windows claim."""
import copy
from types import SimpleNamespace
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
import shutil
import tempfile
import unittest

SOURCE=Path(__file__).resolve().parents[1]/'e2e/native_archive_completeness.py'
sys.path.insert(0,str(SOURCE.parent))

from test_native_cleanup_receipt import receipt
import windows_smoke
import startup_smoke
import korean_ui_smoke
import lifecycle_smoke
import writer_style_smoke
import calc_save_smoke
import calc_close_probe

SHARED='.work/suite-worker-diagnostics'
CALC_SAVE='.work/suite-calc-save/diagnostics'


class NativeArchiveCompletenessTests(unittest.TestCase):
    def setUp(self):
        self.directory=self.enterContext(tempfile.TemporaryDirectory())
        self.root=Path(self.directory).resolve()
        self.suite=self.root/'relocated Suite 한글';self.suite.mkdir()
        self.image=str(self.suite/'Office/program/soffice.bin')
        self.next_pid=100;self.expected=[];self.reports={}
        gui=('home',)+windows_smoke.NEW_MODULES+tuple('new-'+m for m in windows_smoke.NEW_MODULES)
        for scope in ('suite-native','suite-native-2'):
            self.report(scope,gui,lambda name:0 if name=='home' else 1,'gui')
        self.report('suite-startup',[r['case'] for r in startup_smoke.build_plan(40)],lambda name:1,'top',field='attempts')
        self.report('suite-korean-ime',['ime-'+m for m,_ in windows_smoke.INPUT_CASES],lambda name:1,'ime')
        self.report('suite-korean-ui',['korean-ui-'+m for m in korean_ui_smoke.MODULES],lambda name:1,'top')
        self.report('suite-writer-style',[writer_style_smoke.CASE],lambda name:1,'top')
        counts={name:2 if name=='home-two-documents-cancel' else 0 if name=='hwp-tile-hwpx-route' else 1
                for name in lifecycle_smoke.CASE_REQUIREMENTS}
        self.report('suite-lifecycle',list(counts),counts.__getitem__,'lifecycle')
        self.report('suite-calc-save',[calc_save_smoke.CASE],lambda name:1,'calc',archive_root=lambda name:CALC_SAVE)
        self.report('suite-calc-close',['calc-close-'+c for c in calc_close_probe.CHOICES],lambda name:1,'calc',
            archive_root=lambda name:'.work/suite-calc-close/'+name+'/diagnostics')
        for report, data in self.reports.items():self.write_json(self.root/report,data)
        for index,entry in enumerate(self.expected):self.archive(entry,index)

    def row(self,name,count,kind,archive_root):
        self.next_pid+=10;shell=self.next_pid
        result=dict(case=name,success=True,shellPid=shell)
        frames=[]
        for slot in range(count):
            pid=shell+slot+1;created=100000+pid
            generation=dict(pid=pid,creationTime=created,image=self.image)
            frame=dict(hwnd=pid+1000,parent=pid+2000,child=pid+3000,officePid=pid,nativeArchiveGeneration=generation)
            frames.append(frame)
            self.expected.append(dict(root=archive_root,case=name,shellPid=shell,generation=generation))
        if count:
            result['windowActivations']=[dict(suiteHwnd=frame['hwnd'],originalProcess=self.activation_snapshot(shell)) for frame in frames]
            generation=frames[0]['nativeArchiveGeneration']
            if kind=='lifecycle':result['attachments']=frames
            else:
                result.update(officePid=generation['pid'],windowHwnd=frames[0]['hwnd'],parentHwnd=frames[0]['parent'],childHwnd=frames[0]['child'])
                if kind=='gui':result['nativeArchiveGeneration']=generation
                elif kind=='top':result['officeCreationTime']=generation['creationTime']
                else:
                    binding=dict(shellPid=shell,officePid=generation['pid'],officeCreationTime=generation['creationTime'],expectedImage=self.image)
                    if kind=='ime':result['imeKeyboardSession']=dict(expectedNative=binding)
                    else:result['beforeInput']=dict(bindingBefore=binding)
        return result

    def activation_snapshot(self,shell):
        from suite_window_activation import NativeActivationProbe
        def times(handle,created,*rest):
            created._obj.low=50000+shell;created._obj.high=0
            return 1
        def image(handle,flags,buffer,size):
            buffer.value=str(self.suite/'OpenGeul.Office.exe');size._obj.value=len(buffer.value)
            return 1
        probe=NativeActivationProbe.__new__(NativeActivationProbe)
        probe._call=lambda function,*args:function(*args)
        probe.kernel=SimpleNamespace(GetProcessId=lambda handle:shell,WaitForSingleObject=lambda *args:258,
            GetProcessTimes=times,QueryFullProcessImageNameW=image)
        return probe.process_snapshot(SimpleNamespace(_handle=shell+90000))

    def report(self,scope,names,count,kind,field='tests',archive_root=lambda name:SHARED):
        path='.work/'+scope+'/results.json'
        self.reports[path]=dict(success=True,**{field:[self.row(name,count(name),kind,archive_root(name)) for name in names]})

    def write_json(self,path,data):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(data),encoding='utf-8')

    def archive(self,entry,index):
        from suite.worker.native_diagnostics import NativeDiagnostics
        root=self.root/entry['root'];root.mkdir(parents=True,exist_ok=True)
        profile=self.root/'profiles'/str(index);profile.mkdir(parents=True,exist_ok=True)
        proof=receipt();proof['launcherPid']=entry['shellPid']+100000;proof['expectedEngineImage']=self.image
        proof['launcherHandleValue']=proof['initialMembers'][0]['handleValue']
        for rows in (proof['initialMembers'],proof['finalMembers']):
            rows[0].update(pid=proof['launcherPid'],image=str(self.suite/'Office/program/soffice.exe'))
            rows[1].update(**entry['generation'])
        phase={'members':proof['initialMembers']}
        witnesses=SimpleNamespace(snapshot=lambda:copy.deepcopy(phase['members']),close=lambda:None)
        process=SimpleNamespace(pid=proof['launcherPid'],open_diagnostic_witnesses=lambda:witnesses)
        diagnostics=NativeDiagnostics(root,profile,process)
        diagnostics.record('before-owned-shutdown')
        phase['members']=proof['finalMembers']
        diagnostics.record('after-owned-shutdown')
        diagnostics.archive_crash()
        diagnostics.record_shutdown(proof)
        diagnostics.close()
        folder=diagnostics.directory
        entry.update(folder=folder,diagnostics=diagnostics,shutdownProof=proof)
        return folder

    def implementation(self):
        self.assertTrue(SOURCE.is_file(),'Original-case native archive completeness validator is required')
        spec=importlib.util.spec_from_file_location('native_archive_completeness_under_test',SOURCE)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        return module

    def verify(self):return self.implementation().verify_native_archive_completeness(self.root,self.suite)

    def test_every_source_fixed_case_and_original_generation_has_one_archive(self):
        result=self.verify()
        self.assertIs(result['success'],True)
        self.assertEqual(result['expectedGenerations'],len(self.expected))
        self.assertEqual(result['matchedGenerations'],83)
        self.assertEqual(len(result['archives']),83)
        serialized=json.dumps(result)
        for forbidden in ('bodyText','sourceBytesHex','asciiPrefix','keyTokens','traceback'):
            self.assertNotIn(forbidden,serialized)

    def test_entirely_missing_archive_cannot_hide_among_successful_siblings(self):
        self.expected[4]['folder'].rename(self.root/'omitted-owned-archive')
        with self.assertRaisesRegex((ValueError,AssertionError),'[Mm]issing|[Cc]overage|[Bb]ijection'):
            self.verify()

    def test_duplicate_and_orphan_archives_cannot_qualify(self):
        original=self.expected[0]['folder']
        duplicate=original.parent/('f'*32)
        shutil.copytree(original,duplicate)
        with self.assertRaises((ValueError,AssertionError)):self.verify()
        shutil.rmtree(duplicate)
        entry=copy.deepcopy(self.expected[0]);entry['generation']['pid']+=9000
        self.archive(entry,999)
        with self.assertRaises((ValueError,AssertionError)):self.verify()

    def test_missing_duplicate_unexpected_failed_or_reordered_original_cases_reject(self):
        path=self.root/'.work/suite-startup/results.json'
        original=json.loads(path.read_text())
        for change in ('missing','duplicate','unexpected','failed','order','report-missing'):
            current=copy.deepcopy(original)
            if change=='missing':current['attempts'].pop()
            elif change=='duplicate':current['attempts'].append(copy.deepcopy(current['attempts'][0]))
            elif change=='unexpected':current['attempts'][0]['case']='unplanned'
            elif change=='failed':current['attempts'][0]['success']=False
            elif change=='order':current['attempts'].reverse()
            elif change=='report-missing':path.unlink()
            if change!='report-missing':self.write_json(path,current)
            with self.subTest(change=change),self.assertRaises((ValueError,AssertionError,OSError)):self.verify()
            self.write_json(path,original)

    def test_generation_case_shell_image_and_attachment_count_are_independent_joins(self):
        path=self.root/'.work/suite-lifecycle/results.json';original=json.loads(path.read_text())
        for change in ('missing-attachment','extra-attachment','creation','pid','image','shell','bool','unbound'):
            data=copy.deepcopy(original);row=data['tests'][0];frame=row['attachments'][0]
            if change=='missing-attachment':row['attachments'].clear()
            elif change=='extra-attachment':row['attachments'].append(copy.deepcopy(frame))
            elif change=='creation':frame['nativeArchiveGeneration']['creationTime']+=1
            elif change=='pid':frame['nativeArchiveGeneration']['pid']+=1
            elif change=='image':frame['nativeArchiveGeneration']['image']='C:/foreign/soffice.bin'
            elif change=='shell':row['shellPid']+=1
            elif change=='bool':frame['nativeArchiveGeneration']['creationTime']=True
            elif change=='unbound':frame.pop('nativeArchiveGeneration')
            self.write_json(path,data)
            with self.subTest(change=change),self.assertRaises((ValueError,AssertionError)):self.verify()
        self.write_json(path,original)

    def test_original_shortcut_receipts_reuse_generation_and_deduplicate_repeated_edits(self):
        path=self.root/'.work/suite-native/results.json';data=json.loads(path.read_text())
        row=data['tests'][1];generation=row.pop('nativeArchiveGeneration')
        attachment=dict(hwnd=row['windowHwnd'],parent=row['parentHwnd'],child=row['childHwnd'],officePid=row['officePid'])
        row['editorShortcutSessions']=[dict(attachment=attachment,originalEngine=dict(generation,handleValue=77),
            originalShell=dict(pid=row['shellPid'])) for _ in range(2)]
        self.write_json(path,data)
        self.assertIs(self.verify()['success'],True)
        row['editorShortcutSessions'][1]['originalEngine']['creationTime']+=1
        self.write_json(path,data)
        with self.assertRaises((ValueError,AssertionError)):self.verify()

    def test_event_stream_must_exist_and_be_manifest_hashed(self):
        folder=self.expected[0]['folder'];events=folder/'events.jsonl'
        if events.exists():events.unlink()
        with self.assertRaises((ValueError,AssertionError,OSError)):self.verify()

    def test_unlisted_event_stream_cannot_use_the_previous_journal_exemption(self):
        folder=self.expected[0]['folder'];events=folder/'events.jsonl'
        events.write_bytes(b'{"phase":"before-owned-shutdown"}\n')
        manifest=json.loads((folder/'manifest.json').read_text())
        manifest['files']=[row for row in manifest['files'] if row['path']!='events.jsonl']
        self.write_json(folder/'manifest.json',manifest)
        with self.assertRaises((ValueError,AssertionError)):self.verify()

    def test_event_stream_hardlinked_after_seal_cannot_qualify(self):
        events=self.expected[0]['folder']/'events.jsonl'
        os.link(events,self.root/'hardlinked-event-stream')
        with self.assertRaises((ValueError,AssertionError)):self.verify()

    def test_mutated_or_truncated_sealed_event_bytes_cannot_qualify(self):
        events=self.expected[0]['folder']/'events.jsonl';original=events.read_bytes()
        for raw in (b'x'+original[1:],original[:len(original)//2],b''):
            events.write_bytes(raw)
            with self.subTest(bytes=len(raw)),self.assertRaises((ValueError,AssertionError,OSError)):self.verify()
        events.write_bytes(original)
        manifest=(self.expected[0]['folder']/'manifest.json').relative_to(self.root).as_posix()
        proof=next(row for row in self.verify()['archives'] if row['manifest']==manifest)
        self.assertEqual(proof['eventsSha256'],hashlib.sha256(original).hexdigest())
        self.assertEqual(proof['eventsBytes'],len(original))

    def test_real_producer_invalidates_retry_append_and_reseals_without_dropping_phases(self):
        entry=self.expected[0];diagnostics=entry['diagnostics'];events=entry['folder']/'events.jsonl'
        original=events.read_bytes()
        diagnostics.record('before-owned-shutdown')
        appended=events.read_bytes()
        self.assertTrue(appended.startswith(original))
        self.assertGreater(len(appended),len(original))
        with self.assertRaises((ValueError,AssertionError)):self.verify()
        diagnostics.record_shutdown(entry['shutdownProof'])
        self.assertIs(self.verify()['success'],True)
        self.assertEqual(events.read_bytes(),appended)
        manifest=json.loads((entry['folder']/'manifest.json').read_text())
        seal=next(row for row in manifest['files'] if row['path']=='events.jsonl')
        self.assertEqual(seal,dict(path='events.jsonl',bytes=len(appended),sha256=hashlib.sha256(appended).hexdigest()))

    def test_original_zero_exit_and_manifest_hash_proofs_remain_mandatory(self):
        folder=self.expected[0]['folder'];shutdown=folder/'shutdown.json'
        original=shutdown.read_bytes()
        shutdown.write_bytes(original+b' ')
        with self.assertRaises((ValueError,AssertionError)):self.verify()
        shutdown.write_bytes(original)
        data=json.loads(original);data['forcedTermination']=True
        raw=json.dumps(data).encode();shutdown.write_bytes(raw)
        manifest=json.loads((folder/'manifest.json').read_text());next(row for row in manifest['files'] if row['path']=='shutdown.json').update(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
        self.write_json(folder/'manifest.json',manifest)
        with self.assertRaises((ValueError,AssertionError)):self.verify()

    def workflow_process(self):
        from test_calc_matrix_workflow import workflow_steps,field,run_code
        checkout=SOURCE.parents[2]
        for source in (checkout/'suite').rglob('*.py'):
            if '__pycache__' not in source.parts:
                target=self.root/source.relative_to(checkout)
                target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
        with tempfile.TemporaryDirectory() as runner:
            script=Path(runner)/'workflow.py'
            step=next(step for step in workflow_steps() if field(step,'shell')=='python')
            script.write_text(run_code(step),encoding='utf-8')
            environment=dict(os.environ,GITHUB_SHA='a'*40,GITHUB_RUN_ID='123',GITHUB_RUN_ATTEMPT='1',
                SUITE_PACKAGE=str(self.suite),OPENGEUL_SUITE_NUMERIC_NOTICE='1',OPENGEUL_SUITE_NOTICE_SCOPE='10',PYTHONDONTWRITEBYTECODE='1')
            from test_numeric_notice import environment as notice_environment
            environment.update(notice_environment(),OPENGEUL_SUITE_NOTICE_SCOPE='10',GH_TOKEN='synthetic-not-a-credential',GITHUB_TOKEN='synthetic-not-a-credential')
            environment.pop('PYTHONPATH',None)
            return subprocess.run([sys.executable,str(script)],cwd=self.root,env=environment,
                capture_output=True,text=True,encoding='utf-8',timeout=30)

    def test_actual_workflow_blocks_missing_original_archive_and_retains_numeric_failure(self):
        self.expected[4]['folder'].rename(self.root/'omitted-owned-archive')
        process=self.workflow_process()
        self.assertNotEqual(process.returncode,0,'Missing original archive passed the actual workflow')
        result=json.loads((self.root/'.work/suite-native-integrity.json').read_text())
        self.assertIs(result['success'],False)
        self.assertIs(result['generationCompleteness']['success'],False)
        self.assertIn('numericFailure',result)
        import numeric_notice
        prefix='::notice title='+numeric_notice.CASE_TITLE+'::'
        lines=[line[len(prefix):] for line in process.stdout.splitlines() if line.startswith(prefix)]
        self.assertEqual(len(lines),1)
        notice=numeric_notice.decode_notice(lines[0],'a'*40,123,expected_scope=10)
        self.assertEqual(notice['fileCode'],23)
        self.assertGreaterEqual(notice['line'],self.implementation().verify_native_archive_completeness.__code__.co_firstlineno)

    def test_linked_or_oversized_original_reports_are_rejected(self):
        path=self.root/'.work/suite-native/results.json';original=path.read_bytes()
        target=self.root/'original-report.json';path.rename(target);path.symlink_to(target)
        with self.assertRaises((ValueError,AssertionError,OSError)):self.verify()
        path.unlink();path.write_bytes(original)
        module=self.implementation();module.MAX_REPORT_BYTES=1
        with self.assertRaises((ValueError,AssertionError)):module.verify_native_archive_completeness(self.root,self.suite)
