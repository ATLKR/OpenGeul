import json
import hashlib
import os
import stat
import struct
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'e2e'))

class ReleaseKitTests(unittest.TestCase):
    def api(self):
        path=Path(__file__).resolve().parents[1]/'scripts/releasekit.py'
        self.assertTrue(path.is_file(), 'Release policy and archive verification are not implemented')
        import releasekit
        return releasekit

    def test_release_policy_never_allows_pull_requests_or_other_repositories(self):
        k=self.api()
        self.assertFalse(k.release_allowed('ATLKR/OpenGeul','pull_request','refs/pull/2/merge'))
        self.assertFalse(k.release_allowed('other/OpenGeul','push','refs/heads/main'))
        self.assertFalse(k.release_allowed('ATLKR/OpenGeul','push','refs/heads/feature'))
        self.assertFalse(k.release_allowed('ATLKR/OpenGeul','pull_request_target','refs/heads/main'))
        self.assertTrue(k.release_allowed('ATLKR/OpenGeul','push','refs/heads/main'))
        self.assertTrue(k.release_allowed('ATLKR/OpenGeul','workflow_dispatch','refs/heads/main'))
        self.assertTrue(k.release_allowed('ATLKR/OpenGeul','push','refs/tags/v1.0.0'))
        self.assertFalse(k.release_allowed('ATLKR/OpenGeul','push','refs/tags/v1.0.0;echo pwn'))

    def test_release_tags_are_immutable_and_version_checked(self):
        k=self.api()
        self.assertEqual(k.release_tag('1.0.0','refs/heads/main','12','2'),'v1.0.0-dev.12.2')
        self.assertEqual(k.release_tag('1.0.0','refs/tags/v1.0.0','12','2'),'v1.0.0')
        for args in [('1.0.0','refs/tags/v9.0.0','1','1'),('1.0.0','refs/heads/main','xx','1')]:
            with self.assertRaises(ValueError): k.release_tag(*args)

    def test_packaged_msix_has_actual_pe_x64_editor_and_cli(self):
        k=self.api()
        from buildkit import manifest,DEV_IDENTITY
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'app.msix'
            pe=bytearray(256);pe[:2]=b'MZ';pe[60:64]=(128).to_bytes(4,'little');pe[128:132]=b'PE\x00\x00';pe[132:134]=(0x8664).to_bytes(2,'little')
            files={'AppxManifest.xml':manifest(DEV_IDENTITY,'1.0.0'),'OpenGeul.exe':bytes(pe),'Tools/rhwp.exe':bytes(pe),'[Content_Types].xml':'<Types/>','AppxBlockMap.xml':'<BlockMap/>','Notices/OpenGeul-LICENSE.txt':'MIT','Assets/StoreLogo.png':b'PNG'}
            with zipfile.ZipFile(p,'w') as z:
                for name,data in files.items(): z.writestr(name,data)
            result=k.verify_msix(p)
            self.assertTrue(result['unsigned']);self.assertEqual(result['architecture'],'x64')
            doc=ET.fromstring(files['AppxManifest.xml'])
            namespace='{http://schemas.microsoft.com/appx/manifest/foundation/windows10}'
            dependencies=doc.find(namespace+'Dependencies')
            for dep in dependencies.findall(namespace+'PackageDependency'): dependencies.remove(dep)
            files['AppxManifest.xml']=ET.tostring(doc,encoding='unicode')
            missing=Path(tmp)/'missing-runtime.msix'
            with zipfile.ZipFile(missing,'w') as z:
                for name,data in files.items(): z.writestr(name,data)
            with self.assertRaisesRegex(ValueError,'VCLibs'): k.verify_msix(missing)
            with zipfile.ZipFile(p,'a') as z:z.writestr('Fonts/hidden.dat',b'wOF2bad')
            with self.assertRaises(ValueError):k.verify_msix(p)

    def test_msix_rejects_traversal_and_wrong_architecture(self):
        k=self.api()
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'bad.msix'
            with zipfile.ZipFile(p,'w') as z:z.writestr('../escape','oops')
            with self.assertRaises(ValueError):k.verify_msix(p)
        with self.assertRaises(ValueError):k.pe_machine(b'MZnot really a binary')

    def _msix(self, path, extra=()):
        from buildkit import manifest, DEV_IDENTITY
        pe=bytearray(256);pe[:2]=b'MZ';struct.pack_into('<I',pe,60,128)
        pe[128:132]=b'PE\0\0';struct.pack_into('<H',pe,132,0x8664)
        files={'AppxManifest.xml':manifest(DEV_IDENTITY,'1.1.2'),
               'OpenGeul.exe':bytes(pe),'Tools/rhwp.exe':bytes(pe),
               '[Content_Types].xml':'<Types/>','AppxBlockMap.xml':'<BlockMap/>',
               'Notices/OpenGeul-LICENSE.txt':'MIT'}
        with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            for name,data in files.items():archive.writestr(name,data)
            for name,data in extra:archive.writestr(name,bytes(pe) if data is None else data)

    def _reject_before_member_read(self, path):
        opened=[];original=zipfile.ZipFile.open
        def observed(archive, member, *args, **kwargs):
            opened.append(member.filename if isinstance(member,zipfile.ZipInfo) else member)
            return original(archive,member,*args,**kwargs)
        with patch.object(zipfile.ZipFile,'open',observed),self.assertRaises(ValueError):
            self.api().verify_msix(path)
        self.assertEqual(opened,[], 'Unsafe ZIP metadata must be rejected before any member read')

    def test_msix_rejects_case_and_separator_aliases_before_member_reads(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'aliases.msix'
            for alias in ('tools/rhwp.exe','Tools\\rhwp.exe'):
                with self.subTest(alias=alias):
                    self._msix(path,[(alias,None)])
                    self._reject_before_member_read(path)

    def test_msix_expansion_caps_precede_member_reads(self):
        from prepare_payload import MAX_FILE, MAX_UNCOMPRESSED, MAX_MEMBERS
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'expanded.msix'
            for size in (MAX_FILE+1,MAX_UNCOMPRESSED+1):
                with self.subTest(declaredSize=size):
                    self._msix(path)
                    data=bytearray(path.read_bytes());position=0
                    while True:
                        offset=data.find(b'PK\x01\x02',position)
                        if offset<0:break
                        name,extra,comment=struct.unpack_from('<HHH',data,offset+28)
                        if data[offset+46:offset+46+name]==b'AppxManifest.xml':
                            struct.pack_into('<I',data,offset+24,size)
                        position=offset+46+name+extra+comment
                    path.write_bytes(data)
                    self._reject_before_member_read(path)
            self._msix(path,[(f'extra/{number}.txt',b'') for number in range(MAX_MEMBERS-5)])
            self._reject_before_member_read(path)

    def test_msix_unsafe_and_special_members_precede_member_reads(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'unsafe.msix'
            special=zipfile.ZipInfo('extra/link.txt');special.create_system=3
            special.external_attr=(stat.S_IFLNK|0o777)<<16
            for member in ('../escape.txt','extra/./dot.txt','CON.txt',special):
                with self.subTest(member=member.filename if isinstance(member,zipfile.ZipInfo) else member):
                    self._msix(path,[(member,b'unsafe')])
                    self._reject_before_member_read(path)

    def test_payload_allows_only_reviewed_cli_path(self):
        self.api()
        from buildkit import audit_payload
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'Tools').mkdir();(root/'Tools/rhwp.exe').write_bytes(b'MZ')
            audit_payload(root)
            (root/'Tools/secret.pfx').write_text('private')
            with self.assertRaises(ValueError):audit_payload(root)

    def test_canonical_owner_and_windows_byte_stability(self):
        self.api()
        root=Path(__file__).resolve().parents[1]
        self.assertEqual(json.loads((root/'config/product.json').read_text(encoding='utf-8'))['repository'],'ATLKR/OpenGeul')
        prep=(root/'scripts/prepare_upstream.py').read_text(encoding='utf-8')
        self.assertIn('core.autocrlf=false',prep)
        self.assertIn('--depth=1',prep)
        self.assertIn('test:studio',(root/'scripts/build-msix.ps1').read_text(encoding='utf-8'))
        self.assertNotIn('intentionally\n    # NOT represented as passing',(root/'scripts/build-msix.ps1').read_text(encoding='utf-8'))

    def test_release_retains_component_proof_and_rejects_mixed_package_bytes(self):
        k=self.api()
        from buildkit import manifest,DEV_IDENTITY
        env={'GITHUB_REPOSITORY':'ATLKR/OpenGeul','GITHUB_SHA':'a'*40,
             'GITHUB_RUN_ID':'123','GITHUB_RUN_ATTEMPT':'2'}
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);out=root/'dist';out.mkdir();source=root/'source';source.mkdir()
            (source/'.opengeul-overlay.json').write_text('{"ownedTestLedger":true}')
            pe=bytearray(256);pe[:2]=b'MZ';pe[60:64]=(128).to_bytes(4,'little')
            pe[128:132]=b'PE\x00\x00';pe[132:134]=(0x8664).to_bytes(2,'little')
            runtime=bytes(pe)
            with zipfile.ZipFile(out/'app.msix','w') as z:
                for name,data in {'AppxManifest.xml':manifest(DEV_IDENTITY,'1.1.2'),
                    'OpenGeul.exe':runtime,'Tools/rhwp.exe':runtime,'[Content_Types].xml':'<Types/>',
                    'AppxBlockMap.xml':'<BlockMap/>','Notices/OpenGeul-LICENSE.txt':'MIT'}.items():z.writestr(name,data)
            receipt={'formatVersion':1,'repository':env['GITHUB_REPOSITORY'],'commit':env['GITHUB_SHA'],
                'runId':'123','runAttempt':'2','sourceContractSha256':'b'*64,'components':{}}
            for role,name in [('editor','OpenGeul.exe'),('cli','Tools/rhwp.exe')]:
                receipt['components'][role]={'artifactName':f'opengeul-{role}-component-123',
                    'runAttempt':'1','provenanceSha256':'c'*64,'runtime':name,'size':len(runtime),
                    'sha256':hashlib.sha256(runtime).hexdigest()}
            path=source/'.opengeul-windows-components.json'
            with patch.dict(os.environ,env),self.assertRaisesRegex(ValueError,'requires Windows component proof'):
                k.finish(out,source,require_components=True)
            original=json.dumps(receipt)
            for change in ('runtimeHash','source','run','futureAttempt'):
                changed=json.loads(original)
                if change=='runtimeHash':changed['components']['cli']['sha256']='d'*64
                elif change=='source':changed['commit']='e'*40
                elif change=='run':changed['runId']='124'
                else:changed['components']['editor']['runAttempt']='3'
                path.write_text(json.dumps(changed))
                with self.subTest(change=change),patch.dict(os.environ,env),self.assertRaises(ValueError):
                    k.finish(out,source)
                self.assertFalse((out/'provenance.json').exists())
                self.assertFalse((out/'SHA256SUMS.txt').exists())
            path.write_text(original)
            with patch.dict(os.environ,env):k.finish(out,source)
            proof=json.loads((out/'provenance.json').read_text())
            self.assertEqual(proof['windowsComponents'],receipt)
            self.assertEqual(proof['sourceParity'],{'ownedTestLedger':True})
            self.assertIn('provenance.json',(out/'SHA256SUMS.txt').read_text())

if __name__=='__main__':unittest.main()
