import ast
from pathlib import Path
import unittest
import yaml
ROOT=Path(__file__).resolve().parents[1]
DIAG='refs/heads/work/opengeul-office-dotnet-graph-diagnostic'
NORMAL='refs/heads/work/opengeul-office-native-engine'
def condition(text,event,ref,**overrides):
    values={'event':event,'ref':ref,'repository':'ATLKR/OpenGeul','repository_id':'1405493151','repository_owner':'ATLKR','actor':'ATLKR','run_attempt':'1','private':False,'fork':False,**overrides}
    mapping={'github.event_name':'event','github.ref':'ref','github.repository_id':'repository_id','github.repository_owner':'repository_owner','github.repository':'repository','github.actor':'actor','github.run_attempt':'run_attempt','github.event.repository.private':'private','github.event.repository.fork':'fork'}
    text=text.removeprefix('${{').removesuffix('}}').strip()
    for key in sorted(mapping,key=len,reverse=True):text=text.replace(key,mapping[key])
    text=text.replace('||','or').replace('&&','and').replace('false','False')
    tree=ast.parse(text,mode='eval')
    allowed=(ast.Expression,ast.BoolOp,ast.Or,ast.And,ast.Compare,ast.Eq,ast.NotEq,ast.Name,ast.Load,ast.Constant)
    if any(not isinstance(n,allowed) for n in ast.walk(tree)):raise AssertionError('unsupported fixed expression')
    return bool(eval(compile(tree,'fixed-condition','eval'),{'__builtins__':{}},values))
class PushRouting(unittest.TestCase):
    def test_only_diagnostic_job_explicitly_enables_bootstrap_error_codes(self):
        workflow=yaml.safe_load((ROOT.parents[2]/'.github/workflows/office-native-engine.yml').read_bytes())
        diagnostic=workflow['jobs']['dotnet-graph-diagnostic']
        commands=[step.get('run','') for step in diagnostic['steps']]
        self.assertEqual(sum('--bootstrap-error-codes' in command for command in commands),1)
        for name,job in workflow['jobs'].items():
            if name!='dotnet-graph-diagnostic':
                self.assertTrue(all('--bootstrap-error-codes' not in step.get('run','') for step in job['steps']))
    def test_actual_job_expressions_never_send_diagnostic_push_to_full(self):
        v=yaml.safe_load((ROOT.parents[2]/'.github/workflows/office-native-engine.yml').read_bytes());full=v['jobs']['native-firebird-and-office']['if'];diag=v['jobs']['dotnet-graph-diagnostic']['if']
        for event,ref,expected in [('push',DIAG,(False,True)),('push',NORMAL,(True,False)),('workflow_dispatch',NORMAL,(True,False)),('workflow_dispatch',DIAG,(True,False)),('pull_request',DIAG,(True,False))]:
            self.assertEqual((condition(full,event,ref),condition(diag,event,ref)),expected)
    def test_trigger_adds_only_exact_branch_and_keeps_paths(self):
        old=yaml.safe_load((ROOT/'tests/fixtures/workflow.before.yml').read_bytes());new=yaml.safe_load((ROOT.parents[2]/'.github/workflows/office-native-engine.yml').read_bytes())
        self.assertEqual(new['on']['push']['branches'],old['on']['push']['branches']+['work/opengeul-office-dotnet-graph-diagnostic'])
        self.assertEqual(new['on']['push']['paths'],old['on']['push']['paths'])
        self.assertNotIn('pull_request',new['on']);self.assertNotIn('main',new['on']['push']['branches'])

    def test_foreign_private_fork_and_rerun_contexts_skip_before_allocating_runner(self):
        v=yaml.safe_load((ROOT.parents[2]/'.github/workflows/office-native-engine.yml').read_bytes());selector=v['jobs']['dotnet-graph-diagnostic']['if']
        for key,value in [('repository','OTHER/OpenGeul'),('repository_id','1405493152'),('repository_owner','OTHER'),('actor','OTHER'),('run_attempt','2'),('private',True),('fork',True)]:
            with self.subTest(field=key):self.assertFalse(condition(selector,'push',DIAG,**{key:value}))
        self.assertTrue(condition(selector,'push',DIAG))
