"""Executed by the reconstructed candidate; no hashlib/OpenSSL oracle."""
import _sha2
import json
import os
import sys
import time
from pathlib import Path

vectors=json.loads(Path(sys.argv[1]).read_text())
constructors=[getattr(_sha2,n) for n in ['sha224','sha256','sha384','sha512']]
assert _sha2.__spec__.origin=='built-in'
assert all(c.__module__=='_sha2' for c in constructors)
for label,expected in vectors.items():
    data={'empty':b'','abc':b'abc','million-a':b'a'*1000000}.get(label)
    if data is None:data=b'a'*int(label.split('-')[1])
    for name,want in expected.items():
        make=getattr(_sha2,name)
        assert make(data).hexdigest()==want,(label,name,'oneshot')
        h=make()
        for i in range(0,len(data),37):h.update(data[i:i+37])
        assert h.hexdigest()==want,(label,name,'stream')
        cut=len(data)//2;h=make(data[:cut]);copied=h.copy()
        h.update(data[cut:]);copied.update(data[cut:])
        assert h.hexdigest()==copied.hexdigest()==want,(label,name,'copy')
proof={'executable':sys.executable,'dllHandle':sys.dllhandle,'pid':os.getpid(),'module':_sha2.__spec__.origin,'constructors':[c.__module__ for c in constructors],'testsPassed':True,'vectorCases':len(vectors)}
Path(sys.argv[2]).write_text(json.dumps(proof))
# Controller measures the actual live interpreter and loaded DLL before release.
for _ in range(600):
    if Path(sys.argv[3]).exists():break
    time.sleep(.1)
else:raise RuntimeError('Native identity observer did not release KAT')
print(json.dumps(proof))
