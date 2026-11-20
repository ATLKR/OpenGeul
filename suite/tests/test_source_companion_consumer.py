"""Prepare companion glue with a map double; never a fake new Full receipt."""
import ast
import copy
from pathlib import Path
import unittest
from unittest.mock import patch

from suite import payload, prepare, source_contracts as contracts

ROOT = Path(__file__).resolve().parents[2]
MEMBER = 'program/spsupp_x86.dll'
TWAIN = 'program/twain32shim.exe'


class PrepareSourceCompanionTests(unittest.TestCase):
    def helper(self):
        method = getattr(prepare, '_source_x64_companions', None)
        self.assertTrue(callable(method), 'Missing original-runtime companion consumer')
        return method

    def component_map(self):
        return {MEMBER: dict(machine=332, role='x86CompatibilityHelper', size=64, sha256='a'*64),
            TWAIN: dict(machine=332, role='x86CompatibilityHelper', size=80, sha256='c'*64)}

    def source_context(self):
        # Partial argument-boundary inputs, deliberately lacking all Full flags,
        # artifacts and independent pins. Only the explicitly mocked wrapper sees them.
        return dict(sourcePin=dict(contracts.NEW_SOURCE)), dict(contextMarker=1)

    def test_legacy_path_retains_no_context_without_calling_new_wrapper(self):
        with patch.object(payload, '_source_companion_admissions', create=True,
                side_effect=AssertionError('Legacy reached new component wrapper')):
            self.assertEqual(self.helper()({}, None), {})
            self.assertEqual(self.helper()(dict(sourcePin=dict(contracts.LEGACY_SOURCE)), None), {})

    def test_new_source_requires_original_runtime_and_exact_source_tuple(self):
        proof, runtime = self.source_context()
        with patch.object(payload, '_source_companion_admissions', create=True,
                side_effect=AssertionError('Invalid context reached component wrapper')):
            with self.assertRaises(ValueError): self.helper()(proof, None)
            for changes in (dict(size=True), dict(sha256='0'*64), dict(version='26.8.1.1')):
                row = dict(sourcePin=dict(contracts.NEW_SOURCE, **changes))
                with self.subTest(key=next(iter(changes))), self.assertRaises(ValueError):
                    self.helper()(row, runtime)

    def test_common_wrapper_receives_the_original_objects_and_x64(self):
        proof, runtime = self.source_context(); saved = copy.deepcopy((proof, runtime))
        admitted = self.component_map()
        with patch.object(payload, '_source_companion_admissions', create=True, return_value=admitted) as wrapper:
            try: value = self.helper()(proof, runtime)
            except ValueError: self.fail('The exact two independent source companion maps were rejected')
        self.assertEqual(value, admitted)
        self.assertIs(wrapper.call_args.args[0], runtime)
        self.assertIs(wrapper.call_args.args[1], proof)
        self.assertEqual(wrapper.call_args.kwargs, dict(architecture='x64'))
        self.assertEqual((proof, runtime), saved)

    def test_wrapper_rejection_and_nonclosed_component_maps_remain_rejected(self):
        proof, runtime = self.source_context()
        with patch.object(payload, '_source_companion_admissions', create=True, side_effect=ValueError('Closed component rejection')):
            with self.assertRaises(ValueError): self.helper()(proof, runtime)
        variants = [{}, {MEMBER:self.component_map()[MEMBER]}, {TWAIN:self.component_map()[TWAIN]},
            dict(self.component_map(), **{'program/other.dll': {}})]
        for member in (MEMBER,TWAIN):
            for changes in (dict(machine=True), dict(machine=34404), dict(size=True), dict(size=0),
                    dict(role='nativeX64'), dict(sha256='not-a-digest'), dict(extra=0)):
                value=self.component_map();value[member].update(changes);variants.append(value)
        for value in variants:
            with patch.object(payload, '_source_companion_admissions', create=True, return_value=value):
                with self.subTest(memberCount=len(value)), self.assertRaises(ValueError):
                    self.helper()(proof, runtime)

    def test_original_runtime_is_threaded_through_prepare_owned_calls(self):
        source = (ROOT/'suite/prepare.py').read_text(); tree = ast.parse(source)
        methods = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
        for name in ('_source_x64_inventory', '_source_x64_runtime', 'validate_source_build_runtime'):
            args = methods[name].args
            self.assertIn('runtime', [a.arg for a in args.args + args.kwonlyargs], name)
        expected = {'_source_build_x64':'_source_x64_inventory', '_source_x64_runtime':'_source_x64_inventory',
            'validate_source_build_runtime':'_source_x64_runtime', 'extract_source_engine_zip':'validate_source_build_runtime'}
        for caller, callee in expected.items():
            calls = [n for n in ast.walk(methods[caller]) if isinstance(n, ast.Call) and
                isinstance(n.func, ast.Name) and n.func.id == callee]
            self.assertEqual(len(calls), 1)
            self.assertTrue(any(k.arg == 'runtime' and isinstance(k.value, ast.Name) and k.value.id == 'runtime'
                for k in calls[0].keywords), caller)

    def test_helper_is_separate_from_native_counts_and_runtime_gate_is_retained(self):
        source = (ROOT/'suite/prepare.py').read_text(); tree = ast.parse(source)
        methods = {n.name: ast.get_source_segment(source, n) for n in tree.body if isinstance(n, ast.FunctionDef)}
        inventory = methods['_source_x64_inventory']; runtime = methods['_source_x64_runtime']
        self.assertIn('companionPeCount', inventory)
        self.assertIn("'program/spsupp_helper.exe'", inventory)
        self.assertIn("['sourceCompanionProof']['nativeHelper']", inventory)
        self.assertIn("'program/scnlo.dll'", inventory)
        self.assertIn("'sourceTwainProof'", inventory)
        self.assertIn("'nativePeer'", inventory)
        self.assertIn("'size','sha256'", inventory)
        self.assertIn("item[1]['role'] != 'nativeX64'", inventory)
        self.assertIn('counts[\'nativeX64\']', inventory)
        self.assertIn('_source_companion_runtime(runtime_root,', runtime)
        self.assertIn('_source_twain_runtime(runtime_root,', runtime)
        self.assertIn('check_asset(record,path)', runtime)
        self.assertIn('if actual != expected.keys():', runtime)

    def inventory_context(self):
        # Metadata boundary only: these rows contain no artifact, Full flags,
        # receipt, native process witness or input ZIP and cannot qualify a build.
        names = ('soffice.exe','soffice.bin','python.exe','pyuno.pyd','ifbclient.dll',
            'Engine12.dll','intl/fbintl.dll','winaccessibility.dll','spsupp_helper.exe','scnlo.dll')
        inventory = [dict(path='C:\\build\\instdir\\program\\'+name.replace('/','\\'),
            machine=34404,role='nativeX64',size=128,sha256='b'*64) for name in names]
        imports = dict(normal=['kernel32.dll'],delay=[])
        inventory[7]['imports'] = copy.deepcopy(imports)
        for member,record in self.component_map().items():
            inventory.append(dict(path='C:\\build\\instdir\\'+member.replace('/','\\'),**record))
        proof = dict(sourcePin=dict(contracts.NEW_SOURCE),
            appLocalCrt=dict(programDirectory='C:\\build\\instdir\\program'),
            productInventory=inventory, productPeCount=12,nativePeCount=10,
            managedAnyCpuCount=0,pinnedTemplateCount=0,companionPeCount=2,
            crtPreflight=dict(files=[]),crtImportClosure=dict(checkedPeCount=10),
            sourceCompanionProof=dict(nativeHelper=dict(path='program/spsupp_helper.exe',
                machine=34404,role='nativeX64',size=128,sha256='b'*64)),
            sourceTwainProof=dict(nativePeer=dict(path='program/scnlo.dll',machine=34404,
                role='nativeX64',size=128,sha256='b'*64)),
            winAccBinary=dict(path='program/winaccessibility.dll',machine=34404,
                role='nativeX64',size=128,sha256='b'*64,imports=imports))
        return proof, dict(contextMarker=1)

    def test_inventory_joins_component_and_native_helper_without_native_count_inflation(self):
        proof, runtime = self.inventory_context()
        with patch.object(payload,'_source_companion_admissions',create=True,return_value=self.component_map()), \
                patch.object(prepare,'_source_python_templates',return_value={}):
            try: admitted = prepare._source_x64_inventory(proof,runtime=runtime)
            except ValueError: self.fail('The separate component and native peer inventory join was rejected')
        self.assertEqual(admitted[MEMBER][1]['role'],'x86CompatibilityHelper')
        self.assertEqual(admitted[TWAIN][1]['role'],'x86CompatibilityHelper')
        self.assertEqual(sum(row['role']=='nativeX64' for _,row in admitted.values()),10)
        self.assertEqual(admitted['program/spsupp_helper.exe'][1]['machine'],34404)
        self.assertEqual(admitted['program/scnlo.dll'][1]['machine'],34404)
        self.assertNotIn('passed',proof); self.assertNotIn('phase',proof)

    def test_inventory_rejects_companion_count_alias_role_and_native_helper_drift(self):
        original, runtime = self.inventory_context()
        changes = [lambda p:p.update(companionPeCount=0), lambda p:p.update(companionPeCount=1),
            lambda p:p.update(nativePeCount=12),
            lambda p:p.update(companionPeCount=True),
            lambda p:p['productInventory'][-1].update(machine=34404),
            lambda p:p['productInventory'][-1].update(sha256='d'*64),
            lambda p:p['productInventory'][-1].update(path='C:\\build\\instdir\\program\\other.dll'),
            lambda p:p['productInventory'][-1].update(path='C:\\build\\instdir\\Program\\spsupp_x86.dll'),
            lambda p:p['productInventory'][8].update(sha256='c'*64),
            lambda p:p['sourceCompanionProof']['nativeHelper'].update(size=129),
            lambda p:p['sourceCompanionProof']['nativeHelper'].update(path='program/other.exe'),
            lambda p:p['sourceCompanionProof']['nativeHelper'].update(role='managedAnyCpu')]
        for index, change in enumerate(changes):
            proof=copy.deepcopy(original);change(proof)
            with patch.object(payload,'_source_companion_admissions',create=True,return_value=self.component_map()), \
                    patch.object(prepare,'_source_python_templates',return_value={}):
                with self.subTest(change=index),self.assertRaises(ValueError):
                    prepare._source_x64_inventory(proof,runtime=runtime)

    def test_twain_native_peer_is_required_and_cannot_borrow_spsupp_helper_identity(self):
        original, runtime = self.inventory_context()
        changes = [lambda p:p.pop('sourceTwainProof'),lambda p:p['sourceTwainProof'].pop('nativePeer'),
            lambda p:p['sourceTwainProof']['nativePeer'].update(path='program/spsupp_helper.exe'),
            lambda p:p['sourceTwainProof']['nativePeer'].update(size=129),
            lambda p:p['sourceTwainProof']['nativePeer'].update(sha256='d'*64),
            lambda p:p['sourceTwainProof']['nativePeer'].update(role='x86CompatibilityHelper'),
            lambda p:p['productInventory'][9].update(machine=332,role='managedAnyCpu'),
            lambda p:p['productInventory'][9].update(path='C:\\build\\instdir\\program\\SCNLO.dll')]
        for index,change in enumerate(changes):
            proof=copy.deepcopy(original);change(proof)
            with patch.object(payload,'_source_companion_admissions',return_value=self.component_map()), \
                    patch.object(prepare,'_source_python_templates',return_value={}):
                with self.subTest(change=index),self.assertRaises(ValueError):
                    prepare._source_x64_inventory(proof,runtime=runtime)

    def test_legacy_profile_cannot_smuggle_twain_proof_without_original_new_runtime(self):
        proof=dict(sourcePin=dict(contracts.LEGACY_SOURCE),sourceTwainProof=dict(sourceOnly=True))
        with patch.object(payload,'_source_companion_admissions',side_effect=AssertionError('Legacy reached new wrapper')):
            with self.assertRaises(ValueError):self.helper()(proof,None)


if __name__ == '__main__': unittest.main()
