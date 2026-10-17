"""Portable observation admission tests; no native compiler result is implied."""
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('matrix_observation', ROOT/'suite/scripts/native_mdds_matrix_observation.py')
observation = importlib.util.module_from_spec(spec)
if spec.loader and Path(spec.origin).exists(): spec.loader.exec_module(observation)


class MatrixAdmissionTests(unittest.TestCase):
    def command(self, code=0):
        return dict(exitCode=code, forcedTermination=False, pipeDrainComplete=True,
                    directProcessDeathVerified=True, cleanupErrors=[], pid=42,
                    creationUtcTicks=639278626391148272)

    def log(self, extra=''):
        return 'Microsoft C/C++ Optimizing Compiler Version 19.51.36260 for ARM64\n'+extra

    def test_normal_compile_errors_are_classified_without_product_claim(self):
        classify=getattr(observation,'classify_compile',None)
        self.assertIsNotNone(classify, 'matrix classification is not implemented')
        equality="multi_type_matrix_def.inl(93): error C2382: 'mdds::multi_type_matrix<Traits>::operator ==': redefinition; different exception specifications\nmulti_type_matrix.hpp(256): note: see declaration of 'mdds::multi_type_matrix<Traits>::operator =='\n"
        self.assertEqual(classify(self.command(2),self.log(equality)), 'matrix-equality-C2382')
        inequality=equality.replace('(93)', '(99)').replace('(256)', '(257)').replace('operator ==','operator !=')
        self.assertEqual(classify(self.command(2),self.log(inequality)), 'matrix-equality-C2382')
        for text in ('fatal error C1083: missing dependency\n', equality+'error C2143: unrelated syntax\n', equality.replace('(256)','(255)')):
            self.assertEqual(classify(self.command(2),self.log(text)), 'unrelated-compiler-error')
        self.assertEqual(classify(self.command(),self.log()), 'compile-success')

    def test_abnormal_exits_and_unowned_or_incomplete_commands_are_rejected(self):
        classify=getattr(observation,'classify_compile',None)
        self.assertIsNotNone(classify, 'matrix classification is not implemented')
        for command,log in [(self.command(code),self.log('error C2382: different exception specifications')) for code in (1,3,99,-1073741819,3221225477)]+[
            (dict(self.command(),forcedTermination=True),self.log()),
            (dict(self.command(),pipeDrainComplete=False),self.log()),
            (dict(self.command(),directProcessDeathVerified=False),self.log()),
            (dict(self.command(),cleanupErrors=['failure']),self.log()),
            (dict(self.command(),creationUtcTicks=0),self.log()),
            (self.command(2),self.log('fatal error C1001: Internal compiler error')),
            (self.command(),self.log('error C2143: syntax')),
            (self.command(2),self.log()),
            (self.command(),self.log().replace('19.51.36260','19.50.1'))]:
            with self.subTest(command=command, log=log):
                with self.assertRaises(ValueError):classify(command,log)

    def test_expected_original_include_scope_and_arm64_object_are_required(self):
        admit=getattr(observation,'admit_case',None)
        self.assertIsNotNone(admit, 'matrix case admission is not implemented')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);out=root/'evidence';out.mkdir();original=root/'original/include/mdds';original.mkdir(parents=True)
            for filename in ('multi_type_matrix.hpp','multi_type_matrix_def.inl'):(original/filename).write_bytes(b'preserved source')
            sources=[observation.base.identity(original/name) for name in ('multi_type_matrix.hpp','multi_type_matrix_def.inl')]
            obj=out/'matrix-include.obj';data=bytearray(56);data[:4]=b'\0\0\xff\xff';struct.pack_into('<HH',data,4,2,0xaa64);data[12:28]=bytes.fromhex('c7a1bad1eebaa94baf20faf66aa4dcb8');obj.write_bytes(data)
            case=dict(name='matrix-include',object=str(obj),sourceFiles=sources)
            (out/'matrix-include.command.json').write_text(json.dumps(self.command()))
            log=self.log()+''.join('Note: including file: '+s['path']+'\n' for s in sources)
            (out/'matrix-include.stdout.log').write_text(log);(out/'matrix-include.stderr.log').write_text('')
            result=admit(out,case)
            self.assertEqual(result['classification'],'compile-success')
            self.assertEqual(result['object']['machine'],0xaa64)
            self.assertFalse(result['runtimeTested'])
            self.assertFalse(result['productQualified'])
            for change in ('missing-include','changed-source','foreign-object','error-output'):
                with self.subTest(change=change):
                    obj.write_bytes(data);(out/'matrix-include.stdout.log').write_text(log)
                    for s in sources:Path(s['path']).write_bytes(b'preserved source')
                    if change=='missing-include':(out/'matrix-include.stdout.log').write_text(self.log())
                    elif change=='changed-source':Path(sources[0]['path']).write_bytes(b'drift')
                    elif change=='foreign-object':obj.write_bytes(b'\x64\x86'+bytes(54))
                    else:
                        (out/'matrix-include.command.json').write_text(json.dumps(self.command(2)))
                        (out/'matrix-include.stdout.log').write_text(log+'error C2143: syntax\n')
                    with self.assertRaises(ValueError):admit(out,case)

    def test_aggregate_admits_normal_parse_errors_but_rejects_incomplete_second_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp);cases=[]
            for name in observation.CASES:
                case=dict(name=name,object=str(out/(name+'.obj')),sourceFiles=[])
                cases.append(case)
                (out/(name+'.command.json')).write_text(json.dumps(self.command(2)))
                (out/(name+'.stdout.log')).write_text(self.log('fatal error C1083: missing dependency'))
                (out/(name+'.stderr.log')).write_text('')
            (out/'matrix-plan.json').write_text(json.dumps(dict(cases=cases,limits='fixture scope only')))
            observation.admit(out,cases[0]['name'])
            observation.admit(out)
            result=json.loads((out/'matrix-admission.json').read_bytes())
            self.assertEqual([case['classification'] for case in result['cases']],['unrelated-compiler-error']*2)
            self.assertTrue(result['observationAdmitted']);self.assertFalse(result['runtimeTested'])
            self.assertFalse(result['productQualified']);self.assertFalse(result['engineQualified'])
            self.assertEqual(result['cases'][0]['command']['creationUtcTicks'],639278626391148272)
            (out/'matrix-admission.json').unlink()
            (out/(cases[1]['name']+'.command.json')).write_text(json.dumps(dict(self.command(2),pipeDrainComplete=False)))
            with self.assertRaises(ValueError):observation.admit(out)
            self.assertFalse((out/'matrix-admission.json').exists())


class RunnerContracts(unittest.TestCase):
    def test_import_preserves_distinct_matrix_arguments_and_never_runs_old_probe(self):
        import os
        import shutil
        import subprocess
        driver=ROOT/'suite/scripts/probe-native-mdds-matrix.ps1'
        self.assertTrue(driver.is_file(), 'matrix companion runner is not implemented')
        pwsh=os.environ.get('OPENGEUL_MDDS_PWSH') or shutil.which('pwsh')
        if not pwsh:self.skipTest('PowerShell unavailable')
        script=r'''
param([string]$Driver)
. $Driver -MatrixOutput 'output-sentinel' -MatrixWorkRoot 'work-sentinel' -MatrixDeadline 'deadline-sentinel'
if($MatrixOutput -cne 'output-sentinel' -or $MatrixWorkRoot -cne 'work-sentinel' -or $MatrixDeadline -cne 'deadline-sentinel'){throw 'Companion import reset matrix arguments.'}
if(-not(Get-Command Get-MddsToolchainEnvironment -ErrorAction SilentlyContinue)){throw 'Missing reused toolchain helper.'}
if(-not(Get-Command Invoke-LoggedCommand -ErrorAction SilentlyContinue)){throw 'Missing reused owned command helper.'}
'''
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'import.ps1';path.write_text(script)
            result=subprocess.run([pwsh,'-NoLogo','-NoProfile','-File',str(path),str(driver)],text=True,capture_output=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        source=driver.read_text()
        self.assertNotIn('Invoke-NativeMddsProbe $',source)
        self.assertNotIn('candidate-runtime',source)
        self.assertNotIn("'/link'",source)
        self.assertIn("'/c'",source)
        workflow=(ROOT/'.github/workflows/office-native-mdds-matrix-probe.yml').read_text()
        self.assertIn('branches: [work/opengeul-office-native-mdds-matrix-probe]',workflow)
        self.assertIn('probe-native-mdds-matrix.ps1 -MatrixOutput',workflow)
        self.assertNotIn('probe-native-mdds.ps1 -Output',workflow)


class SourcePreparationTests(unittest.TestCase):
    def test_prepare_preserves_exact_original_sources_and_refuses_candidate_scope(self):
        import os
        import shutil
        actual=os.environ.get('OPENGEUL_MDDS_REAL_SOURCE')
        if not actual:self.skipTest('Set authenticated original MDDS directory for source preparation checks')
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp);work=tmp/'work';work.mkdir();original=work/'original'
            for name in list(observation.SOURCE_PINS)+['example/multi_type_matrix.cpp','test/multi_type_matrix/test_main.cpp']:
                target=original/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(Path(actual)/name,target)
            source=dict(cases=[dict(name='original',root=str(original),include=str(original/'include')),dict(name='candidate',root=str(work/'candidate'))],boostInclude=str(work/'boost'))
            def output(name,plan):
                out=tmp/name;out.mkdir();(out/'source-plan.json').write_text(json.dumps(plan));return out
            plan=observation.prepare(output('valid',source),work,ROOT/'suite/scripts')
            self.assertEqual([c['name'] for c in plan['cases']],['matrix-include','matrix-builtin-equality'])
            self.assertFalse(plan['oldFlatCompiled']);self.assertFalse(plan['candidateCompiled']);self.assertFalse(plan['runtimeTested'])
            self.assertTrue(plan['originalMatrixUnchanged'])
            for case in plan['cases']:
                self.assertEqual(case['include'],str(original/'include'))
                self.assertEqual(len(case['sourceFiles']),5)
            with self.assertRaises((ValueError,FileExistsError)):observation.prepare(tmp/'valid',work,ROOT/'suite/scripts')
            foreign=json.loads(json.dumps(source));foreign['cases'][0]['include']=str(work/'candidate/include')
            with self.assertRaises(ValueError):observation.prepare(output('foreign-include',foreign),work,ROOT/'suite/scripts')
            (original/'include/mdds/multi_type_matrix.hpp').write_bytes(b'drift')
            with self.assertRaises(ValueError):observation.prepare(output('drift',source),work,ROOT/'suite/scripts')


if __name__=='__main__':unittest.main()
