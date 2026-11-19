namespace OpenGeul.Office.Core;

/// <summary>Bounded cached-only diagnostic. It never authorizes input or a launch.</summary>
public sealed class HwpCommandRouteObservation(object owner, int generation)
{
    public const int CountCap = 65535, AttemptCap = 16;
    private sealed record CountSequence(int Count, long LastSequence);
    private CountSequence received = new(0, 0), enqueueReturned = new(0, 0), execute = new(0, 0);
    private int overflowMask, updateFailureMask, ownerMismatch;

    public void Observe(int stage, long sequence, object? currentOwner, int currentGeneration)
    {
        if (!ReferenceEquals(owner, currentOwner) || generation is < 1 or > 128 || currentGeneration != generation)
        { Interlocked.Exchange(ref ownerMismatch, 1); return; }
        if (sequence <= 0 || stage is < 1 or > 3) { MarkUpdateFailure(stage); return; }
        switch (stage)
        {
            case 1: Update(ref received, sequence, stage); break;
            case 2: Update(ref enqueueReturned, sequence, stage); break;
            case 3: Update(ref execute, sequence, stage); break;
        }
    }

    public void MarkUpdateFailure(int stage) => Interlocked.Or(ref updateFailureMask,
        stage is >= 1 and <= 3 ? 1 << (stage - 1) : 8);

    private void Update(ref CountSequence slot, long sequence, int stage)
    {
        for (var attempt = 0; attempt < AttemptCap; attempt++)
        {
            var before = Volatile.Read(ref slot);
            if (before.Count == CountCap) { Interlocked.Or(ref overflowMask, 1 << (stage - 1)); return; }
            var next = new CountSequence(before.Count + 1, sequence);
            if (ReferenceEquals(Interlocked.CompareExchange(ref slot, next, before), before)) return;
        }
        MarkUpdateFailure(stage);
    }

    public HwpCommandRouteSnapshot Snapshot()
    {
        var receivedBefore = Volatile.Read(ref received);
        var enqueueBefore = Volatile.Read(ref enqueueReturned);
        var executeBefore = Volatile.Read(ref execute);
        var overflowBefore = Volatile.Read(ref overflowMask);
        var failedBefore = Volatile.Read(ref updateFailureMask);
        var mismatchBefore = Volatile.Read(ref ownerMismatch);
        var receivedAfter = Volatile.Read(ref received);
        var enqueueAfter = Volatile.Read(ref enqueueReturned);
        var executeAfter = Volatile.Read(ref execute);
        var overflowAfter = Volatile.Read(ref overflowMask);
        var failedAfter = Volatile.Read(ref updateFailureMask);
        var mismatchAfter = Volatile.Read(ref ownerMismatch);
        var stable = ReferenceEquals(receivedBefore, receivedAfter) &&
            ReferenceEquals(enqueueBefore, enqueueAfter) && ReferenceEquals(executeBefore, executeAfter) &&
            overflowBefore == overflowAfter && failedBefore == failedAfter && mismatchBefore == mismatchAfter;
        var status = !stable ? 3 : (overflowAfter | failedAfter | mismatchAfter) != 0 ? 2 : 1;
        return new(status, generation, overflowAfter, failedAfter, mismatchAfter,
            stable ? receivedAfter.Count : 0, stable ? receivedAfter.LastSequence : 0,
            stable ? enqueueAfter.Count : 0, stable ? enqueueAfter.LastSequence : 0,
            stable ? executeAfter.Count : 0, stable ? executeAfter.LastSequence : 0);
    }
}

public sealed record HwpCommandRouteSnapshot(int StatusCode, int OwnerGeneration, int OverflowMask,
    int UpdateFailureMask, int OwnerMismatch, int ReceivedCount, long ReceivedLastSequence,
    int EnqueueReturnedCount, long EnqueueReturnedLastSequence, int ExecuteCount, long ExecuteLastSequence);
