"""The synthetic COM wait experiment has no Office/desktop delivery path."""
import unittest
from suite.tests.test_calc_matrix_workflow import workflow_steps, field, run_code, WORKFLOW
from suite.tests.test_navigation_diagnostic_workflow import condition

COM = "env.OPENGEUL_SUITE_RUN_MODE == 'com-wait-diagnostic'"
MODES=('acceptance','navigation-diagnostic','ime-mode-diagnostic','focus-diagnostic','sal-offset-mapping','com-wait-diagnostic','mutex-function-mapping','unknown','')


def step(name):
    found=[s for s in workflow_steps() if field(s,'id')==name]
    assert len(found)==1, 'Missing unique workflow step '+name
    return found[0]


def evaluate(expression, mode, architecture='arm64', outcomes=None):
    text=expression.replace('env.OPENGEUL_SUITE_RUN_MODE',repr(mode)).replace('matrix.architecture',repr(architecture))
    for key,value in (outcomes or {}).items(): text=text.replace('steps.'+key+'.outcome',repr(value))
    return eval(text.replace('&&',' and ').replace('||',' or '),{'__builtins__':{}},{})


class ComWaitWorkflowTests(unittest.TestCase):
    def test_fixed_mode_and_exact_admission_before_any_synthetic_child(self):
        self.assertRegex(WORKFLOW.read_text(encoding='utf-8'), r'(?m)^  OPENGEUL_SUITE_RUN_MODE: (?:acceptance|calc-dispatch-diagnostic)$')
        guard=step('sal-offset-admission');run=step('com-wait-diagnostic')
        self.assertLess(workflow_steps().index(guard),workflow_steps().index(run))
        self.assertIn("Assert-Native31Context '${{ matrix.architecture }}'",run_code(guard))
        self.assertIn("'ls-tree', '-rz', '--full-tree', 'HEAD'",run_code(guard))
        for mode in MODES:
            self.assertEqual(evaluate(condition(guard),mode),mode in ('sal-offset-mapping','com-wait-diagnostic','mutex-function-mapping','ime-mode-diagnostic','focus-diagnostic'))

    def test_unit_shell_and_admission_outcomes_required_on_both_architectures(self):
        units=step('suite-unit-shell');run=step('com-wait-diagnostic')
        self.assertIsNone(condition(units))
        self.assertIn('unittest discover',run_code(units))
        self.assertIn('dotnet run --project suite/shell-tests',run_code(units))
        self.assertLess(workflow_steps().index(units),workflow_steps().index(run))
        for architecture in ('x64','arm64'):
            for mode in MODES:
                for unit in ('success','failure','skipped'):
                    for admission in ('success','failure','skipped'):
                        allowed=evaluate(condition(run),mode,architecture,{'suite-unit-shell':unit,'sal-offset-admission':admission})
                        self.assertEqual(allowed,mode=='com-wait-diagnostic' and unit==admission=='success')
        self.assertIn("dotnet run --no-build --project suite/shell-tests/OpenGeul.Office.Tests.csproj -c Release -- --com-wait-diagnostic --architecture '${{ matrix.architecture }}' --output .work/suite-com-wait-diagnostic/receipt.json",run_code(run))

    def test_no_engine_fetch_build_or_privacy_originals_for_synthetic_mode(self):
        fetch=step('source-engine');build=step('build')
        for architecture in ('x64','arm64'):
            self.assertFalse(evaluate(condition(fetch),'com-wait-diagnostic',architecture,{'sal-offset-admission':'success'}))
        for mode in MODES:
            self.assertEqual(evaluate(condition(build),mode,outcomes={'sal-offset-admission':'success','matched-symbol-qualification':'success','suite-unit-shell':'success','source-engine':'success'}),mode not in ('sal-offset-mapping','com-wait-diagnostic','mutex-function-mapping'))
        privacy_upload=next(s for s in workflow_steps() if 'Suite native31 setup and control originals' in s)
        self.assertIn("env.OPENGEUL_SUITE_RUN_MODE != 'com-wait-diagnostic'",condition(privacy_upload))
        for name in ('readiness','native31-privacy-prepare','fixtures'):
            self.assertIn("steps.build.outcome == 'success'",condition(step(name)))

    def test_admitted_sha_marker_only_on_gated_diagnostic_step(self):
        matches=[s for s in workflow_steps() if 'OPENGEUL_COM_WAIT_ADMITTED_SHA:' in s]
        self.assertEqual(len(matches),1)
        self.assertEqual(field(matches[0],'id'),'com-wait-diagnostic')
        self.assertIn('OPENGEUL_COM_WAIT_ADMITTED_SHA: ${{ github.sha }}',matches[0])

    def test_only_receipt_upload_then_deliberate_nonacceptance(self):
        upload=step('com-wait-evidence');terminal=step('com-wait-not-acceptance')
        self.assertEqual(condition(upload),'always() && '+COM+" && steps.com-wait-diagnostic.outcome != 'skipped'")
        self.assertIn('path: .work/suite-com-wait-diagnostic/receipt.json',upload)
        self.assertNotIn('path: .work/suite-com-wait-diagnostic\n',upload)
        self.assertEqual(condition(terminal),'always() && '+COM)
        self.assertIn('package delivery is prohibited',run_code(terminal))
        self.assertLess(workflow_steps().index(upload),workflow_steps().index(terminal))
        self.assertLess(workflow_steps().index(terminal),workflow_steps().index(step('build')))
        self.assertIn("env.OPENGEUL_SUITE_RUN_MODE == 'acceptance'",condition(workflow_steps()[-1]))
