namespace OpenGeul.Office.Core;

public sealed class StandaloneSaveCloseIntent
{
    private sealed class SaveOperation(object worker)
    {
        internal object Worker { get; } = worker;
        internal bool CloseRequested { get; set; }
    }

    private SaveOperation? active;

    // The owning form calls this policy only on its UI thread.
    public bool RequestClose(object worker)
    {
        if (active is null || !ReferenceEquals(active.Worker, worker)) return false;
        active.CloseRequested = true;
        return true;
    }

    public void Invalidate() => active = null;

    public async Task<bool> RunAsync(object worker, bool documentClosing, Func<Task<bool>> save,
        Func<object?> currentWorker, Func<bool> canClose, Func<Task> close)
    {
        ArgumentNullException.ThrowIfNull(worker);
        if (documentClosing) return await save();
        if (active is not null) throw new InvalidOperationException("A standalone save is already running.");
        var operation = new SaveOperation(worker);
        active = operation;
        var saved = false;
        try
        {
            saved = await save();
            return saved;
        }
        finally
        {
            if (ReferenceEquals(active, operation))
            {
                // Consume before invoking normal close, including its possible save.
                active = null;
                if (saved && operation.CloseRequested && ReferenceEquals(currentWorker(), operation.Worker) && canClose())
                    await close();
            }
        }
    }
}
