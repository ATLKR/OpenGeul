using System.Drawing;

namespace OpenGeul.Office.Core;

public static class InitialWindowPlacement
{
    // Inputs are realized outer bounds and already DPI-scaled minimum sizes.
    public static (Rectangle Bounds, Size MinimumSize) Fit(Rectangle bounds, Size scaledMinimum, Rectangle workingArea)
    {
        if (workingArea.Width <= 0 || workingArea.Height <= 0)
            throw new ArgumentOutOfRangeException(nameof(workingArea));
        var minimum = new Size(Math.Min(scaledMinimum.Width, workingArea.Width), Math.Min(scaledMinimum.Height, workingArea.Height));
        var size = new Size(Math.Clamp(bounds.Width, minimum.Width, workingArea.Width), Math.Clamp(bounds.Height, minimum.Height, workingArea.Height));
        if (size == bounds.Size && workingArea.Contains(bounds)) return (bounds, minimum);
        var fitted = new Rectangle(workingArea.Left + (workingArea.Width - size.Width) / 2,
            workingArea.Top + (workingArea.Height - size.Height) / 2, size.Width, size.Height);
        return (fitted, minimum);
    }
}
