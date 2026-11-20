"""Forward existing fixture lifetime metadata without changing runtime calls."""
import ast
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[2]
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module
smoke=load('lifetime_summary_producer',ROOT/'suite/e2e/engine_smoke.py')
publisher=load('lifetime_summary_publisher',ROOT/'suite/scripts/publish-engine-failure-summary.py')

def member(alive=True,wait=258,exit_code=259):
    return dict(pid=42,creationTime=123,handleValue=99,image='/SYNTHETIC-PRIVATE/soffice.bin',
                alive=alive,waitResult=wait,exitCode=exit_code,getExitCodeProcessResult=True)

def evidence():
    first=member();before=member(exit_code=0);final=member(False,0,0)
    return dict(expectedEngineImage=first['image'],initialMembers=[first],finalMembers=[final],
        snapshots=[dict(phase='fixture-before-first-load',members=[first]),
                   dict(phase='before-desktop-termination',members=[before]),
                   dict(phase='graceful',members=[final])],
        fixtureDesktopLifetime=dict(schemaVersion=1,kind='owned-generated-fixture-desktop-lifetime',
            scope='explicit-run-case-fixture',registration='returned',removal='returned',active=False,
            callbackFault=False,unexpectedTermination=True,omittedEvents=0,
            events=[dict(event='queryTermination',active=True),dict(event='queryTermination',active=False),
                    dict(event='notifyTermination',active=True),dict(event='disposing',active=True),
                    dict(event='notifyTermination',active=False)]))

def results(cleanup):
    return [dict(module=module,status='failed' if module=='writer' else 'passed',
        failureStage='load-factory',error=dict(type='DisposedException',message='SYNTHETIC-PRIVATE',
        traceback='SYNTHETIC-PRIVATE'),engineCleanup=cleanup if module=='writer' else {})
        for module in smoke.FILES]

def projected(cleanup):return smoke.failure_summary(results(cleanup))['cases'][0]['cleanup']

def expected_lease():
    return dict(active=False,registrationCode=3,removalCode=3,eventCount=5,
        activeQueryCount=1,activeNotifyCount=1,activeDisposingCount=1,
        callbackFault=False,unexpectedTermination=True,omittedEvents=0)

def expected_owner():
    return dict(pid=42,creationTime=123,handleValue=99,stateReadsAtomic=False,
        first=dict(alive=True,waitResult=258,exitCode=259,getExitCodeProcessResult=True),
        beforeTermination=dict(alive=True,waitResult=258,exitCode=0,getExitCodeProcessResult=True),
        final=dict(alive=False,waitResult=0,exitCode=0,getExitCodeProcessResult=True))

def forwarded():
    value=smoke.failure_summary(results({}))
    for case in value['cases']:
        case['cleanup'].update(desktopLifetime=None,originalEngine=None)
    value['cases'][0]['cleanup'].update(desktopLifetime=expected_lease(),originalEngine=expected_owner())
    return value

def accepts(value):
    try:publisher.validate_bytes(json.dumps(value,allow_nan=False).encode())
    except (ValueError,TypeError):return False
    return True

class LifetimeSummaryTests(unittest.TestCase):
    def test_registered_lease_counts_only_recorded_active_events(self):
        self.assertEqual(projected(evidence()).get('desktopLifetime'),expected_lease())

    def test_original_owner_keeps_three_sequential_states_without_atomic_inference(self):
        self.assertEqual(projected(evidence()).get('originalEngine'),expected_owner())

    def test_absent_or_unregistered_lease_stays_null(self):
        for registration in (None,'not-attempted','attempted','raised',True):
            value=evidence()
            if registration is None:value.pop('fixtureDesktopLifetime')
            else:value['fixtureDesktopLifetime']['registration']=registration
            with self.subTest():
                actual=projected(value)
                self.assertIn('desktopLifetime',actual);self.assertIn('originalEngine',actual)
                self.assertIsNone(actual['desktopLifetime']);self.assertIsNone(actual['originalEngine'])

    def test_invalid_lease_values_are_unknown_instead_of_coerced(self):
        for key,value in [('active',1),('removal','unknown'),('events',()),('events',[{}]),
                          ('events',[dict(event='other',active=True)]),('events',[dict(event='disposing',active=1)]),
                          ('callbackFault',0),('unexpectedTermination','false'),('omittedEvents',True),
                          ('omittedEvents',-1),('omittedEvents',65)]:
            row=evidence();row['fixtureDesktopLifetime'][key]=value
            with self.subTest():self.assertIsNone(projected(row).get('desktopLifetime'))

    def test_sixty_four_events_and_saturated_omissions_are_forwarded(self):
        row=evidence();row['fixtureDesktopLifetime'].update(events=[dict(event='queryTermination',active=True)]*64,omittedEvents=64)
        expected=expected_lease();expected.update(eventCount=64,activeQueryCount=64,activeNotifyCount=0,activeDisposingCount=0,omittedEvents=64)
        self.assertEqual(projected(row).get('desktopLifetime'),expected)
        row['fixtureDesktopLifetime']['events'].append(dict(event='queryTermination',active=True))
        self.assertIsNone(projected(row).get('desktopLifetime'))

    def test_missing_duplicate_or_nonexact_expected_image_never_selects_an_owner(self):
        rows=[]
        row=evidence();row.pop('expectedEngineImage');rows.append(row)
        row=evidence();row['expectedEngineImage']=row['expectedEngineImage'].upper();rows.append(row)
        row=evidence();row['initialMembers'].append(dict(row['initialMembers'][0],pid=43));rows.append(row)
        row=evidence();row['snapshots'].insert(0,copy.deepcopy(row['snapshots'][0]));rows.append(row)
        row=evidence();row['snapshots'][0]['members'].append(dict(row['initialMembers'][0],pid=43));rows.append(row)
        row=evidence();row['initialMembers'][0]['handleValue']=True;rows.append(row)
        for row in rows:
            with self.subTest():self.assertIsNone(projected(row).get('originalEngine'))

    def test_changed_pid_birth_handle_or_image_is_not_the_original_precleanup_sample(self):
        for key,value in [('pid',43),('creationTime',124),('handleValue',100),('image','/OTHER/soffice.bin')]:
            row=evidence();row['snapshots'][1]['members'][0][key]=value
            actual=projected(row).get('originalEngine')
            with self.subTest():
                self.assertIsNotNone(actual);self.assertEqual(actual['first'],expected_owner()['first'])
                self.assertIsNone(actual['beforeTermination'])

    def test_conflicting_or_malformed_other_members_cannot_resolve_the_original_engine(self):
        for other in (dict(member(),image='/OTHER/soffice.bin'),
                      dict(member(),pid=43,image='/OTHER/soffice.bin'),
                      dict(member(),pid=43,handleValue=100,creationTime=True,image='/OTHER/soffice.bin')):
            row=evidence();row['initialMembers'].append(other)
            with self.subTest():self.assertIsNone(projected(row).get('originalEngine'))

    def test_missing_or_earlier_precleanup_sample_is_not_replaced_with_first_state(self):
        for mutate in (lambda r:r['snapshots'].pop(1),lambda r:r['snapshots'].reverse()):
            row=evidence();mutate(row);actual=projected(row).get('originalEngine')
            with self.subTest():self.assertIsNotNone(actual);self.assertIsNone(actual['beforeTermination'])

    def test_invalid_native_state_is_null_and_boolean_numbers_are_rejected(self):
        for key,value in [('alive',1),('waitResult',True),('waitResult',1),('exitCode',True),
                          ('exitCode',-1),('exitCode',2**32),('getExitCodeProcessResult',False)]:
            row=evidence();row['snapshots'][1]['members'][0][key]=value
            actual=projected(row).get('originalEngine')
            with self.subTest():self.assertIsNotNone(actual);self.assertIsNone(actual['beforeTermination'])

    def test_missing_or_changed_final_member_never_becomes_a_zero_exit(self):
        for value in ([],[member(False,0,0)|{'creationTime':124}],[member(False,0,1)]):
            row=evidence();row['finalMembers']=value;actual=projected(row).get('originalEngine')
            with self.subTest():self.assertIsNotNone(actual);self.assertIsNone(actual['final'])

    def test_projection_does_not_alias_the_raw_events_or_snapshot_rows(self):
        row=evidence();actual=projected(row)
        self.assertEqual(actual.get('desktopLifetime'),expected_lease())
        self.assertEqual(actual.get('originalEngine'),expected_owner())
        row['fixtureDesktopLifetime']['events'].clear();row['snapshots'][1]['members'][0]['exitCode']=77
        self.assertEqual(actual['desktopLifetime'],expected_lease());self.assertEqual(actual['originalEngine'],expected_owner())

    def test_private_payload_and_poison_objects_are_never_inspected_or_copied(self):
        touched=[]
        class Poison:
            def trip(self,*args):touched.append(1);raise AssertionError()
            __str__=__repr__=__bool__=__iter__=__len__=__eq__=__hash__=__int__=trip
            def __getattr__(self,name):return self.trip()
        row=evidence();row['message']=row['traceback']=row['profile']=Poison()
        row['fixtureDesktopLifetime']['payload']=Poison()
        raw=results(row);raw[0]['error'].update(message=Poison(),traceback=Poison(),args=Poison())
        raw[0].update(observed=Poison(),expected=Poison())
        with mock.patch.object(os,'environ',Poison()),mock.patch.object(Path,'resolve',side_effect=AssertionError),mock.patch.object(os,'stat',side_effect=AssertionError):
            actual=smoke.failure_summary(raw)['cases'][0]['cleanup']
            self.assertEqual(actual.get('desktopLifetime'),expected_lease());self.assertEqual(actual.get('originalEngine'),expected_owner())
        self.assertFalse(touched);self.assertNotIn('SYNTHETIC-PRIVATE',json.dumps(actual))
        row['expectedEngineImage']=Poison();self.assertIsNone(projected(row).get('originalEngine'))
        row['fixtureDesktopLifetime']['events']=[dict(event=Poison(),active=True)]
        self.assertIsNone(projected(row).get('desktopLifetime'));self.assertFalse(touched)

    def test_module_status_and_original_failures_do_not_depend_on_diagnostics(self):
        raw=results(evidence());actual=smoke.failure_summary(raw)
        self.assertFalse(actual['passed']);self.assertIs(actual['acceptanceEligible'],False)
        self.assertEqual(actual['cases'][0]['failure'],dict(stage='load-factory',category='DisposedException'))
        self.assertEqual([x['status'] for x in actual['cases']],[x['status'] for x in raw])

    def test_original_runtime_ast_outside_the_two_projectors_is_unchanged(self):
        for name,drop,expected in [('suite/e2e/engine_smoke.py','failure_summary','e5b67c7ea89df8173c029d35211b0e851659eb8b07789e6220bf303879e218aa'),
                                  ('suite/scripts/publish-engine-failure-summary.py','validate_bytes','45ae55d44835de8166e283615b5fff55eceff046374601192feba8c49ba71af0')]:
            tree=ast.parse((ROOT/name).read_text());tree.body=[n for n in tree.body if not isinstance(n,ast.FunctionDef) or n.name!=drop]
            self.assertEqual(hashlib.sha256(ast.dump(tree,include_attributes=False).encode()).hexdigest(),expected)

class LifetimeSummarySchemaTests(unittest.TestCase):
    def test_extended_closed_summary_is_accepted_without_becoming_acceptance(self):
        row=forwarded();self.assertTrue(accepts(row));self.assertIs(row['acceptanceEligible'],False)

    def test_missing_projection_fields_are_rejected_even_for_unknown_evidence(self):
        for field in ('desktopLifetime','originalEngine'):
            row=forwarded();row['cases'][0]['cleanup'].pop(field)
            with self.subTest():self.assertFalse(accepts(row))

    def test_unknown_nested_keys_are_rejected(self):
        for path in [('desktopLifetime',),('originalEngine',),('originalEngine','first')]:
            row=forwarded();target=row['cases'][0]['cleanup']
            for field in path:target=target[field]
            target['message']='SYNTHETIC-PRIVATE'
            with self.subTest():self.assertFalse(accepts(row))

    def test_lease_schema_checks_exact_types_enums_and_bounded_counts(self):
        for field,value in [('active',1),('registrationCode',1),('removalCode',0),('removalCode',True),
            ('eventCount',65),('eventCount',True),('activeQueryCount',-1),('activeNotifyCount',6),
            ('omittedEvents',True),('omittedEvents',65),('omittedEvents',1),('callbackFault',0),('unexpectedTermination',None)]:
            row=forwarded();row['cases'][0]['cleanup']['desktopLifetime'][field]=value
            with self.subTest():self.assertFalse(accepts(row))

    def test_original_owner_schema_checks_generation_handle_and_nonatomic_states(self):
        for field,value in [('pid',True),('pid',0),('pid',2**32),('creationTime',True),('creationTime',2**64),
                            ('handleValue',0),('handleValue',2**64),('stateReadsAtomic',True)]:
            row=forwarded();row['cases'][0]['cleanup']['originalEngine'][field]=value
            with self.subTest():self.assertFalse(accepts(row))
        for field,value in [('alive',0),('waitResult',True),('waitResult',1),('exitCode',True),('exitCode',2**32),
                            ('getExitCodeProcessResult',False)]:
            row=forwarded();row['cases'][0]['cleanup']['originalEngine']['first'][field]=value
            with self.subTest():self.assertFalse(accepts(row))

    def test_all_three_states_may_remain_unknown_without_inventing_zeroes(self):
        row=forwarded();owner=row['cases'][0]['cleanup']['originalEngine']
        owner.update(first=None,beforeTermination=None,final=None)
        self.assertTrue(accepts(row))

    def test_maximum_existing_errors_plus_new_metadata_remain_under_32k(self):
        row=forwarded();error=dict(stage='fixture desktop lifetime release',category='IllegalArgumentException')
        for case in row['cases']:
            case['cleanup'].update(desktopLifetime=expected_lease(),originalEngine=expected_owner(),errors=[error]*16)
            case['finalizationFailures']=[error]*2
        raw=json.dumps(row,ensure_ascii=False,indent=2,allow_nan=False).encode()
        self.assertLessEqual(len(raw),32768);self.assertTrue(accepts(row))
