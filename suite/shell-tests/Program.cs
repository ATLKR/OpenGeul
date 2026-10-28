using System.Diagnostics;
using System.Drawing;
using System.Text.Json;
using OpenGeul.Office.Core;

if (args.Length > 0 && args[0] == "--worker-runtime-probe")
    return await WorkerRuntimeDiagnostic.RunAsync(args);

if (ComWaitDiagnostic.IsDiagnosticCommand(args))
    return await ComWaitDiagnostic.RunAsync(args);

if (args.Contains("--fake-startup-worker"))
{
    var mode = args[^1];
    if (mode == "pending-startup-error")
    {
        using var first = JsonDocument.Parse(Console.ReadLine()!);
        using var second = JsonDocument.Parse(Console.ReadLine()!);
        Console.Error.WriteLine($"request-ids:{first.RootElement.GetProperty("id").GetInt64()},{second.RootElement.GetProperty("id").GetInt64()}");
        Console.Error.Flush();
    }
    Console.WriteLine(JsonSerializer.Serialize(new { id = (long?)null, ok = false,
        error = new { code = mode == "pending-startup-error" ? "ui_style_isolation_failed" : "invalid_manifest",
            message = "제품 설정을 읽을 수 없습니다." } }));
    Console.Out.Flush();
    if (mode == "startup-error-exit") return 1;
    while (Console.ReadLine() is not null) { }
    return 0;
}

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
        else if (command == "unknown-error")
            Console.WriteLine(JsonSerializer.Serialize(new { id, ok = false, error = new { code = "PRIVATE-UNKNOWN-CODE", message = "runtime_missing ui_style_isolation_failed" } }));
        else if (command == "invalid-id")
            Console.WriteLine(JsonSerializer.Serialize(new { id = "invalid", ok = false, error = new { code = "invalid_manifest", message = "제품 설정을 읽을 수 없습니다." } }));
        else if (command == "null-success")
            Console.WriteLine(JsonSerializer.Serialize(new { id = (long?)null, ok = true, result = new { } }));
        else if (command == "invalid-ok")
            Console.WriteLine(JsonSerializer.Serialize(new { id, ok = "false", error = new { code = "invalid_manifest", message = "제품 설정을 읽을 수 없습니다." } }));
        else if (command == "missing-result")
            Console.WriteLine(JsonSerializer.Serialize(new { id, ok = true }));
        else if (command == "invalid-message")
            Console.WriteLine(JsonSerializer.Serialize(new { id, ok = false, error = new { code = "invalid_manifest", message = new { arbitrary = "private" } } }));
        else
        {
            if (command == "late-error")
                Console.WriteLine(JsonSerializer.Serialize(new { id = 99999, ok = false, error = new { code = "runtime_missing", message = "late reply" } }));
            Console.WriteLine(JsonSerializer.Serialize(new { id, ok = true, result = root.GetProperty("args").Clone() }));
        }
    }
    return 0;
}

var tests = new List<(string Name, Func<Task> Run)>();
tests.AddRange(OwnedEditorFocusTests.Cases());
tests.AddRange(OwnedDocumentMenuFocusTests.Cases());
tests.AddRange(StandaloneSaveCloseIntentTests.Cases());
tests.AddRange(StartupDiagnosticTests.Cases(mode => mode == "normal" ? StartWorker() : WorkerClient.Start(new ProcessStartInfo
{
    FileName = Environment.ProcessPath!,
    ArgumentList = { typeof(TestSession).Assembly.Location, "--fake-startup-worker", mode }
}, TimeSpan.FromSeconds(5))));
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
CloseResult ParseWorkerClose(string json)
{
    using var document = JsonDocument.Parse(json);
    return DocumentClose.FromWorkerResult(document.RootElement);
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
        if (new[] { "PATH", "PYTHONHOME", "PYTHONPATH", "PYTHONDONTWRITEBYTECODE", "PYTHONIOENCODING" }.Contains(name, StringComparer.OrdinalIgnoreCase)) continue;
        Equal(true, start.Environment.TryGetValue(name, out var value) && value == (string?)variable.Value);
    }
});
Test("worker launch keeps unicode paths in structured arguments and UTF-8 protocol", () =>
{
    var root = Path.Combine(Path.GetTempPath(), "OpenGeul 한글 & local");
    var start = WorkerLaunch.Create(root);
    Equal(Path.Combine(root, "Office", "program", "python-core-3.13.15", "bin", "python.exe"), start.FileName);
    Equal(root, start.WorkingDirectory);
    Equal("", start.Arguments);
    Equal("-u", start.ArgumentList[0]);
    Equal(Path.Combine(root, "worker", "office_worker.py"), start.ArgumentList[1]);
    Equal("--runtime", start.ArgumentList[2]);
    Equal(Path.Combine(root, "Office"), start.ArgumentList[3]);
    Equal("1", start.Environment["PYTHONDONTWRITEBYTECODE"]);
    Equal("utf-8", start.Environment["PYTHONIOENCODING"]);
});
Test("worker launch supplies packaged Python bootstrap only to the child", () =>
{
    var names = new[] { "UNO_PATH", "URE_BOOTSTRAP", "PYTHONHOME", "PYTHONPATH" };
    var previous = names.ToDictionary(name => name, Environment.GetEnvironmentVariable);
    try
    {
        foreach (var name in names) Environment.SetEnvironmentVariable(name, null);
        var root = Path.Combine(Path.GetTempPath(), "OpenGeul 한글 & $raw");
        var program = Path.Combine(root, "Office", "program");
        var core = Path.Combine(program, "python-core-3.13.15");
        var start = WorkerLaunch.Create(root);
        Equal(program, start.Environment["UNO_PATH"]);
        Equal("vnd.sun.star.pathname:" + Path.Combine(program, "fundamental.ini"), start.Environment["URE_BOOTSTRAP"]);
        Equal(core, start.Environment["PYTHONHOME"]);
        Equal(string.Join(Path.PathSeparator, program, Path.Combine(core, "lib"), Path.Combine(core, "lib", "site-packages")), start.Environment["PYTHONPATH"]);
        foreach (var name in names) Equal(true, Environment.GetEnvironmentVariable(name) is null);
    }
    finally
    {
        foreach (var name in names) Environment.SetEnvironmentVariable(name, previous[name]);
    }
});
Test("worker launch preserves inherited bootstrap and Python path suffix without expansion", () =>
{
    var names = new[] { "UNO_PATH", "URE_BOOTSTRAP", "PYTHONHOME", "PYTHONPATH" };
    var previous = names.ToDictionary(name => name, Environment.GetEnvironmentVariable);
    var inherited = new Dictionary<string, string>
    {
        ["UNO_PATH"] = Path.Combine(Path.GetTempPath(), "기존 UNO & $raw"),
        ["URE_BOOTSTRAP"] = "vnd.sun.star.pathname:" + Path.Combine(Path.GetTempPath(), "기존 & $raw.ini"),
        ["PYTHONHOME"] = Path.Combine(Path.GetTempPath(), "기존 Python & $raw"),
        ["PYTHONPATH"] = Path.Combine(Path.GetTempPath(), "기존 모듈 & $raw")
    };
    try
    {
        foreach (var name in names) Environment.SetEnvironmentVariable(name, inherited[name]);
        var root = Path.Combine(Path.GetTempPath(), "OpenGeul 한글 & $raw");
        var program = Path.Combine(root, "Office", "program");
        var core = Path.Combine(program, "python-core-3.13.15");
        var start = WorkerLaunch.Create(root);
        Equal(inherited["UNO_PATH"], start.Environment["UNO_PATH"]);
        Equal(inherited["URE_BOOTSTRAP"], start.Environment["URE_BOOTSTRAP"]);
        Equal(core, start.Environment["PYTHONHOME"]);
        Equal(string.Join(Path.PathSeparator, program, Path.Combine(core, "lib"), Path.Combine(core, "lib", "site-packages"), inherited["PYTHONPATH"]), start.Environment["PYTHONPATH"]);
        foreach (var name in names) Equal(true, Environment.GetEnvironmentVariable(name) == inherited[name]);
    }
    finally
    {
        foreach (var name in names) Environment.SetEnvironmentVariable(name, previous[name]);
    }
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
    Equal(false, result.Closed); Equal(0, session.CloseCalls); Equal(null, result.Warning);
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
    var session = new TestSession { FailStatus = true, CloseOutcome = new(true, Warning: "engine cleanup failed") };
    var result = await DocumentClose.TryAsync(session, () => Task.FromResult(CloseChoice.Discard), () => Task.FromResult(true));
    Equal(false, result.Closed); Equal(0, session.CloseCalls); Equal(true, result.Error is not null); Equal(null, result.Warning);
});
AsyncTest("worker close cancellation preserves window", async () =>
{
    var session = new TestSession { CancelClose = true };
    var result = await DocumentClose.TryAsync(session, () => Task.FromResult(CloseChoice.Discard), () => Task.FromResult(true));
    Equal(false, result.Closed); Equal(null, result.Warning);
});
AsyncTest("worker close failure preserves window", async () =>
{
    var session = new TestSession { FailClose = true };
    var result = await DocumentClose.TryAsync(session, () => Task.FromResult(CloseChoice.Discard), () => Task.FromResult(true));
    Equal(false, result.Closed); Equal(true, result.Error is not null); Equal(null, result.Warning);
});
Test("confirmed document close carries cleanup failure without claiming document stayed open", () =>
{
    var result = ParseWorkerClose("""
    {"closed":true,"closeCancelled":false,"cleanupVerified":false,"cleanupError":"owned Office process exit was not verified"}
    """);
    Equal(true, result.Closed);
    Equal(null, result.Error);
    var warning = result.Warning;
    Equal(true, warning?.Contains("owned Office process exit was not verified") == true);
    Equal(true, warning?.Contains("문서는 닫혔") == true);
    Equal(false, warning?.Contains("창을 유지") == true);
});
Test("confirmed close with missing or malformed cleanup proof remains closed with a warning", () =>
{
    foreach (var json in new[]
    {
        """{"closed":true,"closeCancelled":false}""",
        """{"closed":true,"closeCancelled":false,"cleanupVerified":null,"cleanupError":42}""",
        """{"closed":true,"closeCancelled":false,"cleanupVerified":"true"}"""
    })
    {
        var result = ParseWorkerClose(json);
        Equal(true, result.Closed);
        Equal(null, result.Error);
        Equal(true, !string.IsNullOrWhiteSpace(result.Warning));
    }
});
Test("verified cleanup after confirmed document close has no warning", () =>
{
    var result = ParseWorkerClose("""{"closed":true,"closeCancelled":false,"cleanupVerified":true}""");
    Equal(true, result.Closed); Equal(null, result.Error); Equal(null, result.Warning);
});
Test("worker cancellation never becomes a confirmed closed cleanup warning", () =>
{
    foreach (var json in new[]
    {
        """{"closed":false,"closeCancelled":true,"cleanupVerified":false}""",
        """{"closed":true,"closeCancelled":true,"cleanupVerified":false}""",
        """{"closed":false,"closeCancelled":false,"cleanupVerified":true}"""
    })
    {
        var result = ParseWorkerClose(json);
        Equal(false, result.Closed); Equal(null, result.Warning);
    }
});
AsyncTest("document close preserves a confirmed close warning from its owned session", async () =>
{
    var outcome = ParseWorkerClose("""{"closed":true,"closeCancelled":false,"cleanupVerified":false,"cleanupError":"owned process was forced"}""");
    var session = new TestSession { CloseOutcome = outcome };
    var result = await DocumentClose.TryAsync(session, () => throw new Exception("unexpected prompt"), () => throw new Exception("unexpected save"));
    Equal(true, result.Closed); Equal(null, result.Error); Equal(outcome.Warning, result.Warning);
    Equal(1, session.CloseCalls); Equal(false, session.Discard);
});
Test("malformed cancellation proof cannot confirm document close", () =>
{
    foreach (var value in new[] { "\"true\"", "null", "0", "{}" })
        Throws<SuiteException>(() => ParseWorkerClose("{\"closed\":true,\"closeCancelled\":" + value + ",\"cleanupVerified\":true}"));
});
AsyncTest("close preparation can require a choice even when ordinary status is clean", async () =>
{
    var session = new TestSession { PreparedModified = true };
    var result = await DocumentClose.TryAsync(session, () =>
    {
        session.Events.Add("choice");
        return Task.FromResult(CloseChoice.Cancel);
    }, () => throw new Exception("unexpected save"));
    Equal(false, result.Closed); Equal(0, session.CloseCalls);
    Equal("prepare,choice", string.Join(',', session.Events));
});
AsyncTest("close preparation precedes choice save and document close", async () =>
{
    var session = new TestSession { PreparedModified = true };
    var result = await DocumentClose.TryAsync(session, () =>
    {
        session.Events.Add("choice");
        return Task.FromResult(CloseChoice.Save);
    }, () =>
    {
        session.Events.Add("save");
        return Task.FromResult(true);
    });
    Equal(true, result.Closed); Equal(false, session.Discard);
    Equal("prepare,choice,save,close", string.Join(',', session.Events));
});
AsyncTest("close preparation precedes explicit discard without saving", async () =>
{
    var session = new TestSession { PreparedModified = true };
    var result = await DocumentClose.TryAsync(session, () =>
    {
        session.Events.Add("choice");
        return Task.FromResult(CloseChoice.Discard);
    }, () => throw new Exception("unexpected save"));
    Equal(true, result.Closed); Equal(true, session.Discard);
    Equal("prepare,choice,close", string.Join(',', session.Events));
});
AsyncTest("close preparation failure keeps the document without prompting saving or closing", async () =>
{
    var session = new TestSession { FailPreparation = true };
    var result = await DocumentClose.TryAsync(session, () => throw new Exception("unexpected prompt"), () => throw new Exception("unexpected save"));
    Equal(false, result.Closed); Equal(true, result.Error?.Contains("닫기 준비 실패") == true);
    Equal(null, result.Warning); Equal(0, session.CloseCalls);
    Equal("prepare", string.Join(',', session.Events));
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

Test("initial placement contains the observed normal window in the actual workarea", () =>
{
    var result = InitialWindowPlacement.Fit(new Rectangle(0, 0, 1044, 788), new Size(700, 500), new Rectangle(0, 0, 1024, 720));
    Equal(new Rectangle(0, 0, 1024, 720), result.Bounds);
    Equal(new Size(700, 500), result.MinimumSize);
});
Test("initial placement preserves fitting desktop bounds and location", () =>
{
    foreach (var bounds in new[] { new Rectangle(207, 151, 1266, 889), new Rectangle(307, 101, 1066, 839) })
    {
        var result = InitialWindowPlacement.Fit(bounds, new Size(700, 500), new Rectangle(0, 0, 1920, 1040));
        Equal(bounds, result.Bounds);
        Equal(new Size(700, 500), result.MinimumSize);
    }
});
Test("initial placement shrinks only the oversized dimension", () =>
{
    var result = InitialWindowPlacement.Fit(new Rectangle(0, 0, 1400, 650), new Size(700, 500), new Rectangle(0, 0, 1024, 720));
    Equal(new Rectangle(0, 35, 1024, 650), result.Bounds);
});
Test("initial placement recenters an off-work window without enlarging it", () =>
{
    var result = InitialWindowPlacement.Fit(new Rectangle(900, 600, 950, 700), new Size(700, 500), new Rectangle(0, 0, 1920, 1040));
    Equal(new Rectangle(485, 170, 950, 700), result.Bounds);
});
Test("initial placement respects negative secondary monitor origins", () =>
{
    var result = InitialWindowPlacement.Fit(new Rectangle(-1700, -940, 1044, 788), new Size(700, 500), new Rectangle(-1600, -900, 1600, 860));
    Equal(new Rectangle(-1322, -864, 1044, 788), result.Bounds);
});
Test("initial placement uses the supplied workarea for every taskbar edge", () =>
{
    foreach (var area in new[] { new Rectangle(0, 0, 1024, 720), new Rectangle(48, 0, 976, 768),
        new Rectangle(0, 48, 1024, 720), new Rectangle(0, 0, 976, 768) })
        Equal(area, InitialWindowPlacement.Fit(new Rectangle(0, 0, 1044, 788), new Size(700, 500), area).Bounds);
});
Test("initial placement accepts supplied 125 percent scaled sizes without scaling again", () =>
{
    var area = new Rectangle(0, 0, 1024, 720);
    var document = InitialWindowPlacement.Fit(new Rectangle(0, 0, 1583, 1112), new Size(875, 625), area);
    Equal(area, document.Bounds);
    Equal(new Size(875, 625), document.MinimumSize);
    var home = InitialWindowPlacement.Fit(new Rectangle(0, 0, 1333, 1049), new Size(1063, 875), area);
    Equal(area, home.Bounds);
    Equal(new Size(1024, 720), home.MinimumSize);
});
Test("initial placement caps supplied 150 percent minimum sizes to the workarea", () =>
{
    var area = new Rectangle(0, 0, 1024, 720);
    foreach (var minimum in new[] { new Size(1050, 750), new Size(1275, 1050) })
    {
        var result = InitialWindowPlacement.Fit(new Rectangle(0, 0, 1900, 1300), minimum, area);
        Equal(area, result.Bounds);
        Equal(area.Size, result.MinimumSize);
    }
});
Test("initial placement caps only minimum dimensions that exceed the workarea", () =>
{
    var result = InitialWindowPlacement.Fit(new Rectangle(0, 0, 1400, 900), new Size(1300, 500), new Rectangle(0, 0, 1024, 720));
    Equal(new Size(1024, 500), result.MinimumSize);
    Equal(new Rectangle(0, 0, 1024, 720), result.Bounds);
});
Test("initial placement rejects an empty working area", () =>
{
    foreach (var area in new[] { new Rectangle(0, 0, 0, 720), new Rectangle(0, 0, 1024, 0) })
        Throws<ArgumentOutOfRangeException>(() => InitialWindowPlacement.Fit(new Rectangle(0, 0, 1044, 788), new Size(700, 500), area));
});

Test("synthetic COM wait pure contracts only", () => ComWaitDiagnostic.PureContractTests());

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
    public bool? PreparedModified { get; init; }
    public bool FailPreparation { get; init; }
    public CloseResult? CloseOutcome { get; init; }
    public List<string> Events { get; } = new();
    public int CloseCalls { get; private set; }
    public bool Discard { get; private set; }
    public Task<DocumentStatus> StatusAsync()
    {
        Events.Add("status");
        return FailStatus ? throw new SuiteException("상태 확인 실패") : Task.FromResult(new DocumentStatus(Modified, "문서"));
    }
    public Task<DocumentStatus> PrepareCloseAsync()
    {
        Events.Add("prepare");
        if (FailPreparation) throw new SuiteException("닫기 준비 실패");
        return FailStatus ? throw new SuiteException("상태 확인 실패") : Task.FromResult(new DocumentStatus(PreparedModified ?? Modified, "문서"));
    }
    public Task<CloseResult> CloseAsync(bool discard)
    {
        CloseCalls++; Discard = discard;
        Events.Add("close");
        if (FailClose) throw new SuiteException("닫기 실패");
        return Task.FromResult(CloseOutcome ?? new CloseResult(!CancelClose));
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
