from pathlib import Path
import unittest,yaml
ROOT=Path(__file__).resolve().parents[2]
class WiringTests(unittest.TestCase):
    def load(self):
        data=yaml.safe_load((ROOT/'.github/workflows/msix.yml').read_text())
        if True in data:data['on']=data.pop(True)
        return data
    def test_windows_producers_run_alongside_browsers_and_package_joins_both(self):
        jobs=self.load()['jobs'];self.assertIn('preflight',jobs)
        self.assertEqual(set(jobs['build']['needs']),{'preflight','wasm','windows-editor','windows-cli'})
        for role in ('editor','cli'):
            job=jobs['windows-'+role]
            self.assertEqual(set(job['needs']),{'preflight','wasm'})
            self.assertEqual(job['runs-on'],'windows-2025')
            self.assertIn("needs.preflight.outputs.mode == 'full'",job['if'])
            self.assertEqual(job['permissions'],{'contents':'read','actions':'read'})
            commands='\n'.join(s.get('run','') for s in job['steps'])
            if role == 'editor':
                from build_progress import build_command
                phases = [s for s in job['steps'] if 'ci/build_progress.py run ' in s.get('run','')]
                self.assertEqual([s['id'] for s in phases], ['editor-prepare','editor-native-tests','editor-release'])
                for stage, step in zip(('Prepare','NativeTests','Release'), phases):
                    self.assertEqual(step['run'], 'python ci/build_progress.py run --stage '+stage+' --architecture x64')
                    self.assertEqual(build_command(stage,'x64')[5:7], ['-Phase','Editor'])
                    self.assertNotIn('if', step)
            else:
                self.assertIn('-Phase '+role.capitalize(),commands)
            self.assertIn('opengeul-wasm-$env:GITHUB_RUN_ID',commands)
        self.assertEqual(jobs['browser-e2e']['needs'],'wasm')
        commands='\n'.join(s.get('run','') for s in jobs['build']['steps'])
        self.assertIn('-Phase Package',commands)
        for role in ('editor','cli'):
            self.assertIn('opengeul-'+role+'-component-$env:GITHUB_RUN_ID',commands)
        self.assertNotIn('cargo ',commands)
    def test_manual_engine_mode_never_reaches_release(self):
        w=self.load();options=w['on']['workflow_dispatch']['inputs']['mode']
        self.assertEqual(options['default'],'full');self.assertEqual(set(options['options']),{'full','engine','checks'})
        self.assertIn("needs.preflight.outputs.mode == 'full'",w['jobs']['build']['if'])
    def test_all_required_release_gates_remain(self):
        jobs=self.load()['jobs'];self.assertEqual(set(jobs['release']['needs']),{'wasm','build','build-arm64','native-e2e','native-e2e-arm64','browser-e2e','msix-install','msix-native-arm64','msix-install-arm64','virtual-print','virtual-print-arm64'})
        for job in ('native-e2e','virtual-print'):
            self.assertEqual(set(jobs[job]['strategy']['matrix']['os']),{'windows-2022','windows-2025'})
            self.assertEqual(jobs[job+'-arm64']['runs-on'],'windows-11-arm')
        self.assertEqual(set(jobs['browser-e2e']['strategy']['matrix']['browser']),{'chromium','firefox','webkit'})
    def test_diagnostics_are_bounded_before_upload(self):
        for job in ('native-e2e','native-e2e-arm64','virtual-print','virtual-print-arm64','browser-e2e','msix-install','msix-native-arm64','msix-install-arm64'):
            steps=self.load()['jobs'][job]['steps']
            pack=[i for i,s in enumerate(steps) if 'ci/evidence.py pack ' in s.get('run','')]
            self.assertEqual(len(pack),1)
            for i,s in enumerate(steps):
                if s.get('uses','').startswith('actions/upload-artifact') and s.get('id') != 'runner-ready-evidence':
                    if s.get('with',{}).get('path')=='mcp-qa/':
                        self.assertEqual(s['with']['name'],'opengeul-mcp-fixtures${{ env.E2E_INPUT_SUFFIX }}-${{ github.run_id }}')
                        self.assertEqual(s['if'],"env.E2E_ARCHITECTURE == 'arm64' || matrix.os == 'windows-2025'")
                        continue  # 별도 test_qa_upload가 원본 QA 입력·16 MiB 제한을 검사한다.
                    if s.get('id')=='synthetic-pdfs-evidence':
                        self.assertIn(job,('virtual-print','virtual-print-arm64'));continue  # exact7+manifest 전송은 별도 합성 PDF 계약 검사.
                    if 'native-transport/native-install.json' in s.get('with',{}).get('path',''):
                        self.assertEqual(job,'msix-native-arm64');continue  # exact3 transport 검사기는 별도로 검사한다.
                    self.assertGreater(i,pack[0]);self.assertEqual(s['with']['path'],'bounded-evidence/')
    def test_native_input_artifact_no_longer_duplicates_browser_dist(self):
        steps=self.load()['jobs']['windows-editor']['steps']
        uploads=[s for s in steps if 'opengeul-e2e-inputs-' in s.get('with',{}).get('name','')]
        self.assertEqual(len(uploads),1);self.assertEqual(uploads[0]['with']['path'],'.work/native-inputs/')
    def test_all_transports_have_pre_upload_size_checks(self):
        for job in ('wasm','windows-editor','windows-cli','build','windows-editor-arm64','windows-cli-arm64','build-arm64'):
            steps=self.load()['jobs'][job]['steps']
            uploads=sum(s.get('uses','').startswith('actions/upload-artifact') for s in steps)
            checks=sum('ci/evidence.py size ' in s.get('run','') for s in steps)
            for step in steps:
                if 'ci/build_progress.py run ' in step.get('run',''):
                    from build_progress import MAX_TOTAL, MAX_LOG
                    self.assertEqual(MAX_TOTAL, 16*1024*1024)
                    self.assertLessEqual(MAX_LOG, MAX_TOTAL-4096)
                    self.assertIn(step['id'], {'editor-prepare','editor-native-tests','editor-release'})
                    checks += 1
            self.assertEqual(uploads,checks)
    def test_password_ui_is_a_required_same_source_native_gate(self):
        jobs=self.load()['jobs'];steps=jobs['native-e2e']['steps']
        password=[s for s in steps if 'password/native.py' in s.get('run','')]
        self.assertEqual(len(password),1,'Native password safety must gate each Windows matrix member')
        self.assertNotIn('if',password[0]);self.assertFalse(password[0].get('continue-on-error',False))
        run=password[0]['run']
        for binding in ('--expected-source $env:GITHUB_SHA','--expected-run $env:GITHUB_RUN_ID',
                        '--output evidence/password-native'):
            self.assertIn(binding,run)
        self.assertIn('native-e2e',jobs['release']['needs'])
        self.assertTrue(any('opengeul-wasm-$env:GITHUB_RUN_ID' in s.get('run','') for s in steps))
        checkout=next(i for i,s in enumerate(steps) if s.get('uses','').startswith('actions/checkout'))
        self.assertTrue(any('core.autocrlf false' in s.get('run','') for s in steps[:checkout]))
    def test_mcp_is_required_after_original_password_generation_on_all_native_runners(self):
        jobs=self.load()['jobs']
        for name in ('native-e2e','native-e2e-arm64'):
            with self.subTest(job=name):
                steps=jobs[name]['steps'];mcp=[(i,s) for i,s in enumerate(steps) if 'e2e/mcp_worker.py' in s.get('run','')]
                self.assertEqual(len(mcp),1,'모든 실제 native OS에서 휴대용 MCP를 실행해야 합니다')
                index,step=mcp[0];self.assertNotIn('if',step);self.assertFalse(step.get('continue-on-error',False))
                prepare=next(i for i,s in enumerate(steps) if 'prepare_payload.py package runtime' in s.get('run',''))
                password=next(i for i,s in enumerate(steps) if 'generate-password-fixtures.mjs' in s.get('run',''))
                self.assertLess(prepare,password);self.assertLess(password,index)
                for flag in ('--context portable','--architecture $env:E2E_ARCHITECTURE','--exe runtime/Tools/rhwp.exe',
                             '--fixtures inputs/e2e-fixtures','--password-fixtures password-fixtures','--expected-sha256 $cliSha','--out evidence/mcp'):
                    self.assertIn(flag,step['run'])
                self.assertIn('windowsComponents.components.cli.sha256',step['run'])
                self.assertNotIn('Get-FileHash',step['run'],'기대 CLI 해시는 실행 파일이 아니라 package 증명에서 받아야 합니다')
    def test_qa_upload_is_arch_specific_original_bounded_one_day_input(self):
        jobs=self.load()['jobs']
        for name in ('native-e2e','native-e2e-arm64'):
            steps=jobs[name]['steps'];stages=[(i,s) for i,s in enumerate(steps) if 'e2e/mcp_fixtures.py stage' in s.get('run','')]
            uploads=[(i,s) for i,s in enumerate(steps) if s.get('with',{}).get('path')=='mcp-qa/']
            self.assertEqual(len(stages),1);self.assertEqual(len(uploads),1);i,stage=stages[0];j,upload=uploads[0]
            self.assertLess(i,j);self.assertEqual(stage['if'],"env.E2E_ARCHITECTURE == 'arm64' || matrix.os == 'windows-2025'")
            self.assertEqual(upload['if'],stage['if']);self.assertFalse(stage.get('continue-on-error',False))
            for binding in ('--architecture $env:E2E_ARCHITECTURE','--fixtures inputs/e2e-fixtures','--password-fixtures password-fixtures',
                            '--wasm-provenance wasm-input/OPEN_GEUL_WASM.json','--source-commit $env:GITHUB_SHA','--source-run $env:GITHUB_RUN_ID',
                            '--source-attempt $env:GITHUB_RUN_ATTEMPT','ci/evidence.py size --limit-mib 16 mcp-qa'):
                self.assertIn(binding,stage['run'])
            self.assertEqual(upload['with']['name'],'opengeul-mcp-fixtures${{ env.E2E_INPUT_SUFFIX }}-${{ github.run_id }}')
            self.assertEqual(upload['with']['retention-days'],1);self.assertEqual(upload['with']['if-no-files-found'],'error')
        cleanup=(ROOT/'ci/transport_cleanup.py').read_text();self.assertNotIn('opengeul-mcp-fixtures',cleanup)
    def test_installed_mcp_gets_same_arch_source_qa_before_any_install(self):
        jobs=self.load()['jobs']
        for name,build,native in (('msix-install','build','native-e2e'),('msix-native-arm64','build-arm64','native-e2e-arm64')):
            with self.subTest(job=name):
                job=jobs[name];self.assertEqual(set(job['needs']),{build,native});steps=job['steps']
                qa=[(i,s) for i,s in enumerate(steps) if 'scripts/mcp_qa_download.py' in s.get('run','')]
                self.assertEqual(len(qa),1);index,step=qa[0];self.assertNotIn('if',step)
                self.assertIn('scripts/mcp_qa_download.py source --package-directory package --output mcp-qa',step['run']);self.assertEqual(step['env']['GH_TOKEN'],'${{ github.token }}')
                install=next((i,s) for i,s in enumerate(steps) if './e2e/msix-install.ps1 ' in s.get('run',''))
                self.assertLess(index,install[0]);self.assertIn('-McpFixtureDirectory mcp-qa',install[1]['run'])
                self.assertIn('-ExpectedCliSha256 $cliSha',install[1]['run'])
                self.assertIn('windowsComponents.components.cli.sha256',install[1]['run'])
                self.assertEqual(job['permissions'],{'contents':'read','actions':'read'});self.assertEqual(job['timeout-minutes'],30)
if __name__=='__main__':unittest.main()
