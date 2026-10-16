namespace OpenGeul.Office.Core;

public sealed class SuiteException(string message, Exception? inner = null) : Exception(message, inner);
public sealed record DocumentStatus(bool Modified, string Title);
public enum CloseChoice { Save, Discard, Cancel }
public sealed record CloseResult(bool Closed, string? Error = null);
public interface IDocumentSession
{
    Task<DocumentStatus> StatusAsync();
    Task<bool> CloseAsync(bool discard);
}

public static class DocumentClose
{
    public static async Task<CloseResult> TryAsync(IDocumentSession session, Func<Task<CloseChoice>> choose, Func<Task<bool>> save)
    {
        try
        {
            var status = await session.StatusAsync();
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
            var closed = await session.CloseAsync(discard);
            return new(closed, closed ? null : "문서가 변경되어 닫기가 취소되었습니다. 저장하거나 버리기를 선택해 주세요.");
        }
        catch (Exception e)
        {
            return new(false, $"문서를 닫지 못했습니다. 문서 창을 유지합니다.\n{e.Message}");
        }
    }
}
