"""Exercise the pinned helper's root links, not only successful extraction.

Real GNU tools process synthetic source archives via the driver's generated
recipe. This does not qualify Cygwin links, Firebird compilation or Office.
"""
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import tarfile
import unittest

from suite.tests import test_native_source_tar_path as tar_boundary


def installer():
    path=tar_boundary.ROOT/'suite/engine-build/enable_firebird_arm64.py'
    spec=importlib.util.spec_from_file_location('source_hook_installer',path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    return result


@unittest.skipUnless(os.name!='nt' and Path('/usr/bin/tar').is_file() and Path('/usr/bin/make').is_file(),
                     'Portable GNU tools; actual Cygwin links remain a Windows qualification')
class NativeSourceModuleLinksTests(unittest.TestCase):
    def setUp(self):
        self.boundary=tar_boundary.NativeSourceTarPathTests()
        self.boundary.setUp();self.addCleanup(self.boundary.doCleanups)
        self.core=self.boundary.core;self.evidence=self.boundary.evidence
        self.boundary.populate(self.boundary.generate())
        self.archives=[];self.modules=[]
        for (archive,_),(ko_file,payload) in zip(self.boundary.archives,self.boundary.expected):
            basename=archive.name[:-len('.tar.xz')]
            module=ko_file.relative_to(self.core/'src'/basename).parts[0]
            members={module+'/ko/source-proof.txt':payload,
                     module+'/Module_'+module+'.mk':('SEEN_'+module+' := yes\n').encode(),
                     'git-hooks/pre-commit':b'must not be linked into the core\n'}
            with tarfile.open(archive,'w:xz') as output:
                for name,raw in members.items():
                    info=tarfile.TarInfo(basename+'/'+name);info.size=len(raw)
                    output.addfile(info,io.BytesIO(raw))
            self.archives.append((archive,hashlib.sha256(archive.read_bytes()).hexdigest()))
            self.modules.append((module,basename))
        fixture=tar_boundary.FIXTURE/'module-lookup.mk'
        self.assertEqual(self.boundary.manifest['moduleLookup']['sha256'],hashlib.sha256(fixture.read_bytes()).hexdigest())
        lookup='''gb_Module_MODULELOCATIONS := libreoffice:.
gb_Output_error = $(error $(1))
'''+fixture.read_text()+'''
$(foreach name,dictionaries helpcontent2 translations,$(eval $(call fixture_require_module,libreoffice,$(name))))
.PHONY: all
all:
	@printf 'modules=$(SEEN_dictionaries),$(SEEN_helpcontent2),$(SEEN_translations)\\n'
'''
        (self.core/'module-lookup.mk').write_text(lookup)

    def lookup(self):
        return subprocess.run(['/usr/bin/make','--no-print-directory','-f','module-lookup.mk','all'],
                              cwd=self.core,capture_output=True,text=True,timeout=10)

    def repair(self):
        function=getattr(installer(),'install_module_bootstrap',None)
        self.assertTrue(callable(function),'Authenticated source-hook installer must repair the pinned module-link predicate')
        return function(self.core,self.evidence)

    def test_pristine_helper_reproduces_missing_root_module_after_successful_extraction(self):
        extracted=self.boundary.run_recipe();self.assertEqual(0,extracted.returncode,extracted.stdout+extracted.stderr)
        self.assertEqual(3,extracted.stdout.count('Unpacking libreoffice-'))
        result=self.lookup();self.assertNotEqual(0,result.returncode)
        self.assertIn('Module does not exist: ./dictionaries/Module_dictionaries.mk',result.stderr)
        for name,basename in self.modules:
            self.assertTrue((self.core/'src'/basename/name/('Module_'+name+'.mk')).is_file())
            self.assertFalse((self.core/name).exists())
        self.assertTrue((self.core/'git-hooks').is_symlink())

    def test_guarded_fix_links_all_three_root_modules_and_excludes_git_hooks(self):
        original=(self.core/'bin/unpack-sources').read_bytes();receipt=self.repair()
        effective=(self.core/'bin/unpack-sources').read_bytes()
        self.assertEqual(original.replace(b'-type d -path ',b'-type d ! -path '),effective)
        self.assertEqual(original,(self.evidence/'original-unpack-sources').read_bytes())
        self.assertEqual(effective,(self.evidence/'effective-unpack-sources').read_bytes())
        self.assertEqual(hashlib.sha256(original).hexdigest(),receipt['beforeSha256'])
        self.assertEqual(hashlib.sha256(effective).hexdigest(),receipt['afterSha256'])
        extracted=self.boundary.run_recipe();self.assertEqual(0,extracted.returncode,extracted.stdout+extracted.stderr)
        result=self.lookup();self.assertEqual(0,result.returncode,result.stdout+result.stderr)
        self.assertEqual('modules=yes,yes,yes',result.stdout.strip())
        for name,basename in self.modules:
            link=self.core/name;self.assertTrue(link.is_symlink())
            self.assertEqual('src/'+basename+'/'+name,os.readlink(link))
            self.assertEqual((self.core/'src'/basename/name).resolve(),link.resolve())
            self.assertEqual(('Preserved '+name+' 한국어').encode(),(link/'ko/source-proof.txt').read_bytes())
        self.assertFalse((self.core/'git-hooks').exists())
        for archive,digest in self.archives:self.assertEqual(digest,hashlib.sha256(archive.read_bytes()).hexdigest())

    def test_unexpected_helper_or_evidence_collision_rejects_before_source_write(self):
        helper=self.core/'bin/unpack-sources';original=helper.read_bytes()
        function=getattr(installer(),'install_module_bootstrap',None)
        self.assertTrue(callable(function),'Missing pinned module-bootstrap guard')
        helper.write_bytes(original+b'\nchanged\n')
        with self.assertRaisesRegex(ValueError,'SHA256'):function(self.core,self.evidence)
        self.assertEqual(original+b'\nchanged\n',helper.read_bytes())
        self.assertEqual([],list(self.evidence.iterdir()))
        saved=self.core/'pristine-helper';saved.write_bytes(original)
        helper.unlink();helper.symlink_to(saved)
        with self.assertRaisesRegex(ValueError,'regular file'):function(self.core,self.evidence)
        self.assertEqual(original,saved.read_bytes());self.assertEqual([],list(self.evidence.iterdir()))
        helper.unlink()
        helper.write_bytes(original)
        collision=self.evidence/'effective-unpack-sources';collision.write_bytes(b'owned prior evidence')
        with self.assertRaisesRegex(ValueError,'exists'):function(self.core,self.evidence)
        self.assertEqual(original,helper.read_bytes());self.assertEqual(b'owned prior evidence',collision.read_bytes())
        self.assertFalse((self.evidence/'original-unpack-sources').exists())


if __name__=='__main__':unittest.main()
