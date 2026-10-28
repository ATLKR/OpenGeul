#nullable enable
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text.Json;
using System.Threading.Tasks;
using OpenGeul.Office.Core;

// Runs only against an explicitly supplied built package, before physical input.
// This new query-only HANDLE admission proves the ephemeral probe's generation;
// it is not the original launch HANDLE or a Calc engine retirement witness.
public static class WorkerRuntimeDiagnostic
{
    const double Seconds = 30;
    const uint QueryAndSynchronize = 0x00101000;
    const uint Pending = 258;
    const string Marker = "한글 & $ 계약";
    static readonly string[] BooleanFields = {
        "consoleAbsent", "interpreterVerified", "prefixVerified", "unoOriginsVerified",
        "unoContextVerified", "architectureVerified", "utf8Verified", "unicodeRoundTrip"
    };

    const string Probe = """
import ctypes
from ctypes import wintypes as W
import encodings
import json
import os
from pathlib import Path
import sys
import sysconfig

sys.stdin.reconfigure(encoding='utf-8', errors='strict')
sys.stdout.reconfigure(encoding='utf-8', errors='strict', line_buffering=True)
kernel = ctypes.WinDLL('kernel32', use_last_error=True)
kernel.GetCurrentProcess.argtypes = []
kernel.GetCurrentProcess.restype = W.HANDLE
kernel.GetProcessTimes.argtypes = [W.HANDLE, *(ctypes.POINTER(W.FILETIME),) * 4]
kernel.GetProcessTimes.restype = W.BOOL
kernel.GetConsoleWindow.argtypes = []
kernel.GetConsoleWindow.restype = W.HWND
times = [W.FILETIME() for _ in range(4)]
assert kernel.GetProcessTimes(kernel.GetCurrentProcess(), *(ctypes.byref(t) for t in times))
created = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
line = sys.stdin.readline(4097)
assert line.endswith('\n') and len(line.encode('utf-8')) <= 4096
request = json.loads(line)
assert type(request) is dict and set(request) == {'id', 'command', 'args'}
assert type(request['id']) is int and request['id'] > 0
assert request['command'] == 'inspect' and type(request['args']) is dict
assert set(request['args']) == {'marker'}
suite = Path(sys.argv[1])
program = suite / 'Office' / 'program'
core = program / 'python-core-3.13.15'
def same(left, right):
    return os.path.normcase(os.path.realpath(left)) == os.path.normcase(os.path.realpath(right))
import uno
import pyuno
context = uno.getComponentContext()
result = dict(pid=os.getpid(), creationTime=created,
    consoleAbsent=not bool(kernel.GetConsoleWindow()),
    interpreterVerified=same(sys.executable, core / 'bin' / 'python.exe'),
    prefixVerified=same(sys.prefix, core) and same(sys.base_prefix, core),
    unoOriginsVerified=same(uno.__file__, program / 'uno.py') and same(pyuno.__file__, program / 'pyuno.pyd')
        and same(encodings.__file__, core / 'lib' / 'encodings' / '__init__.py'),
    unoContextVerified=context is not None,
    architectureVerified=ctypes.sizeof(ctypes.c_void_p) == 8 and
        sysconfig.get_platform() == {'x64': 'win-amd64', 'arm64': 'win-arm64'}[sys.argv[2]],
    utf8Verified=sys.stdin.encoding.lower() == sys.stdout.encoding.lower() == 'utf-8',
    unicodeRoundTrip=request['args']['marker'] == '한글 & $ 계약')
sys.stdout.write(json.dumps(dict(id=request['id'], ok=True, result=result), ensure_ascii=False) + '\n')
sys.stdout.flush()
# Normal exit follows this single response; no EOF/forced cleanup is needed.
""";

    public static async Task<int> RunAsync(string[] args)
    {
        var clock = Stopwatch.StartNew();
        WorkerClient? client = null;
        nint handle = 0;
        bool admitted = false, released = false, disposed = false, normalExit = false;
        bool protocolVerified = false, consoleAbsent = false, valid = false;
        TimeSpan Remaining()
        {
            var remaining = TimeSpan.FromSeconds(Seconds) - clock.Elapsed;
            Require(remaining > TimeSpan.Zero);
            return remaining;
        }
        try
        {
            Require(args.Length == 5 && args[0] == "--worker-runtime-probe" && args[1] == "--suite"
                && args[3] == "--architecture" && args[4] is "x64" or "arm64");
            var architecture = args[4];
            var expected = architecture == "x64" ? Architecture.X64 : Architecture.Arm64;
            Require(OperatingSystem.IsWindows() && IntPtr.Size == 8
                && RuntimeInformation.OSArchitecture == expected && RuntimeInformation.ProcessArchitecture == expected);
            var suite = args[2];
            Require(Path.IsPathFullyQualified(suite) && !suite.StartsWith(@"\\", StringComparison.Ordinal)
                && string.Equals(Path.GetFullPath(suite), suite, StringComparison.OrdinalIgnoreCase));
            for (var part = new DirectoryInfo(suite); part is not null; part = part.Parent)
                Require(part.Exists && (part.Attributes & FileAttributes.ReparsePoint) == 0);
            var start = WorkerLaunch.Create(suite);
            start.ArgumentList.Clear();
            foreach (var argument in new[] { "-u", "-c", Probe, suite, architecture }) start.ArgumentList.Add(argument);
            Remaining();
            client = WorkerClient.Start(start, Remaining());
            // The constant child waits for this controller's first request.
            handle = OpenProcess(QueryAndSynchronize, false, checked((uint)client.ProcessId));
            Require(handle != 0);
            admitted = true;
            Require(GetProcessId(handle) == client.ProcessId && WaitForSingleObject(handle, 0) == Pending);
            var created = Creation(handle);
            Remaining();
            var result = await client.SendAsync("inspect", new { marker = Marker }, Remaining());
            Remaining();
            Require(result.ValueKind == JsonValueKind.Object);
            var properties = result.EnumerateObject().Select(p => p.Name).ToArray();
            Require(properties.Length == BooleanFields.Length + 2
                && properties.Distinct(StringComparer.Ordinal).Count() == properties.Length
                && new HashSet<string>(properties, StringComparer.Ordinal).SetEquals(BooleanFields.Append("pid").Append("creationTime")));
            Require(result.GetProperty("pid").GetUInt32() == GetProcessId(handle)
                && result.GetProperty("pid").GetUInt32() == client.ProcessId
                && result.GetProperty("creationTime").GetUInt64() == created && Creation(handle) == created);
            consoleAbsent = result.GetProperty("consoleAbsent").ValueKind == JsonValueKind.True;
            Require(BooleanFields.All(field => result.GetProperty(field).ValueKind == JsonValueKind.True));
            protocolVerified = true;
            while (true)
            {
                Remaining();
                var wait = WaitForSingleObject(handle, 0);
                if (wait == 0) break;
                Require(wait == Pending);
                await Task.Delay(TimeSpan.FromMilliseconds(Math.Min(10, Remaining().TotalMilliseconds)));
            }
            Require(GetExitCodeProcess(handle, out var exitCode) && exitCode == 0 && Creation(handle) == created);
            normalExit = true;
            Remaining();
            valid = true;
        }
        catch (Exception) { valid = false; } // No native paths, environment values or raw failures leave this probe.
        finally
        {
            if (client is not null)
            {
                try { await client.DisposeAsync(); disposed = true; }
                catch (Exception) { valid = false; }
            }
            if (handle != 0)
            {
                released = CloseHandle(handle);
                if (!released) valid = false;
            }
        }
        bool withinDeadline = clock.Elapsed < TimeSpan.FromSeconds(Seconds);
        bool success = valid && admitted && released && disposed && protocolVerified && normalExit && withinDeadline;
        Console.WriteLine(JsonSerializer.Serialize(new {
            schemaVersion = 1, success, consoleAbsent, protocolVerified, normalExitObserved = normalExit,
            retainedHandleAdmitted = admitted, retainedHandleReleased = released, clientDisposed = disposed, withinDeadline
        }));
        return success ? 0 : 1;
    }

    static void Require(bool condition) { if (!condition) throw new InvalidOperationException(); }
    static ulong Creation(nint handle)
    {
        Require(GetProcessTimes(handle, out var created, out _, out _, out _));
        var value = ((ulong)created.High << 32) | created.Low;
        Require(value > 0);
        return value;
    }
    [StructLayout(LayoutKind.Sequential)]
    struct FileTime { public uint Low, High; }
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern nint OpenProcess(uint access, [MarshalAs(UnmanagedType.Bool)] bool inherit, uint pid);
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern uint GetProcessId(nint handle);
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern uint WaitForSingleObject(nint handle, uint milliseconds);
    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    static extern bool GetProcessTimes(nint handle, out FileTime created, out FileTime exited, out FileTime kernel, out FileTime user);
    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    static extern bool GetExitCodeProcess(nint handle, out uint exitCode);
    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    static extern bool CloseHandle(nint handle);
}
