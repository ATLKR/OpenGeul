"""Synthetic producer archives for the separate six-engine menu UI gate."""
import copy
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
import test_native_archive_completeness as old_archives
from test_native_menu_point_cli import preflight

SOURCE = Path(__file__).resolve().parents[1] / 'e2e/native_menu_archive_completeness.py'
REPORT = '.work/suite-native-menu/results.json'
ROOT = '.work/suite-native-menu/worker-diagnostics'
MODULES = ('writer', 'calc', 'impress', 'draw', 'math', 'base')
VIEW_MODULES = ('writer', 'calc')
CORE_COMMANDS = ['new-hwp', 'home', 'new', 'open', 'save', 'saveAs', 'close']


class NativeMenuArchiveCompletenessTests(unittest.TestCase):
    def setUp(self):
        self.directory = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(self.directory).resolve()
        self.suite = self.root / 'Suite 한글'; self.suite.mkdir()
        self.base = old_archives.NativeArchiveCompletenessTests('test_every_source_fixed_case_and_original_generation_has_one_archive')
        self.base.root, self.base.suite = self.root, self.suite
        self.base.image = str(self.suite / 'Office/program/soffice.bin')
        self.base.next_pid, self.base.expected = 100, []
        rows = []
        for module in MODULES:
            row = self.base.row('native-menu-' + module, 1, 'gui', ROOT)
            row.update(module=module, kind='native-menu-gesture-case', scenarioCompleted=True,
                actualWindowsExecuted=True, nativeMenuVerified=True, cleanupConfirmed=True,
                cleanClose=True, forcedCleanupRequired=False, officeExited=True,
                officeExitedAfterCleanup=True, officeExitCode=0, shellExitCode=0,
                engineHandleReleased=True, officeCreationTime=row['nativeArchiveGeneration']['creationTime'])
            row.update(viewRoundtripCompleted=module in VIEW_MODULES,
                       viewPhysicalVerified=module in VIEW_MODULES,
                       hwpLauncherCompleted=module=='writer', nativeHwpMenuLaunchExecuted=module=='writer')
            row['nativeMenuActions']=[]
            row['gestures']=[dict(index=index,gesture=gesture,
                receipt=dict(gesture=gesture,success=True,
                    receipt=self.action(row,gesture,gesture=True)))
                for index,gesture in enumerate(('open-escape','open-outside','keyboard-escape','open-escape'))]
            if module in VIEW_MODULES:
                preview_first=self.action(row,'printPreview')
                preview_second=self.action(row,'printPreview')
                core_first=self.action(row,'core-commands',gesture=True)
                core_second=self.action(row,'core-commands',gesture=True)
                row['nativeViewRoundtrip'] = dict(kind='native-view-roundtrip', module=module,
                    success=True, originalHomeSurvived=True,
                    previewActions=[preview_first,preview_second],
                    observations=[dict(kind='owned-native-view-observation', success=True,
                        module=module, preview=preview, menuVisible=visible,
                        statusRpcProved=True, statusSequenceVersion=1,
                        firstTargetStartedSequence=0, lastTargetCompletedSequence=1)
                        for preview, visible in ((True, True), (False, True), (False, False), (False, True))],
                    fullscreenActions=[dict(kind='owned-native-fullscreen-toggle', success=True,
                        module=module, focusReturned=True) for _ in range(2)],
                    coreCommands=[core_first,core_second])
            if module=='calc':
                self.action(row,'exit')
                row['postExitCancelMenu']=dict(gesture='open-escape',success=True,
                    receipt=self.action(row,'open-escape',gesture=True))
                row['nativeExitCancelVerified']=True
            elif module=='base':
                row['baseSaveMenuAction']=self.action(row,'save')
                self.action(row,'exit');row['nativeExitVerified']=True
            elif module in ('draw','math'):
                self.action(row,'close');row['nativeCloseVerified']=True
            rows.append(row)
        rows[0]['originalHomeHwnd']=70000
        rows[0]['nativeHwpLauncher']=self.hwp_receipt(rows[0])
        self.action(rows[0],'home');rows[0]['nativeHomeVerified']=True
        self.report = dict(schemaVersion=1, kind='native-menu-gesture-matrix', success=True,
            actualWindowsExecuted=True, nativeMenuVerified=True, scenarioSuccess=True,
            acceptanceEligible=False, expectedCaseCount=6, completedCaseCount=6,
            viewPhysicalVerified=True, viewPhysicalExpectedCaseCount=2, viewPhysicalVerifiedCaseCount=2,
            nativeHwpMenuLaunchExecuted=True, passedCaseCount=6, missingModules=[], failedModules=[], tests=rows)
        self.report.update(nativePointProfileVersion=2,nativePointPreflight=preflight())
        self.save_report()
        for index, entry in enumerate(self.base.expected):
            self.base.archive(entry, index)

    def action(self,row,command,*,gesture=False):
        from test_owned_native_menu import OwnedNativeMenuTests
        helper=OwnedNativeMenuTests();self.addCleanup(helper.doCleanups)
        menu,api,process,record,clock,probe=helper.fixture()
        clock.now=1.+10*len(row['nativeMenuActions'])
        process.opengeul_suite_root=self.suite
        probe.shell['image']=str(self.suite/'OpenGeul.Office.exe')
        probe.engine['image']=str(self.suite/'Office/program/soffice.bin')
        run=menu.inspect_native_menu if gesture else menu.click_native_menu_action
        action=run(api,process,11,record,command,probe=probe,clock=clock)
        action=self.remap_action(action,row)
        menu.require_native_menu_action(action,row['shellPid'],row['windowHwnd'],command)
        row['nativeMenuActions'].append(copy.deepcopy(action))
        return action

    def remap_action(self,action,row):
        old_root=str(Path(action['originalProcess']['image']).parent)
        shell=row['windowActivations'][0]['originalProcess'];generation=row['nativeArchiveGeneration']
        replacements={77:row['shellPid'],88:row['officePid'],11:row['windowHwnd'],55:row['parentHwnd'],
            56:row['childHwnd'],99:row['windowHwnd']+10000,8:shell['handleValue'],100:shell['creationTime'],200:generation['creationTime']}
        identity_fields={'pid','shellPid','officePid','documentHwnd','document','parent','child',
            'hwnd','nativeHwnd','hitHwnd','rootHwnd','focusPid','focusHwnd','focusRootHwnd','activeHwnd',
            'captureHwnd','menuOwnerHwnd','foreground','handleValue','engineHandleValue',
            'creationTime','shellCreationTime','officeCreationTime','engine_pid','shell_pid',
            'engine_birth','shell_birth','parent_hwnd','child_hwnd'}
        def remap(value,field=None):
            if type(value) is int:return replacements.get(value,value) if field in identity_fields else value
            if type(value) is list:
                return [replacements.get(item,item) for item in value] if field=='ownerChain' else [remap(item) for item in value]
            if type(value) is dict:return {key:remap(item,key) for key,item in value.items()}
            if type(value) is str and (value==old_root or value.startswith((old_root+'/',old_root+'\\'))):
                return str(self.suite)+value[len(old_root):]
            return value
        return remap(action)

    def canonical_gesture(self):
        from test_owned_native_menu import canonical_action_fixture
        menu,action=canonical_action_fixture(self,operation='open-escape',gesture=True)
        row=self.report['tests'][0]
        action=json.loads(json.dumps(self.remap_action(action,row)))
        menu.require_native_menu_action(action,row['shellPid'],row['windowHwnd'],'open-escape')
        providers=[]
        for path in self.provider_paths(action):
            point=action
            for key in path:point=point[key]
            providers.append(point['providerLocalProof']['provider'])
        last=max(providers,key=lambda packet:packet['scopeId'])
        action.setdefault('uiaInterop',{})['providerLocalResult']=copy.deepcopy(last)
        row['nativeMenuActions'][0]=copy.deepcopy(action)
        row['gestures'][0]['receipt']['receipt']=copy.deepcopy(action)
        self.save_report()
        return action

    def provider_paths(self,action):
        pending=[(action,())];paths=[]
        while pending:
            value,path=pending.pop()
            if type(value) is dict:
                if 'providerLocalProof' in value:paths.append(path)
                pending.extend((item,path+(key,)) for key,item in value.items())
            elif type(value) is list:pending.extend((item,path+(index,)) for index,item in enumerate(value))
        return paths

    def replace_first_gesture(self,action):
        row=self.report['tests'][0]
        row['nativeMenuActions'][0]=copy.deepcopy(action)
        row['gestures'][0]['receipt']['receipt']=copy.deepcopy(action)
        self.save_report()

    def multiple_scope_action(self):
        from test_owned_native_menu import canonical_action_fixture
        _,action=canonical_action_fixture(self,operation='save',gesture=False)
        action=json.loads(json.dumps(action));packets=[]
        for path in self.provider_paths(action):
            point=action
            for key in path:point=point[key]
            packets.append(point['providerLocalProof']['provider'])
        self.assertGreater(len({packet['scopeId'] for packet in packets}),1)
        action.setdefault('uiaInterop',{})['providerLocalResult']=copy.deepcopy(max(packets,key=lambda packet:packet['scopeId']))
        return action

    def hwp_receipt(self,row):
        action=self.action(row,'new-hwp')
        shell=row['windowActivations'][0]['originalProcess']
        def stamp(n):return dict(low=n,high=0,fileTime=n)
        executable=str(self.suite/'HWP/OpenGeul.exe');born=200000+row['shellPid'];pid=500000+row['shellPid'];handle=600000+pid
        new=dict(pid=pid,parentPid=row['shellPid'],executable=executable,creationFileTime=born)
        original=dict(kind='retained-suite-popen-process',pid=shell['pid'],handleValue=shell['handleValue'],
            nativeImage=shell['image'],nativeImageLength=len(shell['image']),nativeCreation=stamp(shell['creationTime']),waitResult=258,exitCode=259)
        live=dict(kind='home-retained-live-process',pid=pid,creationTime=born,handleValue=handle,getProcessIdResult=pid,waitResult=258,
            expectedImage=executable,nativeImage=executable,nativeImageLength=len(executable),nativeCreation=stamp(born))
        def census(matched):
            when=(300000 if matched else 150000)+row['shellPid']
            candidate=dict(pid=pid,parentPid=row['shellPid'],snapshotExeName='OpenGeul.exe',parentMatches=True,nameMatches=True,
                queryAttempted=True,handleOpened=True,handleClosed=True,matched=True,nativeImage=executable,nativeImageLength=len(executable),
                image=executable,nativeCreation=stamp(born),creationFileTime=born,imageMatches=True,generationWithinSnapshot=True)
            return dict(schemaVersion=1,kind='native-hwp-child-census',clockApi='GetSystemTimePreciseAsFileTime',shellPid=row['shellPid'],
                shellCreationFileTime=shell['creationTime'],expectedExecutable=executable,snapshotClock=stamp(when),snapshotStartedFileTime=when,
                snapshotHandleCreated=True,snapshotClosed=True,enumerationComplete=True,candidates=[candidate] if matched else [],
                match=copy.deepcopy(new) if matched else None,success=True)
        exit=dict(liveBinding=copy.deepcopy(live),pid=pid,creationTime=born,handleValue=handle,image=executable,
            imageSource='retained-live-binding',waitResult=0,getProcessIdResult=pid,getProcessTimesResult=True,
            processTimes={key:stamp(value) for key,value in [('creation',born),('exit',born+1),('kernel',0),('user',0)]},
            getExitCodeProcessResult=True,exitCode=0)
        return dict(kind='owned-native-hwp-launcher',success=True,launchKind='no-argument-launcher',noArgumentBasis='native-new-hwp-shell-route',
            documentCreated=False,hwpApplicationHomeReady=False,originalOfficeHomeHwnd=row['originalHomeHwnd'],
            originalOfficeHomeNativeAvailable=True,visibleOwnedMainWindow=True,windowHwnd=pid+1,windowPid=pid,windowRootHwnd=pid+1,
            webviewHwnds=[pid+2],censuses=[census(False),census(True)],shellBindingChecks=7,closeRequests=1,
            normalExitVerified=True,handleReleased=True,handleValue=handle,cleanupPending=False,originalShell=original,
            menuAction=action,generation=new,liveBinding=live,exit=exit)

    def implementation(self):
        self.assertTrue(SOURCE.is_file(), 'The independent native menu archive join is missing')
        spec = importlib.util.spec_from_file_location('native_menu_archive_under_test', SOURCE)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        return module

    def verify(self):
        return self.implementation().verify_native_menu_archive_completeness(self.root, self.suite)

    def save_report(self):
        self.base.write_json(self.root / REPORT, self.report)

    def reseal_last(self, change):
        entry = self.base.expected[0]
        path = entry['folder'] / 'events.jsonl'
        lines = path.read_bytes().splitlines()
        last = json.loads(lines[-1]); change(last)
        lines[-1] = json.dumps(last, separators=(',', ':')).encode()
        path.write_bytes(b'\n'.join(lines) + b'\n')
        entry['diagnostics'].record_shutdown(entry['shutdownProof'])

    def test_exact_six_source_cases_match_sealed_archives_without_rewriting_reports(self):
        before = (self.root / REPORT).read_bytes()
        result = self.verify()
        self.assertIs(result['success'], True)
        self.assertEqual((result['expectedGenerations'], result['matchedGenerations']), (6, 6))
        self.assertEqual([r['case'] for r in result['archives']], ['native-menu-' + m for m in MODULES])
        self.assertEqual(result['sourceReceipts'][0]['sha256'], hashlib.sha256(before).hexdigest())
        self.assertEqual((self.root / REPORT).read_bytes(), before)
        self.assertTrue(all(row['lastEventVerified'] for row in result['archives']))
        for forbidden in ('bodyText', 'keyTokens', 'processes', 'metadata'):
            self.assertNotIn(forbidden, json.dumps(result))

    def test_success_report_requires_this_cli_native_thread_preflight(self):
        original=copy.deepcopy(self.report)
        for key in ('nativePointProfileVersion','nativePointPreflight'):
            self.report=copy.deepcopy(original);self.report.pop(key);self.save_report()
            with self.assertRaises(ValueError):self.verify()

    def test_current_gate_rejects_legacy_or_relabelled_controller_profile(self):
        for version in (0,1,True,'2',3):
            with self.subTest(version=version):
                self.report['nativePointProfileVersion']=version;self.save_report()
                with self.assertRaises(ValueError):self.verify()

    def test_summary_success_cannot_replace_the_flat_original_action_ledger(self):
        original=copy.deepcopy(self.report)
        for value in (None,[],[dict(kind='owned-native-menu-action',success=True)]):
            with self.subTest(missing=value is None):
                self.report=copy.deepcopy(original)
                if value is None:self.report['tests'][0].pop('nativeMenuActions')
                else:self.report['tests'][0]['nativeMenuActions']=value
                self.save_report()
                with self.assertRaises(ValueError):self.verify()

    def test_fixed_gesture_receipts_cannot_be_missing_reordered_or_relabelled(self):
        original=copy.deepcopy(self.report)
        for mutation in ('missing','short','reverse','index','summary'):
            with self.subTest(mutation=mutation):
                self.report=copy.deepcopy(original);row=self.report['tests'][0]
                if mutation=='missing':row.pop('gestures')
                elif mutation=='short':row['gestures'].pop()
                elif mutation=='reverse':row['gestures'].reverse()
                elif mutation=='index':row['gestures'][0]['index']=1
                else:row['gestures'][0]['receipt']['receipt']=dict(kind='owned-native-menu-action',success=True)
                self.save_report()
                with self.assertRaises(ValueError):self.verify()

    def test_nested_action_must_equal_one_original_flat_ledger_entry(self):
        original=copy.deepcopy(self.report)
        for mutation in ('orphan','divergent','duplicate','reorder','foreign-generation'):
            with self.subTest(mutation=mutation):
                self.report=copy.deepcopy(original);row=self.report['tests'][0]
                if mutation=='orphan':row['nativeMenuActions'].pop(0)
                elif mutation=='divergent':row['gestures'][0]['receipt']['receipt']['inputVerified']=False
                elif mutation=='duplicate':row['nativeMenuActions'].append(copy.deepcopy(row['nativeMenuActions'][0]))
                elif mutation=='reorder':row['nativeMenuActions'].reverse()
                else:row['nativeMenuActions'][0]['originalEngine']['creationTime']+=1
                self.save_report()
                with self.assertRaises(ValueError):self.verify()

    def test_current_archive_replays_a_complete_canonical_point_without_promoting_global_false(self):
        action=self.canonical_gesture();paths=self.provider_paths(action)
        self.assertGreater(len(paths),0)
        for path in paths:
            point=action
            for key in path:point=point[key]
            self.assertIs(point['uiaMatches'],False)
            self.assertEqual(point['pointMethod'],'owned-popup-and-msaa-canonical-hit-v2')
            self.assertEqual(point['providerLocalProof']['provider']['workerSchemaVersion'],2)
        self.assertIs(self.verify()['success'],True)

    def test_every_nested_canonical_positive_flag_is_replayed_beyond_matching_summary_and_ledger(self):
        action=self.canonical_gesture();self.verify()
        flags=('filePairEqual','fileOriginalRepeatEqual','targetPairEqual','targetDifferentFromFile',
            'hitMatchesTarget','fileUiPositive','targetUiPositive','localKnown','localMatch','workerCleanup',
            'nativeExit','threadClosed','processesClosed','threadIdentity','callbackIdentity','physicalDpiVerified')
        for path in self.provider_paths(action):
            for flag in flags:
                with self.subTest(path=path,flag=flag):
                    changed=copy.deepcopy(action);point=changed
                    for key in path:point=point[key]
                    point['providerLocalProof']['provider'][flag]=0
                    self.replace_first_gesture(changed)
                    with self.assertRaises(ValueError):self.verify()

    def test_canonical_versions_scope_creator_counts_popup_and_staleness_cannot_be_relabelled(self):
        action=self.canonical_gesture();self.verify();path=self.provider_paths(action)[0]
        changes=[(('pointMethod',),'owned-popup-and-msaa-hit'),(('uiaMatches',),True),
            (('providerLocalProof','schemaVersion'),1),
            (('providerLocalProof','method'),'owned-popup-and-msaa-hit'),
            (('providerLocalProof','provider','schemaVersion'),1),
            (('providerLocalProof','provider','workerSchemaVersion'),1),
            (('providerLocalProof','provider','canonicalStatus'),0),
            (('providerLocalProof','provider','workerStage'),7),
            (('providerLocalProof','provider','bindingCount'),3),
            (('providerLocalProof','provider','selfCount'),3),
            (('providerLocalProof','provider','referencesAcquired'),15),
            (('providerLocalProof','provider','referencesReleased'),15),
            (('providerLocalProof','provider','negativeRejected'),0),
            (('providerLocalProof','provider','pending'),1),
            (('providerLocalProof','provider','synthetic'),1),
            (('providerLocalProof','creator','sameThread'),False),
            (('providerLocalProof','sourceScope','engine_pid'),999),
            (('providerLocalProof','globalPoint','kindCode'),50011),
            (('providerLocalProof','before','ownershipAfter'),False),
            (('providerLocalProof','sourceFresh','scope','deadline'),999),
            (('providerLocalProof','fresh','positive','file'),False)]
        for keys,value in changes:
            with self.subTest(keys=keys):
                changed=copy.deepcopy(action);point=changed
                for key in path:point=point[key]
                target=point
                for key in keys[:-1]:target=target[key]
                target[keys[-1]]=value
                self.replace_first_gesture(changed)
                with self.assertRaises(ValueError):self.verify()

    def test_matching_view_action_success_summaries_do_not_hide_invalid_actual_receipts(self):
        original=copy.deepcopy(self.report)
        for field,key in (('previewActions','pointers'),('coreCommands','coreSnapshots')):
            with self.subTest(field=field):
                self.report=copy.deepcopy(original);row=self.report['tests'][0]
                action=row['nativeViewRoundtrip'][field][0]
                original_bytes=json.dumps(action,sort_keys=True)
                index=next(i for i,item in enumerate(row['nativeMenuActions'])
                    if json.dumps(item,sort_keys=True)==original_bytes)
                action[key]=[] if key=='pointers' else {}
                row['nativeMenuActions'][index]=copy.deepcopy(action);self.save_report()
                with self.assertRaises(ValueError):self.verify()

    def test_worker_diagnostic_packet_must_equal_an_actual_replayed_point_provider(self):
        action=self.canonical_gesture();self.verify()
        for key,value in (('localMatch',0),('canonicalStatus',0),('scopeId',999),
                ('referencesReleased',15),('nativeExit',0),('extraFlag',1)):
            with self.subTest(key=key):
                changed=copy.deepcopy(action)
                changed['uiaInterop']['providerLocalResult'][key]=value
                self.replace_first_gesture(changed)
                with self.assertRaises(ValueError):self.verify()

    def test_retained_point_snapshot_with_missing_identity_is_a_controlled_archive_failure(self):
        action=self.canonical_gesture()
        snapshot=action['menuObservation']['snapshot']
        self.assertIn('providerLocalProof',snapshot['targetPointProof'])
        snapshot['identityProof']=None
        self.replace_first_gesture(action)
        with self.assertRaises(ValueError):self.verify()

    def test_canonical_worker_packet_requires_the_original_path_and_latest_scope(self):
        action=self.multiple_scope_action();check=self.implementation()._action_profiles;check(action);packets=[]
        for path in self.provider_paths(action):
            point=action
            for key in path:point=point[key]
            packets.append(point['providerLocalProof']['provider'])
        older=min(packets,key=lambda packet:packet['scopeId'])
        for mutation in ('missing-path','older','nested-only','extra-older'):
            with self.subTest(mutation=mutation):
                changed=copy.deepcopy(action)
                if mutation=='missing-path':changed['uiaInterop'].pop('providerLocalResult')
                elif mutation=='older':changed['uiaInterop']['providerLocalResult']=copy.deepcopy(older)
                elif mutation=='nested-only':
                    packet=changed['uiaInterop'].pop('providerLocalResult')
                    changed['otherDiagnostic']=dict(providerLocalResult=packet)
                else:changed['otherDiagnostic']=dict(providerLocalResult=copy.deepcopy(older))
                with self.assertRaises(ValueError):check(changed)

    def test_the_same_local_scope_cannot_describe_two_different_worker_packets(self):
        action=self.multiple_scope_action();paths=self.provider_paths(action)
        points=[]
        for path in paths:
            point=action
            for key in path:point=point[key]
            points.append(point)
        first=min(points,key=lambda point:point['providerLocalProof']['sourceScopeId'])
        second=max(points,key=lambda point:point['providerLocalProof']['sourceScopeId'])
        scope=first['providerLocalProof']['sourceScopeId']
        second['providerLocalProof']['sourceScopeId']=scope
        second['providerLocalProof']['sourceScope']['scope_id']=scope
        second['providerLocalProof']['provider']['scopeId']=scope
        second['providerLocalProof']['provider']['threadBirth']+=1
        packets=[point['providerLocalProof']['provider'] for point in points]
        action['uiaInterop']['providerLocalResult']=copy.deepcopy(max(packets,key=lambda packet:packet['scopeId']))
        with self.assertRaises(ValueError):self.implementation()._action_profiles(action)

    def test_a_global_only_action_cannot_retain_a_local_worker_packet(self):
        action=self.canonical_gesture();packet=copy.deepcopy(action['uiaInterop']['providerLocalResult'])
        row=self.report['tests'][1];changed=copy.deepcopy(row['nativeMenuActions'][0])
        self.assertEqual(self.provider_paths(changed),[])
        changed.setdefault('uiaInterop',{})['providerLocalResult']=packet
        row['nativeMenuActions'][0]=copy.deepcopy(changed)
        row['gestures'][0]['receipt']['receipt']=copy.deepcopy(changed)
        self.save_report()
        with self.assertRaises(ValueError):self.verify()

    def retime_action(self,action,start):
        delta=start-action['startedAt']
        def change(value,field=None):
            if field in ('startedAt','deadline','finishedAt'):return value+delta
            if type(value) is dict:return {key:change(item,key) for key,item in value.items()}
            if type(value) is list:return [change(item) for item in value]
            return value
        return change(action)

    def test_each_fixed_repeated_gesture_slot_needs_a_distinct_increasing_ledger_entry(self):
        original=copy.deepcopy(self.report)
        for mutation in ('reuse-delete','swap'):
            with self.subTest(mutation=mutation):
                self.report=copy.deepcopy(original);row=self.report['tests'][0]
                first=row['gestures'][0]['receipt']['receipt'];last=row['gestures'][3]['receipt']['receipt']
                if mutation=='reuse-delete':
                    row['gestures'][3]['receipt']['receipt']=copy.deepcopy(first)
                    row['nativeMenuActions'].pop(3)
                else:
                    row['gestures'][0]['receipt']['receipt'],row['gestures'][3]['receipt']['receipt']=last,first
                self.save_report()
                with self.assertRaises(ValueError):self.verify()

    def test_preview_and_core_slots_cannot_reuse_delete_or_exchange_the_original_actions(self):
        original=copy.deepcopy(self.report)
        for field,offset in (('previewActions',4),('coreCommands',6)):
            for mutation in ('reuse-delete','swap'):
                with self.subTest(field=field,mutation=mutation):
                    self.report=copy.deepcopy(original);row=self.report['tests'][0]
                    items=row['nativeViewRoundtrip'][field]
                    if mutation=='reuse-delete':
                        items[1]=copy.deepcopy(items[0]);row['nativeMenuActions'].pop(offset+1)
                    else:items[0],items[1]=items[1],items[0]
                    self.save_report()
                    with self.assertRaises(ValueError):self.verify()

    def test_native_preview_must_finish_both_actions_before_the_first_core_slot(self):
        row=self.report['tests'][0];view=row['nativeViewRoundtrip']
        preview=view['previewActions'][1];core=view['coreCommands'][0]
        early=self.retime_action(core,preview['startedAt']);late=self.retime_action(preview,core['startedAt'])
        view['coreCommands'][0]=copy.deepcopy(early);view['previewActions'][1]=copy.deepcopy(late)
        row['nativeMenuActions'][5:7]=[copy.deepcopy(early),copy.deepcopy(late)]
        self.save_report()
        with self.assertRaises(ValueError):self.verify()

    def test_source_finish_slots_are_not_dropped_or_reordered_after_the_fixed_prefix(self):
        self.assertEqual({row['module']:len(row['nativeMenuActions']) for row in self.report['tests']},
            dict(writer=10,calc=10,impress=4,draw=5,math=5,base=6))
        self.verify();original=copy.deepcopy(self.report)
        for module in ('writer','calc','draw','math','base'):
            with self.subTest(module=module,mutation='missing-finish'):
                self.report=copy.deepcopy(original);row=next(item for item in self.report['tests'] if item['module']==module)
                row['nativeMenuActions'].pop(8 if module=='calc' else -1)
                self.save_report()
                with self.assertRaises(ValueError):self.verify()
        for module in ('writer','base'):
            with self.subTest(module=module,mutation='reverse-finish'):
                self.report=copy.deepcopy(original);row=next(item for item in self.report['tests'] if item['module']==module)
                first,last=row['nativeMenuActions'][-2:]
                early=self.retime_action(last,first['startedAt']);late=self.retime_action(first,last['startedAt'])
                row['nativeMenuActions'][-2:]=[copy.deepcopy(early),copy.deepcopy(late)]
                if module=='writer':row['nativeHwpLauncher']['menuAction']=copy.deepcopy(late)
                else:row['baseSaveMenuAction']=copy.deepcopy(late)
                self.save_report()
                with self.assertRaises(ValueError):self.verify()

    def test_cancel_menu_finish_slot_and_unplanned_extra_action_cannot_hide_in_the_ledger(self):
        original=copy.deepcopy(self.report);row=self.report['tests'][1]
        row['postExitCancelMenu']['receipt']=copy.deepcopy(row['gestures'][0]['receipt']['receipt'])
        row['nativeMenuActions'].pop();self.save_report()
        with self.assertRaises(ValueError):self.verify()
        self.report=copy.deepcopy(original);self.action(self.report['tests'][2],'close');self.save_report()
        with self.assertRaises(ValueError):self.verify()

    def test_legacy_success_report_without_physical_view_cases_is_rejected(self):
        for key in ('viewPhysicalVerified', 'viewPhysicalExpectedCaseCount',
                    'viewPhysicalVerifiedCaseCount'):
            self.report.pop(key, None)
        for row in self.report['tests']:
            for key in ('viewRoundtripCompleted', 'viewPhysicalVerified', 'nativeViewRoundtrip'):
                row.pop(key, None)
        self.save_report()
        with self.assertRaises(ValueError):
            self.verify()

    def test_legacy_success_without_mandatory_hwp_evidence_is_rejected(self):
        self.report.pop('nativeHwpMenuLaunchExecuted')
        for row in self.report['tests']:
            for key in ('nativeHwpMenuLaunchExecuted','hwpLauncherCompleted','nativeHwpLauncher'):row.pop(key,None)
        self.save_report()
        with self.assertRaises(ValueError):self.verify()

    def test_hwp_success_booleans_without_receipt_are_rejected(self):
        self.report['tests'][0].pop('nativeHwpLauncher');self.save_report()
        with self.assertRaises(ValueError):self.verify()

    def test_hwp_scope_generation_close_exit_and_menu_receipt_tampering_are_rejected(self):
        mutations=[(('nativeHwpMenuLaunchExecuted',),False),(('hwpLauncherCompleted',),False),
            (('nativeHwpLauncher','generation','executable'),'/foreign/OpenGeul.exe'),
            (('nativeHwpLauncher','generation','pid'),999), (('nativeHwpLauncher','generation','creationFileTime'),1),
            (('nativeHwpLauncher','censuses',0,'match'),{'pid':123}),
            (('nativeHwpLauncher','liveBinding','handleValue'),999),
            (('nativeHwpLauncher','exit','handleValue'),999), (('nativeHwpLauncher','exit','exitCode'),7),
            (('nativeHwpLauncher','closeRequests'),0),(('nativeHwpLauncher','handleReleased'),False),
            (('nativeHwpLauncher','cleanupPending'),True),(('nativeHwpLauncher','windowPid'),999),
            (('nativeHwpLauncher','documentCreated'),True),(('nativeHwpLauncher','hwpApplicationHomeReady'),True),
            (('nativeHwpLauncher','originalShell','handleValue'),999),
            (('nativeHwpLauncher','menuAction','documentHwnd'),999),
            (('nativeHwpLauncher','menuAction','originalEngine','creationTime'),999),
            (('nativeHwpLauncher','menuAction','pointers'),[])]
        original=copy.deepcopy(self.report)
        for path,damage in mutations:
            with self.subTest(path=path):
                self.report=copy.deepcopy(original);target=self.report['tests'][0]
                for key in path[:-1]:target=target[key]
                target[path[-1]]=damage;self.save_report()
                with self.assertRaises(ValueError):self.verify()

    def test_legacy_view_observations_without_completed_status_rpc_are_rejected(self):
        original = copy.deepcopy(self.report)
        for case in (0, 1):
            for observation in range(4):
                for value in (None, False):
                    with self.subTest(case=case, observation=observation, value=value):
                        self.report = copy.deepcopy(original)
                        row = self.report['tests'][case]['nativeViewRoundtrip']['observations'][observation]
                        if value is None: row.pop('statusRpcProved', None)
                        else: row['statusRpcProved'] = value
                        self.save_report()
                        with self.assertRaises(ValueError): self.verify()

    def test_status_rpc_summary_rejects_missing_wrong_type_or_out_of_range_values(self):
        original = copy.deepcopy(self.report)
        for key, values in (
                ('statusRpcProved', (None, False, 1, 'true')),
                ('statusSequenceVersion', (None, 0, 2, True, 1.0, '1')),
                ('firstTargetStartedSequence', (None, -1, 1 << 28, False, True, 0.0, '0')),
                ('lastTargetCompletedSequence', (None, -1, 1 << 28, False, True, 1.0, '1'))):
            for value in values:
                with self.subTest(key=key, value=value):
                    self.report = copy.deepcopy(original)
                    row = self.report['tests'][0]['nativeViewRoundtrip']['observations'][0]
                    if value is None: row.pop(key)
                    else: row[key] = value
                    self.save_report()
                    with self.assertRaises(ValueError): self.verify()

    def test_status_rpc_completion_must_follow_the_first_target_started_sequence(self):
        original = copy.deepcopy(self.report)
        for case in (0, 1):
            for started, completed in ((0, 0), (3, 2), ((1 << 28) - 1, (1 << 28) - 1)):
                with self.subTest(case=case, started=started, completed=completed):
                    self.report = copy.deepcopy(original)
                    row = self.report['tests'][case]['nativeViewRoundtrip']['observations'][0]
                    row.update(firstTargetStartedSequence=started, lastTargetCompletedSequence=completed)
                    self.save_report()
                    with self.assertRaises(ValueError): self.verify()

    def test_status_rpc_summary_accepts_exact_28bit_bounds_without_rewriting_the_report(self):
        original = copy.deepcopy(self.report)
        for started, completed in ((0, 1), (0, (1 << 28) - 1), ((1 << 28) - 2, (1 << 28) - 1)):
            with self.subTest(started=started, completed=completed):
                self.report = copy.deepcopy(original)
                for case in (0, 1):
                    for row in self.report['tests'][case]['nativeViewRoundtrip']['observations']:
                        row.update(firstTargetStartedSequence=started, lastTargetCompletedSequence=completed)
                self.save_report(); before = (self.root / REPORT).read_bytes()
                result = self.verify()
                self.assertIs(result['success'], True)
                self.assertEqual((self.root / REPORT).read_bytes(), before)
                self.assertEqual(result['sourceReceipts'][0]['sha256'], hashlib.sha256(before).hexdigest())

    def test_view_report_flags_and_counts_cannot_qualify_missing_or_different_coverage(self):
        original = copy.deepcopy(self.report)
        for key, values in (
                ('viewPhysicalVerified', (None, False, 1, 'true')),
                ('viewPhysicalExpectedCaseCount', (None, 1, 3, True, 2.0, '2')),
                ('viewPhysicalVerifiedCaseCount', (None, 1, 3, True, 2.0, '2'))):
            for value in values:
                with self.subTest(key=key, value=value):
                    self.report = copy.deepcopy(original)
                    if value is None: self.report.pop(key)
                    else: self.report[key] = value
                    self.save_report()
                    with self.assertRaises(ValueError): self.verify()

    def test_each_writer_and_calc_requires_its_actual_completed_view_roundtrip(self):
        original = copy.deepcopy(self.report)
        for index in (0, 1):
            for key in ('viewRoundtripCompleted', 'viewPhysicalVerified'):
                for value in (None, False, 1, 'true'):
                    with self.subTest(module=VIEW_MODULES[index], key=key, value=value):
                        self.report = copy.deepcopy(original)
                        if value is None: self.report['tests'][index].pop(key)
                        else: self.report['tests'][index][key] = value
                        self.save_report()
                        with self.assertRaises(ValueError): self.verify()

    def test_other_modules_cannot_replace_or_mix_with_the_two_source_fixed_view_cases(self):
        original = copy.deepcopy(self.report)
        for index in range(2, 6):
            for mixed in (False, True):
                with self.subTest(module=MODULES[index], mixed=mixed):
                    self.report = copy.deepcopy(original)
                    target = self.report['tests'][index]
                    target.update(viewRoundtripCompleted=True, viewPhysicalVerified=True,
                                  nativeViewRoundtrip=copy.deepcopy(self.report['tests'][0]['nativeViewRoundtrip']))
                    target['nativeViewRoundtrip']['module'] = MODULES[index]
                    if mixed:
                        self.report['tests'][0].update(viewRoundtripCompleted=False, viewPhysicalVerified=False)
                        self.report['tests'][0].pop('nativeViewRoundtrip')
                    self.save_report()
                    with self.assertRaises(ValueError): self.verify()

    def test_roundtrip_kind_module_success_and_home_must_match_the_original_case(self):
        original = copy.deepcopy(self.report)
        changes = (('kind', 'other'), ('module', 'calc'), ('success', False),
                   ('success', 1), ('originalHomeSurvived', False), ('originalHomeSurvived', None))
        for key, value in changes:
            with self.subTest(key=key, value=value):
                self.report = copy.deepcopy(original)
                roundtrip = self.report['tests'][0]['nativeViewRoundtrip']
                if value is None: roundtrip.pop(key)
                else: roundtrip[key] = value
                self.save_report()
                with self.assertRaises(ValueError): self.verify()
        for value in (None, [], True):
            self.report = copy.deepcopy(original)
            if value is None: self.report['tests'][0].pop('nativeViewRoundtrip')
            else: self.report['tests'][0]['nativeViewRoundtrip'] = value
            self.save_report()
            with self.assertRaises(ValueError): self.verify()

    def test_roundtrip_requires_each_current_source_plan_step_and_order(self):
        original = copy.deepcopy(self.report)
        for field in ('previewActions', 'observations', 'fullscreenActions', 'coreCommands'):
            for mutation in ('missing', 'short', 'extra', 'failed', 'kind'):
                with self.subTest(field=field, mutation=mutation):
                    self.report = copy.deepcopy(original)
                    roundtrip = self.report['tests'][0]['nativeViewRoundtrip']
                    if mutation == 'missing': roundtrip.pop(field)
                    elif mutation == 'short': roundtrip[field].pop()
                    elif mutation == 'extra': roundtrip[field].append(copy.deepcopy(roundtrip[field][-1]))
                    else: roundtrip[field][0]['success' if mutation == 'failed' else 'kind'] = False if mutation == 'failed' else 'other'
                    self.save_report()
                    with self.assertRaises(ValueError): self.verify()
        for target, key, value in (
                ('previewActions', 'command', 'save'), ('previewActions', 'gesture', True),
                ('fullscreenActions', 'module', 'calc'), ('fullscreenActions', 'focusReturned', False),
                ('observations', 'module', 'calc'), ('observations', 'preview', 1),
                ('observations', 'menuVisible', False), ('coreCommands', 'command', 'save'),
                ('coreCommands', 'gesture', False), ('coreCommands', 'coreCommandsVerified', False),
                ('coreCommands', 'coreCommands', CORE_COMMANDS[:-1]), ('coreCommands', 'focusReturned', False)):
            with self.subTest(field=target, key=key):
                self.report = copy.deepcopy(original)
                self.report['tests'][0]['nativeViewRoundtrip'][target][0][key] = value
                self.save_report()
                with self.assertRaises(ValueError): self.verify()
        self.report = copy.deepcopy(original)
        observations = self.report['tests'][0]['nativeViewRoundtrip']['observations']
        observations[0], observations[1] = observations[1], observations[0]
        self.save_report()
        with self.assertRaises(ValueError): self.verify()

    def test_failed_or_synthetic_report_cannot_substitute_for_actual_six_case_source(self):
        original = copy.deepcopy(self.report)
        for key, value in (('success', False), ('actualWindowsExecuted', False),
                           ('nativeMenuVerified', False), ('kind', 'other'), ('expectedCaseCount', 5)):
            with self.subTest(key=key):
                self.report = copy.deepcopy(original); self.report[key] = value; self.save_report()
                with self.assertRaises(ValueError): self.verify()

    def test_missing_duplicated_or_reordered_cases_are_rejected(self):
        original = copy.deepcopy(self.report)
        for rows in (original['tests'][:-1], original['tests'] + [original['tests'][0]],
                     list(reversed(original['tests']))):
            self.report = copy.deepcopy(original); self.report['tests'] = rows; self.save_report()
            with self.assertRaises(ValueError): self.verify()

    def test_unconfirmed_case_cleanup_and_wrong_original_engine_are_rejected(self):
        original = copy.deepcopy(self.report)
        for key, value in (('cleanupConfirmed', False), ('forcedCleanupRequired', True),
                           ('engineHandleReleased', False), ('officeExitCode', 1),
                           ('officeCreationTime', original['tests'][0]['officeCreationTime'] + 1)):
            with self.subTest(key=key):
                self.report = copy.deepcopy(original); self.report['tests'][0][key] = value; self.save_report()
                with self.assertRaises(ValueError): self.verify()

    def test_original_shell_binding_and_image_guards_are_reused(self):
        original = copy.deepcopy(self.report)
        for target in ('shell', 'image'):
            with self.subTest(target=target):
                self.report = copy.deepcopy(original)
                if target == 'shell':
                    self.report['tests'][0]['windowActivations'][0]['originalProcess']['pid'] += 1
                else:
                    self.report['tests'][0]['nativeArchiveGeneration']['image'] = 'C:/foreign/soffice.bin'
                self.save_report()
                with self.assertRaises(ValueError): self.verify()

    def test_missing_archive_and_duplicate_archive_do_not_hide_in_siblings(self):
        entry = self.base.expected[0]
        original = entry['folder']; moved = self.root / 'omitted'
        original.rename(moved)
        with self.assertRaises(ValueError): self.verify()
        moved.rename(original)
        shutil.copytree(original, self.root / ROOT / ('f' * 32))
        with self.assertRaises(ValueError): self.verify()

    def test_orphan_engine_archive_is_rejected(self):
        self.base.row('synthetic-orphan', 1, 'gui', ROOT)
        self.base.archive(self.base.expected[-1], 7)
        with self.assertRaises(ValueError): self.verify()

    def test_existing_archive_member_hash_and_graceful_guards_are_not_bypassed(self):
        entry = self.base.expected[0]
        events = entry['folder'] / 'events.jsonl'; original = events.read_bytes()
        events.write_bytes(b'?' + original[1:])
        with self.assertRaises(ValueError): self.verify()
        events.write_bytes(original)
        proof = copy.deepcopy(entry['shutdownProof']); proof['forcedTermination'] = True
        entry['diagnostics'].record_shutdown(proof)
        with self.assertRaises(ValueError): self.verify()

    def test_last_event_must_be_after_shutdown_even_if_its_new_bytes_are_sealed(self):
        self.reseal_last(lambda last: last.update(phase='shutdown-unconfirmed'))
        with self.assertRaises(ValueError): self.verify()

    def test_last_event_cannot_hide_missing_duplicate_or_new_engine_generation(self):
        entry = self.base.expected[0]; path = entry['folder'] / 'events.jsonl'; original = path.read_bytes()
        changes = [lambda last: last.update(processes=[]),
            lambda last: last['processes'].append(copy.deepcopy(last['processes'][-1])),
            lambda last: last['processes'][-1].update(pid=999999),
            lambda last: last['processes'][-1].update(creationTime=999999),
            lambda last: last['processes'][-1].update(image='C:/foreign/soffice.bin')]
        for change in changes:
            with self.subTest(change=changes.index(change)):
                path.write_bytes(original); self.reseal_last(change)
                with self.assertRaises(ValueError): self.verify()

    def test_earlier_owned_helper_can_exit_before_the_shutdown_witness_is_opened(self):
        # Actual diagnostics retain job members from bootstrap onward, while the
        # shutdown observer opens later and cannot see an already dead helper.
        entry = self.base.expected[0]; path = entry['folder'] / 'events.jsonl'
        lines = path.read_bytes().splitlines()
        early, terminal = json.loads(lines[0]), json.loads(lines[-1])
        helper = copy.deepcopy(terminal['processes'][0])
        helper.update(pid=900001, creationTime=500001,
            image=str(self.suite / 'Office/program/helper.exe'))
        early['processes'].append(dict(helper, alive=True, waitResult=258,
            exitCode=259, exitCodeHex='0x00000103'))
        terminal['processes'].append(helper)
        lines[0] = json.dumps(early).encode(); lines[-1] = json.dumps(terminal).encode()
        path.write_bytes(b'\n'.join(lines) + b'\n')
        entry['diagnostics'].record_shutdown(entry['shutdownProof'])
        result = self.verify()
        self.assertEqual(result['archives'][0]['lastEventMemberCount'], 3)
        self.assertEqual(result['archives'][0]['earlierDiagnosticMemberCount'], 1)

    def test_diagnostic_only_terminal_member_needs_the_same_earlier_owned_generation(self):
        entry = self.base.expected[0]; path = entry['folder'] / 'events.jsonl'
        original = path.read_bytes()
        for mismatch in ('missing', 'pid', 'creationTime', 'image', 'error'):
            with self.subTest(mismatch=mismatch):
                lines = original.splitlines()
                early, terminal = json.loads(lines[0]), json.loads(lines[-1])
                helper = copy.deepcopy(terminal['processes'][0])
                helper.update(pid=900001, creationTime=500001,
                    image=str(self.suite / 'Office/program/helper.exe'))
                observed = dict(helper, alive=True, waitResult=258,
                    exitCode=259, exitCodeHex='0x00000103')
                if mismatch == 'pid': observed['pid'] += 1
                elif mismatch == 'creationTime': observed['creationTime'] += 1
                elif mismatch == 'image': observed['image'] = 'C:/foreign/helper.exe'
                elif mismatch == 'error': observed['error'] = {'type': 'SyntheticError'}
                if mismatch != 'missing': early['processes'].append(observed)
                terminal['processes'].append(helper)
                lines[0] = json.dumps(early).encode(); lines[-1] = json.dumps(terminal).encode()
                path.write_bytes(b'\n'.join(lines) + b'\n')
                entry['diagnostics'].record_shutdown(entry['shutdownProof'])
                with self.assertRaises(ValueError): self.verify()

    def test_last_event_native_errors_alive_or_nonzero_exit_fail(self):
        entry = self.base.expected[0]; path = entry['folder'] / 'events.jsonl'; original = path.read_bytes()
        for key, value in (('alive', True), ('waitResult', 258), ('exitCode', 1),
                           ('getExitCodeProcessResult', False), ('error', {'type': 'synthetic'})):
            with self.subTest(key=key):
                path.write_bytes(original)
                self.reseal_last(lambda last, key=key, value=value: last['processes'][-1].update({key: value}))
                with self.assertRaises(ValueError): self.verify()

    def test_oversized_last_event_and_trailing_partial_line_are_rejected(self):
        entry = self.base.expected[0]; path = entry['folder'] / 'events.jsonl'
        self.reseal_last(lambda last: last.update(syntheticPadding='x' * (256 * 1024)))
        with self.assertRaises(ValueError): self.verify()
        # Corrupting sealed terminal bytes is also rejected by the shared hash guard.
        path.write_bytes(path.read_bytes()[:-1])
        with self.assertRaises(ValueError): self.verify()

    def test_cli_replay_writes_a_bounded_result_and_preserves_failed_qualification(self):
        module = self.implementation()
        target = self.root / 'coverage.json'
        args = ['--workspace', str(self.root), '--suite', str(self.suite), '--output', str(target)]
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(module.main(args), 0)
        self.assertEqual(json.loads(target.read_text())['matchedGenerations'], 6)
        self.reseal_last(lambda last: last.update(phase='shutdown-unconfirmed'))
        failed = self.root / 'failure.json'
        args[-1] = str(failed)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(module.main(args), 1)
        value = json.loads(failed.read_text())
        self.assertFalse(value['success'])
        self.assertEqual(value['errorType'], 'ValueError')
        self.assertNotIn('processes', value)

    def test_cli_must_not_resolve_away_a_linked_workspace_before_admission(self):
        linked = self.root / 'linked-workspace'
        try:
            os.symlink(self.root, linked, target_is_directory=True)
        except OSError:
            self.skipTest('Directory symlink creation is unavailable to this test process')
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(ValueError):
            self.implementation().main(['--workspace', str(linked), '--suite', str(self.suite),
                '--output', str(self.root / 'linked-result.json')])

    def test_cli_rejects_a_dangling_output_symlink_without_creating_its_target(self):
        target = self.root / 'not-created.json'; linked = self.root / 'linked-output.json'
        try:
            os.symlink(target, linked)
        except OSError:
            self.skipTest('File symlink creation is unavailable to this test process')
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(ValueError):
            self.implementation().main(['--workspace', str(self.root), '--suite', str(self.suite),
                '--output', str(linked)])
        self.assertFalse(target.exists())

    def test_different_menu_cases_cannot_reuse_the_same_original_engine_generation(self):
        first, second = self.report['tests'][:2]
        second['nativeArchiveGeneration'] = copy.deepcopy(first['nativeArchiveGeneration'])
        second['officePid'] = first['officePid']
        second['officeCreationTime'] = first['officeCreationTime']
        self.save_report()
        with self.assertRaisesRegex(ValueError, 'Duplicate original'):
            self.verify()

    def test_only_the_terminal_event_is_parsed_after_the_stream_hash_is_verified(self):
        entry = self.base.expected[0]; path = entry['folder'] / 'events.jsonl'
        lines = path.read_bytes().splitlines()
        lines[0] = b'SYNTHETIC-UNPARSED-EARLIER-EVENT'
        path.write_bytes(b'\n'.join(lines) + b'\n')
        entry['diagnostics'].record_shutdown(entry['shutdownProof'])
        self.assertTrue(self.verify()['success'])

    def test_terminal_event_re_read_is_bound_to_the_descriptor_already_verified(self):
        module = self.implementation(); original = module.original._archived
        path = self.base.expected[0]['folder'] / 'events.jsonl'
        def archive_then_change(*args):
            result = original(*args)
            raw = path.read_bytes(); path.write_bytes(b'?' + raw[1:])
            return result
        with patch.object(module.original, '_archived', side_effect=archive_then_change):
            with self.assertRaisesRegex(ValueError, 'bytes changed'):
                module.verify_native_menu_archive_completeness(self.root, self.suite)
