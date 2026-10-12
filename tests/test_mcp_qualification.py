"""설치 MCP 증명의 구조·현재 소스·실제 제품 신원 연결을 합성 fixture로 검증한다."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
try:
    import mcp_qualification as qualification
except ModuleNotFoundError:
    qualification = None

CASE_NAMES = ['initialize','ping','tools-list','normal-read','normal-write','ir-diff-code3','batch-partial-code1',
    *['malformed-paths-'+str(n) for n in range(4)],
    *['password-'+f+'-'+mode for f in ('hwp','hwpx') for mode in ('missing','wrong','correct')]]
CASE_IDS = [1,2,3,4,5,6,7,8,10,12,14,16,17,18,19,20,21]


def installed_proof(architecture='x64', cli_sha256='c'*64, package_full_name=None,
                    source_commit='a'*40, source_run='1234', run_attempt='2', cli_bytes=259):
    """테스트 전용 데이터 생성. production verifier를 대체하거나 mock하지 않는다."""
    package_full_name = package_full_name or f'AllenLabs.OpenGeul.Development_1.1.3.0_{architecture}__9za217j1njc2t'
    path = f'C:\\Program Files\\WindowsApps\\{package_full_name}\\Tools\\rhwp.exe'
    machine = {'x64':0x8664,'arm64':0xaa64}[architecture]
    binding = {'sourceCommit':source_commit,'sourceRun':source_run,'runAttempt':run_attempt}
    native_helper = hashlib.sha256((ROOT/'e2e/native_architecture.py').read_bytes()).hexdigest()
    server = {'architecture':architecture,'processId':100,'imagePath':path,'peMachine':machine,'processMachine':0,
        'nativeMachine':machine,'native':True,'runningAtInspection':True,'packageFullName':package_full_name,
        'sha256':cli_sha256,'bytes':cli_bytes,'createdFileTime':10000,'helperSha256':native_helper,**binding,
        'controller':{'processId':10,'processMachine':0,'architecture':architecture,'native':True}}
    worker = {**{key:server[key] for key in ('architecture','imagePath','peMachine','processMachine','nativeMachine',
        'native','packageFullName','sha256','sourceCommit','sourceRun','runAttempt')},'processId':101,'createdFileTime':10001,
        'classId':'c6c4d247-b4f0-563d-a649-4765796e3164',
        'binding':'실제 경로·바이트·생성 시각·고정 bootstrap; SCM ancestry를 사용하지 않음'}
    checks = [{'protocolPassed':True},{'passed':True},{'toolsListed':5,'requiredToolsPresent':True},
        {'sourceTextMatched':True},{'independentXmlPassed':True,'sourceUnchanged':True,'replacedCount':1},
        {'cliExitCode':3,'sameJson':True},{'cliExitCode':1,'records':2,'sameNdjson':True},
        *[{'rejected':True,'serverResponsive':True} for _ in range(4)],
        *[{'expectedResultPassed':True,'ciphertextUnchanged':True} for _ in range(6)]]
    def response(name, request_id, values):
        raw = json.dumps({'jsonrpc':'2.0','id':request_id,'result':{'syntheticCase':name}},sort_keys=True).encode()
        return {'name':name,'requestId':request_id,'responseSha256':hashlib.sha256(raw).hexdigest(),
            'responseBytes':len(raw),'checks':values}
    cases = [response(name,request_id,values) for name,request_id,values in zip(CASE_NAMES,CASE_IDS,checks)]
    return {'formatVersion':1,'cases':cases,'caseCount':17,**binding,'architecture':architecture,'context':'installed',
        'productSha256':cli_sha256,'helperSha256':hashlib.sha256((ROOT/'e2e/mcp_worker.py').read_bytes()).hexdigest(),
        'nativeArchitectureHelperSha256':native_helper,'fullSourceQualified':False,'storeCertified':False,'passed':True,
        'scope':'실제 MCP stdio·합성 문서·native COM worker; 전체 도구·개인 문서·Store 인증을 주장하지 않음',
        'limits':{'frameBytes':2*1024*1024,'runtimeBytes':96*1024*1024,'requestTimeoutSeconds':30},
        'serverNativeArchitecture':server,'phase':'hwp_export_text','lastCompletedCase':'password-hwpx-correct',
        'stressFixture':{'sha256':'d'*64,'bytes':5000,'addedSyntheticParagraphs':1500,
            'scope':'원본·인쇄 기준과 별개의 작업자 강제 종료용 합성 복사본'},
        'workerIsolation':{'worker':worker,'sameServerAlive':True,'forcedTermination':False,'batchRecords':64,
            'response':response('installed-worker-batch64',22,{'records':64,'passed':True}),
            'scope':'설치 fixed COM class의 native/package identity 관측; 공유 process 강제 종료 없음'},
        'framesSent':23,'framesReceived':22}


class McpQualificationTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(qualification, '설치 MCP 증명 공통 validator가 필요합니다')
        self.proof = installed_proof()
        self.expected = ('x64','c'*64,self.proof['serverNativeArchitecture']['packageFullName'],'a'*40,'1234','2')

    def verify(self, proof=None): return qualification.verify(self.proof if proof is None else proof,*self.expected)
    def rejected(self, change):
        value = copy.deepcopy(self.proof);change(value)
        with self.assertRaises(ValueError):self.verify(value)

    def test_complete_installed_proof_preserves_input_and_returns_same_object(self):
        before = copy.deepcopy(self.proof);self.assertIs(self.verify(),self.proof);self.assertEqual(self.proof,before)

    def test_native_arm64_product_with_x64_controller_is_allowed(self):
        p = installed_proof('arm64');p['serverNativeArchitecture']['controller'].update(processMachine=0x8664,architecture='x64-emulated',native=False)
        self.assertIs(qualification.verify(p,'arm64','c'*64,p['serverNativeArchitecture']['packageFullName'],'a'*40,'1234','2'),p)

    def test_missing_duplicate_or_reordered_cases_and_request_ids_are_rejected(self):
        for change in (lambda p:p['cases'].pop(),lambda p:p['cases'].__setitem__(3,copy.deepcopy(p['cases'][2])),
            lambda p:p['cases'].reverse(),lambda p:p['cases'][8].update(requestId=8),
            lambda p:p['cases'][0].update(requestId=True)):
            with self.subTest(change=change):self.rejected(change)

    def test_any_false_or_wrong_typed_case_assertion_is_rejected(self):
        for index,field,value in ((0,'protocolPassed',1),(3,'sourceTextMatched',False),(4,'replacedCount',True),
            (5,'cliExitCode',0),(6,'records',1),(7,'serverResponsive',False),(11,'ciphertextUnchanged',False)):
            with self.subTest(index=index):self.rejected(lambda p:p['cases'][index]['checks'].update({field:value}))

    def test_current_helper_source_run_attempt_and_product_hash_are_required(self):
        for field,value in [('helperSha256','0'*64),('nativeArchitectureHelperSha256','0'*64),('sourceCommit','b'*40),
            ('sourceRun','999'),('runAttempt','1'),('productSha256','0'*64),('context','portable')]:
            with self.subTest(field=field):self.rejected(lambda p:p.update({field:value}))

    def test_parent_and_worker_pid_time_native_machine_image_and_package_are_bound(self):
        for object_name,field,value in [('serverNativeArchitecture','processId',True),('serverNativeArchitecture','createdFileTime',0),
            ('serverNativeArchitecture','runningAtInspection',False),('serverNativeArchitecture','processMachine',0x8664),
            ('serverNativeArchitecture','helperSha256','0'*64),('serverNativeArchitecture','bytes',True),
            ('worker','processId',100),('worker','createdFileTime',9999),('worker','nativeMachine',0xaa64),
            ('worker','imagePath','C:\\outside\\Tools\\rhwp.exe'),('worker','sha256','0'*64),('worker','sourceRun','999'),
            ('worker','packageFullName','other'),('worker','classId','00000000-0000-0000-0000-000000000000')]:
            with self.subTest(object_name=object_name,field=field):
                def change(p):
                    target = p['workerIsolation']['worker'] if object_name=='worker' else p[object_name]
                    target[field]=value
                self.rejected(change)

    def test_installed_batch64_response_alive_server_and_no_force_are_required(self):
        for change in (lambda p:p['workerIsolation'].update(batchRecords=63),lambda p:p['workerIsolation'].update(forcedTermination=True),
            lambda p:p['workerIsolation'].update(sameServerAlive=False),lambda p:p['workerIsolation']['response'].update(requestId=21),
            lambda p:p['workerIsolation']['response']['checks'].update(records=63)):
            with self.subTest(change=change):self.rejected(change)

    def test_bounded_hash_sizes_counts_and_runtime_only_qualification_are_strict(self):
        for change in (lambda p:p.update(caseCount=True),lambda p:p.update(framesReceived=21),
            lambda p:p.update(fullSourceQualified=True),lambda p:p.update(storeCertified=True),lambda p:p.update(passed=1),
            lambda p:p['cases'][0].update(responseSha256='not-a-hash'),lambda p:p['cases'][0].update(responseBytes=0),
            lambda p:p['cases'][0].update(responseBytes=2*1024*1024+1),lambda p:p['limits'].update(requestTimeoutSeconds=30.0)):
            with self.subTest(change=change):self.rejected(change)

    def test_raw_request_password_environment_and_unknown_fields_are_rejected(self):
        for change in (lambda p:p.update(password='synthetic-secret'),lambda p:p['cases'][0].update(request={'path':'private'}),
            lambda p:p['workerIsolation']['worker'].update(argv=['secret']),lambda p:p['workerIsolation'].update(environment='private')):
            with self.subTest(change=change):self.rejected(change)

    def test_receipt_reader_refuses_duplicate_nonfinite_non_utf8_and_oversize(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'receipt.json'
            for raw in (b'{"passed":true,"passed":true}',b'{"number":NaN}',b'\xff',
                    b' '*(qualification.RECEIPT_CAP+1),b'\xef\xbb\xbf{}'):
                with self.subTest(raw=raw[:20]):
                    path.write_bytes(raw)
                    with self.assertRaises(ValueError):qualification.read_receipt(path)

    def test_expected_source_architecture_hash_and_package_parameters_are_strict(self):
        for index,value in ((0,'neutral'),(1,'C'*64),(2,'Other_65536.1.3.0_x64__9za217j1njc2t'),
                (2,'Other_01.1.3.0_x64__9za217j1njc2t'),(2,self.expected[2].replace('_x64_','_arm64_')),
                (3,'A'*40),(4,'01234'),(5,True)):
            with self.subTest(index=index,value=value):
                args=list(self.expected);args[index]=value
                with self.assertRaises(ValueError):qualification.verify(self.proof,*args)

    def test_false_controller_native_or_aliased_process_pid_is_rejected(self):
        for change in (lambda p:p['serverNativeArchitecture']['controller'].update(native=1),
                lambda p:p['serverNativeArchitecture']['controller'].update(processMachine=0x8664),
                lambda p:p['workerIsolation']['worker'].update(processId=10),
                lambda p:p['workerIsolation']['worker'].update(imagePath='C:\\outside\\..\\'+self.expected[2]+'\\Tools\\rhwp.exe')):
            with self.subTest(change=change):self.rejected(change)

    def test_cli_uses_current_execution_and_refuses_stale_receipt_without_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'receipt.json';path.write_text(json.dumps(self.proof),encoding='utf-8');before=path.read_bytes()
            env={**os.environ,'GITHUB_SHA':'a'*40,'GITHUB_RUN_ID':'1234','GITHUB_RUN_ATTEMPT':'2'}
            cmd=[sys.executable,str(ROOT/'scripts/mcp_qualification.py'),'--receipt',str(path),'--architecture','x64',
                '--cli-sha256','c'*64,'--package-full-name',self.expected[2]]
            good=subprocess.run(cmd,env=env,capture_output=True,text=True);self.assertEqual(good.returncode,0,good.stderr)
            env['GITHUB_RUN_ATTEMPT']='1';bad=subprocess.run(cmd,env=env,capture_output=True,text=True)
            self.assertNotEqual(bad.returncode,0);self.assertNotIn('synthetic-secret',bad.stderr);self.assertEqual(path.read_bytes(),before)


if __name__=='__main__':unittest.main()
