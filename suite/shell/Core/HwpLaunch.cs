using System.Diagnostics;

namespace OpenGeul.Office.Core;

public static class HwpLaunch
{
    public static ProcessStartInfo Create(string packageRoot, string? documentPath)
    {
        var hwpDirectory = Path.Combine(packageRoot, "HWP");
        var start = new ProcessStartInfo(Path.Combine(hwpDirectory, "OpenGeul.exe"))
        {
            UseShellExecute = false,
            WorkingDirectory = hwpDirectory
        };
        RuntimeEnvironment.PrependProgramDirectory(start, packageRoot);
        if (documentPath is not null) start.ArgumentList.Add(documentPath);
        return start;
    }
}
