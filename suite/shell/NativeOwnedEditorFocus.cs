using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32.SafeHandles;
using OpenGeul.Office.Core;

namespace OpenGeul.Office;

/// <summary>One query/synchronize engine HANDLE retained for this attachment only.</summary>
internal sealed class NativeOwnedEditorFocus : IOwnedEditorFocusNative
{
    private readonly nint form, panel, child;
    private readonly uint shellThread, editorThread, enginePid;
    private readonly SafeProcessHandle engine;

    internal NativeOwnedEditorFocus(nint form, nint panel, nint child)
    {
        this.form = form; this.panel = panel; this.child = child;
        shellThread = GetWindowThreadProcessId(form, out var shellPid);
        editorThread = GetWindowThreadProcessId(child, out enginePid);
        if (shellPid != Environment.ProcessId || shellThread != GetCurrentThreadId() || editorThread == 0 || enginePid == 0)
            throw new InvalidOperationException("Embedded editor attachment has no owned native thread");
        engine = OpenProcess(0x00101000, false, enginePid); // SYNCHRONIZE | QUERY_LIMITED_INFORMATION
        if (engine.IsInvalid) { var error = Marshal.GetLastPInvokeError(); engine.Dispose(); throw new Win32Exception(error); }
    }

    private static EditorFocusProcess Process(nint handle)
    {
        var pid = GetProcessId(handle);
        if (pid == 0 || !GetProcessTimes(handle, out var creation, out _, out _, out _)) throw new Win32Exception(Marshal.GetLastPInvokeError());
        var image = new StringBuilder(32768); var length = (uint)image.Capacity;
        if (!QueryFullProcessImageName(handle, 0, image, ref length)) throw new Win32Exception(Marshal.GetLastPInvokeError());
        var wait = WaitForSingleObject(handle, 0);
        if (wait != 0 && wait != 258) throw new Win32Exception(Marshal.GetLastPInvokeError());
        return new(checked((int)pid), checked((long)(((ulong)creation.High << 32) | creation.Low)), image.ToString(), wait == 258);
    }

    private static EditorFocusWindow Window(nint hwnd)
    {
        var exists = hwnd != 0 && IsWindow(hwnd);
        var thread = exists ? GetWindowThreadProcessId(hwnd, out _) : 0;
        uint pid = 0; if (exists) GetWindowThreadProcessId(hwnd, out pid);
        var name = new StringBuilder(256);
        if (exists && GetClassName(hwnd, name, name.Capacity) == 0) throw new Win32Exception(Marshal.GetLastPInvokeError());
        return new(hwnd.ToInt64(), checked((int)pid), thread, exists ? GetAncestor(hwnd, 2).ToInt64() : 0,
            exists ? GetParent(hwnd).ToInt64() : 0, exists, exists && IsWindowVisible(hwnd), exists && IsWindowEnabled(hwnd), name.ToString());
    }

    private static GuiThreadInfo Gui(uint thread)
    {
        var info = new GuiThreadInfo { Size = checked((uint)Marshal.SizeOf<GuiThreadInfo>()) };
        if (!GetGUIThreadInfo(thread, ref info)) throw new Win32Exception(Marshal.GetLastPInvokeError());
        return info;
    }

    public EditorFocusSnapshot Observe()
    {
        if (engine.IsClosed || engine.IsInvalid) throw new ObjectDisposedException(nameof(NativeOwnedEditorFocus));
        var shell = Process(GetCurrentProcess()); var retainedEngine = Process(engine.DangerousGetHandle());
        if (retainedEngine.Pid != enginePid) throw new InvalidOperationException("Retained engine identity changed");
        var hostGui = Gui(shellThread); var editorGui = Gui(editorThread);
        bool Inside(nint hwnd) => hwnd == child || (hwnd != 0 && IsChild(child, hwnd));
        return new(shell, retainedEngine, Window(form), Window(panel), Window(child), Window(GetForegroundWindow()),
            Window(hostGui.Focus), Window(editorGui.Focus), Window(hostGui.Capture), Window(editorGui.Capture), GetCurrentThreadId(),
            true, hostGui.Flags | editorGui.Flags, IsChild(form, panel), IsChild(panel, child),
            Inside(hostGui.Focus), Inside(editorGui.Focus), GetProp(form, NativeWindowProperties.ParentProperty).ToInt64(),
            GetProp(form, NativeWindowProperties.ChildProperty).ToInt64());
    }

    public (long PreviousFocus, int Error) SetEditorFocus()
    {
        Marshal.SetLastPInvokeError(0);
        var previous = SetFocus(child);
        return (previous.ToInt64(), Marshal.GetLastPInvokeError());
    }

    public void Dispose() => engine.Dispose();

    [StructLayout(LayoutKind.Sequential)] private struct FileTime { internal uint Low, High; }
    [StructLayout(LayoutKind.Sequential)] private struct Rect { internal int Left, Top, Right, Bottom; }
    [StructLayout(LayoutKind.Sequential)] private struct GuiThreadInfo
    {
        internal uint Size, Flags;
        internal nint Active, Focus, Capture, MenuOwner, MoveSize, Caret;
        internal Rect CaretRect;
    }
    [DllImport("kernel32.dll", SetLastError = true)] private static extern SafeProcessHandle OpenProcess(uint access, [MarshalAs(UnmanagedType.Bool)] bool inherit, uint pid);
    [DllImport("kernel32.dll")] private static extern nint GetCurrentProcess();
    [DllImport("kernel32.dll")] private static extern uint GetCurrentThreadId();
    [DllImport("kernel32.dll", SetLastError = true)] private static extern uint GetProcessId(nint handle);
    [DllImport("kernel32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetProcessTimes(nint handle, out FileTime creation, out FileTime exit, out FileTime kernel, out FileTime user);
    [DllImport("kernel32.dll", EntryPoint = "QueryFullProcessImageNameW", CharSet = CharSet.Unicode, SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool QueryFullProcessImageName(nint handle, uint flags, StringBuilder image, ref uint size);
    [DllImport("kernel32.dll", SetLastError = true)] private static extern uint WaitForSingleObject(nint handle, uint milliseconds);
    [DllImport("user32.dll", SetLastError = true)] private static extern uint GetWindowThreadProcessId(nint hwnd, out uint pid);
    [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool IsWindow(nint hwnd);
    [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool IsWindowVisible(nint hwnd);
    [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool IsWindowEnabled(nint hwnd);
    [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool IsChild(nint parent, nint child);
    [DllImport("user32.dll")] private static extern nint GetParent(nint hwnd);
    [DllImport("user32.dll")] private static extern nint GetAncestor(nint hwnd, uint flags);
    [DllImport("user32.dll")] private static extern nint GetForegroundWindow();
    [DllImport("user32.dll", EntryPoint = "GetClassNameW", CharSet = CharSet.Unicode, SetLastError = true)] private static extern int GetClassName(nint hwnd, StringBuilder text, int capacity);
    [DllImport("user32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool GetGUIThreadInfo(uint thread, ref GuiThreadInfo info);
    [DllImport("user32.dll", EntryPoint = "GetPropW", CharSet = CharSet.Unicode)] private static extern nint GetProp(nint hwnd, string name);
    [DllImport("user32.dll", SetLastError = true)] private static extern nint SetFocus(nint hwnd);
}
