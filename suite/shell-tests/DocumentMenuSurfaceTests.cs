using System;
using System.Collections.Generic;
using System.Text.Json;
using System.Threading.Tasks;
using OpenGeul.Office.Core;

public static class DocumentMenuSurfaceTests
{
    public static async Task<int> RunAsync()
    {
        var count = 0;
        foreach (var (name, run) in Cases())
        {
            try { await run(); }
            catch (Exception error) { throw new InvalidOperationException(name, error); }
            count++;
        }
        return count;
    }

    internal static IEnumerable<(string Name, Func<Task> Run)> Cases()
    {
        void Check(bool value, string message) { if (!value) throw new Exception(message); }
        (string, Func<Task>) Test(string name, Action body) => (name, () => { body(); return Task.CompletedTask; });
        yield return Test("All Office modules require their original native menu binding", () =>
        {
            foreach (var module in new[] { "writer", "calc", "impress", "draw", "math", "base" })
            {
                var surface = new DocumentMenuSurface(module, 100, 200);
                Check(surface.IsReady(Status(module)), "A bound native Office menu was rejected");
                surface.RequireReady(Status(module));
            }
        });
        yield return Test("Unknown malformed or foreign native readiness rejects the document session", () =>
        {
            var invalid = new[] {
                "null", "[]", "true", "{}",
                """{"nativeMenuReady":true}""",
                """{"module":"writer","parentHwnd":100,"childHwnd":200}""",
                """{"module":"writer","parentHwnd":100,"childHwnd":200,"nativeMenuReady":false}""",
                """{"module":"writer","parentHwnd":100,"childHwnd":200,"nativeMenuReady":"true"}""",
                """{"module":"writer","parentHwnd":100,"childHwnd":200,"nativeMenuReady":1}""",
                """{"module":"Writer","parentHwnd":100,"childHwnd":200,"nativeMenuReady":true}""",
                """{"module":"calc","parentHwnd":100,"childHwnd":200,"nativeMenuReady":true}""",
                """{"module":"writer","parentHwnd":101,"childHwnd":200,"nativeMenuReady":true}""",
                """{"module":"writer","parentHwnd":100,"childHwnd":201,"nativeMenuReady":true}""",
                """{"module":"writer","parentHwnd":"100","childHwnd":200,"nativeMenuReady":true}""",
                """{"module":"writer","parentHwnd":100.0,"childHwnd":200,"nativeMenuReady":true}""",
                """{"module":"writer","parentHwnd":100,"childHwnd":9223372036854775808,"nativeMenuReady":true}"""
            };
            foreach (var raw in invalid)
            {
                var surface = new DocumentMenuSurface("writer", 100, 200);
                var status = Parse(raw);
                Check(!surface.IsReady(status), "Unknown readiness authorized a usable document session");
                var rejected = false;
                try { surface.RequireReady(status); }
                catch (SuiteException) { rejected = true; }
                Check(rejected, "Missing native menus did not fail document admission");
            }
        });
        yield return Test("Duplicate readiness or attachment fields cannot authorize the native menu", () =>
        {
            foreach (var duplicate in new[] {
                "\"nativeMenuReady\":false,", "\"module\":\"calc\",",
                "\"parentHwnd\":101,", "\"childHwnd\":201," })
            {
                var surface = new DocumentMenuSurface("writer", 100, 200);
                var raw = "{" + duplicate + "\"module\":\"writer\",\"parentHwnd\":100,\"childHwnd\":200,\"nativeMenuReady\":true}";
                Check(!surface.IsReady(Parse(raw)), "A duplicate critical field replaced the original binding");
            }
        });
        yield return Test("Repeated menu observation preserves ordinary document status", () =>
        {
            var surface = new DocumentMenuSurface("writer", 100, 200);
            var status = Parse("""{"module":"writer","parentHwnd":100,"childHwnd":200,"nativeMenuReady":true,"modified":true,"title":"synthetic","readiness":{"message":"ready"}}""");
            var before = status.GetRawText();
            surface.RequireReady(status); surface.RequireReady(status);
            Check(surface.IsReady(status) && status.GetRawText() == before, "Menu validation changed the document status");
        });
        yield return Test("Released status payloads cannot establish native readiness", () =>
        {
            var surface = new DocumentMenuSurface("writer", 100, 200);
            var document = JsonDocument.Parse("{}"); var stale = document.RootElement; document.Dispose();
            Check(!surface.IsReady(stale), "Disposed status authorized a document session");
        });
        yield return Test("In-flight status still validates menu ownership while UI updates are deferred", () =>
        {
            var surface = new DocumentMenuSurface("writer", 100, 200);
            var updates = 0; var rejected = false;
            surface.ObserveStatus(Status(), false, _ => updates++);
            try { surface.ObserveStatus(Status("calc"), false, _ => updates++); }
            catch (SuiteException) { rejected = true; }
            Check(rejected && updates == 0, "A transaction silently discarded invalid native menu readiness");
            surface.ObserveStatus(Status(), true, _ => updates++);
            Check(updates == 1, "Valid idle status did not update the document exactly once");
        });
        yield return Test("Menu binding refuses absent or aliased document attachment identities", () =>
        {
            foreach (var (module, parent, child) in new[] {
                ("", 100L, 200L), ("hwp", 100L, 200L), ("writer", 0L, 200L),
                ("writer", 100L, 0L), ("writer", -100L, 200L), ("writer", 100L, 100L) })
            {
                var rejected = false;
                try { _ = new DocumentMenuSurface(module, parent, child); }
                catch (ArgumentException) { rejected = true; }
                Check(rejected, "A missing or aliased attachment created a native menu binding");
            }
        });
        yield return ("Home navigation waits for exactly one confirmed document close", async () =>
        {
            var completion = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
            var closes = 0; var homes = 0;
            var pending = DocumentMenuSurface.CloseAndShowHomeAsync(() => { closes++; return completion.Task; }, () => homes++);
            Check(closes == 1 && homes == 0 && !pending.IsCompleted, "Home was shown before original close completed");
            completion.SetResult(true);
            Check(await pending && closes == 1 && homes == 1, "A confirmed close did not navigate home exactly once");
        });
        yield return ("Home preserves the current document after cancellation failed save or close veto", async () =>
        {
            foreach (var (choice, saveResult, session) in new[] {
                (CloseChoice.Cancel, true, new MenuCloseSession { Modified = true }),
                (CloseChoice.Save, false, new MenuCloseSession { Modified = true }),
                (CloseChoice.Discard, true, new MenuCloseSession { CancelClose = true }),
                (CloseChoice.Discard, true, new MenuCloseSession { FailClose = true }) })
            {
                var homes = 0;
                var moved = await DocumentMenuSurface.CloseAndShowHomeAsync(async () =>
                    (await DocumentClose.TryAsync(session, () => Task.FromResult(choice), () => Task.FromResult(saveResult))).Closed,
                    () => homes++);
                Check(!moved && homes == 0, "Home navigation bypassed original cancellation or close failure");
            }
        });
        yield return ("Home navigation preserves the original close exception", async () =>
        {
            var primary = new SuiteException("synthetic close failure"); var homes = 0; var same = false;
            try { await DocumentMenuSurface.CloseAndShowHomeAsync(() => Task.FromException<bool>(primary), () => homes++); }
            catch (SuiteException error) { same = ReferenceEquals(error, primary); }
            Check(same && homes == 0, "Home navigation replaced the original failure or moved after failure");
        });
    }

    private static JsonElement Parse(string raw)
    {
        using var document = JsonDocument.Parse(raw);
        return document.RootElement.Clone();
    }

    private static JsonElement Status(string module = "writer", bool ready = true) =>
        JsonSerializer.SerializeToElement(new { module, parentHwnd = 100L, childHwnd = 200L, nativeMenuReady = ready });

    private sealed class MenuCloseSession : IDocumentSession
    {
        internal bool Modified { get; init; }
        internal bool CancelClose { get; init; }
        internal bool FailClose { get; init; }
        public Task<DocumentStatus> StatusAsync() => Task.FromResult(new DocumentStatus(Modified, "synthetic"));
        public Task<DocumentStatus> PrepareCloseAsync() => StatusAsync();
        public Task<CloseResult> CloseAsync(bool discard) => FailClose
            ? Task.FromException<CloseResult>(new SuiteException("synthetic close failure"))
            : Task.FromResult(new CloseResult(!CancelClose));
    }
}
