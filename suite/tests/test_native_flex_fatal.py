"""Strict source-only Flex fatal compatibility; no native qualification."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
ENGINE=ROOT/'suite/engine-build'
FIXTURE=ROOT/'suite/tests/fixtures/native-flex-fatal'
CORE='9dea406ab7695df6325b11b0e19fdca8db4b7276'
PATH='connectivity/source/parse/sqlflex.l'
BEFORE_SHA='87e66cc9306322ca97c2e4ccbb41b0960fb8857aee4e536bf051c043ebf6c11a'
AFTER_SHA='f0890c54e65b52ac31a37a99b20a17fb9e9282985f25fa99ba4718490975200c'
PIN=dict(path=PATH,size=37027,sha256=BEFORE_SHA,afterSize=37161,afterSha256=AFTER_SHA,condition='WNT')
QUALIFICATION=('nativeBuildVerified','fullEngineQualified','acceptanceEligible','guiVerified')
LEGACY=b'    if ((0)) yy_fatal_error(msg);\n'
GUARD=b'#if YY_FLEX_MAJOR_VERSION == 2 && YY_FLEX_MINOR_VERSION == 6 && YY_FLEX_SUBMINOR_VERSION == 5\n'


def sha(raw):return hashlib.sha256(raw).hexdigest()


def load():
    path=ENGINE/'apply_native_source.py'
    spec=importlib.util.spec_from_file_location('native_flex_fatal_source',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


class NativeFlexFatalTests(unittest.TestCase):
    def setUp(self):
        self.module=load();self.original=(FIXTURE/'sqlflex.l').read_bytes()
        self.temp=tempfile.TemporaryDirectory(prefix='native-flex-fatal-')
        self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)

    def source(self,name='owned'):
        source=self.root/name/'source';target=source/PATH
        target.parent.mkdir(parents=True);target.write_bytes(self.original)
        evidence=self.root/name/'evidence';evidence.mkdir()
        return source,evidence,target

    def snapshot(self):
        result={}
        for path in self.root.rglob('*'):
            key=str(path.relative_to(self.root))
            if path.is_symlink():result[key]=('link',str(path.readlink()))
            elif path.is_file():
                raw=path.read_bytes();result[key]=('file',len(raw),sha(raw))
            elif path.is_dir():result[key]=('directory',)
        return result

    def rejects_without_writes(self,source,evidence,pin=PIN,architecture='arm64'):
        before=self.snapshot()
        with self.assertRaises((ValueError,FileNotFoundError)):
            self.module._install_flex_fatal_compat(source,evidence,pin,architecture)
        self.assertTrue(self.snapshot()==before,'Rejected installation changed source or evidence')

    def malformed_pins(self):
        for key in PIN:
            pin=dict(PIN);pin.pop(key);yield 'missing-'+key,pin
            wrong=('wrong-'+PIN[key]) if type(PIN[key]) is str else PIN[key]+1
            for label,value in [('wrong',wrong),('boolean',True),('float',1.5),('array',[PIN[key]])]:
                pin=dict(PIN);pin[key]=value;yield label+'-'+key,pin
        for key in ('size','afterSize'):
            pin=dict(PIN);pin[key]=float(PIN[key]);yield 'same-value-float-'+key,pin
        for key in ('sha256','afterSha256'):
            pin=dict(PIN);pin[key]=PIN[key].upper();yield 'uppercase-'+key,pin
        pin=dict(PIN);pin['unknown']=False;yield 'unknown',pin
        for label,value in [('null',None),('array',list(PIN)),('boolean',True)]:yield label,value

    def test_source_manifest_and_helper_are_present(self):
        lock=json.loads((ENGINE/'source-build.json').read_bytes());module=self.module
        self.assertTrue('flexFatalCompatibility' in lock,'Missing closed Flex fatal source contract')
        self.assertEqual(lock['flexFatalCompatibility'],PIN)
        self.assertEqual(getattr(module,'FLEX_PATH',None),'connectivity/source/parse/sqlflex.l')
        self.assertTrue(callable(getattr(module,'_flex_fatal_bytes',None)))
        self.assertTrue(callable(getattr(module,'_install_flex_fatal_compat',None)))
        driver=(ROOT/'suite/scripts/build-native-engine.ps1').read_text()
        calls=re.findall(r"(?m)^\s*Invoke-LoggedCommand \$python @\(([^)\r\n]+)\).*?\(Join-Path \$evidence 'source-recipe-tests'\)",driver)
        self.assertEqual(1,len(calls),'The common producer source unit caller is ambiguous')
        self.assertEqual(['-m','unittest','suite.tests.test_native_source_recipe',
                          'suite.tests.test_native_flex_fatal','-v'],re.findall(r"'([^']*)'",calls[0]))

    def test_fixture_has_exact_public_source_and_independent_candidate_pins(self):
        metadata=json.loads((FIXTURE/'source.json').read_bytes())
        source=metadata['source'];after=metadata['candidateAfter']
        self.assertEqual((source['repository'],source['coreCommit'],source['path']),('LibreOffice/core',CORE,PATH))
        self.assertEqual(source['url'],f'https://github.com/LibreOffice/core/blob/{CORE}/{PATH}')
        self.assertEqual((len(self.original),sha(self.original)),(37027,BEFORE_SHA))
        self.assertEqual((source['bytes'],source['sha256']),(37027,BEFORE_SHA))
        self.assertEqual((after['bytes'],after['sha256']),(37161,AFTER_SHA))
        self.assertEqual(after['patchSha256'],'52e5102c3c6950379c342eb7e36a0f55d96f4c2aad871b0445e2f55c73710f9c')

    def test_exact_265_dead_reference_preserves_active_error_hook_and_legacy_else(self):
        original=bytes(self.original);pin=copy.deepcopy(PIN)
        after=self.module._flex_fatal_bytes(original,pin)
        self.assertIs(type(after),bytes)
        self.assertEqual((len(after),sha(after)),(37161,AFTER_SHA))
        self.assertEqual((self.original,pin),(original,PIN))
        branch=GUARD+b'    if ((0)) yypanic(msg);\n#else\n'+LEGACY+b'#endif\n'
        self.assertEqual(after.count(branch),1)
        self.assertEqual((after.count(GUARD),after.count(b'if ((0)) yypanic(msg);'),after.count(LEGACY)),(1,1,1))
        marker=b'#define YY_FATAL_ERROR(msg)'
        self.assertTrue(original[original.index(marker):]==after[after.index(marker):],
                        'Active fatal macro or later lexer source changed')
        callback=b'    xxx_pGLOBAL_SQLSCAN->SQLyyerror(msg);\n'
        self.assertEqual((original.count(callback),after.count(callback)),(1,1))
        self.assertTrue(original.replace(LEGACY,branch,1)==after,'Compatibility port changed other source bytes')

    def test_all_closed_pin_mutations_fail_purely_and_installer_writes_nothing(self):
        source,evidence,_=self.source()
        for label,pin in self.malformed_pins():
            with self.subTest(pin=label):
                with self.assertRaises(ValueError):self.module._flex_fatal_bytes(self.original,pin)
                self.rejects_without_writes(source,evidence,pin)

    def test_changed_repeated_duplicated_and_oversized_source_fail_without_writes(self):
        after=self.module._flex_fatal_bytes(self.original,PIN)
        inputs={'same-size-byte-drift':bytes([self.original[0]^1])+self.original[1:],
                'reapplication':after,'duplicate-anchor':self.original.replace(LEGACY,LEGACY+LEGACY,1),
                'duplicate-source':self.original+self.original,'oversized':b'x'*(1024*1024+1)}
        for index,(label,raw) in enumerate(inputs.items()):
            with self.subTest(input=label):
                with self.assertRaises(ValueError):self.module._flex_fatal_bytes(raw,PIN)
                source,evidence,target=self.source(str(index));target.write_bytes(raw)
                self.rejects_without_writes(source,evidence)

    def test_both_architectures_return_exact_closed_evidence_and_false_qualification(self):
        fields={'schemaVersion','kind','coreCommit','architecture','path','beforeBytes','afterBytes',
                'beforeSha256','afterSha256','evidence',*QUALIFICATION}
        for architecture in ('arm64','x64'):
            with self.subTest(architecture=architecture):
                source,evidence,target=self.source(architecture)
                sentinel=evidence/'existing-other-hook.txt';sentinel.write_bytes(b'preserve other hook')
                pin=copy.deepcopy(PIN)
                result=self.module._install_flex_fatal_compat(source,evidence,pin,architecture)
                self.assertEqual(set(result),fields);self.assertEqual(pin,PIN)
                self.assertIs(type(result['schemaVersion']),int);self.assertEqual(result['schemaVersion'],1)
                self.assertEqual(result['kind'],'windows-flex-fatal-compatibility-source-hook')
                self.assertEqual((result['coreCommit'],result['architecture'],result['path']),(CORE,architecture,PATH))
                self.assertIs(type(result['beforeBytes']),int);self.assertIs(type(result['afterBytes']),int)
                self.assertEqual((result['beforeBytes'],result['afterBytes']),(37027,37161))
                self.assertEqual((result['beforeSha256'],result['afterSha256']),(BEFORE_SHA,AFTER_SHA))
                self.assertEqual(set(result['evidence']),{'original','effective'})
                for phase,size,digest in [('original',37027,BEFORE_SHA),('effective',37161,AFTER_SHA)]:
                    path=evidence/f'{phase}-{architecture}-sqlflex.l'
                    self.assertIs(type(result['evidence'][phase]),str)
                    self.assertEqual(result['evidence'][phase],str(path))
                    self.assertFalse(path.is_symlink());self.assertEqual(path.stat().st_nlink,1)
                    raw=path.read_bytes();self.assertEqual((len(raw),sha(raw)),(size,digest))
                self.assertEqual((target.stat().st_size,sha(target.read_bytes())),(37161,AFTER_SHA))
                self.assertEqual(sentinel.read_bytes(),b'preserve other hook')
                for name in QUALIFICATION:self.assertIs(result[name],False)

    def test_either_evidence_collision_rejects_before_source_or_new_evidence_write(self):
        for architecture in ('arm64','x64'):
            for phase in ('original','effective'):
                with self.subTest(architecture=architecture,phase=phase):
                    source,evidence,_=self.source(architecture+'-'+phase)
                    (evidence/f'{phase}-{architecture}-sqlflex.l').write_bytes(b'existing evidence')
                    self.rejects_without_writes(source,evidence,architecture=architecture)

    def test_reapplication_with_fresh_evidence_is_rejected(self):
        source,evidence,_=self.source();self.module._install_flex_fatal_compat(source,evidence,PIN,'arm64')
        fresh=self.root/'fresh-evidence';fresh.mkdir()
        self.rejects_without_writes(source,fresh)

    def test_missing_source_and_unknown_architecture_do_not_write_evidence(self):
        source,evidence,target=self.source();target.unlink()
        self.rejects_without_writes(source,evidence)
        target.write_bytes(self.original)
        for architecture in ('x86','ARM64',''):
            with self.subTest(architecture=architecture):
                self.rejects_without_writes(source,evidence,architecture=architecture)

    def test_linked_source_file_and_source_directory_are_rejected(self):
        for mode in ('symlink-file','hardlink-file','symlink-parent'):
            with self.subTest(mode=mode):
                source,evidence,target=self.source(mode)
                saved=self.root/(mode+'-saved');saved.write_bytes(self.original)
                try:
                    if mode=='symlink-parent':
                        parent=target.parent;relocated=self.root/(mode+'-directory')
                        parent.rename(relocated);parent.symlink_to(relocated,target_is_directory=True)
                    else:
                        target.unlink()
                        if mode=='symlink-file':target.symlink_to(saved)
                        else:os.link(saved,target)
                except (OSError,NotImplementedError) as exc:
                    self.skipTest('Host cannot create the required link: '+type(exc).__name__)
                self.rejects_without_writes(source,evidence)

    def test_linked_evidence_directory_and_broken_evidence_slot_are_rejected(self):
        for mode in ('linked-directory','broken-slot'):
            with self.subTest(mode=mode):
                source,evidence,_=self.source(mode)
                try:
                    if mode=='linked-directory':
                        evidence.rmdir();saved=self.root/(mode+'-saved');saved.mkdir()
                        evidence.symlink_to(saved,target_is_directory=True)
                    else:(evidence/'effective-arm64-sqlflex.l').symlink_to(self.root/'missing-evidence-target')
                except (OSError,NotImplementedError) as exc:
                    self.skipTest('Host cannot create the required link: '+type(exc).__name__)
                self.rejects_without_writes(source,evidence)


if __name__=='__main__':unittest.main()
