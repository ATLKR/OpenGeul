using System.Reflection;
using OpenGeul.Office.Core;

internal static class StandaloneSaveCloseIntentTests
{
    private sealed class Policy
    {
        private readonly object value;
        private readonly Type type;
        internal Policy()
        {
            type = typeof(DocumentClose).Assembly.GetType("OpenGeul.Office.Core.StandaloneSaveCloseIntent")
                ?? throw new Exception("Standalone save close-intent policy is missing");
            value = Activator.CreateInstance(type) ?? throw new Exception("Close-intent policy could not be constructed");
        }
        internal bool Request(object worker) => (bool)type.GetMethod("RequestClose")!.Invoke(value, [worker])!;
        internal void Invalidate() => type.GetMethod("Invalidate")!.Invoke(value, null);
        internal Task<bool> Run(object worker, bool closing, Func<Task<bool>> save,
            Func<object?> currentWorker, Func<bool> available, Func<Task> close) =>
            (Task<bool>)type.GetMethod("RunAsync")!.Invoke(value, [worker, closing, save, currentWorker, available, close])!;
    }

    private static void Check(bool value, string message) { if (!value) throw new Exception(message); }
    private static TaskCompletionSource<bool> Pending() => new(TaskCreationOptions.RunContinuationsAsynchronously);

    internal static IEnumerable<(string Name, Func<Task> Run)> Cases()
    {
        yield return ("Close during the same incomplete standalone save drains once after success", async () =>
        {
            var policy = new Policy(); var worker = new object(); var pending = Pending(); var closes = 0;
            var run = policy.Run(worker, false, () => pending.Task, () => worker, () => true,
                () => { closes++; return Task.CompletedTask; });
            Check(!run.IsCompleted && closes == 0, "Close ran before the save completed");
            Check(policy.Request(worker), "The in-flight standalone save lost its close intent");
            Check(closes == 0, "Remembering a close interrupted the save");
            pending.SetResult(true);
            Check(await run && closes == 1, "The successful same save did not drain exactly one close");
            Check(!policy.Request(worker), "Completed save retained a close authority");
        });
        yield return ("Repeated close requests coalesce and are consumed before the close callback", async () =>
        {
            var policy = new Policy(); var worker = new object(); var pending = Pending(); var closes = 0;
            var run = policy.Run(worker, false, () => pending.Task, () => worker, () => true, () =>
            {
                closes++;
                Check(!policy.Request(worker), "The close callback could recursively requeue the consumed intent");
                return Task.CompletedTask;
            });
            Check(policy.Request(worker) && policy.Request(worker) && policy.Request(worker), "Duplicate close lost the original intent");
            pending.SetResult(true); await run;
            Check(closes == 1, "Duplicate requests caused duplicate closes");
        });
        yield return ("Another worker cannot request or inherit the standalone save close", async () =>
        {
            var policy = new Policy(); var worker = new object(); var other = new object(); var pending = Pending(); var closes = 0;
            var run = policy.Run(worker, false, () => pending.Task, () => worker, () => true,
                () => { closes++; return Task.CompletedTask; });
            Check(!policy.Request(other), "A foreign worker armed the close intent");
            pending.SetResult(true); await run;
            Check(closes == 0, "Foreign request caused a close");
        });
        yield return ("Worker replacement or removal before success cancels the queued close", async () =>
        {
            foreach (var replacement in new object?[] { null, new object() })
            {
                var policy = new Policy(); var worker = new object(); object? current = worker;
                var pending = Pending(); var closes = 0;
                var run = policy.Run(worker, false, () => pending.Task, () => current, () => true,
                    () => { closes++; return Task.CompletedTask; });
                Check(policy.Request(worker), "Original worker could not queue close");
                current = replacement; pending.SetResult(true); await run;
                Check(closes == 0 && !policy.Request(worker), "Replaced or missing worker was closed");
            }
        });
        yield return ("Disposed unavailable or recreated form cannot drain a successful save close", async () =>
        {
            var policy = new Policy(); var worker = new object(); var pending = Pending(); var available = true; var closes = 0;
            var run = policy.Run(worker, false, () => pending.Task, () => worker, () => available,
                () => { closes++; return Task.CompletedTask; });
            Check(policy.Request(worker), "Valid form could not queue close");
            available = false; pending.SetResult(true); await run;
            Check(closes == 0 && !policy.Request(worker), "Invalid form lifetime retained a close intent");
        });
        yield return ("Explicit invalidation prevents a stale completion consuming the next save intent", async () =>
        {
            var policy = new Policy(); var worker = new object(); var first = Pending(); var second = Pending(); var closes = 0;
            Task Close() { closes++; return Task.CompletedTask; }
            var oldRun = policy.Run(worker, false, () => first.Task, () => worker, () => true, Close);
            Check(policy.Request(worker), "First save could not queue close");
            policy.Invalidate();
            var newRun = policy.Run(worker, false, () => second.Task, () => worker, () => true, Close);
            Check(policy.Request(worker), "New save could not own a new close intent");
            first.SetResult(true); await oldRun;
            Check(closes == 0 && !newRun.IsCompleted, "Stale completion consumed the current operation");
            second.SetResult(true); await newRun;
            Check(closes == 1, "Current save lost its own pending close");
        });
        yield return ("Save failure or Save As cancellation retains the document and clears close intent", async () =>
        {
            var policy = new Policy(); var worker = new object(); var pending = Pending(); var closes = 0;
            Task Close() { closes++; return Task.CompletedTask; }
            var run = policy.Run(worker, false, () => pending.Task, () => worker, () => true, Close);
            Check(policy.Request(worker), "Standalone save could not queue close");
            pending.SetResult(false);
            Check(!await run && closes == 0 && !policy.Request(worker), "Failed or cancelled save closed the document");
            await policy.Run(worker, false, () => Task.FromResult(true), () => worker, () => true, Close);
            Check(closes == 0, "A later save inherited the cancelled close intent");
        });
        yield return ("Unexpected save exception is preserved without closing or retaining the intent", async () =>
        {
            var policy = new Policy(); var worker = new object(); var pending = Pending(); var error = new InvalidOperationException("original save"); var closes = 0;
            var run = policy.Run(worker, false, () => pending.Task, () => worker, () => true,
                () => { closes++; return Task.CompletedTask; });
            Check(policy.Request(worker), "Standalone save could not queue close");
            pending.SetException(error);
            try { await run; throw new Exception("Save exception was swallowed"); }
            catch (InvalidOperationException caught) { Check(ReferenceEquals(caught, error), "Original save exception changed"); }
            Check(closes == 0 && !policy.Request(worker), "Exceptional save retained close authority");
        });
        yield return ("The save requested by normal document close never queues another close", async () =>
        {
            var policy = new Policy(); var worker = new object(); var pending = Pending(); var closes = 0;
            var run = policy.Run(worker, false, () => pending.Task, () => worker, () => true, async () =>
            {
                closes++;
                await policy.Run(worker, true, () =>
                {
                    Check(!policy.Request(worker), "Close-triggered save acquired a standalone close intent");
                    return Task.FromResult(true);
                }, () => worker, () => true, () => throw new Exception("Nested close ran"));
            });
            Check(policy.Request(worker), "Standalone save could not queue close");
            pending.SetResult(true); await run;
            Check(closes == 1, "Close-triggered save duplicated the original close");
        });
        yield return ("A close callback failure does not resurrect or repeat the consumed close", async () =>
        {
            var policy = new Policy(); var worker = new object(); var pending = Pending(); var closes = 0;
            var run = policy.Run(worker, false, () => pending.Task, () => worker, () => true,
                () => { closes++; throw new InvalidOperationException("close callback"); });
            Check(policy.Request(worker), "Standalone save could not queue close");
            pending.SetResult(true);
            try { await run; throw new Exception("Close callback exception was swallowed"); }
            catch (InvalidOperationException e) { Check(e.Message == "close callback", "Close callback error changed"); }
            Check(closes == 1 && !policy.Request(worker), "Failed close callback was rearmed");
        });
    }
}
