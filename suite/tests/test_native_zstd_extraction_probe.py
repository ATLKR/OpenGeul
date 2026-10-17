"""Portable diagnostic contracts; native Cygwin/NTFS behavior stays in Windows CI."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
SCRIPT=ROOT/'suite/scripts/probe-native-zstd-extraction.ps1'
PWSH=shutil.which('pwsh') or '/workspace/work/opengeul-improvements/work/ime-api-review/powershell/pwsh'

def quote(value):return "'"+str(value).replace("'","''")+"'"

class NativeZstdExtractionProbeTests(unittest.TestCase):
    def helper(self,folder):
        self.assertTrue(SCRIPT.is_file(),'Native zstd extraction diagnostic must exist')
        target=Path(folder)/'helper.py'
        run=subprocess.run([PWSH,'-NoProfile','-Command',"$ErrorActionPreference='Stop'; . "+quote(SCRIPT)+"; Write-ZstdProbeHelper "+quote(target)],capture_output=True,text=True,timeout=15)
        self.assertEqual(0,run.returncode,run.stdout+run.stderr)
        spec=importlib.util.spec_from_file_location('zstd_probe_helper',target);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        return module

    def test_actual_archive_manifest_keeps_link_order_and_rejects_bad_members(self):
        with tempfile.TemporaryDirectory() as folder:
            helper=self.helper(folder);path=Path(folder)/'input.tar.gz'
            def archive(bad=None):
                with tarfile.open(path,'w:gz') as out:
                    for name,kind,data in [('zstd/tests/bin/unzstd','link','zstd'),('zstd/tests/bin/zstd','file',b'#!/bin/sh\n'),('zstd/tests/bin/zstdcat','link','zstd')]:
                        item=tarfile.TarInfo('../escape' if bad=='escape' and kind=='file' else name)
                        if kind=='link':item.type=tarfile.SYMTYPE;item.linkname='../../outside' if bad=='link' else data;out.addfile(item)
                        else:item.size=len(data);out.addfile(item,io.BytesIO(data))
                    if bad=='duplicate':out.addfile(tarfile.TarInfo('zstd/tests/bin/zstd'))
            archive();plan=helper.archive_manifest(path)
            self.assertEqual(['symlink','regular','symlink'],[r['kind'] for r in plan['members']])
            self.assertEqual('tests/bin/unzstd',plan['members'][0]['path']);self.assertEqual('zstd',plan['members'][0]['target'])
            for bad in ('escape','link','duplicate'):
                archive(bad)
                with self.subTest(bad=bad),self.assertRaises(ValueError):helper.archive_manifest(path)

    def test_census_replays_all_regular_bytes_and_link_targets_without_deletion(self):
        with tempfile.TemporaryDirectory() as folder:
            helper=self.helper(folder);root=Path(folder)/'tree';root.mkdir();(root/'zstd').write_bytes(b'owned');(root/'unzstd').symlink_to('zstd')
            manifest=dict(members=[dict(path='zstd',kind='regular',bytes=5,sha256=hashlib.sha256(b'owned').hexdigest()),dict(path='unzstd',kind='symlink',target='zstd')])
            valid=helper.census(root,manifest);self.assertTrue(valid['passed'])
            for damage in ('extra','bytes','link'):
                if damage=='extra':(root/'extra').write_bytes(b'bad')
                elif damage=='bytes':(root/'extra').unlink();(root/'zstd').write_bytes(b'other')
                else:(root/'zstd').write_bytes(b'owned');(root/'unzstd').unlink();(root/'unzstd').symlink_to('absent')
                with self.subTest(damage=damage),self.assertRaises(ValueError):helper.census(root,manifest)

    def test_actual_make_harness_uses_whole_authenticated_macros_and_source_hook(self):
        with tempfile.TemporaryDirectory() as folder:
            helper=self.helper(folder)
            text=helper.make_harness(Path('/owned/core'),Path('/owned/case'),Path('/owned/archive'),False)
            self.assertIn('include /owned/core/solenv/gbuild/UnpackedTarball.mk',text)
            self.assertIn('include /owned/core/external/zstd/UnpackedTarball_zstd.mk',text)
            self.assertIn('OS := WNT',text);self.assertIn('CPUNAME := AARCH64',text)
            self.assertNotIn('winsymlinks:sys',text,'Diagnostic must consume production hook, not duplicate it')
            source=SCRIPT.read_text();self.assertIn('module.install(source, evidence)',source)
            self.assertNotIn("replace(b'",source)

    def test_source_pinned_setup_and_workflow_keep_deadlines_failures_and_no_qualification(self):
        self.assertTrue(SCRIPT.is_file(),'Diagnostic must exist')
        source=SCRIPT.read_text();workflow=(ROOT/'.github/workflows/office-native-zstd-extraction-probe.yml').read_text()
        self.assertIn('New-NativeBuildBudget -DeadlineUtc $Deadline -MaximumMinutes 20',source)
        self.assertIn('-NativeLinks',source);self.assertIn('Assert-ZstdProbeResult',source)
        self.assertIn('engineQualified=$false',source);self.assertIn('productQualified=$false',source)
        self.assertIn('finally',source);self.assertIn('diagnostic.json',source)
        self.assertIn('windows-11-arm',workflow);self.assertIn('timeout-minutes: 30',workflow)
        self.assertIn('if: always()',workflow);self.assertIn('include-hidden-files: true',workflow)
        self.assertIn('if (-not $?)',workflow);self.assertIn('AddMinutes(20)',workflow)
        self.assertNotIn('-Phase Full',workflow);self.assertNotIn('build-native-engine.ps1 -Phase',source)

    def test_actual_command_failure_receipt_and_final_admission_stay_strict(self):
        import sys
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();self.helper(root)
            child=root/'child.py';child.write_text("print('original command diagnostic');raise SystemExit(7)\n")
            prefix=root/'failure'
            body="""$expected=@{strictOriginal=@{exitCode=2;forcedTermination=$false;pipeDrainComplete=$true;directProcessDeathVerified=$true};correctedSource=@{passed=$true;exitCode=0;forcedTermination=$false;pipeDrainComplete=$true;directProcessDeathVerified=$true};completeCensus=@{passed=$true;memberCount=743;platform='cygwin';manifestSha256='owned'};extractionPlan=@{archiveManifestSha256='owned'};nativePython=@{passed=$true;processMachine=0;nativeMachine=43620;alias=@{reparseTag=2684354572};sourceOnlySystemLinks=@(1,2)};nativePowerShell=@{matches=$true;linkType='SymbolicLink'}}
Assert-ZstdProbeResult $expected
foreach($damage in @('forced','count','foreign','manifest','tag')) {
 $changed=$expected|ConvertTo-Json -Depth 20|ConvertFrom-Json
 switch($damage) {'forced' {$changed.correctedSource.forcedTermination=$true};'count' {$changed.completeCensus.memberCount=742};'foreign' {$changed.nativePython.processMachine=34404};'manifest' {$changed.completeCensus.manifestSha256='foreign'};'tag' {$changed.nativePython.alias.reparseTag=0}}
 $rejected=$false;try {Assert-ZstdProbeResult $changed} catch {$rejected=$true};if(-not $rejected){throw ('Invalid proof admitted: '+$damage)}
}
"""
            body+="try {Invoke-LoggedCommand "+quote(sys.executable)+" @("+quote(child)+") "+quote(root)+" "+quote(prefix)+" -TimeoutMinutes 0.1|Out-Null;throw 'Unexpected success'} catch {if($_.Exception.Message -cnotmatch 'Command failed with exit 7'){throw}}"
            test_script=root/'retained-failure.ps1';test_script.write_text("$ErrorActionPreference='Stop'\n. "+quote(SCRIPT)+"\n"+body)
            result=subprocess.run([PWSH,'-NoProfile','-File',str(test_script)],capture_output=True,text=True,timeout=15)
            self.assertEqual(0,result.returncode,result.stdout+result.stderr)
            receipt=json.loads(prefix.with_suffix('.command.json').read_text())
            self.assertFalse(receipt['passed']);self.assertEqual(7,receipt['exitCode']);self.assertFalse(receipt['forcedTermination'])
            self.assertEqual('original command diagnostic',prefix.with_suffix('.stdout.log').read_text().strip())

    def test_actual_tool_inventory_accepts_cygwin_exe_and_dll_without_product_admission(self):
        import struct
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();(root/'bin').mkdir()
            def image(dll=False):
                data=bytearray(1024);data[:2]=b'MZ';struct.pack_into('<I',data,60,128);data[128:132]=b'PE\0\0'
                struct.pack_into('<HH',data,132,0x8664,1);struct.pack_into('<HH',data,148,240,0x2002 if dll else 2)
                struct.pack_into('<H',data,152,0x20b);struct.pack_into('<I',data,260,16);struct.pack_into('<II',data,272,0x1000,40)
                struct.pack_into('<IIII',data,400,512,0x1000,512,512);struct.pack_into('<I',data,524,0x1040);data[576:588]=b'cygwin1.dll\0'
                return bytes(data)
            names=('env.exe','bash.exe','cygpath.exe','make.exe','tar.exe','ln.exe','cygwin1.dll')
            for name in names:(root/'bin'/name).write_bytes(image(name.endswith('.dll')))
            body="""$tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile(SOURCE,[ref]$tokens,[ref]$errors)
$tools=@($ast.FindAll({param($n)$n -is [Management.Automation.Language.AssignmentStatementAst] -and $n.Left.Extent.Text -ceq '$receipt.tools'},$true))
if($errors.Count -or $tools.Count -ne 1){throw 'Expected actual tools inventory assignment'}
$cygwin=OWNED;$receipt=[ordered]@{}
foreach($name in @('env.exe','cygwin1.dll')) {$rejected=$false;try{Get-WindowsBuildToolPeIdentity (Join-Path $cygwin ('bin/'+$name))|Out-Null}catch{$rejected=$true};if(-not $rejected){throw 'Shared non-Cygwin Windows guard was weakened'}}
Invoke-Expression $tools[0].Extent.Text
if($receipt.tools.Count -ne 7 -or @($receipt.tools|Where-Object {$_.productPayload -or -not $_.buildToolOnly -or $_.machine -ne 34404}).Count){throw 'Cygwin inventory changed product admission'}
if(@($receipt.tools|Where-Object {$_.kind -ceq 'dll'}).Count -ne 1){throw 'Cygwin DLL identity was not retained'}
""".replace('SOURCE',quote(SCRIPT)).replace('OWNED',quote(root))
            test=root/'inventory.ps1';test.write_text("$ErrorActionPreference='Stop'\n. "+quote(SCRIPT)+"\n"+body)
            result=subprocess.run([PWSH,'-NoProfile','-File',str(test)],capture_output=True,text=True,timeout=15)
            self.assertEqual(0,result.returncode,result.stdout+result.stderr)

if __name__=='__main__':unittest.main()
