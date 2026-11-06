using OpenGeul.Office.Core;

internal static class OwnedEditorFocusTests
{
    internal static IEnumerable<(string Name, Func<Task> Run)> Cases()
    {
        void Check(bool value, string message) { if (!value) throw new Exception(message); }
        (string, Func<Task>) Test(string name, Action body) => (name, () => { body(); return Task.CompletedTask; });
        yield return Test("CtrlF6 routes host focus exactly once and verifies actual editor focus", () =>
        {
            var native = new FocusNative(); using var route = new OwnedEditorFocus(native, "engine");
            var result = route.Route(OwnedEditorFocus.CtrlF6, 10, true);
            Check(result.Verified && result.Attempted && native.Sets == 1, "Host route did not make one verified handoff");
        });
        yield return Test("CtrlF6 accepts NULL previous focus only with measured postcondition", () =>
        {
            var native = new FocusNative { Previous = 0, Error = 5 }; using var route = new OwnedEditorFocus(native, "engine");
            var result = route.Route(OwnedEditorFocus.CtrlF6, 11, true);
            Check(result.Verified && result.PreviousFocus == 0 && result.NativeError == 5, "NULL return was misclassified");
        });
        yield return Test("CtrlF6 cannot claim native delivery when target focus did not change", () =>
        {
            var native = new FocusNative { MoveFocus = false }; using var route = new OwnedEditorFocus(native, "engine");
            var result = route.Route(OwnedEditorFocus.CtrlF6, 10, true);
            Check(!result.Verified && result.Attempted && native.Sets == 1, "Unverified SetFocus was accepted");
        });
        yield return Test("CtrlF6 leaves an already focused exact editor unchanged", () =>
        {
            var native = new FocusNative(); using var route = new OwnedEditorFocus(native, "engine");
            native.State = native.Focused();
            var result = route.Route(OwnedEditorFocus.CtrlF6, 10, true);
            Check(result.Verified && !result.Attempted && native.Sets == 0, "Already focused editor was changed");
        });
        yield return Test("CtrlF6 cannot verify inconsistent host and editor GUI focus observations", () =>
        {
            foreach (var afterSet in new[] { false, true })
            {
                var native = new FocusNative(); using var route = new OwnedEditorFocus(native, "engine");
                EditorFocusSnapshot Inconsistent(EditorFocusSnapshot s) => s with
                { Focus = s.Form with { Hwnd = 13, ClassName = "EDIT" }, FocusWithinEditor = false };
                if (afterSet) native.AfterSet = Inconsistent; else native.State = Inconsistent(native.Focused());
                var result = route.Route(OwnedEditorFocus.CtrlF6, 10, true);
                Check(!result.Verified && native.Sets == (afterSet ? 1 : 0), "Inconsistent GUI focus was verified");
            }
        });
        yield return Test("CtrlF6 refuses unavailable documents and unrelated chords or message windows", () =>
        {
            foreach (var (key, hwnd, available) in new[] { (OwnedEditorFocus.CtrlF6, 10L, false),
                (OwnedEditorFocus.CtrlF6 | 0x10000, 10L, true), (OwnedEditorFocus.CtrlF6, 12L, true), (0x75, 10L, true) })
            {
                var native = new FocusNative(); using var route = new OwnedEditorFocus(native, "engine");
                Check(!route.Route(key, hwnd, available).Verified && native.Sets == 0, "Unrelated or unavailable route touched focus");
            }
        });
        yield return Test("CtrlF6 rejects generation ownership modal capture and input-control changes before focus", () =>
        {
            var mutations = new Func<EditorFocusSnapshot, EditorFocusSnapshot>[] {
                s => s with { Engine = s.Engine with { CreationTime = 201 } },
                s => s with { Engine = s.Engine with { Pid = 99 } },
                s => s with { Engine = s.Engine with { Alive = false } },
                s => s with { Shell = s.Shell with { CreationTime = 99 } },
                s => s with { Child = s.Child with { ThreadId = 99 } },
                s => s with { Child = s.Child with { Exists = false } },
                s => s with { Form = s.Form with { Enabled = false } },
                s => s with { Panel = s.Panel with { Visible = false } },
                s => s with { Foreground = s.Foreground with { Hwnd = 90 } },
                s => s with { Focus = s.Focus with { Hwnd = 13, ClassName = "EDIT" } },
                s => s with { Capture = s.Panel }, s => s with { EditorCapture = s.Child },
                s => s with { GuiFlags = 4 }, s => s with { GuiQueriesSucceeded = false },
                s => s with { CurrentThread = 99 }, s => s with { RegisteredChild = 99 },
                s => s with { PanelOwnsChild = false }, s => s with { FormOwnsPanel = false } };
            foreach (var mutate in mutations)
            {
                var native = new FocusNative(); using var route = new OwnedEditorFocus(native, "engine");
                native.State = mutate(native.State);
                var result = route.Route(OwnedEditorFocus.CtrlF6, 10, true);
                Check(!result.Verified && !result.Attempted && native.Sets == 0, "Unsafe context changed focus");
                Check(result.Before is not null, "Rejected fresh snapshot was lost");
            }
        });
        yield return Test("CtrlF6 rejects post-handoff generation replacement without a second call", () =>
        {
            var native = new FocusNative(); using var route = new OwnedEditorFocus(native, "engine");
            native.AfterSet = s => s with { Engine = s.Engine with { CreationTime = 201 } };
            var result = route.Route(OwnedEditorFocus.CtrlF6, 10, true);
            Check(!result.Verified && result.Attempted && native.Sets == 1 && result.After is not null, "Replacement was accepted or retried");
        });
        yield return Test("CtrlF6 closes retained native lease on failed admission and exactly once on dispose", () =>
        {
            var bad = new FocusNative(); bad.State = bad.State with { Engine = bad.State.Engine with { CreationTime = 99 } };
            var rejected = false;
            try { using var route = new OwnedEditorFocus(bad, "engine"); } catch (InvalidOperationException) { rejected = true; }
            Check(rejected && bad.Disposals == 1, "Failed admission leaked its native lease");
            var native = new FocusNative(); var good = new OwnedEditorFocus(native, "engine"); good.Dispose(); good.Dispose();
            Check(native.Disposals == 1 && !good.Route(OwnedEditorFocus.CtrlF6, 10, true).Attempted, "Lease disposal was not idempotent");
        });
        EditorFocusResult Initial(OwnedEditorFocus route, bool available) => route.TryInitialFocus(available);
        EditorFocusSnapshot MenuOwner(EditorFocusSnapshot snapshot, bool editor) => editor ?
            snapshot with { EditorMenuOwner = snapshot.Child.Hwnd } : snapshot with { HostMenuOwner = snapshot.Child.Hwnd };
        yield return Test("Initial focus hands off the exact form or panel only once", () =>
        {
            foreach (var panel in new[] { false, true })
            {
                var native = new FocusNative();
                if (panel) native.State = native.State with { Focus = native.State.Panel, EditorFocus = native.State.Panel };
                using var route = new OwnedEditorFocus(native, "engine");
                var first = Initial(route, true);
                Check(first.Verified && first.Attempted && native.Sets == 1, "Initial handoff was not independently verified");
                Check(!Initial(route, true).Attempted && native.Sets == 1, "Initial handoff was repeated");
            }
        });
        yield return Test("Initial focus preserves the editor and leaves explicit CtrlF6 available", () =>
        {
            var native = new FocusNative(); using var route = new OwnedEditorFocus(native, "engine");
            var host = native.State; native.State = native.Focused();
            var first = Initial(route, true);
            Check(first.Verified && !first.Attempted && native.Sets == 0, "Focused editor was changed");
            native.State = host;
            Check(!Initial(route, true).Attempted && native.Sets == 0, "Initial request was retried after already focused");
            Check(route.Route(OwnedEditorFocus.CtrlF6, 10, true).Verified && native.Sets == 1, "Explicit keyboard route was disabled");
        });
        yield return Test("Unavailable initial focus is consumed without a deferred retry", () =>
        {
            var native = new FocusNative(); using var route = new OwnedEditorFocus(native, "engine");
            var first = Initial(route, false);
            Check(!first.Verified && !first.Attempted && native.Sets == 0, "Unavailable initial focus was attempted");
            Check(!Initial(route, true).Attempted && native.Sets == 0, "Unavailable initial request was retried");
        });
        yield return Test("Initial focus rejects unsafe contexts without a later automatic retry", () =>
        {
            var mutations = new Func<EditorFocusSnapshot, EditorFocusSnapshot>[] {
                s => s with { Engine = s.Engine with { CreationTime = 201 } },
                s => s with { Engine = s.Engine with { Pid = 99 } },
                s => s with { Engine = s.Engine with { Alive = false } },
                s => s with { Shell = s.Shell with { CreationTime = 99 } },
                s => s with { Child = s.Child with { ThreadId = 99 } },
                s => s with { Child = s.Child with { Exists = false } },
                s => s with { Form = s.Form with { Enabled = false } },
                s => s with { Panel = s.Panel with { Visible = false } },
                s => s with { Foreground = s.Foreground with { Hwnd = 90 } },
                s => s with { Focus = s.Focus with { Hwnd = 13, ClassName = "EDIT" } },
                s => s with { EditorFocus = s.Panel },
                s => s with { Capture = s.Panel }, s => s with { EditorCapture = s.Child },
                s => s with { GuiFlags = 4 }, s => s with { GuiQueriesSucceeded = false },
                s => s with { CurrentThread = 99 }, s => s with { RegisteredChild = 99 },
                s => s with { PanelOwnsChild = false }, s => s with { FormOwnsPanel = false } };
            foreach (var mutate in mutations)
            {
                var native = new FocusNative(); using var route = new OwnedEditorFocus(native, "engine");
                var safe = native.State; native.State = mutate(safe);
                var first = Initial(route, true);
                Check(!first.Verified && !first.Attempted && native.Sets == 0, "Unsafe initial context changed focus");
                native.State = safe;
                Check(!Initial(route, true).Attempted && native.Sets == 0, "Guarded initial request was retried");
            }
        });
        yield return Test("Failed initial native handoff never retries or qualifies an unobserved result", () =>
        {
            foreach (var changedGeneration in new[] { false, true })
            {
                var native = new FocusNative { MoveFocus = changedGeneration };
                using var route = new OwnedEditorFocus(native, "engine");
                if (changedGeneration) native.AfterSet = s => s with { Engine = s.Engine with { CreationTime = 201 } };
                var first = Initial(route, true);
                Check(!first.Verified && first.Attempted && first.After is not null && native.Sets == 1, "Failed initial handoff qualified");
                Check(!Initial(route, true).Attempted && native.Sets == 1, "Failed initial handoff was repeated");
            }
        });
        yield return Test("Both focus entries reject either native menu owner before and after handoff", () =>
        {
            foreach (var initial in new[] { false, true })
            foreach (var editor in new[] { false, true })
            foreach (var afterSet in new[] { false, true })
            {
                var native = new FocusNative(); using var route = new OwnedEditorFocus(native, "engine");
                if (afterSet) native.AfterSet = s => MenuOwner(s, editor); else native.State = MenuOwner(native.State, editor);
                var result = initial ? Initial(route, true) : route.Route(OwnedEditorFocus.CtrlF6, 10, true);
                Check(!result.Verified && result.Attempted == afterSet && native.Sets == (afterSet ? 1 : 0), "Menu owner was ignored");
            }
        });
        yield return Test("Initial focus consumes its one shot before a reentrant native callback", () =>
        {
            var native = new FocusNative(); using var route = new OwnedEditorFocus(native, "engine");
            native.AfterSet = s =>
            {
                Check(!Initial(route, true).Attempted && native.Sets == 1, "Reentrant initial handoff was repeated");
                return s;
            };
            Check(Initial(route, true).Verified && native.Sets == 1, "Reentrant initial handoff lost the original result");
        });
        yield return Test("Disposed initial focus cannot reopen the retained lease", () =>
        {
            var native = new FocusNative(); var route = new OwnedEditorFocus(native, "engine"); route.Dispose();
            Check(!Initial(route, true).Attempted && !Initial(route, true).Attempted && native.Sets == 0, "Disposed lease changed focus");
            route.Dispose(); Check(native.Disposals == 1, "Initial focus changed disposal ownership");
        });
        yield return Test("Initial native failures retain only a fixed diagnostic reason", () =>
        {
            var native = new FocusNative(); using var route = new OwnedEditorFocus(native, "engine");
            native.AfterSet = _ => throw new InvalidOperationException("SYNTHETIC-UNRELATED-DETAIL");
            var result = Initial(route, true);
            Check(!result.Verified && result.Attempted && result.Reason == "initialHandoffUnverified", "Initial reason was not fixed");
        });
    }
}

internal sealed class FocusNative : IOwnedEditorFocusNative
{
    internal EditorFocusSnapshot State = Initial();
    internal int Sets, Disposals, Error;
    internal long Previous = 10;
    internal bool MoveFocus = true;
    internal Func<EditorFocusSnapshot, EditorFocusSnapshot>? AfterSet;
    private static EditorFocusSnapshot Initial()
    {
        EditorFocusWindow W(long hwnd, int pid, uint thread, long parent, string name) => new(hwnd, pid, thread, 10, parent, true, true, true, name);
        var form = W(10, 1, 3, 0, "Form"); var panel = W(11, 1, 3, 10, "Panel");
        var child = W(12, 2, 4, 11, "SALTMPSUBFRAME"); var zero = new EditorFocusWindow(0, 0, 0, 0, 0, false, false, false, "");
        return new(new(1, 100, "shell", true), new(2, 200, "engine", true), form, panel, child,
            form, form, form, zero, zero, 3, true, 0, true, true, false, false, 11, 12);
    }
    internal EditorFocusSnapshot Focused() => State with { Focus = State.Child, EditorFocus = State.Child, FocusWithinEditor = true, EditorFocusWithinEditor = true };
    public EditorFocusSnapshot Observe() => State;
    public (long PreviousFocus, int Error) SetEditorFocus()
    {
        Sets++; if (MoveFocus) State = Focused(); if (AfterSet is not null) State = AfterSet(State);
        return (Previous, Error);
    }
    public void Dispose() => Disposals++;
}
