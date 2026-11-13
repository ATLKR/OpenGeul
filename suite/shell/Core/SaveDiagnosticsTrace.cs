using System.Text.Json;

namespace OpenGeul.Office.Core;

/// <summary>Opt-in, content-free save-route evidence; never part of a save decision.</summary>
public sealed class SaveDiagnosticsTrace
{
    private readonly string eventName;
    private readonly object writeLock = new();
    private int count;
    public bool Enabled { get; }

    public SaveDiagnosticsTrace(string eventName)
    {
        this.eventName = eventName;
        try { Enabled = !string.IsNullOrEmpty(Environment.GetEnvironmentVariable("OPENGEUL_SUITE_DIAGNOSTICS")); }
        catch (Exception) { Enabled = false; }
    }

    public void Write(string stage, object? details = null, int? workerProcessId = null, string? traceId = null)
    {
        if (!Enabled) return;
        try
        {
            lock (writeLock)
            {
                // Bound attempts, including failed writes, independently for each form/client.
                // Keep physical output order equal to sequence order for this logger only.
                if (count >= 128) return;
                var sequence = ++count;
                Console.Error.WriteLine(JsonSerializer.Serialize(new
                {
                    @event = eventName, component = "host", stage, sequence,
                    utc = DateTimeOffset.UtcNow, processId = Environment.ProcessId,
                    managedThreadId = Environment.CurrentManagedThreadId, workerProcessId, traceId, details
                }));
                Console.Error.Flush();
            }
        }
        catch (Exception) { /* Diagnostic failures must not change save behavior. */ }
    }
}
