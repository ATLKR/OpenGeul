using System.Diagnostics;
using System.Text.Json;
using OpenGeul.Office.Core;

if (args.Contains("--fake-worker"))
{
    while (Console.ReadLine() is { } line)
    {
        using var request = JsonDocument.Parse(line);
        var root = request.RootElement;
        var id = root.GetProperty("id").GetInt64();
        var command = root.GetProperty("command").GetString();
        if (command == "timeout") continue;
        if (command == "exit") return 0;
        if (command == "event")
            Console.WriteLine(JsonSerializer.Serialize(new { @event = "command", command = "saveAs", module = "writer" }));
        if (command == "error")
            Console.WriteLine(JsonSerializer.Serialize(new { id, ok = false, error = new { code = "save_failed", message = "저장 실패" } }));
        else
            Console.WriteLine(JsonSerializer.Serialize(new { id, ok = true, result = root.GetProperty("args").Clone() }));
    }
    return 0;
}

var tests = new List<(string Name, Func<Task> Run)>();
void Test(string name, Action action) => tests.Add((name, () => { action(); return Task.CompletedTask; }));
void AsyncTest(string name, Func<Task> action) => tests.Add((name, action));
void Equal<T>(T expected, T actual)
{
    if (!EqualityComparer<T>.Default.Equals(expected, actual))
        throw new Exception($"Expected {expected}; got {actual}");
}
void Throws<T>(Action action) where T : Exception
{
    try { action(); } catch (T) { return; }
    throw new Exception($"Expected {typeof(T).Name}");
}
async Task ThrowsAsync<T>(Func<Task> action) where T : Exception
{
    try { await action(); } catch (T) { return; }
    throw new Exception($"Expected {typeof(T).Name}");
}

var manifestJson = """
{"schemaVersion":1,"productName":"OpenGeul Office","vendor":"ATLKR","runtime":{"directory":"Office","executable":"program/soffice.exe","python":"program/python.exe"},"modules":{
"hwp":{"displayName":"OpenGeul HWP","factory":null,"extensions":["hwp","hwpx"],"filters":{},"executable":"HWP/OpenGeul.exe"},
"writer":{"displayName":"OpenGeul Writer","factory":"private:factory/swriter","extensions":["odt","docx","doc","rtf","txt"],"filters":{"odt":"writer8","docx":"Office Open XML Text","doc":"MS Word 97","rtf":"Rich Text Format","txt":"Text"}},
"calc":{"displayName":"OpenGeul Calc","factory":"private:factory/scalc","extensions":["ods","xlsx"],"filters":{"ods":"calc8","xlsx":"Calc MS Excel 2007 XML"}},
"impress":{"displayName":"OpenGeul Impress","factory":"private:factory/simpress","extensions":["odp","pptx"],"filters":{"odp":"impress8","pptx":"Impress MS PowerPoint 2007 XML"}},
"draw":{"displayName":"OpenGeul Draw","factory":"private:factory/sdraw","extensions":["odg"],"filters":{"odg":"draw8"}},
"math":{"displayName":"OpenGeul Math","factory":"private:factory/smath","extensions":["odf"],"filters":{"odf":"math8"}},
"base":{"displayName":"OpenGeul Base","factory":"private:factory/sdatabase","extensions":["odb"],"filters":{"odb":"StarOffice XML (Base)"}}}}
""";

// Removing extension lookup, allowing a fallback route, or accepting arbitrary save filters
// must break these real manifest/router tests.
Test("routes mixed-case Korean DOCX path to Writer", () =>
    Equal("writer", SuiteManifest.Parse(manifestJson).Route("C:\\문서 폴더\\계약서.DOCX").Id));
Test("routes HWPX to existing HWP engine", () =>
    Equal("hwp", SuiteManifest.Parse(manifestJson).Route("C:\\문서\\표.hwpx").Id));
Test("routes each Office native format explicitly", () =>
{
    var manifest = SuiteManifest.Parse(manifestJson);
    foreach (var (extension, module) in new[] { ("ods", "calc"), ("pptx", "impress"), ("odg", "draw"), ("odf", "math"), ("odb", "base") })
        Equal(module, manifest.Route($"C:\\data\\a.{extension}").Id);
});
Test("unsupported file never falls back to Writer", () =>
    Throws<SuiteException>(() => SuiteManifest.Parse(manifestJson).Route("C:\\data\\unknown.pdf")));
Test("duplicate extensions are rejected", () =>
    Throws<SuiteException>(() => SuiteManifest.Parse(manifestJson.Replace("\"ods\",\"xlsx\"", "\"ods\",\"docx\""))));
Test("manifest missing required module is rejected", () =>
    Throws<SuiteException>(() => SuiteManifest.Parse(manifestJson.Replace("\"base\":", "\"unknown\":"))));
Test("unsupported manifest version is rejected", () =>
    Throws<SuiteException>(() => SuiteManifest.Parse(manifestJson.Replace("schemaVersion\":1", "schemaVersion\":2"))));
Test("save filter comes from module extension allowlist", () =>
    Equal("Office Open XML Text", SuiteManifest.Parse(manifestJson).Modules["writer"].SaveFilter("C:\\문서\\특수 & 글.DOCX")));
Test("save cannot cross module format boundary", () =>
    Throws<SuiteException>(() => SuiteManifest.Parse(manifestJson).Modules["writer"].SaveFilter("C:\\data\\a.xlsx")));
Test("paths preserve shell characters as plain data", () =>
    Equal("C:\\문서 폴더\\a & b $(x).docx", LocalDocumentPath.Validate("C:\\문서 폴더\\a & b $(x).docx")));
Test("remote and relative paths are rejected", () =>
{
    foreach (var path in new[] { "https://example.com/a.docx", "file:///C:/a.docx", "\\\\server\\share\\a.docx", "//server/a.docx", "relative.docx", "C:relative.docx" })
        Throws<SuiteException>(() => LocalDocumentPath.Validate(path));
});
Test("CLI routes file without module", () =>
    Equal("writer", StartupRequest.Parse(["--file", "C:\\문서\\a.docx"], SuiteManifest.Parse(manifestJson)).ModuleId));
Test("CLI opens selected new module", () =>
    Equal("calc", StartupRequest.Parse(["--module", "calc"], SuiteManifest.Parse(manifestJson)).ModuleId));
Test("CLI rejects conflicting module and file", () =>
    Throws<SuiteException>(() => StartupRequest.Parse(["--module", "writer", "--file", "C:\\문서\\a.xlsx"], SuiteManifest.Parse(manifestJson))));
Test("CLI rejects unknown arguments without shell interpretation", () =>
    Throws<SuiteException>(() => StartupRequest.Parse(["--module", "writer", "--unknown"], SuiteManifest.Parse(manifestJson))));

// Removing a cancel branch or closing after a failed save must break these close-flow tests.
AsyncTest("cancel dirty close preserves the document", async () =>
{
    var session = new TestSession { Modified = true };
    var result = await DocumentClose.TryAsync(session, () => Task.FromResult(CloseChoice.Cancel), () => Task.FromResult(true));
    Equal(false, result.Closed); Equal(0, session.CloseCalls);
});
AsyncTest("failed save preserves dirty document and worker", async () =>
{
    var session = new TestSession { Modified = true };
    var result = await DocumentClose.TryAsync(session, () => Task.FromResult(CloseChoice.Save), () => Task.FromResult(false));
    Equal(false, result.Closed); Equal(0, session.CloseCalls);
});
AsyncTest("save then close never discards", async () =>
{
    var session = new TestSession { Modified = true };
    var saves = 0;
    var result = await DocumentClose.TryAsync(session, () => Task.FromResult(CloseChoice.Save), () => { saves++; return Task.FromResult(true); });
    Equal(true, result.Closed); Equal(1, saves); Equal(false, session.Discard);
});
AsyncTest("explicit discard is passed to worker", async () =>
{
    var session = new TestSession { Modified = true };
    var result = await DocumentClose.TryAsync(session, () => Task.FromResult(CloseChoice.Discard), () => Task.FromResult(false));
    Equal(true, result.Closed); Equal(true, session.Discard);
});
AsyncTest("clean close does not prompt or save", async () =>
{
    var session = new TestSession();
    var result = await DocumentClose.TryAsync(session, () => throw new Exception("unexpected prompt"), () => throw new Exception("unexpected save"));
    Equal(true, result.Closed); Equal(false, session.Discard);
});
AsyncTest("status failure preserves window and does not close", async () =>
{
    var session = new TestSession { FailStatus = true };
    var result = await DocumentClose.TryAsync(session, () => Task.FromResult(CloseChoice.Discard), () => Task.FromResult(true));
    Equal(false, result.Closed); Equal(0, session.CloseCalls); Equal(true, result.Error is not null);
});
AsyncTest("worker close cancellation preserves window", async () =>
{
    var session = new TestSession { CancelClose = true };
    var result = await DocumentClose.TryAsync(session, () => Task.FromResult(CloseChoice.Discard), () => Task.FromResult(true));
    Equal(false, result.Closed);
});
AsyncTest("worker close failure preserves window", async () =>
{
    var session = new TestSession { FailClose = true };
    var result = await DocumentClose.TryAsync(session, () => Task.FromResult(CloseChoice.Discard), () => Task.FromResult(true));
    Equal(false, result.Closed); Equal(true, result.Error is not null);
});

WorkerClient StartWorker() => WorkerClient.Start(new ProcessStartInfo
{
    FileName = Environment.ProcessPath!,
    ArgumentList = { typeof(TestSession).Assembly.Location, "--fake-worker" }
}, TimeSpan.FromSeconds(2));

// A real child process verifies wire framing, request correlation, timeout and owned cleanup.
AsyncTest("worker JSON preserves Korean paths and correlates concurrent replies", async () =>
{
    await using var client = StartWorker();
    var first = client.SendAsync("echo", new { path = "C:\\문서 & 글\\a.docx", parentHwnd = 1234567890123L });
    var second = client.SendAsync("echo", new { value = "두 번째" });
    Equal("C:\\문서 & 글\\a.docx", (await first).GetProperty("path").GetString());
    Equal(1234567890123L, (await first).GetProperty("parentHwnd").GetInt64());
    Equal("두 번째", (await second).GetProperty("value").GetString());
});
AsyncTest("worker structured errors surface as Korean errors", async () =>
{
    await using var client = StartWorker();
    await ThrowsAsync<SuiteException>(() => client.SendAsync("error", new { }));
});
AsyncTest("native menu event is delivered without consuming request reply", async () =>
{
    await using var client = StartWorker();
    var received = new TaskCompletionSource<WorkerCommand>(TaskCreationOptions.RunContinuationsAsynchronously);
    client.CommandReceived += command => received.TrySetResult(command);
    Equal(3, (await client.SendAsync("event", new { value = 3 })).GetProperty("value").GetInt32());
    Equal("saveAs", (await received.Task.WaitAsync(TimeSpan.FromSeconds(2))).Command);
});
AsyncTest("worker timeout is bounded and later replies still correlate", async () =>
{
    await using var client = StartWorker();
    await ThrowsAsync<SuiteException>(() => client.SendAsync("timeout", new { }));
    Equal(7, (await client.SendAsync("echo", new { value = 7 })).GetProperty("value").GetInt32());
});
AsyncTest("worker unexpected exit fails pending operation", async () =>
{
    await using var client = StartWorker();
    await ThrowsAsync<SuiteException>(() => client.SendAsync("exit", new { }));
});
AsyncTest("dispose terminates only the owned worker", async () =>
{
    await using var unrelated = StartWorker();
    var client = StartWorker();
    var id = client.ProcessId;
    await client.DisposeAsync();
    try { Equal(true, Process.GetProcessById(id).HasExited); }
    catch (ArgumentException) { }
    Equal("alive", (await unrelated.SendAsync("echo", new { value = "alive" })).GetProperty("value").GetString());
});

var failures = 0;
foreach (var (name, run) in tests)
{
    try { await run(); Console.WriteLine($"PASS {name}"); }
    catch (Exception e) { failures++; Console.WriteLine($"FAIL {name}: {e.Message}"); }
}
Console.WriteLine($"{tests.Count - failures}/{tests.Count} passed");
return failures == 0 ? 0 : 1;

sealed class TestSession : IDocumentSession
{
    public bool Modified { get; init; }
    public bool FailStatus { get; init; }
    public bool FailClose { get; init; }
    public bool CancelClose { get; init; }
    public int CloseCalls { get; private set; }
    public bool Discard { get; private set; }
    public Task<DocumentStatus> StatusAsync() => FailStatus ? throw new SuiteException("상태 확인 실패") : Task.FromResult(new DocumentStatus(Modified, "문서"));
    public Task<bool> CloseAsync(bool discard)
    {
        CloseCalls++; Discard = discard;
        if (FailClose) throw new SuiteException("닫기 실패");
        return Task.FromResult(!CancelClose);
    }
}
