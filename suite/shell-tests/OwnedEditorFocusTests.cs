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
        bool Pending(OwnedEditorFocus route) => route.InitialFocusPending;
        bool Queue(OwnedEditorFocus route, Action<Action> post, Func<bool> available, Action<EditorFocusResult> completed) =>
            route.QueueInitialFocus(post, available, completed);
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
        yield return Test("Unavailable initial focus remains pending until a guarded activation", () =>
        {
            var native = new FocusNative(); using var route = new OwnedEditorFocus(native, "engine");
            var first = Initial(route, false);
            Check(!first.Verified && !first.Attempted && native.Sets == 0, "Unavailable initial focus was attempted");
            Check(Pending(route), "Inactive initial request was consumed");
            Check(Initial(route, true).Verified && native.Sets == 1 && !Pending(route), "Later guarded activation did not finish the initial request");
        });
        yield return Test("Foreign foreground keeps a stale owned control pending until one guarded activation", () =>
        {
            foreach (var available in new[] { false, true })
            {
                var native = new FocusNative(); using var route = new OwnedEditorFocus(native, "engine");
                var safe = native.State; var selected = safe.Panel with { Hwnd = 13, ClassName = "EDIT" };
                native.State = safe with { Focus = selected, EditorFocus = selected,
                    Foreground = safe.Foreground with { Hwnd = 90, Pid = 9, ThreadId = 99, Root = 90 } };
                for (var observation = 0; observation < 2; observation++)
                {
                    var result = Initial(route, available);
                    Check(!result.Verified && !result.Attempted && result.Before is not null &&
                        result.Reason == "initialPending" && Pending(route) && native.Sets == 0,
                        "Background owned control observation consumed the initial request");
                }
                native.State = safe;
                var callbacks = new List<Action>(); var reports = new List<EditorFocusResult>();
                Check(Queue(route, callbacks.Add, () => true, reports.Add), "Later activation could not queue the pending request");
                callbacks[0](); callbacks[0]();
                Check(reports.Count == 1 && reports[0].Verified && native.Sets == 1 && !Pending(route),
                    "Later activation was not a single verified initial handoff");
                Check(!Initial(route, true).Attempted && native.Sets == 1, "Initial handoff repeated after activation");
            }
        });
        yield return Test("Returning foreground to another selected owned control cancels without focus transfer", () =>
        {
            var native = new FocusNative(); using var route = new OwnedEditorFocus(native, "engine");
            var safe = native.State; var selected = safe.Panel with { Hwnd = 13, ClassName = "EDIT" };
            var activeSelection = safe with { Focus = selected, EditorFocus = selected };
            native.State = activeSelection with { Foreground = safe.Foreground with { Hwnd = 90, Pid = 9 } };
            Check(!Initial(route, false).Attempted && Pending(route) && native.Sets == 0,
                "Background selected control consumed the pending request");
            native.State = activeSelection;
            var result = Initial(route, true);
            Check(!result.Verified && !result.Attempted && !Pending(route) && native.Sets == 0,
                "Active selected control did not cancel the automatic handoff");
            native.State = safe;
            Check(!Initial(route, true).Attempted && native.Sets == 0, "Host return overwrote the selected control");
        });
        yield return Test("Foreign foreground never preserves an invalid original attachment", () =>
        {
            foreach (var mutate in new Func<EditorFocusSnapshot, EditorFocusSnapshot>[] {
                s => s with { Engine = s.Engine with { CreationTime = 201 } },
                s => s with { Child = s.Child with { ThreadId = 99 } },
                s => s with { RegisteredChild = 99 } })
            {
                var native = new FocusNative(); using var route = new OwnedEditorFocus(native, "engine");
                var safe = native.State; var selected = safe.Panel with { Hwnd = 13, ClassName = "EDIT" };
                native.State = mutate(safe with { Focus = selected, EditorFocus = selected,
                    Foreground = safe.Foreground with { Hwnd = 90, Pid = 9 } });
                var result = Initial(route, false);
                Check(!result.Verified && !result.Attempted && !Pending(route) && native.Sets == 0,
                    "Invalid attachment was preserved behind the foreground guard");
                native.State = safe;
                Check(!Initial(route, true).Attempted && native.Sets == 0, "Cancelled attachment was retried");
            }
        });
        yield return Test("Initial focus cancels replaced attachment or another selected control", () =>
        {
            var mutations = new Func<EditorFocusSnapshot, EditorFocusSnapshot>[] {
                s => s with { Engine = s.Engine with { CreationTime = 201 } },
                s => s with { Engine = s.Engine with { Pid = 99 } },
                s => s with { Engine = s.Engine with { Alive = false } },
                s => s with { Shell = s.Shell with { CreationTime = 99 } },
                s => s with { Child = s.Child with { ThreadId = 99 } },
                s => s with { Child = s.Child with { Exists = false } },
                s => s with { Focus = s.Panel with { Hwnd = 13, ClassName = "EDIT" },
                    EditorFocus = s.Panel with { Hwnd = 13, ClassName = "EDIT" } },
                s => s with { CurrentThread = 99 }, s => s with { RegisteredChild = 99 },
                s => s with { PanelOwnsChild = false }, s => s with { FormOwnsPanel = false } };
            foreach (var mutate in mutations)
            {
                var native = new FocusNative(); using var route = new OwnedEditorFocus(native, "engine");
                var safe = native.State; native.State = mutate(safe);
                var first = Initial(route, true);
                Check(!first.Verified && !first.Attempted && native.Sets == 0, "Unsafe initial context changed focus");
                Check(!Pending(route), "Cancelled original attachment retained an automatic request");
                native.State = safe;
                Check(!Initial(route, true).Attempted && native.Sets == 0, "Guarded initial request was retried");
            }
        });
        yield return Test("Initial focus waits without input through temporary unavailable GUI states", () =>
        {
            var mutations = new Func<EditorFocusSnapshot, EditorFocusSnapshot>[] {
                s => s with { Form = s.Form with { Enabled = false } },
                s => s with { Panel = s.Panel with { Visible = false } },
                s => s with { Foreground = s.Foreground with { Hwnd = 90, Pid = 9 } },
                s => s with { Foreground = s.Foreground with { ThreadId = 99 } },
                s => s with { Foreground = s.Foreground with { Root = 90 } },
                s => s with { Foreground = s.Foreground with { Enabled = false } },
                s => s with { Focus = s.Focus with { Hwnd = 90, Pid = 9, ThreadId = 9, Root = 90 },
                    EditorFocus = s.EditorFocus with { Hwnd = 90, Pid = 9, ThreadId = 9, Root = 90 } },
                s => s with { EditorFocus = s.Panel },
                s => s with { Capture = s.Panel }, s => s with { EditorCapture = s.Child },
                s => s with { GuiFlags = 4 }, s => s with { GuiQueriesSucceeded = false },
                s => s with { HostMenuOwner = s.Child.Hwnd }, s => s with { EditorMenuOwner = s.Child.Hwnd } };
            foreach (var mutate in mutations)
            {
                var native = new FocusNative(); using var route = new OwnedEditorFocus(native, "engine");
                var safe = native.State; native.State = mutate(safe);
                var first = Initial(route, true);
                Check(!first.Verified && !first.Attempted && native.Sets == 0 && Pending(route), "Temporary GUI state was consumed or changed");
                native.State = safe;
                Check(Initial(route, true).Verified && native.Sets == 1 && !Pending(route), "Guarded initial request did not finish");
            }
        });
        yield return Test("Failed initial native handoff never retries or qualifies an unobserved result", () =>
        {
            foreach (var mode in new[] { "unchanged", "generation", "foreground" })
            {
                var native = new FocusNative { MoveFocus = mode != "unchanged" };
                using var route = new OwnedEditorFocus(native, "engine");
                if (mode == "generation") native.AfterSet = s => s with { Engine = s.Engine with { CreationTime = 201 } };
                if (mode == "foreground") native.AfterSet = s => s with { Foreground = s.Foreground with { ThreadId = 99 } };
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
        yield return Test("Initial activation callbacks coalesce and recheck availability at execution", () =>
        {
            var native = new FocusNative(); using var route = new OwnedEditorFocus(native, "engine");
            var callbacks = new List<Action>(); var reports = new List<EditorFocusResult>(); var available = false;
            Check(Queue(route, callbacks.Add, () => available, reports.Add), "Initial callback was not queued");
            Check(!Queue(route, callbacks.Add, () => true, reports.Add) && callbacks.Count == 1 && native.Sets == 0, "Queued callbacks accumulated");
            available = true; callbacks[0]();
            Check(native.Sets == 1 && reports.Count == 1 && reports[0].Verified && !Pending(route), "Callback did not recheck the actual execution state");
            Check(!Queue(route, callbacks.Add, () => true, reports.Add) && callbacks.Count == 1, "Completed initial focus queued again");
        });
        yield return Test("App activation wakes one deferred initial request and coalesces with Activated", () =>
        {
            var native = new FocusNative(); using var route = new OwnedEditorFocus(native, "engine");
            var safe = native.State;
            native.State = safe with { Foreground = safe.Foreground with { Hwnd = 90, Pid = 9 } };
            var initial = Initial(route, false);
            Check(!initial.Attempted && Pending(route) && native.Sets == 0, "Inactive attach did not retain its request");
            native.State = safe;
            var callbacks = new List<Action>(); var reports = new List<EditorFocusResult>();
            Check(Queue(route, callbacks.Add, () => true, reports.Add), "App activation did not wake the pending request");
            Check(!Queue(route, callbacks.Add, () => true, reports.Add) && callbacks.Count == 1,
                "App activation and Activated created duplicate work");
            callbacks[0]();
            Check(native.Sets == 1 && reports.Count == 1 && reports[0].Verified && !Pending(route),
                "App activation did not complete one guarded initial handoff");
            Check(!Queue(route, callbacks.Add, () => true, reports.Add) && native.Sets == 1,
                "A completed app activation retried native focus");
        });
        yield return Test("The actual app activation entry fences the original owner and HWND after base processing", () =>
        {
            var source = FocusFormSource();
            var body = FocusHostMethod(source, "protected override void WndProc(ref Message m)");
            var processed = body.IndexOf("base.WndProc(ref m);", StringComparison.Ordinal);
            Check(processed >= 0 && body.IndexOf("var appActivated = m.Msg == 0x001C && m.WParam != 0;", StringComparison.Ordinal) is var active && active >= 0 && active < processed,
                "The original app activation message is not retained before base processing");
            foreach (var capture in new[] { "var activationHwnd = m.HWnd;", "var initialFocusOwner = editorFocus;" })
                Check(body.IndexOf(capture, StringComparison.Ordinal) is var at && at >= 0 && at < processed,
                    "The original app activation owner or HWND is not retained");
            var wake = body.IndexOf("if (appActivated", StringComparison.Ordinal);
            var queue = body.IndexOf("QueueInitialEditorFocus();", StringComparison.Ordinal);
            Check(wake > processed && queue > wake, "App activation queued focus before base processing");
            var guard = body[wake..queue];
            foreach (var condition in new[] { "initialFocusOwner is not null", "initialFocusOwner.InitialFocusPending",
                "ReferenceEquals(editorFocus, initialFocusOwner)", "!IsDisposed", "!Disposing", "IsHandleCreated",
                "activationHwnd == editorFocusFormHwnd", "activationHwnd == Handle" })
                Check(guard.Contains(condition, StringComparison.Ordinal), "App activation lost an original owner/lifetime guard");
            Check(guard.IndexOf("IsHandleCreated", StringComparison.Ordinal) < guard.IndexOf("activationHwnd == Handle", StringComparison.Ordinal),
                "App activation may create a missing HWND");
            Check(!body.Contains("LParam", StringComparison.Ordinal) && !body.Contains("SetFocus", StringComparison.Ordinal)
                && !body.Contains("SetForegroundWindow", StringComparison.Ordinal), "App activation bypassed the existing queue or interpreted its thread ID");
            var activated = FocusHostMethod(source, "protected override void OnActivated(EventArgs e)");
            Check(activated.IndexOf("base.OnActivated(e);", StringComparison.Ordinal) < activated.IndexOf("QueueInitialEditorFocus();", StringComparison.Ordinal),
                "The existing Activated entry changed ordering");
        });
        yield return Test("Inactive callback stays pending without an automatic polling loop", () =>
        {
            var native = new FocusNative(); using var route = new OwnedEditorFocus(native, "engine");
            var callbacks = new List<Action>(); var reports = new List<EditorFocusResult>();
            var safe = native.State;
            native.State = safe with { Foreground = safe.Foreground with { Hwnd = 90, Pid = 9 } };
            Check(Queue(route, callbacks.Add, () => false, reports.Add), "Inactive callback was not queued");
            callbacks[0]();
            Check(native.Sets == 0 && reports.Count == 1 && Pending(route) && callbacks.Count == 1, "Inactive callback changed focus or rescheduled itself");
            native.State = safe;
            Check(Queue(route, callbacks.Add, () => true, reports.Add) && callbacks.Count == 2, "Later activation was not admitted");
            callbacks[1]();
            Check(native.Sets == 1 && reports.Count == 2 && reports[1].Verified && !Pending(route), "Later activation did not complete exactly once");
        });
        yield return Test("Queued initial focus respects a newly selected owned control", () =>
        {
            var native = new FocusNative(); using var route = new OwnedEditorFocus(native, "engine");
            var callbacks = new List<Action>(); var reports = new List<EditorFocusResult>();
            Check(Queue(route, callbacks.Add, () => false, reports.Add), "Initial callback was not queued");
            var selected = native.State.Panel with { Hwnd = 13, ClassName = "EDIT" };
            native.State = native.State with { Focus = selected, EditorFocus = selected };
            callbacks[0]();
            Check(native.Sets == 0 && !Pending(route) && reports.Count == 1 && !reports[0].Attempted, "Selected owned control lost focus");
            Check(!Queue(route, callbacks.Add, () => true, reports.Add), "Cancelled initial request was queued again");
        });
        yield return Test("Queued initial callbacks retire after manual success disposal or replacement", () =>
        {
            foreach (var mode in new[] { "manual", "dispose", "replacement", "available-manual", "available-dispose" })
            {
                var native = new FocusNative(); using var route = new OwnedEditorFocus(native, "engine");
                var callbacks = new List<Action>(); var reports = new List<EditorFocusResult>();
                bool Available()
                {
                    if (mode == "available-dispose") route.Dispose();
                    if (mode == "available-manual") Check(route.Route(OwnedEditorFocus.CtrlF6, 10, true).Verified, "Manual readiness handoff did not complete");
                    return true;
                }
                Check(Queue(route, callbacks.Add, Available, reports.Add), "Initial callback was not queued");
                if (mode == "manual") Check(route.Route(OwnedEditorFocus.CtrlF6, 10, true).Verified, "Manual handoff did not complete");
                else if (mode == "dispose") route.Dispose();
                else if (mode == "replacement") native.State = native.State with { RegisteredChild = 99 };
                callbacks[0]();
                Check(native.Sets == (mode == "manual" || mode == "available-manual" ? 1 : 0) && !Pending(route), "Retired initial callback changed focus");
                Check(reports.Count == (mode == "replacement" ? 1 : 0), "Retired callback reported an unrelated operation");
                Check(!Queue(route, callbacks.Add, () => true, reports.Add), "Retired initial request was queued again");
            }
        });
        yield return Test("Initial queue remains occupied through callbacks and native reentrancy", () =>
        {
            var native = new FocusNative(); using var route = new OwnedEditorFocus(native, "engine");
            var callbacks = new List<Action>(); var reports = new List<EditorFocusResult>();
            bool Available()
            {
                Check(!Queue(route, callbacks.Add, () => true, reports.Add), "Reentrant readiness queued another callback");
                return true;
            }
            native.AfterSet = s =>
            {
                Check(!Queue(route, callbacks.Add, () => true, reports.Add), "Native callback queued another initial operation");
                return s;
            };
            Check(Queue(route, callbacks.Add, Available, reports.Add), "Initial callback was not queued");
            callbacks[0]();
            Check(native.Sets == 1 && reports.Count == 1 && reports[0].Verified && callbacks.Count == 1, "Reentrant initial callback changed cardinality");
        });
        yield return Test("Uncertain scheduling or callback errors cancel the pending initial operation", () =>
        {
            foreach (var mode in new[] { "schedule", "available", "completed" })
            {
                var native = new FocusNative(); using var route = new OwnedEditorFocus(native, "engine");
                var callbacks = new List<Action>(); var reports = new List<EditorFocusResult>();
                void Post(Action callback)
                {
                    callbacks.Add(callback);
                    if (mode == "schedule") throw new InvalidOperationException("Synthetic scheduling failure");
                }
                bool Available() => mode == "available" ? throw new InvalidOperationException("Synthetic callback failure") : true;
                void Completed(EditorFocusResult result)
                {
                    reports.Add(result);
                    if (mode == "completed") throw new InvalidOperationException("Synthetic reporting failure");
                }
                Check(Queue(route, Post, Available, Completed) == (mode != "schedule"), "Scheduling result was misreported");
                callbacks[0]();
                Check(!Pending(route) && native.Sets == (mode == "completed" ? 1 : 0), "Uncertain callback retained automatic focus");
                Check(!Queue(route, callbacks.Add, () => true, reports.Add), "Uncertain scheduling created another callback");
            }
        });
        foreach (var mode in new[] { "manual", "initial", "dispose" })
        {
            yield return Test("Initial observation stops after reentrant " + mode, () =>
            {
                var native = new FocusNative(); using var route = new OwnedEditorFocus(native, "engine");
                native.AfterObserve = observed =>
                {
                    native.AfterObserve = null;
                    if (mode == "manual") Check(route.Route(OwnedEditorFocus.CtrlF6, 10, true).Verified, "Reentrant manual handoff did not complete");
                    else if (mode == "initial") Check(Initial(route, true).Verified, "Reentrant initial handoff did not complete");
                    else route.Dispose();
                    return observed;
                };
                var result = Initial(route, true);
                Check(!result.Verified && !result.Attempted && native.Sets == (mode == "dispose" ? 0 : 1), "Stale initial observation touched focus after completion");
                Check(!Pending(route), "Completed initial observation became pending again");
            });
        }
        foreach (var initial in new[] { false, true })
        {
            yield return Test("Focus postcondition stops after lease disposal " + (initial ? "initial" : "manual"), () =>
            {
                var native = new FocusNative(); using var route = new OwnedEditorFocus(native, "engine");
                native.AfterSet = state =>
                {
                    native.AfterObserve = observed => { route.Dispose(); return observed; };
                    return state;
                };
                var result = initial ? Initial(route, true) : route.Route(OwnedEditorFocus.CtrlF6, 10, true);
                Check(!result.Verified && result.Attempted && native.Sets == 1 && native.Disposals == 1, "Disposed lease qualified a stale focus postcondition");
            });
        }
        yield return Test("Manual focus cannot use a lease disposed during its observation", () =>
        {
            var native = new FocusNative(); using var route = new OwnedEditorFocus(native, "engine");
            native.AfterObserve = observed => { route.Dispose(); return observed; };
            var result = route.Route(OwnedEditorFocus.CtrlF6, 10, true);
            Check(!result.Verified && !result.Attempted && native.Sets == 0 && native.Disposals == 1, "Manual focus used a disposed lease");
        });
        yield return Test("An agreed control in the exact active document cancels while transfer guards are blocked", () =>
        {
            var blocks = new Func<EditorFocusSnapshot, EditorFocusSnapshot>[] {
                s => s with { Capture = s.Focus }, s => s with { EditorCapture = s.EditorFocus },
                s => s with { HostMenuOwner = s.Child.Hwnd }, s => s with { EditorMenuOwner = s.Child.Hwnd },
                s => s with { Form = s.Form with { Enabled = false },
                    Foreground = s.Foreground with { Enabled = false } } };
            foreach (var block in blocks)
            {
                var native = new FocusNative(); using var route = new OwnedEditorFocus(native, "engine");
                var safe = native.State; var selected = safe.Panel with { Hwnd = 13, ClassName = "EDIT" };
                native.State = block(safe with { Focus = selected, EditorFocus = selected });
                var result = Initial(route, false);
                Check(!result.Verified && !result.Attempted && !Pending(route) && native.Sets == 0, "Selected control was left pending behind a transfer guard");
                native.State = safe;
                Check(!Initial(route, true).Attempted && native.Sets == 0, "Returning to the host overwrote the selected control");
            }
        });
    }

    private static string FocusFormSource([System.Runtime.CompilerServices.CallerFilePath] string path = "") =>
        System.IO.File.ReadAllText(System.IO.Path.Combine(System.IO.Path.GetDirectoryName(path)!, "../shell/OfficeDocumentForm.cs"));

    private static string FocusHostMethod(string source, string signature)
    {
        var begin = source.IndexOf('{', source.IndexOf(signature, StringComparison.Ordinal));
        var depth = 1;
        for (var end = begin + 1; end < source.Length; end++)
        {
            if (source[end] == '{') depth++;
            if (source[end] == '}' && --depth == 0) return source[(begin + 1)..end];
        }
        throw new Exception("Actual focus host method did not end");
    }
}

internal sealed class FocusNative : IOwnedEditorFocusNative
{
    internal EditorFocusSnapshot State = Initial();
    internal int Sets, Disposals, Error;
    internal long Previous = 10;
    internal bool MoveFocus = true;
    internal Func<EditorFocusSnapshot, EditorFocusSnapshot>? AfterSet;
    internal Func<EditorFocusSnapshot, EditorFocusSnapshot>? AfterObserve;
    private static EditorFocusSnapshot Initial()
    {
        EditorFocusWindow W(long hwnd, int pid, uint thread, long parent, string name) => new(hwnd, pid, thread, 10, parent, true, true, true, name);
        var form = W(10, 1, 3, 0, "Form"); var panel = W(11, 1, 3, 10, "Panel");
        var child = W(12, 2, 4, 11, "SALTMPSUBFRAME"); var zero = new EditorFocusWindow(0, 0, 0, 0, 0, false, false, false, "");
        return new(new(1, 100, "shell", true), new(2, 200, "engine", true), form, panel, child,
            form, form, form, zero, zero, 3, true, 0, true, true, false, false, 11, 12);
    }
    internal EditorFocusSnapshot Focused() => State with { Focus = State.Child, EditorFocus = State.Child, FocusWithinEditor = true, EditorFocusWithinEditor = true };
    public EditorFocusSnapshot Observe()
    {
        var observed = State;
        return AfterObserve is null ? observed : AfterObserve(observed);
    }
    public (long PreviousFocus, int Error) SetEditorFocus()
    {
        Sets++; if (MoveFocus) State = Focused(); if (AfterSet is not null) State = AfterSet(State);
        return (Previous, Error);
    }
    public void Dispose() => Disposals++;
}
