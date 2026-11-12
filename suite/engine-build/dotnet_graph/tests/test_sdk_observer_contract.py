"""Portable source contracts only; no C# compiler or Windows execution."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'runtime/sdk-observer'


def body(source, declaration):
    start = source.index(declaration)
    start = source.index('{', start)
    depth = 1
    cursor = start + 1
    while depth:
        if source[cursor] == '{': depth += 1
        elif source[cursor] == '}': depth -= 1
        cursor += 1
    return source[start + 1:cursor - 1]


class SdkObserverContracts(unittest.TestCase):
    def source(self, name):
        path = ROOT / name
        self.assertTrue(path.is_file(), 'Missing bounded numeric C# observer')
        return path.read_text()

    def test_logger_observes_typed_csc_target_and_error_events_only(self):
        s = self.source('NumericLogger.cs')
        self.assertIn('class NumericLogger : ILogger', s)
        for event in ('TaskStarted', 'TaskFinished', 'TargetFinished', 'ErrorRaised', 'BuildFinished'):
            self.assertIn('eventSource.' + event + ' +=', s)
        for typed in ('TaskStartedEventArgs', 'TaskFinishedEventArgs', 'TargetFinishedEventArgs', 'BuildErrorEventArgs'):
            self.assertIn(typed, s)
        self.assertIn('"Csc"', s); self.assertIn('"GetTargetPath"', s); self.assertIn('"CS2012"', s)
        for forbidden in ('MessageRaised', 'AnyEventRaised', 'DiagnosticMessage', '.Message', '.StackTrace',
                '.CommandLine', '.GetMetadata(', '.MetadataNames', '.Environment', 'Console.', 'Process.'):
            self.assertNotIn(forbidden, s)

    def test_logger_schema_has_only_closed_numeric_fields(self):
        s = self.source('NumericLogger.cs')
        fields = re.findall(r'public ([\w\[\]?<>]+) (\w+) \{ get; set; \}', body(s, 'class LoggerReceipt'))
        self.assertEqual({name:kind for kind,name in fields}, {
            'SchemaVersion':'int', 'Phase':'int', 'RootProjectCode':'int', 'Known':'int',
            'LoggerFailed':'int', 'Overflow':'int', 'BuildStarted':'int', 'BuildFinished':'int',
            'BuildSucceeded':'int', 'ProjectStarted':'int[]', 'ProjectFinished':'int[]',
            'CscStarted':'int[]', 'CscFinished':'int[]', 'CscSucceeded':'int[]',
            'TargetPathSeen':'int[]', 'TargetPathMatched':'int[]', 'TargetPathForeign':'int[]',
            'TargetPathUnknown':'int[]', 'CopyLocalKnown':'int', 'CopyLocalSeen':'int',
            'ErrorCount':'int', 'Cs2012Count':'int', 'OtherErrorCount':'int'})
        self.assertIn('lock (sync)', s)
        self.assertIn('16384', s); self.assertIn('65535', s)
        self.assertIn('FileMode.CreateNew', s); self.assertIn('File.Move(', s)

    def test_logger_parameter_and_output_paths_are_fresh_owned_and_not_emitted(self):
        s = self.source('NumericLogger.cs')
        for required in ('"root="', '"output="', '"phase="', '"observations"',
                'FileAttributes.ReparsePoint', 'Path.IsPathFullyQualified', 'Path.GetFullPath',
                'StringComparison.OrdinalIgnoreCase', 'File.Exists(output)', 'Directory.Exists(output)'):
            self.assertIn(required, s)
        self.assertIn('parts.Length != 3', s)
        self.assertIn('"DotnetLibrary"', s)
        self.assertIn('item.ItemSpec', s)
        self.assertNotIn('GetEnvironmentVariable', s)
        self.assertNotIn('Parameters,', s)

    def test_verifier_reads_exact_owned_assemblies_and_controlled_api(self):
        s = self.source('ApiVerifier.cs')
        for name in ('net_basetypes', 'net_uretypes', 'net_oootypes', 'net_bridge',
                'BaseValue', 'UreValue', 'OfficeValue', 'BridgeValue'):
            self.assertIn('"' + name + '"', s)
        for required in ('AssemblyLoadContext', 'LoadFromAssemblyPath', 'GetExportedTypes',
                'GetReferencedAssemblies', 'BindingFlags.Public', 'BindingFlags.Static',
                'typeof(int)', 'GetParameters().Length == 0', 'new Version(0, 1, 0, 0)',
                'FileShare.Read', 'SHA256.HashData', '"observations"'):
            self.assertIn(required, s)
        self.assertIn('expectedBase != 1 && expectedBase != 2', s)
        self.assertIn('new[] { expectedBase, expectedBase + 2, expectedBase + 6, expectedBase + 10 }', s)
        for forbidden in ('Console.', '.Message', '.StackTrace', 'GetEnvironmentVariable', 'Process.',
                'Assembly.Load(', 'Assembly.LoadFrom(', 'GetCurrentDirectory'):
            self.assertNotIn(forbidden, s)

    def test_verifier_schema_and_copy_checks_are_numeric_and_fail_closed(self):
        s = self.source('ApiVerifier.cs')
        fields = re.findall(r'public ([\w\[\]?<>]+) (\w+) \{ get; set; \}', body(s, 'class VerifierReceipt'))
        self.assertEqual({name:kind for kind,name in fields}, {
            'SchemaVersion':'int', 'ExpectedBase':'int', 'Known':'int', 'Success':'int',
            'ErrorCode':'int', 'Values':'int[]', 'PublicApi':'int[]',
            'ReferenceClosure':'int[]', 'CopiedReferences':'int[]'})
        self.assertIn('16384', s); self.assertIn('FileMode.CreateNew', s)
        self.assertIn('CryptographicOperations.FixedTimeEquals', s)
        self.assertIn('receipt.CopiedReferences.All(value => value == 1)', s)
        self.assertIn('receipt.PublicApi.All(value => value == 1)', s)
        self.assertIn('receipt.ReferenceClosure.All(value => value == 1)', s)
        self.assertIn('return 2;', s); self.assertIn('return 4;', s)

    def test_verifier_failure_cleanup_cannot_escape_fixed_result_contract(self):
        s = self.source('ApiVerifier.cs')
        cleanup = body(s, 'finally')
        self.assertIn('catch (Exception)', cleanup,
            'A retained stream disposal error must not escape as an unhandled exception')
        self.assertIn('receipt.Known = 0', cleanup)
        self.assertIn('receipt.Success = 0', cleanup)


if __name__ == '__main__':
    unittest.main()
