using System.Diagnostics;

namespace OpenGeul.Office.Core;

public static class WorkerLaunch
{
    public static ProcessStartInfo Create(string packageRoot)
    {
        var runtime = Path.Combine(packageRoot, "Office");
        var program = Path.Combine(runtime, "program");
        var core = Path.Combine(program, "python-core-3.13.15");
        // The pinned LibreOffice launcher starts another console Python process.
        // Start its fixed interpreter directly so WorkerClient's no-window flag applies to it.
        var start = new ProcessStartInfo(Path.Combine(core, "bin", "python.exe"))
        {
            WorkingDirectory = packageRoot,
            ArgumentList = { "-u", Path.Combine(packageRoot, "worker", "office_worker.py"), "--runtime", runtime }
        };
        start.Environment["PYTHONDONTWRITEBYTECODE"] = "1";
        start.Environment["PYTHONIOENCODING"] = "utf-8";
        if (!start.Environment.ContainsKey("UNO_PATH")) start.Environment["UNO_PATH"] = program;
        if (!start.Environment.ContainsKey("URE_BOOTSTRAP"))
            start.Environment["URE_BOOTSTRAP"] = "vnd.sun.star.pathname:" + Path.Combine(program, "fundamental.ini");
        start.Environment["PYTHONHOME"] = core;
        start.Environment.TryGetValue("PYTHONPATH", out var inheritedPythonPath);
        var pythonPath = string.Join(Path.PathSeparator, program, Path.Combine(core, "lib"), Path.Combine(core, "lib", "site-packages"));
        start.Environment["PYTHONPATH"] = string.IsNullOrEmpty(inheritedPythonPath)
            ? pythonPath : pythonPath + Path.PathSeparator + inheritedPythonPath;
        RuntimeEnvironment.PrependProgramDirectory(start, packageRoot);
        return start;
    }
}
