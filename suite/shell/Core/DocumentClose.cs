using System.Text.Json;

namespace OpenGeul.Office.Core;

public sealed class SuiteException(string message, Exception? inner = null) : Exception(message, inner);
public sealed record DocumentStatus(bool Modified, string Title);
public enum CloseChoice { Save, Discard, Cancel }
public sealed record CloseResult(bool Closed, string? Error = null, string? Warning = null);
public interface IDocumentSession
{
    Task<DocumentStatus> StatusAsync();
    Task<DocumentStatus> PrepareCloseAsync();
    Task<CloseResult> CloseAsync(bool discard);
}

public static class DocumentClose
{
    public static CloseResult FromWorkerResult(JsonElement result)
    {
        bool IsTrue(string property) => result.ValueKind == JsonValueKind.Object
            && result.TryGetProperty(property, out var value) && value.ValueKind == JsonValueKind.True;
        if (!IsTrue("closed")) return new(false);
        if (result.TryGetProperty("closeCancelled", out var cancelled))
        {
            if (cancelled.ValueKind is not (JsonValueKind.True or JsonValueKind.False))
                throw new SuiteException("문서 닫기 취소 상태를 확인하지 못했습니다.");
            if (cancelled.ValueKind == JsonValueKind.True) return new(false);
        }
        if (IsTrue("cleanupVerified")) return new(true);
        var cleanupError = result.TryGetProperty("cleanupError", out var error) && error.ValueKind == JsonValueKind.String
            ? error.GetString() : null;
        var warning = "문서는 닫혔지만 문서 엔진의 정상 종료를 확인하지 못했습니다.";
        if (!string.IsNullOrWhiteSpace(cleanupError)) warning += "\n" + cleanupError;
        return new(true, Warning: warning);
    }

    public static async Task<CloseResult> TryAsync(IDocumentSession session, Func<Task<CloseChoice>> choose, Func<Task<bool>> save)
    {
        try
        {
            var status = await session.PrepareCloseAsync();
            var discard = false;
            if (status.Modified)
            {
                switch (await choose())
                {
                    case CloseChoice.Cancel: return new(false);
                    case CloseChoice.Save:
                        if (!await save()) return new(false);
                        break;
                    case CloseChoice.Discard: discard = true; break;
                    default: return new(false);
                }
            }
            var result = await session.CloseAsync(discard);
            return result.Closed || result.Error is not null ? result
                : result with { Error = "문서가 변경되어 닫기가 취소되었습니다. 저장하거나 버리기를 선택해 주세요." };
        }
        catch (Exception e)
        {
            return new(false, $"문서를 닫지 못했습니다. 문서 창을 유지합니다.\n{e.Message}");
        }
    }
}
