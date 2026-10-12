import importlib.util
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

SPEC=importlib.util.spec_from_file_location('preflight_parallel',Path(__file__).resolve().parents[1]/'preflight_tests.py')
M=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(M)


class ParallelPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)

    def command(self,code): return [sys.executable,'-c',code]

    def run_suites(self,left,right,**bounds):
        return M.execute({'ci':self.command(left),'product':self.command(right)},self.root/'output',self.root,**bounds)

    def test_two_real_children_overlap_and_keep_original_utf8_crlf_bytes(self):
        def child(name,peer,payload):
            return f"from pathlib import Path;import time,sys;Path('{name}').touch();deadline=time.monotonic()+4\nwhile not Path('{peer}').exists():\n assert time.monotonic()<deadline;time.sleep(.01)\nsys.stdout.buffer.write({payload!r})"
        left='CI 한글\r\n'.encode();right='Product 한글\r\n'.encode()
        r=self.run_suites(child('ci-ready','product-ready',left),child('product-ready','ci-ready',right),timeout=5)
        self.assertTrue(r['passed']);self.assertEqual((self.root/'output/ci.log').read_bytes(),left)
        self.assertEqual((self.root/'output/product.log').read_bytes(),right)

    def test_one_failure_preserves_both_real_exit_codes_and_peer_output(self):
        r=self.run_suites("import sys;print('failed');sys.exit(23)","import time;time.sleep(.1);print('completed')",timeout=3)
        self.assertFalse(r['passed']);self.assertEqual(r['suiteStates']['ci']['exitCode'],23)
        self.assertEqual(r['suiteStates']['product']['exitCode'],0)
        self.assertIn(b'completed',(self.root/'output/product.log').read_bytes())

    def test_existing_directory_file_or_symlink_refused_before_children(self):
        code="from pathlib import Path;Path('started').touch()"
        for kind in ('directory','file','symlink'):
            path=self.root/kind
            if kind=='directory':path.mkdir()
            elif kind=='file':path.write_bytes(b'preserve')
            else:path.symlink_to(self.root/'missing')
            with self.assertRaises(ValueError):M.execute({'ci':self.command(code),'product':self.command(code)},path,self.root)
        self.assertFalse((self.root/'started').exists());self.assertEqual((self.root/'file').read_bytes(),b'preserve')

    def test_timeout_stops_owned_child_and_keeps_completed_peer_status(self):
        r=self.run_suites("import time;time.sleep(30)","print('normal peer')",timeout=.3)
        self.assertFalse(r['passed']);self.assertTrue(r['suiteStates']['ci']['timedOut'])
        self.assertIsNotNone(r['suiteStates']['ci']['exitCode']);self.assertEqual(r['suiteStates']['product']['exitCode'],0)

    def test_buffered_output_over_cap_cannot_pass_after_parent_exit_zero(self):
        r=self.run_suites("import sys;sys.stdout.buffer.write(b'x'*4097)","print('normal')",timeout=3,cap=4096)
        self.assertFalse(r['passed']);self.assertTrue(r['suiteStates']['ci']['logCapExceeded'])
        self.assertFalse(r['suiteStates']['ci']['logComplete']);self.assertEqual((self.root/'output/ci.log').read_bytes(),b'x'*4096)
        self.assertEqual(r['suiteStates']['product']['exitCode'],0)

    def test_exited_root_cannot_leave_stdout_descendant_or_mutable_receipt_log(self):
        grandchild="import os,signal,time;from pathlib import Path;signal.signal(signal.SIGTERM,signal.SIG_IGN);Path('grandchild.pid').write_text(str(os.getpid()));print('owned descendant',flush=True);time.sleep(30)"
        root=f"import subprocess,sys,time;from pathlib import Path;subprocess.Popen([sys.executable,'-c',{grandchild!r}]);deadline=time.monotonic()+3\nwhile not Path('grandchild.pid').exists():\n assert time.monotonic()<deadline;time.sleep(.01)\n"
        r=self.run_suites(root,"print('completed peer')",timeout=.5)
        self.assertFalse(r['passed']);self.assertEqual(r['suiteStates']['ci']['exitCode'],0)
        self.assertTrue(r['suiteStates']['ci']['timedOut']);self.assertFalse(r['suiteStates']['ci']['readError'])
        self.assertEqual(r['suiteStates']['product']['exitCode'],0)
        pid=int((self.root/'grandchild.pid').read_text());stat=Path(f'/proc/{pid}/stat')
        self.assertTrue(not stat.exists() or stat.read_text().split()[2]=='Z','Owned descendant is still running')
        log=self.root/'output/ci.log';before=log.read_bytes();time.sleep(.1)
        self.assertEqual(log.read_bytes(),before)
        self.assertEqual(M.hashlib.sha256(before).hexdigest(),r['suiteStates']['ci']['logSha256'])

    def test_short_raw_file_write_fails_with_actual_retained_prefix(self):
        original_open = Path.open
        class ShortWriter:
            def __init__(self,stream):self.stream=stream
            def __enter__(self):return self
            def __exit__(self,*args):self.stream.close()
            def write(self,data):return self.stream.write(data[:3])
        def fault(path,*args,**kwargs):
            stream=original_open(path,*args,**kwargs)
            return ShortWriter(stream) if path.name=='ci.log' and args and args[0]=='xb' else stream
        with patch.object(Path,'open',fault):
            r=self.run_suites("import sys;sys.stdout.buffer.write(b'original payload')","print('peer')",timeout=3)
        self.assertFalse(r['passed']);self.assertTrue(r['suiteStates']['ci']['readError'])
        self.assertFalse(r['suiteStates']['ci']['logComplete']);self.assertEqual(r['suiteStates']['ci']['bytesRetained'],3)
        self.assertEqual((self.root/'output/ci.log').read_bytes(),b'ori');self.assertEqual(r['suiteStates']['product']['exitCode'],0)


if __name__=='__main__':unittest.main()
