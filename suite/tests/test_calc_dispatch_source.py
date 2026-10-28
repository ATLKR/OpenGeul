"""Authenticated source probes and explicit diagnostic build isolation."""
import copy
import difflib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import shutil
import tempfile
import unittest
from unittest.mock import patch

from suite.tests.test_native_engine_build import PWSH, SOURCE, quote

PACKAGE = Path(__file__).resolve().parents[1]/'engine-build/calc-dispatch-diagnostic'
CORE = 'bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1'
PATHS = ('sc/source/ui/view/tabvwsha.cxx', 'sfx2/source/doc/objstor.cxx')
PAYLOADS = tuple((name, 'include/opengeul_calc_dispatch/'+name)
                 for name in ('windows_runtime.h', 'recorder.h', 'wire.h'))


def digest(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


class CalcDispatchSourceTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((PACKAGE/'install.py').is_file(), 'Diagnostic source installer is missing')
        spec = importlib.util.spec_from_file_location('calc_dispatch_source_test', PACKAGE/'install.py')
        self.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.m)
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.source = self.root/'source'; self.source.mkdir()
        self.package = self.root/'repo/suite/engine-build/calc-dispatch-diagnostic'
        self.package.mkdir(parents=True)
        self.payload = self.package
        (self.source/'include').mkdir()
        self.originals = {}; self.changed = {}; differences = []
        for index, name in enumerate(PATHS):
            raw = f'// synthetic source {index}\nvoid save()\n{{\n    existing_save();\n}}\n'.encode()
            changed = raw.replace(b'    existing_save();', b'    numeric_probe();\n    existing_save();')
            path = self.source/name; path.parent.mkdir(parents=True); path.write_bytes(raw)
            self.originals[name] = raw; self.changed[name] = changed
            differences.extend(difflib.unified_diff(raw.decode().splitlines(True), changed.decode().splitlines(True),
                               fromfile='a/'+name, tofile='b/'+name))
        diff = ''.join(differences).encode(); (self.package/'source.patch').write_bytes(diff)
        self.lock = {'schemaVersion': 1, 'kind': 'calc-save-dispatch-diagnostic-source',
                     'coreCommit': CORE, 'target': 'windows-arm64', 'acceptanceEligible': False,
                     'patch': {'path': 'source.patch', **digest(diff)},
                     'sources': [{'path': name, 'before': digest(self.originals[name]),
                                  'after': digest(self.changed[name])} for name in PATHS], 'payloads': []}
        for name, target in PAYLOADS:
            raw = ('// synthetic numeric diagnostic '+name+'\n').encode()
            (self.payload/name).write_bytes(raw)
            self.lock['payloads'].append({'source': name, 'path': target, **digest(raw)})
        self.save_lock()

    def save_lock(self):
        (self.package/'source-lock.json').write_text(json.dumps(self.lock), encoding='utf-8')

    def install(self, target='windows-arm64', core=CORE):
        return self.m.install(self.source, target, core, package=self.package)

    def unchanged(self):
        for name, raw in self.originals.items():
            self.assertEqual(raw, (self.source/name).read_bytes())
        for _, name in PAYLOADS:
            self.assertFalse((self.source/name).exists())

    def test_authenticated_exact_patch_and_payload_receipt(self):
        receipt = self.install()
        self.assertEqual('calc-save-dispatch-diagnostic-source', receipt['kind'])
        self.assertFalse(receipt['fullEngineQualified']); self.assertFalse(receipt['acceptanceEligible'])
        self.assertEqual(CORE, receipt['coreCommit'])
        self.assertEqual(hashlib.sha256((self.package/'source-lock.json').read_bytes()).hexdigest(), receipt['lockSha256'])
        self.assertEqual(2, len(receipt['sources'])); self.assertEqual(3, len(receipt['payloads']))
        for name in PATHS:
            self.assertEqual(self.changed[name], (self.source/name).read_bytes())
        for name, target in PAYLOADS:
            self.assertEqual((self.payload/name).read_bytes(), (self.source/target).read_bytes())
        self.assertNotIn(str(self.root), json.dumps(receipt))
        with self.assertRaises(ValueError): self.install()

    def test_late_source_patch_and_payload_drift_reject_before_any_write(self):
        cases = [(self.source/PATHS[-1], b'stale source'), (self.payload/'wire.h', b'stale payload'),
                 (self.package/'source.patch', b'stale patch')]
        for path, changed in cases:
            old = path.read_bytes(); path.write_bytes(changed)
            with self.subTest(path=path.name), self.assertRaises(ValueError): self.install()
            self.assertEqual(self.originals[PATHS[0]], (self.source/PATHS[0]).read_bytes())
            self.assertFalse((self.source/'include/opengeul_calc_dispatch').exists())
            path.write_bytes(old)
        self.unchanged()

    def test_bad_result_digest_duplicate_and_escape_reject_before_writes(self):
        pristine = copy.deepcopy(self.lock)
        for mode in ('after', 'duplicate-source', 'duplicate-payload', 'escape-source', 'escape-payload'):
            self.lock = copy.deepcopy(pristine)
            if mode == 'after': self.lock['sources'][-1]['after']['sha256'] = '0'*64
            if mode == 'duplicate-source': self.lock['sources'].append(self.lock['sources'][0])
            if mode == 'duplicate-payload': self.lock['payloads'].append(self.lock['payloads'][0])
            if mode == 'escape-source': self.lock['sources'][-1]['path'] = '../outside.cxx'
            if mode == 'escape-payload': self.lock['payloads'][-1]['path'] = '../outside.h'
            self.save_lock()
            with self.subTest(mode=mode), self.assertRaises(ValueError): self.install()
            self.unchanged()

    def test_existing_payload_is_preserved_and_prevents_source_writes(self):
        existing = self.source/PAYLOADS[-1][1]; existing.parent.mkdir(); existing.write_bytes(b'preserve existing header')
        with self.assertRaises(ValueError): self.install()
        self.assertEqual(b'preserve existing header', existing.read_bytes())
        for name, raw in self.originals.items(): self.assertEqual(raw, (self.source/name).read_bytes())

    def test_nonarm64_and_unpinned_core_reject_before_writes(self):
        for target, core in (('windows-x64', CORE), ('linux-arm64', CORE), ('windows-arm64', 'a'*40)):
            with self.subTest(target=target, core=core), self.assertRaises(ValueError): self.install(target, core)
            self.unchanged()

    def test_linked_source_payload_and_destination_ancestor_reject(self):
        source = self.source/PATHS[0]; original = source.read_bytes()
        other = self.root/'other'; other.write_bytes(original)
        try: source.unlink(); source.symlink_to(other)
        except OSError as error: self.skipTest('Host cannot create a synthetic link: '+type(error).__name__)
        with self.assertRaises(ValueError): self.install()
        source.unlink(); source.write_bytes(original)
        native = self.payload/'wire.h'; raw = native.read_bytes(); native.unlink(); native.symlink_to(other)
        with self.assertRaises(ValueError): self.install()
        native.unlink(); native.write_bytes(raw)
        include = self.source/'include'; include.rmdir(); include.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError): self.install()
        include.unlink(); include.mkdir(); self.unchanged()

    def test_source_change_between_planning_and_writing_rejects(self):
        read = self.m.read_regular; seen = []
        def mutate(path, *args, **kwargs):
            raw = read(path, *args, **kwargs)
            if Path(path) == self.payload/'wire.h' and not seen:
                seen.append(True); (self.source/PATHS[0]).write_bytes(b'concurrent source change')
            return raw
        with patch.object(self.m, 'read_regular', side_effect=mutate), self.assertRaises(ValueError): self.install()
        self.assertEqual(self.originals[PATHS[1]], (self.source/PATHS[1]).read_bytes())
        self.assertFalse((self.source/'include/opengeul_calc_dispatch').exists())

    def test_cli_failure_is_numeric_free_of_input_paths(self):
        process = subprocess.run([os.sys.executable, str(PACKAGE/'install.py'), '--source-root', str(self.source),
            '--target', 'windows-x64', '--core-commit', CORE], text=True, capture_output=True, timeout=10)
        self.assertNotEqual(0, process.returncode)
        self.assertNotIn(str(self.root), process.stdout+process.stderr)
        self.unchanged()

    def test_locked_real_patch_observes_existing_calls_without_extra_saves(self):
        lock = json.loads((PACKAGE/'source-lock.json').read_text())
        self.assertEqual(CORE, lock['coreCommit'])
        self.assertEqual({'sc/source/ui/view/tabvwsha.cxx', 'sfx2/source/doc/objstor.cxx'}, {s['path'] for s in lock['sources']})
        self.assertEqual({'sc/source/ui/view/tabvwsha.cxx': 'bff1e750e6d778b0b8a5f13f69325a309fc7a1d6d95935d4b3579f9e497a0561',
                          'sfx2/source/doc/objstor.cxx': '383efdebc4548969c1b64ae899f09cbd8ae622461508861de8b5db5119d1fee5'},
                         {s['path']: s['before']['sha256'] for s in lock['sources']})
        patch_bytes = (PACKAGE/'source.patch').read_bytes()
        self.assertEqual(digest(patch_bytes), {key: lock['patch'][key] for key in ('bytes', 'sha256')})
        self.assertFalse(any(line.startswith('-') and not line.startswith('---') for line in patch_bytes.decode().splitlines()))
        added = '\n'.join(line[1:] for line in patch_bytes.decode().splitlines() if line.startswith('+') and not line.startswith('+++'))
        for operation in (1, 2, 3): self.assertIn(f'Scope opengeulCalcDispatch({operation})', added)
        for phase in (3, 4, 5, 6, 7, 8, 9): self.assertIn(f'.mark({phase}', added)
        self.assertNotRegex(added, r'InputEnterHandler\(|ExecuteSlot\(|\.Commit\(|SetDocument|SendInput|sleep')
        self.assertIn('mark(3, bCommitChanges)', added)
        self.assertIn('mark(9, bOk)', added)
        for payload in lock['payloads']:
            raw = (PACKAGE/payload['source']).read_bytes()
            self.assertEqual(digest(raw), {key: payload[key] for key in ('bytes', 'sha256')})

    def test_actual_added_probe_statements_compile_against_native_runtime_api(self):
        compiler = shutil.which('c++') or shutil.which('g++') or shutil.which('clang++')
        if not compiler: self.skipTest('Portable C++ compiler unavailable for the source/runtime API check')
        functions = []
        for line in (PACKAGE/'source.patch').read_text().splitlines():
            if not line.startswith('+') or line.startswith('+++'): continue
            statement = line[1:].strip()
            if '::Scope ' in statement: functions.append([])
            if 'opengeul' in statement and not statement.startswith('#'):
                self.assertTrue(functions, 'Probe statement precedes its source Scope')
                functions[-1].append(statement)
        self.assertEqual(3, len(functions))
        source = self.root/'probe-api.cpp'
        source.write_text('#include "windows_runtime.h"\n'+''.join(
            f'void probe{index}() {{ bool bCommitChanges=true; bool bOk=true;\n'
            +'\n'.join(statements)+'\n(void)bCommitChanges; (void)bOk; }\n'
            for index, statements in enumerate(functions)))
        result = subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror', '-pedantic',
                                 '-fsyntax-only', '-I', str(PACKAGE), str(source)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(0, result.returncode, result.stdout+result.stderr)

    def test_exact_pristine_upstream_source_when_supplied_by_build(self):
        supplied = os.environ.get('OPENGEUL_CALC_DISPATCH_SOURCE_ROOT')
        if not supplied: self.skipTest('Pristine upstream source is supplied by the diagnostic source-build gate')
        root = self.root/'pristine'; root.mkdir(); (root/'include').mkdir()
        for name in PATHS:
            target = root/name; target.parent.mkdir(parents=True)
            shutil.copyfile(Path(supplied)/name, target)
        receipt = self.m.install(root, 'windows-arm64', CORE)
        for item in receipt['sources']:
            self.assertEqual(digest((Path(supplied)/item['path']).read_bytes()), item['before'])
            self.assertEqual(digest((root/item['path']).read_bytes()), item['after'])


class CalcDispatchBuildTests(unittest.TestCase):
    def test_source_gate_override_reaches_only_real_child_and_retains_guard(self):
        source = self.root/"owned source's tree"
        source.mkdir()
        child = self.root/'source-child.py'
        child.write_text("import os,pathlib,sys\nprint(pathlib.Path(os.environ['OPENGEUL_CALC_DISPATCH_SOURCE_ROOT']).samefile(sys.argv[1]))\n")
        output = self.ps(f"""
$before=[Environment]::GetEnvironmentVariable('OPENGEUL_CALC_DISPATCH_SOURCE_ROOT')
$r=Invoke-LoggedCommand {quote(os.sys.executable)} @({quote(child)},{quote(source)}) {quote(self.root)} {quote(self.root/'gate')} -TimeoutMinutes 0.1 -EnvironmentOverrides @{{OPENGEUL_CALC_DISPATCH_SOURCE_ROOT={quote(source)}}}
if([Environment]::GetEnvironmentVariable('OPENGEUL_CALC_DISPATCH_SOURCE_ROOT') -cne $before){{throw 'Controller environment changed'}}
Get-Content -LiteralPath $r.stdout
""")
        self.assertEqual(output.splitlines()[-1], 'True')
        receipt=json.loads((self.root/'gate.command.json').read_text())
        self.assertEqual(set(receipt['environmentOverrideSha256']), {'OPENGEUL_CALC_DISPATCH_SOURCE_ROOT'})
        self.assertTrue(receipt['passed'])
        for key,value in (('OTHER','synthetic'),('OPENGEUL_CALC_DISPATCH_SOURCE_ROOT','relative'),
                          ('OPENGEUL_CALC_DISPATCH_SOURCE_ROOT',str(child))):
            prefix=self.root/('reject-'+key+('-file' if value==str(child) else ''))
            self.ps(f"$rejected=$false;try{{Invoke-LoggedCommand {quote(os.sys.executable)} @('-c','pass') {quote(self.root)} {quote(prefix)} -EnvironmentOverrides @{{{key}={quote(value)}}}}}catch{{$rejected=$true}};if(-not $rejected){{throw 'Invalid child override admitted'}}")

    def setUp(self):
        self.assertTrue(Path(PWSH).is_file(), 'PowerShell boundary tests require the selected validation environment')
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup); self.root = Path(tmp.name).resolve()

    def ps(self, body):
        script = self.root/'case.ps1'
        script.write_text("$ErrorActionPreference='Stop'\n. "+quote(SOURCE)+'\n'+body)
        result = subprocess.run([PWSH, '-NoLogo', '-NoProfile', '-File', str(script)], text=True,
                                capture_output=True, timeout=30)
        self.assertEqual(0, result.returncode, result.stdout+'\n'+result.stderr)
        return result.stdout.strip()

    def test_diagnostic_mode_has_distinct_artifact_receipt_and_false_qualification(self):
        normal = json.loads(self.ps('Get-NativeEngineBuildMode Full|ConvertTo-Json -Compress'))
        diagnostic = json.loads(self.ps('Get-NativeEngineBuildMode Full -CalcDispatchDiagnostic|ConvertTo-Json -Compress'))
        self.assertEqual('OpenGeul-Office-engine-arm64.zip', normal['archive'])
        self.assertEqual('source-build-receipt.json', normal['receipt'])
        self.assertTrue(normal['fullEngineQualified'])
        self.assertEqual('OpenGeul-Office-engine-arm64-calc-dispatch.zip', diagnostic['archive'])
        self.assertEqual('calc-dispatch-source-build-receipt.json', diagnostic['receipt'])
        self.assertEqual('native-engine-calc-dispatch-diagnostic-built', diagnostic['status'])
        self.assertFalse(diagnostic['fullEngineQualified']); self.assertFalse(diagnostic['acceptanceEligible'])
        self.assertEqual('native-office-engine-calc-dispatch-diagnostic', diagnostic['kind'])

    def test_nonfull_diagnostic_rejects_before_creating_any_work(self):
        work = self.root/'work'; evidence = self.root/'evidence'
        self.ps(f"$rejected=$false; try {{ Invoke-NativeEngineBuild Firebird {quote(work)} {quote(evidence)} '' 4 -CalcDispatchDiagnostic }} catch {{$rejected=$true}}; if(-not $rejected){{throw 'Nonfull diagnostic admitted'}}")
        self.assertFalse(work.exists()); self.assertFalse(evidence.exists())

    def test_diagnostic_failure_receipt_cannot_qualify_normal_artifact(self):
        evidence = self.root/'evidence'
        self.ps(f"function Get-NativeBuildHost {{throw 'Synthetic native host rejection'}}; try {{ Invoke-NativeEngineBuild Full {quote(self.root/'work')} {quote(evidence)} '' 4 -CalcDispatchDiagnostic }} catch {{}}")
        self.assertFalse((evidence/'source-build-receipt.json').exists())
        receipt = json.loads((evidence/'calc-dispatch-source-build-receipt.json').read_text())
        self.assertFalse(receipt['passed']); self.assertFalse(receipt['fullEngineQualified']); self.assertFalse(receipt['acceptanceEligible'])
        self.assertEqual('native-office-engine-calc-dispatch-diagnostic', receipt['kind'])

    def test_actual_packaging_tail_selects_diagnostic_archive_and_receipt(self):
        import zipfile
        for diagnostic in (False, True):
            case = self.root/str(diagnostic); case.mkdir()
            runtime = case/'runtime'; (runtime/'program').mkdir(parents=True)
            (runtime/'program/soffice.bin').write_bytes(b'synthetic native runtime')
            evidence = case/'evidence'; evidence.mkdir()
            tail = self.ps(f"""
$text=Get-Content -LiteralPath {quote(SOURCE)} -Raw
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseInput($text,[ref]$tokens,[ref]$errors)
$build=$ast.Find({{param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Invoke-NativeEngineBuild'}},$true)
$outer=$build.Body.Find({{param($n) $n -is [Management.Automation.Language.TryStatementAst]}},$true)
$start=$text.IndexOf('            if($CalcDispatchDiagnostic) {{Write-CalcDispatchRuntimeMarker')
if($start -lt 0){{throw 'Runtime marker boundary absent'}}
$tail='if($Phase -eq ''Full'') {{'+$text.Substring($start,$outer.Body.Extent.EndOffset-1-$start)
$Phase='Full';$CalcDispatchDiagnostic=${str(diagnostic).lower()}
$mode=Get-NativeEngineBuildMode $Phase -CalcDispatchDiagnostic:$CalcDispatchDiagnostic
$evidence={quote(evidence)};$instdir={quote(runtime)}
$receipt=[ordered]@{{kind=$mode.kind;sourceCommit=('a'*40);calcDispatchSourceHooks=@{{coreCommit='{CORE}';lockSha256=('b'*64);acceptanceEligible=$false;fullEngineQualified=$false}}}}
function Assert-NativeBuildTimeRemaining {{}}
& ([scriptblock]::Create($tail))
Write-BuildJson (Join-Path $evidence $mode.receipt) $receipt
$mode.receipt
""")
            receipt = json.loads((evidence/tail.splitlines()[-1]).read_text())
            self.assertTrue(receipt['passed'])
            self.assertEqual(not diagnostic, receipt['fullEngineQualified'])
            self.assertEqual(not diagnostic, receipt['acceptanceEligible'])
            expected = 'OpenGeul-Office-engine-arm64'+('-calc-dispatch' if diagnostic else '')+'.zip'
            self.assertEqual(str(evidence/expected), receipt['artifact']['path'])
            self.assertEqual(digest((evidence/expected).read_bytes())['sha256'], receipt['artifact']['sha256'])
            self.assertFalse((evidence/('source-build-receipt.json' if diagnostic else 'calc-dispatch-source-build-receipt.json')).exists())
            with zipfile.ZipFile(evidence/expected) as archive:
                self.assertEqual(b'synthetic native runtime', archive.read('program/soffice.bin'))
                self.assertEqual(diagnostic, 'program/opengeul-calc-dispatch-diagnostic.json' in archive.namelist())
                if diagnostic:
                    marker = json.loads(archive.read('program/opengeul-calc-dispatch-diagnostic.json'))
                    self.assertFalse(marker['acceptanceEligible']); self.assertFalse(marker['fullEngineQualified'])

    def test_marker_is_fixed_ineligible_and_bound_to_source_install_receipt(self):
        program = self.root/'runtime/program'; program.mkdir(parents=True)
        marker = program/'opengeul-calc-dispatch-diagnostic.json'
        self.ps(f"Write-CalcDispatchRuntimeMarker {quote(program.parent)} ('a'*40) @{{coreCommit='{CORE}';lockSha256=('b'*64);acceptanceEligible=$false;fullEngineQualified=$false}}")
        receipt = json.loads(marker.read_text())
        self.assertEqual('calc-save-dispatch-diagnostic', receipt['kind'])
        self.assertFalse(receipt['acceptanceEligible']); self.assertFalse(receipt['fullEngineQualified'])
        self.assertEqual('a'*40, receipt['sourceCommit']); self.assertEqual('b'*64, receipt['sourceLockSha256'])
        original = marker.read_bytes()
        self.ps(f"$rejected=$false;try {{Write-CalcDispatchRuntimeMarker {quote(program.parent)} ('a'*40) @{{}}}} catch {{$rejected=$true}};if(-not $rejected){{throw 'Existing marker admitted'}}")
        self.assertEqual(original, marker.read_bytes())

    def test_workflow_explicit_diagnostic_cannot_upload_as_qualified(self):
        text = (SOURCE.parents[2]/'.github/workflows/office-native-engine.yml').read_text()
        build = text.split('      - name: Build and verify native Firebird before the full Office engine', 1)[1].split('      - name:', 1)[0]
        self.assertIn('-CalcDispatchDiagnostic', build); self.assertIn('-MutexSymbols', build)
        qualified = text.split('      - name: Retain the qualified native engine input', 1)[1].split('      - name:', 1)[0]
        self.assertIn("if: ${{ env.OPENGEUL_CALC_DISPATCH_BUILD != 'true' }}", qualified)
        self.assertIn('OPENGEUL_CALC_DISPATCH_BUILD:', text)
        self.assertIn('OpenGeul-Office-engine-arm64-calc-dispatch.zip', text)
        self.assertIn('calc-dispatch-source-build-receipt.json', text)
        self.assertIn('Assert-MutexSymbolsEnvironment', text)


if __name__ == '__main__': unittest.main()
