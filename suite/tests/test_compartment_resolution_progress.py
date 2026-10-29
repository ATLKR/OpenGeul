"""Retain validated selection when the original file-only resolution fails."""
import copy
import inspect
from pathlib import Path
import unittest
from unittest.mock import patch

import test_compartment_selection as selection_fixture


class CompartmentResolutionProgressTests(unittest.TestCase):
    def fixture(self):
        fixture=selection_fixture.CompartmentSelectionTests();fixture.setUp()
        function=fixture.m.resolve_compartment_in_memory
        self.assertTrue('progress' in inspect.signature(function).parameters,
            'Resolution must expose closed phase/validated-selection progress')
        return fixture.m,fixture.compartment_report(),function

    def test_worker_error_keeps_completed_selection_and_original_exception(self):
        module,report,function=self.fixture();before=copy.deepcopy(report)
        expected=module.select_compartment(report);primary=OSError('synthetic private worker failure')
        progress={'selection':{'stale':True},'stage':'stale'};calls=[]
        def worker(pair,*,mode,rvas):
            calls.append((pair,mode,list(rvas)));raise primary
        with self.assertRaises(OSError) as caught:
            function(report,Path('/synthetic/pair'),report['runBinding'],worker_run=worker,progress=progress)
        self.assertIs(caught.exception,primary)
        self.assertEqual(progress,dict(stage='ime-compartment-worker',selection=expected))
        self.assertEqual(calls,[(Path('/synthetic/pair'),'resolve',[100])])
        self.assertEqual(report,before)

    def test_unresolved_join_keeps_checked_worker_and_original_failure_without_retry(self):
        module,report,function=self.fixture();before=copy.deepcopy(report)
        expected=module.select_compartment(report);progress={};calls=[]
        resolution=dict(success=True,resolution=dict(dllSha256=report['pluginFileOrigin']['dllSha256'],
            identity=report['pluginFileOrigin']['matchedIdentity'],
            frames=[dict(returnRva=100,tag='unresolved')]))
        def worker(pair,*,mode,rvas):
            calls.append((mode,list(rvas)))
            return resolution
        with patch.object(module,'join_resolution',wraps=module.join_resolution) as join, \
                self.assertRaisesRegex(AssertionError,'symbols remain inconclusive'):
            function(report,Path('/synthetic/pair'),report['runBinding'],worker_run=worker,progress=progress)
        self.assertEqual(join.call_count,1)
        self.assertEqual(progress,dict(stage='ime-compartment-join',selection=expected,resolution=resolution))
        self.assertIs(progress['resolution'],resolution)
        self.assertEqual(calls,[('resolve',[100])]);self.assertEqual(report,before)

    def test_join_rejections_never_retain_unchecked_worker(self):
        for damage in ('unknown','partial','identity','frame','tag'):
            with self.subTest(damage=damage):
                module,report,function=self.fixture()
                selected=module.select_compartment(report);calls=[]
                resolution=dict(success=True,resolution=dict(dllSha256=report['pluginFileOrigin']['dllSha256'],
                    identity=copy.deepcopy(report['pluginFileOrigin']['matchedIdentity']),
                    frames=[dict(returnRva=100,tag='unresolved')]))
                if damage=='unknown':resolution=None
                elif damage=='partial':resolution={'success':False}
                elif damage=='identity':resolution['resolution']['identity']['age']+=1
                elif damage=='frame':resolution['resolution']['frames'][0]['returnRva']=104
                else:resolution['resolution']['frames'][0]['tag']='not-allowlisted'
                progress={'selection':{'stale':True},'resolution':{'stale':True}}
                def worker(*args,**kwargs):calls.append('worker');return resolution
                with self.assertRaises(AttributeError if damage=='unknown' else AssertionError):
                    function(report,Path('/synthetic/pair'),report['runBinding'],worker_run=worker,progress=progress)
                self.assertEqual(progress,dict(stage='ime-compartment-join',selection=selected))
                self.assertEqual(calls,['worker'])

    def test_selector_rejection_discards_stale_selection_and_never_runs_worker(self):
        module,report,function=self.fixture()
        selected=module.select_compartment(report)
        report['tests'][0]['imeFailureCleanup']['engineExitConfirmed']=False
        progress={'selection':selected,'stage':'old-worker'}
        calls=[]
        with self.assertRaises(AssertionError):
            function(report,Path('/synthetic/pair'),report['runBinding'],
                worker_run=lambda *a,**k:calls.append('worker'),progress=progress)
        self.assertEqual(progress,dict(stage='ime-compartment-select'))
        self.assertEqual(calls,[])

    def test_inconclusive_selection_keeps_existing_return_without_worker(self):
        module,report,function=self.fixture();report['tests'][0]['keyTokens']=['g','k']
        progress={};calls=[]
        selected,resolved=function(report,Path('/synthetic/pair'),report['runBinding'],
            worker_run=lambda *a,**k:calls.append('worker'),progress=progress)
        self.assertEqual(selected['status'],'inconclusive-case');self.assertIsNone(resolved)
        self.assertEqual(progress,dict(stage='ime-compartment-select',selection=selected))
        self.assertEqual(calls,[])
