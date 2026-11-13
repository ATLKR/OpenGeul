using OpenGeul.Office.Core;

internal static class OwnedDocumentMenuFocusTests
{
    internal static IEnumerable<(string Name, Func<Task> Run)> Cases()
    {
        void Check(bool value, string message) { if (!value) throw new Exception(message); }
        (string, Func<Task>) Test(string name, Action body) => (name, () => { body(); return Task.CompletedTask; });
        yield return Test("File opening focuses the owned active document menu exactly once", () =>
        {
            var observations = 0; var focusCalls = 0;
            var focused = OwnedDocumentMenuFocus.OnOpening(7, 7,
                () => { observations++; return Ready(); }, () => { focusCalls++; return true; });
            Check(focused && observations == 1 && focusCalls == 1, "Genuine opening did not make one menu focus request");
        });
        yield return Test("File opening rejects another or missing UI thread before observing controls", () =>
        {
            foreach (var (current, owner) in new[] { (8, 7), (0, 7), (0, 0), (7, 0) })
            {
                var observed = false; var focusCalls = 0;
                var focused = OwnedDocumentMenuFocus.OnOpening(current, owner,
                    () => { observed = true; return Ready(); }, () => { focusCalls++; return true; });
                Check(!focused && !observed && focusCalls == 0, "A non-owner thread inspected controls or changed focus");
            }
        });
        yield return Test("File opening leaves unavailable inactive detached and foreign menus untouched", () =>
        {
            var states = new[] {
                Ready() with { Attached = false }, Ready() with { WorkerAvailable = false },
                Ready() with { Loading = true }, Ready() with { Busy = true },
                Ready() with { Closing = true }, Ready() with { CloseApproved = true },
                Ready() with { FormAlive = false }, Ready() with { FormVisible = false },
                Ready() with { FormEnabled = false }, Ready() with { FormActive = false },
                Ready() with { MenuOwned = false }, Ready() with { MenuAlive = false },
                Ready() with { MenuVisible = false }, Ready() with { MenuEnabled = false },
                Ready() with { MenuCanFocus = false }
            };
            foreach (var state in states)
            {
                var focusCalls = 0;
                var focused = OwnedDocumentMenuFocus.OnOpening(7, 7, () => state,
                    () => { focusCalls++; return true; });
                Check(!focused && focusCalls == 0, "An unavailable document or unowned menu changed focus");
            }
        });
        yield return Test("File opening preserves a failed focus result without retry", () =>
        {
            var focusCalls = 0;
            var focused = OwnedDocumentMenuFocus.OnOpening(7, 7, Ready,
                () => { focusCalls++; return false; });
            Check(!focused && focusCalls == 1, "Failed menu focus was retried or reported successful");
        });
    }

    private static DocumentMenuFocusState Ready() => new(true, true, false, false, false, false,
        true, true, true, true, true, true, true, true, true);
}
