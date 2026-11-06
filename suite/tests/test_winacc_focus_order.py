"""Pinned WinAcc source order; portable semantics never qualify Windows UI."""
import difflib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
ENGINE=ROOT/'suite/engine-build'
FIXTURE=Path(__file__).parent/'fixtures/winacc-focus-order'
CORE='bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1'
ENV={'PATH':'/workspace/toolcache/opengeul-validation/powershell:/usr/bin:/bin',
    'XDG_CACHE_HOME':'/workspace/toolcache/opengeul-validation/cache',
    'XDG_CONFIG_HOME':'/workspace/toolcache/opengeul-validation/config',
    'XDG_DATA_HOME':'/workspace/toolcache/opengeul-validation/data','PYTHONUTF8':'1'}


def extract(raw,marker):
    """Reuse the scratch lexer; execute the pinned bodies, not a focus model."""
    assert raw.count(marker)==1
    at=raw.index(marker);start=raw.rfind('\n',0,at)+1
    i=raw.index('{',at);depth=0;state='code'
    while i<len(raw):
        char=raw[i];pair=raw[i:i+2]
        if state=='line':
            if char=='\n':state='code'
        elif state=='block':
            if pair=='*/':state='code';i+=1
        elif state in ('"',"'"):
            if char=='\\':i+=1
            elif char==state:state='code'
        elif pair=='//':state='line';i+=1
        elif pair=='/*':state='block';i+=1
        elif char in ('"',"'"):state=char
        elif char=='{':depth+=1
        elif char=='}':
            depth-=1
            if depth==0:
                end=i+1
                if raw[end:end+1]=='\n':end+=1
                return raw[start:end]
        i+=1
    raise AssertionError('Unterminated pinned method')


class WinAccFocusOrderTests(unittest.TestCase):
    def setUp(self):
        self.folder=Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.source=self.folder/'source';self.source.mkdir()
        self.evidence=self.folder/'evidence';self.evidence.mkdir()
        self.metadata=json.loads((FIXTURE/'source.json').read_text())
        for item in self.metadata['sources']:
            raw=(FIXTURE/item['fixture']).read_bytes()
            self.assertEqual(len(raw),item['bytes'])
            self.assertEqual(hashlib.sha256(raw).hexdigest(),item['sha256'])
            self.assertEqual(hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest(),item['gitBlob'])
            target=self.source/item['path'];target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)

    def pin(self):
        lock=json.loads((ENGINE/'source-build.json').read_text())
        self.assertTrue('winAccFocusOrder' in lock,'Missing exact WinAcc source-order pin')
        return lock['winAccFocusOrder']

    def installer(self):
        file=ENGINE/'apply_winacc_focus_order.py'
        self.assertTrue(file.is_file(),'Missing authenticated WinAcc source-order installer')
        spec=importlib.util.spec_from_file_location('winacc_focus_order_installer',file)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        return module

    def install(self):return self.installer().install(self.source,self.evidence,CORE)

    def test_exact_patch_and_lock_change_only_the_new_focus_call_order(self):
        pin=self.pin();self.assertEqual(pin['coreCommit'],CORE)
        self.assertEqual(pin['path'],'winaccessibility/source/service/AccObjectWinManager.cxx')
        self.assertFalse(pin['currentCiRootCauseConfirmed']);self.assertFalse(pin['nativeBuildVerified'])
        target=self.source/pin['path'];before=target.read_bytes()
        self.assertEqual(pin['beforeBytes'],len(before));self.assertEqual(pin['sha256'],hashlib.sha256(before).hexdigest())
        receipt=self.install();after=target.read_bytes()
        self.assertEqual(pin['afterBytes'],len(after));self.assertEqual(pin['afterSha256'],hashlib.sha256(after).hexdigest())
        old=b'        pAccObjNew->setFocus();\n';end=b'            pAccObjOld->unsetFocus();\n'
        self.assertEqual(before.replace(old,b'',1).replace(end,end+old,1),after)
        expected=''.join(difflib.unified_diff(before.decode().splitlines(True),after.decode().splitlines(True),
            fromfile='a/'+pin['path'],tofile='b/'+pin['path'])).encode()
        patch_bytes=(ENGINE/pin['patch']['filename']).read_bytes()
        self.assertEqual(expected,patch_bytes);self.assertEqual(hashlib.sha256(patch_bytes).hexdigest(),pin['patch']['sha256'])
        self.assertTrue(receipt['passed']);self.assertEqual(receipt['coreCommit'],CORE)
        self.assertEqual((self.evidence/'original-AccObjectWinManager.cxx').read_bytes(),before)
        self.assertEqual((self.evidence/'effective-AccObjectWinManager.cxx').read_bytes(),after)
        self.assertEqual((self.evidence/pin['patch']['filename']).read_bytes(),patch_bytes)
        for item in self.metadata['sources'][1:]:self.assertEqual((self.source/item['path']).read_bytes(),(FIXTURE/item['fixture']).read_bytes())

    def test_source_drift_repeat_and_wrong_core_reject_before_source_writes(self):
        pin=self.pin();module=self.installer();target=self.source/pin['path'];before=target.read_bytes()
        with self.assertRaises(ValueError):module.install(self.source,self.evidence,'0'*40)
        self.assertEqual(target.read_bytes(),before);self.assertEqual(list(self.evidence.iterdir()),[])
        for item in self.metadata['sources']:
            with self.subTest(source=item['path']):
                changed=self.source/item['path'];raw=changed.read_bytes();changed.write_bytes(raw+b'\n')
                with self.assertRaises(ValueError):module.install(self.source,self.evidence,CORE)
                self.assertEqual(changed.read_bytes(),raw+b'\n');self.assertEqual(list(self.evidence.iterdir()),[])
                changed.write_bytes(raw)
        module.install(self.source,self.evidence,CORE);after=target.read_bytes()
        with self.assertRaises(ValueError):module.install(self.source,self.evidence,CORE)
        self.assertEqual(target.read_bytes(),after)

    def test_evidence_collision_and_linked_source_are_rejected_without_write(self):
        pin=self.pin();module=self.installer();target=self.source/pin['path'];before=target.read_bytes()
        collision=self.evidence/'effective-AccObjectWinManager.cxx';collision.write_bytes(b'synthetic previous receipt')
        with self.assertRaises(ValueError):module.install(self.source,self.evidence,CORE)
        self.assertEqual(target.read_bytes(),before);self.assertEqual(collision.read_bytes(),b'synthetic previous receipt')
        collision.unlink();saved=target.with_name('owned-original.cxx');target.rename(saved)
        try:target.symlink_to(saved)
        except (OSError,NotImplementedError):self.skipTest('Local test filesystem cannot create a synthetic link')
        with self.assertRaises(ValueError):module.install(self.source,self.evidence,CORE)
        self.assertEqual(saved.read_bytes(),before);self.assertEqual(list(self.evidence.iterdir()),[])

    def test_patch_hash_and_payload_drift_are_rejected_before_source_write(self):
        pin=self.pin();module=self.installer();target=self.source/pin['path'];before=target.read_bytes()
        alternate=self.folder/'engine';alternate.mkdir()
        lock=json.loads((ENGINE/'source-build.json').read_text())
        payload=(ENGINE/pin['patch']['filename']).read_bytes()+b'\n'
        (alternate/pin['patch']['filename']).write_bytes(payload)
        for authenticated in (False,True):
            if authenticated:
                lock['winAccFocusOrder']['patch']['sha256']=hashlib.sha256(payload).hexdigest()
                lock['winAccFocusOrder']['patch']['size']=len(payload)
            (alternate/'source-build.json').write_text(json.dumps(lock))
            with patch.object(module,'HERE',alternate),self.assertRaises(ValueError):module.install(self.source,self.evidence,CORE)
            self.assertEqual(target.read_bytes(),before);self.assertEqual(list(self.evidence.iterdir()),[])

    def test_hardlinked_input_or_linked_source_ancestor_is_rejected_before_write(self):
        pin=self.pin();module=self.installer();target=self.source/pin['path'];before=target.read_bytes()
        saved=target.with_name('owned-original.cxx');target.rename(saved)
        try:os.link(saved,target)
        except (OSError,NotImplementedError):self.skipTest('Local filesystem cannot create a synthetic hardlink')
        with self.assertRaises(ValueError):module.install(self.source,self.evidence,CORE)
        self.assertEqual(target.read_bytes(),before);self.assertEqual(list(self.evidence.iterdir()),[])
        target.unlink();saved.rename(target)
        directory=target.parent;owned=directory.with_name('owned-service');directory.rename(owned)
        try:directory.symlink_to(owned,target_is_directory=True)
        except (OSError,NotImplementedError):self.skipTest('Local filesystem cannot create a synthetic directory link')
        with self.assertRaises(ValueError):module.install(self.source,self.evidence,CORE)
        self.assertEqual(target.read_bytes(),before);self.assertEqual(list(self.evidence.iterdir()),[])

    def test_lexical_source_alias_cannot_hide_evidence_inside_the_source(self):
        pin=self.pin();module=self.installer();target=self.source/pin['path'];before=target.read_bytes()
        anchor=self.folder/'anchor';anchor.mkdir()
        alias=anchor/'..'/'source'
        inside=self.source/'evidence';inside.mkdir()
        with self.assertRaises(ValueError):module.install(alias,inside,CORE)
        self.assertEqual(target.read_bytes(),before);self.assertEqual(list(inside.iterdir()),[])

    def test_exact_extracted_methods_original_red_candidate_green(self):
        self.pin()
        if os.name=='nt':self.skipTest('Portable Cygwin/GNU compiler regression; actual Windows engine build is separate')
        compiler=shutil.which('g++',path=ENV['PATH'])
        self.assertIsNotNone(compiler,'The mandatory portable source gate requires its installed GNU C++ compiler')
        out=self.folder/'compile';out.mkdir()
        for item in self.metadata['files']:
            raw=(FIXTURE/item['path']).read_bytes();self.assertEqual(len(raw),item['bytes'])
            self.assertEqual(hashlib.sha256(raw).hexdigest(),item['sha256']);(out/item['path']).write_bytes(raw)
        def methods(pristine):
            result=[]
            for item in self.metadata['methods']:
                path=self.source/item['source'];body=extract(path.read_text(),item['method']+'(')
                if pristine:self.assertEqual(hashlib.sha256(body.encode()).hexdigest(),item['bodySha256'])
                result.append('#line '+str(item['firstLine'])+' '+json.dumps(item['source'])+'\n'+body)
            return '\n'.join(result)
        (out/'extracted_methods.inc').write_text(methods(True))
        self.install();(out/'candidate_methods.inc').write_text(methods(False))
        for candidate in (False,True):
            binary=out/('candidate' if candidate else 'original')
            command=[compiler,'-std=c++20','-O2','-Wall','-Wextra','-Werror','-pedantic']
            if candidate:command.append('-DWINACC_CANDIDATE=1')
            command+=['harness.cpp','-o',str(binary)]
            compiled=self.capture(command,out,30);self.assertEqual(compiled[0],0,'Pinned source semantic compiler failed')
            self.assertEqual(compiled[1:],(b'',b''))
            code,stdout,stderr=self.capture([str(binary)],out,5);self.assertEqual(stderr,b'')
            rows=[json.loads(line) for line in stdout.decode().splitlines()];self.assertEqual(len(rows),11)
            self.assertEqual(rows[-1]['tests'],10);self.assertEqual(rows[-1]['actualWindows'],0)
            self.assertEqual(rows[-1]['nativeAbiVerified'],0)
            failed=[row['test'] for row in rows[:-1] if row['passed']==0]
            self.assertEqual(code,0 if candidate else 1)
            self.assertEqual(failed,[] if candidate else ['siblings_A_to_B_returns_B','deep_common_root_returns_new_leaf'])
            self.assertEqual(rows[-1]['passed'],10 if candidate else 8)

    def test_cli_installs_the_same_source_and_reports_only_source_qualification(self):
        pin=self.pin();command=[sys.executable,str(ENGINE/'apply_winacc_focus_order.py'),
            '--libreoffice-source',str(self.source),'--evidence-directory',str(self.evidence),'--core-commit',CORE]
        code,stdout,stderr=self.capture(command,self.folder,10)
        self.assertEqual(code,0);self.assertEqual(stderr,b'');value=json.loads(stdout)
        self.assertTrue(value['passed']);self.assertFalse(value['nativeBuildVerified'])
        self.assertFalse(value['guiVerified']);self.assertFalse(value['currentCiRootCauseConfirmed'])
        self.assertEqual(value['afterSha256'],pin['afterSha256']);self.assertEqual(len(value['sourceFiles']),3)

    def test_locked_unified_patch_applies_with_zero_fuzz_to_the_same_bytes(self):
        pin=self.pin()
        if os.name=='nt':self.skipTest('Portable GNU patch boundary; actual Windows source hook is separate')
        tool=shutil.which('patch',path=ENV['PATH'])
        self.assertIsNotNone(tool,'The mandatory portable source gate requires its installed patch tool')
        code,stdout,stderr=self.capture([tool,'--batch','--fuzz=0','-p1','-i',str(ENGINE/pin['patch']['filename'])],self.source,5)
        self.assertEqual(code,0);self.assertEqual(stderr,b'')
        self.assertEqual(hashlib.sha256((self.source/pin['path']).read_bytes()).hexdigest(),pin['afterSha256'])
        for item in self.metadata['sources'][1:]:self.assertEqual((self.source/item['path']).read_bytes(),(FIXTURE/item['fixture']).read_bytes())

    @staticmethod
    def capture(command,cwd,seconds):
        with tempfile.TemporaryFile(dir=cwd) as stdout,tempfile.TemporaryFile(dir=cwd) as stderr:
            process=subprocess.Popen(command,cwd=cwd,env=ENV,stdout=stdout,stderr=stderr,start_new_session=True)
            try:code=process.wait(timeout=seconds)
            except subprocess.TimeoutExpired:
                if os.name=='nt':process.kill()  # The CLI child has no descendants.
                else:os.killpg(process.pid,signal.SIGKILL)
                process.wait(timeout=3);raise
            stdout.seek(0);out=stdout.read(1024*1024+1);stderr.seek(0);err=stderr.read(1024*1024+1)
        assert len(out)<=1024*1024 and len(err)<=1024*1024
        return code,out,err


if __name__=='__main__':unittest.main()
