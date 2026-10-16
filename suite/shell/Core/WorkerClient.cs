using System.Collections.Concurrent;
using System.Diagnostics;
using System.Text;
using System.Text.Json;

namespace OpenGeul.Office.Core;

public sealed record WorkerCommand(string Command, string? Module);

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
    private long nextId;
    private int disposed;
    private volatile Exception? terminalError;
    public int ProcessId => process.Id;
    public string Diagnostics { get { lock (diagnostics) return diagnostics.ToString(); } }

    private WorkerClient(Process process, TimeSpan timeout)
    {
        this.process = process;
        this.timeout = timeout;
        readTask = ReadRepliesAsync();
        errorTask = ReadDiagnosticsAsync();
    }

    public static WorkerClient Start(ProcessStartInfo start, TimeSpan? timeout = null)
    {
        start.UseShellExecute = false;
        start.CreateNoWindow = true;
        start.RedirectStandardInput = start.RedirectStandardOutput = start.RedirectStandardError = true;
        start.StandardInputEncoding = start.StandardOutputEncoding = start.StandardErrorEncoding = new UTF8Encoding(false);
        try
        {
            var process = Process.Start(start) ?? throw new SuiteException("문서 작업자를 시작할 수 없습니다.");
            process.StandardInput.AutoFlush = true;
            return new WorkerClient(process, timeout ?? TimeSpan.FromSeconds(60));
        }
        catch (Exception e) when (e is not SuiteException)
        {
            throw new SuiteException("Office 문서 작업자를 시작하지 못했습니다. 패키지의 런타임을 확인해 주세요.", e);
        }
    }

    public async Task<JsonElement> SendAsync(string command, object args)
    {
        if (Volatile.Read(ref disposed) != 0) throw new SuiteException("문서 작업자가 이미 종료되었습니다.");
        if (terminalError is not null) throw new SuiteException("문서 작업자와 연결이 끊어졌습니다. 문서 창을 유지합니다.", terminalError);
        var id = Interlocked.Increment(ref nextId);
        var completion = new TaskCompletionSource<JsonElement>(TaskCreationOptions.RunContinuationsAsynchronously);
        pending[id] = completion;
        try
        {
            using var deadline = CancellationTokenSource.CreateLinkedTokenSource(stopped.Token);
            deadline.CancelAfter(timeout);
            await writeLock.WaitAsync(deadline.Token);
            try
            {
                if (terminalError is not null) throw new SuiteException("문서 작업자와 연결이 끊어졌습니다.", terminalError);
                var line = JsonSerializer.Serialize(new { id, command, args });
                await process.StandardInput.WriteLineAsync(line.AsMemory(), deadline.Token);
                await process.StandardInput.FlushAsync(deadline.Token);
            }
            finally { writeLock.Release(); }
            return await completion.Task.WaitAsync(deadline.Token);
        }
        catch (SuiteException) { throw; }
        catch (OperationCanceledException e)
        {
            throw new SuiteException("문서 작업자의 응답 시간이 초과되었습니다. 문서 창을 유지합니다. 잠시 후 다시 시도해 주세요.", e);
        }
        catch (Exception e)
        {
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
                            if (handler is not null)
                                _ = Task.Run(() => { try { handler(new WorkerCommand(command, module)); } catch (Exception) { /* UI lifetime may have ended. */ } });
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
