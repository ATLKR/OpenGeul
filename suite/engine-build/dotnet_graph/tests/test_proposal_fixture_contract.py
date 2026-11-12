"""Portable checks of proposal fixtures only; never SDK/source qualification."""
import hashlib
import json
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET
import yaml
BASE=Path(__file__).resolve().parents[1]
NAMES=('net_basetypes','net_uretypes','net_oootypes','net_bridge')
GRAPH={'net_basetypes':[],'net_uretypes':['net_basetypes'],'net_oootypes':['net_uretypes'],'net_bridge':['net_uretypes']}
class FixtureContract(unittest.TestCase):
    def test_all_source_pins_preserve_exact_public_snapshot(self):
        c=json.loads((BASE/'fixtures/contract.json').read_bytes())
        for p in c['sourcePins']:
            data=(BASE/'source-snapshot'/p['path']).read_bytes()
            self.assertEqual(len(data),p['bytes'])
            self.assertEqual(hashlib.sha256(data).hexdigest(),p['sha256'])
            self.assertEqual(hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest(),p['gitBlob'])
    def test_actual_gmake_baseline_preserves_original_project_graph(self):
        for name in NAMES:
            r=ET.fromstring((BASE/'tests/fixtures/gmake/DotnetLibrary'/name/(name+'.csproj')).read_bytes())
            self.assertEqual(r.findtext('PropertyGroup/TargetFramework'),'netstandard2.0')
            self.assertEqual(r.findtext('PropertyGroup/AssemblyName'),name)
            self.assertEqual([Path(x.attrib['Include']).stem for x in r.findall('ItemGroup/ProjectReference')],GRAPH[name])
        bridge=ET.fromstring((BASE/'tests/fixtures/gmake/DotnetLibrary/net_bridge/net_bridge.csproj').read_bytes())
        self.assertEqual([(x.attrib['Include'],x.attrib['Version']) for x in bridge.findall('ItemGroup/PackageReference')],[('System.Reflection.DispatchProxy','4.7.1')])
    def test_candidate_fixed_own_output_and_reference_build_property(self):
        for name in NAMES:
            p=BASE/'templates/candidate'/(name+'.csproj')
            self.assertTrue(p.is_file(),'candidate project fixture is required')
            r=ET.fromstring(p.read_bytes())
            self.assertEqual(r.findtext('PropertyGroup/OutputPath'),'@VARIANT_ROOT@/DotnetLibrary/'+name+'/')
            self.assertEqual(r.findtext('PropertyGroup/AppendTargetFrameworkToOutputPath'),'false')
            self.assertEqual(r.findtext('PropertyGroup/BuildProjectReferences'),'false')
    def test_candidate_preserves_project_reference_and_package_metadata(self):
        for name in NAMES:
            p=BASE/'templates/candidate'/(name+'.csproj')
            self.assertTrue(p.is_file(),'candidate reference fixture is required')
            r=ET.fromstring(p.read_bytes())
            refs=r.findall('ItemGroup/ProjectReference')
            self.assertEqual([Path(x.attrib['Include']).stem for x in refs],GRAPH[name])
            self.assertTrue(all(x.attrib.get('GlobalPropertiesToRemove')=='OutputPath;OutDir' for x in refs))
            before=ET.fromstring((BASE/'tests/fixtures/gmake/DotnetLibrary'/name/(name+'.csproj')).read_bytes())
            self.assertEqual([x.attrib for x in r.findall('ItemGroup/PackageReference')],[x.attrib for x in before.findall('ItemGroup/PackageReference')])
    def test_workflow_existing_full_body_is_unchanged(self):
        old=yaml.safe_load((BASE/'tests/fixtures/workflow.before.yml').read_bytes())
        new=yaml.safe_load((BASE.parents[2]/'.github/workflows/office-native-engine.yml').read_bytes())
        full=dict(new['jobs']['native-firebird-and-office']);full.pop('if')
        self.assertEqual(full,old['jobs']['native-firebird-and-office'])
        self.assertEqual(old['on']['push']['paths'],new['on']['push']['paths'])
        self.assertEqual(new['on']['push']['branches'],old['on']['push']['branches']+['work/opengeul-office-dotnet-graph-diagnostic'])
        self.assertEqual(old['permissions'],new['permissions'])
        self.assertEqual(new['on']['workflow_dispatch'],old['on']['workflow_dispatch'])
    def test_diagnostic_job_only_is_bounded_isolated_and_nonshipping(self):
        v=yaml.safe_load((BASE.parents[2]/'.github/workflows/office-native-engine.yml').read_bytes())
        j=v['jobs']['dotnet-graph-diagnostic']
        self.assertEqual(j['runs-on'],'windows-11-arm');self.assertEqual(j['timeout-minutes'],15)
        self.assertIn("github.event_name == 'push'",j['if'])
        self.assertIn("github.ref == 'refs/heads/work/opengeul-office-dotnet-graph-diagnostic'",j['if'])
        uploads=[s for s in j['steps'] if s.get('uses','').startswith('actions/upload-artifact@')]
        self.assertEqual(len(uploads),1)
        self.assertEqual(uploads[0]['with']['path'],'.work/dotnet-graph-diagnostic/dotnet-graph-diagnostic.json')
    def test_synthetic_contract_never_claims_sdk_or_full_qualification(self):
        c=json.loads((BASE/'fixtures/contract.json').read_bytes())
        self.assertEqual(c['graph'],GRAPH)
        for key in ('sdkExecutionVerified','sourcePortApplied','sourceFullQualified','acceptanceEligible','nativeGuiVerified'):
            self.assertIs(c[key],False)
        self.assertEqual(c['nugetFixtureId'],'OpenGeul.Diagnostic.Only')
        self.assertEqual(len(c['nugetDllMembers']),4)
