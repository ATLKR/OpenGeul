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
import time
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


class SourceQualifiedMenuArchiveTests(unittest.TestCase):
    def local_action(self,legacy,admission,*,row_index=-1,ledger_index=-2,operation='save'):
        from test_native_menu_point_profile import source_qualified_action_fixture
        row=legacy.report['tests'][row_index];origin=row['nativeMenuActions'][ledger_index]
        _,action=source_qualified_action_fixture(self,admission,legacy.source_selection,
            operation=operation,started_at=origin['startedAt'])
        action=legacy.remap_action(action,row)
        action['sourceMenu']=copy.deepcopy(origin['sourceMenu'])
        # Synthetic archive cases renumber the fixture's original HWNDs. Keep
        # the separately observed signed raw field consistent with that remap.
        for node in legacy.implementation()._nodes(action):
            if type(node) is dict and 'providerLocalProof' in node:
                raw=node['providerLocalProof']['globalPoint']
                self.assertGreaterEqual(raw['nativeHwndRaw'],0)
                raw['nativeHwndRaw']=raw['nativeHwnd']
        row['nativeMenuActions'][ledger_index]=copy.deepcopy(action)
        if operation=='save':row['baseSaveMenuAction']=copy.deepcopy(action)
        else:
            self.assertEqual((row_index,ledger_index,operation),(0,5,'printPreview'))
            view=row['nativeViewRoundtrip'];view['previewActions'][1]=copy.deepcopy(action)
            for field in ('observations','fullscreenActions'):
                for item in view[field]:
                    if item['originIndex']!=ledger_index:continue
                    for key in ('binding','originalProcess','originalEngine'):item[key]=copy.deepcopy(action[key])
                    if field=='fullscreenActions':item['nativeMenuOrigin']=copy.deepcopy(action)
        legacy.save_report()
        return action

    def fixture(self):
        legacy=NativeMenuArchiveCompletenessTests(methodName='runTest')
        legacy.setUp();self.addCleanup(legacy.doCleanups)
        from suite.tests.test_native_menu_source_admission import SourceMenuAdmissionTests
        import native_menu_source_admission as gate
        source=SourceMenuAdmissionTests(methodName='runTest')
        source.setUp();self.addCleanup(source.doCleanups)
        shutil.copytree(source.root,legacy.suite,dirs_exist_ok=True)
        source.root=legacy.suite
        inputs=source.trusted/'.work/source-engine-input';inputs.mkdir(parents=True)
        (inputs/'OpenGeul-Office-engine-arm64.zip').write_bytes(source.archive.read_bytes())
        (inputs/'source-build-receipt.json').write_bytes(source.receipt.read_bytes())
        import native_menu_source_selection as selected
        self.enterContext(patch.object(gate,'_HARNESS_ROOT',source.trusted))
        prepared=selected.prepare_source_menu_runtime(legacy.suite,'arm64',deadline=time.monotonic()+30)
        legacy.source_selection=selected.source_menu_for_launch(prepared,deadline=time.monotonic()+30)
        admission=prepared.admission
        summary=dict(admission.summary());summary['providers']=[dict(item) for item in summary['providers']]
        legacy.report.update(nativePointProfileVersion=4,sourceMenuAdmission=summary)
        for row in legacy.report['tests']:
            row.update(nativePointProfileVersion=4,sourceMenuAdmission=copy.deepcopy(summary))
            for action in legacy.implementation()._nodes(row):
                if type(action) is not dict or action.get('kind')!='owned-native-menu-action':continue
                binding=action['binding'];shell=action['originalProcess'];engine=action['originalEngine']
                action['sourceMenu']=dict(schemaVersion=1,pointProfileVersion=4,admission=copy.deepcopy(summary),
                    generation=dict(binding,shellPid=shell['pid'],shellCreationTime=shell['creationTime'],
                        shellHandleValue=shell['handleValue'],engineCreationTime=engine['creationTime'],
                        engineHandleValue=action['engineHandleValue']))
                action['pointUses']=[]
            if row['module'] in VIEW_MODULES:
                view=row['nativeViewRoundtrip']
                for field in ('observations','fullscreenActions'):
                    for index,item in enumerate(view[field]):
                        origin_index=4 if field=='observations' and index==0 else 5
                        origin=row['nativeMenuActions'][origin_index]
                        item.update(originIndex=origin_index,binding=copy.deepcopy(origin['binding']),
                            originalProcess=copy.deepcopy(origin['originalProcess']),
                            originalEngine=copy.deepcopy(origin['originalEngine']),engineHandleValue=9,
                            sourceMenu=copy.deepcopy(origin['sourceMenu']),pointUses=[])
                        offset=((.1,.1,3.3,6.5)[index] if field=='observations' else (3.2,6.4)[index])
                        item['startedAt']=origin['finishedAt']+offset
                        item['deadline']=item['startedAt']+5
                        item['finishedAt']=item['startedAt']+(3 if field=='observations' else .05)
                        if field=='fullscreenActions':item['nativeMenuOrigin']=copy.deepcopy(origin)
        legacy.save_report()
        return legacy,admission

    def verify(self,legacy,admission):
        verify=getattr(legacy.implementation(),'verify_source_qualified_native_menu_archive_completeness',None)
        self.assertTrue(callable(verify),'Separate actual-Gate source archive entry is missing')
        return verify(legacy.root,legacy.suite,admission=admission)

    def test_source_entry_rejects_saved_summary_or_boolean_authority_before_report_read(self):
        legacy=NativeMenuArchiveCompletenessTests(methodName='runTest')
        module=legacy.implementation()
        verify=getattr(module,'verify_source_qualified_native_menu_archive_completeness',None)
        self.assertTrue(callable(verify), 'Separate actual-Gate source archive entry is missing')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for invalid in (None,True,{},object()):
                with self.subTest(authority=type(invalid).__name__), self.assertRaises(ValueError):
                    verify(root,root,admission=invalid)

    def test_actual_gate_replays_global_source_actions_without_promoting_complete_suite_acceptance(self):
        legacy,admission=self.fixture()
        before=(legacy.root/REPORT).read_bytes()
        result=self.verify(legacy,admission)
        self.assertTrue(result['success']);self.assertIs(result['acceptanceEligible'],False)
        self.assertEqual((result['expectedGenerations'],result['matchedGenerations']),(6,6))
        self.assertEqual(result['nativePointProfileVersion'],4)
        self.assertEqual((legacy.root/REPORT).read_bytes(),before)
        with self.assertRaises(ValueError):legacy.verify()

    def test_full_archive_replays_five_distinct_new_worker4_sites_and_recorded_input_use(self):
        legacy,admission=self.fixture();action=self.local_action(legacy,admission)
        legacy.implementation()._action_profiles_v4(action,admission)
        try:result=self.verify(legacy,admission)
        except ValueError:
            self.fail('Actual source-aware public action replay did not accept five fresh worker4 sites')
        self.assertTrue(result['success'])
        points=[node['providerLocalProof'] for node in legacy.implementation()._nodes(action)
            if type(node) is dict and 'providerLocalProof' in node]
        scopes={}
        for proof in points:
            exact=(json.dumps(proof,sort_keys=True,allow_nan=False),
                json.dumps(proof['provider'],sort_keys=True,allow_nan=False))
            self.assertEqual(scopes.setdefault(proof['sourceScopeId'],exact),exact)
        self.assertEqual(sorted(scopes),[1,2,3,4,5])
        self.assertEqual([use['useCode'] for use in action['pointUses']],[1,1,2,1,2,3])

    def test_historical_local_points_replay_after_wall_clock_expiry_only_at_original_use_times(self):
        legacy,admission=self.fixture();self.local_action(legacy,admission)
        with patch.object(time,'monotonic',return_value=10**12):
            self.assertTrue(self.verify(legacy,admission)['success'])

    def test_full_archive_rejects_missing_copied_reordered_sites_and_invalid_recorded_consumption(self):
        legacy,admission=self.fixture();original=self.local_action(legacy,admission)
        self.verify(legacy,admission)
        for mutation in ('missing','copied','reordered','unobserved','expired-use','expired-current-input','before-capture',
                         'late-input','unused-scope','wrong-use-code','duplicate-use','missing-use',
                         'oversized-uses','oversized-action'):
            with self.subTest(mutation=mutation):
                action=copy.deepcopy(original);pointer=action['pointers'][-1]
                if mutation=='missing':del pointer['snapshots'][0]['targetPointProof']
                elif mutation=='copied':pointer['snapshots'][2]['targetPointProof']=copy.deepcopy(pointer['snapshots'][1]['targetPointProof'])
                elif mutation=='reordered':
                    first,last=pointer['snapshots'][0],pointer['snapshots'][1]
                    first['targetPointProof'],last['targetPointProof']=last['targetPointProof'],first['targetPointProof']
                elif mutation=='unobserved':action['orphanPoint']=copy.deepcopy(pointer['hits'][0])
                elif mutation=='expired-use':action['pointUses'][-1]['at']=pointer['hits'][-1]['providerLocalProof']['effectiveDeadline']
                elif mutation=='expired-current-input':
                    pointer['inputStartedAt']=action['deadline']-.1
                    pointer['inputFinishedAt']=action['deadline']-.09
                    action['pointUses'][-1]['at']=pointer['inputStartedAt']
                    action['finishedAt']=action['deadline']-.05
                elif mutation=='before-capture':pointer['hits'][0]['pointObservedAt']-=1
                elif mutation=='late-input':pointer['inputStartedAt']=action['finishedAt']+1
                elif mutation=='unused-scope':action['pointUses'][-1]['sourceScopeId']=31
                elif mutation=='wrong-use-code':action['pointUses'][-1]['useCode']=4
                elif mutation=='duplicate-use':action['pointUses'].append(copy.deepcopy(action['pointUses'][-1]))
                elif mutation=='oversized-uses':action['pointUses']=[copy.deepcopy(action['pointUses'][0]) for _ in range(129)]
                elif mutation=='oversized-action':action['unplannedPadding']='x'*(128*1024)
                else:action['pointUses'].pop()
                row=legacy.report['tests'][-1]
                row['nativeMenuActions'][-2]=copy.deepcopy(action);row['baseSaveMenuAction']=copy.deepcopy(action)
                legacy.save_report()
                with self.assertRaises(ValueError):self.verify(legacy,admission)

    def test_full_archive_rejects_missing_older_and_conflicting_final_worker_packets(self):
        legacy,admission=self.fixture();original=self.local_action(legacy,admission)
        self.verify(legacy,admission)
        for mutation in ('missing','older','different-copy','reused-source-id'):
            with self.subTest(mutation=mutation):
                action=copy.deepcopy(original);pointer=action['pointers'][-1]
                if mutation=='missing':del action['uiaInterop']['providerLocalResult']
                elif mutation=='older':action['uiaInterop']['providerLocalResult']=copy.deepcopy(pointer['hits'][0]['providerLocalProof']['provider'])
                elif mutation=='different-copy':action['otherDiagnostic']=dict(providerLocalResult=copy.deepcopy(pointer['hits'][0]['providerLocalProof']['provider']))
                else:
                    proof=pointer['hits'][-1]['providerLocalProof']
                    proof['sourceScopeId']=1;proof['sourceScope']['scope_id']=1;proof['provider']['scopeId']=1
                    proof['provider']['threadBirth']+=1
                    action['uiaInterop']['providerLocalResult']=copy.deepcopy(proof['provider'])
                row=legacy.report['tests'][-1]
                row['nativeMenuActions'][-2]=copy.deepcopy(action);row['baseSaveMenuAction']=copy.deepcopy(action)
                legacy.save_report()
                with self.assertRaises(ValueError):self.verify(legacy,admission)

    def test_report_case_and_action_summaries_cannot_replace_actual_source_identity(self):
        legacy,admission=self.fixture();original=copy.deepcopy(legacy.report)
        for site in ('report','case','action'):
            with self.subTest(site=site):
                legacy.report=copy.deepcopy(original)
                target=(legacy.report['sourceMenuAdmission'] if site=='report' else
                    legacy.report['tests'][0]['sourceMenuAdmission'] if site=='case' else
                    legacy.report['tests'][0]['nativeMenuActions'][0]['sourceMenu']['admission'])
                target['admissionSha256']='0'*64
                legacy.save_report()
                with self.assertRaises(ValueError):self.verify(legacy,admission)

    def test_source_report_case_profile_and_generation_downgrades_fail_closed(self):
        legacy,admission=self.fixture();original=copy.deepcopy(legacy.report)
        for site in ('report','case','action-generation','missing-source'):
            with self.subTest(site=site):
                legacy.report=copy.deepcopy(original);row=legacy.report['tests'][0]
                if site=='report':legacy.report['nativePointProfileVersion']=2
                elif site=='case':row['nativePointProfileVersion']=3
                elif site=='action-generation':row['nativeMenuActions'][0]['sourceMenu']['generation']['engineCreationTime']+=1
                else:del row['nativeMenuActions'][0]['sourceMenu']
                legacy.save_report()
                with self.assertRaises(ValueError):self.verify(legacy,admission)

    def test_actual_admission_suite_root_cannot_authorize_another_payload(self):
        legacy,admission=self.fixture()
        with self.assertRaises(ValueError):
            legacy.implementation().verify_source_qualified_native_menu_archive_completeness(
                legacy.root,legacy.root,admission=admission)

    def test_source_plan_rejects_reused_slots_and_missing_finish_even_with_matching_summary(self):
        legacy,admission=self.fixture();original=copy.deepcopy(legacy.report)
        for mutation in ('reuse-gesture','missing-finish','nested-only'):
            with self.subTest(mutation=mutation):
                legacy.report=copy.deepcopy(original);row=legacy.report['tests'][0]
                if mutation=='reuse-gesture':row['gestures'][3]['receipt']['receipt']=copy.deepcopy(row['nativeMenuActions'][0])
                elif mutation=='missing-finish':row['nativeMenuActions'].pop()
                else:row['nativeHwpLauncher']['menuAction']['sourceMenu']['generation']['shellHandleValue']+=1
                legacy.save_report()
                with self.assertRaises(ValueError):self.verify(legacy,admission)

    def test_report_and_case_source_summary_require_exact_closed_wire_types(self):
        legacy,admission=self.fixture();original=copy.deepcopy(legacy.report)
        for site in ('report','case'):
            for mutation in ('bool-schema','float-role','extra-field'):
                with self.subTest(site=site,mutation=mutation):
                    legacy.report=copy.deepcopy(original)
                    summary=(legacy.report if site=='report' else legacy.report['tests'][0])['sourceMenuAdmission']
                    if mutation=='bool-schema':summary['schemaVersion']=True
                    elif mutation=='float-role':summary['providers'][0]['role']=1.0
                    else:summary['unreviewed']=0
                    legacy.save_report()
                    with self.assertRaises(ValueError):self.verify(legacy,admission)

    def test_historical_archive_never_uses_current_clock_or_live_provider_rechecks(self):
        legacy,admission=self.fixture()
        with patch.object(time,'monotonic',side_effect=AssertionError('Historical replay queried current clock')), \
                patch.object(type(admission),'verify_provider_files',side_effect=AssertionError('Historical replay queried provider files')):
            self.assertTrue(self.verify(legacy,admission)['success'])

    def test_source_view_and_fullscreen_headers_join_actual_admission_generation_and_original_ledger(self):
        legacy,admission=self.fixture();self.verify(legacy,admission);original=copy.deepcopy(legacy.report)
        for field in ('observations','fullscreenActions'):
            for mutation in ('missing-header','wrong-source','wrong-generation','wrong-origin'):
                with self.subTest(field=field,mutation=mutation):
                    legacy.report=copy.deepcopy(original)
                    item=legacy.report['tests'][0]['nativeViewRoundtrip'][field][0]
                    if mutation=='missing-header':del item['sourceMenu']
                    elif mutation=='wrong-source':item['sourceMenu']['admission']['schemaVersion']=True
                    elif mutation=='wrong-generation':item['sourceMenu']['generation']['engineHandleValue']+=1
                    else:item['originIndex']=0
                    legacy.save_report()
                    with self.assertRaises(ValueError):self.verify(legacy,admission)

    def test_global_only_direct_view_receipts_reject_orphan_local_packets_and_points(self):
        legacy,admission=self.fixture();action=self.local_action(legacy,admission)
        self.verify(legacy,admission);original=copy.deepcopy(legacy.report)
        packet=action['uiaInterop']['providerLocalResult'];point=action['pointers'][-1]['hits'][-1]
        for module_index in (0,1):
            for field,count in (('observations',4),('fullscreenActions',2)):
                for index in range(count):
                    for payload in ('packet','point','raw-worker','bare-proof'):
                        with self.subTest(module=module_index,field=field,index=index,payload=payload):
                            legacy.report=copy.deepcopy(original)
                            item=legacy.report['tests'][module_index]['nativeViewRoundtrip'][field][index]
                            if payload=='packet':item['uiaInterop']=dict(providerLocalResult=copy.deepcopy(packet))
                            elif payload=='point':item['targetPointProof']=copy.deepcopy(point)
                            elif payload=='raw-worker':item['unjoined']=dict(rawWorker=copy.deepcopy(packet))
                            else:item['unjoined']=dict(rawProof=copy.deepcopy(point['providerLocalProof']))
                            legacy.save_report()
                            with self.assertRaises(ValueError):self.verify(legacy,admission)

    def test_direct_fullscreen_keeps_its_exact_validated_local_menu_origin(self):
        legacy,admission=self.fixture()
        action=self.local_action(legacy,admission,row_index=0,ledger_index=5,operation='printPreview')
        self.assertIn('providerLocalResult',action['uiaInterop'])
        self.assertTrue(self.verify(legacy,admission)['success'])

    def local_profile(self,admission):
        # Obtain a new4 result through the real Task2 adapter and fake native
        # SDK worker. No older packet is relabelled into a source candidate.
        from test_native_menu_point_profile import NativeSourceQualifiedPointV4Tests
        owner=NativeSourceQualifiedPointV4Tests(methodName='runTest')
        self.addCleanup(owner.doCleanups);owner.admission=admission
        fixture=owner.source_fixture();proof=owner.observe(fixture)
        scope=proof['scope'];binding=scope['binding'];position=proof['before']['point']
        point=dict(point=list(position),hitHwnd=proof['before']['hwnd'],rootHwnd=proof['before']['hwnd'],
            pid=binding['officePid'],pointMethod=proof['method'],providerLocalProof=proof,
            uiaMatches=False,withinControl=False,pointObservedAt=proof['capturedAt'])
        snapshot=dict(binding=copy.deepcopy(binding),identityProof=copy.deepcopy(proof['sourceFresh']),
            targetPointProof=point)
        action=dict(binding=copy.deepcopy(binding),originalProcess=dict(pid=scope['shellPid']),
            elementIdentityScope=copy.deepcopy(scope),pointers=[],observations=[snapshot],
            uiaInterop=dict(providerLocalResult=copy.deepcopy(proof['provider'])))
        return action

    def test_archive_profile_replays_a_new_worker4_and_keeps_raw_false_and_old_zeros(self):
        legacy,admission=self.fixture();action=self.local_profile(admission)
        legacy.implementation()._action_profiles_v4(action,admission)
        point=action['observations'][0]['targetPointProof'];packet=point['providerLocalProof']['provider']
        self.assertIs(point['uiaMatches'],False)
        self.assertEqual((packet['localKnown'],packet['localMatch'],packet['acceptanceEligible']),(0,0,0))

    def test_archive_profile_rejects_worker_cleanup_schema_digest_and_raw_comparison_mutations(self):
        legacy,admission=self.fixture();original=self.local_profile(admission)
        paths=[(('uiaMatches',),True),(('pointMethod',),'owned-popup-and-msaa-canonical-hit-v2'),
            (('providerLocalProof','schemaVersion'),3),(('providerLocalProof','finalPointVerified'),0),
            (('providerLocalProof','sourceAdmissionSha256'),'0'*64),
            (('providerLocalProof','globalPoint','nativeHwndRaw'),True),
            (('providerLocalProof','provider','workerSchemaVersion'),3),
            (('providerLocalProof','provider','admissionDigest0'),0),
            (('providerLocalProof','provider','workerCleanup'),0),
            (('providerLocalProof','provider','nativeExit'),0),
            (('providerLocalProof','provider','pending'),1),
            (('providerLocalProof','provider','referencesReleased'),25),
            (('providerLocalProof','provider','localKnown'),1)]
        for path,value in paths:
            with self.subTest(path=path):
                action=copy.deepcopy(original);node=action['observations'][0]['targetPointProof']
                for part in path[:-1]:node=node[part]
                node[path[-1]]=value
                with self.assertRaises((AssertionError,ValueError)):
                    legacy.implementation()._action_profiles_v4(action,admission)

    def test_archive_profile_requires_latest_packet_on_original_path_and_rejects_hidden_global_packet(self):
        legacy,admission=self.fixture();original=self.local_profile(admission)
        for mutation in ('missing','older','hidden','unjoined'):
            with self.subTest(mutation=mutation):
                action=copy.deepcopy(original)
                if mutation=='missing':del action['uiaInterop']['providerLocalResult']
                elif mutation=='older':action['uiaInterop']['providerLocalResult']['scopeId']+=1
                elif mutation=='hidden':action['hidden']=action.pop('uiaInterop')
                else:action['unjoined']=copy.deepcopy(action['observations'][0]['targetPointProof'])
                with self.assertRaises((AssertionError,ValueError)):
                    legacy.implementation()._action_profiles_v4(action,admission)
        action=dict(pointers=[],uiaInterop=copy.deepcopy(original['uiaInterop']))
        with self.assertRaises(ValueError):legacy.implementation()._action_profiles_v4(action,admission)


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
