using System.ComponentModel;
using OpenGeul.Office.Core;

internal static class StartupDiagnosticTests
{
    private static void Check(bool value, string message) { if (!value) throw new Exception(message); }

    private static async Task<SuiteException> Failure(Func<Task> action)
    {
        try { await action(); }
        catch (SuiteException error) { return error; }
        throw new Exception("Expected the owned worker to fail");
    }

    private static (int Phase, int Reason, uint NativeCode) Diagnostic(SuiteException error)
    {
        var value = typeof(SuiteException).GetProperty("StartupDiagnostic")?.GetValue(error)
            ?? throw new Exception("Worker error lost its typed startup diagnostic");
        var type = value.GetType();
        return (Convert.ToInt32(type.GetProperty("Phase")!.GetValue(value)),
            Convert.ToInt32(type.GetProperty("Reason")!.GetValue(value)),
            Convert.ToUInt32(type.GetProperty("NativeCode")!.GetValue(value)));
    }

    // The delegate launches a real controlled child. Normal suite runs use the
    // C# fake worker; the SDK-free local check can use an equivalent JSONL child.
    internal static IEnumerable<(string Name, Func<Task> Run)> Cases(Func<string, WorkerClient> startWorker)
    {
        yield return ("Startup numeric packing has fixed version phase reason and native fields", () =>
        {
            var type = typeof(SuiteException).Assembly.GetType("OpenGeul.Office.Core.StartupDiagnostic")
                ?? throw new Exception("Startup numeric contract is missing");
            var method = type.GetMethod("FromWorkerCode")!;
            var known = method.Invoke(null, ["ui_style_isolation_failed"])!;
            var unknown = method.Invoke(null, ["PRIVATE-UNKNOWN-CODE"])!;
            Check((ulong)type.GetProperty("Packed")!.GetValue(known)! == (1UL << 56 | 2UL << 48 | 16UL << 32),
                "Startup diagnostic wire layout changed");
            Check((ulong)type.GetProperty("Packed")!.GetValue(unknown)! == (1UL << 56 | 2UL << 48),
                "Unknown code was exported");
            var codes = new[] { "invalid_request", "invalid_json", "request_too_large", "unknown_command",
                "invalid_state", "invalid_path", "unsupported_module", "unsupported_format", "invalid_manifest",
                "close_cancelled", "engine_error", "engine_exited", "connect_timeout", "runtime_missing",
                "ui_bootstrap_failed", "ui_style_isolation_failed", "new_database_failed", "uno_unavailable",
                "attach_failed", "accessibility_failed", "open_failed", "close_failed", "save_failed",
                "cleanup_pending", "unsupported_platform", "invalid_window", "embedding_failed" };
            for (var index = 0; index < codes.Length; index++)
            {
                var diagnostic = method.Invoke(null, [codes[index]])!;
                Check((ulong)type.GetProperty("Packed")!.GetValue(diagnostic)! == (1UL << 56 | 2UL << 48 | (ulong)(index + 1) << 32),
                    "Known worker code changed its numeric contract");
            }
            return Task.CompletedTask;
        });
        yield return ("Startup numeric publication requires the exact existing opt-in value", () =>
        {
            var type = typeof(SuiteException).Assembly.GetType("OpenGeul.Office.Core.StartupDiagnostic")
                ?? throw new Exception("Startup numeric contract is missing");
            var previous = Environment.GetEnvironmentVariable("OPENGEUL_SUITE_NUMERIC_NOTICE");
            try
            {
                foreach (var value in new string?[] { null, "", "0", "true", "01", " 1", "1 ", "1" })
                {
                    Environment.SetEnvironmentVariable("OPENGEUL_SUITE_NUMERIC_NOTICE", value);
                    Check((bool)type.GetProperty("Enabled")!.GetValue(null)! == (value == "1"), "Numeric property opt-in widened");
                }
            }
            finally { Environment.SetEnvironmentVariable("OPENGEUL_SUITE_NUMERIC_NOTICE", previous); }
            return Task.CompletedTask;
        });
        yield return ("Typed unknown worker cause keeps its original phase through exception wrappers", () =>
        {
            var assembly = typeof(SuiteException).Assembly;
            var type = assembly.GetType("OpenGeul.Office.Core.StartupDiagnostic")
                ?? throw new Exception("Startup numeric contract is missing");
            var phase = Enum.ToObject(assembly.GetType("OpenGeul.Office.Core.StartupPhase")!, 3);
            var diagnostic = type.GetMethod("FromWorkerCode")!.Invoke(null, ["PRIVATE-UNKNOWN-CODE"])!;
            var typed = (SuiteException)Activator.CreateInstance(typeof(SuiteException), ["original", null, diagnostic])!;
            var wrapper = new InvalidOperationException("wrapper", new SuiteException("connection", typed));
            var result = type.GetMethod("FromException")!.Invoke(null, [wrapper, phase])!;
            Check((ulong)type.GetProperty("Packed")!.GetValue(result)! == (1UL << 56 | 2UL << 48), "Unknown typed worker cause was reclassified by a wrapper");
            return Task.CompletedTask;
        });
        yield return ("Only allowlisted native error codes are exported and exception text is ignored", () =>
        {
            var assembly = typeof(SuiteException).Assembly;
            var type = assembly.GetType("OpenGeul.Office.Core.StartupDiagnostic")
                ?? throw new Exception("Startup numeric contract is missing");
            var phase = Enum.ToObject(assembly.GetType("OpenGeul.Office.Core.StartupPhase")!, 1);
            foreach (var code in new[] { 2, 3, 5, 8, 14, 32, 87, 126, 127, 193, 216, 740, 12345, -1 })
            {
                var diagnostic = type.GetMethod("FromException")!.Invoke(null, [new Win32Exception(code, "PRIVATE-MESSAGE"), phase])!;
                var packed = (ulong)type.GetProperty("Packed")!.GetValue(diagnostic)!;
                var expectedCode = code is 12345 or -1 ? 0U : (uint)code;
                Check(packed == (1UL << 56 | 1UL << 48 | 38UL << 32 | expectedCode), "Native error escaped the finite contract");
            }
            var unknown = type.GetMethod("FromException")!.Invoke(null, [new Exception("runtime_missing ui_style_isolation_failed"), phase])!;
            Check((ulong)type.GetProperty("Packed")!.GetValue(unknown)! == (1UL << 56 | 1UL << 48), "Exception message was parsed");
            return Task.CompletedTask;
        });
        yield return ("Null-id startup error preserves the worker classification and localized message", async () =>
        {
            await using var client = startWorker("startup-error");
            var error = await Failure(() => client.SendAsync("attach", new { }));
            Check(error.ToString().Contains("제품 설정을 읽을 수 없습니다."), "Null startup id replaced the worker's localized error");
            Check(Diagnostic(error) == (2, 9, 0U), "invalid_manifest did not keep its fixed worker reason");
        });
        yield return ("Startup error survives EOF and subsequent disconnected wrappers", async () =>
        {
            await using var client = startWorker("startup-error-exit");
            var first = await Failure(() => client.SendAsync("attach", new { }));
            var second = await Failure(() => client.SendAsync("echo", new { }));
            Check(Diagnostic(first) == (2, 9, 0U) && Diagnostic(second) == (2, 9, 0U),
                "EOF or a disconnected wrapper overwrote the first startup cause");
        });
        yield return ("A null-id fatal reply fails every pending request without changing request ids", async () =>
        {
            await using var client = startWorker("pending-startup-error");
            var first = client.SendAsync("attach", new { });
            var second = client.SendAsync("echo", new { });
            Check(Diagnostic(await Failure(() => first)) == (2, 16, 0U), "First pending request lost the startup code");
            Check(Diagnostic(await Failure(() => second)) == (2, 16, 0U), "Second pending request lost the startup code");
            using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(3));
            while (!client.Diagnostics.Contains("request-ids:1,2")) await Task.Delay(10, deadline.Token);
        });
        yield return ("Known correlated worker error keeps its code while a later request succeeds", async () =>
        {
            await using var client = startWorker("normal");
            var error = await Failure(() => client.SendAsync("error", new { }));
            Check(Diagnostic(error) == (2, 23, 0U), "save_failed was discarded");
            Check((await client.SendAsync("echo", new { value = 7 })).GetProperty("value").GetInt32() == 7,
                "An ordinary correlated error incorrectly terminated the worker");
        });
        yield return ("Unknown worker code stays unknown even when message names a known failure", async () =>
        {
            await using var client = startWorker("normal");
            var error = await Failure(() => client.SendAsync("unknown-error", new { }));
            Check(Diagnostic(error) == (2, 0, 0U), "Error text or an unknown worker code escaped the numeric allowlist");
        });
        yield return ("A valid unmatched late error reply never poisons the active request", async () =>
        {
            await using var client = startWorker("normal");
            Check((await client.SendAsync("late-error", new { value = 8 })).GetProperty("value").GetInt32() == 8,
                "A late correlated reply was treated as a startup failure");
        });
        yield return ("Malformed reply ids stay protocol errors rather than typed worker failures", async () =>
        {
            foreach (var command in new[] { "invalid-id", "null-success", "invalid-ok", "missing-result", "invalid-message" })
            {
                await using var client = startWorker("normal");
                var error = await Failure(() => client.SendAsync(command, new { }));
                Check(Diagnostic(error) == (2, 35, 0U), "A malformed reply was accepted as a valid startup error");
            }
        });
        yield return ("Invalid request timeout keeps localized failure handling and removes the pending request", async () =>
        {
            await using var client = startWorker("normal");
            await Failure(() => client.SendAsync("echo", new { }, requestTimeout: TimeSpan.FromMilliseconds(-2)));
            var pending = typeof(WorkerClient).GetField("pending", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!.GetValue(client)!;
            Check((int)pending.GetType().GetProperty("Count")!.GetValue(pending)! == 0, "Invalid deadline leaked a pending request");
            Check((await client.SendAsync("echo", new { value = 9 })).GetProperty("value").GetInt32() == 9,
                "Invalid deadline terminated the worker");
        });
        yield return ("Request timeout retains its finite classification and later replies still correlate", async () =>
        {
            await using var client = startWorker("normal");
            await client.SendAsync("echo", new { });
            var error = await Failure(() => client.SendAsync("timeout", new { }, requestTimeout: TimeSpan.FromMilliseconds(50)));
            Check(Diagnostic(error) == (2, 33, 0U), "Request timeout lost its finite classification");
            Check((await client.SendAsync("echo", new { value = 10 })).GetProperty("value").GetInt32() == 10,
                "Request timeout damaged later reply correlation");
        });
        yield return ("Worker EOF retains its finite disconnected classification", async () =>
        {
            await using var client = startWorker("normal");
            Check(Diagnostic(await Failure(() => client.SendAsync("exit", new { }))) == (2, 34, 0U),
                "Worker EOF lost its disconnected classification");
        });
    }
}
