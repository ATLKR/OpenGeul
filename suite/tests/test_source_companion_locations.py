"""Configured source products stay separate from installed-archive partial fixtures."""
from pathlib import Path
import copy
import ast
import inspect
import hashlib
import tempfile
import unittest
import test_source_companion as fixture
payload=fixture.payload

class LocationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.source=self.root/'source';self.runtime=self.root/'runtime'
        (self.source/'instdir/program').mkdir(parents=True);self.runtime.mkdir()
    def config(self,changes=None):
        values=dict(OS='WNT',CPUNAME='X86_64',SRCDIR=str(self.source),INSTROOT=str(self.source/'instdir'),LIBO_LIB_FOLDER='program',LIBO_BIN_FOLDER='program')
        values.update(changes or {})
        return ''.join(k+'='+v+'\n'for k,v in values.items()).encode()
    def test_actual_configured_instroot_and_separate_runtime_are_mandatory(self):
        raw=self.config();path,proof=payload._source_companion_locations(self.source,self.runtime,raw)
        self.assertEqual(path,self.source/'instdir')
        self.assertEqual(proof['configurationSha256'],hashlib.sha256(raw).hexdigest())
        self.assertEqual(proof['sourceProofs'],payload.SOURCE_COMPANION_LOCATION_PINS)
        self.assertEqual(payload._source_companion_location_contract(proof),proof)
    def test_unknown_missing_duplicate_and_unresolved_config_cannot_select_a_product(self):
        cases=[self.config({'OS':'LINUX'}),self.config({'CPUNAME':'AARCH64'}),self.config({'SRCDIR':str(self.root)}),
               self.config({'INSTROOT':str(self.runtime)}),self.config({'INSTROOT':str(self.source/'elsewhere')}),
               self.config({'INSTROOT':str(self.source/'one/../instdir')}),self.config({'INSTROOT':'$(SRCDIR)/instdir'}),
               self.config({'LIBO_LIB_FOLDER':'Program'}),self.config({'LIBO_BIN_FOLDER':'other'}),
               self.config()+b'INSTROOT=other\n',self.config().replace(b'LIBO_BIN_FOLDER=program\n',b'')]
        for raw in cases:
            with self.subTest(case=cases.index(raw)),self.assertRaises(ValueError):payload._source_companion_locations(self.source,self.runtime,raw)
    def test_location_contract_cannot_claim_drifted_original_sources_or_config(self):
        _,p=payload._source_companion_locations(self.source,self.runtime,self.config())
        cases=[]
        for key,value in [('schemaVersion',True),('schemaVersion',2),('coreCommit','0'*40),('configurationSha256','bad'),('sourceRelativeInstRoot','../instdir'),('libraryFolder','elsewhere')]:
            q=copy.deepcopy(p);q[key]=value;cases.append(q)
        q=copy.deepcopy(p);q['sourceProofs'][0]['sha256']='0'*64;cases.append(q)
        q=copy.deepcopy(p);q['sourceProofs'].pop();cases.append(q)
        q=copy.deepcopy(p);q['sourceProofs'][0]['bytes']=float(q['sourceProofs'][0]['bytes']);cases.append(q)
        q=copy.deepcopy(p);q['optional']=False;cases.append(q)
        for index,q in enumerate(cases):
            with self.subTest(case=index),self.assertRaises(ValueError):payload._source_companion_location_contract(q)
    def test_public_location_sources_are_exact_original_bytes(self):
        root=Path(__file__).parent/'fixtures/spsupp-source-9dea'
        self.assertEqual(len(payload.SOURCE_COMPANION_SOURCE_PINS),13)
        self.assertEqual(len(payload.SOURCE_COMPANION_LOCATION_PINS),3)
        for pin in payload.SOURCE_COMPANION_LOCATION_PINS:
            data=(root/pin['path']).read_bytes()
            self.assertEqual(len(data),pin['bytes']);self.assertEqual(hashlib.sha256(data).hexdigest(),pin['sha256'])
            self.assertEqual(hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest(),pin['gitBlob'])
    def test_physical_product_identity_is_typed_and_cannot_change_size_hash_or_path(self):
        actual=dict(size=1234,sha256='1'*64);record=dict(path='instdir/program/owned.dll',**actual)
        payload._source_companion_build_output(record,record['path'],actual)
        for key,value in [('size',True),('size',1233),('sha256','2'*64),('path','workdir/LinkTarget/Library/owned.dll')]:
            q=dict(record);q[key]=value
            with self.subTest(field=key),self.assertRaises(ValueError):payload._source_companion_build_output(q,record['path'],actual)
    def test_untyped_expected_peer_identity_fails_with_the_validator_error(self):
        for expected in (None,[],{},dict(size=True,sha256='1'*64)):
            with self.subTest(kind=type(expected).__name__),self.assertRaises(ValueError):
                payload._source_companion_build_output(dict(path='instdir/program/x.dll',size=1234,sha256='1'*64),'instdir/program/x.dll',expected)
    def test_failed_join_records_known_comparison_without_turning_it_into_authority(self):
        d=payload._source_companion_diagnostic()
        self.assertFalse(payload._source_companion_observe_join(3,dict(size=12,sha256='1'*64),13,'1'*64,d))
        self.assertEqual(d['comparisonAttemptMask'],4);self.assertEqual(d['sizeEqualMask'],0);self.assertEqual(d['hashEqualMask'],4)
        self.assertEqual(d['readCompleteMask'],0);self.assertEqual(d['identityVerifiedMask'],0)
    def test_closed_exception_diagnostic_does_not_read_message_or_arbitrary_locals(self):
        class MessageMustNotBeRead(ValueError):
            def __str__(self):raise AssertionError('No exception formatting')
        def owned():raise MessageMustNotBeRead('synthetic-sensitive-message')
        d=payload._source_companion_diagnostic()
        try:owned()
        except MessageMustNotBeRead as e:payload._source_companion_closed_exception(e,d,owned,RuntimeError)
        self.assertEqual(d['exceptionTypeCode'],0);self.assertEqual(d['sourceFrameCode'],1)
        self.assertGreater(d['sourceLine'],0);self.assertNotIn('exceptionMessage',d)

    def test_static_runtime_source_proofs_require_exact_typed_ordered_pair(self):
        pins=copy.deepcopy(payload.SOURCE_X86_COMPANION_CRT_PINS)
        payload._source_companion_static_runtime_contract(pins)
        for kind in ('missing','reorder','float','extra','old-effective'):
            rows=copy.deepcopy(pins)
            if kind=='missing':rows.pop()
            elif kind=='reorder':rows.reverse()
            elif kind=='float':rows[0]['afterSize']=float(rows[0]['afterSize'])
            elif kind=='extra':rows[0]['extra']=False
            else:rows[0]['afterSha256']=rows[0]['sha256']
            with self.subTest(kind=kind),self.assertRaises(ValueError):payload._source_companion_static_runtime_contract(rows)

    def test_both_partial_locations_join_the_exact_typed_parent_configuration_only(self):
        _,location=payload._source_companion_locations(self.source,self.runtime,self.config())
        first=dict(locationContract=copy.deepcopy(location));second=dict(locationContract=copy.deepcopy(location))
        parent=dict(configurationSha256=location['configurationSha256'])
        payload._source_companion_configuration_join(parent,first,second)
        self.assertNotIn('fullEngineQualified',parent)
        for kind in ('missing','untyped','different-parent','first-family','second-family'):
            p=copy.deepcopy(parent);a=copy.deepcopy(first);b=copy.deepcopy(second)
            if kind=='missing':p.clear()
            elif kind=='untyped':p['configurationSha256']=1234
            elif kind=='different-parent':p['configurationSha256']='1'*64
            elif kind=='first-family':a['locationContract']['configurationSha256']='2'*64
            else:b['locationContract']['configurationSha256']='3'*64
            with self.subTest(kind=kind),self.assertRaises(ValueError):payload._source_companion_configuration_join(p,a,b)
    def test_actual_internal_admissions_requires_the_two_family_configuration_join(self):
        tree=ast.parse(inspect.getsource(payload._source_companion_admissions))
        calls=[n for n in ast.walk(tree)if isinstance(n,ast.Call)and isinstance(n.func,ast.Name)and n.func.id=='_source_companion_configuration_join']
        self.assertEqual(len(calls),1)
        self.assertEqual([n.id for n in calls[0].args],['proof','component','twain'])
