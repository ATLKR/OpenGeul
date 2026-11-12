"""Real GNU make metadata/CLI checks; no SDK or Windows execution."""
import hashlib
import copy
import importlib.util
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

REGRESSION=Path(__file__).resolve().parents[1]
ROOT=REGRESSION.parents[2]
BEFORE=REGRESSION/'fixtures/source-before'
AFTER=REGRESSION/'fixtures/source-after'
MAKE=None  # Explicit existing tool supplied by runner; no discovery/install.
NAMES=('net_basetypes','net_uretypes','net_oootypes','net_bridge')
CORE='9dea406ab7695df6325b11b0e19fdca8db4b7276'
PINS=[dict(path='solenv/gbuild/DotnetLibrary.mk',size=5315,
    sha256='f4d2e54af51037267b4027461d7caa6c7a22d3660b99bedeb68f2160d46f476b',afterSize=5728,
    afterSha256='cc1e4a62d0d97681b1742ada794af15945e465af86d4d2f54b38b245c8889db3'),
    dict(path='solenv/gbuild/DotnetTest.mk',size=5154,
    sha256='5391ab97bd1a43c71584afd2819499c1fca75ab95a2e35835dc7e10a02813272',afterSize=5555,
    afterSha256='09987ad29eb2afac9f2ff7a973bd2b7c32ccd54f286a4281610b5bc89fe939f7')]

def descriptor():return dict(schemaVersion=1,coreCommit=CORE,sources=copy.deepcopy(PINS))

def module():
    p=ROOT/'suite/engine-build/apply_native_source.py'
    spec=importlib.util.spec_from_file_location('dotnet_graph_producer_under_test',p)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def render(snapshot,root,debug=False):
    root.mkdir(); source=root/'source';source.mkdir();work=root/'work';work.mkdir()
    for name in NAMES:
        (work/'DotnetLibrary'/name).mkdir(parents=True)
    (work/'DotnetTest/net_graph_tests').mkdir(parents=True)
    stub=root/'owned-sdk-version'
    stub.write_text('#!/bin/sh\n[ "$#" = 1 ] && [ "$1" = --version ] || exit 97\nprintf "10.0.404\\n"\n')
    stub.chmod(0o700)
    text=(REGRESSION/'fixtures/TargetLocations.excerpt.mk').read_text()
    text+='\n'.join([
        '\n.DEFAULT_GOAL := fixture','gb_CustomTarget_workdir := $(WORKDIR)/CustomTarget',
        'gb_DotnetLibrary_get_clean_target = $(WORKDIR)/DotnetLibrary/$(1)/clean',
        'gb_DotnetTest_get_clean_target = $(WORKDIR)/DotnetTest/$(1)/clean',
        'gb_CustomTarget_get_target = $(WORKDIR)/CustomTarget/$(1)/done',
        'gb_Helper_abbreviate_dirs = $(1)','gb_Helper_print_on_error = $(1)',
        'gb_Helper_make_userfriendly_targets =','gb_Helper_make_userfriendly_targets =',
        'gb_Module_register_target =','gb_Output_announce =','gb_Trace_StartRange =','gb_Trace_EndRange =',
        'include $(SNAPSHOT)/solenv/gbuild/DotnetLibrary.mk',
        'include $(SNAPSHOT)/solenv/gbuild/DotnetTest.mk',
        *['include $(SNAPSHOT)/net_ure/DotnetLibrary_'+n+'.mk' for n in NAMES],
        '$(eval $(call gb_DotnetTest_DotnetTest,net_graph_tests,$(gb_DotnetTest_CS)))',
        '$(eval $(call gb_DotnetTest_add_sources,net_graph_tests,synthetic/Test))',
        '$(eval $(call gb_DotnetTest_link_library,net_graph_tests,net_oootypes))',
        '$(eval $(call gb_DotnetTest_link_library,net_graph_tests,net_bridge))',
        '$(call gb_CustomTarget_get_target,net_ure/net_uretypes) $(call gb_CustomTarget_get_target,net_ure/net_oootypes):',
        '\t@true','%/done:\n\t@true','%.cs:\n\t@true',
        '.PHONY: fixture',
        'fixture: $(foreach n,'+' '.join(NAMES)+',$(call gb_DotnetLibrary_get_target,$(n))) $(call gb_DotnetTest_get_target,net_graph_tests)',
        '',''])
    makefile=root/'metadata.mk';makefile.write_text(text)
    output=root/'make.numeric-input';commands=[str(MAKE),'--no-print-directory','-pn','-f',str(makefile),
        'SNAPSHOT='+str(snapshot),'WORKDIR='+str(work),'SRCDIR='+str(source),'DOTNET='+str(stub),
        'ENABLE_DEBUG='+('TRUE' if debug else ''),'fixture']
    with output.open('xb') as out:
        p=subprocess.Popen(commands,stdin=subprocess.DEVNULL,stdout=out,stderr=subprocess.DEVNULL,
            env={'PATH':'/usr/bin:/bin','LC_ALL':'C'})
        try:exit_code=p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill();p.wait(timeout=1);raise AssertionError('GNU make finite metadata deadline') from None
    if exit_code!=0 or not 0<output.stat().st_size<=512*1024:raise AssertionError('GNU make metadata generation failed')
    raw=output.read_text();output.unlink()
    commands=[]
    for line in raw.splitlines():
        if line.startswith('"'+str(stub)+'" '):commands.append(shlex.split(line))
    projects={n:ET.parse(work/'DotnetLibrary'/n/(n+'.csproj')).getroot() for n in NAMES}
    projects['net_graph_tests']=ET.parse(work/'DotnetTest/net_graph_tests/net_graph_tests.csproj').getroot()
    return dict(projects=projects,commands=commands,database=raw,root=root,work=work,stub=stub)

def semantic(project,root):
    clone=ET.fromstring(ET.tostring(project))
    for group in clone.findall('PropertyGroup'):
        for node in list(group):
            if node.tag in ('OutputPath','AppendTargetFrameworkToOutputPath','BuildProjectReferences'):group.remove(node)
    for node in clone.findall('ItemGroup/ProjectReference'):node.attrib.pop('GlobalPropertiesToRemove',None)
    def normalized(node):
        return (node.tag,tuple(sorted((k,v.replace(str(root),'<owned>')) for k,v in node.attrib.items())),
                (node.text or '').strip().replace(str(root),'<owned>'),tuple(normalized(n) for n in node))
    return normalized(clone)

def native_fragment(snapshot,folder,kind,workdir):
    """Expand the real constructor with a native drive path, without parsing it
    as a POSIX make target. This is Linux gmake expansion, not a Cygwin run.
    """
    output=folder/(kind+'.fragment');makefile=folder/(kind+'.mk')
    prefix='gb_Dotnet'+kind
    source=('WORKDIR := '+workdir+'\n'+(REGRESSION/'fixtures/TargetLocations.excerpt.mk').read_text()+
        'gb_DotnetLibrary_child_project := '+workdir+'/DotnetLibrary/child/child.csproj\n'+
        'include '+str(snapshot/'solenv/gbuild'/('Dotnet'+kind+'.mk'))+'\n'+
        '$(file >'+str(output)+',$(call '+prefix+'_Dotnet'+kind+',owned,cs))\n'+
        '$(file >>'+str(output)+',$(call '+prefix+'_link_library,owned,child))\n'+
        '.PHONY: fixture\nfixture:\n\t@true\n')
    makefile.write_text(source,encoding='utf-8')
    p=subprocess.Popen([str(MAKE),'--no-print-directory','-n','-f',str(makefile),'fixture'],
        stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
        env={'PATH':'/usr/bin:/bin','LC_ALL':'C'})
    try:code=p.wait(timeout=10)
    except subprocess.TimeoutExpired:
        p.kill();p.wait(timeout=1);raise AssertionError('Native path expansion deadline') from None
    if code!=0 or not 0<output.stat().st_size<=32*1024:raise AssertionError('Native path expansion failed')
    return output.read_text(encoding='utf-8')

class GmakeGraphContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.folder=Path(cls.temp.name).resolve()
        cls.before=render(BEFORE,cls.folder/'before')
        cls.after=render(AFTER,cls.folder/'after')

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_candidate_outputs_equal_original_cli_target_directories(self):
        self.assertEqual(5,len(self.before['commands']))
        for name,project in self.after['projects'].items():
            kind='DotnetTest' if name=='net_graph_tests' else 'DotnetLibrary'
            self.assertEqual(str(self.after['work']/kind/name)+'/',project.findtext('PropertyGroup/OutputPath'))
            self.assertEqual('false',project.findtext('PropertyGroup/AppendTargetFrameworkToOutputPath'))
            self.assertEqual('false',project.findtext('PropertyGroup/BuildProjectReferences'))
        for command in self.before['commands']:
            self.assertIn('-o',command)
            self.assertEqual(str(Path(command[2]).parent)+'/',command[command.index('-o')+1])

    def test_candidate_cli_preserves_build_and_test_configuration_without_global_output(self):
        self.assertEqual(5,len(self.after['commands']))
        self.assertEqual(['build']*4+['test'],[x[1] for x in self.after['commands']])
        for command in self.after['commands']:
            self.assertNotIn('-o',command);self.assertEqual(['-c','Release'],command[3:])

    def test_project_reference_keeps_metadata_but_drops_inherited_output(self):
        count=0
        for project in self.after['projects'].values():
            for reference in project.findall('ItemGroup/ProjectReference'):
                count+=1;self.assertEqual('OutputPath;OutDir',reference.get('GlobalPropertiesToRemove'))
        self.assertEqual(5,count)

    def test_original_property_item_and_package_metadata_is_preserved(self):
        for name in self.before['projects']:
            self.assertEqual(semantic(self.before['projects'][name],self.before['root']),
                             semantic(self.after['projects'][name],self.after['root']))
        tests=self.after['projects']['net_graph_tests']
        self.assertEqual('net10.0',tests.findtext('PropertyGroup/TargetFramework'))
        self.assertEqual('true',tests.findtext('PropertyGroup/IsTestProject'))
        self.assertEqual('false',tests.findtext('PropertyGroup/IsPackable'))
        self.assertEqual([('NUnit','4.1.0'),('NUnit3TestAdapter','4.5.0'),('Microsoft.NET.Test.Sdk','17.10.0')],
            [(n.get('Include'),n.get('Version')) for n in tests.findall('ItemGroup/PackageReference')])
        for name in NAMES:self.assertEqual('netstandard2.0',self.after['projects'][name].findtext('PropertyGroup/TargetFramework'))
        self.assertEqual([('System.Reflection.DispatchProxy','4.7.1')],
            [(n.get('Include'),n.get('Version')) for n in self.after['projects']['net_bridge'].findall('ItemGroup/PackageReference')])

    def test_actual_make_database_keeps_gmake_prerequisites_and_test_phony_done(self):
        def row(run,name,kind='DotnetLibrary',ending=None):
            target=run['work']/kind/name/(ending or name+'.csproj')
            found=[s for s in run['database'].splitlines() if s.startswith(str(target)+': ')]
            return '\n'.join(found)
        for name,child in [('net_uretypes','net_basetypes'),('net_oootypes','net_uretypes'),('net_bridge','net_uretypes')]:
            self.assertIn(str(self.after['work']/'DotnetLibrary'/child/(child+'.dll')),row(self.after,name))
        for child in ('net_oootypes','net_bridge'):
            self.assertIn(str(self.after['work']/'DotnetLibrary'/child/(child+'.dll')),row(self.after,'net_graph_tests','DotnetTest'))
        done=str(self.after['work']/'DotnetTest/net_graph_tests/done')
        self.assertIn('.PHONY: ',self.after['database'])
        phony=next(s for s in self.after['database'].splitlines() if s.startswith('.PHONY: '))
        self.assertIn(done,phony)
        self.assertFalse(Path(done).exists())

    def test_package_content_source_is_byte_identical_and_maps_four_gbuild_dlls(self):
        rel='net_ure/CustomTarget_net_nuget_pkg.mk'
        self.assertEqual((BEFORE/rel).read_bytes(),(AFTER/rel).read_bytes())
        raw=(AFTER/rel).read_text()
        self.assertEqual(4,raw.count('Pack="true" PackagePath="lib/$$(TargetFramework)"'))
        self.assertIn('"$(DOTNET)" pack $< -o $(dir $@)',raw)

    def test_metadata_comparison_still_detects_package_or_property_drift(self):
        original=self.after['projects']['net_bridge']
        for tag in ('Version','Company','Description','TargetFramework'):
            changed=ET.fromstring(ET.tostring(original));changed.find('PropertyGroup/'+tag).text='changed'
            self.assertNotEqual(semantic(original,self.after['root']),semantic(changed,self.after['root']))
        changed=ET.fromstring(ET.tostring(original))
        changed.find('ItemGroup/PackageReference').set('Version','4.7.2')
        self.assertNotEqual(semantic(original,self.after['root']),semantic(changed,self.after['root']))

    def test_native_drive_output_and_original_reference_use_the_same_gbuild_root(self):
        for index,workdir in enumerate(('C:/synthetic/native-work','D:/synthetic/한글-work')):
            for kind in ('Library','Test'):
                folder=self.folder/('drive-'+str(index)+'-'+kind);folder.mkdir()
                text=native_fragment(AFTER,folder,kind,workdir)
                value=re.search(r'<OutputPath>([^<]+)</OutputPath>',text)
                self.assertIsNotNone(value)
                self.assertEqual(workdir+'/Dotnet'+kind+'/owned/',value.group(1))
                self.assertIn('<ProjectReference Include="'+workdir+'/DotnetLibrary/child/child.csproj" GlobalPropertiesToRemove="OutputPath;OutDir"/>',text)
                self.assertNotIn('gb_Helper_native_path',text)

    def test_debug_configuration_uses_the_same_owned_output_policy(self):
        run=render(AFTER,self.folder/'debug',debug=True)
        for command in run['commands']:self.assertEqual(['-c','Debug'],command[3:])
        for name,p in run['projects'].items():
            kind='DotnetTest' if name=='net_graph_tests' else 'DotnetLibrary'
            self.assertEqual(str(run['work']/kind/name)+'/',p.findtext('PropertyGroup/OutputPath'))

class DotnetSourceRecipeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.module=module()

    def test_exact_original_transform_matches_independent_after_fixture(self):
        for pin in PINS:
            self.assertEqual((AFTER/pin['path']).read_bytes(),
                self.module._dotnet_graph_bytes((BEFORE/pin['path']).read_bytes(),pin))

    def test_descriptor_has_exact_order_keys_types_and_source_identity(self):
        value=descriptor();pins=self.module._dotnet_graph_pins(value)
        self.assertEqual([p['path'] for p in PINS],[p['path'] for p in pins])
        for change in (lambda d:d.update(extra=False),lambda d:d.update(schemaVersion=True),
                       lambda d:d.update(coreCommit='b'*40),lambda d:d['sources'].reverse(),
                       lambda d:d['sources'].pop(),lambda d:d['sources'][0].update(size=True),
                       lambda d:d['sources'][0].update(afterSize=5728.0),
                       lambda d:d['sources'][0].update(afterSha256='a'*64),
                       lambda d:d['sources'][0].update(path='../escape'),
                       lambda d:d['sources'][0].update(extra=False)):
            changed=descriptor();change(changed)
            with self.assertRaises(ValueError):self.module._dotnet_graph_pins(changed)

    def test_changed_repeated_and_forged_originals_are_rejected(self):
        for pin in PINS:
            before=(BEFORE/pin['path']).read_bytes();after=(AFTER/pin['path']).read_bytes()
            for raw in (before+b'\n',after,bytearray(before)):
                with self.assertRaises(ValueError):self.module._dotnet_graph_bytes(raw,pin)
            changed=dict(pin,sha256=hashlib.sha256(before+b'\n').hexdigest(),size=len(before)+1)
            with self.assertRaises(ValueError):self.module._dotnet_graph_bytes(before+b'\n',changed)

    def test_both_normal_source_plans_require_graph_hook_and_two_source_pins(self):
        lock=json.loads((ROOT/'suite/engine-build/source-build.json').read_bytes())
        policy=(ROOT/'suite/engine-build/native-targets.json').read_bytes()
        for arch in ('arm64','x64'):
            plan=self.module._select_plan(lock,policy,arch)
            self.assertEqual('dotnetProjectGraph',plan['recipe']['hooks'][-1])
            selected={p['path']:p for p in plan['sources']}
            for pin in PINS:
                self.assertEqual(pin['sha256'],selected[pin['path']]['beforeSha256'])
                self.assertEqual(pin['afterSha256'],selected[pin['path']]['afterSha256'])

    def test_missing_or_receipt_selected_graph_descriptor_is_rejected(self):
        lock=json.loads((ROOT/'suite/engine-build/source-build.json').read_bytes())
        policy=(ROOT/'suite/engine-build/native-targets.json').read_bytes()
        for change in (lambda d:d.pop('windowsDotnetProjectGraph',None),
                       lambda d:d.update(windowsDotnetProjectGraph=descriptor())):
            changed=copy.deepcopy(lock);change(changed)
            if 'windowsDotnetProjectGraph' in changed:
                changed['windowsDotnetProjectGraph']['sources'][0]['afterSha256']='a'*64
            for arch in ('arm64','x64'):
                with self.assertRaises(ValueError):self.module._select_plan(changed,policy,arch)

    def roots(self,folder):
        source=folder/'source';evidence=folder/'evidence';source.mkdir();evidence.mkdir()
        for pin in PINS:
            p=source/pin['path'];p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((BEFORE/pin['path']).read_bytes())
        return source,evidence

    def test_install_retains_original_and_effective_bytes_and_false_flags(self):
        for arch in ('arm64','x64'):
            with tempfile.TemporaryDirectory() as tmp:
                source,evidence=self.roots(Path(tmp).resolve())
                proof=self.module._install_dotnet_project_graph(source,evidence,descriptor(),arch)
                self.assertEqual('windows-dotnet-project-graph-source-hook',proof['kind'])
                self.assertEqual(arch,proof['architecture']);self.assertEqual(CORE,proof['coreCommit'])
                for key in ('nativeBuildVerified','fullEngineQualified','acceptanceEligible','guiVerified'):
                    self.assertIs(False,proof[key])
                self.assertEqual(2,len(proof['sources']))
                for pin,row in zip(PINS,proof['sources']):
                    self.assertEqual(pin['path'],row['path'])
                    self.assertEqual(pin['sha256'],hashlib.sha256(Path(row['evidence']['original']).read_bytes()).hexdigest())
                    self.assertEqual(pin['afterSha256'],hashlib.sha256(Path(row['evidence']['effective']).read_bytes()).hexdigest())
                    self.assertEqual((AFTER/pin['path']).read_bytes(),(source/pin['path']).read_bytes())
                with self.assertRaises(ValueError):self.module._install_dotnet_project_graph(source,evidence,descriptor(),arch)

    def test_install_prevalidates_all_sources_before_writing_either(self):
        with tempfile.TemporaryDirectory() as tmp:
            source,evidence=self.roots(Path(tmp).resolve())
            last=source/PINS[1]['path'];last.write_bytes(last.read_bytes()+b'\n')
            with self.assertRaises(ValueError):self.module._install_dotnet_project_graph(source,evidence,descriptor(),'arm64')
            self.assertEqual((BEFORE/PINS[0]['path']).read_bytes(),(source/PINS[0]['path']).read_bytes())
            self.assertEqual([],list(evidence.iterdir()))

    def test_install_rejects_preexisting_evidence_and_linked_source(self):
        for mode in ('evidence','symlink','hardlink','nested-root'):
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp).resolve();source,evidence=self.roots(root);p=source/PINS[0]['path']
                if mode=='evidence':(evidence/'original-DotnetTest.mk').write_bytes(b'owned')
                elif mode=='symlink':p.unlink();p.symlink_to(BEFORE/PINS[0]['path'])
                elif mode=='hardlink':
                    other=root/'owned-anchor.mk';other.write_bytes(p.read_bytes());p.unlink();p.hardlink_to(other)
                else:evidence=source/'evidence';evidence.mkdir()
                with self.assertRaises(ValueError):self.module._install_dotnet_project_graph(source,evidence,descriptor(),'arm64')

    def test_install_rejects_unreviewed_architecture(self):
        with tempfile.TemporaryDirectory() as tmp:
            source,evidence=self.roots(Path(tmp).resolve())
            for arch in ('ARM64','x86',True,None):
                with self.assertRaises(ValueError):self.module._install_dotnet_project_graph(source,evidence,descriptor(),arch)

if __name__=='__main__':unittest.main()
