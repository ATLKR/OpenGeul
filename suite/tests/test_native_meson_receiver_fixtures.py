"""Real portable PowerShell/GNU make fixture boundary; no Windows qualification."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from suite.tests.test_native_meson_receiver_control import PWSH, SCRIPT, prepare_module, quote


class FixturePlacementTests(unittest.TestCase):
    def ps(self, root, body):
        script = root / 'case.ps1'
        script.write_text("$ErrorActionPreference='Stop'\n. " + quote(SCRIPT) + '\n' + body)
        result = subprocess.run([PWSH, '-NoLogo', '-NoProfile', '-File', str(script)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        return result.stdout

    def test_authentic_macro_stages_and_places_all_three_spaced_pc_files_byte_identically(self):
        module = prepare_module()
        helper = module.HERE / 'source/Helper.mk'
        original = module.authentic_macro(helper.read_text(), 'gb_pkgconfig_file')
        for newline in ('\n', '\r\n'):
            with self.subTest(newline=repr(newline)), tempfile.TemporaryDirectory(prefix='pc fixture ') as folder:
                root = Path(folder); work = root / 'work';work.mkdir()
                dependencies = root / 'Dependency Fixtures'
                for part in ('graphite', 'icu', 'prefix pc'):
                    (dependencies / part).mkdir(parents=True)
                macro = root / 'macro.mk';macro.write_bytes(original.replace('\n', newline).encode())
                result = root / 'result.json';makefile = root / 'generated.mk'
                self.ps(root, '$flags=@{graphite=@(' + quote('-I"C:/Graphite include space" -DGRAPHITE2_STATIC') + ',' +
                        quote('"C:/Graphite library space/receiver-graphite.lib"') + ');icu=@(' +
                        quote('-I"C:/ICU include space"') + ',' + quote('-L"C:/ICU library space" -lreceiver-icu') + ')}\n' +
                        '$plan=Get-MesonPkgFixturePlan '+quote(dependencies)+' '+quote(work)+
                        ' ([IO.File]::ReadAllText('+quote(macro)+')) $flags\n'+
                        '[IO.File]::WriteAllText('+quote(makefile)+',$plan.makeText,[Text.UTF8Encoding]::new($false))\n'+
                        'Push-Location '+quote(work)+'\ntry{& '+quote(shutil.which('make'))+
                        ' --no-print-directory --no-builtin-rules --no-builtin-variables -f '+quote(makefile)+
                        ';if($LASTEXITCODE -ne 0){throw "Genuine make failed"}}finally{Pop-Location}\n'+
                        '$placed=@($plan.files|ForEach-Object {Install-MesonPcStage $_.staged $_.destination})\n'+
                        'Write-BuildJson '+quote(result)+' @{plan=$plan;placed=$placed}\n')
                recorded = json.loads(result.read_text(encoding='utf-8-sig'))
                self.assertEqual(3, len(recorded['placed']))
                expected = [('graphite/graphite2-uninstalled.pc', 'graphite2', '1.3.15', 'graphite'),
                            ('icu/icu-uc-uninstalled.pc', 'icu-uc', '78.3', 'icu'),
                            ('prefix pc/prefix-control.pc', 'prefix-control', '1.0', 'prefix')]
                for entry, (relative, name, version, sentinel) in zip(recorded['placed'], expected):
                    dest = dependencies / relative;stage = Path(entry['stagedPath'])
                    self.assertEqual(stage.read_bytes(), dest.read_bytes())
                    self.assertEqual(hashlib.sha256(stage.read_bytes()).hexdigest(), entry['sha256'])
                    self.assertEqual(entry['stagedSha256'], entry['sha256'])
                    self.assertTrue(entry['byteIdentical'])
                    fields = dict(line.split(':', 1) for line in dest.read_text().splitlines() if ':' in line)
                    self.assertEqual(name, fields['Name'].strip());self.assertEqual(version, fields['Version'].strip())
                    self.assertTrue(fields['Cflags'].strip());self.assertTrue(fields['Libs'].strip())
                    self.assertIn('fixture_control='+sentinel, dest.read_text())
                self.assertIn('C:/Graphite include space', (dependencies / expected[0][0]).read_text())
                self.assertFalse((root / 'Dependency').exists())

    def test_placement_rejects_empty_missing_linked_or_existing_targets(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder);stage = root / 'stage.pc';dest = root / 'destination.pc'
            self.ps(root, '$rejected=$false;try{Install-MesonPcStage '+quote(stage)+' '+quote(dest)+
                    '|Out-Null}catch{$rejected=$true};if(-not $rejected){throw "Missing stage accepted"}')
            stage.write_bytes(b'')
            self.ps(root, '$rejected=$false;try{Install-MesonPcStage '+quote(stage)+' '+quote(dest)+
                    '|Out-Null}catch{$rejected=$true};if(-not $rejected){throw "Empty stage accepted"}')
            stage.write_bytes(b'Name: fixture\n');dest.write_bytes(b'preserved destination')
            self.ps(root, '$rejected=$false;try{Install-MesonPcStage '+quote(stage)+' '+quote(dest)+
                    '|Out-Null}catch{$rejected=$true};if(-not $rejected){throw "Existing destination accepted"}')
            self.assertEqual(b'preserved destination', dest.read_bytes());dest.unlink()
            linked = root / 'linked.pc';linked.symlink_to(stage)
            self.ps(root, '$rejected=$false;try{Install-MesonPcStage '+quote(linked)+' '+quote(dest)+
                    '|Out-Null}catch{$rejected=$true};if(-not $rejected){throw "Linked stage accepted"}')
            self.assertFalse(dest.exists())

    def test_cross_file_retains_intended_bytes_and_rejects_unexpected_sibling(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder);expected = root / 'Dependency Fixtures/harfbuzz/cross-file.txt'
            expected.parent.mkdir(parents=True);expected.write_bytes(b'[binaries]\nc = [\'exact configured compiler\']\n')
            unexpected = root / 'Dependency';evidence = root / 'evidence';evidence.mkdir()
            output = root / 'cross.json'
            self.ps(root, '$r=Save-MesonCrossFile '+quote(expected)+' '+quote(unexpected)+' '+quote(evidence)+
                    ' first;Write-BuildJson '+quote(output)+' $r')
            record = json.loads(output.read_text(encoding='utf-8-sig'))
            self.assertTrue(record['passed']);self.assertEqual(expected.read_bytes(), Path(record['intended']['snapshot']).read_bytes())
            unexpected.write_bytes(b'unexpected truncated output')
            self.ps(root, '$r=Save-MesonCrossFile '+quote(expected)+' '+quote(unexpected)+' '+quote(evidence)+
                    ' second;Write-BuildJson '+quote(output)+' $r')
            record = json.loads(output.read_text(encoding='utf-8-sig'))
            self.assertFalse(record['passed'])
            self.assertEqual(unexpected.read_bytes(), Path(record['unexpected']['snapshot']).read_bytes())

    def test_observation_wrapper_recreates_cross_file_in_owned_cwd_and_retains_failed_make_output(self):
        # Replace only the Windows/Cygwin launcher with real local GNU make.
        # Ownership/native receipts remain the separate unchanged Windows gate.
        with tempfile.TemporaryDirectory(prefix='cross wrapper ') as folder:
            root = Path(folder);dependencies = root / 'Dependency Fixtures'
            observation = dependencies / 'original-capture';observation.mkdir(parents=True)
            cross = dependencies / 'harfbuzz/cross-file.txt';cross.parent.mkdir()
            evidence = root / 'evidence';evidence.mkdir();makefile = observation / 'receiver.mk'
            makefile.write_text('all:\n\t$(file >../harfbuzz/cross-file.txt,[binaries])\n\t@true\n')
            failure = observation / 'failure.mk'
            failure.write_text('all:\n\t$(file >../harfbuzz/cross-file.txt,failed make output)\n\t@false\n')
            output = root / 'wrapper.json'
            self.ps(root, '''
function Invoke-MesonMake($Makefile,$Bash,$Cygpath,$Work,$Evidence,$Name,$Allowed) {
 Push-Location $Work
 try {
  & '''+quote(shutil.which('make'))+''' --no-print-directory -f $Makefile
  $code=$LASTEXITCODE
  if($code -notin $Allowed){throw ('Portable make exit '+$code)}
  return [ordered]@{exitCode=$code;cwd=(Get-Location).Path}
 } finally {Pop-Location}
}
$observation=[pscustomobject]@{directory='''+quote(observation)+''';makefile='''+quote(makefile)+''';crossFile='''+quote(cross)+''';unexpectedSibling='''+quote(root / 'Dependency')+'''}
$first=Invoke-MesonRecipeMake $observation unused unused '''+quote(evidence)+''' first @(0) $null
$second=Invoke-MesonRecipeMake $observation unused unused '''+quote(evidence)+''' second @(0) $first.crossFile
$observation.makefile='''+quote(failure)+'''
$rejected=$false
try{Invoke-MesonRecipeMake $observation unused unused '''+quote(evidence)+''' failed @(0) $second.crossFile|Out-Null}catch{$rejected=$true}
if(-not $rejected){throw 'Failed make was accepted'}
Write-BuildJson '''+quote(output)+''' @{first=$first;second=$second}
''')
            record = json.loads(output.read_text(encoding='utf-8-sig'))
            for name in ('first', 'second'):
                self.assertEqual(str(observation), record[name]['cwd'])
                self.assertTrue(record[name]['crossFile']['passed'])
                self.assertEqual(b'[binaries]\n', Path(record[name]['crossFile']['intended']['snapshot']).read_bytes())
            failed = json.loads((evidence / 'failed-cross-file.json').read_text(encoding='utf-8-sig'))
            self.assertEqual(b'failed make output\n', Path(failed['intended']['snapshot']).read_bytes())
            self.assertFalse((root / 'Dependency').exists())


if __name__ == '__main__':
    unittest.main()
