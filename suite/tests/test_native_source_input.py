"""Source-only descriptors cannot impersonate an already qualified runtime."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
DRIVER = ROOT/'suite/scripts/build-native-engine.ps1'
INPUT = ROOT/'suite/engine-build/source-input.lock.json'
PWSH = shutil.which('pwsh')


def quote(value):
    return "'"+str(value).replace("'", "''")+"'"


@unittest.skipUnless(PWSH, 'PowerShell is required for the actual source admission boundary')
class NativeSourceInputTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def ps(self, body, accepted=True):
        script=self.root/'case.ps1'
        script.write_text("$ErrorActionPreference='Stop'\n. "+quote(DRIVER)+'\n'+body)
        result=subprocess.run([PWSH,'-NoLogo','-NoProfile','-NonInteractive','-File',str(script)],
                              stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=20)
        self.assertEqual(result.returncode==0,accepted,'source admission returned the wrong status')
        return result.stdout

    def test_source_only_input_accepts_the_exact_new_source_without_qualification(self):
        descriptor=json.loads(INPUT.read_bytes())
        actual=json.loads(self.ps('Get-SourcePin '+quote(INPUT)+'|ConvertTo-Json -Compress'))
        self.assertEqual(actual,descriptor['source'])
        for field in ('nativeBuildVerified','fullEngineQualified','acceptanceEligible','guiVerified'):
            self.assertIs(descriptor[field],False)

    def test_changed_source_identity_and_qualification_claims_fail(self):
        original=json.loads(INPUT.read_bytes())
        variants=[]
        for field,value in [('version','26.8.1.1'),('coreCommit','bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1'),
                            ('url','https://example.org/source.tar.xz'),('size',True),('size',302823255),('sha256','0'*64)]:
            value_copy=copy.deepcopy(original);value_copy['source'][field]=value;variants.append(value_copy)
        for field in ('nativeBuildVerified','fullEngineQualified','acceptanceEligible','guiVerified'):
            value_copy=copy.deepcopy(original);value_copy[field]=True;variants.append(value_copy)
        for field in ('version','coreCommit','url','sha256'):
            value_copy=copy.deepcopy(original);value_copy['source'][field]=[value_copy['source'][field]];variants.append(value_copy)
        value_copy=copy.deepcopy(original);value_copy['kind']=[value_copy['kind']];variants.append(value_copy)
        for value in variants:
            path=self.root/'changed.json';path.write_text(json.dumps(value))
            self.ps('Get-SourcePin '+quote(path),accepted=False)

    def test_unknown_duplicate_and_missing_descriptor_members_fail(self):
        original=json.loads(INPUT.read_bytes())
        variants=[]
        changed=copy.deepcopy(original);changed['source']['archiveArtifact']='old qualified engine';variants.append(json.dumps(changed))
        changed=copy.deepcopy(original);changed['extra']=False;variants.append(json.dumps(changed))
        changed=copy.deepcopy(original);del changed['guiVerified'];variants.append(json.dumps(changed))
        variants.append(json.dumps(original).replace('"schemaVersion": 1','"schemaVersion": 1, "schemaVersion": 1'))
        for text in variants:
            path=self.root/'changed.json';path.write_text(text)
            self.ps('Get-SourcePin '+quote(path),accepted=False)

    def test_old_qualified_runtime_lock_is_not_new_source_input(self):
        for name in ('runtime.lock.json','runtime.arm64.lock.json'):
            self.ps('Get-SourcePin '+quote(ROOT/'suite/config'/name),accepted=False)

    def test_both_workflows_use_unqualified_source_input_and_keep_old_runtime_locks(self):
        for suffix in ('','-x64'):
            text=(ROOT/f'.github/workflows/office-native-engine{suffix}.yml').read_text()
            self.assertIn('-SourceLockPath suite/engine-build/source-input.lock.json',text)
        old=json.loads((ROOT/'suite/config/runtime.arm64.lock.json').read_bytes())['runtime']
        self.assertEqual(old['version'],'26.8.1.1')
        self.assertEqual(old['sourceCoreCommit'],'bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1')
        self.assertNotEqual(old['sourceSha256'],json.loads(INPUT.read_bytes())['source']['sha256'])

    def test_installed_fallback_derivation_binds_each_complete_source_profile(self):
        source=json.loads(INPUT.read_bytes())['source']
        pin=self.root/'pin.json';pin.write_text(json.dumps(source))
        configuration="@{LIBO_VERSION_MAJOR='26';LIBO_VERSION_MINOR='8';LIBO_VERSION_MICRO='2';LIBO_VERSION_PATCH='2';LIBO_VERSION_SUFFIX=''}"
        body='Get-InstalledIdentityDerivation (Get-Content '+quote(pin)+' -Raw|ConvertFrom-Json) '
        data=json.loads(self.ps(body+configuration+'|ConvertTo-Json -Compress'))
        self.assertEqual(data['buildid'],'680(Build:2)')
        self.assertEqual(data['rule'],'libreoffice-26.8.2.2-installer-no-git-v1')
        self.ps(body+configuration.replace("MICRO='2'","MICRO='1'"),accepted=False)
        source['coreCommit']='bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1';pin.write_text(json.dumps(source))
        self.ps(body+configuration,accepted=False)

    def test_python_path_family_cannot_cross_exact_core_boundary(self):
        old='bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1';new='9dea406ab7695df6325b11b0e19fdca8db4b7276'
        pins=json.loads(self.ps('@(Get-PinnedPythonTemplates arm64)|ConvertTo-Json -Compress'))
        for row in pins:
            self.assertTrue(row['path'].startswith('program/python-core-3.13.17/lib/'))
        row=pins[0];args=quote(row['path'])+' '+str(row['machine'])+' '+quote(row['sha256'])+' arm64 '
        self.ps('Assert-PythonTemplateAdmission '+args+quote(new))
        self.ps('Assert-PythonTemplateAdmission '+args+quote(old),accepted=False)
        historical=args.replace('3.13.17','3.13.15')
        self.ps('Assert-PythonTemplateAdmission '+historical+quote(old))
        self.ps('Assert-PythonTemplateAdmission '+historical+quote(new),accepted=False)
        self.ps('Get-PinnedPythonTemplates arm64 '+quote('0'*40),accepted=False)


if __name__=='__main__':
    unittest.main()
