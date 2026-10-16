using System.ComponentModel;
using System.Runtime.InteropServices;

namespace OpenGeul.Office;

internal static class SuiteWindowIcon
{
    internal static void Apply(Form form)
    {
        try
        {
            var icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
            if (icon is null) return;
            form.Disposed += (_, _) => icon.Dispose();
            form.Icon = icon;
        }
        catch (Exception e) when (e is ArgumentException or IOException or UnauthorizedAccessException or Win32Exception or ExternalException)
        {
            // An unavailable shell icon must not prevent a document from opening.
        }
    }
}
