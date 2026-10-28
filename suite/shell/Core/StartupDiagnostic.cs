using System.ComponentModel;
using System.Text.Json;

namespace OpenGeul.Office.Core;

public enum StartupPhase : byte { WorkerLaunch = 1, WorkerReply = 2, ShellAttach = 3 }

// These values form a versioned, closed numeric contract. Never derive them from
// exception text, paths, HRESULTs, or arbitrary worker-supplied strings.
public enum StartupReason : ushort
{
    Unknown = 0,
    InvalidRequest = 1, InvalidJson = 2, RequestTooLarge = 3, UnknownCommand = 4,
    InvalidState = 5, InvalidPath = 6, UnsupportedModule = 7, UnsupportedFormat = 8,
    InvalidManifest = 9, CloseCancelled = 10, EngineError = 11, EngineExited = 12,
    ConnectTimeout = 13, RuntimeMissing = 14, UiBootstrapFailed = 15,
    UiStyleIsolationFailed = 16, NewDatabaseFailed = 17, UnoUnavailable = 18,
    AttachFailed = 19, AccessibilityFailed = 20, OpenFailed = 21, CloseFailed = 22,
    SaveFailed = 23, CleanupPending = 24, UnsupportedPlatform = 25,
    InvalidWindow = 26, EmbeddingFailed = 27,
    ProcessStartFailed = 32, RequestTimeout = 33, WorkerDisconnected = 34,
    WorkerProtocol = 35, WorkerCommunication = 36, ShellAttachFailed = 37, NativeFailure = 38
}

public readonly record struct StartupDiagnostic(StartupPhase Phase, StartupReason Reason, uint NativeCode = 0)
{
    public const string PropertyName = "OpenGeul.Office.StartupDiagnosticV1";
    public static bool Enabled => Environment.GetEnvironmentVariable("OPENGEUL_SUITE_NUMERIC_NOTICE") == "1";

    // Positive UInt64: bit63=0, version56..62=1, phase48..55, reason32..47,
    // allowlisted Win32 native code0..31. The property value is an integer,
    // never an allocated buffer or handle.
    public ulong Packed => (1UL << 56)
        | ((ulong)(Enum.IsDefined(Phase) ? Phase : StartupPhase.ShellAttach) << 48)
        | ((ulong)(Enum.IsDefined(Reason) ? Reason : StartupReason.Unknown) << 32)
        | KnownNativeCode(NativeCode);

    public static uint KnownNativeCode(long code) => code is 2 or 3 or 5 or 8 or 14 or 32 or 87 or 126 or 127 or 193 or 216 or 740
        ? (uint)code : 0;

    public static StartupDiagnostic FromWorkerCode(string? code) => new(StartupPhase.WorkerReply, code switch
    {
        "invalid_request" => StartupReason.InvalidRequest,
        "invalid_json" => StartupReason.InvalidJson,
        "request_too_large" => StartupReason.RequestTooLarge,
        "unknown_command" => StartupReason.UnknownCommand,
        "invalid_state" => StartupReason.InvalidState,
        "invalid_path" => StartupReason.InvalidPath,
        "unsupported_module" => StartupReason.UnsupportedModule,
        "unsupported_format" => StartupReason.UnsupportedFormat,
        "invalid_manifest" => StartupReason.InvalidManifest,
        "close_cancelled" => StartupReason.CloseCancelled,
        "engine_error" => StartupReason.EngineError,
        "engine_exited" => StartupReason.EngineExited,
        "connect_timeout" => StartupReason.ConnectTimeout,
        "runtime_missing" => StartupReason.RuntimeMissing,
        "ui_bootstrap_failed" => StartupReason.UiBootstrapFailed,
        "ui_style_isolation_failed" => StartupReason.UiStyleIsolationFailed,
        "new_database_failed" => StartupReason.NewDatabaseFailed,
        "uno_unavailable" => StartupReason.UnoUnavailable,
        "attach_failed" => StartupReason.AttachFailed,
        "accessibility_failed" => StartupReason.AccessibilityFailed,
        "open_failed" => StartupReason.OpenFailed,
        "close_failed" => StartupReason.CloseFailed,
        "save_failed" => StartupReason.SaveFailed,
        "cleanup_pending" => StartupReason.CleanupPending,
        "unsupported_platform" => StartupReason.UnsupportedPlatform,
        "invalid_window" => StartupReason.InvalidWindow,
        "embedding_failed" => StartupReason.EmbeddingFailed,
        _ => StartupReason.Unknown
    });

    public static StartupDiagnostic FromException(Exception error, StartupPhase phase)
    {
        for (Exception? current = error; current is not null; current = current.InnerException)
            if (current is SuiteException { StartupDiagnostic: { } diagnostic }) return diagnostic;
        if (error.InnerException is { } inner)
        {
            var original = FromException(inner, phase);
            if (original.Reason != StartupReason.Unknown) return original;
        }
        return error switch
        {
            Win32Exception native => new(phase, StartupReason.NativeFailure, KnownNativeCode(native.NativeErrorCode)),
            OperationCanceledException or TimeoutException => new(phase, StartupReason.RequestTimeout),
            JsonException => new(phase, StartupReason.WorkerProtocol),
            EndOfStreamException => new(phase, StartupReason.WorkerDisconnected),
            IOException => new(phase, StartupReason.WorkerCommunication),
            _ => new(phase, StartupReason.Unknown)
        };
    }
}
