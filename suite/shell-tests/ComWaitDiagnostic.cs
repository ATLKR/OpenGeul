#nullable enable
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Runtime.Versioning;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

// Synthetic posted-message experiment. Never invoked by ordinary shell tests.
public static class ComWaitDiagnostic
{
    public const string OutputPath = ".work/suite-com-wait-diagnostic/receipt.json";
    const int CallPending = unchecked((int)0x80010115);
    const int OutputLimit = 16384;
    const uint Up = 0x202;
    const uint RendezvousMessage = 0x8051;
    const string Stimulus = "receiver-post-during-owned-rendezvous";
    const int Tag = (37 << 16) | 29;
    static readonly string[] Branches = { "ordinary", "pinned", "counterfactual" };

    public static bool IsDiagnosticCommand(string[] args) => Array.Exists(args, a => a.StartsWith("--com-wait-", StringComparison.Ordinal));
    static bool Architecture(string value) => value == "x64" || value == "arm64";
    static bool Hex(string value, int length)
    {
        if (value.Length != length) return false;
        foreach (char c in value) if (!(c >= '0' && c <= '9') && !(c >= 'a' && c <= 'f')) return false;
        return true;
    }
    static void Require(bool valid, string reason) { if (!valid) throw new InvalidOperationException(reason); }
    static string Classify(string branch, int result, int removedInCall, int deliveredInCall, int totalRemoved, int totalDelivered, bool valid)
    {
        if (!valid || !Array.Exists(Branches, b => b == branch) || totalRemoved < 0 || totalRemoved > 1 || totalDelivered > totalRemoved || totalDelivered < 0 || totalDelivered > 1 || removedInCall < 0 || removedInCall > totalRemoved || deliveredInCall < 0 || deliveredInCall > totalDelivered) return "fixture-failed";
        if (branch == "ordinary") return totalRemoved == 1 && totalDelivered == 1 ? "ordinary-control-valid" : "fixture-failed";
        if (result != CallPending) return "fixture-failed"; // Unsignaled event: even S_OK contradicts the fixture.
        if (totalRemoved == 0) return "inconclusive";
        if (removedInCall == 1 && totalDelivered == 0) return "synthetic-removal-without-observed-delivery";
        if (deliveredInCall == 1) return "synthetic-delivery-during-call";
        return totalDelivered == 1 ? "synthetic-deferred-delivery" : "inconclusive";
    }
    static void Parse(string[] args, out bool child, out string architecture, out string branch, out string nonce)
    {
        child = args.Length > 0 && args[0] == "--com-wait-child";
        architecture = branch = nonce = "";
        if (child)
        {
            Require(args.Length == 7 && args[1] == "--architecture" && args[3] == "--branch" && args[5] == "--nonce", "Invalid child arguments");
            architecture = args[2]; branch = args[4]; nonce = args[6];
            Require(Array.IndexOf(Branches, branch) >= 0 && Hex(nonce, 32), "Invalid child identity");
        }
        else
        {
            Require(args.Length == 5 && args[0] == "--com-wait-diagnostic" && args[1] == "--architecture" && args[3] == "--output" && args[4] == OutputPath, "Invalid diagnostic arguments/output");
            architecture = args[2];
        }
        Require(Architecture(architecture), "Invalid architecture");
    }
    static void Admission(string architecture)
    {
        Require(OperatingSystem.IsWindows(), "Windows native fixture only");
        Require(IntPtr.Size == 8 && RuntimeInformation.OSArchitecture == RuntimeInformation.ProcessArchitecture && RuntimeInformation.ProcessArchitecture.ToString().ToLowerInvariant() == architecture, "Native architecture mismatch/emulation");
        string sha = Environment.GetEnvironmentVariable("GITHUB_SHA") ?? "";
        Require(Hex(sha, 40) && Environment.GetEnvironmentVariable("OPENGEUL_COM_WAIT_ADMITTED_SHA") == sha &&
            Environment.GetEnvironmentVariable("GITHUB_ACTIONS") == "true" && Environment.GetEnvironmentVariable("GITHUB_EVENT_NAME") == "push" &&
            Environment.GetEnvironmentVariable("GITHUB_RUN_ATTEMPT") == "1" && Environment.GetEnvironmentVariable("GITHUB_REPOSITORY") == "ATLKR/OpenGeul" &&
            Environment.GetEnvironmentVariable("GITHUB_REPOSITORY_OWNER") == "ATLKR", "Missing fresh owner/source workflow admission");
    }
    public static async Task<int> RunAsync(string[] args)
    {
        try
        {
            Parse(args, out bool child, out string architecture, out string branch, out string nonce);
            Admission(architecture);
            if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
            if (child)
            {
                var completion = new TaskCompletionSource<Receipt>(TaskCreationOptions.RunContinuationsAsynchronously);
                long deadline = Stopwatch.GetTimestamp() + 5 * Stopwatch.Frequency; // Newly defined fixture budget, not an Office budget.
                var thread = new Thread(() =>
                {
                    try
                    {
                        // The escaped delegate needs its own platform guard for net8 analysis.
                        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
                        completion.SetResult(new NativeCase(branch, nonce, architecture, deadline).Run());
                    }
                    catch (Exception e) { completion.SetException(e); }
                }) { IsBackground = true };
                thread.SetApartmentState(ApartmentState.STA);
                thread.Start();
                Receipt receipt = await completion.Task;
                string encoded = JsonSerializer.Serialize(receipt);
                Require(Encoding.UTF8.GetByteCount(encoded) <= OutputLimit, "Child receipt overflow");
                Console.WriteLine(encoded);
                return receipt.Outcome == "fixture-failed" ? 1 : 0;
            }
            var results = new List<JsonElement>();
            string? failure = null;
            foreach (string arm in Branches)
            {
                try
                {
                    JsonElement result = await ChildAsync(architecture, arm);
                    results.Add(result);
                    if (result.GetProperty("Outcome").GetString() == "fixture-failed") { failure = "Child fixture failed: " + arm; break; }
                }
                catch (Exception e) { failure = e.GetType().Name; break; }
            }
            var report = new { SchemaVersion = 2, Stimulus, Kind = "synthetic-sta-com-wait", Architecture = architecture,
                SourceCommit = Environment.GetEnvironmentVariable("GITHUB_SHA"), Acceptance = false, PhysicalInputReproduced = false,
                Cases = results, Failure = failure };
            Directory.CreateDirectory(Path.GetDirectoryName(OutputPath)!);
            File.WriteAllText(OutputPath, JsonSerializer.Serialize(report, new JsonSerializerOptions { WriteIndented = true }));
            return failure == null && results.Count == 3 ? 0 : 1;
        }
        catch (Exception e)
        {
            Console.Error.WriteLine("COM wait fixture rejected: " + e.GetType().Name);
            return 1;
        }
    }
    static async Task<byte[]> ReadBoundedAsync(Stream stream, CancellationToken token, int limit = OutputLimit)
    {
        using var output = new MemoryStream();
        byte[] buffer = new byte[1024];
        while (true)
        {
            int count = await stream.ReadAsync(buffer.AsMemory(), token);
            if (count == 0) return output.ToArray();
            if (output.Length + count > limit) throw new InvalidDataException("Child output exceeded16KiB");
            output.Write(buffer, 0, count);
        }
    }
    static async Task<byte[]> WatchRead(Stream stream, CancellationTokenSource stop, int limit = OutputLimit)
    {
        try { return await ReadBoundedAsync(stream, stop.Token, limit); }
        catch { stop.Cancel(); throw; }
    }
    static async Task<JsonElement> ChildAsync(string architecture, string branch)
    {
        long deadline = Stopwatch.GetTimestamp() + 10 * Stopwatch.Frequency;
        string nonce = Guid.NewGuid().ToString("N");
        string executable = Environment.ProcessPath ?? throw new InvalidOperationException("Missing executable");
        var start = new ProcessStartInfo(executable) { UseShellExecute = false, RedirectStandardOutput = true, RedirectStandardError = true, CreateNoWindow = true };
        if (string.Equals(Path.GetFileNameWithoutExtension(executable), "dotnet", StringComparison.OrdinalIgnoreCase))
            start.ArgumentList.Add(Assembly.GetExecutingAssembly().Location);
        foreach (string arg in new[] { "--com-wait-child", "--architecture", architecture, "--branch", branch, "--nonce", nonce }) start.ArgumentList.Add(arg);
        using var process = new Process { StartInfo = start };
        using var timeout = new CancellationTokenSource();
        Task<byte[]>? stdout = null, stderr = null;
        bool started = false, exited = false;
        try
        {
            Require(process.Start(), "Child launch failed"); started = true;
            int remaining = RemainingMilliseconds(deadline);
            Require(remaining > 0, "Child startup deadline expired");
            timeout.CancelAfter(remaining);
            stdout = WatchRead(process.StandardOutput.BaseStream, timeout);
            stderr = WatchRead(process.StandardError.BaseStream, timeout, 0); // Any stderr byte fails immediately; total accepted output <=16KiB.
            await Task.WhenAll(process.WaitForExitAsync(timeout.Token), stdout, stderr).WaitAsync(timeout.Token);
            exited = process.HasExited;
            Require(Stopwatch.GetTimestamp() < deadline && exited, "Child watchdog expired");
            Require(process.ExitCode == 0 || process.ExitCode == 1, "Unexpected child exit");
            Require(stderr.Result.Length == 0, "Unexpected child stderr");
            using JsonDocument document = JsonDocument.Parse(stdout.Result);
            JsonElement receipt = document.RootElement;
            Receipt parsed = JsonSerializer.Deserialize<Receipt>(stdout.Result) ?? throw new InvalidDataException("Missing child receipt");
            Require(IdentityMatches(parsed, nonce, branch, architecture, process.Id) &&
                (parsed.Outcome == "fixture-failed" ? process.ExitCode == 1 : process.ExitCode == 0 && parsed.CleanupSucceeded), "Child receipt identity/cleanup mismatch");
            Require(parsed.Outcome == "fixture-failed" || ValidReceipt(parsed), "Malformed successful child receipt");
            return receipt.Clone();
        }
        finally
        {
            timeout.Cancel();
            using var cleanup = new CancellationTokenSource(TimeSpan.FromSeconds(2));
            if (started && !exited)
            {
                if (!process.HasExited) process.Kill(); // Only this retained child; no descendants are created.
                await process.WaitForExitAsync(cleanup.Token);
                Require(process.HasExited, "Retained child exit unconfirmed");
            }
            // Observe reader failures; no additional per-reader timeout allowance.
            if (stdout != null) { try { await stdout.WaitAsync(cleanup.Token); } catch (OperationCanceledException) { } catch (InvalidDataException) { } }
            if (stderr != null) { try { await stderr.WaitAsync(cleanup.Token); } catch (OperationCanceledException) { } catch (InvalidDataException) { } }
        }
    }
    static int RemainingMilliseconds(long deadline) => (int)Math.Max(0, Math.Min(int.MaxValue, (deadline - Stopwatch.GetTimestamp()) * 1000.0 / Stopwatch.Frequency));

    static bool IdentityMatches(Receipt r, string nonce, string branch, string architecture, int pid) =>
        r.Nonce == nonce && r.Branch == branch && r.Architecture == architecture && r.Pid == pid;
    static bool ValidArrival(Receipt r)
    {
        ArrivalGate a = r.Arrival;
        ProducerReceipt? p = r.Producer;
        if (r.SchemaVersion != 2 || r.Stimulus != Stimulus || !r.ProducerResourceQuiescent || r.ProducerThreadExitProved ||
            r.ProducerStartEventClosed != true || r.ProducerDoneEventClosed != true || p == null || a == null || a.Invalid ||
            p.Error != null || p.Tid == 0 || p.Tid == r.Tid || p.SendAttempts != 1 || p.SendBefore < r.CallBefore ||
            p.SendBefore > p.SendAfter || p.SendAfter >= r.Deadline || a.Attempts < 0 || a.Attempts > 1 ||
            r.ArmDeadline != Math.Min(r.Deadline, r.CallBefore + r.Frequency)) return false;
        if (a.PostAttempts == 1)
            return a.Attempts == 1 && a.PostSucceeded && a.Phase == (r.Branch == "ordinary" ? 1 : 2) &&
                r.CallBefore <= a.Entry && p.SendBefore <= a.Entry && a.Entry <= a.PostBefore && a.PostBefore <= a.PostAfter && a.PostAfter <= a.Ack &&
                a.Ack <= r.CallAfter && a.Ack < r.ArmDeadline && a.Ack <= p.SendAfter && r.Posted == a.PostAfter && p.SendSucceeded && p.Ack == 1;
        if (a.PostAttempts != 0 || a.PostSucceeded || r.Posted != 0 || a.PostBefore != 0 || a.PostAfter != 0 || a.Ack != 0 || r.Rows.Length != 0 || r.Branch == "ordinary") return false;
        if (!p.SendSucceeded && p.LastError != 1460) return false; // Generic/API failure is not called a timeout.
        if (p.SendSucceeded && p.Ack != 0) return false;
        return a.Attempts == 0 ? a.Entry == 0 && a.Phase == 0 && !p.SendSucceeded :
            a.Phase >= 3 && a.Phase <= 4 && a.Entry >= r.CallAfter && a.Entry < r.Deadline;
    }
    static bool ValidReceipt(Receipt r)
    {
        if (!ValidArrival(r) || !r.CleanupSucceeded || r.HookRemoved != true || r.WindowDestroyed != true || r.ClassUnregistered != true || r.EventClosed != true || r.ComBalanced != true || r.Error != null || r.Overflow || r.Reentrancy || r.CallbackError || r.Frequency <= 0 || r.Tid == 0 || r.Hwnd == 0 ||
            (r.Apartment != 0 && r.Apartment != 3) || r.Rows == null || r.Rows.Length > 32 ||
            r.Ready <= 0 || r.Ready < r.Deadline - 5 * r.Frequency || r.Ready > r.CallBefore || r.CallBefore > r.CallAfter || r.CallAfter > r.DrainEnd || r.DrainEnd >= r.Deadline) return false;
        int removed = 0, delivered = 0, inRemoved = 0, inDelivered = 0, beforeDrain = 0;
        if (r.WaitIndex != null || (r.Branch == "ordinary" && r.HResult != 0)) return false;
        long previous = r.Posted == 0 ? r.CallBefore : r.Posted;
        int previousPhase = 0;
        for (int i = 0; i < r.Rows.Length; i++)
        {
            Row row = r.Rows[i];
            if (row.Sequence != i + 1 || row.Qpc < previous || row.Qpc > r.DrainEnd || row.Phase < 1 || row.Phase > 3 ||
                row.Phase < previousPhase ||
                (row.Phase == 1 && (r.Branch != "ordinary" || row.Qpc < r.CallBefore || row.Qpc > r.CallAfter)) ||
                (row.Phase == 2 && (r.Branch == "ordinary" || row.Qpc < r.CallBefore || row.Qpc > r.CallAfter)) ||
                (row.Phase == 3 && row.Qpc < r.CallAfter)) return false;
            previous = row.Qpc; previousPhase = row.Phase;
            if (row.Source == "getmessage")
            {
                if (row.RemovalFlags < 0 || row.RemovalFlags > 3) return false;
                if ((row.RemovalFlags & 1) != 0) { removed++; if (row.Phase == 2) inRemoved++; }
            }
            else if (row.Source == "wndproc")
            {
                if (row.RemovalFlags != 0 || removed != 1) return false;
                delivered++; if (row.Phase == 2) inDelivered++;
                if (row.Phase != 3) beforeDrain++;
            }
            else return false;
        }
        return r.DeliveredBeforeDrain == beforeDrain && r.Outcome == Classify(r.Branch, r.HResult, inRemoved, inDelivered, removed, delivered, true) && r.Outcome != "fixture-failed";
    }
    static void SeedArrival(Receipt r)
    {
        r.ArmDeadline = Math.Min(r.Deadline, r.CallBefore + r.Frequency);
        r.ProducerResourceQuiescent = true; r.ProducerStartEventClosed = true; r.ProducerDoneEventClosed = true;
        r.Arrival = new ArrivalGate { Attempts = 1, PostAttempts = 1, Phase = r.Branch == "ordinary" ? 1 : 2,
            Entry = r.CallBefore, PostBefore = r.Posted, PostAfter = r.Posted, Ack = r.Posted, PostSucceeded = true };
        r.Producer = new ProducerReceipt { Tid = r.Tid + 1, SendAttempts = 1, SendBefore = r.CallBefore, SendAfter = r.Posted + 1, SendSucceeded = true, Ack = 1 };
    }
    public static void PureContractTests()
    {
        ArrivalContractTests();
        Require(Classify("ordinary", 0, 0, 0, 1, 1, true) == "ordinary-control-valid", "control classifier");
        Require(Classify("pinned", CallPending, 0, 0, 0, 0, true) == "inconclusive", "no qualifying COM removal is inconclusive");
        Require(Classify("ordinary", 0, 0, 0, 0, 0, true) == "fixture-failed", "empty control fails");
        Require(Classify("pinned", CallPending, 0, 0, 0, 1, true) == "fixture-failed", "delivery without removal fails");
        Require(Classify("pinned", 0, 0, 0, 0, 0, true) == "fixture-failed", "empty unexpected success fails");
        Require(Classify("pinned", CallPending, 1, 0, 1, 0, true) == "synthetic-removal-without-observed-delivery", "suppression classifier");
        Require(Classify("pinned", CallPending, 0, 0, 1, 1, true) == "synthetic-deferred-delivery", "deferred classifier");
        Require(Classify("counterfactual", CallPending, 1, 1, 1, 1, true) == "synthetic-delivery-during-call", "nested classifier");
        foreach (int result in new[] { 0, -1 }) Require(Classify("pinned", result, 1, 0, 1, 0, true) == "fixture-failed", "unsignaled event rejects success/error");
        Require(Classify("pinned", CallPending, 1, 0, 1, 0, false) == "fixture-failed", "invalid trace rejected");
        Require(Classify("pinned", CallPending, 1, 2, 1, 2, true) == "fixture-failed", "duplicate rejected");
        Parse(new[] { "--com-wait-diagnostic", "--architecture", "arm64", "--output", OutputPath }, out bool child, out _, out _, out _);
        Require(!child, "parent route");
        foreach (string arm in Branches) Parse(new[] { "--com-wait-child", "--architecture", "x64", "--branch", arm, "--nonce", new string('a', 32) }, out _, out _, out _, out _);
        bool rejected = false;
        try { Parse(new[] { "--com-wait-diagnostic", "--architecture", "x64", "--output", "elsewhere.json" }, out _, out _, out _, out _); } catch (InvalidOperationException) { rejected = true; }
        Require(rejected, "arbitrary output rejected");
        Require(ReadBoundedAsync(new MemoryStream(new byte[OutputLimit]), CancellationToken.None).GetAwaiter().GetResult().Length == OutputLimit, "bounded exact read");
        rejected = false;
        try { ReadBoundedAsync(new MemoryStream(new byte[OutputLimit + 1]), CancellationToken.None).GetAwaiter().GetResult(); } catch (InvalidDataException) { rejected = true; }
        Require(rejected, "oversized live stream rejected");
        rejected = false;
        try { ReadBoundedAsync(new MemoryStream(new byte[1]), CancellationToken.None, 0).GetAwaiter().GetResult(); } catch (InvalidDataException) { rejected = true; }
        Require(rejected, "stderr first byte rejected");
        var valid = new Receipt { Branch = "pinned", Tid = 1, Hwnd = 10, Apartment = 0, Frequency = 100, Deadline = 600,
            Ready = 101, Posted = 104, CallBefore = 103, CallAfter = 204, DrainEnd = 205, HResult = CallPending,
            Nonce = new string('a', 32), Pid = 12, Architecture = "arm64", HookRemoved = true, WindowDestroyed = true, ClassUnregistered = true, EventClosed = true, ComBalanced = true,
            CleanupSucceeded = true, Outcome = "synthetic-removal-without-observed-delivery",
            Rows = new[] { new Row { Sequence = 1, Qpc = 104, Phase = 2, Source = "getmessage", RemovalFlags = 3 } } };
        SeedArrival(valid);
        Require(ValidReceipt(valid), "valid correlated receipt");
        Require(IdentityMatches(valid, new string('a', 32), "pinned", "arm64", 12), "bound child identity");
        Require(!IdentityMatches(valid, new string('b', 32), "pinned", "arm64", 12) && !IdentityMatches(valid, new string('a', 32), "ordinary", "arm64", 12) &&
            !IdentityMatches(valid, new string('a', 32), "pinned", "x64", 12) && !IdentityMatches(valid, new string('a', 32), "pinned", "arm64", 13), "forged identities rejected");
        valid.Rows[0].Phase = 1; Require(!ValidReceipt(valid), "COM phase1 rejected"); valid.Rows[0].Phase = 2;
        valid.Rows[0].Phase = 3; Require(!ValidReceipt(valid), "drain before call return rejected"); valid.Rows[0].Phase = 2;
        valid.WaitIndex = 0; Require(!ValidReceipt(valid), "unsignaled wait index rejected"); valid.WaitIndex = null;
        var reordered = new Receipt { Branch = "ordinary", Tid = 1, Hwnd = 10, Apartment = 0, Frequency = 100, Deadline = 600,
            Ready = 101, Posted = 104, CallBefore = 103, CallAfter = 204, DrainEnd = 205, CleanupSucceeded = true,
            HookRemoved = true, WindowDestroyed = true, ClassUnregistered = true, EventClosed = true, ComBalanced = true,
            DeliveredBeforeDrain = 1, Outcome = "ordinary-control-valid", Rows = new[] {
                new Row { Sequence = 1, Qpc = 104, Phase = 1, Source = "wndproc" },
                new Row { Sequence = 2, Qpc = 105, Phase = 1, Source = "getmessage", RemovalFlags = 1 } } };
        SeedArrival(reordered);
        Require(!ValidReceipt(reordered), "delivery before removal rejected");
        reordered.Rows[0].Source = "getmessage"; reordered.Rows[0].RemovalFlags = 1;
        reordered.Rows[1].Source = "wndproc"; reordered.Rows[1].RemovalFlags = 0;
        Require(ValidReceipt(reordered), "ordered ordinary control");
        reordered.HResult = CallPending; Require(!ValidReceipt(reordered), "ordinary COM result rejected"); reordered.HResult = 0;
        reordered.Branch = "pinned"; reordered.HResult = CallPending; reordered.Outcome = "synthetic-deferred-delivery";
        Require(!ValidReceipt(reordered), "delivered COM phase1 forged as deferred rejected");
        reordered.Rows[0].Phase = 3; reordered.Rows[1].Phase = 3; reordered.DeliveredBeforeDrain = 0;
        Require(!ValidReceipt(reordered), "early drain forged as deferred rejected");
        reordered.Branch = "ordinary"; reordered.HResult = 0; reordered.Outcome = "ordinary-control-valid";
        reordered.Rows[1].Phase = 1; reordered.DeliveredBeforeDrain = 1;
        reordered.Rows[0].Phase = 3; reordered.Rows[0].Qpc = 204; reordered.Rows[1].Qpc = 204;
        Require(!ValidReceipt(reordered), "phase reversal rejected");
        Row[] savedRows = valid.Rows;
        valid.Rows = Array.Empty<Row>(); valid.Outcome = "inconclusive";
        Require(ValidReceipt(valid), "valid empty COM observation stays inconclusive");
        valid.Rows = savedRows; valid.Outcome = "synthetic-removal-without-observed-delivery";
        valid.Overflow = true; Require(!ValidReceipt(valid), "overflow receipt rejected"); valid.Overflow = false;
        valid.CleanupSucceeded = false; Require(!ValidReceipt(valid), "cleanup receipt rejected"); valid.CleanupSucceeded = true;
        valid.Rows[0].Qpc = 99; Require(!ValidReceipt(valid), "out-of-order receipt rejected"); valid.Rows[0].Qpc = 104;
        valid.Rows[0].Sequence = 2; Require(!ValidReceipt(valid), "forged sequence rejected"); valid.Rows[0].Sequence = 1;
        valid.Rows = new[] { valid.Rows[0], new Row { Sequence = 2, Qpc = 105, Phase = 2, Source = "getmessage", RemovalFlags = 3 } };
        Require(!ValidReceipt(valid), "duplicate removal rejected");
        if (IntPtr.Size == 8) Require(Marshal.SizeOf<Msg>() == 48 && Marshal.SizeOf<WindowClass>() == 80, "Win64 ABI layout");
    }

    static bool CanDisposeProducer(bool started, bool quiescent) => !started || quiescent;
    static void EmitFailureThenTerminate(Action emit, Action terminate)
    {
        try { emit(); }
        finally { terminate(); }
    }
    public sealed class ArrivalGate
    {
        public int Attempts { get; set; }
        public int PostAttempts { get; set; }
        public int Phase { get; set; }
        public long Entry { get; set; }
        public long PostBefore { get; set; }
        public long PostAfter { get; set; }
        public long Ack { get; set; }
        public bool PostSucceeded { get; set; }
        public bool Invalid { get; set; }
        public bool TryBegin(bool owned, int phase, long now, long deadline)
        {
            if (!owned) return false;
            if (Attempts != 0) { Invalid = true; return false; }
            Attempts = 1; Phase = phase; Entry = now;
            if ((phase != 1 && phase != 2) || now <= 0 || now >= deadline) return false;
            PostAttempts = 1;
            return true;
        }
        public void Complete(bool success, long before, long after, long ack)
        {
            PostBefore = before; PostAfter = after; Ack = ack; PostSucceeded = success;
            if (PostAttempts != 1 || !success || Entry > before || before > after || after > ack) Invalid = true;
        }
    }
    public sealed class ProducerReceipt
    {
        public uint Tid { get; set; }
        public int SendAttempts { get; set; }
        public long SendBefore { get; set; }
        public long SendAfter { get; set; }
        public bool SendSucceeded { get; set; }
        public ulong Ack { get; set; }
        public int LastError { get; set; }
        public string? Error { get; set; }
    }
    public static void ArrivalContractTests()
    {
        var gate = new ArrivalGate();
        Require(!gate.TryBegin(false, 2, 100, 200) && gate.Attempts == 0, "foreign rendezvous ignored");
        Require(gate.TryBegin(true, 2, 100, 200), "during-call rendezvous admitted");
        gate.Complete(true, 101, 102, 103);
        Require(gate.PostAttempts == 1 && gate.PostSucceeded && !gate.Invalid, "one callback post");
        Require(!gate.TryBegin(true, 2, 104, 200) && gate.Invalid && gate.PostAttempts == 1, "duplicate never posts");
        var late = new ArrivalGate();
        Require(!late.TryBegin(true, 3, 100, 200) && late.PostAttempts == 0, "drain rendezvous never posts");
        var expired = new ArrivalGate();
        Require(!expired.TryBegin(true, 2, 200, 200) && expired.PostAttempts == 0, "deadline rendezvous never posts");
        var failed = new ArrivalGate();
        Require(failed.TryBegin(true, 1, 100, 200), "ordinary admission"); failed.Complete(false, 101, 102, 103);
        Require(failed.Invalid && !failed.PostSucceeded, "failed post not qualified");
        var sample = new Receipt { Branch = "pinned", Tid = 1, Frequency = 100, Deadline = 600, CallBefore = 103, CallAfter = 204, Posted = 104 };
        SeedArrival(sample);
        Require(ValidArrival(sample), "qualified callback chronology");
        sample.Arrival.PostAfter = 205; Require(!ValidArrival(sample), "post after return rejected"); sample.Arrival.PostAfter = 104;
        sample.ProducerResourceQuiescent = false; Require(!ValidArrival(sample), "unconfirmed barrier rejected"); sample.ProducerResourceQuiescent = true;
        sample.SchemaVersion = 1; Require(!ValidArrival(sample), "historical prequeued schema rejected"); sample.SchemaVersion = 2;
        sample.Arrival = new ArrivalGate(); sample.Posted = 0;
        sample.Producer!.SendSucceeded = false; sample.Producer.LastError = 1460; sample.Producer.Ack = 0;
        Require(ValidArrival(sample), "no rendezvous timeout is unqualified not fabricated input");
        sample.Producer.LastError = 0; Require(!ValidArrival(sample), "generic send failure not called timeout");
        bool terminationCalled = false;
        try { EmitFailureThenTerminate(() => throw new IOException("synthetic output failure"), () => terminationCalled = true); } catch (IOException) { }
        Require(terminationCalled, "failed failure receipt cannot bypass process containment");
        Require(!CanDisposeProducer(true, false) && CanDisposeProducer(true, true) && CanDisposeProducer(false, false), "unconfirmed resource barrier prohibits disposal");
    }

    public sealed class Row
    {
        public int Sequence { get; set; }
        public long Qpc { get; set; }
        public int Phase { get; set; }
        public string Source { get; set; } = "";
        public long RemovalFlags { get; set; }
    }
    public sealed class Receipt
    {
        public int SchemaVersion { get; set; } = 2;
        public string Stimulus { get; set; } = ComWaitDiagnostic.Stimulus;
        public ArrivalGate Arrival { get; set; } = new ArrivalGate();
        public ProducerReceipt? Producer { get; set; }
        public bool ProducerResourceQuiescent { get; set; }
        public bool ProducerThreadExitProved { get; set; } // Resource barrier is deliberately not thread-exit proof.
        public bool? ProducerStartEventClosed { get; set; }
        public bool? ProducerDoneEventClosed { get; set; }
        public long ArmDeadline { get; set; }
        public string Nonce { get; set; } = "";
        public string Branch { get; set; } = "";
        public string Architecture { get; set; } = "";
        public int Pid { get; set; }
        public uint Tid { get; set; }
        public long Hwnd { get; set; }
        public int Apartment { get; set; }
        public int ApartmentQualifier { get; set; }
        public long Frequency { get; set; }
        public long Deadline { get; set; }
        public long Ready { get; set; }
        public long Posted { get; set; }
        public long CallBefore { get; set; }
        public long CallAfter { get; set; }
        public long DrainEnd { get; set; }
        public int HResult { get; set; }
        public uint? WaitIndex { get; set; }
        public int DeliveredBeforeDrain { get; set; }
        public bool Overflow { get; set; }
        public bool Reentrancy { get; set; }
        public bool CallbackError { get; set; }
        public bool? HookRemoved { get; set; }
        public bool? WindowDestroyed { get; set; }
        public bool? ClassUnregistered { get; set; }
        public bool? EventClosed { get; set; }
        public bool? ComBalanced { get; set; }
        public bool CleanupSucceeded { get; set; }
        public string Stage { get; set; } = "start";
        public string? Error { get; set; }
        public string Outcome { get; set; } = "fixture-failed";
        public Row[] Rows { get; set; } = Array.Empty<Row>();
    }
    struct NativeRow { public long Qpc, Flags; public int Phase, Source; }
    [SupportedOSPlatform("windows")]
    sealed class NativeCase
    {
        readonly Receipt receipt;
        readonly NativeRow[] rows = new NativeRow[32];
        readonly long deadline;
        readonly WindowProcedure procedure;
        readonly HookProcedure hookProcedure;
        IntPtr window, hook, signal, producerStart, producerDone;
        readonly ProducerReceipt producerReceipt = new ProducerReceipt();
        readonly UIntPtr rendezvousToken;
        Thread? producer;
        bool producerStarted;
        ushort atom;
        int count, phase, depth, removed, delivered, removedInCall, deliveredInCall;
        bool initialized, overflow, reentered, callbackError;
        readonly string className;
        public NativeCase(string branch, string nonce, string architecture, long deadline)
        {
            receipt = new Receipt { Branch = branch, Nonce = nonce, Architecture = architecture, Pid = Environment.ProcessId, Deadline = deadline };
            this.deadline = deadline; className = "OpenGeulSyntheticComWait_" + nonce;
            procedure = WndProc; hookProcedure = Hook;
            rendezvousToken = new UIntPtr(Convert.ToUInt64(nonce.Substring(0, 16), 16));
        }
        long Clock()
        {
            Require(Native.QueryPerformanceCounter(out long value) && value > 0, "QPC failed");
            Require(value < deadline && Native.GetCurrentThreadId() == receipt.Tid, "Fixture original deadline/thread mismatch");
            return value;
        }
        void Observe(int source, long flags)
        {
            try
            {
                if (!Native.QueryPerformanceCounter(out long now) || now >= deadline || Native.GetCurrentThreadId() != receipt.Tid) { callbackError = true; return; }
                if (count == rows.Length) { overflow = true; return; }
                rows[count++] = new NativeRow { Qpc = now, Flags = flags, Phase = phase, Source = source };
                if (source == 1 && (flags & 1) != 0) { removed++; if (phase == 2) removedInCall++; }
                if (source == 2) { delivered++; if (phase == 2) deliveredInCall++; }
            }
            catch { callbackError = true; }
        }
        IntPtr Hook(int code, UIntPtr flags, IntPtr message)
        {
            depth++;
            try
            {
                // Win64 MSG offsets; no managed object construction inside callback.
                if (code >= 0 && Marshal.ReadIntPtr(message) == window && Marshal.ReadInt32(message, 8) == Up &&
                    Marshal.ReadIntPtr(message, 16) == IntPtr.Zero && Marshal.ReadIntPtr(message, 24) == new IntPtr(Tag) && phase >= 1 && phase <= 3)
                { if (depth > 1) reentered = true; Observe(1, unchecked((long)flags.ToUInt64())); }
            }
            catch { callbackError = true; }
            try { return Native.CallNextHookEx(hook, code, flags, message); }
            catch { callbackError = true; return IntPtr.Zero; }
            finally { depth--; }
        }
        IntPtr WndProc(IntPtr hwnd, uint message, UIntPtr wp, IntPtr lp)
        {
            depth++;
            try
            {
                if (hwnd == window && message == RendezvousMessage && wp == rendezvousToken && lp == new IntPtr(Tag))
                {
                    if (!Native.QueryPerformanceCounter(out long now) || Native.GetCurrentThreadId() != receipt.Tid) { callbackError = true; return IntPtr.Zero; }
                    if (!receipt.Arrival.TryBegin(true, phase, now, Math.Min(deadline, receipt.ArmDeadline))) return IntPtr.Zero;
                    if (depth > 1) { reentered = true; return IntPtr.Zero; }
                    if (!Native.QueryPerformanceCounter(out long before) || before >= deadline || before >= receipt.ArmDeadline) { callbackError = true; return IntPtr.Zero; }
                    bool posted = Native.PostMessageW(window, Up, UIntPtr.Zero, new IntPtr(Tag));
                    bool afterOk = Native.QueryPerformanceCounter(out long after);
                    bool ackOk = Native.QueryPerformanceCounter(out long ack);
                    receipt.Arrival.Complete(posted && afterOk && ackOk, before, after, ack);
                    receipt.Posted = after;
                    if (!posted || !afterOk || !ackOk || ack >= deadline || ack >= receipt.ArmDeadline) { callbackError = true; return IntPtr.Zero; }
                    return new IntPtr(1); // The sole up has already been posted before ACK.
                }
                if (hwnd == window && message == Up && wp == UIntPtr.Zero && lp == new IntPtr(Tag) && phase >= 1 && phase <= 3)
                { if (depth > 1) reentered = true; Observe(2, 0); }
                return Native.DefWindowProcW(hwnd, message, wp, lp);
            }
            catch { callbackError = true; return IntPtr.Zero; }
            finally { depth--; }
        }
        void StartProducer()
        {
            Clock(); producerStart = Native.CreateEventW(IntPtr.Zero, true, false, null); Require(producerStart != IntPtr.Zero, "Producer start event failed");
            Clock(); producerDone = Native.CreateEventW(IntPtr.Zero, true, false, null); Require(producerDone != IntPtr.Zero, "Producer done event failed");
            // Immutable native targets; publisher makes no resource access after final SetEvent(done).
            IntPtr target = window, start = producerStart, done = producerDone;
            UIntPtr token = rendezvousToken;
            ProducerReceipt result = producerReceipt;
            long originalDeadline = deadline;
            producer = new Thread(() =>
            {
                try
                {
                    if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
                    result.Tid = Native.GetCurrentThreadId();
                    int remaining = RemainingMilliseconds(originalDeadline);
                    if (remaining <= 0 || Native.WaitForSingleObject(start, (uint)remaining) != 0) { result.Error = "StartUnavailable"; return; }
                    remaining = Math.Min(1000, RemainingMilliseconds(originalDeadline));
                    if (remaining <= 0 || !Native.QueryPerformanceCounter(out long before)) { result.Error = "ProducerDeadline"; return; }
                    result.SendBefore = before; result.SendAttempts = 1;
                    Marshal.SetLastPInvokeError(0);
                    IntPtr sent = Native.SendMessageTimeoutW(target, RendezvousMessage, token, new IntPtr(Tag), 0x23, (uint)remaining, out UIntPtr ack);
                    int error = Marshal.GetLastPInvokeError();
                    bool clock = Native.QueryPerformanceCounter(out long after);
                    result.SendAfter = after; result.SendSucceeded = sent != IntPtr.Zero; result.Ack = ack.ToUInt64(); result.LastError = error;
                    if (!clock || after >= originalDeadline) result.Error = "ProducerDeadline";
                }
                catch { result.Error = "ProducerException"; }
                finally
                {
                    Native.SetEvent(done); // FINAL native/resource operation: release-publishes all result fields.
                }
            }) { IsBackground = true };
            Clock(); producer.Start(); producerStarted = true;
        }
        void OrdinaryPump()
        {
            for (int i = 0; i < 256; i++)
            {
                Clock();
                int remaining = RemainingMilliseconds(receipt.ArmDeadline);
                if (remaining <= 0) return;
                uint wait = Native.MsgWaitForMultipleObjectsEx(0, IntPtr.Zero, (uint)remaining, 0x48, 4); // SENDMESSAGE|POSTMESSAGE, ordinary API only.
                Clock();
                if (wait == 258) return;
                Require(wait == 0, "Ordinary message wait failed");
                if (Stopwatch.GetTimestamp() >= receipt.ArmDeadline) return;
                // Peek dispatches the sent rendezvous even if no posted item is returned.
                if (Native.PeekMessageW(out Msg msg, IntPtr.Zero, 0, 0, 1))
                {
                    Clock();
                    if (Stopwatch.GetTimestamp() >= receipt.ArmDeadline) return;
                    Native.DispatchMessageW(ref msg);
                }
                if (delivered == 1) return;
            }
            throw new InvalidOperationException("Ordinary wake cap");
        }
        void Drain()
        {
            for (int i = 0; i < 256; i++)
            {
                Clock();
                if (!Native.PeekMessageW(out Msg msg, IntPtr.Zero, 0, 0, 1)) return;
                Clock();
                Native.DispatchMessageW(ref msg);
            }
            throw new InvalidOperationException("Queue drain iteration cap");
        }
        public Receipt Run()
        {
            receipt.Tid = Native.GetCurrentThreadId();
            try
            {
                Require(IntPtr.Size == 8, "Win64 fixture only");
                Require(Native.QueryPerformanceFrequency(out long frequency) && frequency == Stopwatch.Frequency, "QPC frequency mismatch"); receipt.Frequency = frequency;
                Clock();
                receipt.Stage = "initialize-com";
                int hr = Native.CoInitializeEx(IntPtr.Zero, 2);
                Require(hr == 0 || hr == 1, "COM initialization failed"); initialized = true;
                Clock();
                Require(Native.CoGetApartmentType(out int apartment, out int qualifier) == 0 && (apartment == 0 || apartment == 3), "STA verification failed");
                receipt.Apartment = apartment; receipt.ApartmentQualifier = qualifier;
                Clock();
                var wc = new WindowClass { Size = (uint)Marshal.SizeOf<WindowClass>(), Procedure = Marshal.GetFunctionPointerForDelegate(procedure), ClassName = className, Instance = Native.GetModuleHandleW(null) };
                Clock();
                receipt.Stage = "register-window-class";
                atom = Native.RegisterClassExW(ref wc); Require(atom != 0, "RegisterClass failed");
                Clock();
                receipt.Stage = "create-owned-window";
                window = Native.CreateWindowExW(0, className, "", 0, 0, 0, 1, 1, IntPtr.Zero, IntPtr.Zero, wc.Instance, IntPtr.Zero); Require(window != IntPtr.Zero, "CreateWindow failed");
                receipt.Hwnd = window.ToInt64();
                Clock();
                signal = Native.CreateEventW(IntPtr.Zero, true, false, null); Require(signal != IntPtr.Zero, "CreateEvent failed");
                Clock();
                receipt.Stage = "install-thread-hook";
                hook = Native.SetWindowsHookExW(3, hookProcedure, IntPtr.Zero, receipt.Tid); Require(hook != IntPtr.Zero, "Thread hook failed");
                receipt.Stage = "start-producer"; StartProducer();
                receipt.Ready = Clock();
                receipt.Stage = "arm";
                receipt.CallBefore = Clock();
                receipt.ArmDeadline = Math.Min(deadline, receipt.CallBefore + receipt.Frequency);
                IntPtr[] handles = { signal };
                phase = receipt.Branch == "ordinary" ? 1 : 2;
                Require(Native.SetEvent(producerStart), "Producer start failed");
                if (receipt.Branch == "ordinary") OrdinaryPump();
                else
                {
                    int remaining = RemainingMilliseconds(receipt.ArmDeadline); Require(remaining > 0, "No wait budget");
                    receipt.HResult = Native.CoWaitForMultipleHandles(receipt.Branch == "pinned" ? 8u : 24u, (uint)remaining, 1, handles, out uint index);
                    if (receipt.HResult == 0) receipt.WaitIndex = index;
                }
                phase = 3; // Disallow rendezvous-created input before any drain or cleanup pump.
                receipt.CallAfter = Clock(); receipt.DeliveredBeforeDrain = delivered;
                receipt.Stage = "drain";
                phase = 3; Drain(); receipt.DrainEnd = Clock();
            }
            catch (Exception e) { receipt.Error = e.GetType().Name; }
            finally
            {
                phase = 4;
                if (producerStarted)
                {
                    try
                    {
                        int remaining = RemainingMilliseconds(deadline);
                        uint result = Native.WaitForSingleObject(producerDone, (uint)remaining);
                        receipt.ProducerResourceQuiescent = result == 0 && Stopwatch.GetTimestamp() < deadline;
                        if (receipt.ProducerResourceQuiescent) receipt.Producer = producerReceipt; // acquire barrier before reading producer fields
                    }
                    catch { receipt.ProducerResourceQuiescent = false; }
                }
                if (!CanDisposeProducer(producerStarted, receipt.ProducerResourceQuiescent))
                {
                    receipt.Error = receipt.Error ?? "ProducerResourceQuiescenceUnconfirmed";
                    receipt.Stage = "producer-resource-quiescence-failed-whole-child-exit";
                    receipt.CleanupSucceeded = false;
                    EmitFailureThenTerminate(() =>
                    {
                        string failure = JsonSerializer.Serialize(receipt);
                        if (Encoding.UTF8.GetByteCount(failure) <= OutputLimit) Console.WriteLine(failure);
                    }, () => Environment.Exit(1)); // Whole-child containment even if output throws; watchdog covers a blocked write.
                }
                bool clean = true;
                bool Cleanup(Func<bool> action)
                {
                    try { bool result = action(); clean &= result; return result; }
                    catch { clean = false; return false; }
                }
                if (hook != IntPtr.Zero) { receipt.HookRemoved = Cleanup(() => Native.UnhookWindowsHookEx(hook)); hook = IntPtr.Zero; }
                if (window != IntPtr.Zero) { receipt.WindowDestroyed = Cleanup(() => Native.DestroyWindow(window)); window = IntPtr.Zero; }
                if (atom != 0) receipt.ClassUnregistered = Cleanup(() => Native.UnregisterClassW(className, Native.GetModuleHandleW(null)));
                if (producerStart != IntPtr.Zero) receipt.ProducerStartEventClosed = Cleanup(() => Native.CloseHandle(producerStart));
                if (producerDone != IntPtr.Zero) receipt.ProducerDoneEventClosed = Cleanup(() => Native.CloseHandle(producerDone));
                if (signal != IntPtr.Zero) receipt.EventClosed = Cleanup(() => Native.CloseHandle(signal));
                if (initialized) receipt.ComBalanced = Cleanup(() => { Native.CoUninitialize(); return true; });
                GC.KeepAlive(procedure); GC.KeepAlive(hookProcedure); GC.KeepAlive(producer);
                receipt.CleanupSucceeded = clean;
            }
            receipt.Overflow = overflow; receipt.Reentrancy = reentered; receipt.CallbackError = callbackError;
            receipt.Rows = new Row[count];
            for (int i = 0; i < count; i++) receipt.Rows[i] = new Row { Sequence = i + 1, Qpc = rows[i].Qpc, Phase = rows[i].Phase, Source = rows[i].Source == 1 ? "getmessage" : "wndproc", RemovalFlags = rows[i].Flags };
            bool valid = receipt.Error == null && receipt.CleanupSucceeded && !overflow && !reentered && !callbackError &&
                receipt.Ready <= receipt.CallBefore && receipt.CallBefore <= receipt.CallAfter && receipt.CallAfter <= receipt.DrainEnd && receipt.DrainEnd < deadline;
            receipt.Outcome = Classify(receipt.Branch, receipt.HResult, removedInCall, deliveredInCall, removed, delivered, valid);
            if (!ValidReceipt(receipt)) receipt.Outcome = "fixture-failed";
            return receipt;
        }
    }
    [UnmanagedFunctionPointer(CallingConvention.Winapi)] delegate IntPtr WindowProcedure(IntPtr hwnd, uint msg, UIntPtr wp, IntPtr lp);
    [UnmanagedFunctionPointer(CallingConvention.Winapi)] delegate IntPtr HookProcedure(int code, UIntPtr flags, IntPtr message);
    [StructLayout(LayoutKind.Sequential)] struct Msg { public IntPtr Hwnd; public uint Message; public UIntPtr WParam; public IntPtr LParam; public uint Time; public int X, Y; public uint Private; }
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)] struct WindowClass
    {
        public uint Size, Style; public IntPtr Procedure; public int ClassExtra, WindowExtra;
        public IntPtr Instance, Icon, Cursor, Background; public string? MenuName; public string? ClassName; public IntPtr SmallIcon;
    }
    static class Native
    {
        [DllImport("kernel32.dll")] internal static extern uint GetCurrentThreadId();
        [DllImport("kernel32.dll")] [return: MarshalAs(UnmanagedType.Bool)] internal static extern bool QueryPerformanceCounter(out long value);
        [DllImport("kernel32.dll")] [return: MarshalAs(UnmanagedType.Bool)] internal static extern bool QueryPerformanceFrequency(out long value);
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode)] internal static extern IntPtr GetModuleHandleW(string? name);
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode)] internal static extern IntPtr CreateEventW(IntPtr attrs, [MarshalAs(UnmanagedType.Bool)] bool manual, [MarshalAs(UnmanagedType.Bool)] bool initial, string? name);
        [DllImport("kernel32.dll")] [return: MarshalAs(UnmanagedType.Bool)] internal static extern bool SetEvent(IntPtr handle);
        [DllImport("kernel32.dll")] internal static extern uint WaitForSingleObject(IntPtr handle, uint milliseconds);
        [DllImport("kernel32.dll")] [return: MarshalAs(UnmanagedType.Bool)] internal static extern bool CloseHandle(IntPtr handle);
        [DllImport("user32.dll", CharSet = CharSet.Unicode)] internal static extern ushort RegisterClassExW(ref WindowClass value);
        [DllImport("user32.dll", CharSet = CharSet.Unicode)] internal static extern IntPtr CreateWindowExW(uint ex, string cls, string title, uint style, int x, int y, int width, int height, IntPtr parent, IntPtr menu, IntPtr instance, IntPtr param);
        [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] internal static extern bool DestroyWindow(IntPtr window);
        [DllImport("user32.dll", CharSet = CharSet.Unicode)] [return: MarshalAs(UnmanagedType.Bool)] internal static extern bool UnregisterClassW(string name, IntPtr instance);
        [DllImport("user32.dll", SetLastError = true)] internal static extern IntPtr SendMessageTimeoutW(IntPtr window, uint message, UIntPtr wp, IntPtr lp, uint flags, uint timeout, out UIntPtr result);
        [DllImport("user32.dll")] internal static extern uint MsgWaitForMultipleObjectsEx(uint count, IntPtr handles, uint milliseconds, uint mask, uint flags);
        [DllImport("user32.dll")] internal static extern IntPtr DefWindowProcW(IntPtr window, uint msg, UIntPtr wp, IntPtr lp);
        [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] internal static extern bool PostMessageW(IntPtr window, uint msg, UIntPtr wp, IntPtr lp);
        [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] internal static extern bool PeekMessageW(out Msg message, IntPtr window, uint min, uint max, uint flags);
        [DllImport("user32.dll")] internal static extern IntPtr DispatchMessageW(ref Msg message);
        [DllImport("user32.dll")] internal static extern IntPtr SetWindowsHookExW(int id, HookProcedure callback, IntPtr module, uint tid);
        [DllImport("user32.dll")] internal static extern IntPtr CallNextHookEx(IntPtr hook, int code, UIntPtr flags, IntPtr message);
        [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] internal static extern bool UnhookWindowsHookEx(IntPtr hook);
        [DllImport("ole32.dll")] internal static extern int CoInitializeEx(IntPtr reserved, uint flags);
        [DllImport("ole32.dll")] internal static extern int CoGetApartmentType(out int type, out int qualifier);
        [DllImport("ole32.dll")] internal static extern void CoUninitialize();
        [DllImport("ole32.dll")] internal static extern int CoWaitForMultipleHandles(uint flags, uint milliseconds, uint count, [In] IntPtr[] handles, out uint index);
    }
}
