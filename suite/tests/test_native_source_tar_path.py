"""Actual pinned unpack recipe plus real GNU tools expose Windows colon paths.

The surrounding core and minimal archives are synthetic. This does not prove
Cygwin execution, actual source compilation, or Office/Firebird qualification.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
DRIVER=ROOT/'suite/scripts/build-native-engine.ps1'
FIXTURE=Path(__file__).parent/'fixtures/native-source-tar'
PWSH=shutil.which('pwsh') or '/workspace/work/opengeul-improvements/work/ime-api-review/powershell/pwsh'


def quote(value):return "'"+str(value).replace("'","''")+"'"


@unittest.skipUnless(os.name!='nt' and Path('/usr/bin/tar').is_file() and Path('/usr/bin/make').is_file(),
                     'Portable GNU tools boundary; actual Cygwin remains a Windows qualification')
class NativeSourceTarPathTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='native-tar-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.core=self.root/'core';self.core.mkdir()
        (self.core/'bin').mkdir();shutil.copyfile(FIXTURE/'unpack-sources',self.core/'bin/unpack-sources')
        (self.core/'bin/unpack-sources').chmod(0o755)
        self.script=self.root/'make-target.sh';self.evidence=self.root/'evidence';self.evidence.mkdir()
        self.manifest=json.loads((FIXTURE/'source.json').read_text())
        self.assertEqual(self.manifest['fragment']['sha256'],hashlib.sha256((FIXTURE/'get-submodules.mk').read_bytes()).hexdigest())
        self.assertEqual(self.manifest['unpackFixture']['sha256'],hashlib.sha256((FIXTURE/'unpack-sources').read_bytes()).hexdigest())

    def ps(self,body):
        script=self.root/'generate.ps1'
        script.write_text("$ErrorActionPreference='Stop'\n. "+quote(DRIVER)+'\n'+body)
        result=subprocess.run([PWSH,'-NoLogo','-NoProfile','-File',str(script)],capture_output=True,text=True,timeout=15)
        self.assertEqual(0,result.returncode,result.stdout+result.stderr)
        return result.stdout.strip()

    def generate(self):
        raw=self.ps(f"""
$script={quote(self.script)};$unixSource={quote(self.core)};$Jobs=1;$target='ExternalProject_firebird';$evidence={quote(self.evidence)}
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile({quote(DRIVER)},[ref]$tokens,[ref]$errors)
if($errors.Count) {{throw 'Production driver has parse errors'}}
$write=@($ast.FindAll({{param($node) $node -is [Management.Automation.Language.CommandAst] -and
 $node.GetCommandName() -eq 'Write-BashScript' -and $node.CommandElements[1].Extent.Text -eq '$script' -and
 $node.Extent.Text.Contains('make -j$Jobs $target')}},$true))
if($write.Count -ne 1) {{throw 'Expected one actual make-target recipe generation statement'}}
Invoke-Expression $write[0].Extent.Text
[pscustomobject]@{{pins=@(Get-ExtraSourcePins);sourcePin=(Get-SourcePin {quote(ROOT/'suite/config/runtime.arm64.lock.json')});configure=@(Get-ConfigureArguments)}}|ConvertTo-Json -Depth 6 -Compress
""")
        data=json.loads(raw.splitlines()[-1]);self.assertEqual(self.manifest['sourceArchive'],data['sourcePin'])
        self.assertIn('--with-lang=en-US ko',data['configure'])
        self.assertEqual(3,len(data['pins']))
        return data['pins']

    def populate(self,pins):
        # Native config exports this same drive-colon spelling and module list.
        # The core path can stay POSIX here; the archive argument is the failing boundary.
        download=self.core/'C:/authenticated-downloads';download.mkdir(parents=True)
        (self.core/'Repository.mk').write_text('# synthetic core marker\n')
        (self.core/'sources.ver').write_text('lo_sources_ver='+self.manifest['sourceArchive']['version']+'\n')
        self.expected=[];self.archives=[]
        for pin in pins:
            filename=pin['filename'];self.assertTrue(filename.endswith('.tar.xz'))
            basename=filename[:-len('.tar.xz')]
            module=next(name for name in ('translations','dictionaries','helpcontent2')
                        if filename.startswith('libreoffice-'+('help' if name=='helpcontent2' else name)+'-'))
            member=module+'/ko/source-proof.txt';payload=('Preserved '+module+' 한국어').encode()
            path=download/filename
            with tarfile.open(path,'w:xz') as archive:
                info=tarfile.TarInfo(basename+'/'+member);info.size=len(payload)
                archive.addfile(info,io.BytesIO(payload))
            self.archives.append((path,hashlib.sha256(path.read_bytes()).hexdigest()))
            self.expected.append((self.core/'src'/basename/member,payload))
        header='''SRCDIR := .
TARFILE_LOCATION := C:/authenticated-downloads
GIT_NEEDED_SUBMODULES := translations dictionaries helpcontent2
.PHONY: ExternalProject_firebird get-submodules download
ExternalProject_firebird: get-submodules
	@printf 'bootstrap-fixture-complete\\n'
download:
	@true
# All synthetic archives must already exist; this harness permits no downloads.
fetch_Download_item_unchecked = $(if $(wildcard $(TARFILE_LOCATION)/$(2)),,$(error Missing cached synthetic archive))
'''
        (self.core/'Makefile').write_text(header+(FIXTURE/'get-submodules.mk').read_text())

    def run_recipe(self,options='--rsh-command=/bin/false'):
        env=dict(os.environ);env['TAR_OPTIONS']=options
        return subprocess.run(['/bin/bash','--noprofile','--norc',str(self.script)],cwd=self.core,
                              capture_output=True,text=True,env=env,timeout=10)

    def test_actual_make_fragment_unpacks_all_three_local_colon_archives(self):
        self.populate(self.generate());result=self.run_recipe()
        self.assertEqual(0,result.returncode,result.stdout+result.stderr)
        self.assertIn('bootstrap-fixture-complete',result.stdout)
        for path,raw in self.expected:
            self.assertTrue(path.is_file(),'Owned recipe must preserve '+str(path.relative_to(self.core)))
            self.assertEqual(raw,path.read_bytes())
        for path,digest in self.archives:self.assertEqual(digest,hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(3,result.stdout.count('Unpacking libreoffice-'))

    def test_owned_recipe_overrides_inherited_exclusions_and_preserves_korean_resources(self):
        self.populate(self.generate());result=self.run_recipe('--force-local --exclude=* --rsh-command=/bin/false')
        self.assertEqual(0,result.returncode,result.stdout+result.stderr)
        for path,raw in self.expected:
            self.assertTrue(path.is_file(),'Owned recipe must preserve '+str(path.relative_to(self.core)))
            self.assertEqual(raw,path.read_bytes())

    def test_local_tar_failure_is_not_hidden_by_force_local(self):
        self.populate(self.generate());self.archives[0][0].write_bytes(b'broken owned archive')
        result=self.run_recipe()
        self.assertNotEqual(0,result.returncode)
        self.assertIn('could not unpack',result.stdout)
        self.assertNotIn('bootstrap-fixture-complete',result.stdout)

    def test_actual_generated_make_recipe_is_retained_for_audit(self):
        self.generate()
        self.ps(f"""
$script={quote(self.script)};$evidence={quote(self.evidence)};$target='ExternalProject_firebird'
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile({quote(DRIVER)},[ref]$tokens,[ref]$errors)
$copies=@($ast.FindAll({{param($node) $node -is [Management.Automation.Language.CommandAst] -and
 $node.GetCommandName() -eq 'Copy-Item' -and $node.Extent.Text.Contains('-LiteralPath $script') -and
 $node.Extent.Text.Contains('make-')}},$true))
if($copies.Count -ne 1) {{throw 'Actual make recipe must be retained as owned evidence'}}
Invoke-Expression $copies[0].Extent.Text
""")
        self.assertEqual(self.script.read_bytes(),(self.evidence/'make-ExternalProject_firebird.sh').read_bytes())


if __name__=='__main__':unittest.main()
