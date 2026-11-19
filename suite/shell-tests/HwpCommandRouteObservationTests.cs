using OpenGeul.Office.Core;

// Synthetic only: these tests do not instantiate WinForms or qualify real input.
public static class HwpCommandRouteObservationTests
{
    public static IEnumerable<(string Name, Func<Task> Run)> Cases()
    {
        yield return ("HWP route CallbackBeforeReturn preserves original sequence", CallbackBeforeReturn);
        yield return ("HWP route GuardedOrEnqueueFailure remains partial", GuardedOrEnqueueFailure);
        yield return ("HWP route ObserverFailure is sticky and separate", ObserverFailure);
        yield return ("HWP route OwnerMismatch never adopts a replacement", OwnerMismatch);
        yield return ("HWP route Overflow never wraps a pair", Overflow);
        yield return ("HWP route ConcurrentPairSnapshot never tears count and sequence", ConcurrentPairSnapshot);
        yield return ("HWP route ConcurrentWriters remain bounded or explicitly unknown", ConcurrentWriters);
    }

    private static void Require(bool condition)
    {
        if (!condition) throw new Exception("Synthetic HWP route contract failed");
    }

    private static Task CallbackBeforeReturn()
    {
        var owner = new object(); var observer = new HwpCommandRouteObservation(owner, 1);
        observer.Observe(1, 42, owner, 1); observer.Observe(3, 42, owner, 1);
        var before = observer.Snapshot();
        Require(before.StatusCode == 1 && before.ExecuteCount == 1 && before.EnqueueReturnedCount == 0);
        observer.Observe(2, 42, owner, 1);
        var after = observer.Snapshot();
        Require(after.StatusCode == 1 && after.ReceivedLastSequence == 42 &&
            after.EnqueueReturnedLastSequence == 42 && after.ExecuteLastSequence == 42);
        // Existing thread-pool command arrival may reorder sequence values.
        observer.Observe(1, 40, owner, 1);
        Require(observer.Snapshot().ReceivedLastSequence == 40);
        return Task.CompletedTask;
    }

    private static Task GuardedOrEnqueueFailure()
    {
        var owner = new object(); var observer = new HwpCommandRouteObservation(owner, 1);
        observer.Observe(1, 1, owner, 1);
        var enqueueFailure = observer.Snapshot();
        Require(enqueueFailure.ReceivedCount == 1 && enqueueFailure.EnqueueReturnedCount == 0 && enqueueFailure.ExecuteCount == 0);
        observer.Observe(2, 1, owner, 1);
        var callbackGuard = observer.Snapshot();
        Require(callbackGuard.EnqueueReturnedCount == 1 && callbackGuard.ExecuteCount == 0);
        return Task.CompletedTask;
    }

    private static Task ObserverFailure()
    {
        var owner = new object(); var observer = new HwpCommandRouteObservation(owner, 1);
        observer.Observe(1, 0, owner, 1);
        observer.MarkUpdateFailure(2);
        observer.Observe(3, 1, owner, 1);
        Require(observer.Snapshot().StatusCode == 2 && observer.Snapshot().UpdateFailureMask == 3);
        var invalid = new HwpCommandRouteObservation(owner, 1);
        invalid.Observe(0, 1, owner, 1);
        Require(invalid.Snapshot().UpdateFailureMask == 8);
        return Task.CompletedTask;
    }

    private static Task OwnerMismatch()
    {
        var owner = new object(); var observer = new HwpCommandRouteObservation(owner, 1);
        observer.Observe(1, 1, owner, 1);
        observer.Observe(2, 1, new object(), 1);
        observer.Observe(3, 1, owner, 2);
        var value = observer.Snapshot();
        Require(value.StatusCode == 2 && value.OwnerMismatch == 1 && value.EnqueueReturnedCount == 0 && value.ExecuteCount == 0);
        return Task.CompletedTask;
    }

    private static Task Overflow()
    {
        var owner = new object(); var observer = new HwpCommandRouteObservation(owner, 1);
        for (var count = 1; count <= HwpCommandRouteObservation.CountCap; count++) observer.Observe(1, count, owner, 1);
        Require(observer.Snapshot().ReceivedCount == 65535 && observer.Snapshot().StatusCode == 1);
        observer.Observe(1, 65536, owner, 1);
        var value = observer.Snapshot();
        Require(value.StatusCode == 2 && value.OverflowMask == 1 && value.ReceivedCount == 65535 && value.ReceivedLastSequence == 65535);
        return Task.CompletedTask;
    }

    private static async Task ConcurrentPairSnapshot()
    {
        var owner = new object(); var observer = new HwpCommandRouteObservation(owner, 1);
        using var begin = new ManualResetEventSlim(false);
        var writer = Task.Run(() =>
        {
            begin.Wait();
            for (var count = 1; count <= 4096; count++) observer.Observe(1, count, owner, 1);
        });
        begin.Set();
        for (var sample = 0; sample < 4096; sample++)
        {
            var value = observer.Snapshot();
            Require(value.StatusCode is 1 or 3);
            if (value.StatusCode == 1) Require(value.ReceivedCount == value.ReceivedLastSequence);
            else Require(value.ReceivedCount == 0 && value.ReceivedLastSequence == 0);
        }
        await writer;
        Require(observer.Snapshot().ReceivedCount == 4096);
    }

    private static async Task ConcurrentWriters()
    {
        var owner = new object(); var observer = new HwpCommandRouteObservation(owner, 1);
        var writers = Enumerable.Range(0, 8).Select(writer => Task.Run(() =>
        {
            for (var count = 1; count <= 256; count++) observer.Observe(1, writer * 256L + count, owner, 1);
        })).ToArray();
        await Task.WhenAll(writers);
        var value = observer.Snapshot();
        Require(value.ReceivedCount is > 0 and <= 2048 && value.ReceivedLastSequence is > 0 and <= 2048);
        Require(value.StatusCode == 1 ? value.ReceivedCount == 2048 : value.StatusCode == 2 && value.UpdateFailureMask == 1);
    }
}
