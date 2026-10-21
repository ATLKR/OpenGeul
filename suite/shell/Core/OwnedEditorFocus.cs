namespace OpenGeul.Office.Core;

public sealed record EditorFocusProcess(int Pid, long CreationTime, string Image, bool Alive);
public sealed record EditorFocusWindow(long Hwnd, int Pid, uint ThreadId, long Root, long Parent,
    bool Exists, bool Visible, bool Enabled, string ClassName);
public sealed record EditorFocusSnapshot(EditorFocusProcess Shell, EditorFocusProcess Engine,
    EditorFocusWindow Form, EditorFocusWindow Panel, EditorFocusWindow Child,
    EditorFocusWindow Foreground, EditorFocusWindow Focus, EditorFocusWindow EditorFocus,
    EditorFocusWindow Capture, EditorFocusWindow EditorCapture, uint CurrentThread,
    bool GuiQueriesSucceeded, uint GuiFlags, bool FormOwnsPanel, bool PanelOwnsChild,
    bool FocusWithinEditor, bool EditorFocusWithinEditor, long RegisteredPanel, long RegisteredChild);
public sealed record EditorFocusResult(bool Verified, bool Attempted, string Reason,
    EditorFocusSnapshot? Before, EditorFocusSnapshot? After, long PreviousFocus, int NativeError);

/// <summary>A retained engine lease; Observe must never reopen a PID.</summary>
public interface IOwnedEditorFocusNative : IDisposable
{
    EditorFocusSnapshot Observe();
    (long PreviousFocus, int Error) SetEditorFocus();
}

public sealed class OwnedEditorFocus : IDisposable
{
    public const int CtrlF6 = 0x20075;
    private readonly IOwnedEditorFocusNative native;
    private readonly EditorFocusSnapshot original;
    private bool disposed;

    public OwnedEditorFocus(IOwnedEditorFocusNative native, string expectedEngineImage)
    {
        this.native = native;
        try
        {
            original = native.Observe();
            if (!original.Shell.Alive || !original.Engine.Alive || original.Shell.Pid <= 0 ||
                original.Engine.Pid <= 0 || original.Engine.Pid == original.Shell.Pid ||
                original.Shell.CreationTime <= 0 || original.Engine.CreationTime < original.Shell.CreationTime ||
                !string.Equals(Path.GetFullPath(original.Engine.Image), Path.GetFullPath(expectedEngineImage), StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("Embedded editor process admission failed");
            Validate(original);
        }
        catch { native.Dispose(); throw; }
    }

    private void Validate(EditorFocusSnapshot s)
    {
        if (s.Shell != original.Shell || s.Engine != original.Engine || !s.Shell.Alive || !s.Engine.Alive)
            throw new InvalidOperationException("Embedded editor process generation changed");
        void Window(EditorFocusWindow value, EditorFocusWindow initial, int pid)
        {
            if (value.Hwnd <= 0 || value.Hwnd != initial.Hwnd || value.Pid != pid || value.ThreadId == 0 ||
                value.ThreadId != initial.ThreadId || value.Root != original.Form.Hwnd || value.Parent != initial.Parent ||
                value.ClassName != initial.ClassName || !value.Exists || !value.Visible || !value.Enabled)
                throw new InvalidOperationException("Embedded editor window ownership or readiness changed");
        }
        Window(s.Form, original.Form, s.Shell.Pid); Window(s.Panel, original.Panel, s.Shell.Pid);
        Window(s.Child, original.Child, s.Engine.Pid);
        if (s.Form.ThreadId != s.Panel.ThreadId || s.CurrentThread != s.Form.ThreadId ||
            s.Panel.Parent != s.Form.Hwnd || s.Child.Parent != s.Panel.Hwnd || s.Child.ClassName != "SALTMPSUBFRAME" ||
            !s.FormOwnsPanel || !s.PanelOwnsChild || s.RegisteredPanel != s.Panel.Hwnd || s.RegisteredChild != s.Child.Hwnd)
            throw new InvalidOperationException("Embedded editor attachment changed");
    }

    private void Ready(EditorFocusSnapshot s)
    {
        Validate(s);
        if (!s.GuiQueriesSucceeded || (s.GuiFlags & 0x1e) != 0 || s.Capture.Hwnd != 0 || s.EditorCapture.Hwnd != 0 ||
            s.Foreground.Hwnd != s.Form.Hwnd || s.Foreground.Pid != s.Shell.Pid || !s.Foreground.Exists)
            throw new InvalidOperationException("Document is not the active capture-free editor host");
        if (s.Focus.Hwnd != s.EditorFocus.Hwnd || s.Focus.Pid != s.EditorFocus.Pid ||
            s.Focus.ThreadId != s.EditorFocus.ThreadId || s.Focus.Root != s.EditorFocus.Root ||
            s.FocusWithinEditor != s.EditorFocusWithinEditor)
            throw new InvalidOperationException("Host and editor GUI focus observations do not agree");
    }

    private static bool EditorFocused(EditorFocusSnapshot s) =>
        s.FocusWithinEditor && s.Focus.Exists && s.EditorFocusWithinEditor && s.EditorFocus.Exists && s.EditorFocus.Pid == s.Engine.Pid &&
        s.EditorFocus.ThreadId == s.Child.ThreadId && s.EditorFocus.Root == s.Form.Hwnd;

    public EditorFocusResult Route(int keyData, long messageHwnd, bool available)
    {
        EditorFocusSnapshot? before = null, after = null;
        var attempted = false; long previous = 0; var error = 0;
        if (disposed || !available || keyData != CtrlF6 || (messageHwnd != original.Form.Hwnd && messageHwnd != original.Panel.Hwnd))
            return new(false, false, "notApplicable", null, null, 0, 0);
        try
        {
            before = native.Observe(); Ready(before);
            if (EditorFocused(before)) return new(true, false, "alreadyFocused", before, null, 0, 0);
            if (!before.Focus.Exists || before.Focus.Pid != before.Shell.Pid || before.Focus.ThreadId != before.Form.ThreadId ||
                before.Focus.Root != before.Form.Hwnd || (before.Focus.Hwnd != before.Form.Hwnd && before.Focus.Hwnd != before.Panel.Hwnd))
                throw new InvalidOperationException("CtrlF6 requires exact document form or host panel focus");
            attempted = true;
            (previous, error) = native.SetEditorFocus();
            after = native.Observe(); Ready(after);
            if (!EditorFocused(after)) throw new InvalidOperationException("Native editor focus handoff was not observed");
            return new(true, true, "editorFocused", before, after, previous, error);
        }
        catch (Exception e)
        {
            return new(false, attempted, e.Message, before, after, previous, error);
        }
    }

    public void Dispose()
    {
        if (disposed) return;
        disposed = true; native.Dispose();
    }
}
