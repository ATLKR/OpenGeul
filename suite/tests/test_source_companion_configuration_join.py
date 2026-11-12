"""Synthetic internal metadata units, not a Full receipt or engine adoption.

No artifact, ZIP, external lock, status/phase, executable qualification or actual
Windows is supplied. Production authentication guards are executed without mocks.
"""
import copy
import unittest
import test_source_companion as component_fixture
import test_source_twain as twain_fixture
payload=component_fixture.payload

class InternalConfigurationJoinTests(unittest.TestCase):
    def context(self):
        first=component_fixture.SourceCompanionTests();first.setUp();self.addCleanup(first.doCleanups)
        component=first.setup_component()
        other=twain_fixture.TwainTests();other.setUp();self.addCleanup(other.doCleanups);twain=other.component()
        core=payload._SOURCE_COMPANION_CORE;source=payload._PYTHON_TEMPLATE_SOURCES[core]
        runtime=dict(format='source-built-zip',sourceCoreCommit=core,**source)
        # Only the fields inspected by this internal consistency function are
        # present; this is deliberately incomplete for every external Full gate.
        metadata=dict(passed=True,fullEngineQualified=True,acceptanceEligible=True,guiVerified=False,
            sourcePin=dict(version=source['version'],coreCommit=core,url=source['sourceUrl'],size=302823256,sha256=source['sourceSha256']),
            sourceRecipeProof=dict(recipeSha256=first.binding['recipeSha256']),
            installedRuntimeStage=dict(receipt=dict(sha256=component['installedArchive']['stageReceiptSha256'])),
            configurationSha256=component['locationContract']['configurationSha256'],
            sourceCompanionProof=component,sourceTwainProof=twain,
            **{key:value for key,value in first.binding.items()if key!='recipeSha256'})
        self.assertNotIn('artifact',metadata);self.assertNotIn('status',metadata);self.assertNotIn('phase',metadata)
        return runtime,metadata
    def test_actual_internal_admissions_accepts_consistent_two_family_metadata_without_authority(self):
        runtime,metadata=self.context();before=copy.deepcopy((runtime,metadata))
        admitted=payload._source_companion_admissions(runtime,metadata,architecture='x64')
        self.assertEqual(set(admitted),{'program/spsupp_x86.dll','program/twain32shim.exe'})
        self.assertEqual((runtime,metadata),before)
        self.assertNotIn('fullEngineQualified',admitted)
        for key in ('passed','fullEngineQualified','acceptanceEligible'):
            row=copy.deepcopy(metadata);row[key]=False
            with self.subTest(guard=key),self.assertRaises(ValueError):payload._source_companion_admissions(runtime,row,architecture='x64')
    def test_actual_internal_admissions_rejects_parent_or_either_family_configuration_mismatch(self):
        runtime,metadata=self.context()
        for kind in ('missing','untyped','different-parent','first-family','second-family'):
            row=copy.deepcopy(metadata)
            if kind=='missing':row.pop('configurationSha256')
            elif kind=='untyped':row['configurationSha256']=False
            elif kind=='different-parent':row['configurationSha256']='1'*64
            elif kind=='first-family':row['sourceCompanionProof']['locationContract']['configurationSha256']='2'*64
            else:row['sourceTwainProof']['locationContract']['configurationSha256']='3'*64
            with self.subTest(kind=kind),self.assertRaises(ValueError):payload._source_companion_admissions(runtime,row,architecture='x64')
