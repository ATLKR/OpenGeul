namespace OpenGeul.Office.Core;

public sealed record DocumentMenuFocusState(bool Attached, bool WorkerAvailable,
    bool Loading, bool Busy, bool Closing, bool CloseApproved,
    bool FormAlive, bool FormVisible, bool FormEnabled, bool FormActive,
    bool MenuOwned, bool MenuAlive, bool MenuVisible, bool MenuEnabled, bool MenuCanFocus);

public static class OwnedDocumentMenuFocus
{
    public static bool OnOpening(int currentThreadId, int uiThreadId,
        Func<DocumentMenuFocusState> observe, Func<bool> focus)
    {
        // Do not inspect WinForms controls from another thread, even to reject them.
        if (currentThreadId <= 0 || currentThreadId != uiThreadId) return false;
        var state = observe();
        if (!state.Attached || !state.WorkerAvailable || state.Loading || state.Busy ||
            state.Closing || state.CloseApproved || !state.FormAlive || !state.FormVisible ||
            !state.FormEnabled || !state.FormActive || !state.MenuOwned || !state.MenuAlive ||
            !state.MenuVisible || !state.MenuEnabled || !state.MenuCanFocus) return false;
        return focus();
    }
}
