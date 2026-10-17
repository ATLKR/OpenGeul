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
        if (command == "delay")
            await Task.Delay(root.GetProperty("args").GetProperty("delayMs").GetInt32());
        if (command == "timeout") continue;
        if (command == "exit") return 0;
        if (command == "event")
            Console.WriteLine(JsonSerializer.Serialize(new { @event = "command", command = "saveAs", module = "writer" }));
        if (command == "trace-environment")
        {
            Console.WriteLine(JsonSerializer.Serialize(new { id, ok = true, result = new
            {
                traceId = Environment.GetEnvironmentVariable("OPENGEUL_SUITE_SAVE_TRACE_ID")
            } }));
            continue;
        }
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
Test("worker launch prepends bundled program to process-local PATH", () =>
{
    var inheritedPath = Environment.GetEnvironmentVariable("PATH");
    var root = Path.Combine(Path.GetTempPath(), "OpenGeul 한글 & local");
    var start = WorkerLaunch.Create(root);
    var program = Path.Combine(root, "Office", "program");
    Equal(program + (string.IsNullOrEmpty(inheritedPath) ? "" : Path.PathSeparator + inheritedPath), start.Environment["PATH"]);
    Equal(inheritedPath, Environment.GetEnvironmentVariable("PATH"));
});
Test("worker launch preserves inherited environment without exposing values", () =>
{
    var start = WorkerLaunch.Create(Path.Combine(Path.GetTempPath(), "OpenGeul"));
    foreach (System.Collections.DictionaryEntry variable in Environment.GetEnvironmentVariables())
    {
        var name = (string)variable.Key;
        if (new[] { "PATH", "PYTHONDONTWRITEBYTECODE", "PYTHONIOENCODING" }.Contains(name, StringComparer.OrdinalIgnoreCase)) continue;
        Equal(true, start.Environment.TryGetValue(name, out var value) && value == (string?)variable.Value);
    }
});
Test("worker launch keeps unicode paths in structured arguments and UTF-8 protocol", () =>
{
    var root = Path.Combine(Path.GetTempPath(), "OpenGeul 한글 & local");
    var start = WorkerLaunch.Create(root);
    Equal(Path.Combine(root, "Office", "program", "python.exe"), start.FileName);
    Equal(root, start.WorkingDirectory);
    Equal("", start.Arguments);
    Equal("-u", start.ArgumentList[0]);
    Equal(Path.Combine(root, "worker", "office_worker.py"), start.ArgumentList[1]);
    Equal("--runtime", start.ArgumentList[2]);
    Equal(Path.Combine(root, "Office"), start.ArgumentList[3]);
    Equal("1", start.Environment["PYTHONDONTWRITEBYTECODE"]);
    Equal("utf-8", start.Environment["PYTHONIOENCODING"]);
});
Test("Base clean status preserves unverified connection readiness message", () =>
    Equal("저장됨 · 연결과 Java 사용 가능 여부가 확인되지 않았습니다.",
        DocumentStatusText.Format("base", false, true, "연결과 Java 사용 가능 여부가 확인되지 않았습니다.")));
Test("Base dirty status keeps the worker readiness message visible", () =>
    Equal("변경 내용이 있습니다. · 데이터베이스 연결을 확인해 주세요.",
        DocumentStatusText.Format("base", true, true, "데이터베이스 연결을 확인해 주세요.")));
Test("Base missing readiness does not claim database is ready", () =>
    Equal("새 문서 · 데이터베이스 연결과 추가 구성 요소의 준비 상태가 확인되지 않았습니다.",
        DocumentStatusText.Format("base", false, false, null)));
Test("ordinary module status is unchanged by Base readiness metadata", () =>
{
    Equal("준비 · 저장됨", DocumentStatusText.Format("writer", false, true, "연결 확인 필요"));
    Equal("준비 · 새 문서", DocumentStatusText.Format("calc", false, false, null));
    Equal("변경 내용이 있습니다.", DocumentStatusText.Format("impress", true, true, null));
});
Test("HWP launch prepends shared CRT directory to process-local PATH", () =>
{
    var inheritedPath = Environment.GetEnvironmentVariable("PATH");
    var root = Path.Combine(Path.GetTempPath(), "OpenGeul 한글 & local");
    var start = HwpLaunch.Create(root, null);
    Equal(Path.Combine(root, "Office", "program") + (string.IsNullOrEmpty(inheritedPath) ? "" : Path.PathSeparator + inheritedPath), start.Environment["PATH"]);
    Equal(inheritedPath, Environment.GetEnvironmentVariable("PATH"));
});
Test("HWP launch uses only fixed original executable and one structured document argument", () =>
{
    var root = Path.Combine(Path.GetTempPath(), "OpenGeul 한글 & local");
    var document = "C:\\문서 폴더\\a & b $(x).hwpx";
    var start = HwpLaunch.Create(root, document);
    Equal(Path.Combine(root, "HWP", "OpenGeul.exe"), start.FileName);
    Equal(Path.Combine(root, "HWP"), start.WorkingDirectory);
    Equal(false, start.UseShellExecute);
    Equal("", start.Arguments);
    Equal(1, start.ArgumentList.Count);
    Equal(document, start.ArgumentList[0]);
});
Test("HWP new-document launch has no document argument", () =>
    Equal(0, HwpLaunch.Create(Path.Combine(Path.GetTempPath(), "OpenGeul"), null).ArgumentList.Count));
Test("HWP launch preserves every inherited non-PATH environment entry", () =>
{
    var start = HwpLaunch.Create(Path.Combine(Path.GetTempPath(), "OpenGeul"), null);
    foreach (System.Collections.DictionaryEntry variable in Environment.GetEnvironmentVariables())
    {
        var name = (string)variable.Key;
        if (name.Equals("PATH", StringComparison.OrdinalIgnoreCase)) continue;
        Equal(true, start.Environment.TryGetValue(name, out var value) && value == (string?)variable.Value);
    }
});

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

WorkerClient StartWorker(TimeSpan? timeout = null) => WorkerClient.Start(new ProcessStartInfo
{
    FileName = Environment.ProcessPath!,
    ArgumentList = { typeof(TestSession).Assembly.Location, "--fake-worker" }
}, timeout ?? TimeSpan.FromSeconds(2));

// These exercise real child-process saves. Diagnostic output must not expose args,
// alter request/reply values, grow without bound, or turn output failure into a save failure.
AsyncTest("save diagnostics bind the original worker request without exposing document arguments", async () =>
{
    var previousEnvironment = Environment.GetEnvironmentVariable("OPENGEUL_SUITE_DIAGNOSTICS");
    var previousError = Console.Error;
    using var output = new StringWriter();
    try
    {
        Environment.SetEnvironmentVariable("OPENGEUL_SUITE_DIAGNOSTICS", "enabled-for-test");
        Console.SetError(output);
        await using var client = StartWorker();
        Equal("DOCUMENT-CONTENT-SENTINEL", (await client.SendAsync("save", new { value = "DOCUMENT-CONTENT-SENTINEL" })).GetProperty("value").GetString());
        var rows = output.ToString().Split('\n', StringSplitOptions.RemoveEmptyEntries)
            .Select(line => JsonDocument.Parse(line).RootElement.Clone()).ToArray();
        Equal("request.begin,request.written,request.reply", string.Join(',', rows.Select(row => row.GetProperty("stage").GetString())));
        foreach (var row in rows)
        {
            Equal("suite.workerSave", row.GetProperty("event").GetString());
            Equal("host", row.GetProperty("component").GetString());
            Equal(client.ProcessId, row.GetProperty("workerProcessId").GetInt32());
            Equal(1L, row.GetProperty("details").GetProperty("requestId").GetInt64());
        }
        Equal(true, rows[^1].GetProperty("details").GetProperty("ok").GetBoolean());
        Equal(false, output.ToString().Contains("DOCUMENT-CONTENT-SENTINEL"));
    }
    finally { Console.SetError(previousError); Environment.SetEnvironmentVariable("OPENGEUL_SUITE_DIAGNOSTICS", previousEnvironment); }
});
AsyncTest("save diagnostics are disabled without the existing opt in", async () =>
{
    var previousEnvironment = Environment.GetEnvironmentVariable("OPENGEUL_SUITE_DIAGNOSTICS");
    var previousError = Console.Error;
    using var output = new StringWriter();
    try
    {
        Environment.SetEnvironmentVariable("OPENGEUL_SUITE_DIAGNOSTICS", null);
        Console.SetError(output);
        await using var client = StartWorker();
        Equal(7, (await client.SendAsync("save", new { value = 7 })).GetProperty("value").GetInt32());
        Equal("", output.ToString());
    }
    finally { Console.SetError(previousError); Environment.SetEnvironmentVariable("OPENGEUL_SUITE_DIAGNOSTICS", previousEnvironment); }
});
AsyncTest("save trace token belongs only to the owned child and matches its actual environment", async () =>
{
    var previousEnvironment = Environment.GetEnvironmentVariable("OPENGEUL_SUITE_DIAGNOSTICS");
    var previousToken = Environment.GetEnvironmentVariable("OPENGEUL_SUITE_SAVE_TRACE_ID");
    var previousError = Console.Error;
    using var output = new StringWriter();
    try
    {
        Environment.SetEnvironmentVariable("OPENGEUL_SUITE_DIAGNOSTICS", "enabled-for-test");
        Environment.SetEnvironmentVariable("OPENGEUL_SUITE_SAVE_TRACE_ID", "PARENT-PRIVATE-SENTINEL");
        Console.SetError(output);
        await using var first = StartWorker();
        await using var second = StartWorker();
        var firstToken = (await first.SendAsync("trace-environment", new { })).GetProperty("traceId").GetString();
        var secondToken = (await second.SendAsync("trace-environment", new { })).GetProperty("traceId").GetString();
        Equal(true, Guid.TryParseExact(firstToken, "N", out _));
        Equal(true, Guid.TryParseExact(secondToken, "N", out _));
        Equal(false, firstToken == secondToken);
        Equal("PARENT-PRIVATE-SENTINEL", Environment.GetEnvironmentVariable("OPENGEUL_SUITE_SAVE_TRACE_ID"));
        await first.SendAsync("save", new { });
        await second.SendAsync("save", new { });
        var rows = output.ToString().Split('\n', StringSplitOptions.RemoveEmptyEntries)
            .Select(line => JsonDocument.Parse(line).RootElement.Clone()).ToArray();
        foreach (var row in rows)
            Equal(row.GetProperty("workerProcessId").GetInt32() == first.ProcessId ? firstToken : secondToken,
                row.GetProperty("traceId").GetString());
        Equal(false, output.ToString().Contains("PARENT-PRIVATE-SENTINEL"));
    }
    finally
    {
        Console.SetError(previousError);
        Environment.SetEnvironmentVariable("OPENGEUL_SUITE_DIAGNOSTICS", previousEnvironment);
        Environment.SetEnvironmentVariable("OPENGEUL_SUITE_SAVE_TRACE_ID", previousToken);
    }
});
AsyncTest("disabled save tracing preserves inherited child environment without creating a token", async () =>
{
    var previousEnvironment = Environment.GetEnvironmentVariable("OPENGEUL_SUITE_DIAGNOSTICS");
    var previousToken = Environment.GetEnvironmentVariable("OPENGEUL_SUITE_SAVE_TRACE_ID");
    var previousError = Console.Error;
    using var output = new StringWriter();
    try
    {
        Environment.SetEnvironmentVariable("OPENGEUL_SUITE_DIAGNOSTICS", null);
        Environment.SetEnvironmentVariable("OPENGEUL_SUITE_SAVE_TRACE_ID", "INHERITED-PRIVATE-SENTINEL");
        Console.SetError(output);
        await using var client = StartWorker();
        Equal("INHERITED-PRIVATE-SENTINEL", (await client.SendAsync("trace-environment", new { })).GetProperty("traceId").GetString());
        await client.SendAsync("save", new { });
        Equal("", output.ToString());
        Equal("INHERITED-PRIVATE-SENTINEL", Environment.GetEnvironmentVariable("OPENGEUL_SUITE_SAVE_TRACE_ID"));
    }
    finally
    {
        Console.SetError(previousError);
        Environment.SetEnvironmentVariable("OPENGEUL_SUITE_DIAGNOSTICS", previousEnvironment);
        Environment.SetEnvironmentVariable("OPENGEUL_SUITE_SAVE_TRACE_ID", previousToken);
    }
});
AsyncTest("save diagnostic output is bounded while all original saves still complete", async () =>
{
    var previousEnvironment = Environment.GetEnvironmentVariable("OPENGEUL_SUITE_DIAGNOSTICS");
    var previousError = Console.Error;
    using var output = new StringWriter();
    try
    {
        Environment.SetEnvironmentVariable("OPENGEUL_SUITE_DIAGNOSTICS", "enabled-for-test");
        Console.SetError(output);
        await using var client = StartWorker();
        for (var index = 0; index < 70; index++)
            Equal(index, (await client.SendAsync("save", new { value = index })).GetProperty("value").GetInt32());
        var rows = output.ToString().Split('\n', StringSplitOptions.RemoveEmptyEntries);
        Equal(128, rows.Length);
        using var last = JsonDocument.Parse(rows[^1]);
        Equal(128, last.RootElement.GetProperty("sequence").GetInt32());
    }
    finally { Console.SetError(previousError); Environment.SetEnvironmentVariable("OPENGEUL_SUITE_DIAGNOSTICS", previousEnvironment); }
});
AsyncTest("throwing diagnostic output preserves save request and reply", async () =>
{
    var previousEnvironment = Environment.GetEnvironmentVariable("OPENGEUL_SUITE_DIAGNOSTICS");
    var previousError = Console.Error;
    try
    {
        Environment.SetEnvironmentVariable("OPENGEUL_SUITE_DIAGNOSTICS", "enabled-for-test");
        Console.SetError(new FailingDiagnosticWriter());
        await using var client = StartWorker();
        Equal(9, (await client.SendAsync("save", new { value = 9 })).GetProperty("value").GetInt32());
    }
    finally { Console.SetError(previousError); Environment.SetEnvironmentVariable("OPENGEUL_SUITE_DIAGNOSTICS", previousEnvironment); }
});
Test("concurrent save trace serialization preserves physical sequence order and the attempt cap", () =>
{
    var previousEnvironment = Environment.GetEnvironmentVariable("OPENGEUL_SUITE_DIAGNOSTICS");
    var previousError = Console.Error;
    using var output = new StringWriter();
    using var firstEntered = new ManualResetEventSlim();
    using var secondFinished = new ManualResetEventSlim();
    try
    {
        Environment.SetEnvironmentVariable("OPENGEUL_SUITE_DIAGNOSTICS", "enabled-for-test");
        Console.SetError(output);
        var trace = new SaveDiagnosticsTrace("suite.workerSave");
        var first = new Thread(() => trace.Write("first", new BlockingDiagnosticDetails(firstEntered, secondFinished)));
        var second = new Thread(() => { trace.Write("second"); secondFinished.Set(); });
        first.Start();
        Equal(true, firstEntered.Wait(TimeSpan.FromSeconds(2)));
        second.Start();
        Equal(true, first.Join(TimeSpan.FromSeconds(2)));
        Equal(true, second.Join(TimeSpan.FromSeconds(2)));
        Parallel.For(0, 200, _ => trace.Write("concurrent"));
        var sequences = output.ToString().Split('\n', StringSplitOptions.RemoveEmptyEntries)
            .Select(line => JsonDocument.Parse(line).RootElement.GetProperty("sequence").GetInt32()).ToArray();
        Equal(128, sequences.Length);
        Equal(string.Join(',', Enumerable.Range(1, 128)), string.Join(',', sequences));
    }
    finally { Console.SetError(previousError); Environment.SetEnvironmentVariable("OPENGEUL_SUITE_DIAGNOSTICS", previousEnvironment); }
});
AsyncTest("native save event diagnostics preserve delivery and bind the host command sequence", async () =>
{
    var previousEnvironment = Environment.GetEnvironmentVariable("OPENGEUL_SUITE_DIAGNOSTICS");
    var previousError = Console.Error;
    using var output = new StringWriter();
    try
    {
        Environment.SetEnvironmentVariable("OPENGEUL_SUITE_DIAGNOSTICS", "enabled-for-test");
        Console.SetError(output);
        await using var client = StartWorker();
        var received = new TaskCompletionSource<WorkerCommand>(TaskCreationOptions.RunContinuationsAsynchronously);
        client.CommandReceived += command => received.TrySetResult(command);
        Equal(3, (await client.SendAsync("event", new { value = 3 })).GetProperty("value").GetInt32());
        var command = await received.Task.WaitAsync(TimeSpan.FromSeconds(2));
        Equal("saveAs", command.Command);
        var sequence = command.GetType().GetProperty("DiagnosticSequence")?.GetValue(command);
        Equal(1L, sequence);
        var rows = output.ToString().Split('\n', StringSplitOptions.RemoveEmptyEntries)
            .Select(line => JsonDocument.Parse(line).RootElement.Clone()).ToArray();
        Equal(true, rows.Any(row => row.GetProperty("stage").GetString() == "command.received"
            && row.GetProperty("details").GetProperty("commandSequence").GetInt64() == 1));
        Equal(true, rows.Any(row => row.GetProperty("stage").GetString() == "command.handler.enter"));
    }
    finally { Console.SetError(previousError); Environment.SetEnvironmentVariable("OPENGEUL_SUITE_DIAGNOSTICS", previousEnvironment); }
});

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
AsyncTest("per-request timeout permits a slow reply without changing the default deadline", async () =>
{
    await using var client = StartWorker(TimeSpan.FromMilliseconds(150));
    await client.SendAsync("echo", new { }, requestTimeout: TimeSpan.FromSeconds(5));
    Equal("startup", (await client.SendAsync("delay", new { delayMs = 600, value = "startup" },
        requestTimeout: TimeSpan.FromSeconds(3))).GetProperty("value").GetString());
    await ThrowsAsync<SuiteException>(() => client.SendAsync("delay", new { delayMs = 600 }));
    Equal("after default timeout", (await client.SendAsync("echo", new { value = "after default timeout" },
        requestTimeout: TimeSpan.FromSeconds(3))).GetProperty("value").GetString());
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

sealed class FailingDiagnosticWriter : StringWriter
{
    public override void WriteLine(string? value) => throw new IOException("diagnostic output unavailable");
}

sealed class BlockingDiagnosticDetails(ManualResetEventSlim entered, ManualResetEventSlim release)
{
    public bool Value
    {
        get { entered.Set(); release.Wait(TimeSpan.FromSeconds(1)); return true; }
    }
}
