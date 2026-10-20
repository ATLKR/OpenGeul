using OpenGeul.Office.Core;

namespace OpenGeul.Office;

internal static class InitialWindowLayout
{
    internal static void Apply(Form form)
    {
        if (form.WindowState != FormWindowState.Normal) return;
        var placement = InitialWindowPlacement.Fit(form.Bounds, form.MinimumSize, Screen.FromHandle(form.Handle).WorkingArea);
        // Lower an oversized minimum before applying the outer bounds.
        if (form.MinimumSize != placement.MinimumSize) form.MinimumSize = placement.MinimumSize;
        if (form.Bounds != placement.Bounds) form.Bounds = placement.Bounds;
    }
}
