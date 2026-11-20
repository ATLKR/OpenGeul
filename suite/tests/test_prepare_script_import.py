"""The standalone preparation entry point must keep the pinned x64 recipe."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT=Path(__file__).resolve().parents[2]
CHILD=r'''
import json,sys
from pathlib import Path
root=Path(sys.argv[1]);mode=sys.argv[2]
sys.path.insert(0,str(root if mode=='package' else root/'suite'))
if mode=='package':
    from suite import prepare,payload
else:
    assert str(root) not in sys.path
    import prepare,payload
assert Path(prepare.__file__).resolve()==root/'suite/prepare.py'
assert Path(payload.__file__).resolve()==root/'suite/payload.py'
manifest=json.loads((root/'suite/engine-build/source-build.26.8.2.2.json').read_bytes())
pins=prepare._source_new_x86_crt_pins(manifest)
assert pins==[dict(row) for row in payload.SOURCE_X86_COMPANION_CRT_PINS]
print(json.dumps({'passed':True,'pinCount':len(pins)}))
'''


class PrepareScriptImportTests(unittest.TestCase):
    def test_same_reviewed_pins_work_in_package_and_standalone_script_modes(self):
        environment={name:os.environ[name] for name in ('SystemRoot','WINDIR') if name in os.environ}
        environment.update(PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1')
        with tempfile.TemporaryDirectory() as temporary:
            for mode in ('package','script'):
                with self.subTest(mode=mode):
                    child=subprocess.run([sys.executable,'-I','-B','-c',CHILD,str(ROOT),mode],
                        cwd=temporary,env=environment,stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=15)
                    self.assertEqual(child.returncode,0,'Reviewed source pins must support the preparation script entry point')
                    self.assertEqual(json.loads(child.stdout),dict(passed=True,pinCount=2))

    def test_unrelated_missing_dependency_keeps_the_original_exception(self):
        import builtins
        from suite import prepare
        primary=ModuleNotFoundError('Synthetic missing dependency',name='synthetic_dependency')
        original=builtins.__import__
        def imports(name,*args,**kwargs):
            if name=='suite.payload':raise primary
            return original(name,*args,**kwargs)
        with mock.patch.object(builtins,'__import__',side_effect=imports):
            with self.assertRaises(ModuleNotFoundError) as observed:
                prepare._source_new_x86_crt_pins({})
        self.assertIs(observed.exception,primary)
