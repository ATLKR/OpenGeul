using System.Text.Json;

namespace OpenGeul.Office.Core;

/// <summary>Admit only the native menu of this document's original attachment.</summary>
public sealed class DocumentMenuSurface
{
    private readonly string module;
    private readonly long parentHwnd, childHwnd;

    public DocumentMenuSurface(string module, long parentHwnd, long childHwnd)
    {
        if (module is not ("writer" or "calc" or "impress" or "draw" or "math" or "base"))
            throw new ArgumentException("An Office document module is required.", nameof(module));
        if (parentHwnd <= 0 || childHwnd <= 0 || parentHwnd == childHwnd)
            throw new ArgumentException("Distinct owned parent and child handles are required.");
        this.module = module;
        this.parentHwnd = parentHwnd;
        this.childHwnd = childHwnd;
    }

    public bool IsReady(JsonElement status)
    {
        try
        {
            if (status.ValueKind != JsonValueKind.Object) return false;
            var seen = 0;
            foreach (var property in status.EnumerateObject())
            {
                var bit = property.Name switch
                {
                    "nativeMenuReady" => 1, "module" => 2, "parentHwnd" => 4, "childHwnd" => 8, _ => 0
                };
                if ((seen & bit) != 0) return false;
                seen |= bit;
            }
            if (seen != 15) return false;
            var reportedModule = status.GetProperty("module");
            var parent = status.GetProperty("parentHwnd");
            var child = status.GetProperty("childHwnd");
            return status.GetProperty("nativeMenuReady").ValueKind == JsonValueKind.True
                && reportedModule.ValueKind == JsonValueKind.String && reportedModule.GetString() == module
                && parent.ValueKind == JsonValueKind.Number && parent.TryGetInt64(out var reportedParent) && reportedParent == parentHwnd
                && child.ValueKind == JsonValueKind.Number && child.TryGetInt64(out var reportedChild) && reportedChild == childHwnd;
        }
        catch (InvalidOperationException) { return false; }
    }

    public void RequireReady(JsonElement status)
    {
        if (!IsReady(status))
            throw new SuiteException("문서의 통합 메뉴를 연결할 수 없습니다. 문서 세션을 종료해야 합니다.",
                startupDiagnostic: new(StartupPhase.ShellAttach, StartupReason.ShellAttachFailed));
    }

    public void ObserveStatus(JsonElement status, bool updateDocumentStatus, Action<JsonElement> applyDocumentStatus)
    {
        RequireReady(status);
        if (updateDocumentStatus) applyDocumentStatus(status);
    }

    public static async Task<bool> CloseAndShowHomeAsync(Func<Task<bool>> close, Action showHome)
    {
        if (!await close()) return false;
        showHome();
        return true;
    }
}
