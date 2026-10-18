"""Portable query-oracle checks; these do not qualify native Windows execution."""
import json
import unittest

from suite.tests import test_native_meson_receiver_control as control


GOOD = r"""
$dependencies='C:\Dependency Fixtures'
$graphite='C:/Dependency Fixtures/graphite/graphite2-uninstalled.pc'
$icu='C:/Dependency Fixtures/icu/icu-uc-uninstalled.pc'
$prefix='C:/Dependency Fixtures/prefix pc/prefix-control.pc'
$queries=@{
 'tool-version'=[pscustomobject]@{stdout="2.4.3`n"}
 exists=[pscustomobject]@{stdout=''}
 versions=[pscustomobject]@{stdout="1.3.15`n78.3`n"}
 'graphite-path'=[pscustomobject]@{stdout="c:/dependency fixtures/graphite\graphite2-uninstalled.pc`n"}
 'icu-path'=[pscustomobject]@{stdout="C:\Dependency Fixtures/icu\icu-uc-uninstalled.pc`n"}
 'prefix-path'=[pscustomobject]@{stdout="c:/dependency fixtures/prefix pc\prefix-control.pc`n"}
 'graphite-sentinel'=[pscustomobject]@{stdout="graphite`n"}
 'icu-sentinel'=[pscustomobject]@{stdout="icu`n"}
 cflags=[pscustomobject]@{stdout='-IC:/Dependency\ Fixtures/graphite/include\ space -DGRAPHITE2_STATIC'}
 libs=[pscustomobject]@{stdout='C:/Dependency\ Fixtures/graphite/receiver-graphite.lib -lreceiver-icu'}
}
"""


class QueryContractTests(unittest.TestCase):
    ps = control.ControllerContractTests.ps

    def test_individual_paths_accept_mixed_slashes_case_policy_and_spaced_native_prefix(self):
        self.ps(GOOD + r"""
$result=Assert-MesonFixtureQueries $queries $dependencies
if(-not $result.passed -or -not $result.prefixPreserved -or $result.selectedPaths.Count -ne 2 -or
   $result.selectedPaths[0] -ine $graphite -or $result.selectedPaths[1] -ine $icu) {
 throw 'Exact Graphite/ICU path selection was not retained'
}
""")

    def test_each_path_rejects_missing_wrong_blank_extra_or_swapped_file_selection(self):
        self.ps(GOOD + r"""
Assert-MesonFixtureQueries $queries $dependencies|Out-Null
$paths=@{'graphite-path'=$graphite;'icu-path'=$icu;'prefix-path'=$prefix}
foreach($name in $paths.Keys) {
 $missing=$queries.Clone();$missing.Remove($name)
 $rejected=$false;try{Assert-MesonFixtureQueries $missing $dependencies|Out-Null}catch{$rejected=$true}
 if(-not $rejected){throw ('Missing path query accepted: '+$name)}
 foreach($value in @('', ' ', 'C:/machine-fallback/wrong.pc', '../relative/wrong.pc',
                     ($paths[$name]+"`n"+$paths[$name]+"`n"),
                     ($paths[$name]+"`nC:/extra/second.pc`n"))) {
  $bad=$queries.Clone();$bad[$name]=[pscustomobject]@{stdout=$value}
  $rejected=$false;try{Assert-MesonFixtureQueries $bad $dependencies|Out-Null}catch{$rejected=$true}
  if(-not $rejected){throw ('Nonexact path accepted: '+$name+' '+$value)}
 }
}
foreach($swap in @(@{name='graphite-path';value=$icu},@{name='icu-path';value=$graphite})) {
 $bad=$queries.Clone();$bad[$swap.name]=[pscustomobject]@{stdout=$swap.value}
 $rejected=$false;try{Assert-MesonFixtureQueries $bad $dependencies|Out-Null}catch{$rejected=$true}
 if(-not $rejected){throw ('Reversed Graphite/ICU selection accepted: '+$swap.name)}
}
""")

    def test_tool_versions_sentinels_and_nonempty_flags_keep_all_existing_oracles(self):
        self.ps(GOOD + r"""
Assert-MesonFixtureQueries $queries $dependencies|Out-Null
foreach($name in @('tool-version','versions','graphite-sentinel','icu-sentinel','cflags','libs')) {
 foreach($remove in @($false,$true)) {
  $bad=$queries.Clone()
  if($remove){$bad.Remove($name)}else{$bad[$name]=[pscustomobject]@{stdout=' '}}
  $rejected=$false;try{Assert-MesonFixtureQueries $bad $dependencies|Out-Null}catch{$rejected=$true}
  if(-not $rejected){throw ('Required existing oracle was weakened: '+$name)}
 }
}
foreach($change in @(@{name='tool-version';value='2.4.4'},
                     @{name='versions';value="78.3`n1.3.15`n"},
                     @{name='versions';value="1.3.15`n78.4`n"},
                     @{name='versions';value="1.3.15`n78.3`n1.0`n"},
                     @{name='graphite-sentinel';value='icu'},
                     @{name='icu-sentinel';value='graphite'})) {
 $bad=$queries.Clone();$bad[$change.name]=[pscustomobject]@{stdout=$change.value}
 $rejected=$false;try{Assert-MesonFixtureQueries $bad $dependencies|Out-Null}catch{$rejected=$true}
 if(-not $rejected){throw ('Wrong existing oracle accepted: '+$change.name)}
}
""")

    def test_actual_literal_query_assignment_has_ten_unique_exact_command_rows(self):
        raw = self.ps(r"""
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile(""" + control.quote(control.SCRIPT) + r""",[ref]$tokens,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
$assignments=@($ast.FindAll({param($node)
 $node -is [Management.Automation.Language.AssignmentStatementAst] -and
 $node.Left -is [Management.Automation.Language.VariableExpressionAst] -and
 $node.Left.VariablePath.UserPath -ceq 'queries'
},$true))
if($assignments.Count -ne 1 -or $assignments[0].Right -isnot [Management.Automation.Language.CommandExpressionAst]) {
 throw 'Expected exactly one actual literal queries assignment'
}
function Get-LiteralArrayAst($expression) {
 if($expression -isnot [Management.Automation.Language.ArrayExpressionAst]){throw 'Expected literal array wrapper'}
 $statements=$expression.SubExpression.Statements
 if($statements.Count -ne 1 -or $statements[0] -isnot [Management.Automation.Language.PipelineAst] -or
    $statements[0].PipelineElements.Count -ne 1 -or
    $statements[0].PipelineElements[0] -isnot [Management.Automation.Language.CommandExpressionAst]) {
  throw 'Dynamic query array expression rejected'
 }
 $literal=$statements[0].PipelineElements[0].Expression
 if($literal -isnot [Management.Automation.Language.ArrayLiteralAst]){throw 'Expected pure literal query array'}
 return $literal
}
$outer=Get-LiteralArrayAst $assignments[0].Right.Expression
$rows=[Collections.Generic.List[object]]::new()
foreach($row in $outer.Elements) {
 $literal=Get-LiteralArrayAst $row
 foreach($element in $literal.Elements) {
  if($element -isnot [Management.Automation.Language.StringConstantExpressionAst]){throw 'Dynamic query element rejected'}
 }
 $rows.Add(@($literal.SafeGetValue()))
}
ConvertTo-Json -InputObject @($rows.ToArray()) -Depth 4 -Compress
""")
        rows = json.loads(raw)
        expected = [
            ['tool-version', '--version'],
            ['exists', '--exists', 'graphite2', 'icu-uc'],
            ['versions', '--modversion', 'graphite2', 'icu-uc'],
            ['graphite-path', '--path', 'graphite2'],
            ['icu-path', '--path', 'icu-uc'],
            ['cflags', '--cflags', 'graphite2', 'icu-uc'],
            ['libs', '--libs', 'graphite2', 'icu-uc'],
            ['graphite-sentinel', '--variable=fixture_control', 'graphite2'],
            ['icu-sentinel', '--variable=fixture_control', 'icu-uc'],
            ['prefix-path', '--path', 'prefix-control'],
        ]
        self.assertEqual(10, len(rows))
        self.assertEqual(10, len({row[0] for row in rows}))
        self.assertEqual(expected, rows)


if __name__ == '__main__':
    unittest.main()
