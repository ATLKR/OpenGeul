"""Synthetic source-only metadata; no Windows execution or servicing."""
from pathlib import Path
import copy
import hashlib
import importlib.util
import json
import os
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
MODULE=ROOT/'observation_contract.py'
if MODULE.is_file():
    spec=importlib.util.spec_from_file_location('observation_contract_under_test',MODULE)
    contract=importlib.util.module_from_spec(spec);spec.loader.exec_module(contract)
else:contract=None

FLAGS=('actualWindowsExecuted','qualification','canService','originalHelperHandleKnown',
       'controllerOwnershipKnown','durableLease','watchdogVerified','osImplicitEffectsKnown',
       'createdByThisRun','preexistingAdopted')
FILES=('observation_contract.py','context_observer.hpp','context_observer_windows.cpp')

def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()

def expected_data():
    return dict(schemaVersion=1,kind='source-only-packaged-context-expectation',
        packageFullName='OpenGeul_1.0.0.0_x64__synthetic',packageFamilyName='OpenGeul_synthetic',
        userSid='S-1-5-21-1000',architecture='x64',
        sourceRecipe=dict(formatVersion=1,identifier='org.allenlabs.opengeul',
            tauriConfigSha256='1'*64,webviewManagerSha256='2'*64,pathResolverSha256='3'*64,
            appDirectoriesOverride=None,dataDirectory=None),
        logicalPaths=dict(productLocalData=r'C:\Users\Synthetic\AppData\Local\org.allenlabs.opengeul',
                          productRoamingData=r'C:\Users\Synthetic\AppData\Roaming\org.allenlabs.opengeul'),
        clock=dict(startQpc=1000,phaseDeadlineQpc=10000,observerDeadlineQpc=2000,qpcFrequency=100),
        sourceBundleSha256='4'*64)

def observation(expected):
    source=expected.to_data();paths=source['logicalPaths']
    directories={}
    for i,(name,path) in enumerate((*paths.items(),('localState',r'C:\Users\Synthetic\AppData\Local\Packages\OpenGeul_synthetic\LocalState')),1):
        directories[name]=dict(logicalPath=path,finalPath=path,volumeSerial=0,fileId=f'{i:032x}',
            creationFileTime=100+i,desiredAccess=128,shareMode=7,openDisposition=3,reparse=False,
            handleRetainedDuringObservation=True,handleClosed=True)
    return dict(schemaVersion=1,kind='packaged-context-readonly-observation',observationComplete=True,
        failureCode=0,simulationOnly=True,**dict.fromkeys(FLAGS,False),
        requestSha256=expected.sha256,sourceBundleSha256=source['sourceBundleSha256'],
        package=dict(fullName=source['packageFullName'],familyName=source['packageFamilyName'],userSid=source['userSid'],
                     pid=123,createdFileTime=100,nativeMachine=34404 if source['architecture']=='x64' else 43620,processMachine=0),
        knownFolders=dict(localAppData=r'C:\Users\Synthetic\AppData\Local',roamingAppData=r'C:\Users\Synthetic\AppData\Roaming'),
        directories=directories,clock=dict(startedQpc=1001,finishedQpc=1999,deadlineQpc=2000,qpcFrequency=100),
        allDirectoryHandlesHeldTogether=True,processGenerationRechecked=True)


class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(contract,'Strict source-only observation contract is not implemented')

    def reject_expected(self,value):
        with self.assertRaises(contract.ContractError):contract.ExpectedObservation.from_data(value)

    def reject_record(self,value,expected=None):
        with self.assertRaises(contract.ContractError):contract.validate_observation(value,expected or self.expected)

    def make(self):
        self.expected=contract.ExpectedObservation.from_data(expected_data())
        return observation(self.expected)

    def test_expected_canonical_hash_and_original_input_are_isolated(self):
        raw=expected_data();expected=contract.ExpectedObservation.from_data(raw)
        self.assertEqual(expected.sha256,hashlib.sha256(canonical(raw)).hexdigest())
        raw['sourceRecipe']['identifier']='changed';exported=expected.to_data();exported['clock']['startQpc']=9
        self.assertEqual(expected.to_data(),expected_data())
        with self.assertRaises((AttributeError,TypeError)):expected.sha256='0'*64

    def test_expectation_schema_unknown_missing_and_bool_integers_reject(self):
        for key in expected_data():
            value=expected_data();value.pop(key)
            with self.subTest(missing=key):self.reject_expected(value)
        for change in ({'extra':1},{'schemaVersion':True},{'schemaVersion':2},{'kind':'phase-witness'},
                       {'sourceBundleSha256':'A'*64}):
            value=expected_data();value.update(change);self.reject_expected(value)

    def test_identifiers_sid_and_architecture_are_closed(self):
        cases=[('packageFullName',''),('packageFamilyName','x y'),('packageFullName','x'*257),
               ('packageFamilyName','한글'),('userSid','S-1-5-021'),('userSid','S-1-5-4294967296'),
               ('userSid','S-1-5'),('userSid','S-1-5-'+'-'.join(['1']*16)),('architecture','x86')]
        for key,value in cases:
            raw=expected_data();raw[key]=value
            with self.subTest(field=key):self.reject_expected(raw)

    def test_recipe_cannot_enable_overrides_or_change_identifier(self):
        for key,value in [('formatVersion',True),('identifier','another.product'),('tauriConfigSha256','a'*63),
                          ('webviewManagerSha256','A'*64),('appDirectoriesOverride',{}),('dataDirectory','C:\\other')]:
            raw=expected_data();raw['sourceRecipe'][key]=value;self.reject_expected(raw)
        raw=expected_data();raw['sourceRecipe']['unknown']=None;self.reject_expected(raw)

    def test_constant_strings_and_binding_digests_require_exact_string_types(self):
        class Text(str):pass
        raw=expected_data();raw['kind']=Text(raw['kind']);self.reject_expected(raw)
        raw=expected_data();raw['sourceRecipe']['identifier']=Text(raw['sourceRecipe']['identifier']);self.reject_expected(raw)
        original=self.make()
        for key in ('kind','requestSha256','sourceBundleSha256'):
            value=copy.deepcopy(original);value[key]=Text(value[key])
            with self.subTest(field=key):self.reject_record(value)

    def test_logical_windows_paths_reject_aliases_without_os_access(self):
        bad=[r'relative\app',r'C:relative',r'\\server\share\app',r'\\?\C:\app',r'\\.\C:\app',
             r'C:\a\..\app',r'C:\a\.\app',r'C:\a\\app',r'C:/a/app',r'C:\app:stream',
             'C:\\app ', 'C:\\app.',r'C:\NUL\app',r'C:\com1.txt\app','C:\\app\\',
             'C:\\app\x00value','C:\\'+('a'*1024)]
        for path in bad:
            raw=expected_data();raw['logicalPaths']['productLocalData']=path
            with self.subTest(path_case=bad.index(path)):self.reject_expected(raw)
        raw=expected_data();raw['logicalPaths']['productRoamingData']=raw['logicalPaths']['productLocalData'].swapcase()
        self.reject_expected(raw)

    def test_windows_path_limit_counts_utf16_units_and_rejects_surrogates(self):
        raw=expected_data();raw['logicalPaths']['productLocalData']='C:\\'+'😀'*511
        self.reject_expected(raw)  # 514 codepoints, 1025 native WCHAR units.
        raw=expected_data();raw['logicalPaths']['productLocalData']='C:\\'+'😀'*510
        self.assertEqual(contract.ExpectedObservation.from_data(raw).to_data(),raw)
        raw=expected_data();raw['logicalPaths']['productLocalData']='C:\\Synthetic\\\ud800'
        self.reject_expected(raw)

    def test_unicode_names_are_preserved_without_full_casefold_aliases(self):
        raw=expected_data();raw['logicalPaths']['productLocalData']=raw['logicalPaths']['productLocalData'].replace('Synthetic','Straße')
        self.expected=contract.ExpectedObservation.from_data(raw);record=observation(self.expected)
        record['knownFolders']['localAppData']=record['knownFolders']['localAppData'].replace('Synthetic','Strasse')
        self.reject_record(record)  # str.casefold incorrectly makes ß and ss equal.
        record['knownFolders']['localAppData']=record['knownFolders']['localAppData'].replace('Strasse','Straße')
        self.assertEqual(contract.validate_observation(record,self.expected),record)

    def test_expected_clock_uses_original_ninety_second_and_ten_second_windows(self):
        for key,value in [('startQpc',True),('startQpc',0),('qpcFrequency',0),('observerDeadlineQpc',1000),
                          ('observerDeadlineQpc',2001),('phaseDeadlineQpc',10001),('phaseDeadlineQpc',1999)]:
            raw=expected_data();raw['clock'][key]=value;self.reject_expected(raw)

    def test_valid_metadata_is_not_phase_or_native_authority(self):
        record=self.make();value=contract.validate_observation(record,self.expected)
        self.assertEqual(value,record)
        for name in FLAGS:self.assertIs(value[name],False)
        record['directories']['localState']['fileId']='f'*32
        self.assertNotEqual(value['directories']['localState']['fileId'],record['directories']['localState']['fileId'])
        for function,code in ((contract.as_phase_witness,'OBSERVATION_IS_NOT_PHASE_AUTHORITY'),
                              (contract.run_native,'OWNED_LAUNCH_AND_WATCHDOG_UNVERIFIED')):
            with self.assertRaises(contract.ContractError) as error:function(value,self.expected)
            self.assertEqual(str(error.exception),code)

    def test_success_schema_and_every_authority_flag_are_exact(self):
        original=self.make()
        for name in FLAGS:
            for bad in (True,0,None):
                record=copy.deepcopy(original);record[name]=bad
                with self.subTest(flag=name,value_type=type(bad).__name__):self.reject_record(record)
        for key in original:
            record=copy.deepcopy(original);record.pop(key);self.reject_record(record)
        for change in ({'schemaVersion':True},{'observationComplete':1},{'failureCode':False},
                       {'simulationOnly':0},{'unknown':0},{'kind':'phase-witness'}):
            record=copy.deepcopy(original);record.update(change);self.reject_record(record)
        record=copy.deepcopy(original);record['simulationOnly']=False
        self.assertEqual(contract.validate_observation(record,self.expected),record)

    def test_package_and_request_are_bound_to_independent_expectation(self):
        original=self.make()
        for field,value in [('fullName','Other'),('familyName','Other'),('userSid','S-1-5-21-1001'),
                            ('pid',True),('pid',0),('pid',2**32),('createdFileTime',0),
                            ('createdFileTime',2**64),('nativeMachine',43620),('processMachine',332)]:
            record=copy.deepcopy(original);record['package'][field]=value;self.reject_record(record)
        for field in ('requestSha256','sourceBundleSha256'):
            record=copy.deepcopy(original);record[field]='f'*64;self.reject_record(record)
        raw=expected_data();raw['architecture']='arm64';expected=contract.ExpectedObservation.from_data(raw)
        self.assertEqual(contract.validate_observation(observation(expected),expected)['package']['nativeMachine'],43620)

    def test_actual_known_folder_binding_and_final_paths_are_required(self):
        original=self.make()
        record=copy.deepcopy(original);record['knownFolders']['localAppData']=r'C:\Foreign';self.reject_record(record)
        record=copy.deepcopy(original);record['directories']['productRoamingData']['logicalPath']=r'C:\Foreign';self.reject_record(record)
        record=copy.deepcopy(original);record['directories']['productLocalData'].pop('finalPath');self.reject_record(record)
        record=copy.deepcopy(original);record['directories']['localState']['finalPath']=r'\\?\C:\x';self.reject_record(record)
        # A path observed through virtualization need not be the logical path.
        record=copy.deepcopy(original);record['directories']['productLocalData']['finalPath']=r'C:\Virtualized\ObservedProduct'
        record['directories']['productRoamingData']['logicalPath']=record['directories']['productRoamingData']['logicalPath'].swapcase()
        self.assertEqual(contract.validate_observation(record,self.expected),record)

    def test_directory_access_lifetime_identity_and_field_types_are_closed(self):
        original=self.make()
        cases=[('volumeSerial',True),('volumeSerial',-1),('volumeSerial',2**64),('fileId','0'*32),
               ('fileId','A'*32),('fileId','1'*31),('creationFileTime',0),('creationFileTime',2**64),
               ('desiredAccess',True),('desiredAccess',256),('shareMode',3),('openDisposition',4),
               ('reparse',True),('reparse',0),('handleRetainedDuringObservation',False),('handleClosed',False)]
        for key,value in cases:
            record=copy.deepcopy(original);record['directories']['localState'][key]=value
            with self.subTest(field=key):self.reject_record(record)
        record=copy.deepcopy(original);record['directories']['localState']['extra']=0;self.reject_record(record)
        record=copy.deepcopy(original);record['directories']['localState']['fileId']=record['directories']['productLocalData']['fileId'];self.reject_record(record)
        for key in ('allDirectoryHandlesHeldTogether','processGenerationRechecked'):
            record=copy.deepcopy(original);record[key]=1;self.reject_record(record)

    def test_record_clock_has_no_new_budget_or_late_success(self):
        original=self.make()
        for key,value in [('startedQpc',999),('finishedQpc',1000),('finishedQpc',2000),
                          ('deadlineQpc',2001),('qpcFrequency',101),('startedQpc',True)]:
            record=copy.deepcopy(original);record['clock'][key]=value;self.reject_record(record)

    def test_failure_shape_never_returns_success_or_partial_payload(self):
        self.make()
        record=dict(schemaVersion=1,kind='packaged-context-readonly-failure',failureCode=1,
                    observationComplete=False,simulationOnly=True,**dict.fromkeys(FLAGS,False))
        for code in (1,31):
            record['failureCode']=code
            with self.assertRaises(contract.ContractError) as error:contract.validate_observation(record,self.expected)
            self.assertEqual(str(error.exception),'OBSERVATION_INCOMPLETE')
        for change in ({'failureCode':0},{'failureCode':32},{'package':{}},{'logicalPath':r'C:\Synthetic'},
                       {'simulationOnly':0},{'qualification':True}):
            value=copy.deepcopy(record);value.update(change);self.reject_record(value)

    def test_contract_errors_do_not_include_observed_input(self):
        record=self.make();record['package']['fullName']='SYNTHETIC-PRIVATE-SENTINEL'
        with self.assertRaises(contract.ContractError) as error:contract.validate_observation(record,self.expected)
        self.assertNotIn('SYNTHETIC-PRIVATE-SENTINEL',str(error.exception))


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(contract,'Strict source bundle contract is not implemented')
        self.tmp=tempfile.TemporaryDirectory(prefix='opengeul-observation-');self.addCleanup(self.tmp.cleanup)
        self.parent=Path(self.tmp.name);self.root=self.parent/'bundle';self.root.mkdir()
        self.rows=[]
        for name in FILES:
            data=('synthetic source-only '+name+'\n').encode();(self.root/name).write_bytes(data)
            self.rows.append(dict(path=name,bytes=len(data),sha256=hashlib.sha256(data).hexdigest()))

    def raw(self,rows=None):
        return canonical(dict(schemaVersion=1,kind='packaged-context-source-bundle',files=self.rows if rows is None else rows))

    def validate(self,raw=None,*,root=None,expected=None):
        raw=self.raw() if raw is None else raw
        return contract.validate_bundle(root or self.root,raw,hashlib.sha256(raw).hexdigest(),expected_paths=FILES if expected is None else expected)

    def reject(self,**kwargs):
        with self.assertRaises(contract.ContractError):self.validate(**kwargs)

    def test_complete_external_hash_and_independent_file_set_are_required(self):
        self.assertEqual(self.validate(),json.loads(self.raw()))
        with self.assertRaises(TypeError):contract.validate_bundle(self.root,self.raw(),hashlib.sha256(self.raw()).hexdigest())
        with self.assertRaises(contract.ContractError):contract.validate_bundle(self.root,self.raw(),'0'*64,expected_paths=FILES)
        self.reject(expected=FILES[:-1]);self.reject(expected=(*FILES,'missing.cpp'))

    def test_manifest_shape_json_encoding_and_external_hash_reject(self):
        for raw in (b'{}',b'[]',b'not-json',b'\xef\xbb\xbf'+self.raw(),b'\xff',self.raw()+b'{}',
                    b'{"schemaVersion":1,"schemaVersion":1}',b'{"number":NaN}'):
            with self.subTest(shape_bytes=len(raw)):self.reject(raw=raw)
        for change in ({'schemaVersion':True},{'schemaVersion':2},{'kind':'qualified-runtime'},{'extra':0}):
            value=json.loads(self.raw());value.update(change);self.reject(raw=canonical(value))

    def test_total_source_bound_is_checked_before_any_filesystem_read(self):
        rows=[dict(path='source'+str(i)+'.cpp',bytes=512*1024,sha256='1'*64) for i in range(5)]
        with mock.patch.object(contract.os,'lstat',side_effect=AssertionError('Filesystem must not be read')) as observed:
            self.reject(raw=self.raw(rows),expected=tuple(r['path'] for r in rows))
        observed.assert_not_called()

    def test_rows_are_bounded_exact_case_and_cannot_escape(self):
        cases=[dict(path='../outside'),dict(path='/outside'),dict(path=r'a\b'),dict(path='a:b'),
               dict(path='./a'),dict(path='a//b'),dict(path='a/../b'),dict(path='AUX.txt'),
               dict(bytes=True),dict(bytes=0),dict(bytes=512*1024+1),dict(sha256='A'*64),dict(extra=1)]
        for change in cases:
            rows=copy.deepcopy(self.rows);rows[0].update(change)
            with self.subTest(keys=tuple(change)):self.reject(raw=self.raw(rows))
        rows=copy.deepcopy(self.rows);rows.append(dict(rows[0]));self.reject(raw=self.raw(rows))
        rows=copy.deepcopy(self.rows);rows.append(dict(rows[0],path=rows[0]['path'].upper()));self.reject(raw=self.raw(rows))
        self.reject(raw=self.raw([]));self.reject(raw=self.raw(self.rows*6))

    def test_hash_size_missing_extra_and_directory_aliases_are_observed(self):
        path=self.root/FILES[0];original=path.read_bytes();path.write_bytes(original+b'x');self.reject()
        path.write_bytes(b'x'*len(original));self.reject();path.write_bytes(original)
        path.unlink();self.reject();path.write_bytes(original)
        extra=self.root/'unlisted.cpp';extra.write_bytes(b'synthetic');self.reject();extra.unlink()
        extra=self.root/'empty-extra';extra.mkdir();self.reject();extra.rmdir()
        alias=self.root/FILES[0].upper();alias.write_bytes(original);self.reject()

    @unittest.skipUnless(hasattr(os,'symlink'),'symlink API unavailable')
    def test_member_and_parent_symlinks_cannot_supply_runtime_source(self):
        path=self.root/FILES[0];outside=self.parent/'outside-source';outside.write_bytes(path.read_bytes());path.unlink();path.symlink_to(outside)
        self.reject();path.unlink();path.write_bytes(outside.read_bytes())
        alias=self.parent/'aliased-root';alias.symlink_to(self.root,target_is_directory=True);self.reject(root=alias)

    @unittest.skipUnless(hasattr(os,'link'),'hardlink API unavailable')
    def test_hardlinked_source_is_rejected_even_when_bytes_match(self):
        os.link(self.root/FILES[0],self.parent/'second-link');self.reject()

    def test_in_place_change_during_read_cannot_pass_post_identity(self):
        read=os.read;changed=[];target=self.root/FILES[0]
        def racing(fd,count):
            data=read(fd,count)
            if data and not changed:
                changed.append(1);target.write_bytes(target.read_bytes()+b'changed')
            return data
        with mock.patch.object(contract.os,'read',side_effect=racing):self.reject()
        self.assertEqual(changed,[1])

    def test_bundle_failure_uses_closed_error_text(self):
        self.rows[0]['path']='SYNTHETIC-PRIVATE-SENTINEL'
        with self.assertRaises(contract.ContractError) as error:self.validate()
        self.assertNotIn('SYNTHETIC-PRIVATE-SENTINEL',str(error.exception))


if __name__=='__main__':unittest.main()
