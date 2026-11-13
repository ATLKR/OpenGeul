"""Exact new-insertion frames derived from source and font metrics, not UI output.

rhwp 0.8.7/1a76570 used width guesses (.55, italic1.05, symbol .5) and
fraction height 2.44em. Its positive continuous width2712.5HU truncates to2712.
rhwp 0.9.0/c9095c5 uses Latin Modern Math advances and MATH positioning:
italic x572, plus778, digit500, script70%; fraction shifts677/686, gap120,
axis250 and rule40 (UPM1000). The independently read source font has SHA256
b11060f37967c090457580275129d0d7da1d5fbfc82b04e78c91aa31977f547c.
The glyph-source comment names a different byte SHA1177d9; formula-relevant
font tables were read independently and match, without claiming byte equality.

Primary references (exact public source, not saved browser documents):
https://github.com/edwardkim/rhwp/blob/1a76570e833917d15817415a53c09ad61ab3203f/src/renderer/equation/layout.rs
https://github.com/edwardkim/rhwp/blob/c9095c5f67632e6721e800ccc7fb43ea49d26682/src/renderer/equation/layout/glyph_advances.rs
https://github.com/edwardkim/rhwp/blob/c9095c5f67632e6721e800ccc7fb43ea49d26682/src/renderer/equation/layout/fraction_geometry.rs
These tests invoke the real live checkpoint oracle with authored metadata only.
They do not perform browser input, prove paint, or replace the full UI cases.
"""
import ast
import copy
from fractions import Fraction as F
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'e2e'))
from advanced_edit_oracle import assert_equation

NEW_CORE='c9095c5f67632e6721e800ccc7fb43ea49d26682'

def declared_frames():
    # One-letter base, one superscript digit, plus, one-over-two fraction.
    old_width=F(55,100)*F(105,100)+F(55,100)*F(7,10)+F(1,2)+F(15,100)*2+F(55,100)+F(2,10)*2
    old_height=(1+F(2,10))*2+F(4,100)
    # Read from source glyph advances / actual font hmtx and MATH tables.
    x,plus,digit,scale=F(572,1000),F(778,1000),F(500,1000),F(70,100)
    baseline,axis,rule,gap=F(4,5),F(250,1000),F(40,1000),F(120,1000)
    numerator_shift=max(F(677,1000),axis+rule/2+gap+1-baseline)
    denominator_shift=max(F(686,1000),rule/2+gap+baseline-axis)
    ascent=max(numerator_shift+baseline,baseline-denominator_shift,axis+rule/2)
    descent=max(1-baseline-numerator_shift,denominator_shift+1-baseline,rule/2-axis,F(0))
    width=x+digit*scale+plus+F(15,100)*2+digit+F(2,10)*2
    # The 1em x and .7em superscript occupy less than the fraction ascent/descent.
    sup_shift=max(F(363,1000),scale*(1-baseline)+F(108,1000))
    sup_ascent=max(baseline,scale*baseline+sup_shift)
    sup_descent=max(1-baseline,scale*(1-baseline)-sup_shift)
    height=max(ascent,sup_ascent)+max(descent,sup_descent)
    return tuple(int(v*1000) for v in (old_width,old_height)),tuple(int(v*1000) for v in (width,height))

def authored_result(size):
    return dict(tables={},fields=[],notes=[],headers=[],footers=[],shapes=[],
        body='EQUATION-BODY',paragraphs={'s0/body':['EQUATION-BODY','']},
        equations=[dict(script='x^2 + {1} over {2}',size=size,owner='s0/body',
            anchor={'treatAsChar':'1'},reference=(1,0),base_unit=1000)])

class CheckpointReached(Exception):pass

def live_checkpoint_accepts(result):
    # Load the actual method without booting Playwright. Only public input at the
    # boundary is inert; its real checkpoint lambda and real oracle are executed.
    source=ROOT/'e2e/advanced_edit_cases.py'
    tree=ast.parse(source.read_text())
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='AdvancedEditCases')
    method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='test_advanced_equation_chord_doubleclick_history_reopen')
    namespace={'assert_equation':assert_equation,'edit':lambda *args:None}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[method],type_ignores=[])),str(source),'exec'),namespace)
    def checkpoint(label,oracle,**declarations):
        if label!='inserted':raise AssertionError('Unexpected first checkpoint')
        oracle(result);raise CheckpointReached
    target=SimpleNamespace(page=SimpleNamespace(keyboard=SimpleNamespace(press=lambda *args:None)),
        advanced_owned=lambda:None,advanced_eq_dialog=lambda *args:None,advanced_check=checkpoint)
    try:namespace[method.name](target)
    except CheckpointReached:return True
    except ValueError:return False
    raise AssertionError('Live first checkpoint was not reached')

class EquationSourceGeometryTests(unittest.TestCase):
    def test_reference_is_bound_to_the_current_reviewed_source_pin(self):
        pin=json.loads((ROOT/'config/upstream.lock.json').read_text())['rhwp']
        self.assertEqual((pin['version'],pin['commit']),('0.9.0',NEW_CORE))

    def test_old_and_new_declared_metrics_are_independently_exact(self):
        self.assertEqual(declared_frames(),((2712,2440),(2900,2367)))

    def test_new_live_insertion_accepts_only_the_new_source_frame(self):
        self.assertTrue(live_checkpoint_accepts(authored_result(declared_frames()[1])))

    def test_legacy_frame_is_not_a_second_allowed_new_insertion_frame(self):
        self.assertFalse(live_checkpoint_accepts(authored_result(declared_frames()[0])))

    def test_one_hwpunit_in_either_direction_still_fails(self):
        width,height=declared_frames()[1]
        for size in ((width-1,height),(width+1,height),(width,height-1),(width,height+1)):
            with self.subTest(size=size):self.assertFalse(live_checkpoint_accepts(authored_result(size)))

    def test_new_frame_cannot_hide_wrong_baseunit_anchor_owner_or_script(self):
        source=authored_result(declared_frames()[1])
        changes=[dict(base_unit=999),dict(reference=(0,13)),dict(owner='s0/body/t0/r0c0'),
            dict(anchor={'treatAsChar':'0'}),dict(script='x^9')]
        for change in changes:
            value=copy.deepcopy(source);value['equations'][0].update(change)
            with self.subTest(fields=tuple(change)):self.assertFalse(live_checkpoint_accepts(value))

    def test_imported_legacy_oracle_default_is_unchanged(self):
        assert_equation(authored_result(declared_frames()[0]),'x^2 + {1} over {2}',body=('EQUATION-BODY',),anchor=(1,0))
        with self.assertRaisesRegex(ValueError,'geometry'):
            assert_equation(authored_result(declared_frames()[1]),'x^2 + {1} over {2}',body=('EQUATION-BODY',),anchor=(1,0))

if __name__=='__main__':unittest.main()
