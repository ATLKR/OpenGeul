using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text.Json;
using Microsoft.Build.Framework;

namespace OpenGeulSynthetic;

// Diagnostic-only. The outer controller owns all process and time boundaries.
public sealed class NumericLogger : ILogger
{
    private static readonly string[] Names = { "", "net_basetypes", "net_uretypes", "net_oootypes", "net_bridge", "ApiVerifier", "NumericLogger" };
    private readonly object sync = new();
    private readonly LoggerReceipt receipt = new();
    private string root = "", output = "";
    private IEventSource? source;
    private bool stopped;

    public LoggerVerbosity Verbosity { get; set; } = LoggerVerbosity.Diagnostic;
    public string Parameters { get; set; } = "";

    public void Initialize(IEventSource eventSource)
    {
        try
        {
            if (source is not null || eventSource is null) throw new InvalidOperationException();
            var parts = Parameters.Split(';');
            if (parts.Length != 3 || !parts[0].StartsWith("root=", StringComparison.Ordinal) ||
                !parts[1].StartsWith("output=", StringComparison.Ordinal) ||
                !parts[2].StartsWith("phase=", StringComparison.Ordinal)) throw new InvalidOperationException();
            root = Canonical(parts[0].Substring(5));
            output = Canonical(parts[1].Substring(7));
            CheckDirectory(root);
            if (!int.TryParse(parts[2].Substring(6), NumberStyles.None, CultureInfo.InvariantCulture, out var phase) ||
                phase < 1 || phase > 65535) throw new InvalidOperationException();
            var observations = Path.Combine(root, "observations");
            if (!string.Equals(Path.GetDirectoryName(output), observations, StringComparison.OrdinalIgnoreCase) ||
                !string.Equals(Path.GetExtension(output), ".json", StringComparison.Ordinal)) throw new InvalidOperationException();
            CheckDirectory(observations);
            if (File.Exists(output) || Directory.Exists(output) || File.Exists(output + ".pending") || Directory.Exists(output + ".pending"))
                throw new InvalidOperationException();
            var stem = Path.GetFileNameWithoutExtension(output).Split('-');
            if (stem.Length != 2 || stem[0] != phase.ToString(CultureInfo.InvariantCulture) ||
                !int.TryParse(stem[1], NumberStyles.None, CultureInfo.InvariantCulture, out var code) ||
                code < 1 || code > 6 || stem[1] != code.ToString(CultureInfo.InvariantCulture)) throw new InvalidOperationException();
            receipt.Phase = phase; receipt.RootProjectCode = code;
            source = eventSource;
            eventSource.BuildStarted += BuildStarted;
            eventSource.BuildFinished += BuildFinished;
            eventSource.ProjectStarted += ProjectStarted;
            eventSource.ProjectFinished += ProjectFinished;
            eventSource.TaskStarted += TaskStarted;
            eventSource.TaskFinished += TaskFinished;
            eventSource.TargetFinished += TargetFinished;
            eventSource.ErrorRaised += ErrorRaised;
        }
        catch (Exception) { throw new LoggerException("Numeric diagnostic initialization rejected."); }
    }

    private static string Canonical(string path)
    {
        if (string.IsNullOrEmpty(path) || path.Any(c => char.IsControl(c) || c == ';') ||
            !Path.IsPathFullyQualified(path) || path.StartsWith(@"\\", StringComparison.Ordinal)) throw new InvalidOperationException();
        var full = Path.GetFullPath(path);
        if (!string.Equals(path, full, StringComparison.Ordinal) || full.Split(Path.DirectorySeparatorChar).Any(p => p == "." || p == ".."))
            throw new InvalidOperationException();
        return full;
    }

    private static void CheckDirectory(string path)
    {
        for (var info = new DirectoryInfo(path); info is not null; info = info.Parent)
            if (!info.Exists || (info.Attributes & FileAttributes.ReparsePoint) != 0) throw new InvalidOperationException();
    }

    private string ProjectPath(int code) => code <= 4
        ? Path.Combine(root, "DotnetLibrary", Names[code], Names[code] + ".csproj")
        : Path.Combine(root, "SdkObserver", Names[code], Names[code] + ".csproj");

    private string OutputPath(int code) => code <= 4
        ? Path.Combine(root, "DotnetLibrary", Names[code], Names[code] + ".dll")
        : Path.Combine(root, "SdkObserver", Names[code], Names[code] + ".dll");

    private int ProjectCode(string? project)
    {
        if (string.IsNullOrEmpty(project) || !Path.IsPathFullyQualified(project)) return 0;
        var full = Path.GetFullPath(project);
        for (var code = 1; code <= 6; code++)
            if (string.Equals(full, ProjectPath(code), StringComparison.OrdinalIgnoreCase)) return code;
        return 0;
    }

    private void Increment(ref int value)
    {
        if (value < 65535) value++;
        else { receipt.Overflow = 1; receipt.LoggerFailed = 1; }
    }

    private void Increment(int[] values, int code)
    {
        if (values[code] < 65535) values[code]++;
        else { receipt.Overflow = 1; receipt.LoggerFailed = 1; }
    }

    private void Capture(Action action)
    {
        lock (sync)
        {
            if (stopped) return;
            try { action(); }
            catch (Exception) { receipt.LoggerFailed = 1; }
        }
    }

    private void BuildStarted(object sender, BuildStartedEventArgs args) => Capture(() =>
    {
        var value = receipt.BuildStarted; Increment(ref value); receipt.BuildStarted = value;
        if (value != 1) receipt.LoggerFailed = 1;
    });

    private void BuildFinished(object sender, BuildFinishedEventArgs args) => Capture(() =>
    {
        var value = receipt.BuildFinished; Increment(ref value); receipt.BuildFinished = value;
        receipt.BuildSucceeded = args.Succeeded ? 1 : 0;
        if (value != 1) receipt.LoggerFailed = 1;
    });

    private void ProjectStarted(object sender, ProjectStartedEventArgs args) => Capture(() => Increment(receipt.ProjectStarted, ProjectCode(args.ProjectFile)));
    private void ProjectFinished(object sender, ProjectFinishedEventArgs args) => Capture(() => Increment(receipt.ProjectFinished, ProjectCode(args.ProjectFile)));

    private void TaskStarted(object sender, TaskStartedEventArgs args) => Capture(() =>
    {
        if (string.Equals(args.TaskName, "Csc", StringComparison.Ordinal)) Increment(receipt.CscStarted, ProjectCode(args.ProjectFile));
    });

    private void TaskFinished(object sender, TaskFinishedEventArgs args) => Capture(() =>
    {
        if (!string.Equals(args.TaskName, "Csc", StringComparison.Ordinal)) return;
        var code = ProjectCode(args.ProjectFile);
        Increment(receipt.CscFinished, code);
        if (args.Succeeded) Increment(receipt.CscSucceeded, code);
        if (receipt.CscFinished[code] > receipt.CscStarted[code]) receipt.LoggerFailed = 1;
    });

    private void TargetFinished(object sender, TargetFinishedEventArgs args) => Capture(() =>
    {
        if (!string.Equals(args.TargetName, "GetTargetPath", StringComparison.Ordinal)) return;
        var code = ProjectCode(args.ProjectFile);
        Increment(receipt.TargetPathSeen, code);
        if (!args.Succeeded || args.TargetOutputs is null) { Increment(receipt.TargetPathUnknown, code); return; }
        var count = 0; var matched = false;
        foreach (var rawItem in args.TargetOutputs)
        {
            if (++count > 1) { Increment(receipt.TargetPathForeign, code); return; }
            if (code != 0 && rawItem is ITaskItem item && Path.IsPathFullyQualified(item.ItemSpec))
                matched = string.Equals(Path.GetFullPath(item.ItemSpec), OutputPath(code), StringComparison.OrdinalIgnoreCase);
        }
        if (count == 0) Increment(receipt.TargetPathUnknown, code);
        else if (matched) Increment(receipt.TargetPathMatched, code);
        else Increment(receipt.TargetPathForeign, code);
    });

    private void ErrorRaised(object sender, BuildErrorEventArgs args) => Capture(() =>
    {
        var total = receipt.ErrorCount; Increment(ref total); receipt.ErrorCount = total;
        if (string.Equals(args.Code, "CS2012", StringComparison.Ordinal))
        { var value = receipt.Cs2012Count; Increment(ref value); receipt.Cs2012Count = value; }
        else { var value = receipt.OtherErrorCount; Increment(ref value); receipt.OtherErrorCount = value; }
    });

    public void Shutdown()
    {
        lock (sync)
        {
            if (stopped) return;
            stopped = true;
            if (source is not null)
            {
                source.BuildStarted -= BuildStarted; source.BuildFinished -= BuildFinished;
                source.ProjectStarted -= ProjectStarted; source.ProjectFinished -= ProjectFinished;
                source.TaskStarted -= TaskStarted; source.TaskFinished -= TaskFinished;
                source.TargetFinished -= TargetFinished; source.ErrorRaised -= ErrorRaised;
            }
            if (receipt.BuildStarted != 1 || receipt.BuildFinished != 1 ||
                Enumerable.Range(0, 7).Any(code => receipt.CscStarted[code] != receipt.CscFinished[code])) receipt.LoggerFailed = 1;
            receipt.Known = receipt.LoggerFailed == 0 && receipt.Overflow == 0 ? 1 : 0;
            // Copy task parameters are deliberately never inspected. Actual copied
            // reference bytes belong to the separate post-build verifier.
            receipt.CopyLocalKnown = 0; receipt.CopyLocalSeen = 0;
            try
            {
                var bytes = JsonSerializer.SerializeToUtf8Bytes(receipt, new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.CamelCase });
                if (bytes.Length > 16384) throw new InvalidOperationException();
                CheckDirectory(Path.GetDirectoryName(output)!);
                if (File.Exists(output) || Directory.Exists(output)) throw new InvalidOperationException();
                using (var stream = new FileStream(output + ".pending", FileMode.CreateNew, FileAccess.Write, FileShare.None))
                { stream.Write(bytes); stream.Flush(true); }
                File.Move(output + ".pending", output, false);
            }
            catch (Exception) { throw new LoggerException("Numeric diagnostic receipt rejected."); }
        }
    }

    private sealed class LoggerReceipt
    {
        public int SchemaVersion { get; set; } = 1;
        public int Phase { get; set; }
        public int RootProjectCode { get; set; }
        public int Known { get; set; }
        public int LoggerFailed { get; set; }
        public int Overflow { get; set; }
        public int BuildStarted { get; set; }
        public int BuildFinished { get; set; }
        public int BuildSucceeded { get; set; }
        public int[] ProjectStarted { get; set; } = new int[7];
        public int[] ProjectFinished { get; set; } = new int[7];
        public int[] CscStarted { get; set; } = new int[7];
        public int[] CscFinished { get; set; } = new int[7];
        public int[] CscSucceeded { get; set; } = new int[7];
        public int[] TargetPathSeen { get; set; } = new int[7];
        public int[] TargetPathMatched { get; set; } = new int[7];
        public int[] TargetPathForeign { get; set; } = new int[7];
        public int[] TargetPathUnknown { get; set; } = new int[7];
        public int CopyLocalKnown { get; set; }
        public int CopyLocalSeen { get; set; }
        public int ErrorCount { get; set; }
        public int Cs2012Count { get; set; }
        public int OtherErrorCount { get; set; }
    }
}
