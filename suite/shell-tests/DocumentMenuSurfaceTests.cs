using System;
using System.Collections.Generic;
using System.Reflection;
using System.Runtime.ExceptionServices;
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
        yield return Test("Native status notice distinguishes started requests from admitted replies", () =>
        {
            var surface = new DocumentMenuSurface("writer", 100, 200);
            var published = new List<ulong>();
            void Publish() => PublishNotice(surface, value => { published.Add(value); return true; },
                () => throw new Exception("Successful publication tried to remove its notice"));
            Check(ReadNotice(surface) == 0x0100000000000000UL, "A new session invented an earlier status read");
            Publish();
            surface.RequireReady(Status());
            surface.ObserveStatus(Status(), false, _ => { });
            Check(ReadNotice(surface) == 0x0100000000000000UL, "Attach or ordinary status application advanced the RPC sequence");
            var first = StartRead(surface);
            Check(first == 1 && ReadNotice(surface) == 0x0100000010000000UL, "A started request was already counted as complete");
            Publish();
            CompleteRead(surface, Status(), first);
            Check(ReadNotice(surface) == 0x0100000010000001UL, "An admitted response did not complete its own request");
            Publish();
            var second = StartRead(surface);
            Check(second == 2 && ReadNotice(surface) == 0x0100000020000001UL, "A later request reused an earlier completed sequence");
            CompleteRead(surface, Status(), second);
            Check(ReadNotice(surface) == 0x0100000020000002UL, "A later admitted response did not remain monotonic");
            Publish();
            Check(published.Count == 4 && published[0] == 0x0100000000000000UL
                && published[1] == 0x0100000010000000UL && published[2] == 0x0100000010000001UL
                && published[3] == 0x0100000020000002UL,
                "Successful publication stopped early or advertised a different request state");
        });
        yield return Test("Overlapping stale and invalid native status reads cannot be blessed later", () =>
        {
            foreach (var failure in new[] { "overlap", "stale", "unstarted", "foreign-status" })
            {
                var surface = new DocumentMenuSurface("writer", 100, 200);
                var token = StartRead(surface);
                var rejected = false;
                try
                {
                    if (failure == "overlap") StartRead(surface);
                    else if (failure == "stale")
                    {
                        CompleteRead(surface, Status(), token);
                        token = StartRead(surface);
                        CompleteRead(surface, Status(), token - 1);
                    }
                    else if (failure == "unstarted") CompleteRead(surface, Status(), token + 1);
                    else CompleteRead(surface, Status("calc"), token);
                }
                catch (SuiteException) { rejected = true; }
                var afterFailure = ReadNotice(surface);
                Check(rejected, "An overlapping, foreign or stale reply authorized status proof");
                rejected = false;
                try { CompleteRead(surface, Status(), token); }
                catch (SuiteException) { rejected = true; }
                Check(rejected && ReadNotice(surface) == afterFailure, "A later valid reply blessed a failed sequence");
                rejected = false;
                try { StartRead(surface); }
                catch (SuiteException) { rejected = true; }
                Check(rejected && ReadNotice(surface) == afterFailure, "A failed sequence restarted inside the same document session");
            }
        });
        yield return Test("Admitted native status is published before optional document UI updates", () =>
        {
            var surface = new DocumentMenuSurface("writer", 100, 200);
            var events = new List<string>();
            var token = StartRead(surface);
            ObserveRead(surface, Status(), token, false, _ => events.Add("apply"), () => events.Add("publish"));
            Check(events.Count == 1 && events[0] == "publish" && ReadNotice(surface) == 0x0100000010000001UL,
                "Busy UI suppressed an admitted status completion");
            events.Clear();
            token = StartRead(surface);
            ObserveRead(surface, Status(), token, true, _ => events.Add("apply"), () => events.Add("publish"));
            Check(events.Count == 2 && events[0] == "publish" && events[1] == "apply",
                "UI application preceded its validated status completion");
            events.Clear();
            token = StartRead(surface);
            var rejected = false;
            try { ObserveRead(surface, Status("calc"), token, true, _ => events.Add("apply"), () => events.Add("publish")); }
            catch (SuiteException) { rejected = true; }
            Check(rejected && events.Count == 0 && ReadNotice(surface) == 0x0100000030000002UL,
                "A foreign response published freshness or applied UI state");
        });
        yield return Test("Status notice publication failure stays disabled without changing the document", () =>
        {
            foreach (var failure in new[] { "false", "write-throws", "clear-throws" })
            {
                var surface = new DocumentMenuSurface("writer", 100, 200);
                var writes = 0; var clears = 0; var updates = 0;
                Func<ulong, bool> write = _ =>
                {
                    writes++;
                    if (failure == "write-throws") throw new InvalidOperationException("Synthetic publication failure");
                    return false;
                };
                Action clear = () =>
                {
                    clears++;
                    if (failure == "clear-throws") throw new InvalidOperationException("Synthetic removal failure");
                };
                var token = StartRead(surface);
                PublishNotice(surface, write, clear);
                ObserveRead(surface, Status(), token, true, _ => updates++, () => PublishNotice(surface, write, clear));
                PublishNotice(surface, _ => { writes++; return true; }, clear);
                Check(writes == 1 && clears == 1 && updates == 1,
                    "Failed begin publication resumed later or changed ordinary document UI application");
                Check(ReadNotice(surface) == 0x0100000010000001UL && surface.IsReady(Status()),
                    "Optional diagnostics changed the actual menu state");
            }
        });
        yield return Test("Native status sequence rejects transport overflow instead of wrapping", () =>
        {
            var surface = new DocumentMenuSurface("writer", 100, 200);
            foreach (var name in new[] { "startedStatusReads", "completedStatusReads" })
            {
                var field = typeof(DocumentMenuSurface).GetField(name, BindingFlags.Instance | BindingFlags.NonPublic);
                Check(field is not null, "The status boundary fixture could not initialize the real transport limit");
                field!.SetValue(surface, 0x0fffffffU);
            }
            Check(ReadNotice(surface) == 0x01ffffffffffffffUL, "The largest valid transport sequence was not represented exactly");
            var rejected = false;
            try { StartRead(surface); }
            catch (SuiteException) { rejected = true; }
            Check(rejected && ReadNotice(surface) == 0x01ffffffffffffffUL,
                "Transport overflow wrapped into a reusable freshness sequence");
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

    private static object? Invoke(DocumentMenuSurface surface, string name, Type[] signature, params object[] args)
    {
        var method = typeof(DocumentMenuSurface).GetMethod(name, signature)
            ?? throw new Exception("Native status proof API is missing: " + name);
        try { return method.Invoke(surface, args); }
        catch (TargetInvocationException error) when (error.InnerException is not null)
        {
            ExceptionDispatchInfo.Capture(error.InnerException).Throw();
            throw;
        }
    }
    private static ulong ReadNotice(DocumentMenuSurface surface) => (ulong)(
        typeof(DocumentMenuSurface).GetProperty("StatusReadNotice")?.GetValue(surface)
        ?? throw new Exception("Native status proof notice is missing"));
    private static uint StartRead(DocumentMenuSurface surface) => (uint)Invoke(surface, "StartStatusRead", Type.EmptyTypes)!;
    private static void CompleteRead(DocumentMenuSurface surface, JsonElement status, uint token) =>
        Invoke(surface, "CompleteStatusRead", new[] { typeof(JsonElement), typeof(uint) }, status, token);
    private static void ObserveRead(DocumentMenuSurface surface, JsonElement status, uint token, bool update,
        Action<JsonElement> apply, Action publish) => Invoke(surface, "ObserveStatus",
            new[] { typeof(JsonElement), typeof(uint), typeof(bool), typeof(Action<JsonElement>), typeof(Action) },
            status, token, update, apply, publish);
    private static void PublishNotice(DocumentMenuSurface surface, Func<ulong, bool> write, Action clear) =>
        Invoke(surface, "PublishStatusNotice", new[] { typeof(Func<ulong, bool>), typeof(Action) }, write, clear);

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
