using System.Diagnostics;

namespace OpenGeul.Office.Core;

public static class WorkerLaunch
{
    public static ProcessStartInfo Create(string packageRoot)
    {
        var runtime = Path.Combine(packageRoot, "Office");
        var start = new ProcessStartInfo(Path.Combine(runtime, "program", "python.exe"))
        {
            WorkingDirectory = packageRoot,
            ArgumentList = { "-u", Path.Combine(packageRoot, "worker", "office_worker.py"), "--runtime", runtime }
        };
        start.Environment["PYTHONDONTWRITEBYTECODE"] = "1";
        start.Environment["PYTHONIOENCODING"] = "utf-8";
        RuntimeEnvironment.PrependProgramDirectory(start, packageRoot);
        return start;
    }
}
