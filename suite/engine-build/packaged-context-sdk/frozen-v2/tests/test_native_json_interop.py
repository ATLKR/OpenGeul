"""Real portable C++ projection meets independent Python metadata only."""
from pathlib import Path
import hashlib,json,subprocess,sys,tempfile,time,unittest
BASE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(BASE))
import observation_contract as contract
FILES=('context_observer.hpp','context_observer_windows.cpp','observation_contract.py')
def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()
class NativeProjectionInteropTests(unittest.TestCase):
    def run_owned(self,args,*,stdout):
        child=subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=stdout,stderr=subprocess.DEVNULL,env={'PATH':'/usr/bin:/bin'},close_fds=True)
        self.children.append(child);end=time.monotonic()+20
        while child.poll() is None and time.monotonic()<end:time.sleep(.01)
        return child.returncode if child.poll() is not None else 124
    def test_compiled_simulation_json_and_actual_source_bundle_stay_unqualified(self):
        self.children=[];temporary=tempfile.TemporaryDirectory();root=Path(temporary.name)
        try:
            bundle=root/'runtime';bundle.mkdir();rows=[]
            for name in FILES:
                data=(BASE/name).read_bytes();(bundle/name).write_bytes(data)
                rows.append(dict(path=name,bytes=len(data),sha256=hashlib.sha256(data).hexdigest()))
            manifest=canonical(dict(schemaVersion=1,kind='packaged-context-source-bundle',files=rows));bundle_sha=hashlib.sha256(manifest).hexdigest()
            contract.validate_bundle(bundle,manifest,bundle_sha,expected_paths=FILES)
            value=dict(schemaVersion=1,kind='source-only-packaged-context-expectation',
                packageFullName='org.allenlabs.OpenGeul_1.2.3.4_x64__abcdefghijklm',packageFamilyName='org.allenlabs.OpenGeul_abcdefghijklm',
                userSid='S-1-5-21-100',architecture='x64',sourceRecipe=dict(formatVersion=1,identifier='org.allenlabs.opengeul',tauriConfigSha256='1'*64,webviewManagerSha256='2'*64,pathResolverSha256='3'*64,appDirectoriesOverride=None,dataDirectory=None),
                logicalPaths=dict(productLocalData=r'C:\owned\Local\org.allenlabs.opengeul',productRoamingData=r'C:\owned\Roaming\org.allenlabs.opengeul'),
                clock=dict(startQpc=100,phaseDeadlineQpc=90100,observerDeadlineQpc=10100,qpcFrequency=1000),sourceBundleSha256=bundle_sha)
            expected=contract.ExpectedObservation.from_data(value);exe=root/'projection'
            args=['/usr/bin/g++','-std=c++17','-Wall','-Wextra','-Werror','-pedantic','-DCORE_REQUEST_SHA="'+expected.sha256+'"','-DCORE_BUNDLE_SHA="'+bundle_sha+'"','-I',str(BASE),str(BASE/'tests/core_tests.cpp'),'-o',str(exe)]
            self.assertEqual(self.run_owned(args,stdout=subprocess.DEVNULL),0)
            packet=root/'synthetic-observation.json'
            with packet.open('xb') as stream:self.assertEqual(self.run_owned([str(exe),'30'],stdout=stream),0)
            self.assertLessEqual(packet.stat().st_size,65536);record=json.loads(packet.read_bytes());observed=contract.validate_observation(record,expected)
            self.assertIs(observed['simulationOnly'],True)
            for flag in contract.AUTHORITY_FLAGS:self.assertIs(observed[flag],False)
            with self.assertRaises(contract.ContractError):contract.as_phase_witness(observed)
            with self.assertRaises(contract.ContractError):contract.run_native(expected)
        finally:
            if not any(p.poll() is None for p in self.children):temporary.cleanup()
