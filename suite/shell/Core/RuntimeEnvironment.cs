using System.Diagnostics;

namespace OpenGeul.Office.Core;

internal static class RuntimeEnvironment
{
    internal static void PrependProgramDirectory(ProcessStartInfo start, string packageRoot)
    {
        start.Environment.TryGetValue("PATH", out var inheritedPath);
        var program = Path.Combine(packageRoot, "Office", "program");
        start.Environment["PATH"] = string.IsNullOrEmpty(inheritedPath)
            ? program
            : program + Path.PathSeparator + inheritedPath;
    }
}
