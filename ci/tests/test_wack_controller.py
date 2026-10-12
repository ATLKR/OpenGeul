"""SDK 도움말 관측은 네이티브 소유 process만 받아들이고 WACK 합격을 뜻하지 않는다."""
from pathlib import Path
import importlib.util
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'e2e'))


class Process:
    pid=17
    _handle=27
    def __init__(self, code=0, timeout=False):
        self.returncode=None;self.code=code;self.timeout=timeout;self.killed=False
    def communicate(self,timeout):
        if self.timeout:raise subprocess.TimeoutExpired('stock-appcert',timeout)
        self.returncode=self.code
        return b'Windows App Certification Kit',None
    def poll(self):return self.returncode
    def kill(self):self.killed=True;self.returncode=-9
    def wait(self,timeout):return self.returncode


class WackControllerTests(unittest.TestCase):
    def setUp(self):
        self.path=ROOT/'e2e/wack-controller.py'
        self.assertTrue(self.path.is_file(),'stock SDK controller missing')
        spec=importlib.util.spec_from_file_location('wack_controller',self.path)
        self.module=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.module)
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.exe=Path(self.tmp.name)/'appcert.exe'
        raw=bytearray(256);raw[:2]=b'MZ';raw[60:64]=(128).to_bytes(4,'little');raw[128:132]=b'PE\0\0';raw[132:134]=(0x8664).to_bytes(2,'little')
        self.exe.write_bytes(raw)
        self.record={'processId':17,'imagePath':str(self.exe),'processMachine':0,'nativeMachine':0x8664}

    def observe(self,process,**changes):
        record=self.record|changes
        class Probe:
            def inspect(_,pid,handle):return record
        return self.module.observe(self.exe,probe=Probe(),process_factory=lambda *a,**k:process)

    def test_nonzero_help_completion_never_claims_wack_pass(self):
        record=self.observe(Process(-1))
        self.assertTrue(record['ordinaryExit']);self.assertEqual(record['helpExitCode'],-1)
        self.assertEqual(record['processMachine'],0);self.assertEqual(record['nativeMachine'],0x8664)
        self.assertNotIn('passed',record);self.assertNotIn('productQualified',record)

    def test_wrong_pid_path_or_emulation_is_rejected(self):
        for changes in ({'processId':18},{'imagePath':str(self.exe.parent/'other.exe')},
                        {'processMachine':0x8664},{'nativeMachine':0xAA64},
                        {'processMachine':False},{'nativeMachine':float(0x8664)}):
            process=Process()
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.observe(process,**changes)
            self.assertTrue(process.killed)

    def test_timeout_never_creates_success_record(self):
        process=Process(timeout=True)
        with self.assertRaises(subprocess.TimeoutExpired):self.observe(process)
        self.assertTrue(process.killed)

    def test_non_x64_tool_bytes_are_rejected_before_start(self):
        raw=bytearray(self.exe.read_bytes());raw[132:134]=(0xAA64).to_bytes(2,'little');self.exe.write_bytes(raw)
        called=[]
        with self.assertRaises(ValueError):
            self.module.observe(self.exe,process_factory=lambda *a,**k:called.append(a))
        self.assertEqual(called,[])


if __name__=='__main__':unittest.main()
