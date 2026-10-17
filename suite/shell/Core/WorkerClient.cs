using System.Collections.Concurrent;
using System.Diagnostics;
using System.Text;
using System.Text.Json;

namespace OpenGeul.Office.Core;

public sealed record WorkerCommand(string Command, string? Module, long DiagnosticSequence = 0);

/// <summary>One document, one owned worker; no global process discovery or termination.</summary>
public sealed class WorkerClient : IAsyncDisposable
{
    public event Action<WorkerCommand>? CommandReceived;
    private readonly Process process;
    private readonly TimeSpan timeout;
    private readonly SemaphoreSlim writeLock = new(1, 1);
    private readonly CancellationTokenSource stopped = new();
    private readonly ConcurrentDictionary<long, TaskCompletionSource<JsonElement>> pending = new();
    private readonly Task readTask;
    private readonly Task errorTask;
    private readonly StringBuilder diagnostics = new();
    private readonly SaveDiagnosticsTrace saveDiagnostics = new("suite.workerSave");
    private long nextId;
    private long nextCommandSequence;
    private int disposed;
    private volatile Exception? terminalError;
    public int ProcessId => process.Id;
    public string? DiagnosticTraceId { get; }
    public string Diagnostics { get { lock (diagnostics) return diagnostics.ToString(); } }

    private WorkerClient(Process process, TimeSpan timeout, string? diagnosticTraceId)
    {
        this.process = process;
        this.timeout = timeout;
        DiagnosticTraceId = diagnosticTraceId;
        readTask = ReadRepliesAsync();
        errorTask = ReadDiagnosticsAsync();
    }

    public static WorkerClient Start(ProcessStartInfo start, TimeSpan? timeout = null)
    {
        start.UseShellExecute = false;
        start.CreateNoWindow = true;
        start.RedirectStandardInput = start.RedirectStandardOutput = start.RedirectStandardError = true;
        start.StandardInputEncoding = start.StandardOutputEncoding = start.StandardErrorEncoding = new UTF8Encoding(false);
        string? diagnosticTraceId = null;
        try
        {
            if (!string.IsNullOrEmpty(Environment.GetEnvironmentVariable("OPENGEUL_SUITE_DIAGNOSTICS")))
            {
                var token = Guid.NewGuid().ToString("N");
                // The bundled Python launcher and interpreter can have different PIDs.
                // Bind their inherited diagnostics to this client without touching the parent environment.
                start.Environment["OPENGEUL_SUITE_SAVE_TRACE_ID"] = token;
                diagnosticTraceId = token;
            }
        }
        catch (Exception) { /* Diagnostic token setup must not prevent worker startup. */ }
        try
        {
            var process = Process.Start(start) ?? throw new SuiteException("문서 작업자를 시작할 수 없습니다.");
            process.StandardInput.AutoFlush = true;
            return new WorkerClient(process, timeout ?? TimeSpan.FromSeconds(60), diagnosticTraceId);
        }
        catch (Exception e) when (e is not SuiteException)
        {
            throw new SuiteException("Office 문서 작업자를 시작하지 못했습니다. 패키지의 런타임을 확인해 주세요.", e);
        }
    }

    public async Task<JsonElement> SendAsync(string command, object args, TimeSpan? requestTimeout = null,
        long? diagnosticCommandSequence = null)
    {
        if (Volatile.Read(ref disposed) != 0) throw new SuiteException("문서 작업자가 이미 종료되었습니다.");
        if (terminalError is not null) throw new SuiteException("문서 작업자와 연결이 끊어졌습니다. 문서 창을 유지합니다.", terminalError);
        var id = Interlocked.Increment(ref nextId);
        var completion = new TaskCompletionSource<JsonElement>(TaskCreationOptions.RunContinuationsAsynchronously);
        pending[id] = completion;
        var traceSave = command == "save";
        if (traceSave) TraceSave("request.begin", new { requestId = id, commandSequence = diagnosticCommandSequence });
        try
        {
            using var deadline = CancellationTokenSource.CreateLinkedTokenSource(stopped.Token);
            deadline.CancelAfter(requestTimeout ?? timeout);
            await writeLock.WaitAsync(deadline.Token);
            try
            {
                if (terminalError is not null) throw new SuiteException("문서 작업자와 연결이 끊어졌습니다.", terminalError);
                var line = JsonSerializer.Serialize(new { id, command, args });
                await process.StandardInput.WriteLineAsync(line.AsMemory(), deadline.Token);
                await process.StandardInput.FlushAsync(deadline.Token);
                if (traceSave) TraceSave("request.written", new { requestId = id, commandSequence = diagnosticCommandSequence });
            }
            finally { writeLock.Release(); }
            var result = await completion.Task.WaitAsync(deadline.Token);
            if (traceSave) TraceSave("request.reply", new { requestId = id, commandSequence = diagnosticCommandSequence, ok = true });
            return result;
        }
        catch (SuiteException e)
        {
            if (traceSave) TraceSave("request.error", new { requestId = id, commandSequence = diagnosticCommandSequence, exceptionType = e.GetType().FullName });
            throw;
        }
        catch (OperationCanceledException e)
        {
            if (traceSave) TraceSave("request.error", new { requestId = id, commandSequence = diagnosticCommandSequence, exceptionType = e.GetType().FullName });
            throw new SuiteException("문서 작업자의 응답 시간이 초과되었습니다. 문서 창을 유지합니다. 잠시 후 다시 시도해 주세요.", e);
        }
        catch (Exception e)
        {
            if (traceSave) TraceSave("request.error", new { requestId = id, commandSequence = diagnosticCommandSequence, exceptionType = e.GetType().FullName });
            throw new SuiteException("문서 작업자와 통신하지 못했습니다. 문서 창을 유지합니다.", e);
        }
        finally { pending.TryRemove(id, out _); }
    }

    private async Task ReadRepliesAsync()
    {
        try
        {
            while (await process.StandardOutput.ReadLineAsync(stopped.Token) is { } line)
            {
                if (line.Length > 1048576) throw new SuiteException("작업자 응답이 너무 큽니다.");
                using var document = JsonDocument.Parse(line);
                var root = document.RootElement;
                if (root.TryGetProperty("event", out var eventName))
                {
                    if (eventName.GetString() == "command")
                    {
                        var command = root.GetProperty("command").GetString();
                        if (command is "open" or "new" or "save" or "saveAs" or "close")
                        {
                            var module = root.TryGetProperty("module", out var moduleValue) ? moduleValue.GetString() : null;
                            var handler = CommandReceived;
                            var commandSequence = Interlocked.Increment(ref nextCommandSequence);
                            var traceSave = command is "save" or "saveAs";
                            if (traceSave) TraceSave("command.received", new { commandSequence, command });
                            if (handler is not null)
                                _ = Task.Run(() =>
                                {
                                    try
                                    {
                                        if (traceSave) TraceSave("command.handler.enter", new { commandSequence, command });
                                        handler(new WorkerCommand(command, module, commandSequence));
                                        if (traceSave) TraceSave("command.handler.return", new { commandSequence, command });
                                    }
                                    catch (Exception e)
                                    {
                                        if (traceSave) TraceSave("command.handler.error", new { commandSequence, command, exceptionType = e.GetType().FullName });
                                        /* UI lifetime may have ended. */
                                    }
                                });
                            else if (traceSave) TraceSave("command.handler.missing", new { commandSequence, command });
                        }
                    }
                    continue;
                }
                var id = root.GetProperty("id").GetInt64();
                if (!pending.TryRemove(id, out var completion)) continue; // Late timed-out reply.
                if (root.GetProperty("ok").GetBoolean())
                    completion.TrySetResult(root.GetProperty("result").Clone());
                else
                {
                    var error = root.GetProperty("error");
                    var message = error.ValueKind == JsonValueKind.Object && error.TryGetProperty("message", out var text) ? text.GetString() : error.ToString();
                    completion.TrySetException(new SuiteException($"Office 문서 작업에 실패했습니다.\n{message}"));
                }
            }
            FailPending(new SuiteException("문서 작업자가 종료되어 연결이 끊어졌습니다."));
        }
        catch (Exception e) { FailPending(new SuiteException("문서 작업자의 응답을 읽지 못했습니다.", e)); }
    }

    private void TraceSave(string stage, object? details)
    {
        try { saveDiagnostics.Write(stage, details, process.Id, DiagnosticTraceId); }
        catch (Exception) { /* Even diagnostic identity lookup must not affect the worker. */ }
    }

    private void FailPending(Exception error)
    {
        terminalError = error;
        foreach (var item in pending)
            if (pending.TryRemove(item.Key, out var completion)) completion.TrySetException(error);
    }

    private async Task ReadDiagnosticsAsync()
    {
        var buffer = new char[1024];
        try
        {
            int count;
            while ((count = await process.StandardError.ReadAsync(buffer.AsMemory(), stopped.Token)) > 0)
                lock (diagnostics)
                {
                    diagnostics.Append(buffer, 0, count);
                    if (diagnostics.Length > 4096) diagnostics.Remove(0, diagnostics.Length - 4096);
                }
        }
        catch (OperationCanceledException) { }
        catch (IOException) { }
    }

    public async ValueTask DisposeAsync()
    {
        if (Interlocked.Exchange(ref disposed, 1) != 0) return;
        try
        {
            // The UI calls this only after a confirmed close or a failed initial attach.
            process.StandardInput.Close();
            using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(2));
            try { await process.WaitForExitAsync(deadline.Token); }
            catch (OperationCanceledException)
            {
                if (!process.HasExited) process.Kill(entireProcessTree: true);
                using var killDeadline = new CancellationTokenSource(TimeSpan.FromSeconds(2));
                await process.WaitForExitAsync(killDeadline.Token);
            }
        }
        finally
        {
            stopped.Cancel();
            FailPending(new SuiteException("문서 작업자가 종료되었습니다."));
            try { await Task.WhenAll(readTask, errorTask).WaitAsync(TimeSpan.FromSeconds(2)); } catch (Exception) { }
            process.Dispose();
            stopped.Dispose();
        }
    }
}
